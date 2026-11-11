"""Root-managed lifecycle for Feclora remote image repositories.

Repository definitions contain paths and credential references only. Secret
material remains in separately provisioned root-owned files and is never
accepted from a Cockpit request or copied into the repository registry.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from feclora.storage.repository import RemoteRepository, RepositoryError, required_tools


REGISTRY = Path("/etc/feclora/repositories.json")
MOUNT_ROOT = Path("/var/lib/feclora/repositories")
_REPOSITORY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_SUPPORTED = {"sshfs", "nfs", "smb"}


class RepositoryManagerError(RuntimeError):
    """A managed repository operation failed safely."""


def _private_directory(path: Path, *, create: bool, owner_uid: int = 0) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RepositoryManagerError(f"repository state directory is unavailable: {path}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or info.st_mode & 0o022):
        raise RepositoryManagerError(f"repository state directory is not root-owned or is group/other-writable: {path}")


def _read_registry(path: Path = REGISTRY, *, owner_uid: int = 0) -> dict[str, dict[str, Any]]:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RepositoryManagerError(f"cannot inspect repository registry: {exc}") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or info.st_mode & 0o077 or info.st_size > 256 * 1024):
        raise RepositoryManagerError("repository registry must be a private root-owned regular file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != owner_uid
                or opened.st_mode & 0o077
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
            raise RepositoryManagerError("repository registry changed during inspection")
        raw = os.read(fd, 256 * 1024 + 1)
    finally:
        os.close(fd)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RepositoryManagerError("repository registry is malformed") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "repositories"}:
        raise RepositoryManagerError("repository registry has an invalid schema")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise RepositoryManagerError("unsupported repository registry version")
    repositories = value["repositories"]
    if not isinstance(repositories, dict) or len(repositories) > 128:
        raise RepositoryManagerError("repository registry has an invalid repository collection")
    for identifier, definition in repositories.items():
        if not isinstance(identifier, str) or not _REPOSITORY_ID.fullmatch(identifier):
            raise RepositoryManagerError("repository registry contains an invalid identifier")
        if not isinstance(definition, dict):
            raise RepositoryManagerError("repository registry contains an invalid definition")
    return repositories


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registry field")
        result[key] = value
    return result


def _write_registry(repositories: dict[str, dict[str, Any]], path: Path = REGISTRY, *, owner_uid: int = 0) -> None:
    _private_directory(path.parent, create=True, owner_uid=owner_uid)
    fd, temporary = tempfile.mkstemp(prefix=".repositories-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "repositories": repositories},
                      stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _check_secret_reference(path: str | None, label: str, *, private: bool = True, owner_uid: int = 0) -> None:
    """Validate a credential path without following symlinks or trusting a stale stat.

    Open with O_NOFOLLOW and validate the descriptor itself. This closes the
    lstat/open symlink-swap window and ensures the file actually consumed by
    the privileged mount helper is a root-owned regular file with safe modes.
    """
    if path is None:
        return
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RepositoryManagerError(f"{label} is unavailable or is not a regular non-symlink file") from exc
    try:
        info = os.fstat(fd)
        unsafe_mode = bool(info.st_mode & (0o077 if private else 0o022))
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                or unsafe_mode or info.st_nlink != 1):
            requirement = "mode 0600 or stricter" if private else "not group/other-writable"
            raise RepositoryManagerError(
                f"{label} must be a root-owned regular file with {requirement} and no hard links"
            )
    finally:
        os.close(fd)


def _repository(identifier: str, definition: dict[str, Any], *, owner_uid: int = 0) -> RemoteRepository:
    if not _REPOSITORY_ID.fullmatch(identifier):
        raise RepositoryManagerError("repository identifier is invalid")
    required = {
        "provider", "host", "remote_path", "username", "credential_file",
        "identity_file", "known_hosts_file", "port", "read_only",
    }
    if set(definition) != required:
        raise RepositoryManagerError("repository definition has missing or unknown fields")
    try:
        repo = RemoteRepository(
            provider=definition["provider"], host=definition["host"],
            remote_path=definition["remote_path"],
            mountpoint=str(MOUNT_ROOT / identifier),
            username=definition["username"],
            credential_file=definition["credential_file"],
            identity_file=definition["identity_file"],
            known_hosts_file=definition["known_hosts_file"],
            port=definition["port"],
            read_only=definition["read_only"],
        )
    except (RepositoryError, TypeError) as exc:
        raise RepositoryManagerError(f"invalid repository definition: {exc}") from exc
    if repo.provider not in _SUPPORTED:
        raise RepositoryManagerError("unsupported managed repository provider")
    if repo.provider == "sshfs":
        _check_secret_reference(repo.identity_file, "SSH private key", owner_uid=owner_uid)
        _check_secret_reference(repo.known_hosts_file, "SSH known_hosts", private=False, owner_uid=owner_uid)
    if repo.provider == "smb":
        _check_secret_reference(repo.credential_file, "SMB credentials file", owner_uid=owner_uid)
    return repo


class RemoteRepositoryManager:
    """Manage supported SSHFS, NFS and SMB mounts."""

    def __init__(
        self, *, registry: Path = REGISTRY, mount_root: Path = MOUNT_ROOT,
        runner: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] | None = None,
        effective_uid: Callable[[], int] | None = None,
        owner_uid: int = 0, credential_root: Path = Path("/etc/credstore.encrypted/feclora"),
    ) -> None:
        self.registry = Path(registry)
        self.mount_root = Path(mount_root)
        self.runner = runner or subprocess.run
        self.which = which or shutil.which
        self.effective_uid = effective_uid or os.geteuid
        self.owner_uid = owner_uid
        self.credential_root = Path(credential_root)

    def _root(self) -> None:
        if self.effective_uid() != 0:
            raise RepositoryManagerError("remote repository management requires root")
        _private_directory(self.mount_root, create=True, owner_uid=self.owner_uid)
        os.chmod(self.mount_root, 0o700)
        _private_directory(self.registry.parent, create=True, owner_uid=self.owner_uid)

    def _load(self) -> dict[str, dict[str, Any]]:
        self._root()
        return _read_registry(self.registry, owner_uid=self.owner_uid)

    @contextmanager
    def _registry_lock(self):
        """Serialize registry read-modify-write transactions across processes."""
        self._root()
        path = self.registry.parent / ".repositories.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RepositoryManagerError(f"cannot open repository registry lock: {exc}") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise RepositoryManagerError("repository registry lock must be a private root-owned regular file")
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as exc:
                raise RepositoryManagerError(f"cannot acquire repository registry lock: {exc}") from exc
            yield
        finally:
            os.close(fd)

    def list(self) -> list[dict[str, Any]]:
        entries = self._load()
        result = []
        for identifier, definition in sorted(entries.items()):
            mountpoint = str(self.mount_root / identifier)
            mounted = self._is_mounted(mountpoint)
            item = {
                "id": identifier, "provider": definition["provider"],
                "host": definition["host"], "remote_path": definition["remote_path"],
                "username": definition.get("username"), "credential_file": definition.get("credential_file"),
                "identity_file": definition.get("identity_file"), "known_hosts_file": definition.get("known_hosts_file"),
                "port": definition.get("port"),
                "read_only": definition["read_only"], "mountpoint": mountpoint,
                "credential_refs": [
                    value for key in ("credential_file", "identity_file", "known_hosts_file")
                    if (value := definition.get(key)) is not None
                    and self._is_encrypted_credential_path(value)
                ],
                "mounted": mounted, "verified": False, "mount_error": None,
            }
            if mounted:
                try:
                    self.resolve(identifier)
                    item["verified"] = True
                except RepositoryManagerError as exc:
                    # A mount at the managed path is not necessarily the
                    # remote filesystem that this repository definition owns.
                    # Keep it visible as mounted, but never label it trusted.
                    item["mount_error"] = str(exc)[:512]
            result.append(item)
        return result

    def _is_encrypted_credential_path(self, value: str) -> bool:
        try:
            path = Path(value)
            return path.is_absolute() and path.parent == self.credential_root and path.name.endswith(".cred")
        except (TypeError, ValueError):
            return False

    def check(self, identifier: str) -> dict[str, Any]:
        """Report the current mount and source verification state for one repository."""
        for item in self.list():
            if item["id"] == identifier:
                return item
        raise RepositoryManagerError("unknown repository ID")

    def update(self, identifier: str, definition: dict[str, Any]) -> dict[str, Any]:
        """Replace a repository definition only while it is unmounted and unused."""
        if not isinstance(definition, dict):
            raise RepositoryManagerError("repository definition must be an object")
        repo = _repository(identifier, definition, owner_uid=self.owner_uid)
        lock_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            with self._registry_lock():
                entries = self._load()
                if identifier not in entries:
                    raise RepositoryManagerError("unknown repository ID")
                mountpoint = self.mount_root / identifier
                _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
                if self._is_mounted(str(mountpoint)):
                    raise RepositoryManagerError("unmount the repository before editing its definition")
                entries[identifier] = {
                    "provider": repo.provider, "host": repo.host, "remote_path": repo.remote_path,
                    "username": repo.username, "credential_file": repo.credential_file,
                    "identity_file": repo.identity_file, "known_hosts_file": repo.known_hosts_file,
                    "port": repo.port,
                    "read_only": repo.read_only,
                }
                _write_registry(entries, self.registry, owner_uid=self.owner_uid)
                return {"id": identifier, "updated": True, "provider": repo.provider}
        finally:
            os.close(lock_fd)

    def credential_is_referenced(self, credential_path: str) -> bool:
        """Return whether any saved repository definition references this credential."""
        if not isinstance(credential_path, str) or not credential_path:
            raise RepositoryManagerError("credential path is invalid")
        entries = self._load()
        return any(
            definition.get(field) == credential_path
            for definition in entries.values()
            for field in ("credential_file", "identity_file", "known_hosts_file")
        )

    def add(self, identifier: str, definition: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(identifier, str) or not _REPOSITORY_ID.fullmatch(identifier):
            raise RepositoryManagerError("repository ID must contain 1-48 lowercase letters, digits or hyphens")
        if not isinstance(definition, dict):
            raise RepositoryManagerError("repository definition must be an object")
        repo = _repository(identifier, definition, owner_uid=self.owner_uid)
        mountpoint = self.mount_root / identifier
        with self._registry_lock():
            entries = self._load()
            if identifier in entries:
                raise RepositoryManagerError("repository ID already exists")
            if os.path.lexists(mountpoint):
                raise RepositoryManagerError("repository mountpoint already exists outside the registry")
            mountpoint.mkdir(mode=0o700)
            entries[identifier] = {
                "provider": repo.provider, "host": repo.host, "remote_path": repo.remote_path,
                "username": repo.username, "credential_file": repo.credential_file,
                "identity_file": repo.identity_file, "known_hosts_file": repo.known_hosts_file,
                "port": repo.port,
                "read_only": repo.read_only,
            }
            try:
                _write_registry(entries, self.registry, owner_uid=self.owner_uid)
            except Exception:
                mountpoint.rmdir()
                raise
        return {"id": identifier, "mountpoint": str(mountpoint), "provider": repo.provider}

    def mount(self, identifier: str) -> dict[str, Any]:
        lock_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            return self._mount_locked(identifier)
        finally:
            os.close(lock_fd)

    def _mount_locked(self, identifier: str) -> dict[str, Any]:
        entries = self._load()
        try:
            definition = entries[identifier]
        except KeyError as exc:
            raise RepositoryManagerError("unknown repository ID") from exc
        repo = _repository(identifier, definition, owner_uid=self.owner_uid)
        mountpoint = self.mount_root / identifier
        _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
        if self._is_mounted(str(mountpoint)):
            raise RepositoryManagerError("repository is already mounted")
        tool_paths = {tool: self.which(tool) for tool in required_tools(repo.provider)}
        missing = [tool for tool, resolved in tool_paths.items() if not resolved]
        if missing:
            raise RepositoryManagerError("missing repository tools: " + ", ".join(missing))
        encrypted = self._encrypted_credential_bindings(repo)
        service_managed = bool(encrypted)
        try:
            if encrypted:
                systemd_run = self.which("systemd-run")
                python = self.which("python3")
                if not systemd_run or not python:
                    raise RepositoryManagerError("systemd-run and python3 are required for encrypted repository mounts")
                unit = f"feclora-repository-{identifier}.service"
                command = [
                    systemd_run,
                    f"--unit={unit}", "--no-block", "--collect",
                    "--property=User=root", "--property=Group=root",
                    "--property=UMask=0077", "--property=NoNewPrivileges=yes",
                ]
                for name, path in encrypted:
                    command.append(f"--property=LoadCredentialEncrypted={name}:{path}")
                command.extend([
                    "--setenv=PYTHONPATH=/usr/share/feclora/python", "--",
                    python,
                    "-m", "feclora.storage.repository_mount_service", "--id", identifier,
                ])
                result = self.runner(
                    command, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, check=False, timeout=30,
                )
            else:
                result = self.runner(
                    repo.mount_argv(executables={tool: resolved for tool, resolved in tool_paths.items() if resolved}),
                    stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, check=False, timeout=60,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryManagerError(f"repository mount failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:512]
            raise RepositoryManagerError("repository mount failed" + (f": {detail}" if detail else ""))
        mounted = self._is_mounted(str(mountpoint))
        if service_managed and not mounted:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not mounted:
                time.sleep(0.2)
                mounted = self._is_mounted(str(mountpoint))
        if not mounted:
            raise RepositoryManagerError("mount command returned success but the selected mountpoint is not mounted")
        # A mount appearing at the expected path is not sufficient: another
        # filesystem may have raced the helper or a provider helper may have
        # mounted an unexpected source/type/access mode. Never report success
        # until the same identity checks used by image-engine resolution pass.
        try:
            self.resolve(identifier)
        except RepositoryManagerError as exc:
            raise RepositoryManagerError(
                f"repository mount did not pass source/type/access-mode verification: {exc}"
            ) from exc
        return {"id": identifier, "mounted": True, "mountpoint": str(mountpoint)}

    def _encrypted_credential_bindings(self, repo: RemoteRepository) -> list[tuple[str, str]]:
        """Return validated systemd credential names for encrypted blob paths."""
        candidates = [repo.identity_file, repo.known_hosts_file, repo.credential_file]
        encrypted_paths = []
        for value in candidates:
            if value is None:
                continue
            path = Path(value)
            try:
                path.relative_to(self.credential_root)
            except ValueError:
                continue
            encrypted_paths.append(path)
        if not encrypted_paths:
            return []
        if repo.provider == "webdav":
            # davfs2's system-wide configuration always uses
            # /etc/davfs2/secrets; its configurable secrets= setting is
            # restricted to per-user configuration. Feclora mounts as root,
            # so substituting a systemd credential path here would be ignored.
            raise RepositoryManagerError(
                "WebDAV encrypted credentials are not supported yet: davfs2 "
                "uses the system-wide /etc/davfs2/secrets for root mounts"
            )
        from feclora.storage.systemd_credential_store import SystemdCredentialStore
        try:
            inventory = SystemdCredentialStore(
                self.credential_root, effective_uid=self.effective_uid,
                owner_uid=self.owner_uid,
            ).list()
        except Exception as exc:
            raise RepositoryManagerError(f"encrypted repository credentials are unavailable: {exc}") from exc
        by_path = {item["path"]: item["name"] for item in inventory}
        bindings = []
        for path in encrypted_paths:
            name = by_path.get(str(path))
            if name is None:
                raise RepositoryManagerError("repository credential path is not a registered encrypted credential")
            bindings.append((name, str(path)))
        return bindings

    def _acquire_usage_lock(self, identifier: str, *, exclusive: bool) -> int:
        if not isinstance(identifier, str) or not _REPOSITORY_ID.fullmatch(identifier):
            raise RepositoryManagerError("repository identifier is invalid")
        self._root()
        lock_dir = self.mount_root / ".locks"
        _private_directory(lock_dir, create=True, owner_uid=self.owner_uid)
        os.chmod(lock_dir, 0o700)
        path = lock_dir / (identifier + ".lock")
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                    or info.st_mode & 0o077):
                raise RepositoryManagerError("repository usage lock is not a private root-owned regular file")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, operation | fcntl.LOCK_NB)
            return fd
        except BlockingIOError as exc:
            if "fd" in locals():
                os.close(fd)
            raise RepositoryManagerError("repository is in use by an active deployment restore") from exc
        except RepositoryManagerError:
            if "fd" in locals():
                os.close(fd)
            raise
        except OSError as exc:
            if "fd" in locals():
                os.close(fd)
            raise RepositoryManagerError(f"cannot acquire repository usage lock: {exc}") from exc

    def acquire_usage_lock(self, identifier: str) -> int:
        """Hold a shared lease while a deployment job may read this repository."""
        if identifier not in self._load():
            raise RepositoryManagerError("unknown repository ID")
        return self._acquire_usage_lock(identifier, exclusive=False)

    def unmount(self, identifier: str) -> dict[str, Any]:
        entries = self._load()
        if identifier not in entries:
            raise RepositoryManagerError("unknown repository ID")
        lock_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            mountpoint = self.mount_root / identifier
            _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
            if not self._is_mounted(str(mountpoint)):
                return {"id": identifier, "mounted": False, "already_unmounted": True}
            # Never unmount an unrelated filesystem that happens to occupy this path.
            self.resolve(identifier)
            unit = f"feclora-repository-{identifier}.service"
            systemctl = self.which("systemctl") or "systemctl"
            try:
                active = self.runner(
                    [systemctl, "is-active", "--quiet", unit],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    check=False, timeout=10,
                )
                if active.returncode == 0:
                    stopped = self.runner(
                        [systemctl, "stop", unit],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        check=False, timeout=30,
                    )
                    if stopped.returncode != 0:
                        detail = (stopped.stderr or stopped.stdout or "").strip()[:512]
                        raise RepositoryManagerError("repository mount service could not stop" + (f": {detail}" if detail else ""))
                if self._is_mounted(str(mountpoint)):
                    result = self.runner(
                        [self.which("umount") or "umount", "--", str(mountpoint)],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        check=False, timeout=30,
                    )
                else:
                    result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
            except (OSError, subprocess.SubprocessError) as exc:
                raise RepositoryManagerError(f"repository unmount failed: {exc}") from exc
            if result.returncode != 0 or self._is_mounted(str(mountpoint)):
                detail = (result.stderr or result.stdout or "").strip()[:512]
                raise RepositoryManagerError("repository remains mounted" + (f": {detail}" if detail else ""))
            return {"id": identifier, "mounted": False}
        finally:
            os.close(lock_fd)

    def remove(self, identifier: str) -> dict[str, Any]:
        # Definition removal must obey the same exclusive lease as unmount:
        # a restore may still need this registry entry even if the remote mount
        # disappeared unexpectedly while its service was active.
        lock_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            with self._registry_lock():
                entries = self._load()
                if identifier not in entries:
                    raise RepositoryManagerError("unknown repository ID")
                mountpoint = self.mount_root / identifier
                _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
                if self._is_mounted(str(mountpoint)):
                    raise RepositoryManagerError("unmount the repository before removing its definition")
                mountpoint.rmdir()
                del entries[identifier]
                try:
                    _write_registry(entries, self.registry, owner_uid=self.owner_uid)
                except Exception:
                    # Keep the persisted definition usable if the atomic
                    # registry replacement fails after the empty mountpoint
                    # has been removed.
                    try:
                        mountpoint.mkdir(mode=0o700)
                    except OSError as restore_exc:
                        raise RepositoryManagerError(
                            "registry update failed and the repository mountpoint could not be restored"
                        ) from restore_exc
                    raise
                return {"id": identifier, "removed": True}
        finally:
            os.close(lock_fd)

    def resolve(self, identifier: str, *, write: bool = False) -> str:
        """Return a repository path only when its expected remote mount is active."""
        entries = self._load()
        try:
            definition = entries[identifier]
        except KeyError as exc:
            raise RepositoryManagerError("unknown repository ID") from exc
        repo = _repository(identifier, definition, owner_uid=self.owner_uid)
        if write and repo.read_only:
            raise RepositoryManagerError("repository is configured read-only and cannot receive image artifacts")
        mountpoint = str(self.mount_root / identifier)
        record = self._mount_record(mountpoint)
        if record is None:
            raise RepositoryManagerError("repository is not mounted")
        filesystem, source, options = record
        if repo.provider == "sshfs":
            expected_source = f"{repo.username}@{repo.host}:{repo.remote_path}"
            valid_source = source == expected_source
            valid_type = filesystem.startswith("fuse.sshfs")
        elif repo.provider == "nfs":
            valid_source = source == f"{repo.host}:{repo.remote_path}"
            valid_type = filesystem in {"nfs", "nfs4"}
        elif repo.provider == "smb":
            share = repo.remote_path.strip("/").split("/", 1)[0]
            valid_source = source == f"//{repo.host}/{share}"
            valid_type = filesystem == "cifs"
            subpath = repo.remote_path.strip("/").split("/", 1)
            if len(subpath) == 2:
                valid_source = valid_source and ("prefixpath=" + subpath[1]) in options.split(",")
        elif repo.provider == "webdav":
            valid_source = source == f"https://{repo.host}{repo.remote_path}"
            valid_type = filesystem.startswith("fuse.davfs")
        else:
            raise RepositoryManagerError("unsupported managed repository provider")
        if not valid_source or not valid_type:
            raise RepositoryManagerError("mounted filesystem source or type does not match the saved repository definition")
        option_set = set(options.split(","))
        if "ro" not in option_set and "rw" not in option_set:
            raise RepositoryManagerError("mounted filesystem does not report its access mode")
        if write and "rw" not in option_set:
            raise RepositoryManagerError("repository is not mounted read/write")
        if not write and repo.read_only and "ro" not in option_set:
            raise RepositoryManagerError("repository was configured read-only but is mounted read/write")
        return mountpoint

    def _mount_record(self, mountpoint: str) -> tuple[str, str, str] | None:
        findmnt = self.which("findmnt")
        if not findmnt:
            raise RepositoryManagerError("findmnt is required to verify repository mount state")
        try:
            result = self.runner(
                [findmnt, "--noheadings", "--mountpoint", mountpoint,
                 "--output", "TARGET,FSTYPE,SOURCE,OPTIONS"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryManagerError(f"cannot verify repository mount state: {exc}") from exc
        if result.returncode == 1 and not result.stdout.strip():
            return None
        if result.returncode != 0:
            raise RepositoryManagerError("findmnt could not verify repository mount state")
        fields = result.stdout.strip().split(None, 3)
        if len(fields) != 4 or fields[0] != mountpoint:
            raise RepositoryManagerError("findmnt returned an unexpected mountpoint record")
        return fields[1], fields[2], fields[3]

    def _is_mounted(self, mountpoint: str) -> bool:
        return self._mount_record(mountpoint) is not None

"""Root-managed lifecycle for Feclora remote image repositories.

Repository definitions contain paths and credential references only. Secret
material remains in separately provisioned root-owned files and is never
accepted from a Cockpit request or copied into the repository registry.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
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
    if path is None:
        return
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RepositoryManagerError(f"{label} is unavailable") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or (private and info.st_mode & 0o077)):
        raise RepositoryManagerError(f"{label} must be a root-owned regular file with mode 0600 or stricter")


def _repository(identifier: str, definition: dict[str, Any], *, owner_uid: int = 0) -> RemoteRepository:
    if not _REPOSITORY_ID.fullmatch(identifier):
        raise RepositoryManagerError("repository identifier is invalid")
    if set(definition) != {
        "provider", "host", "remote_path", "username", "credential_file",
        "identity_file", "known_hosts_file", "port", "read_only",
    }:
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
            port=definition["port"], read_only=definition["read_only"],
        )
    except (RepositoryError, TypeError) as exc:
        raise RepositoryManagerError(f"invalid repository definition: {exc}") from exc
    if repo.provider not in _SUPPORTED:
        raise RepositoryManagerError(
            "managed mounts currently support SSHFS, NFS and SMB/CIFS; "
            "WebDAV and S3 need dedicated protected-credential integration"
        )
    if repo.provider == "sshfs":
        _check_secret_reference(repo.identity_file, "SSH private key", owner_uid=owner_uid)
        _check_secret_reference(repo.known_hosts_file, "SSH known_hosts", private=False, owner_uid=owner_uid)
    if repo.provider == "smb":
        _check_secret_reference(repo.credential_file, "SMB credentials file", owner_uid=owner_uid)
    return repo


class RemoteRepositoryManager:
    """Manage SSHFS, NFS and SMB mounts below a private Feclora directory."""

    def __init__(
        self, *, registry: Path = REGISTRY, mount_root: Path = MOUNT_ROOT,
        runner: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] | None = None,
        effective_uid: Callable[[], int] | None = None,
        owner_uid: int = 0,
    ) -> None:
        self.registry = Path(registry)
        self.mount_root = Path(mount_root)
        self.runner = runner or subprocess.run
        self.which = which or shutil.which
        self.effective_uid = effective_uid or os.geteuid
        self.owner_uid = owner_uid

    def _root(self) -> None:
        if self.effective_uid() != 0:
            raise RepositoryManagerError("remote repository management requires root")
        _private_directory(self.mount_root, create=True, owner_uid=self.owner_uid)
        _private_directory(self.registry.parent, create=True, owner_uid=self.owner_uid)

    def _load(self) -> dict[str, dict[str, Any]]:
        self._root()
        return _read_registry(self.registry, owner_uid=self.owner_uid)

    def list(self) -> list[dict[str, Any]]:
        entries = self._load()
        return [
            {"id": identifier, "provider": definition["provider"],
             "host": definition["host"], "remote_path": definition["remote_path"],
             "read_only": definition["read_only"],
             "mountpoint": str(self.mount_root / identifier),
             "mounted": self._is_mounted(str(self.mount_root / identifier))}
            for identifier, definition in sorted(entries.items())
        ]

    def add(self, identifier: str, definition: dict[str, Any]) -> dict[str, Any]:
        entries = self._load()
        if not isinstance(identifier, str) or not _REPOSITORY_ID.fullmatch(identifier):
            raise RepositoryManagerError("repository ID must contain 1-48 lowercase letters, digits or hyphens")
        if identifier in entries:
            raise RepositoryManagerError("repository ID already exists")
        if not isinstance(definition, dict):
            raise RepositoryManagerError("repository definition must be an object")
        repo = _repository(identifier, definition, owner_uid=self.owner_uid)
        mountpoint = self.mount_root / identifier
        if os.path.lexists(mountpoint):
            raise RepositoryManagerError("repository mountpoint already exists outside the registry")
        mountpoint.mkdir(mode=0o700)
        entries[identifier] = {
            "provider": repo.provider, "host": repo.host, "remote_path": repo.remote_path,
            "username": repo.username, "credential_file": repo.credential_file,
            "identity_file": repo.identity_file, "known_hosts_file": repo.known_hosts_file,
            "port": repo.port, "read_only": repo.read_only,
        }
        try:
            _write_registry(entries, self.registry, owner_uid=self.owner_uid)
        except Exception:
            mountpoint.rmdir()
            raise
        return {"id": identifier, "mountpoint": str(mountpoint), "provider": repo.provider}

    def mount(self, identifier: str) -> dict[str, Any]:
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
        try:
            result = self.runner(
                repo.mount_argv(executables={tool: resolved for tool, resolved in tool_paths.items() if resolved}), stdin=subprocess.DEVNULL, capture_output=True,
                text=True, check=False, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryManagerError(f"repository mount failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:512]
            raise RepositoryManagerError("repository mount failed" + (f": {detail}" if detail else ""))
        if not self._is_mounted(str(mountpoint)):
            raise RepositoryManagerError("mount command returned success but the selected mountpoint is not mounted")
        return {"id": identifier, "mounted": True, "mountpoint": str(mountpoint)}

    def unmount(self, identifier: str) -> dict[str, Any]:
        entries = self._load()
        if identifier not in entries:
            raise RepositoryManagerError("unknown repository ID")
        mountpoint = self.mount_root / identifier
        _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
        if not self._is_mounted(str(mountpoint)):
            return {"id": identifier, "mounted": False, "already_unmounted": True}
        try:
            result = self.runner(
                [self.which("umount") or "umount", "--", str(mountpoint)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryManagerError(f"repository unmount failed: {exc}") from exc
        if result.returncode != 0 or self._is_mounted(str(mountpoint)):
            detail = (result.stderr or result.stdout or "").strip()[:512]
            raise RepositoryManagerError("repository remains mounted" + (f": {detail}" if detail else ""))
        return {"id": identifier, "mounted": False}

    def remove(self, identifier: str) -> dict[str, Any]:
        entries = self._load()
        if identifier not in entries:
            raise RepositoryManagerError("unknown repository ID")
        mountpoint = self.mount_root / identifier
        _private_directory(mountpoint, create=False, owner_uid=self.owner_uid)
        if self._is_mounted(str(mountpoint)):
            raise RepositoryManagerError("unmount the repository before removing its definition")
        mountpoint.rmdir()
        del entries[identifier]
        _write_registry(entries, self.registry, owner_uid=self.owner_uid)
        return {"id": identifier, "removed": True}

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
        else:
            share = repo.remote_path.strip("/").split("/", 1)[0]
            valid_source = source == f"//{repo.host}/{share}"
            valid_type = filesystem == "cifs"
            subpath = repo.remote_path.strip("/").split("/", 1)
            if len(subpath) == 2:
                valid_source = valid_source and ("prefixpath=" + subpath[1]) in options.split(",")
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

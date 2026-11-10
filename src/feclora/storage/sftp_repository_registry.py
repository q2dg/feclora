"""Root-owned registry of reusable SFTP image repository connection definitions.

Only endpoint metadata and references to encrypted systemd credentials are
stored. Private-key and known_hosts contents are never read into this registry.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY = Path("/etc/feclora/sftp-repositories.json")
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
_USER = re.compile(r"[A-Za-z0-9._-]{1,64}")
_CREDENTIAL = re.compile(
    r"/etc/credstore\.encrypted/feclora/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.cred"
)
_REMOTE = re.compile(r"/[A-Za-z0-9._/-]{0,1024}")


class SFTPRepositoryRegistryError(RuntimeError):
    """A saved SFTP repository definition is invalid or unavailable."""


def _credential(path: str, label: str, owner_uid: int) -> None:
    if not isinstance(path, str) or not _CREDENTIAL.fullmatch(path):
        raise SFTPRepositoryRegistryError(f"{label} must reference a registered encrypted credential")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise SFTPRepositoryRegistryError(f"{label} is unavailable or is a symlink") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise SFTPRepositoryRegistryError(
                f"{label} must be a private root-owned regular encrypted credential without hard links"
            )
    finally:
        os.close(fd)


class SFTPRepositoryRegistry:
    """Atomic root-owned storage for saved SFTP endpoints and credential refs."""

    def __init__(
        self, path: Path = DEFAULT_REGISTRY, *, owner_uid: int = 0,
        effective_uid: Any = os.geteuid,
    ) -> None:
        self.path = Path(path)
        self.owner_uid = owner_uid
        self.effective_uid = effective_uid

    def _root(self) -> None:
        if self.effective_uid() != 0:
            raise SFTPRepositoryRegistryError("SFTP repository registry requires root")
        try:
            self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            info = os.lstat(self.path.parent)
        except OSError as exc:
            raise SFTPRepositoryRegistryError("SFTP repository registry directory is unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != self.owner_uid or info.st_mode & 0o022):
            raise SFTPRepositoryRegistryError("SFTP repository registry directory is unsafe")

    def _locked(self):
        self._root()
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                or info.st_mode & 0o077 or info.st_nlink != 1):
            os.close(fd)
            raise SFTPRepositoryRegistryError("SFTP repository registry lock is unsafe")
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SFTPRepositoryRegistryError("cannot inspect SFTP repository registry") from exc
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != self.owner_uid or info.st_mode & 0o077
                or info.st_size > 256 * 1024):
            raise SFTPRepositoryRegistryError("SFTP repository registry must be a private root-owned regular file")
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != self.owner_uid
                    or opened.st_mode & 0o077
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise SFTPRepositoryRegistryError("SFTP repository registry changed during inspection")
            raw = os.read(fd, 256 * 1024 + 1)
        finally:
            os.close(fd)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SFTPRepositoryRegistryError("SFTP repository registry is malformed") from exc
        if (not isinstance(value, dict) or set(value) != {"schema_version", "repositories"}
                or value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool)
                or not isinstance(value.get("repositories"), dict)
                or len(value["repositories"]) > 128):
            raise SFTPRepositoryRegistryError("SFTP repository registry schema is invalid")
        repositories = value["repositories"]
        required_fields = {
            "host", "username", "remote_directory", "port",
            "identity_credential", "known_hosts_credential",
        }
        for identifier, definition in repositories.items():
            if (not isinstance(identifier, str) or not _ID.fullmatch(identifier)
                    or not isinstance(definition, dict) or set(definition) != required_fields):
                raise SFTPRepositoryRegistryError("SFTP repository registry contains an invalid definition")
            if (not isinstance(definition["host"], str) or not _HOST.fullmatch(definition["host"])
                    or definition["host"].endswith(".") or ".." in definition["host"]
                    or not isinstance(definition["username"], str) or not _USER.fullmatch(definition["username"])):
                raise SFTPRepositoryRegistryError("SFTP repository registry contains invalid endpoint fields")
            remote = definition["remote_directory"]
            if (not isinstance(remote, str) or not _REMOTE.fullmatch(remote)
                    or remote.startswith("//") or os.path.normpath(remote) != remote
                    or any(part in {".", ".."} for part in remote.split("/"))):
                raise SFTPRepositoryRegistryError("SFTP repository registry contains an invalid remote directory")
            if (isinstance(definition["port"], bool) or not isinstance(definition["port"], int)
                    or not 1 <= definition["port"] <= 65535):
                raise SFTPRepositoryRegistryError("SFTP repository registry contains an invalid port")
            if any(not isinstance(definition[field], str) or not _CREDENTIAL.fullmatch(definition[field])
                   for field in ("identity_credential", "known_hosts_credential")):
                raise SFTPRepositoryRegistryError("SFTP repository registry contains an invalid credential reference")
        return repositories

    def _write(self, repositories: dict[str, dict[str, Any]]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".sftp-repositories-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {"schema_version": 1, "repositories": repositories},
                    stream, sort_keys=True, separators=(",", ":"),
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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

    def _validate(self, definition: dict[str, Any]) -> dict[str, Any]:
        required = {
            "id", "host", "username", "remote_directory",
            "identity_credential", "known_hosts_credential",
        }
        if not isinstance(definition, dict) or set(definition) not in (required, required | {"port"}):
            raise SFTPRepositoryRegistryError("SFTP repository definition has missing or unknown fields")
        identifier = definition["id"]
        host = definition["host"]
        username = definition["username"]
        remote = definition["remote_directory"]
        port = definition.get("port", 22)
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SFTPRepositoryRegistryError("SFTP repository ID is invalid")
        if (not isinstance(host, str) or not _HOST.fullmatch(host)
                or host.endswith(".") or ".." in host):
            raise SFTPRepositoryRegistryError("SFTP repository host is invalid")
        if not isinstance(username, str) or not _USER.fullmatch(username):
            raise SFTPRepositoryRegistryError("SFTP repository username is invalid")
        if (not isinstance(remote, str) or not _REMOTE.fullmatch(remote)
                or remote.startswith("//") or os.path.normpath(remote) != remote
                or any(part in {".", ".."} for part in remote.split("/"))):
            raise SFTPRepositoryRegistryError("SFTP repository directory must be absolute and normalized")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise SFTPRepositoryRegistryError("SFTP repository port must be between 1 and 65535")
        _credential(definition["identity_credential"], "SSH key", self.owner_uid)
        _credential(definition["known_hosts_credential"], "known_hosts", self.owner_uid)
        return {
            "id": identifier, "host": host, "username": username,
            "remote_directory": remote, "port": port,
            "identity_credential": definition["identity_credential"],
            "known_hosts_credential": definition["known_hosts_credential"],
        }

    def list(self) -> list[dict[str, Any]]:
        lock_fd = self._locked()
        try:
            repositories = self._read()
            return [dict(repositories[key]) for key in sorted(repositories)]
        finally:
            os.close(lock_fd)

    def save(self, definition: dict[str, Any]) -> dict[str, Any]:
        validated = self._validate(definition)
        lock_fd = self._locked()
        try:
            repositories = self._read()
            if validated["id"] not in repositories and len(repositories) >= 128:
                raise SFTPRepositoryRegistryError("SFTP repository registry is full")
            repositories[validated["id"]] = {key: value for key, value in validated.items() if key != "id"}
            self._write(repositories)
            return validated
        finally:
            os.close(lock_fd)

    def remove(self, identifier: str) -> None:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SFTPRepositoryRegistryError("SFTP repository ID is invalid")
        lock_fd = self._locked()
        try:
            repositories = self._read()
            if identifier not in repositories:
                raise SFTPRepositoryRegistryError("saved SFTP repository does not exist")
            del repositories[identifier]
            self._write(repositories)
        finally:
            os.close(lock_fd)

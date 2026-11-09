"""Validated remote repository definitions and safe mount command construction.

Credentials are referenced through protected local configuration; inline
secrets are never accepted or embedded in generated argv. The caller owns
mountpoint creation, privilege escalation and mount lifecycle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit


class RepositoryError(ValueError):
    """A remote repository definition is invalid or unsupported."""


_PROVIDERS = {"sshfs", "nfs", "smb", "webdav", "s3"}
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/@+,-]*(?:/[A-Za-z0-9._/@+,-]*)*$")
_SAFE_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_SHARE_RE = re.compile(r"^[A-Za-z0-9._$-]{1,80}$")


def _absolute_path(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise RepositoryError(f"{field} must be an absolute path")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise RepositoryError(f"{field} must not contain parent path components")
    return str(path)


def _host(value: str) -> str:
    if not isinstance(value, str) or not _HOST_RE.fullmatch(value):
        raise RepositoryError("host must be a DNS name or IPv4 address (IPv6 literals are not yet supported)")
    return value


@dataclass(frozen=True)
class RemoteRepository:
    """A remote image repository, with no inline credentials."""

    provider: str
    host: str
    remote_path: str
    mountpoint: str
    username: str | None = None
    credential_file: str | None = None
    identity_file: str | None = None
    known_hosts_file: str | None = None
    port: int | None = None
    rclone_remote: str | None = None
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.provider not in _PROVIDERS:
            raise RepositoryError(f"provider must be one of {', '.join(sorted(_PROVIDERS))}")
        _host(self.host)
        _absolute_path(self.mountpoint, "mountpoint")
        if not isinstance(self.remote_path, str) or not self.remote_path.startswith("/") or not _REMOTE_PATH_RE.fullmatch(self.remote_path):
            raise RepositoryError("remote_path must be an absolute normalized path without shell metacharacters")
        if any(part == ".." for part in self.remote_path.split("/")):
            raise RepositoryError("remote_path must not contain parent path components")
        if self.username is not None and not _SAFE_USER_RE.fullmatch(self.username):
            raise RepositoryError("username contains unsupported characters")
        if self.port is not None and (isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535):
            raise RepositoryError("port must be between 1 and 65535")
        if self.credential_file is not None:
            credential_path = _absolute_path(self.credential_file, "credential_file")
            if "," in credential_path or "\\" in credential_path:
                raise RepositoryError("credential_file must not contain mount-option separators")
            object.__setattr__(self, "credential_file", credential_path)
        if self.identity_file is not None:
            identity_path = _absolute_path(self.identity_file, "identity_file")
            if "," in identity_path or "\\" in identity_path:
                raise RepositoryError("identity_file must not contain mount-option separators")
            object.__setattr__(self, "identity_file", identity_path)
        if not isinstance(self.read_only, bool):
            raise RepositoryError("read_only must be boolean")
        if self.known_hosts_file is not None:
            known_hosts_path = _absolute_path(self.known_hosts_file, "known_hosts_file")
            if "," in known_hosts_path or "\\" in known_hosts_path:
                raise RepositoryError("known_hosts_file must not contain mount-option separators")
            object.__setattr__(self, "known_hosts_file", known_hosts_path)
        if self.provider == "sshfs":
            if self.username is None or self.identity_file is None or self.known_hosts_file is None:
                raise RepositoryError("sshfs requires username, identity_file and known_hosts_file")
        elif self.provider == "smb":
            if self.credential_file is None:
                raise RepositoryError("SMB requires a protected credentials file")
            if not _SAFE_SHARE_RE.fullmatch(self.remote_path.strip("/").split("/")[0]):
                raise RepositoryError("SMB remote_path must begin with a valid share name")
        elif self.provider == "webdav":
            parsed = urlsplit(self.remote_path)
            if parsed.scheme or parsed.netloc:
                raise RepositoryError("WebDAV remote_path must be a path; host is configured separately")
            if self.credential_file is not None:
                raise RepositoryError("WebDAV credentials are managed by davfs2 secrets")
        elif self.provider == "s3":
            if not isinstance(self.rclone_remote, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.rclone_remote):
                raise RepositoryError("S3 requires a configured rclone remote alias")
            if self.credential_file is not None:
                raise RepositoryError("S3 credentials belong in the protected rclone config")
        elif self.provider == "nfs" and (self.username or self.credential_file or self.identity_file):
            raise RepositoryError("NFS does not accept username or credential-file fields")

    def mount_argv(self, *, executables: dict[str, str] | None = None) -> list[str]:
        """Return argv for a system mount helper; never invokes a shell."""
        paths = executables or {}
        def exe(name: str) -> str:
            return paths.get(name, name)
        options = ["ro"] if self.read_only else ["rw"]
        if self.provider == "sshfs":
            options += ["reconnect", "ServerAliveInterval=15", "ServerAliveCountMax=3",
                        "StrictHostKeyChecking=yes",
                        f"UserKnownHostsFile={self.known_hosts_file}",
                        f"IdentityFile={self.identity_file}"]
            if self.port is not None:
                options.append(f"port={self.port}")
            return [exe("sshfs"), "-o", ",".join(options),
                    f"{self.username}@{self.host}:{self.remote_path}", self.mountpoint]
        if self.provider == "nfs":
            options += ["vers=4.2", "hard", "timeo=600", "retrans=2"]
            return [exe("mount"), "-t", "nfs", "-o", ",".join(options),
                    f"{self.host}:{self.remote_path}", self.mountpoint]
        if self.provider == "smb":
            parts = self.remote_path.strip("/").split("/")
            source = f"//{self.host}/{parts[0]}"
            options += ["vers=3.1.1", "seal", "serverino",
                        f"credentials={self.credential_file}"]
            if len(parts) > 1:
                options.append("prefixpath=" + "/".join(parts[1:]))
            if self.username:
                options.append(f"username={self.username}")
            if self.port is not None:
                options.append(f"port={self.port}")
            return [exe("mount"), "-t", "cifs", "-o", ",".join(options), source, self.mountpoint]
        if self.provider == "webdav":
            options += ["conf=/etc/davfs2/davfs2.conf"]
            return [exe("mount.davfs"), "-o", ",".join(options),
                    f"https://{self.host}{self.remote_path}", self.mountpoint]
        bucket_path = self.remote_path.lstrip("/")
        argv = [exe("rclone"), "mount", f"{self.rclone_remote}:{bucket_path}",
                self.mountpoint, "--vfs-cache-mode", "writes", "--dir-cache-time", "5m"]
        if self.read_only:
            argv.append("--read-only")
        return argv


def required_tools(provider: str) -> tuple[str, ...]:
    """Return executable dependencies for a provider."""
    mapping = {
        "sshfs": ("sshfs",), "nfs": ("mount", "mount.nfs"),
        "smb": ("mount", "mount.cifs"), "webdav": ("mount.davfs",),
        "s3": ("rclone",),
    }
    try:
        return mapping[provider]
    except KeyError as exc:
        raise RepositoryError(f"unsupported repository provider: {provider}") from exc

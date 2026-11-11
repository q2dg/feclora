"""Root-only provisioning of local credential files for remote repositories.

This is an administrative primitive, not a Cockpit API: callers must
obtain secret material through a trusted local channel. Secret bytes are never
returned by this store or written to the repository registry.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path


DEFAULT_ROOT = Path("/etc/feclora/credentials")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_MODES = {"ssh-key": 0o600, "known-hosts": 0o644, "smb": 0o600}


class CredentialStoreError(RuntimeError):
    """A credential store operation failed safely."""


class CredentialStore:
    """Provision, replace and remove root-owned credential files."""

    def __init__(self, root: Path = DEFAULT_ROOT, *, effective_uid=os.geteuid, owner_uid: int = 0) -> None:
        self.root = Path(root)
        self.effective_uid = effective_uid
        self.owner_uid = owner_uid

    def _directory(self, *, create: bool) -> None:
        if create:
            try:
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                raise CredentialStoreError("credential directory is unavailable") from exc
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            raise CredentialStoreError("credential directory is unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077):
            raise CredentialStoreError("credential directory must be a private owner-controlled directory")

    def _name(self, identifier: str, kind: str) -> str:
        if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
            raise CredentialStoreError("credential ID must contain 1-48 lowercase letters, digits or hyphens")
        if kind not in _MODES:
            raise CredentialStoreError("unsupported credential kind")
        return f"{identifier}.{kind}"

    def path(self, identifier: str, kind: str) -> str:
        """Return the reference path, never the credential contents."""
        return str(self.root / self._name(identifier, kind))

    def put(self, identifier: str, kind: str, content: bytes, *, replace: bool = False) -> str:
        """Atomically create or explicitly replace a credential file."""
        if self.effective_uid() != 0:
            raise CredentialStoreError("credential provisioning requires root")
        name = self._name(identifier, kind)
        if not isinstance(content, bytes) or not content or len(content) > 1024 * 1024 or b"\x00" in content:
            raise CredentialStoreError("credential content must be 1 byte to 1 MiB and contain no NUL")
        self._directory(create=True)
        destination = self.root / name
        fd = -1
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".credential-", dir=self.root)
            os.fchmod(fd, _MODES[kind])
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                self._validate_existing(destination, kind)
                os.replace(temporary, destination)
                temporary = None
            else:
                # link() is an atomic create-if-absent operation.
                os.link(temporary, destination, follow_symlinks=False)
                os.unlink(temporary)
                temporary = None
            directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as exc:
            raise CredentialStoreError("credential already exists; explicit replacement is required") from exc
        except CredentialStoreError:
            raise
        except OSError as exc:
            raise CredentialStoreError("credential could not be stored safely") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        return str(destination)

    def _validate_existing(self, path: Path, kind: str) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            raise CredentialStoreError("existing credential is unavailable or is a symlink") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != _MODES[kind]):
                raise CredentialStoreError("existing credential has unsafe ownership, links or permissions")
        finally:
            os.close(fd)

    def list(self) -> list[dict[str, str]]:
        """List valid credential references without reading their contents."""
        if self.effective_uid() != 0:
            raise CredentialStoreError("credential inventory requires root")
        self._directory(create=False)
        result = []
        for entry in sorted(self.root.iterdir(), key=lambda item: item.name):
            if entry.name.startswith(".credential-"):
                continue
            matched = next(((entry.name[:-len("." + kind)], kind) for kind in _MODES
                            if entry.name.endswith("." + kind)), None)
            if matched is None:
                continue
            identifier, kind = matched
            self._name(identifier, kind)
            self._validate_existing(entry, kind)
            result.append({"id": identifier, "kind": kind, "path": str(entry)})
        return result

    def remove(self, identifier: str, kind: str) -> None:
        """Remove a credential after validating its current file identity."""
        if self.effective_uid() != 0:
            raise CredentialStoreError("credential removal requires root")
        name = self._name(identifier, kind)
        self._directory(create=False)
        destination = self.root / name
        self._validate_existing(destination, kind)
        try:
            os.unlink(destination)
            directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise CredentialStoreError("credential could not be removed safely") from exc

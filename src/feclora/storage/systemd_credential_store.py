"""Root-only encrypted credential storage backed by systemd-creds.

Encrypted blobs are suitable for LoadCredentialEncrypted= in systemd units.
Plaintext is supplied to systemd-creds over stdin and is never written here.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Any


DEFAULT_ROOT = Path("/etc/credstore.encrypted/feclora")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_KINDS = {"ssh-key", "known-hosts", "smb", "rclone"}


class SystemdCredentialStoreError(RuntimeError):
    """A systemd encrypted credential operation failed safely."""


class SystemdCredentialStore:
    """Manage host-bound encrypted credentials for persistent system services."""

    def __init__(
        self, root: Path = DEFAULT_ROOT, *,
        effective_uid: Callable[[], int] = os.geteuid,
        owner_uid: int = 0,
        runner: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.root = Path(root)
        self.effective_uid = effective_uid
        self.owner_uid = owner_uid
        self.runner = runner
        self.which = which

    def _name(self, identifier: str, kind: str) -> str:
        if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
            raise SystemdCredentialStoreError("credential ID must contain 1-48 lowercase letters, digits or hyphens")
        if kind not in _KINDS:
            raise SystemdCredentialStoreError("unsupported credential kind")
        return f"feclora-{identifier}-{kind}"

    def _directory(self, *, create: bool) -> None:
        if create:
            try:
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                raise SystemdCredentialStoreError("encrypted credential directory is unavailable") from exc
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            raise SystemdCredentialStoreError("encrypted credential directory is unavailable") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077):
            raise SystemdCredentialStoreError("encrypted credential directory must be private and owner-controlled")

    def _path(self, identifier: str, kind: str) -> Path:
        return self.root / (self._name(identifier, kind) + ".cred")

    def put(self, identifier: str, kind: str, content: bytes, *, replace: bool = False) -> dict[str, str]:
        """Encrypt bytes with the local systemd credential key and store atomically."""
        if self.effective_uid() != 0:
            raise SystemdCredentialStoreError("credential provisioning requires root")
        name = self._name(identifier, kind)
        if not isinstance(content, bytes) or not content or len(content) > 1024 * 1024 or b"\\x00" in content:
            raise SystemdCredentialStoreError("credential content must be 1 byte to 1 MiB and contain no NUL")
        executable = self.which("systemd-creds")
        if not executable:
            raise SystemdCredentialStoreError("systemd-creds is required")
        self._directory(create=True)
        destination = self._path(identifier, kind)
        temporary_dir = None
        try:
            temporary_dir = tempfile.mkdtemp(prefix=".credential-", dir=self.root)
            os.chmod(temporary_dir, 0o700)
            temporary = Path(temporary_dir) / "payload.cred"
            result = self.runner(
                [executable, "encrypt", f"--name={name}", "--with-key=auto", "-", str(temporary)],
                input=content, capture_output=True, check=False, timeout=30,
            )
            if result.returncode != 0:
                raise SystemdCredentialStoreError("systemd-creds could not encrypt the credential")
            try:
                info = os.lstat(temporary)
            except OSError as exc:
                raise SystemdCredentialStoreError("systemd-creds did not create an encrypted credential") from exc
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_nlink != 1:
                raise SystemdCredentialStoreError("systemd-creds produced an unsafe credential file")
            os.chmod(temporary, 0o600)
            if replace:
                self._validate_existing(destination)
                os.replace(temporary, destination)
            else:
                os.link(temporary, destination, follow_symlinks=False)
            directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as exc:
            raise SystemdCredentialStoreError("credential already exists; explicit replacement is required") from exc
        except SystemdCredentialStoreError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise SystemdCredentialStoreError("encrypted credential could not be stored safely") from exc
        finally:
            if temporary_dir is not None:
                shutil.rmtree(temporary_dir, ignore_errors=True)
        return {"id": identifier, "kind": kind, "name": name, "path": str(destination)}

    def _validate_existing(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            raise SystemdCredentialStoreError("existing encrypted credential is unavailable or a symlink") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise SystemdCredentialStoreError("existing encrypted credential has unsafe ownership, links or permissions")
        finally:
            os.close(fd)

    def list(self) -> list[dict[str, str]]:
        if self.effective_uid() != 0:
            raise SystemdCredentialStoreError("credential inventory requires root")
        self._directory(create=False)
        result = []
        for path in sorted(self.root.glob("*.cred")):
            match = re.fullmatch(r"feclora-([a-z0-9][a-z0-9-]{0,47})-(ssh-key|known-hosts|smb|rclone)\\.cred", path.name)
            if not match:
                continue
            identifier, kind = match.groups()
            self._validate_existing(path)
            result.append({"id": identifier, "kind": kind, "name": self._name(identifier, kind), "path": str(path)})
        return result

    def remove(self, identifier: str, kind: str) -> None:
        if self.effective_uid() != 0:
            raise SystemdCredentialStoreError("credential removal requires root")
        self._name(identifier, kind)
        self._directory(create=False)
        path = self._path(identifier, kind)
        self._validate_existing(path)
        os.unlink(path)
        directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

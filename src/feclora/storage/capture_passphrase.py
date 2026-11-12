"""One-shot, volatile passphrase handoff for local capture workers."""
from __future__ import annotations

import os
import re
import stat
import tempfile
import time
import uuid
from pathlib import Path

DIRECTORY = Path("/run/feclora/capture-passphrases")


class CapturePassphraseError(RuntimeError):
    """A volatile capture passphrase could not be safely handed off."""


def _identifier(value: str) -> str:
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CapturePassphraseError("operation_id must be a UUID") from exc
    if normalized != value:
        raise CapturePassphraseError("operation_id must use canonical UUID form")
    return normalized


def _directory(*, create: bool) -> Path:
    if create:
        DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = os.lstat(DIRECTORY)
    except OSError as exc:
        raise CapturePassphraseError("volatile passphrase directory is unavailable") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise CapturePassphraseError("volatile passphrase directory must be root-owned mode 0700")
    return DIRECTORY


def provide(operation_id: str, passphrase: str) -> None:
    """Atomically publish one passphrase without replacing an existing value."""
    identifier = _identifier(operation_id)
    if (not isinstance(passphrase, str) or not passphrase
            or len(passphrase.encode("utf-8")) > 1024
            or any(char in passphrase for char in "\r\n\x00")):
        raise CapturePassphraseError("passphrase must be 1-1024 UTF-8 bytes without line breaks")
    directory = _directory(create=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        payload = passphrase.encode("utf-8")
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, directory / identifier, follow_symlinks=False)
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except FileExistsError as exc:
        raise CapturePassphraseError("a passphrase has already been supplied for this operation") from exc
    except OSError as exc:
        raise CapturePassphraseError(f"cannot publish volatile passphrase: {exc}") from exc
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def consume(operation_id: str, *, timeout: float = 120.0, poll_interval: float = 0.2) -> str:
    """Wait for and consume exactly one root-owned passphrase file."""
    identifier = _identifier(operation_id)
    directory = _directory(create=False)
    path = directory / identifier
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                raise CapturePassphraseError("timed out waiting for the capture passphrase")
            time.sleep(poll_interval)
            continue
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024):
                raise CapturePassphraseError("volatile passphrase file has unsafe type, owner, mode or size")
            chunks = []
            total = 0
            while True:
                chunk = os.read(fd, 2048)
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024:
                    raise CapturePassphraseError("volatile passphrase exceeds 1024 bytes")
                chunks.append(chunk)
            try:
                value = b"".join(chunks).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CapturePassphraseError("volatile passphrase is not valid UTF-8") from exc
            if (not value or any(char in value for char in "\r\n\x00")):
                raise CapturePassphraseError("volatile passphrase is empty or contains a line break")
        finally:
            os.close(fd)
        try:
            os.unlink(path)
        except FileNotFoundError as exc:
            raise CapturePassphraseError("volatile passphrase was concurrently consumed") from exc
        return value


def discard(operation_id: str) -> None:
    """Remove an unconsumed passphrase after failure or cancellation."""
    identifier = _identifier(operation_id)
    try:
        directory = _directory(create=False)
        os.unlink(directory / identifier)
    except FileNotFoundError:
        pass

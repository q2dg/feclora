"""Read protected local credential source files without following links."""
from __future__ import annotations

import os
import stat


class CredentialSourceError(RuntimeError):
    """A protected credential source could not be read safely."""


def read_source_file(path: str, *, owner_uid: int = 0) -> bytes:
    """Read a private, single-link regular file owned by the expected UID."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CredentialSourceError("source file is unavailable or is a symlink") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                or info.st_mode & 0o077 or info.st_nlink != 1
                or info.st_size < 1 or info.st_size > 1024 * 1024):
            raise CredentialSourceError("source must be a root-owned private regular file (1 byte to 1 MiB)")
        chunks, remaining = [], 1024 * 1024 + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if not content or len(content) > 1024 * 1024 or b"\x00" in content:
            raise CredentialSourceError("source file content is invalid or too large")
        return content
    finally:
        os.close(fd)

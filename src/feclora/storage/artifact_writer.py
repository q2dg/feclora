"""Safe, atomic writer for image artifact streams.

The writer stores bytes supplied by a caller; it does not open block devices
or execute imaging commands. SHA-256 and size describe the stored bytes.
"""

from __future__ import annotations

import gzip
import hashlib
import lzma
import os
import re
import secrets
import stat
from typing import BinaryIO

from .image_manifest import ImageArtifact


class ArtifactWriteError(ValueError):
    """Raised when an artifact cannot be safely written."""


_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SUPPORTED_COMPRESSION = {"none", "gzip", "xz"}
_CHUNK_SIZE = 1024 * 1024


class _DigestWriter:
    """Hash and count exactly the bytes accepted by the underlying file."""

    def __init__(self, raw: BinaryIO) -> None:
        self.raw = raw
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        written = self.raw.write(data)
        if written is None:
            written = len(data)
        if written:
            self.digest.update(data[:written])
            self.size += written
        return written

    def flush(self) -> None:
        self.raw.flush()


def write_artifact(
    directory: str | os.PathLike[str],
    filename: str,
    source: BinaryIO,
    *,
    role: str,
    image_format: str,
    compression: str = "none",
    partition_id: str | None = None,
    chunk_size: int = _CHUNK_SIZE,
) -> ImageArtifact:
    """Stream source into a new artifact and atomically publish it.

    The destination directory must already exist and must not itself be a
    symlink. Existing destination files are never replaced. Temporary files
    are created in the destination directory, fsynced, and hard-linked to the
    final name so publication cannot overwrite an existing file.
    """
    if not isinstance(filename, str) or not _FILENAME_RE.fullmatch(filename) or filename in {".", ".."}:
        raise ArtifactWriteError("filename must be a safe basename")
    if compression not in _SUPPORTED_COMPRESSION:
        raise ArtifactWriteError("compression must be one of: none, gzip, xz")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ArtifactWriteError("chunk_size must be a positive integer")
    if not hasattr(source, "read"):
        raise ArtifactWriteError("source must be a binary readable stream")

    directory_path = os.fspath(directory)
    try:
        directory_info = os.lstat(directory_path)
    except OSError as exc:
        raise ArtifactWriteError("destination directory is unavailable") from exc
    if not stat.S_ISDIR(directory_info.st_mode):
        raise ArtifactWriteError("destination must be a real directory, not a symlink")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dir_fd = os.open(directory_path, flags)
    except OSError as exc:
        raise ArtifactWriteError("cannot safely open destination directory") from exc

    temp_name = f".feclora-{secrets.token_hex(16)}.tmp"
    raw_fd = None
    published = False
    source_size = 0
    try:
        raw_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=dir_fd,
        )
        with os.fdopen(raw_fd, "wb", closefd=True) as raw:
            raw_fd = None
            sink = _DigestWriter(raw)
            if compression == "gzip":
                compressor = gzip.GzipFile(filename="", mode="wb", fileobj=sink, mtime=0)
            elif compression == "xz":
                compressor = lzma.LZMAFile(sink, mode="wb")
            else:
                compressor = sink

            try:
                while True:
                    chunk = source.read(chunk_size)
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise ArtifactWriteError("source.read() must return bytes")
                    if not chunk:
                        break
                    source_size += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = compressor.write(view)
                        if written is None or written <= 0:
                            raise ArtifactWriteError("compression stream made no write progress")
                        view = view[written:]
            finally:
                if compressor is not sink:
                    compressor.close()

            if source_size == 0:
                raise ArtifactWriteError("refusing to create an empty artifact")
            raw.flush()
            os.fsync(raw.fileno())

        try:
            os.link(
                temp_name,
                filename,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ArtifactWriteError("destination artifact already exists") from exc
        os.unlink(temp_name, dir_fd=dir_fd)
        os.fsync(dir_fd)
        published = True
        return ImageArtifact(
            filename=filename,
            role=role,
            format=image_format,
            compression=compression,
            size_bytes=sink.size,
            sha256=sink.digest.hexdigest(),
            partition_id=partition_id,
        )
    except ArtifactWriteError:
        raise
    except (OSError, EOFError, lzma.LZMAError) as exc:
        raise ArtifactWriteError(f"artifact write failed: {exc}") from exc
    finally:
        if raw_fd is not None:
            os.close(raw_fd)
        if not published:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
        os.close(dir_fd)

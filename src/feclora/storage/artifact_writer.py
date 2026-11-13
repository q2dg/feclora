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
import subprocess
import tempfile
import shutil
from typing import BinaryIO

from .image_manifest import ImageArtifact


class ArtifactWriteError(ValueError):
    """Raised when an artifact cannot be safely written."""


_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SUPPORTED_COMPRESSION = {"none", "gzip", "xz", "zstd", "lz4"}
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
    compression_level: int | None = None,
    compression_executable: str | None = None,
    partition_id: str | None = None,
    filesystem: str | None = None,
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
        raise ArtifactWriteError("compression must be one of: none, gzip, xz, zstd, lz4")
    if compression == "none" and compression_level is not None:
        raise ArtifactWriteError("compression_level is not valid when compression is none")
    if compression != "none":
        if compression_level is None:
            compression_level = {"gzip": 6, "xz": 6, "zstd": 3, "lz4": 1}[compression]
        if (isinstance(compression_level, bool) or not isinstance(compression_level, int)
                or (compression == "gzip" and not 1 <= compression_level <= 9)
                or (compression == "xz" and not 0 <= compression_level <= 9)
                or (compression == "zstd" and not 1 <= compression_level <= 19)
                or (compression == "lz4" and not 1 <= compression_level <= 12)):
            raise ArtifactWriteError("gzip 1-9, xz 0-9, zstd 1-19, lz4 1-12")
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

    opened_directory = os.fstat(dir_fd)
    if (not stat.S_ISDIR(opened_directory.st_mode)
            or (opened_directory.st_dev, opened_directory.st_ino)
            != (directory_info.st_dev, directory_info.st_ino)):
        os.close(dir_fd)
        raise ArtifactWriteError("destination directory changed during inspection")

    temp_name = f".feclora-{secrets.token_hex(16)}.tmp"
    raw_fd = None
    linked = False
    linked_identity = None
    committed = False
    source_size = 0
    try:
        raw_fd = os.open(
            temp_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=dir_fd,
        )
        with os.fdopen(raw_fd, "w+b", closefd=True) as raw:
            raw_fd = None
            sink = _DigestWriter(raw)
            if compression in {"zstd", "lz4"}:
                executable = compression_executable or shutil.which(compression)
                if not executable:
                    raise ArtifactWriteError(f"{compression} executable is required")
                stderr = tempfile.TemporaryFile(mode="w+b")
                process = None
                try:
                    process = subprocess.Popen(
                        [executable, "-q", "-c", f"-{compression_level}"],
                        stdin=subprocess.PIPE, stdout=raw, stderr=stderr, close_fds=True,
                    )
                    if process.stdin is None:
                        raise ArtifactWriteError(f"{compression} did not provide an input pipe")
                    while True:
                        chunk = source.read(chunk_size)
                        if not isinstance(chunk, (bytes, bytearray)):
                            raise ArtifactWriteError("source.read() must return bytes")
                        if not chunk:
                            break
                        source_size += len(chunk)
                        view = memoryview(chunk)
                        while view:
                            count = process.stdin.write(view)
                            if count is None or count <= 0:
                                raise ArtifactWriteError(f"{compression} input pipe stopped accepting data")
                            view = view[count:]
                    process.stdin.close()
                    result = process.wait()
                    if result != 0:
                        stderr.seek(0)
                        detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
                        raise ArtifactWriteError(f"{compression} exited with status {result}" + (f": {detail}" if detail else ""))
                except OSError as exc:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        process.wait()
                    raise ArtifactWriteError(f"{compression} compression failed: {exc}") from exc
                finally:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        process.wait()
                    stderr.close()
                raw.flush()
                raw.seek(0)
                digest = hashlib.sha256()
                stored_size = 0
                while True:
                    chunk = raw.read(chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    stored_size += len(chunk)
                sink.digest = digest
                sink.size = stored_size
                compressor = sink
            elif compression == "gzip":
                compressor = gzip.GzipFile(filename="", mode="wb", fileobj=sink, compresslevel=compression_level, mtime=0)
            elif compression == "xz":
                compressor = lzma.LZMAFile(sink, mode="wb", preset=compression_level)
            else:
                compressor = sink

            try:
                while compression not in {"zstd", "lz4"}:
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
                if compression not in {"zstd", "lz4"} and compressor is not sink:
                    compressor.close()

            if source_size == 0:
                raise ArtifactWriteError("refusing to create an empty artifact")
            raw.flush()
            os.fsync(raw.fileno())

        temp_info = os.stat(temp_name, dir_fd=dir_fd, follow_symlinks=False)
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
        # Record the exact inode published by this attempt. Rollback must not
        # unlink a different file if another actor replaces the final name.
        linked_identity = (temp_info.st_dev, temp_info.st_ino)
        linked = True
        os.unlink(temp_name, dir_fd=dir_fd)
        os.fsync(dir_fd)
        committed = True
        return ImageArtifact(
            filename=filename,
            role=role,
            format=image_format,
            compression=compression,
            size_bytes=sink.size,
            sha256=sink.digest.hexdigest(),
            partition_id=partition_id,
            filesystem=filesystem,
            compression_level=compression_level,
        )
    except ArtifactWriteError:
        raise
    except (OSError, EOFError, lzma.LZMAError, subprocess.SubprocessError) as exc:
        raise ArtifactWriteError(f"artifact write failed: {exc}") from exc
    finally:
        if raw_fd is not None:
            os.close(raw_fd)
        if not committed and linked:
            try:
                current = os.stat(filename, dir_fd=dir_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == linked_identity:
                    os.unlink(filename, dir_fd=dir_fd)
                    os.fsync(dir_fd)
            except FileNotFoundError:
                pass
            except OSError:
                # Preserve the original failure; a remaining final link is
                # safer than deleting a name we can no longer identify.
                pass
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        os.close(dir_fd)

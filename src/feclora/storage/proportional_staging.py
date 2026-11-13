"""Private, verified RAW staging for future proportional disk transformations.

The source artifact is never opened for writing. The yielded file lives in a
fresh mode-0700 directory and is removed when the context exits. This module
does not shrink filesystems, edit GPT, authorize a target, or restore a disk.
"""
from __future__ import annotations

import hashlib
import fcntl
import lzma
import os
import shutil
import stat
import tempfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .disk_restore import (
    DiskRestoreError,
    _decoded_stream,
    _preflight_decoded_size,
    _verified_artifact_stream,
    _verify_stored_artifact,
)
from .compression import CompressionError
from .image_manifest import ImageManifest
from .gpt_binary import GPTBinaryError, build_gpt_rewrite, inspect_gpt_binary


class ProportionalStagingError(RuntimeError):
    """A verified private staging copy could not be prepared."""


@dataclass(frozen=True)
class StagedRawDiskImage:
    path: str
    size_bytes: int
    sha256: str


@contextmanager
def stage_verified_raw_disk_image(
    manifest: ImageManifest,
    repository: str | os.PathLike[str],
    *,
    staging_root: str | os.PathLike[str] | None = None,
    executables: dict[str, str | None] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    age_passphrase: str | None = None,
) -> Iterator[StagedRawDiskImage]:
    """Decode a verified whole-disk artifact into a private local staging file.

    Both the stored artifact digest and the decoded byte count are checked
    before the staged file is yielded. The source repository must be separate
    from the staging directory. The temporary copy is always removed on exit.
    """
    if not isinstance(manifest, ImageManifest) or manifest.image_type != "disk":
        raise ProportionalStagingError("staging requires a validated whole-disk image manifest")
    artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(artifacts) != 1 or artifacts[0].format != "raw":
        raise ProportionalStagingError("manifest must contain exactly one raw disk-image artifact")
    artifact = artifacts[0]
    if artifact.compression not in {"none", "gzip", "xz", "zstd", "lz4"}:
        raise ProportionalStagingError("unsupported source image compression")

    repo = os.path.realpath(os.fspath(repository))
    try:
        repo_info = os.lstat(repository)
    except OSError as exc:
        raise ProportionalStagingError(f"image repository is unavailable: {exc}") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise ProportionalStagingError("image repository must be a real directory, not a symlink")

    root = os.fspath(staging_root) if staging_root is not None else tempfile.gettempdir()
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise ProportionalStagingError(f"staging root is unavailable: {exc}") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise ProportionalStagingError("staging root must be a real directory, not a symlink")
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath((repo, root_real)) == repo:
            raise ProportionalStagingError("private staging must be outside the image repository")
    except ValueError as exc:
        raise ProportionalStagingError("repository and staging root are on incompatible paths") from exc

    try:
        free_bytes = shutil.disk_usage(root_real).free
    except OSError as exc:
        raise ProportionalStagingError(f"cannot inspect staging capacity: {exc}") from exc
    if free_bytes < manifest.source_size_bytes:
        raise ProportionalStagingError("insufficient free space for a complete private RAW staging copy")

    stage_dir = None
    staged_path = None
    try:
        stage_dir = tempfile.mkdtemp(prefix=".feclora-proportional-", dir=root_real)
        os.chmod(stage_dir, 0o700)
        staged_path = os.path.join(stage_dir, "disk.raw")
        available = executables or {}
        with _verified_artifact_stream(
            repo, artifact, age_identity_file, available.get("age"), age_passphrase
        ) as stored:
            _preflight_decoded_size(stored, artifact, manifest.source_size_bytes, available)
            decoded = _decoded_stream(stored, artifact.compression, available)
            digest = hashlib.sha256()
            total = 0
            fd = os.open(
                staged_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                with os.fdopen(fd, "wb") as output:
                    while True:
                        chunk = decoded.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > manifest.source_size_bytes:
                            raise ProportionalStagingError("decoded image exceeds manifest source size")
                        digest.update(chunk)
                        output.write(chunk)
                    if hasattr(decoded, "finish"):
                        decoded.finish()
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if decoded is not stored:
                    decoded.close()
            if total != manifest.source_size_bytes:
                raise ProportionalStagingError("staged RAW size differs from manifest source size")
            # Re-hash unencrypted source bytes after decoding to detect changes
            # made in place between initial verification and staging. Age
            # ciphertext has already been authenticated before decryption.
            if artifact.encryption == "none":
                # Decoding consumes the stored stream. Rewind before the
                # second integrity pass; otherwise compressed artifacts are
                # incorrectly hashed as an empty stream at EOF.
                stored.seek(0)
                _verify_stored_artifact(stored, artifact)
            info = os.lstat(staged_path)
            if not stat.S_ISREG(info.st_mode) or info.st_size != total or info.st_mode & 0o077:
                raise ProportionalStagingError("staged RAW file failed private-file validation")
            directory_fd = os.open(
                stage_dir,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            yield StagedRawDiskImage(staged_path, total, digest.hexdigest())
    except (DiskRestoreError, CompressionError, OSError, EOFError, lzma.LZMAError, zlib.error) as exc:
        raise ProportionalStagingError(f"could not prepare verified private RAW staging: {exc}") from exc
    finally:
        if staged_path is not None:
            try:
                os.unlink(staged_path)
            except FileNotFoundError:
                pass
        if stage_dir is not None:
            shutil.rmtree(stage_dir, ignore_errors=True)


def apply_gpt_rewrite_to_staged_image(
    staged: StagedRawDiskImage,
    *,
    target_size_bytes: int,
    sector_size: int,
    planned_partitions: tuple[object, ...],
) -> StagedRawDiskImage:
    """Rewrite GPT metadata on one private regular staging file, then verify it.

    This deliberately accepts a staging descriptor rather than a device path.
    Symlinks, hard-linked files, non-regular files and non-private workspaces
    are rejected. The original image repository and all block devices remain
    outside this function's write path.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise ProportionalStagingError("a verified staged RAW image is required")
    if (isinstance(target_size_bytes, bool) or not isinstance(target_size_bytes, int)
            or target_size_bytes <= 0 or target_size_bytes >= staged.size_bytes):
        raise ProportionalStagingError("target size must be smaller than the staged source")
    path = staged.path
    if not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path:
        raise ProportionalStagingError("staged image path is invalid")
    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    directory_fd = -1
    try:
        directory_fd = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent_info = os.fstat(directory_fd)
        if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_mode & 0o077
                or parent_info.st_uid != os.geteuid()):
            raise ProportionalStagingError("staging workspace is not a private owned directory")
        path_info = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(path_info.st_mode) or path_info.st_mode & 0o077
                or path_info.st_nlink != 1 or path_info.st_size != staged.size_bytes
                or path_info.st_uid != os.geteuid()):
            raise ProportionalStagingError("staged image is not a private, single-link regular file")

        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(basename, flags, dir_fd=directory_fd)
        with os.fdopen(fd, "r+b", buffering=0) as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            opened = os.fstat(stream.fileno())
            current_path = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != current_path.st_dev
                    or opened.st_ino != current_path.st_ino or opened.st_nlink != 1
                    or opened.st_size != staged.size_bytes or opened.st_mode & 0o077
                    or opened.st_uid != os.geteuid()):
                raise ProportionalStagingError("staged image identity changed before GPT rewrite")
            digest = hashlib.sha256()
            stream.seek(0)
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if digest.hexdigest() != staged.sha256:
                raise ProportionalStagingError("staged image digest changed before GPT rewrite")

            patches = build_gpt_rewrite(
                stream,
                source_size_bytes=staged.size_bytes,
                target_size_bytes=target_size_bytes,
                sector_size=sector_size,
                planned_partitions=planned_partitions,
            )
            for offset, data in patches:
                if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
                        or not isinstance(data, bytes) or offset + len(data) > target_size_bytes):
                    raise ProportionalStagingError("GPT rewrite produced an out-of-range patch")
            for offset, data in patches:
                stream.seek(offset)
                stream.write(data)
            stream.truncate(target_size_bytes)
            stream.flush()
            os.fsync(stream.fileno())

            verified = inspect_gpt_binary(
                stream, sector_size=sector_size, disk_size_bytes=target_size_bytes
            )
            if not verified.get("primary_backup_consistent"):
                raise ProportionalStagingError("rewritten GPT copies did not validate")
            output_digest = hashlib.sha256()
            stream.seek(0)
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                output_digest.update(chunk)
            os.fsync(stream.fileno())
            return StagedRawDiskImage(path, target_size_bytes, output_digest.hexdigest())
    except (OSError, GPTBinaryError) as exc:
        raise ProportionalStagingError(f"private staged GPT rewrite failed validation: {exc}") from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)

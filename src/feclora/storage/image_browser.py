"""Read-only browsing of manifest-backed whole-disk images using libguestfs.

libguestfs runs filesystem inspection in its isolated appliance. The host never
mounts an untrusted guest filesystem or exposes a loop/NBD device.
"""
from __future__ import annotations

import base64
import json
import os
import posixpath
import shutil
import stat
import struct
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .image_manifest import ImageManifest


class ImageBrowserError(RuntimeError):
    """An image cannot be browsed safely or the requested file is unavailable."""


_MAX_DIRECTORY_ENTRIES = 1000
_MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024
_SUPPORTED_FILESYSTEMS = {"btrfs", "ext2", "ext3", "ext4", "exfat", "fat", "fat12", "fat16", "fat32", "ntfs", "ntfs3", "vfat", "xfs"}
_CACHE_PARENT = Path("/var/cache/feclora")


def _guest_path(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise ImageBrowserError("guest path must be a string of at most 4096 characters")
    path = value if value.startswith("/") else "/" + value
    normalized = posixpath.normpath(path)
    if normalized != path or any(part in {".", ".."} for part in path.split("/")):
        raise ImageBrowserError("guest path must be normalized and must not traverse parent directories")
    return path



def _lstat_without_symlink_traversal(guestfs: Any, path: str) -> dict[str, Any]:
    current = "/"
    components = [part for part in path.split("/") if part]
    metadata = guestfs.lstat("/")
    for index, component in enumerate(components):
        current = posixpath.join(current, component)
        metadata = guestfs.lstat(current)
        mode = metadata.get("mode", 0)
        if stat.S_ISLNK(mode):
            raise ImageBrowserError("symbolic links are not followed while browsing an image")
        if index < len(components) - 1 and not stat.S_ISDIR(mode):
            raise ImageBrowserError("a path component is not a directory")
    return metadata



def _qcow2_header_is_self_contained(path: Path) -> None:
    """Reject backing files and external data files before invoking qemu-img."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            header = stream.read(104)
    except OSError as exc:
        raise ImageBrowserError(f"cannot safely read QCOW2 header: {exc}") from exc
    if len(header) < 72 or header[:4] != b"QFI\xfb":
        raise ImageBrowserError("QCOW2 header is invalid or truncated")
    version = struct.unpack_from(">I", header, 4)[0]
    backing_offset = struct.unpack_from(">Q", header, 8)[0]
    backing_size = struct.unpack_from(">I", header, 16)[0]
    if version not in {2, 3}:
        raise ImageBrowserError("unsupported QCOW2 header version")
    if backing_offset or backing_size:
        raise ImageBrowserError("QCOW2 images with external backing files cannot be browsed")
    if version == 3:
        if len(header) < 104:
            raise ImageBrowserError("QCOW2 v3 header is truncated")
        incompatible_features = struct.unpack_from(">Q", header, 72)[0]
        if incompatible_features & 0x4:
            raise ImageBrowserError("QCOW2 images with external data files cannot be browsed")


def _qcow2_info(path: Path, expected_size: int) -> None:
    executable = shutil.which("qemu-img")
    if not executable:
        raise ImageBrowserError("qemu-img is required to inspect QCOW2 images")
    try:
        result = subprocess.run(
            [executable, "info", "--output=json", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageBrowserError(f"cannot inspect QCOW2 image: {exc}") from exc
    if result.returncode != 0:
        raise ImageBrowserError("qemu-img rejected the QCOW2 image")
    try:
        info = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ImageBrowserError("qemu-img returned invalid QCOW2 metadata") from exc
    if (not isinstance(info, dict) or info.get("format") != "qcow2"
            or isinstance(info.get("virtual-size"), bool)
            or not isinstance(info.get("virtual-size"), int)
            or info["virtual-size"] != expected_size):
        raise ImageBrowserError("QCOW2 format or virtual capacity does not match the image manifest")
    if any(info.get(key) for key in ("backing-filename", "full-backing-filename", "data-file")):
        raise ImageBrowserError("QCOW2 images with external backing or data files cannot be browsed")



def _session_directory(
    manifest: ImageManifest, artifact: Any, partition_index: int,
    session_id: str | None,
) -> tuple[str, Path, bool]:
    if session_id is None:
        session_id = str(uuid.uuid4())
        created = True
    else:
        try:
            normalized = str(uuid.UUID(session_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ImageBrowserError("browser session identifier is invalid") from exc
        if normalized != session_id:
            raise ImageBrowserError("browser session identifier is invalid")
        created = False

    parent = _CACHE_PARENT
    cache_root = parent / "image-browser"
    try:
        parent.mkdir(mode=0o700, parents=False, exist_ok=True)
        parent_info = os.lstat(parent)
        if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
                or parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o077):
            raise ImageBrowserError("image browser cache parent must be a private root-owned directory")
        cache_root.mkdir(mode=0o700, exist_ok=True)
        root_info = os.lstat(cache_root)
        if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
                or root_info.st_uid != os.geteuid() or root_info.st_mode & 0o077):
            raise ImageBrowserError("image browser cache must be a private root-owned directory")
        directory = cache_root / session_id
        if created:
            directory.mkdir(mode=0o700)
            metadata = {
                "schema_version": 1, "image_id": manifest.image_id,
                "artifact_sha256": artifact.sha256,
                "source_size_bytes": manifest.source_size_bytes,
                "partition_index": partition_index,
            }
            fd = os.open(directory / "session.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        else:
            directory_info = os.lstat(directory)
            if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                    or directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o077):
                raise ImageBrowserError("browser session directory is unavailable or unsafe")
            metadata_path = directory / "session.json"
            metadata_info = os.lstat(metadata_path)
            if (not stat.S_ISREG(metadata_info.st_mode) or stat.S_ISLNK(metadata_info.st_mode)
                    or metadata_info.st_uid != os.geteuid() or metadata_info.st_mode & 0o077):
                raise ImageBrowserError("browser session metadata is unavailable or unsafe")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            expected = {
                "schema_version": 1, "image_id": manifest.image_id,
                "artifact_sha256": artifact.sha256,
                "source_size_bytes": manifest.source_size_bytes,
                "partition_index": partition_index,
            }
            if metadata != expected:
                raise ImageBrowserError("browser session does not match the selected image and partition")
            os.utime(metadata_path, None)
        os.utime(directory, None)
        return session_id, directory, created
    except ImageBrowserError:
        raise
    except OSError as exc:
        raise ImageBrowserError(f"cannot create or open private image browser session: {exc}") from exc


def _prepare_image(
    manifest: ImageManifest, repository: Path, temporary: Path,
    age_identity_file: str | os.PathLike[str] | None,
) -> tuple[Path, str]:
    disks = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disks) != 1 or disks[0].format not in {"raw", "qcow2"}:
        raise ImageBrowserError("browsing requires exactly one RAW or QCOW2 whole-disk artifact")
    artifact = disks[0]
    source = repository / artifact.filename
    try:
        info = os.lstat(source)
    except OSError as exc:
        raise ImageBrowserError("disk image artifact is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise ImageBrowserError("disk image artifact must be a root-owned regular file")
    if artifact.format == "qcow2":
        if artifact.compression != "none" or artifact.encryption != "none":
            raise ImageBrowserError("QCOW2 artifact must not use separate compression or encryption")
        from .disk_restore import _open_artifact, _verify_stored_artifact
        try:
            with _open_artifact(str(repository), artifact) as stream:
                _verify_stored_artifact(stream, artifact)
        except Exception as exc:
            raise ImageBrowserError(f"QCOW2 image integrity verification failed: {exc}") from exc
        _qcow2_header_is_self_contained(source)
        _qcow2_info(source, manifest.source_size_bytes)
        return source, "qcow2"

    if artifact.compression == "none" and artifact.encryption == "none":
        from .disk_restore import _open_artifact, _verify_stored_artifact
        try:
            with _open_artifact(str(repository), artifact) as stream:
                _verify_stored_artifact(stream, artifact)
        except Exception as exc:
            raise ImageBrowserError(f"RAW image integrity verification failed: {exc}") from exc
        if info.st_size != manifest.source_size_bytes:
            raise ImageBrowserError("RAW image size does not match the manifest source capacity")
        return source, "raw"

    from .disk_restore import _decoded_stream, _preflight_decoded_size, _verified_artifact_stream
    if shutil.disk_usage(temporary).free < manifest.source_size_bytes:
        raise ImageBrowserError("insufficient temporary storage to decode the RAW image")
    staged = temporary / "disk.raw"
    try:
        if os.path.lexists(staged):
            cached = os.lstat(staged)
            if (stat.S_ISREG(cached.st_mode) and cached.st_uid == os.geteuid()
                    and cached.st_size == manifest.source_size_bytes):
                return staged, "raw"
            os.unlink(staged)
        partial = temporary / f"disk.raw.{uuid.uuid4().hex}.partial"
        with _verified_artifact_stream(str(repository), artifact, age_identity_file) as stored:
            _preflight_decoded_size(stored, artifact, manifest.source_size_bytes)
            decoded = _decoded_stream(stored, artifact.compression)
            try:
                with partial.open("xb") as output:
                    shutil.copyfileobj(decoded, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if hasattr(decoded, "finish"):
                    decoded.finish()
            finally:
                if decoded is not stored:
                    decoded.close()
        if partial.stat().st_size != manifest.source_size_bytes:
            raise ImageBrowserError("decoded RAW image size does not match the manifest")
        os.chmod(partial, 0o600)
        os.replace(partial, staged)
    except Exception as exc:
        try:
            if "partial" in locals():
                partial.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, ImageBrowserError):
            raise
        raise ImageBrowserError(f"cannot prepare verified RAW image for browsing: {exc}") from exc
    return staged, "raw"



def browse_image(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    partition_index: int,
    guest_path: str = "/",
    *,
    download: bool = False,
    expected_partition_count: int | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Browse one directory or download one bounded regular file in a cached session."""
    repo = Path(repository)
    try:
        manifest = ImageManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ImageBrowserError(f"cannot load image manifest: {exc}") from exc
    if manifest.image_type != "disk":
        raise ImageBrowserError("browsing requires a whole-disk image")
    if isinstance(partition_index, bool) or not isinstance(partition_index, int) or partition_index < 1:
        raise ImageBrowserError("partition index must be a positive integer")
    path = _guest_path(guest_path)
    disks = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disks) != 1:
        raise ImageBrowserError("browsing requires exactly one whole-disk artifact")
    session_id, session_directory, created_session = _session_directory(
        manifest, disks[0], partition_index, session_id,
    )

    guestfs = None
    download_path = None
    try:
        image_path, image_format = _prepare_image(
            manifest, repo, session_directory, age_identity_file,
        )
        if image_path.parent == session_directory:
            os.utime(image_path, None)
        try:
            import guestfs as guestfs_module
        except ImportError as exc:
            raise ImageBrowserError("python3-libguestfs is required for image browsing") from exc
        guestfs = guestfs_module.GuestFS(python_return_dict=True)
        guestfs.add_drive_opts(str(image_path), readonly=1, format=image_format)
        guestfs.launch()
        partitions = guestfs.list_partitions()
        if expected_partition_count is not None and len(partitions) != expected_partition_count:
            raise ImageBrowserError("guest partition enumeration does not match the verified partition table")
        if partition_index > len(partitions):
            raise ImageBrowserError("selected partition does not exist in the image")
        device = partitions[partition_index - 1]
        filesystems = guestfs.list_filesystems()
        filesystem = filesystems.get(device)
        if not filesystem or filesystem not in _SUPPORTED_FILESYSTEMS:
            raise ImageBrowserError("selected partition has no supported, recognizable filesystem")
        guestfs.mount_ro(device, "/")
        metadata = _lstat_without_symlink_traversal(guestfs, path)
        mode = metadata.get("mode", 0)
        if download:
            if not stat.S_ISREG(mode):
                raise ImageBrowserError("only regular files can be downloaded; directories and symbolic links are not followed")
            size = metadata.get("size")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > _MAX_DOWNLOAD_BYTES:
                raise ImageBrowserError("file exceeds the 16 MiB per-download limit")
            download_path = session_directory / f".download-{uuid.uuid4().hex}"
            guestfs.download(path, str(download_path))
            data = download_path.read_bytes()
            if len(data) != size:
                raise ImageBrowserError("downloaded file size changed during extraction")
            return {
                "session_id": session_id, "partition": device,
                "filesystem": filesystem, "path": path, "size_bytes": size,
                "filename": posixpath.basename(path) or "image-file",
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        if not stat.S_ISDIR(mode):
            raise ImageBrowserError("selected path is not a directory")
        names = sorted(name for name in guestfs.ls(path) if name not in {".", ".."})
        if len(names) > _MAX_DIRECTORY_ENTRIES:
            raise ImageBrowserError("directory contains more than 1000 entries; open a narrower directory")
        entries = []
        for name in names:
            child = posixpath.join(path, name)
            try:
                child_info = _lstat_without_symlink_traversal(guestfs, child)
            except Exception:
                continue
            child_mode = child_info.get("mode", 0)
            kind = (
                "directory" if stat.S_ISDIR(child_mode) else
                "file" if stat.S_ISREG(child_mode) else
                "symlink" if stat.S_ISLNK(child_mode) else "other"
            )
            entries.append({
                "name": name, "path": child, "kind": kind,
                "size_bytes": child_info.get("size", 0) if kind == "file" else None,
            })
        return {
            "session_id": session_id, "partition": device,
            "filesystem": filesystem, "path": path, "entries": entries,
        }
    except ImageBrowserError:
        if created_session:
            shutil.rmtree(session_directory, ignore_errors=True)
        raise
    except Exception as exc:
        if created_session:
            shutil.rmtree(session_directory, ignore_errors=True)
        raise ImageBrowserError(f"read-only filesystem inspection failed: {exc}") from exc
    finally:
        if download_path is not None:
            download_path.unlink(missing_ok=True)
        if guestfs is not None:
            try:
                guestfs.shutdown()
            finally:
                guestfs.close()

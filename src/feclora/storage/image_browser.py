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
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .image_manifest import ImageManifest


class ImageBrowserError(RuntimeError):
    """An image cannot be browsed safely or the requested file is unavailable."""


_MAX_DIRECTORY_ENTRIES = 1000
_MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024


def _guest_path(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise ImageBrowserError("guest path must be a string of at most 4096 characters")
    path = value if value.startswith("/") else "/" + value
    normalized = posixpath.normpath(path)
    if normalized != path or any(part in {".", ".."} for part in path.split("/")):
        raise ImageBrowserError("guest path must be normalized and must not traverse parent directories")
    return path


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
        _qcow2_info(source, manifest.source_size_bytes)
        return source, "qcow2"

    if artifact.compression == "none" and artifact.encryption == "none":
        from .disk_restore import _open_artifact, _verify_stored_artifact
        try:
            with _open_artifact(str(repository), artifact) as stream:
                _verify_stored_artifact(stream, artifact)
        except Exception as exc:
            raise ImageBrowserError(f"RAW image integrity verification failed: {exc}") from exc
        return source, "raw"

    from .disk_restore import _decoded_stream, _preflight_decoded_size, _verified_artifact_stream
    staged = temporary / "disk.raw"
    try:
        with _verified_artifact_stream(str(repository), artifact, age_identity_file) as stored:
            _preflight_decoded_size(stored, artifact, manifest.source_size_bytes)
            decoded = _decoded_stream(stored, artifact.compression)
            try:
                with staged.open("xb") as output:
                    shutil.copyfileobj(decoded, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if hasattr(decoded, "finish"):
                    decoded.finish()
            finally:
                if decoded is not stored:
                    decoded.close()
    except Exception as exc:
        raise ImageBrowserError(f"cannot prepare verified RAW image for browsing: {exc}") from exc
    if staged.stat().st_size != manifest.source_size_bytes:
        raise ImageBrowserError("decoded RAW image size does not match the manifest")
    return staged, "raw"


def browse_image(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    partition_index: int,
    guest_path: str = "/",
    *,
    download: bool = False,
    age_identity_file: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """List one directory or return one bounded regular file from a disk image."""
    repo = Path(repository)
    try:
        raw_manifest = Path(manifest_path).read_text(encoding="utf-8")
        manifest = ImageManifest.from_json(raw_manifest)
    except Exception as exc:
        raise ImageBrowserError(f"cannot load image manifest: {exc}") from exc
    if manifest.image_type != "disk":
        raise ImageBrowserError("browsing requires a whole-disk image")
    if isinstance(partition_index, bool) or not isinstance(partition_index, int) or partition_index < 1:
        raise ImageBrowserError("partition index must be a positive integer")
    path = _guest_path(guest_path)

    guestfs = None
    try:
        import guestfs as guestfs_module
    except ImportError as exc:
        raise ImageBrowserError("python3-libguestfs is required for image browsing") from exc

    with tempfile.TemporaryDirectory(prefix="feclora-image-browser-") as temporary_name:
        temporary = Path(temporary_name)
        os.chmod(temporary, 0o700)
        image_path, image_format = _prepare_image(
            manifest, repo, temporary, age_identity_file,
        )
        try:
            guestfs = guestfs_module.GuestFS(python_return_dict=True)
            guestfs.add_drive_opts(
                str(image_path), readonly=1, format=image_format,
                discard="disable", cachemode="unsafe",
            )
            guestfs.launch()
            partitions = guestfs.list_partitions()
            if partition_index > len(partitions):
                raise ImageBrowserError("selected partition does not exist in the image")
            device = partitions[partition_index - 1]
            filesystems = guestfs.list_filesystems()
            filesystem = filesystems.get(device)
            if not filesystem or filesystem == "unknown":
                raise ImageBrowserError("selected partition has no supported, recognizable filesystem")
            guestfs.mount_ro(device, "/")
            metadata = guestfs.lstat(path)
            mode = metadata.get("mode", 0)
            if download:
                if not stat.S_ISREG(mode):
                    raise ImageBrowserError("only regular files can be downloaded; directories and symbolic links are not followed")
                size = metadata.get("size")
                if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > _MAX_DOWNLOAD_BYTES:
                    raise ImageBrowserError("file exceeds the 16 MiB per-download limit")
                destination = temporary / "download.bin"
                guestfs.download(path, str(destination))
                data = destination.read_bytes()
                if len(data) != size:
                    raise ImageBrowserError("downloaded file size changed during extraction")
                return {
                    "partition": device, "filesystem": filesystem,
                    "path": path, "size_bytes": size,
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
                    child_info = guestfs.lstat(child)
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
                "partition": device, "filesystem": filesystem,
                "path": path, "entries": entries,
            }
        except ImageBrowserError:
            raise
        except Exception as exc:
            raise ImageBrowserError(f"read-only filesystem inspection failed: {exc}") from exc
        finally:
            if guestfs is not None:
                try:
                    guestfs.shutdown()
                finally:
                    guestfs.close()

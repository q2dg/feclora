"""Import a verified P2V QCOW2 into Feclora's native whole-disk image format."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.storage.image_manifest import ImageArtifact, ImageManifest
from feclora.storage.image_publication import publish_image_set


class P2VImportError(RuntimeError):
    """A P2V QCOW2 could not be safely imported as a Feclora image."""


def _run(argv: list[str], runner: Callable[..., Any]) -> Any:
    try:
        result = runner(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=24 * 60 * 60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise P2VImportError(f"could not execute {Path(argv[0]).name}: {exc}") from exc
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise P2VImportError(f"{Path(argv[0]).name} failed" + (f": {detail[:512]}" if detail else ""))
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_p2v_qcow2(
    repository: str | os.PathLike[str],
    source_image_id: str,
    image_id: str,
    *,
    qemu_img: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> ImageManifest:
    """Convert a committed P2V QCOW2 into a manifest-backed raw disk image.

    The source QCOW2 and its sidecar remain unchanged. The imported image is a
    new native Feclora image set, published manifest-last without replacement.
    Partition-table metadata is marked unknown: this import preserves sectors
    but does not claim to have repaired guest boot drivers or firmware settings.
    """
    for value, label in ((source_image_id, "source_image_id"), (image_id, "image_id")):
        if (not isinstance(value, str) or not value
                or len(value) > 128 or not value[0].isalnum()
                or any(not (ch.isalnum() or ch in "_.-") for ch in value)):
            raise P2VImportError(f"{label} is invalid")
    if source_image_id == image_id:
        raise P2VImportError("imported image_id must differ from the source P2V image_id")
    repo = Path(repository)
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise P2VImportError("image repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode):
        raise P2VImportError("image repository must be a real directory")
    source = repo / f"{source_image_id}.qcow2"
    sidecar = repo / f"{source_image_id}.p2v.json"
    try:
        for path in (source, sidecar):
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise P2VImportError("P2V source and metadata must be regular files")
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except P2VImportError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise P2VImportError("cannot read committed P2V image and metadata") from exc
    required_metadata = {
        "schema_version", "image_id", "format", "source_device", "virtual_size_bytes",
        "logical_sector_size", "file_size_bytes", "qcow2_sha256", "verified", "bootability_note",
    }
    if (not isinstance(metadata, dict) or set(metadata) != required_metadata
            or isinstance(metadata.get("schema_version"), bool) or metadata.get("schema_version") != 1
            or metadata.get("image_id") != source_image_id or metadata.get("format") != "qcow2"
            or metadata.get("verified") is not True
            or not isinstance(metadata.get("source_device"), str)
            or not metadata["source_device"].startswith("/dev/")
            or not isinstance(metadata.get("bootability_note"), str)
            or metadata.get("file_size_bytes") != source.stat().st_size
            or metadata.get("qcow2_sha256") != _sha256(source)):
        raise P2VImportError("P2V sidecar does not match the QCOW2 source")
    virtual_size = metadata.get("virtual_size_bytes")
    if isinstance(virtual_size, bool) or not isinstance(virtual_size, int) or virtual_size <= 0:
        raise P2VImportError("P2V sidecar has an invalid virtual disk size")
    logical_sector_size = metadata.get("logical_sector_size")
    if isinstance(logical_sector_size, bool) or logical_sector_size not in {512, 4096}:
        raise P2VImportError("P2V sidecar has an invalid or missing logical sector size")
    names = [f"{image_id}.disk.raw", f"{image_id}.sfdisk", f"{image_id}.manifest.json"]
    if any(os.path.lexists(repo / name) for name in names):
        raise P2VImportError("imported Feclora image identifier already exists")
    qemu_img = qemu_img or shutil.which("qemu-img")
    if not qemu_img:
        raise P2VImportError("qemu-img is required for P2V import")
    try:
        available_bytes = shutil.disk_usage(repo).free
    except OSError as exc:
        raise P2VImportError(f"cannot check P2V import repository capacity: {exc}") from exc
    required_bytes = virtual_size + 64 * 1024 * 1024
    if available_bytes < required_bytes:
        raise P2VImportError(f"insufficient repository capacity: need {required_bytes} bytes, have {available_bytes}")
    stage = Path(tempfile.mkdtemp(prefix=".feclora-p2v-import-", dir=repo))
    os.chmod(stage, 0o700)
    try:
        _run([qemu_img, "check", "-f", "qcow2", str(source)], runner)
        info_result = _run([qemu_img, "info", "--output=json", str(source)], runner)
        try:
            info = json.loads(info_result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise P2VImportError("qemu-img returned invalid source metadata") from exc
        if (not isinstance(info, dict) or info.get("format") != "qcow2"
                or info.get("virtual-size") != virtual_size
                or info.get("backing-filename") or info.get("full-backing-filename")
                or info.get("data-file") or info.get("encrypted") is True):
            raise P2VImportError("QCOW2 format, dependencies or virtual capacity disagree with its sidecar")
        raw_path = stage / names[0]
        _run([qemu_img, "convert", "-p", "-f", "qcow2", "-O", "raw", str(source), str(raw_path)], runner)
        raw_info = os.lstat(raw_path)
        if not stat.S_ISREG(raw_info.st_mode) or stat.S_ISLNK(raw_info.st_mode) or raw_info.st_size != virtual_size:
            raise P2VImportError("raw conversion did not preserve the declared virtual disk capacity")
        os.chmod(raw_path, 0o600)
        with raw_path.open("rb") as stream:
            os.fsync(stream.fileno())
        disk_artifact = ImageArtifact(
            filename=names[0], role="disk-image", format="raw", compression="none",
            size_bytes=raw_info.st_size, sha256=_sha256(raw_path),
        )
        table_text = (
            "# Imported from a verified P2V QCOW2; partition-table type is not independently inspected.\n"
            "# Raw sectors are preserved. Guest boot repair and BIOS/UEFI compatibility require separate validation.\n"
        )
        import io
        from feclora.storage.artifact_writer import write_artifact
        table_artifact = write_artifact(
            stage, names[1], io.BytesIO(table_text.encode("utf-8")),
            role="partition-table", image_format="raw",
        )
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id, "image_type": "disk",
            "source_size_bytes": virtual_size, "logical_sector_size": logical_sector_size,
            "partition_table": "unknown",
            "artifacts": [disk_artifact.to_dict(), table_artifact.to_dict()],
        })
        manifest_path = stage / names[2]
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(manifest.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        publish_image_set(repo, stage, names)
        return manifest
    except Exception:
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

"""Build a self-contained recovery ISO without modifying its Live base.

The builder copies verified Feclora image artifacts and a narrowly-scoped
recovery answer into a new ISO filesystem tree, asking xorriso to replay the
source ISO's El Torito boot configuration. It never writes to block devices.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError


class RecoveryISOError(ValueError):
    """Recovery ISO input or assembly failed closed."""


_IMAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WWN_RE = re.compile(r"^[A-Za-z0-9_.:-]{4,128}$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9_.:+/-]{1,128}$")
_MAX_ANSWER_BYTES = 64 * 1024


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RecoveryISOError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RecoveryISOError(f"{label} must be a regular non-symlink file")
    return info


def _read_answer(path: Path, image_id: str) -> bytes:
    info = _regular_file(path, "recovery answer")
    if info.st_size <= 0 or info.st_size > _MAX_ANSWER_BYTES:
        raise RecoveryISOError("recovery answer must be non-empty and at most 64 KiB")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryISOError(f"recovery answer is not valid UTF-8 JSON: {exc}") from exc
    except RecoveryISOError:
        raise
    if not isinstance(value, dict):
        raise RecoveryISOError("recovery answer must be a JSON object")
    required = {"schema_version", "operation", "image_id", "target", "confirm_destructive", "start"}
    if set(value) != required:
        raise RecoveryISOError("recovery answer has missing or unknown fields")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise RecoveryISOError("unsupported recovery answer schema_version")
    if value["operation"] != "restore" or value["image_id"] != image_id:
        raise RecoveryISOError("recovery answer must target the selected restore image")
    if not isinstance(value["image_id"], str) or not _IMAGE_ID_RE.fullmatch(value["image_id"]):
        raise RecoveryISOError("recovery answer image_id is invalid")
    target = value["target"]
    if not isinstance(target, dict) or set(target) != {"wwn", "serial"}:
        raise RecoveryISOError("target must contain exactly wwn and serial selectors")
    wwn, serial = target["wwn"], target["serial"]
    if wwn is not None and (not isinstance(wwn, str) or not _WWN_RE.fullmatch(wwn)):
        raise RecoveryISOError("target.wwn is invalid")
    if serial is not None and (not isinstance(serial, str) or not _SERIAL_RE.fullmatch(serial)):
        raise RecoveryISOError("target.serial is invalid")
    if wwn is None and serial is None:
        raise RecoveryISOError("target requires a WWN and/or serial selector")
    if value["confirm_destructive"] is not True or value["start"] is not True:
        raise RecoveryISOError("recovery restore requires explicit destructive confirmation and start")
    canonical = {
        "schema_version": 1, "operation": "restore", "image_id": image_id,
        "target": {"wwn": wwn, "serial": serial},
        "confirm_destructive": True, "start": True,
    }
    return (json.dumps(canonical, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryISOError(f"duplicate recovery answer field: {key}")
        result[key] = value
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise RecoveryISOError(f"cannot read image artifact {path.name}: {exc}") from exc
    return digest.hexdigest()


def _run(argv: list[str], runner: Callable[..., Any]) -> str:
    try:
        result = runner(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=24 * 60 * 60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryISOError(f"could not execute xorriso: {exc}") from exc
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise RecoveryISOError("xorriso failed" + (f": {detail[:512]}" if detail else ""))
    return (getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")


def _require_el_torito(report: str, label: str) -> None:
    if "El Torito" not in report and "El-Torito" not in report and "boot catalog" not in report.lower():
        raise RecoveryISOError(f"{label} does not report an El Torito boot catalog")


def build_recovery_iso(
    base_iso: str,
    image_directory: str,
    manifest_path: str,
    answer_path: str,
    output_path: str,
    *,
    xorriso: str = "/usr/bin/xorriso",
    runner: Callable[..., Any] = subprocess.run,
    free_bytes: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Assemble a verified recovery image set into a new bootable ISO file."""
    base = Path(base_iso)
    image_dir = Path(image_directory)
    manifest_file = Path(manifest_path)
    answer_file = Path(answer_path)
    output = Path(output_path)
    base_info = _regular_file(base, "base Live ISO")
    if not base.is_absolute() or not image_dir.is_absolute() or not output.is_absolute():
        raise RecoveryISOError("base ISO, image directory and output path must be absolute")
    try:
        directory_info = os.lstat(image_dir)
        output_parent_info = os.lstat(output.parent)
    except OSError as exc:
        raise RecoveryISOError(f"cannot inspect recovery ISO directories: {exc}") from exc
    if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
            or not stat.S_ISDIR(output_parent_info.st_mode) or stat.S_ISLNK(output_parent_info.st_mode)):
        raise RecoveryISOError("image directory and output parent must be real directories")
    if output.suffix.lower() != ".iso" or output.name in {"", ".", ".."}:
        raise RecoveryISOError("output must be an .iso file")
    if os.path.lexists(output):
        raise RecoveryISOError("refusing to overwrite an existing recovery ISO")
    manifest_info = _regular_file(manifest_file, "image manifest")
    if manifest_info.st_size <= 0 or manifest_info.st_size > 1024 * 1024:
        raise RecoveryISOError("image manifest must be non-empty and at most 1 MiB")
    try:
        manifest = ImageManifest.from_json(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise RecoveryISOError(f"image manifest is invalid: {exc}") from exc
    answer = _read_answer(answer_file, manifest.image_id)

    artifacts: list[tuple[Path, str]] = []
    payload_bytes = len(answer) + manifest_info.st_size
    for artifact in manifest.artifacts:
        source = image_dir / artifact.filename
        info = _regular_file(source, f"image artifact {artifact.filename}")
        if info.st_size != artifact.size_bytes:
            raise RecoveryISOError(f"image artifact size does not match manifest: {artifact.filename}")
        if _sha256(source) != artifact.sha256:
            raise RecoveryISOError(f"image artifact SHA-256 does not match manifest: {artifact.filename}")
        payload_bytes += info.st_size
        artifacts.append((source, artifact.filename))

    if free_bytes is None:
        free_bytes = lambda directory: shutil.disk_usage(directory).free
    required_bytes = base_info.st_size + payload_bytes + max(64 * 1024 * 1024, base_info.st_size // 100)
    try:
        available = free_bytes(str(output.parent))
    except OSError as exc:
        raise RecoveryISOError(f"cannot check output filesystem capacity: {exc}") from exc
    if available < required_bytes:
        raise RecoveryISOError(
            f"insufficient output capacity: need at least {required_bytes} bytes, have {available}"
        )

    xorriso_path = shutil.which(xorriso) if "/" not in xorriso else xorriso
    if not xorriso_path or not os.path.isfile(xorriso_path) or not os.access(xorriso_path, os.X_OK):
        raise RecoveryISOError("xorriso executable is not available")
    base_report = _run([xorriso_path, "-indev", str(base), "-report_el_torito", "plain"], runner)
    _require_el_torito(base_report, "base Live ISO")

    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".feclora-recovery-", suffix=".iso", dir=output.parent)
        os.close(fd)
        os.chmod(temp_path, 0o600)
        command = [
            xorriso_path, "-indev", str(base), "-outdev", temp_path,
            "-mkdir", "/FECLORA", "-mkdir", "/FECLORA/RECOVERY",
        ]
        for source, filename in artifacts:
            command.extend(["-map", str(source), f"/FECLORA/RECOVERY/{filename}"])
        command.extend([
            "-map", str(manifest_file), "/FECLORA/RECOVERY/manifest.json",
            "-map", str(answer_file), "/FECLORA/RECOVERY/answer.json",
            "-boot_image", "any", "replay", "-commit",
        ])
        _run(command, runner)
        output_report = _run([
            xorriso_path, "-indev", temp_path, "-report_el_torito", "plain",
            "-find", "/FECLORA/RECOVERY", "-type", "f", "-exec", "lsdl",
        ], runner)
        _require_el_torito(output_report, "assembled recovery ISO")
        for filename in [item[1] for item in artifacts] + ["manifest.json", "answer.json"]:
            if filename not in output_report:
                raise RecoveryISOError(f"assembled ISO is missing embedded file {filename}")
        output_fd = os.open(temp_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
        os.link(temp_path, output)
        output_info = os.stat(output, follow_symlinks=False)
        return {
            "image_id": manifest.image_id,
            "output_path": str(output),
            "file_size_bytes": output_info.st_size,
            "payload_size_bytes": payload_bytes,
            "sha256": _sha256(output),
            "verified": True,
            "boot_catalog_preserved": True,
        }
    except FileExistsError as exc:
        raise RecoveryISOError("refusing to overwrite an existing recovery ISO") from exc
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

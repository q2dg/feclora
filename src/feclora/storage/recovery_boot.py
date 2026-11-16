"""Discover and execute a self-contained recovery ISO payload at Live boot.

The mounted recovery medium is treated as read-only. The embedded answer is
strictly validated, the image manifest is checked, and the destination is
resolved by stable WWN/serial identity again immediately before writing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.restore_profile import RestoreTargetSelector
from feclora.storage.inventory import collect_inventory
from feclora.deployment.restore_execution import execute_restore
from feclora.storage.operation_log import operation_record, record_progress
from feclora.network.pxe_answer_client import _flatten_devices, _wait_for_age_passphrase


class RecoveryBootError(RuntimeError):
    """A mounted recovery payload is invalid or its restore failed."""


MEDIA_ROOTS = (
    Path("/run/initramfs/live"),
    Path("/run/live/medium"),
    Path("/mnt/live"),
)
PAYLOAD = Path("FECLORA/RECOVERY")
MAX_ANSWER = 64 * 1024
MAX_MANIFEST = 1024 * 1024


def discover_payload(roots: tuple[Path, ...] = MEDIA_ROOTS) -> Path | None:
    """Return exactly one mounted recovery payload; never mount or modify media."""
    found: list[Path] = []
    for root in roots:
        try:
            info = os.stat(root, follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            continue
        candidate = root / PAYLOAD
        try:
            candidate_info = os.stat(candidate, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISDIR(candidate_info.st_mode):
            found.append(candidate)
    unique = list(dict.fromkeys(found))
    if len(unique) > 1:
        raise RecoveryBootError("multiple recovery ISO payloads are mounted; refusing ambiguous restore")
    return unique[0] if unique else None


def _read_regular(directory: Path, name: str, maximum: int) -> bytes:
    path = directory / name
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RecoveryBootError(f"recovery {name} must be a regular non-symlink file")
        if info.st_size <= 0 or info.st_size > maximum:
            raise RecoveryBootError(f"recovery {name} has an invalid size")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(maximum + 1)
    except RecoveryBootError:
        raise
    except OSError as exc:
        raise RecoveryBootError(f"cannot safely read recovery {name}: {exc}") from exc
    if len(raw) > maximum:
        raise RecoveryBootError(f"recovery {name} exceeds its size limit")
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryBootError(f"duplicate recovery answer field: {key}")
        result[key] = value
    return result


def _load_answer(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular(directory, "answer.json", MAX_ANSWER).decode("utf-8"),
                           object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryBootError(f"recovery answer is not valid UTF-8 JSON: {exc}") from exc
    required = {"schema_version", "operation", "image_id", "target", "confirm_destructive", "start"}
    if not isinstance(value, dict) or set(value) != required:
        raise RecoveryBootError("recovery answer has missing or unknown fields")
    if (isinstance(value["schema_version"], bool) or value["schema_version"] != 1
            or value["operation"] != "restore" or value["confirm_destructive"] is not True
            or value["start"] is not True):
        raise RecoveryBootError("recovery answer does not explicitly authorize schema-v1 restore")
    image_id = value["image_id"]
    if (not isinstance(image_id, str) or not image_id
            or len(image_id) > 128
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in image_id)):
        raise RecoveryBootError("recovery image_id is invalid")
    target = value["target"]
    if not isinstance(target, dict) or set(target) != {"wwn", "serial"}:
        raise RecoveryBootError("recovery target must contain exactly WWN and serial selectors")
    try:
        selector = RestoreTargetSelector(**target)
    except (TypeError, ValueError) as exc:
        raise RecoveryBootError(f"recovery target selector is invalid: {exc}") from exc
    return {"image_id": image_id, "selector": selector}


def _load_manifest(directory: Path, image_id: str) -> ImageManifest:
    try:
        manifest = ImageManifest.from_json(_read_regular(directory, "manifest.json", MAX_MANIFEST).decode("utf-8"))
    except (UnicodeError, ManifestValidationError) as exc:
        raise RecoveryBootError(f"embedded recovery manifest is invalid: {exc}") from exc
    if manifest.image_id != image_id or manifest.image_type != "disk":
        raise RecoveryBootError("embedded manifest is not the selected whole-disk image")
    for artifact in manifest.artifacts:
        if artifact.encryption not in {"none", "age"}:
            raise RecoveryBootError("embedded image uses unsupported encryption")
        artifact_path = directory / artifact.filename
        try:
            artifact_info = os.lstat(artifact_path)
        except OSError as exc:
            raise RecoveryBootError(f"cannot inspect embedded artifact {artifact.filename}: {exc}") from exc
        if (not stat.S_ISREG(artifact_info.st_mode) or stat.S_ISLNK(artifact_info.st_mode)
                or artifact_info.st_size != artifact.size_bytes):
            raise RecoveryBootError(f"embedded artifact type or size does not match manifest: {artifact.filename}")
    return manifest


def _resolve(selector: RestoreTargetSelector) -> tuple[str, dict[str, Any]]:
    try:
        inventory = collect_inventory()
    except Exception as exc:
        raise RecoveryBootError(f"cannot inventory disks for recovery: {exc}") from exc
    matches = [item for item in _flatten_devices(inventory.get("devices"))
               if item.get("type") == "disk" and selector.matches(item)]
    if len(matches) != 1:
        raise RecoveryBootError(f"recovery target selector matched {len(matches)} whole disks; exactly one is required")
    path = matches[0].get("path")
    if not isinstance(path, str) or not path.startswith("/dev/"):
        raise RecoveryBootError("resolved recovery target has no valid device path")
    return path, matches[0]


def _revalidate(selector: RestoreTargetSelector, expected_path: str) -> None:
    path, _device = _resolve(selector)
    if path != expected_path:
        raise RecoveryBootError("recovery target identity or device path changed before the first write")


def execute_recovery(directory: Path, *, passphrase_provider: Any = _wait_for_age_passphrase) -> str:
    """Validate and run one embedded restore through Feclora's shared engine."""
    answer = _load_answer(directory)
    manifest = _load_manifest(directory, answer["image_id"])
    target_path, _initial_device = _resolve(answer["selector"])
    manifest_path = directory / "manifest.json"
    encrypted = any(item.encryption == "age" for item in manifest.artifacts)
    passphrase = passphrase_provider() if encrypted else None
    try:
        with operation_record("restore_disk", target_path, image_id=manifest.image_id):
            execute_restore(
                str(manifest_path), str(directory), target_path,
                target_type="disk",
                confirmation=f"ERASE {target_path}",
                age_passphrase=passphrase,
                progress_callback=record_progress,
                pre_write_callback=lambda: _revalidate(answer["selector"], target_path),
            )
    finally:
        passphrase = None
    return target_path


def main() -> int:
    try:
        directory = discover_payload()
        if directory is None:
            return 0
        target = execute_recovery(directory)
    except (RecoveryBootError, OSError, RuntimeError, ValueError) as exc:
        print(f"feclora-recovery-boot: {exc}", file=sys.stderr)
        return 1
    print(f"Feclora recovery restore completed and verified: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only whole-disk destination inspection for proportional restore previews."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe


class TargetInspectionError(ValueError):
    """A proposed restore destination cannot be verified safely."""


def inspect_restore_target(
    disk_path: str,
    *,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
) -> dict[str, object]:
    """Inspect a whole-disk target without modifying it.

    The target must be an offline, unused whole block device. Existing
    partitions are inventoried but never erased or treated as disposable.
    """
    if (not isinstance(disk_path, str) or not disk_path.startswith("/dev/")
            or "\x00" in disk_path):
        raise TargetInspectionError("target must be an absolute /dev/ path")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(disk_path):
            raise TargetInspectionError("target path is not a block device")
    except OSError as exc:
        raise TargetInspectionError(f"cannot inspect target block device: {exc}") from exc

    run = runner or subprocess.run
    resolve = which or shutil.which
    required = {name: resolve(name) for name in ("lsblk", "blockdev")}
    missing = [name for name, path in required.items() if not path]
    if missing:
        raise TargetInspectionError("required target inspection tools are missing: " + ", ".join(missing))

    try:
        if safety_check is None:
            check_capture_source_safe(
                disk_path, runner=run, which=resolve, effective_uid=effective_uid
            )
        else:
            safety_check(disk_path)
    except SourceSafetyError as exc:
        raise TargetInspectionError(f"target must be offline and unused: {exc}") from exc
    except Exception as exc:
        raise TargetInspectionError(f"target safety check failed: {exc}") from exc

    uid = effective_uid or os.geteuid

    def invoke(tool: str, args: list[str]) -> str:
        try:
            argv = privileged_argv(
                [required[tool], *args], effective_uid=uid, which=resolve
            )
            result = run(argv, check=True, capture_output=True, text=True, timeout=30)
            return result.stdout
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise TargetInspectionError(f"{tool} target inspection failed: {exc}") from exc

    try:
        inventory = json.loads(invoke(
            "lsblk",
            ["--json", "--bytes", "--tree", "--paths",
             "--output", "PATH,TYPE,SIZE,LOG-SEC,PTTYPE,MODEL,SERIAL,WWN", disk_path],
        ))
    except (TypeError, json.JSONDecodeError) as exc:
        raise TargetInspectionError("lsblk returned invalid target inventory JSON") from exc
    roots = inventory.get("blockdevices") if isinstance(inventory, dict) else None
    if not isinstance(roots, list) or len(roots) != 1 or not isinstance(roots[0], dict):
        raise TargetInspectionError("lsblk did not resolve exactly one target disk")
    root = roots[0]
    if root.get("path") != disk_path or root.get("type") != "disk":
        raise TargetInspectionError("restore target must resolve to the selected whole disk")

    sector_size = root.get("log-sec")
    size_from_lsblk = root.get("size")
    if (isinstance(sector_size, bool) or not isinstance(sector_size, int)
            or sector_size not in {512, 4096}):
        raise TargetInspectionError("target logical sector size is unknown or unsupported")
    if (isinstance(size_from_lsblk, bool) or not isinstance(size_from_lsblk, int)
            or size_from_lsblk <= 0):
        raise TargetInspectionError("target capacity is unknown or invalid")

    try:
        size_from_blockdev = int(invoke("blockdev", ["--getsize64", disk_path]).strip())
        sector_from_blockdev = int(invoke("blockdev", ["--getss", disk_path]).strip())
    except (TypeError, ValueError) as exc:
        raise TargetInspectionError("blockdev returned invalid target geometry") from exc
    if (size_from_blockdev <= 0 or size_from_blockdev != size_from_lsblk
            or sector_from_blockdev != sector_size
            or size_from_blockdev % sector_size):
        raise TargetInspectionError("blockdev and lsblk target geometry disagree")

    children = root.get("children") or []
    if not isinstance(children, list):
        raise TargetInspectionError("lsblk returned invalid target partition hierarchy")
    partitions: list[dict[str, object]] = []
    seen: set[str] = set()
    for child in children:
        if (not isinstance(child, dict) or child.get("type") != "part"
                or child.get("children")):
            raise TargetInspectionError("target contains an unrecognized child storage layer")
        path = child.get("path")
        if not isinstance(path, str) or not path.startswith(disk_path) or not re.fullmatch(r"(?:p?\d+|-part\d+)", path[len(disk_path):]) or path in seen:
            raise TargetInspectionError("target contains duplicate or invalid partition paths")
        seen.add(path)
        partitions.append({
            "path": path,
            "filesystem_type": child.get("fstype") if isinstance(child.get("fstype"), str) else None,
            "size_bytes": child.get("size") if isinstance(child.get("size"), int) else None,
        })

    return {
        "disk_path": disk_path,
        "target_size_bytes": size_from_blockdev,
        "sector_size": sector_size,
        "partition_table_type": root.get("pttype") if isinstance(root.get("pttype"), str) else None,
        "model": root.get("model") if isinstance(root.get("model"), str) else None,
        "serial": root.get("serial") if isinstance(root.get("serial"), str) else None,
        "wwn": root.get("wwn") if isinstance(root.get("wwn"), str) else None,
        "existing_partitions": tuple(partitions),
        "write_authorized": False,
    }

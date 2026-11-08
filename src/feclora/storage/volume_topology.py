"""Read-only LVM topology collection using the LVM reporting interface.

No activation, scanning override, metadata repair, or mutation command is used.
The caller can disable LVM reporting when running in constrained environments.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Callable


class VolumeTopologyError(RuntimeError):
    """A volume manager returned invalid or incomplete topology data."""


_LVM_REPORTS = {
    "pvs": ("pv_name,pv_uuid,vg_name,pv_size,pv_free,pv_attr",),
    "vgs": ("vg_name,vg_uuid,vg_size,vg_free,vg_attr,pv_count,lv_count",),
    "lvs": ("lv_path,lv_name,vg_name,lv_uuid,lv_size,lv_attr,origin,pool_lv,devices",),
}


def _report_rows(payload: str, command: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise VolumeTopologyError(f"{command} returned invalid JSON: {exc}") from exc
    reports = document.get("report") if isinstance(document, dict) else None
    if not isinstance(reports, list):
        raise VolumeTopologyError(f"{command} JSON has no report array")
    rows: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        section = report.get(command)
        if section is None:
            continue
        if not isinstance(section, list) or any(not isinstance(row, dict) for row in section):
            raise VolumeTopologyError(f"{command} JSON contains an invalid report section")
        rows.extend(section)
    return rows


def collect_lvm_topology(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Collect PV/VG/LV relationships through LVM's machine-readable reports."""
    result: dict[str, Any] = {"status": "available", "pvs": [], "vgs": [], "lvs": []}
    for command, fields in _LVM_REPORTS.items():
        executable = which(command)
        if executable is None:
            result["status"] = "incomplete"
            result["missing"] = sorted(set(result.get("missing", [])) | {command})
            continue
        argv = [
            executable, "--readonly", "--reportformat", "json",
            "--units", "b", "--nosuffix", "-o", fields[0],
        ]
        try:
            completed = runner(
                argv, check=True, capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            raise VolumeTopologyError(f"{command} timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip()
            raise VolumeTopologyError(f"{command} failed: {detail or exc}") from exc
        result[command] = _report_rows(completed.stdout, command)
    return result

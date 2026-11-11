"""Read-only LVM topology collection using the LVM reporting interface.

No activation, scanning override, metadata repair, or mutation command is used.
The caller can disable LVM reporting when running in constrained environments.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable


class VolumeTopologyError(RuntimeError):
    """A volume manager returned invalid or incomplete topology data."""


_LVM_REPORT_SECTIONS = {"pvs": "pv", "vgs": "vg", "lvs": "lv"}


_LVM_REPORTS = {
    "pvs": ("pv_name,pv_uuid,vg_name,pv_size,pv_free,pv_attr,pv_pe_count,pv_pe_alloc_count,pv_missing",),
    "vgs": ("vg_name,vg_uuid,vg_size,vg_free,vg_attr,pv_count,lv_count,vg_extent_size,vg_extent_count,vg_free_count,vg_missing_pv_count",),
    "lvs": ("lv_path,lv_name,vg_name,lv_uuid,lv_size,lv_attr,origin,pool_lv,devices,segtype,lv_layout,lv_role,data_percent,metadata_percent,lv_health_status,lv_kernel_major,lv_kernel_minor",),
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
        section = report.get(_LVM_REPORT_SECTIONS[command])
        if section is None:
            continue
        if not isinstance(section, list) or any(not isinstance(row, dict) for row in section):
            raise VolumeTopologyError(f"{command} JSON contains an invalid report section")
        rows.extend(section)
    return rows



def _as_nonnegative_int(value: Any) -> int | None:
    """Parse an LVM integer field without treating unknown values as zero."""
    if value in (None, "", "-"):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def summarize_lvm_topology(result: dict[str, Any]) -> dict[str, Any]:
    """Attach explicit VG membership and conservative health/thin-LV summaries.

    Original LVM report rows remain unchanged. Missing or unrecognized fields
    are represented as unknown rather than inferred to be healthy.
    """
    pvs = result.get("pvs", [])
    vgs = result.get("vgs", [])
    lvs = result.get("lvs", [])
    if not all(isinstance(rows, list) for rows in (pvs, vgs, lvs)):
        raise VolumeTopologyError("LVM topology rows must be lists")

    pvs_by_vg: dict[str, list[dict[str, Any]]] = {}
    lvs_by_vg: dict[str, list[dict[str, Any]]] = {}
    for pv in pvs:
        if not isinstance(pv, dict):
            raise VolumeTopologyError("LVM PV report contains a non-object row")
        vg_name = str(pv.get("vg_name") or "").strip()
        if vg_name:
            pvs_by_vg.setdefault(vg_name, []).append(pv)
    for lv in lvs:
        if not isinstance(lv, dict):
            raise VolumeTopologyError("LVM LV report contains a non-object row")
        vg_name = str(lv.get("vg_name") or "").strip()
        if vg_name:
            lvs_by_vg.setdefault(vg_name, []).append(lv)

    groups: list[dict[str, Any]] = []
    for vg in vgs:
        if not isinstance(vg, dict):
            raise VolumeTopologyError("LVM VG report contains a non-object row")
        name = str(vg.get("vg_name") or "").strip()
        if not name:
            continue
        missing = _as_nonnegative_int(vg.get("vg_missing_pv_count"))
        health_values = [
            str(lv.get("lv_health_status") or "").strip().lower()
            for lv in lvs_by_vg.get(name, [])
        ]
        unhealthy_lv = any(value not in {"", "-", "ok", "healthy"} for value in health_values)
        pv_missing_count = sum(
            1 for pv in pvs_by_vg.get(name, [])
            if str(pv.get("pv_missing") or "").strip().lower() in {"1", "yes", "missing", "true"}
        )
        # LVM's vg_attr is positional: the fourth character is the
        # partial flag. A "p" in another attribute position (for example an
        # allocation policy) must not be mistaken for a partial VG.
        vg_attr = str(vg.get("vg_attr") or "").strip().lower()
        vg_attr_known = len(vg_attr) >= 4
        vg_partial = vg_attr_known and vg_attr[3] == "p"
        degraded = (
            (missing is not None and missing > 0)
            or pv_missing_count > 0
            or vg_partial
            or unhealthy_lv
        )
        healthy = missing == 0 and vg_attr_known and not vg_partial and not unhealthy_lv
        groups.append({
            "name": name,
            "uuid": vg.get("vg_uuid"),
            "status": "degraded" if degraded else "healthy" if healthy else "unknown",
            "missing_pv_count": max(missing or 0, pv_missing_count) if missing is not None or pv_missing_count else None,
            "pv_count_reported": _as_nonnegative_int(vg.get("pv_count")),
            "lv_count_reported": _as_nonnegative_int(vg.get("lv_count")),
            "extent_size_bytes": _as_nonnegative_int(vg.get("vg_extent_size")),
            "extent_count": _as_nonnegative_int(vg.get("vg_extent_count")),
            "free_extent_count": _as_nonnegative_int(vg.get("vg_free_count")),
            "pv_members": [
                {
                    "path": pv.get("pv_name"),
                    "uuid": pv.get("pv_uuid"),
                    "size_bytes": _as_nonnegative_int(pv.get("pv_size")),
                    "free_bytes": _as_nonnegative_int(pv.get("pv_free")),
                    "total_extents": _as_nonnegative_int(pv.get("pv_pe_count")),
                    "allocated_extents": _as_nonnegative_int(pv.get("pv_pe_alloc_count")),
                    "missing": str(pv.get("pv_missing") or "").strip().lower() in {"1", "yes", "missing", "true"},
                }
                for pv in pvs_by_vg.get(name, [])
            ],
            "logical_volumes": [
                {
                    "path": lv.get("lv_path"),
                    "name": lv.get("lv_name"),
                    "uuid": lv.get("lv_uuid"),
                    "size_bytes": _as_nonnegative_int(lv.get("lv_size")),
                    "segment_type": lv.get("segtype"),
                    "layout": lv.get("lv_layout"),
                    "role": lv.get("lv_role"),
                    "pool": lv.get("pool_lv") or None,
                    "origin": lv.get("origin") or None,
                    "devices": lv.get("devices"),
                    "data_percent": lv.get("data_percent"),
                    "metadata_percent": lv.get("metadata_percent"),
                    "health": lv.get("lv_health_status") or None,
                    "kernel_major": _as_nonnegative_int(lv.get("lv_kernel_major")),
                    "kernel_minor": _as_nonnegative_int(lv.get("lv_kernel_minor")),
                    "major_minor": (
                        f"{_as_nonnegative_int(lv.get('lv_kernel_major'))}:"
                        f"{_as_nonnegative_int(lv.get('lv_kernel_minor'))}"
                        if _as_nonnegative_int(lv.get("lv_kernel_major")) is not None
                        and _as_nonnegative_int(lv.get("lv_kernel_minor")) is not None
                        else None
                    ),
                    "thin_provisioned": (
                        "thin" in str(lv.get("lv_layout") or "").lower()
                        or str(lv.get("segtype") or "").lower() in {"thin", "thin-pool"}
                        or bool(lv.get("pool_lv"))
                    ),
                    "snapshot": bool(lv.get("origin"))
                        or "snapshot" in str(lv.get("lv_role") or "").lower(),
                    "hidden": str(lv.get("lv_name") or "").startswith("[")
                        or "private" in str(lv.get("lv_role") or "").lower(),
                }
                for lv in lvs_by_vg.get(name, [])
            ],
        })
    return {**result, "volume_groups": groups}


def collect_lvm_topology(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    effective_uid: Callable[[], int] = os.geteuid,
    sudo: str | None = None,
) -> dict[str, Any]:
    """Collect PV/VG/LV relationships through LVM's machine-readable reports."""
    result: dict[str, Any] = {"status": "available", "pvs": [], "vgs": [], "lvs": []}
    prefix: list[str] = []
    if effective_uid() != 0:
        sudo_bin = sudo or shutil.which("sudo")
        if not sudo_bin:
            return {"status": "permission_required", "pvs": [], "vgs": [], "lvs": []}
        prefix = [sudo_bin, "-n"]
    for command, fields in _LVM_REPORTS.items():
        executable = which(command)
        if executable is None:
            result["status"] = "incomplete"
            result["missing"] = sorted(set(result.get("missing", [])) | {command})
            continue
        argv = [
            *prefix, executable, "--readonly", *(["--all"] if command == "lvs" else []),
            "--reportformat", "json",
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
    return summarize_lvm_topology(result)

"""Fail-closed block-device and byte-stream primitives for physical multicast.

This module intentionally contains no UDPcast orchestration or device-opening
policy. The deployment runtime must establish the authenticated control plane,
open the source read-only, open each approved destination exclusively, and
revalidate the supplied identities at the write boundary before using these
primitives. Tests use in-memory streams only.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable, Mapping
from typing import Any


class PhysicalMulticastError(RuntimeError):
    """A physical multicast preflight, stream, or verification check failed."""


_IDENTITY_FIELDS = (
    "major_minor", "sysfs_path", "wwn", "serial", "size_bytes",
    "logical_sector_size", "physical_sector_size",
)
_DEVICE_PATH = re.compile(r"^/dev/[A-Za-z0-9_.!/+:-]{1,120}$")


def _device_record(value: Mapping[str, Any], role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PhysicalMulticastError(f"{role} device inventory is invalid")
    path = value.get("path")
    if (not isinstance(path, str) or not _DEVICE_PATH.fullmatch(path)
            or ".." in path.split("/") or "//" in path):
        raise PhysicalMulticastError(f"{role} device path is not a normalized /dev path")
    record = dict(value)
    for field in _IDENTITY_FIELDS:
        item = record.get(field)
        if field in {"wwn", "serial"} and item in (None, ""):
            continue
        if field == "size_bytes":
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise PhysicalMulticastError(f"{role} device has invalid capacity")
        elif field in {"logical_sector_size", "physical_sector_size"}:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise PhysicalMulticastError(f"{role} device has invalid sector geometry")
        elif not isinstance(item, str) or not item:
            raise PhysicalMulticastError(f"{role} device is missing stable identity field {field}")
    if not record.get("wwn") and not record.get("serial"):
        raise PhysicalMulticastError(f"{role} device requires a WWN or serial number")
    if not isinstance(record.get("read_only"), bool):
        raise PhysicalMulticastError(f"{role} device read-only state is unknown")
    for field in ("mountpoints", "holders"):
        values = record.get(field)
        if not isinstance(values, (list, tuple)) or any(not isinstance(x, str) or not x for x in values):
            raise PhysicalMulticastError(f"{role} device {field} inventory is incomplete")
    if not isinstance(record.get("backs_system"), bool) or not isinstance(record.get("busy"), bool):
        raise PhysicalMulticastError(f"{role} device use-state inventory is incomplete")
    return record


def build_physical_device_record(
    device: Mapping[str, Any],
    *,
    sysfs_root: str = "/sys",
) -> dict[str, Any]:
    """Build fail-closed physical identity/use metadata from one lsblk record.

    sysfs_root is injectable so tests can model kernel metadata without touching
    host block devices. Any missing geometry or sysfs identity is a hard error.
    """
    if not isinstance(device, Mapping):
        raise PhysicalMulticastError("selected block-device inventory record is invalid")
    path = device.get("path")
    major_minor = device.get("major_minor")
    if not isinstance(path, str) or not _DEVICE_PATH.fullmatch(path):
        raise PhysicalMulticastError("selected block-device path is invalid")
    if not isinstance(major_minor, str) or not re.fullmatch(r"[0-9]+:[0-9]+", major_minor):
        raise PhysicalMulticastError("selected block device has no kernel major/minor identity")
    sysfs_device = os.path.join(sysfs_root, "dev", "block", major_minor)
    if not os.path.exists(sysfs_device):
        raise PhysicalMulticastError("selected block device has no sysfs identity")
    sysfs_path = os.path.realpath(sysfs_device)
    queue = os.path.join(sysfs_path, "queue")
    try:
        with open(os.path.join(queue, "physical_block_size"), encoding="ascii") as stream:
            physical_sector = int(stream.read().strip())
        holders_path = os.path.join(sysfs_path, "holders")
        holders = sorted(os.listdir(holders_path))
    except (OSError, ValueError) as exc:
        raise PhysicalMulticastError(f"cannot read selected block-device sysfs metadata: {exc}") from exc
    mountpoints = device.get("mountpoints")
    if not isinstance(mountpoints, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in mountpoints
    ):
        raise PhysicalMulticastError("selected block-device mount inventory is incomplete")

    def subtree_has_system_mount(item: Mapping[str, Any]) -> bool:
        points = item.get("mountpoints", [])
        if isinstance(points, (list, tuple)) and any(
            point == "/" or point.startswith(("/boot", "/efi")) for point in points
        ):
            return True
        children = item.get("children", [])
        return isinstance(children, (list, tuple)) and any(
            isinstance(child, Mapping) and subtree_has_system_mount(child)
            for child in children
        )

    backs_system = subtree_has_system_mount(device)
    # A device is considered busy if it or any descendant is mounted/held.
    def subtree_busy(item: Mapping[str, Any]) -> bool:
        points = item.get("mountpoints", [])
        if isinstance(points, (list, tuple)) and points:
            return True
        children = item.get("children", [])
        return isinstance(children, (list, tuple)) and any(
            isinstance(child, Mapping) and subtree_busy(child)
            for child in children
        )

    record = {
        "path": path,
        "major_minor": major_minor,
        "sysfs_path": sysfs_path,
        "wwn": device.get("wwn"),
        "serial": device.get("serial"),
        "size_bytes": device.get("size_bytes"),
        "logical_sector_size": device.get("logical_sector_size"),
        "physical_sector_size": physical_sector,
        "read_only": device.get("read_only"),
        "mountpoints": list(mountpoints),
        "holders": holders,
        "backs_system": backs_system,
        "busy": bool(mountpoints or holders or backs_system or subtree_busy(device)),
    }
    return _device_record(record, "Selected")


def validate_physical_multicast_pair(
    source: Mapping[str, Any],
    destination: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate independently inventoried Server source and Client destination."""
    src = _device_record(source, "Server source")
    dst = _device_record(destination, "Client destination")
    if src["path"] == dst["path"]:
        raise PhysicalMulticastError("source and destination use the same device path")
    if src["major_minor"] == dst["major_minor"]:
        raise PhysicalMulticastError("source and destination resolve to the same major/minor device")
    if src["sysfs_path"] == dst["sysfs_path"]:
        raise PhysicalMulticastError("source and destination resolve to the same sysfs device")
    if src.get("wwn") and dst.get("wwn") and src["wwn"].casefold() == dst["wwn"].casefold():
        raise PhysicalMulticastError("source and destination share the same WWN hardware identity")
    if src.get("serial") and dst.get("serial") and src["serial"].casefold() == dst["serial"].casefold():
        raise PhysicalMulticastError("source and destination share the same hardware serial identity")
    if src["read_only"] is not True:
        raise PhysicalMulticastError("Server source must be hardware/kernel read-only")
    if dst["read_only"] is not False:
        raise PhysicalMulticastError("Client destination must be writable")
    for role, item in (("Server source", src), ("Client destination", dst)):
        if item["mountpoints"] or item["holders"] or item["backs_system"] or item["busy"]:
            raise PhysicalMulticastError(
                f"{role} is mounted, held, system-backed, or otherwise busy"
            )
    if dst["size_bytes"] < src["size_bytes"]:
        raise PhysicalMulticastError("Client destination is smaller than the Server source")
    if dst["logical_sector_size"] != src["logical_sector_size"]:
        raise PhysicalMulticastError("source and destination logical sector sizes differ")
    if dst["physical_sector_size"] != src["physical_sector_size"]:
        raise PhysicalMulticastError("source and destination physical sector sizes differ")
    return src, dst


def assert_device_identity_unchanged(
    approved: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    role: str,
) -> None:
    """Reject path reuse or any identity/geometry/use-state drift after READY."""
    before = _device_record(approved, role)
    now = _device_record(current, role)
    fields = ("path", *_IDENTITY_FIELDS, "read_only", "mountpoints", "holders", "backs_system", "busy")
    changed = [field for field in fields if before.get(field) != now.get(field)]
    if changed:
        raise PhysicalMulticastError(
            f"{role} identity or safety state changed after approval: {', '.join(changed)}"
        )


def open_approved_block_device(
    approved: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    role: str,
    sysfs_root: str = "/sys",
) -> int:
    """Open an already-approved block device with role-specific kernel exclusivity.

    The Server source is opened read-only. A Client destination is opened
    read/write with O_EXCL so Linux rejects a block device already in use.
    The descriptor's actual block major/minor is checked after open to close
    the inventory-to-open path-reuse race.
    """
    if role not in {"Server source", "Client destination"}:
        raise PhysicalMulticastError("block-device role is invalid")
    assert_device_identity_unchanged(approved, current, role=role)
    expected_read_only = role == "Server source"
    if approved.get("read_only") is not expected_read_only:
        raise PhysicalMulticastError(f"{role} has the wrong read-only state")
    flags = os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_RDONLY if expected_read_only else os.O_RDWR | os.O_EXCL
    try:
        descriptor = os.open(approved["path"], flags)
    except OSError as exc:
        detail = "source cannot be opened read-only" if expected_read_only else "destination is busy or cannot be opened exclusively"
        raise PhysicalMulticastError(f"{role} {detail}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISBLK(info.st_mode):
            raise PhysicalMulticastError(f"{role} descriptor is not a block device")
        actual = f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
        if actual != approved["major_minor"]:
            raise PhysicalMulticastError(f"{role} block identity changed between inventory and open")
        sysfs_link = os.path.join(sysfs_root, "dev", "block", actual)
        if not os.path.exists(sysfs_link) or os.path.realpath(sysfs_link) != approved["sysfs_path"]:
            raise PhysicalMulticastError(f"{role} sysfs identity changed between inventory and open")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def block_device_stream_callbacks(descriptor: int):
    """Return positional write/flush/read-back callbacks for an exclusive disk fd."""
    if isinstance(descriptor, bool) or not isinstance(descriptor, int) or descriptor < 0:
        raise PhysicalMulticastError("block-device descriptor is invalid")
    if not all(callable(getattr(os, name, None)) for name in ("pwrite", "pread", "fsync")):
        raise PhysicalMulticastError("positional block-device I/O is unavailable")
    offset = 0
    read_offset = 0

    def write(view: memoryview) -> int:
        nonlocal offset
        written = os.pwrite(descriptor, view, offset)
        if isinstance(written, int) and not isinstance(written, bool) and written > 0:
            offset += written
        return written

    def flush() -> None:
        os.fsync(descriptor)

    def readback(count: int) -> bytes:
        nonlocal read_offset
        chunk = os.pread(descriptor, count, read_offset)
        if chunk:
            read_offset += len(chunk)
        return chunk

    return write, flush, readback


def write_and_verify_stream(
    source_stream: Any,
    write: Callable[[memoryview], int],
    flush: Callable[[], None],
    readback: Callable[[int], bytes],
    *,
    expected_bytes: int,
    chunk_size: int = 1024 * 1024,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Write an exact stream with short-write handling, flush, and full read-back SHA-256.

    The caller owns the already-authorized block-device descriptors. No device
    path is accepted here, preventing this helper from selecting a destination.
    """
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes <= 0:
        raise PhysicalMulticastError("expected stream size must be a positive integer")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or not 4096 <= chunk_size <= 16 * 1024 * 1024:
        raise PhysicalMulticastError("stream chunk size is outside the supported bounds")
    source_digest = hashlib.sha256()
    total = 0
    while total < expected_bytes:
        if cancel_check is not None and cancel_check():
            raise PhysicalMulticastError("physical multicast stream cancelled before destination write completed")
        chunk = source_stream.read(min(chunk_size, expected_bytes - total))
        if not isinstance(chunk, (bytes, bytearray, memoryview)) or not chunk:
            raise PhysicalMulticastError(f"physical multicast stream ended early ({total}/{expected_bytes} bytes)")
        view = memoryview(chunk)
        if len(view) > expected_bytes - total:
            view = view[:expected_bytes - total]
        source_digest.update(view)
        offset = 0
        while offset < len(view):
            written = write(view[offset:])
            if isinstance(written, bool) or not isinstance(written, int) or written <= 0 or written > len(view) - offset:
                raise PhysicalMulticastError("destination returned an invalid or zero-length write")
            offset += written
        total += len(view)
    flush()
    expected_digest = source_digest.hexdigest()
    readback_digest = hashlib.sha256()
    verified = 0
    while verified < expected_bytes:
        if cancel_check is not None and cancel_check():
            raise PhysicalMulticastError("physical multicast stream cancelled during destination read-back")
        chunk = readback(min(chunk_size, expected_bytes - verified))
        if not isinstance(chunk, (bytes, bytearray, memoryview)) or not chunk:
            raise PhysicalMulticastError(f"destination read-back ended early ({verified}/{expected_bytes} bytes)")
        if len(chunk) > expected_bytes - verified:
            raise PhysicalMulticastError("destination read-back returned more bytes than authorized")
        readback_digest.update(chunk)
        verified += len(chunk)
    actual_digest = readback_digest.hexdigest()
    if actual_digest != expected_digest:
        raise PhysicalMulticastError("destination read-back SHA-256 does not match the received source stream")
    return {
        "bytes_written": total,
        "bytes_verified": verified,
        "sha256": expected_digest,
        "readback_sha256": actual_digest,
        "verified": True,
    }


def validate_physical_multicast_cohort(
    source_approved: Mapping[str, Any],
    source_current: Mapping[str, Any],
    expected_clients: list[str] | tuple[str, ...],
    client_states: Mapping[str, str],
    approved_destinations: Mapping[str, Mapping[str, Any]],
    current_destinations: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Validate the complete READY cohort before any physical multicast write.

    Every selected Client must be READY and must have independently approved a
    destination. The source and every destination are revalidated as one
    all-or-nothing preflight; callers must not start UDPcast or open writable
    destination descriptors unless this function returns successfully.
    """
    if not isinstance(expected_clients, (list, tuple)) or not expected_clients:
        raise PhysicalMulticastError("physical multicast requires a non-empty selected Client set")
    normalized: list[str] = []
    for mac in expected_clients:
        if (not isinstance(mac, str)
                or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac)):
            raise PhysicalMulticastError("physical multicast selected Client MAC is invalid")
        value = mac.lower()
        if int(value[:2], 16) & 1 or value == "00:00:00:00:00:00" or value in normalized:
            raise PhysicalMulticastError("physical multicast selected Client set is not unique unicast MACs")
        normalized.append(value)
    selected = set(normalized)
    def normalize_client_map(value: Mapping[str, Any], label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PhysicalMulticastError(f"physical multicast {label} inventory is invalid")
        result: dict[str, Any] = {}
        for raw_mac, item in value.items():
            if (not isinstance(raw_mac, str)
                    or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", raw_mac)):
                raise PhysicalMulticastError(f"physical multicast {label} contains an invalid Client MAC")
            mac = raw_mac.lower()
            if mac in result:
                raise PhysicalMulticastError(f"physical multicast {label} contains duplicate Client MACs")
            result[mac] = item
        return result

    states = normalize_client_map(client_states, "readiness")
    approved_by_mac = normalize_client_map(approved_destinations, "destination approval")
    current_by_mac = normalize_client_map(current_destinations, "destination revalidation")
    if set(states) != selected:
        raise PhysicalMulticastError("every selected Client must be present before physical multicast")
    if any(state != "ready" for state in states.values()):
        raise PhysicalMulticastError("every selected Client must be READY before physical multicast")
    if set(approved_by_mac) != selected or set(current_by_mac) != selected:
        raise PhysicalMulticastError("every selected Client must independently approve and revalidate one destination")
    assert_device_identity_unchanged(
        source_approved, source_current, role="Server source",
    )
    validated: list[tuple[str, dict[str, Any]]] = []
    for mac in sorted(selected):
        approved = approved_by_mac[mac]
        current = current_by_mac[mac]
        if not isinstance(approved, Mapping) or not isinstance(current, Mapping):
            raise PhysicalMulticastError(f"Client {mac} destination approval is incomplete")
        assert_device_identity_unchanged(
            approved, current, role=f"Client {mac} destination",
        )
        _source, destination = validate_physical_multicast_pair(
            source_current, current,
        )
        validated.append((mac, destination))
    return tuple(validated)

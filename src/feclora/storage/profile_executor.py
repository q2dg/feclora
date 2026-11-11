"""Execute signed, single-use unattended whole-disk restore profiles."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from feclora.storage.disk_restore import restore_disk
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.operation_log import operation_record
from feclora.storage.privilege import privileged_argv
from feclora.storage.restore_profile import (
    RestoreProfile,
    RestoreProfileError,
    load_restore_profile,
)
from feclora.storage.inventory import collect_inventory

_MAX_LEDGER_BYTES = 8 * 1024 * 1024


def _consume_profile_once(profile_id: str, ledger_path: str | os.PathLike[str]) -> None:
    """Atomically consume a profile ID immediately before the first disk write."""
    destination = Path(ledger_path)
    directory = destination.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        dir_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            dir_info = os.fstat(dir_fd)
            if not stat.S_ISDIR(dir_info.st_mode) or dir_info.st_uid != os.geteuid():
                raise RestoreProfileError("profile consumption ledger directory has unsafe type or ownership")
            os.fchmod(dir_fd, 0o700)
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(destination.name, flags, 0o600, dir_fd=dir_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                    raise RestoreProfileError("profile consumption ledger has unsafe type or ownership")
                if info.st_size > _MAX_LEDGER_BYTES:
                    raise RestoreProfileError("profile consumption ledger exceeds its safety limit")
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.lseek(fd, 0, os.SEEK_SET)
                chunks = []
                remaining = _MAX_LEDGER_BYTES + 1
                while remaining:
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
                if len(raw) > _MAX_LEDGER_BYTES:
                    raise RestoreProfileError("profile consumption ledger exceeds its safety limit")
                consumed: set[str] = set()
                for line_number, line in enumerate(raw.splitlines(), 1):
                    try:
                        event = json.loads(line.decode("utf-8"))
                        value = event["profile_id"]
                    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                        raise RestoreProfileError(
                            f"profile consumption ledger is corrupt at line {line_number}"
                        ) from exc
                    if not isinstance(value, str):
                        raise RestoreProfileError(
                            f"profile consumption ledger has invalid profile ID at line {line_number}"
                        )
                    consumed.add(value)
                if profile_id in consumed:
                    raise RestoreProfileError("unattended restore profile has already been consumed")
                payload = (json.dumps({
                    "profile_id": profile_id,
                    "status": "consumed",
                }, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise RestoreProfileError("short write while consuming restore profile")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except RestoreProfileError:
        raise
    except OSError as exc:
        raise RestoreProfileError(f"cannot persist one-time profile authorization: {exc}") from exc


def _require_persistent_ledger(
    ledger_path: str | os.PathLike[str],
    *,
    runner: Any = subprocess.run,
) -> None:
    """Refuse an ephemeral Live overlay as the single-use replay ledger."""
    parent = Path(ledger_path).parent
    try:
        info = os.lstat(parent)
    except OSError as exc:
        raise RestoreProfileError(f"profile ledger directory must already exist on persistent storage: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise RestoreProfileError("profile ledger directory must be a real directory owned by the live operator")
    findmnt = shutil.which("findmnt")
    if not findmnt:
        raise RestoreProfileError("findmnt is required to verify persistent profile-ledger storage")
    try:
        result = runner(
            [findmnt, "--noheadings", "--output", "FSTYPE,TARGET", "--target", str(parent)],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RestoreProfileError(f"cannot verify profile ledger mount: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) < 2:
        raise RestoreProfileError("findmnt did not identify the profile ledger filesystem")
    filesystem, mountpoint = fields[0].lower(), fields[-1]
    if filesystem in {"overlay", "tmpfs", "ramfs", "rootfs", "squashfs", "devtmpfs"} or mountpoint == "/":
        raise RestoreProfileError(
            "single-use restore ledger must reside on a dedicated persistent mounted filesystem, not the Live root"
        )


def _matching_target(profile: RestoreProfile, inventory: dict[str, Any]) -> dict[str, Any]:
    matches = [
        device for device in inventory.get("devices", [])
        if device.get("type") == "disk" and profile.target.matches(device)
    ]
    if len(matches) != 1:
        raise RestoreProfileError(
            f"stable target selector matched {len(matches)} disks; exactly one is required"
        )
    target = matches[0]
    path = target.get("path")
    if not isinstance(path, str) or not path.startswith("/dev/"):
        raise RestoreProfileError("matched target has no valid local block-device path")
    return target



def _flatten_inventory_devices(devices: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if not isinstance(devices, list):
        return flattened
    pending = list(devices)
    while pending:
        device = pending.pop()
        if not isinstance(device, dict):
            continue
        flattened.append(device)
        children = device.get("children")
        if isinstance(children, list):
            pending.extend(children)
    return flattened


def preflight_logical_volume_restore(
    manifest: ImageManifest,
    inventory: dict[str, Any],
    target_path: str,
) -> dict[str, Any]:
    """Validate an existing LVM LV destination without activating or writing it.

    This is deliberately a preflight primitive, not a restore executor. The
    target must already be active and uniquely identifiable in both LVM and
    lsblk reports. It does not create VGs/LVs, resize thin pools, or restore
    LVM metadata.
    """
    if not isinstance(manifest, ImageManifest) or manifest.image_type != "logical_volume":
        raise RestoreProfileError("logical-volume preflight requires a logical_volume image manifest")
    storage = manifest.storage
    if not isinstance(storage, dict):
        raise RestoreProfileError("logical-volume manifest has no storage provenance")
    if (storage.get("capture_scope") != "logical_volume_bytes"
            or storage.get("source_layer") != "lvm_logical_volume"):
        raise RestoreProfileError("manifest does not describe raw logical-volume bytes")
    source_vg = storage.get("lvm_vg_name")
    source_lv = storage.get("lvm_lv_name")
    if not isinstance(source_vg, str) or not source_vg or not isinstance(source_lv, str) or not source_lv:
        raise RestoreProfileError("manifest must identify its source VG and LV")
    artifacts = [item for item in manifest.artifacts if item.role == "logical-volume-image"]
    if len(artifacts) != 1:
        raise RestoreProfileError("manifest must contain exactly one logical-volume-image artifact")
    if artifacts[0].format == "partclone" and not artifacts[0].filesystem:
        raise RestoreProfileError("Partclone logical-volume image has no filesystem type")

    dependencies = storage.get("dependencies", [])
    vg_dependencies = [
        item for item in dependencies
        if isinstance(item, dict) and item.get("kind") == "lvm_volume_group"
    ]
    if len(vg_dependencies) != 1:
        raise RestoreProfileError("manifest must declare exactly one external LVM volume-group dependency")
    if vg_dependencies[0].get("included_in_source_bytes") is not False:
        raise RestoreProfileError("LV image must not claim that VG metadata is included in its data bytes")
    if vg_dependencies[0].get("identity") not in {source_vg, storage.get("lvm_vg_uuid")}:
        raise RestoreProfileError("manifest VG dependency does not match its source VG identity")
    unsupported = [
        item.get("kind") for item in dependencies
        if isinstance(item, dict)
        and item.get("kind") not in {"lvm_volume_group", "lvm_vg_members", "lvm_pv_metadata"}
    ]
    if unsupported:
        raise RestoreProfileError("manifest contains storage dependencies unsupported by LV restore preflight")

    if not isinstance(target_path, str) or not target_path.startswith("/dev/"):
        raise RestoreProfileError("target LV path must be an absolute /dev/ path")
    topology = inventory.get("volume_topology")
    if not isinstance(topology, dict) or topology.get("status") != "available":
        raise RestoreProfileError("LVM topology is unavailable; refusing logical-volume restore")
    groups = topology.get("volume_groups")
    if not isinstance(groups, list):
        raise RestoreProfileError("LVM topology has no normalized volume-group inventory")
    target_matches = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for lv in group.get("logical_volumes", []):
            if isinstance(lv, dict) and lv.get("path") == target_path:
                target_matches.append((group, lv))
    if len(target_matches) != 1:
        raise RestoreProfileError("target path must identify exactly one existing LVM logical volume")
    group, lv = target_matches[0]
    if group.get("status") != "healthy" or group.get("missing_pv_count") != 0:
        raise RestoreProfileError("target volume group is degraded or its PV health is unknown")
    members = group.get("pv_members")
    if not isinstance(members, list) or not members:
        raise RestoreProfileError("target volume group has no verified PV membership")
    if any(not isinstance(member, dict) or member.get("missing") is not False for member in members):
        raise RestoreProfileError("target volume group has missing or unverified PV members")
    reported_pv_count = group.get("pv_count_reported")
    if (isinstance(reported_pv_count, bool) or not isinstance(reported_pv_count, int)
            or reported_pv_count <= 0 or reported_pv_count != len(members)):
        raise RestoreProfileError("target VG PV membership is incomplete or inconsistent")

    if lv.get("hidden") or lv.get("segment_type") == "thin-pool":
        raise RestoreProfileError("hidden LVs and thin-pool metadata LVs are not valid restore targets")
    segment_type = lv.get("segment_type")
    thin_provisioned = lv.get("thin_provisioned")
    if segment_type not in {"linear", "thin"}:
        raise RestoreProfileError(
            f"target LV segment type {segment_type!r} is not supported for byte-image restore"
        )
    if not isinstance(thin_provisioned, bool) or thin_provisioned != (segment_type == "thin"):
        raise RestoreProfileError("target LV segment type and thin-provisioning metadata are inconsistent")
    if lv.get("snapshot") or lv.get("origin"):
        raise RestoreProfileError("snapshot LVs and snapshot origins are not valid restore targets")
    lv_name = lv.get("name")
    if not isinstance(lv_name, str) or not lv_name:
        raise RestoreProfileError("target LV has no stable name")
    siblings = group.get("logical_volumes", [])
    if any(
        isinstance(other, dict) and other.get("origin") == lv_name
        for other in siblings
    ):
        raise RestoreProfileError("target LV has dependent snapshots; refusing to overwrite their origin")
    if lv.get("health") not in (None, "", "-", "ok", "healthy"):
        raise RestoreProfileError("target LV reports an unhealthy state")
    target_size = lv.get("size_bytes")
    if isinstance(target_size, bool) or not isinstance(target_size, int) or target_size <= 0:
        raise RestoreProfileError("target LV capacity is unknown")
    if target_size < manifest.source_size_bytes:
        raise RestoreProfileError("target LV is smaller than the image source size")

    major_minor = lv.get("major_minor")
    if not isinstance(major_minor, str) or not major_minor:
        raise RestoreProfileError("target LV is not active or its kernel device identity is unknown")
    block_devices = _flatten_inventory_devices(inventory.get("devices", []))
    exact_paths = [device for device in block_devices if device.get("path") == target_path]
    major_matches = [device for device in block_devices if device.get("major_minor") == major_minor]
    if len(exact_paths) > 1:
        raise RestoreProfileError("target LV path is ambiguous in the block-device inventory")
    if exact_paths:
        block = exact_paths[0]
        if block.get("major_minor") != major_minor:
            raise RestoreProfileError("LVM and block-device identities disagree for the target LV")
    else:
        if len(major_matches) != 1:
            raise RestoreProfileError("target LV block-device identity is missing or ambiguous")
        block = major_matches[0]
    if block.get("read_only"):
        raise RestoreProfileError("target LV is read-only")
    try:
        target_sector_size = int(block.get("logical_sector_size"))
    except (TypeError, ValueError):
        raise RestoreProfileError("target LV logical sector size is unknown")
    if target_sector_size != manifest.logical_sector_size:
        raise RestoreProfileError("target LV logical sector size differs from the image")
    if any(device.get("mountpoints") for device in _flatten_inventory_devices([block])):
        raise RestoreProfileError("target LV or one of its child devices is mounted or in use")

    warnings: list[str] = []
    thin = bool(lv.get("thin_provisioned"))
    pool_name = lv.get("pool")
    if thin:
        if not isinstance(pool_name, str) or not pool_name:
            raise RestoreProfileError("thin LV has no identifiable thin pool")
        pools = [
            item for item in siblings
            if isinstance(item, dict) and item.get("name") == pool_name
            and item.get("segment_type") == "thin-pool"
        ]
        if len(pools) != 1:
            raise RestoreProfileError("thin LV pool is missing or ambiguous")
        pool = pools[0]
        if pool.get("health") not in (None, "", "-", "ok", "healthy"):
            raise RestoreProfileError("thin pool reports an unhealthy state")
        percentages: dict[str, float] = {}
        for field in ("data_percent", "metadata_percent"):
            try:
                percent = float(pool[field])
            except (KeyError, TypeError, ValueError):
                raise RestoreProfileError(f"thin pool {field} is unknown; refusing restore")
            if not 0 <= percent < 100:
                raise RestoreProfileError(f"thin pool {field} is exhausted or invalid")
            percentages[field] = percent
            if percent >= 90:
                warnings.append(f"Thin pool {field} is at {percent:g}%; allocation during restore may exhaust it.")
        pool_size = pool.get("size_bytes")
        if isinstance(pool_size, bool) or not isinstance(pool_size, int) or pool_size <= 0:
            raise RestoreProfileError("thin pool capacity is unknown")
        estimated_free_data = int(pool_size * (100.0 - percentages["data_percent"]) / 100.0)
        if estimated_free_data < manifest.source_size_bytes:
            raise RestoreProfileError(
                "thin pool estimated free data capacity is smaller than the logical-volume image"
            )
        warnings.append(
            f"Estimated thin-pool free data capacity is {estimated_free_data} bytes; "
            "this estimate is not a reservation and can change before or during restore."
        )
        warnings.append("Thin-pool metadata allocation can change during restore; this preflight does not reserve metadata extents.")

    return {
        "status": "ready",
        "target_path": target_path,
        "target_vg": group.get("name"),
        "target_lv": lv_name,
        "target_size_bytes": target_size,
        "image_size_bytes": manifest.source_size_bytes,
        "thin_provisioned": thin,
        "thin_pool": pool_name if thin else None,
        "warnings": warnings,
        "writes_performed": False,
        "activation_performed": False,
    }


def execute_unattended_restore_profile(
    profile_path: str | os.PathLike[str],
    *,
    profile_trusted_key: str | os.PathLike[str],
    image_trusted_key: str | os.PathLike[str],
    consumption_ledger: str | os.PathLike[str],
    repository: str | os.PathLike[str] = "/home/feclora/images",
    age_identity_file: str | os.PathLike[str] | None = None,
    operation_log_path: str | os.PathLike[str],
    inventory: dict[str, Any] | None = None,
    restore_function: Any = restore_disk,
    command_runner: Any = subprocess.run,
) -> ImageManifest:
    """Run one signed profile; all destructive preflight remains in restore_disk."""
    profile = load_restore_profile(
        profile_path, minisign_public_key=profile_trusted_key,
    )
    if profile.execution_mode != "unattended":
        raise RestoreProfileError("profile execution mode is not unattended")
    if profile.layout_policy != "preserve":
        raise RestoreProfileError(
            "proportional layout execution is not yet available; choose preserve for this raw-disk executor"
        )
    if not profile.single_use or not profile.verify_after_restore:
        raise RestoreProfileError("unattended profile must be single-use and require read-back verification")
    _require_persistent_ledger(consumption_ledger, runner=command_runner)
    _require_persistent_ledger(operation_log_path, runner=command_runner)
    current_inventory = inventory if inventory is not None else collect_inventory()
    target = _matching_target(profile, current_inventory)
    profile.authorize(target)
    repository_path = Path(repository)
    manifest_path = repository_path / profile.image_manifest
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise RestoreProfileError(f"cannot load profile image manifest: {exc}") from exc
    if manifest.image_type != "disk":
        raise RestoreProfileError("unattended profile executor currently supports whole-disk images only")
    if age_identity_file is None and any(item.encryption == "age" for item in manifest.artifacts):
        raise RestoreProfileError("this image requires an age identity supplied outside the profile")
    target_path = target["path"]

    def consume_before_write() -> None:
        # Re-read stable hardware identity and expiry after the potentially
        # lengthy artifact preflight, immediately before consuming permission.
        current_target = _matching_target(profile, collect_inventory())
        if current_target.get("path") != target_path:
            raise RestoreProfileError("target device path changed during restore preflight")
        profile.authorize(current_target)
        _consume_profile_once(profile.profile_id, consumption_ledger)

    with operation_record(
        "unattended-restore-profile",
        target_path,
        image_id=profile.profile_id,
        log_path=operation_log_path,
    ):
        restored = restore_function(
            profile.image_manifest,
            repository_path,
            target_path,
            confirmation=f"ERASE {target_path}",
            age_identity_file=age_identity_file,
            minisign_public_key=image_trusted_key,
            require_signature=True,
            pre_write_callback=consume_before_write,
        )
    if profile.on_success in {"reboot", "poweroff"}:
        command_runner(privileged_argv(["systemctl", profile.on_success]), check=True, timeout=30)
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one signed, single-use feclora whole-disk restore profile."
    )
    parser.add_argument("--profile", required=True, help="Path to the signed restore profile JSON")
    parser.add_argument("--profile-trusted-key", required=True, help="Trusted minisign public key for the profile")
    parser.add_argument("--image-trusted-key", required=True, help="Trusted minisign public key for the image manifest")
    parser.add_argument("--repository", default="/home/feclora/images")
    parser.add_argument("--consumption-ledger", required=True, help="JSONL replay ledger on a dedicated persistent mounted filesystem")
    parser.add_argument("--operation-log", required=True, help="Persistent JSONL operation journal path")
    parser.add_argument("--age-identity", help="Protected path to the age identity; never stored in the profile")
    args = parser.parse_args(argv)
    try:
        manifest = execute_unattended_restore_profile(
            args.profile,
            profile_trusted_key=args.profile_trusted_key,
            image_trusted_key=args.image_trusted_key,
            consumption_ledger=args.consumption_ledger,
            operation_log_path=args.operation_log,
            repository=args.repository,
            age_identity_file=args.age_identity,
        )
    except (RestoreProfileError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"feclora-restore-profile: {exc}", file=sys.stderr)
        return 1
    print(f"Verified restore completed: {manifest.image_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

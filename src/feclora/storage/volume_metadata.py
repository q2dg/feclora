"""Read-only classification of LVM, Stratis and Btrfs block-device metadata.

This module deliberately does not activate volume groups, mount filesystems, or
change pool state. It annotates lsblk's device tree; deeper Stratis topology
requires querying stratisd and is not inferred from an XFS signature alone.
"""
from __future__ import annotations

from typing import Any


def classify_volume(device: dict[str, Any]) -> list[str]:
    """Return conservative volume-layer tags supported by lsblk metadata."""
    tags: list[str] = []
    fstype = str(device.get("fstype") or device.get("filesystem") or "").lower()
    dev_type = str(device.get("type") or "").lower()
    name = str(device.get("name") or "")
    path = str(device.get("path") or "")
    mapper_name = name.rsplit("/", 1)[-1]

    if fstype == "btrfs":
        tags.append("btrfs")
    # lsblk reports crypto_LUKS for an unopened encrypted container and
    # TYPE=crypt for an active device-mapper mapping. Do not infer LUKS from
    # mapper names: only the kernel-reported type/signature is authoritative.
    if fstype == "crypto_luks":
        tags.extend(("luks", "luks_container"))
    elif dev_type == "crypt":
        # TYPE=crypt proves an active dm-crypt mapping, but does not prove
        # that its on-disk format is LUKS (plain dm-crypt is also possible).
        tags.extend(("encrypted", "crypt_mapping"))
    if fstype in {"lvm2_member", "lvm"} or dev_type == "lvm":
        tags.append("lvm")
        if fstype == "lvm2_member":
            tags.append("lvm_pv")
        if dev_type == "lvm":
            tags.append("lvm_lv")
    # Stratis uses device-mapper devices and commonly formats filesystems as
    # XFS. Only the distinctive mapper namespace is a positive lsblk clue.
    if mapper_name.startswith("stratis-") or path.startswith("/dev/stratis/"):
        tags.append("stratis")
        if fstype:
            tags.append("stratis_filesystem")
    return tags


def annotate_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with conservative volume-layer annotations."""
    def visit(node: dict[str, Any]) -> dict[str, Any]:
        result = dict(node)
        result["volume_features"] = classify_volume(node)
        result["children"] = [visit(child) for child in node.get("children", [])]
        return result

    return {
        **inventory,
        "devices": [visit(device) for device in inventory.get("devices", [])],
    }

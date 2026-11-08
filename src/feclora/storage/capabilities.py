"""Discover Clonezilla-style storage utilities without invoking them."""

from __future__ import annotations

import shutil
from typing import Callable

# Partclone exposes filesystem-specific executables, as used by Clonezilla.
# Their presence does not guarantee that a particular volume is supported.
TOOL_GROUPS = {
    "inventory": ("lsblk", "blkid", "findmnt"),
    "partition_tables": ("sfdisk", "sfdisk"),
    "partitioning": ("parted", "sgdisk"),
    "partclone": (
        "partclone.ext4",
        "partclone.extfs",
        "partclone.ntfs",
        "partclone.xfs",
        "partclone.btrfs",
        "partclone.fat",
        "partclone.exfat",
        "partclone.f2fs",
        "partclone.dd",
        "partclone.chkimg",
    ),
    "raw_imaging": ("dd",),
    "compression": ("gzip", "pigz", "zstd", "xz", "lz4"),
    "integrity": ("sha256sum",),
    "encryption": ("cryptsetup", "age"),
    "image_signing": ("minisign",),
    "volume_management": ("lvm", "dmsetup", "stratis"),
    "btrfs": ("btrfs",),
    "hardware_diagnostics": ("smartctl",),
}


def discover_capabilities(
    which: Callable[[str], str | None] | None = None,
) -> dict:
    """Return executable paths grouped by purpose; execute no external command."""
    resolver = which or shutil.which
    groups = {
        group: {tool: resolver(tool) for tool in dict.fromkeys(tools)}
        for group, tools in TOOL_GROUPS.items()
    }
    return {
        "schema_version": 1,
        "groups": groups,
        "available": sorted(
            tool for tools in groups.values()
            for tool, path in tools.items() if path is not None
        ),
        "missing": sorted(
            tool for tools in groups.values()
            for tool, path in tools.items() if path is None
        ),
        "status": "executable_presence_only",
    }

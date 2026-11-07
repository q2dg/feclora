"""Discover installed storage utilities without invoking them."""

from __future__ import annotations

import shutil
from typing import Callable

# Presence is not proof that a particular device/filesystem is supported.
TOOL_GROUPS = {
    "inventory": ("lsblk", "blkid", "findmnt"),
    "partitioning": ("parted", "sfdisk", "sgdisk"),
    "filesystem_tools": ("e2fsck", "e2label", "xfs_repair", "btrfs"),
    "imaging": ("partclone", "dd"),
    "compression": ("gzip", "zstd", "xz"),
    "integrity": ("sha256sum",),
    "encryption": ("cryptsetup",),
    "volume_management": ("lvm",),
    "hardware_diagnostics": ("smartctl",),
}


def discover_capabilities(
    which: Callable[[str], str | None] | None = None,
) -> dict:
    """Return executable paths grouped by purpose; execute no external command."""
    resolver = which or shutil.which
    groups = {
        group: {tool: resolver(tool) for tool in tools}
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

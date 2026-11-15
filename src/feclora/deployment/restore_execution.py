"""Shared destructive restore execution engine for ISO, multicast and PXE clients.

Boot and transport adapters perform their own admission, target selection and
transfer. Once a verified manifest and locally resolved target are available,
all modes enter this common restore dispatcher.
"""
from __future__ import annotations

from os import PathLike
from typing import Any, Callable

from feclora.storage.disk_restore import DiskRestoreError, restore_disk
from feclora.storage.partition_restore import PartitionRestoreError, restore_partition
from feclora.storage.logical_volume_restore import (
    LogicalVolumeRestoreError, restore_logical_volume,
)


class RestoreExecutionError(RuntimeError):
    """A shared restore operation failed or was rejected."""


def execute_restore(
    manifest_path: str | PathLike[str],
    repository: str | PathLike[str],
    target_path: str,
    *,
    target_type: str = "disk",
    confirmation: str,
    age_identity_file: str | PathLike[str] | None = None,
    age_passphrase: str | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    pre_write_callback: Callable[[], None] | None = None,
    executables: dict[str, str | None] | None = None,
) -> None:
    """Run the same manifest-backed restore implementation for every boot mode."""
    if target_type not in {"disk", "partition", "logical_volume"}:
        raise RestoreExecutionError("unsupported restore target type")
    if not isinstance(target_path, str) or not target_path.startswith("/dev/"):
        raise RestoreExecutionError("restore target must be an absolute /dev path")
    if confirmation != f"ERASE {target_path}":
        raise RestoreExecutionError(f"explicit local restore confirmation required: ERASE {target_path}")
    if age_identity_file is not None and age_passphrase is not None:
        raise RestoreExecutionError("choose either an age identity file or an age passphrase, not both")

    restore_function = {
        "disk": restore_disk,
        "partition": restore_partition,
        "logical_volume": restore_logical_volume,
    }[target_type]
    kwargs: dict[str, Any] = {
        "confirmation": confirmation,
        "age_identity_file": age_identity_file,
        "progress_callback": progress_callback,
        "executables": executables,
    }
    if age_passphrase is not None:
        if target_type != "disk":
            raise RestoreExecutionError("one-shot age passphrases are currently supported only for whole-disk restores")
        kwargs["age_passphrase"] = age_passphrase
    if target_type == "disk" and pre_write_callback is not None:
        kwargs["pre_write_callback"] = pre_write_callback
    if target_type == "logical_volume":
        from feclora.storage.inventory import collect_inventory
        kwargs["inventory_provider"] = collect_inventory
    try:
        restore_function(manifest_path, repository, target_path, **kwargs)
    except (DiskRestoreError, PartitionRestoreError, LogicalVolumeRestoreError, OSError) as exc:
        raise RestoreExecutionError(f"{target_type} restore failed: {exc}") from exc

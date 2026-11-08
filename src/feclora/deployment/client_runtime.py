"""Client-side image save/restore execution for authenticated unicast jobs.

The caller must first complete the mTLS control handshake and obtain explicit
local device authorization. The selected /dev path and typed confirmation stay
inside this Client process; only a human-readable target description is sent
to the Server. Image payloads are transferred over the same authenticated TLS
socket and verified before any restore write.
"""
from __future__ import annotations

import os
import stat
from typing import Any, Callable

from feclora.deployment.artifact_transfer import ImageTransferError, receive_image_set, send_image_set
from feclora.deployment.control import DeploymentControlError
from feclora.deployment.job import DeploymentJob
from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.disk_restore import DiskRestoreError, restore_disk
from feclora.storage.image_security import ImageSecurityError


class ClientImageRuntimeError(RuntimeError):
    """A Client image save/restore operation failed closed."""


def execute_client_image_job(
    job: DeploymentJob,
    tls_socket: Any,
    *,
    local_device_path: str,
    confirmation: str,
    server_identity: str,
    repository: str | os.PathLike[str],
    trusted_server_public_key: str | os.PathLike[str],
    local_minisign_secret_key: str | os.PathLike[str] | None = None,
    local_minisign_public_key: str | os.PathLike[str] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    compression: str = "gzip",
    compression_level: int | None = 6,
    progress_callback: Callable[[int, int | None], None] | None = None,
    executables: dict[str, str | None] | None = None,
) -> tuple[bool, str]:
    """Run one signed whole-disk image job after local, role-specific approval."""
    if not isinstance(local_device_path, str) or not local_device_path.startswith("/dev/"):
        raise ClientImageRuntimeError("local device selection must be an absolute /dev path")
    try:
        info = os.stat(local_device_path)
    except OSError as exc:
        raise ClientImageRuntimeError(f"cannot inspect locally selected device: {exc}") from exc
    if not stat.S_ISBLK(info.st_mode):
        raise ClientImageRuntimeError("local device selection must resolve to a block device")
    if job.operation == "restore":
        required = f"ERASE {local_device_path} FROM {server_identity}"
        if confirmation != required:
            raise ClientImageRuntimeError(f"explicit local restore confirmation required: {required}")
        try:
            manifest_path = receive_image_set(
                tls_socket, repository, expected_image_id=job.image_id,
                trusted_public_key=trusted_server_public_key,
            )
            restore_disk(
                manifest_path, repository, local_device_path,
                confirmation=f"ERASE {local_device_path}",
                minisign_public_key=trusted_server_public_key,
                require_signature=True,
                age_identity_file=age_identity_file,
                progress_callback=progress_callback,
                executables=executables,
            )
            return True, f"image {job.image_id} restored and destination read-back verified"
        except (ImageTransferError, DiskRestoreError, ImageSecurityError, OSError) as exc:
            raise ClientImageRuntimeError(f"restore failed: {exc}") from exc

    if job.operation == "save":
        required = f"READ {local_device_path} TO {server_identity}"
        if confirmation != required:
            raise ClientImageRuntimeError(f"explicit local capture confirmation required: {required}")
        if not local_minisign_secret_key or not local_minisign_public_key:
            raise ClientImageRuntimeError("Client save requires its enrolled minisign signing key and matching public key")
        try:
            capture_disk(
                local_device_path, job.image_id, repository,
                compression=compression, compression_level=compression_level,
                minisign_secret_key=local_minisign_secret_key,
                progress_callback=progress_callback,
                executables=executables,
            )
            manifest_path = os.path.join(os.fspath(repository), job.image_id + ".manifest.json")
            send_image_set(
                tls_socket, repository, manifest_path,
                expected_image_id=job.image_id,
                trusted_public_key=local_minisign_public_key,
            )
            return True, f"image {job.image_id} captured, signed and transferred"
        except (ImageTransferError, DiskCaptureError, ImageSecurityError, OSError) as exc:
            raise ClientImageRuntimeError(f"capture/transfer failed: {exc}") from exc

    raise ClientImageRuntimeError("unsupported deployment operation")

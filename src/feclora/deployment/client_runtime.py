"""Client-side image save/restore execution over Server-authenticated TLS.

The caller must first complete the Server-authenticated TLS control handshake and obtain explicit
local device authorization. The selected /dev path and typed confirmation stay
inside this Client process; only a human-readable target description is sent
to the Server. Image payloads are transferred over the same Server-authenticated TLS
socket and verified before any restore write.
"""
from __future__ import annotations

import os
import stat
import shutil
from typing import Any, Callable

from feclora.deployment.artifact_transfer import ImageTransferError, receive_image_set, send_image_set
from feclora.deployment.control import LocalTargetApproval, receive_control_message, send_control_message
from feclora.deployment.job import DeploymentJob
from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.disk_restore import DiskRestoreError, restore_disk
from feclora.storage.partition_restore import PartitionRestoreError, restore_partition
from feclora.storage.logical_volume_restore import LogicalVolumeRestoreError, restore_logical_volume
from feclora.storage.inventory import collect_inventory
from feclora.storage.image_security import ImageSecurityError
from feclora.network.remote_clone import receive_remote_disk


class ClientImageRuntimeError(RuntimeError):
    """A Client image save/restore operation failed closed."""


def execute_client_image_job(
    job: DeploymentJob,
    tls_socket: Any,
    approval: LocalTargetApproval,
    *,
    server_identity: str,
    repository: str | os.PathLike[str],
    trusted_server_public_key: str | os.PathLike[str] | None,
    local_minisign_secret_key: str | os.PathLike[str] | None = None,
    local_minisign_public_key: str | os.PathLike[str] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    age_recipients_file: str | os.PathLike[str] | None = None,
    encrypt_image: bool = False,
    sign_image: bool = False,
    compression: str = "gzip",
    compression_level: int | None = 6,
    progress_callback: Callable[[int, int | None], None] | None = None,
    transfer_progress_callback: Callable[[int, int], None] | None = None,
    pre_write_callback: Callable[[], None] | None = None,
    executables: dict[str, str | None] | None = None,
) -> tuple[bool, str]:
    """Run one whole-disk image job over Server-authenticated TLS after local approval."""
    local_device_path = approval.device_path
    confirmation = approval.confirmation
    if not isinstance(local_device_path, str) or not local_device_path.startswith("/dev/"):
        raise ClientImageRuntimeError("local device selection must be an absolute /dev path")
    try:
        info = os.lstat(local_device_path)
    except OSError as exc:
        raise ClientImageRuntimeError(f"cannot inspect locally selected device: {exc}") from exc
    if not stat.S_ISBLK(info.st_mode):
        raise ClientImageRuntimeError("local device selection must resolve to a block device")
    tls_socket.settimeout(86400)
    if job.operation == "clone":
        required = f"ERASE {local_device_path}"
        if confirmation != required:
            raise ClientImageRuntimeError(f"explicit local clone-target confirmation required: {required}")
        try:
            result = receive_remote_disk(
                tls_socket,
                target_path=local_device_path,
                confirmation=confirmation,
                progress_callback=progress_callback,
                executables=executables,
            )
            return True, (
                f"remote {job.target_type} clone verified: {result.byte_count} bytes, "
                f"SHA-256 {result.readback_sha256}"
            )
        except Exception as exc:
            raise ClientImageRuntimeError(f"remote {job.target_type} clone failed: {exc}") from exc
    if job.operation == "restore":
        required = f"ERASE {local_device_path}"
        if confirmation != required:
            raise ClientImageRuntimeError(f"explicit local restore confirmation required: {required}")
        try:
            offer = receive_control_message(tls_socket, expected_type="transfer_offer")
            if (set(offer) != {"type", "job_id", "image_id"}
                    or offer.get("job_id") != job.job_id
                    or offer.get("image_id") != job.image_id):
                raise ClientImageRuntimeError("Server image offer is not bound to this armed job")
            manifest_path = receive_image_set(
                tls_socket, repository, expected_image_id=job.image_id,
                trusted_public_key=trusted_server_public_key,
                progress_callback=transfer_progress_callback,
            )
            signature_present = os.path.isfile(manifest_path + ".minisig")
            restore_function = (restore_logical_volume if job.target_type == "logical_volume" else restore_partition if job.target_type == "partition" else restore_disk)
            restore_kwargs = {
                "confirmation": f"ERASE {local_device_path}",
                "minisign_public_key": trusted_server_public_key if signature_present else None,
                "require_signature": signature_present,
                "age_identity_file": age_identity_file,
                "progress_callback": progress_callback,
                "executables": executables,
            }
            if job.target_type == "disk" and pre_write_callback is not None:
                restore_kwargs["pre_write_callback"] = pre_write_callback
            if job.target_type == "logical_volume":
                restore_kwargs["inventory_provider"] = collect_inventory
            restore_function(
                manifest_path, repository, local_device_path, **restore_kwargs,
            )
            return True, f"image {job.image_id} restored and destination read-back verified"
        except (ImageTransferError, DiskRestoreError, PartitionRestoreError, LogicalVolumeRestoreError, ImageSecurityError, OSError) as exc:
            raise ClientImageRuntimeError(f"restore failed: {exc}") from exc

    if job.operation == "save":
        if not isinstance(encrypt_image, bool) or not isinstance(sign_image, bool):
            raise ClientImageRuntimeError("per-image encryption/signing choices must be boolean")
        if encrypt_image and (not age_recipients_file or not shutil.which("age")):
            raise ClientImageRuntimeError("age encryption was selected but no usable recipient inventory or age executable is available")
        if sign_image and (
            not local_minisign_secret_key or not local_minisign_public_key or not shutil.which("minisign")
        ):
            raise ClientImageRuntimeError("minisign signing was selected but no usable signing keypair or minisign executable is available")
        required = f"READ {local_device_path}"
        if confirmation != required:
            raise ClientImageRuntimeError(f"explicit local capture confirmation required: {required}")
        try:
            capture_disk(
                local_device_path, job.image_id, repository,
                compression=compression, compression_level=compression_level,
                minisign_secret_key=local_minisign_secret_key if sign_image else None,
                age_recipients_file=age_recipients_file if encrypt_image else None,
                progress_callback=progress_callback,
                executables=executables,
            )
            manifest_path = os.path.join(os.fspath(repository), job.image_id + ".manifest.json")
            send_control_message(tls_socket, {
                "type": "transfer_ready", "job_id": job.job_id,
                "image_id": job.image_id,
            })
            send_image_set(
                tls_socket, repository, manifest_path,
                expected_image_id=job.image_id,
                trusted_public_key=local_minisign_public_key if sign_image else None,
                progress_callback=transfer_progress_callback,
            )
            signed = os.path.isfile(manifest_path + ".minisig")
            protections = [
                label for enabled, label in (
                    (encrypt_image, "age-encrypted"),
                    (signed, "minisign-signed"),
                ) if enabled
            ]
            protection_detail = " (" + ", ".join(protections) + ")" if protections else " (unsigned, unencrypted)"
            return True, f"image {job.image_id} captured{protection_detail} and transferred"
        except (ImageTransferError, DiskCaptureError, ImageSecurityError, OSError) as exc:
            raise ClientImageRuntimeError(f"capture/transfer failed: {exc}") from exc

    raise ClientImageRuntimeError("unsupported deployment operation")

"""Authenticated, signed-manifest UDPcast restore runtime for multiple Clients.

The mTLS channel distributes only the signed manifest and coordinates the job.
UDPcast carries artifact bytes to private Client staging files. Every artifact
is verified against the signed manifest before the existing restore path may
write to the locally selected disk.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import tempfile
from typing import Any, Callable

from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, receive_control_message,
)
from feclora.deployment.job import DeploymentJob
from feclora.network.udpcast import (
    UDPcastConfig, UDPcastError, receive_multicast_artifact_to_staging,
    verify_staged_multicast_artifact,
)
from feclora.storage.disk_restore import DiskRestoreError, restore_disk
from feclora.storage.partition_restore import PartitionRestoreError, restore_partition
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.image_security import ImageSecurityError, verify_manifest_signature


class MulticastDeploymentError(RuntimeError):
    """Authenticated multicast restore failed closed."""


def rendezvous_group_for(data_group: str) -> str:
    """Derive a stable, distinct IPv4 multicast rendezvous group from the data group."""
    import ipaddress

    address = ipaddress.ip_address(data_group)
    if address.version != 4 or not address.is_multicast:
        raise MulticastDeploymentError("data group must be IPv4 multicast")
    low, high = int(ipaddress.ip_address("224.0.0.0")), int(ipaddress.ip_address("239.255.255.255"))
    candidate = int(address) + 1
    if candidate > high:
        candidate = int(address) - 1
    if candidate < low or candidate == int(address):
        raise MulticastDeploymentError("could not derive a distinct rendezvous group")
    return str(ipaddress.ip_address(candidate))


def udpcast_config_for_job(
    job: DeploymentJob, *, min_receivers: int, network_interface: str | None = None,
) -> UDPcastConfig:
    if job.transport != "multicast" or job.multicast_group is None or job.multicast_port is None:
        raise MulticastDeploymentError("deployment job is not configured for multicast")
    try:
        return UDPcastConfig(
            interface=network_interface or job.network_interface,
            data_group=job.multicast_group,
            rendezvous_group=rendezvous_group_for(job.multicast_group),
            portbase=job.multicast_port,
            ttl=1,
            max_bitrate="100m",
            min_receivers=min_receivers,
            max_wait_seconds=120,
        )
    except UDPcastError as exc:
        raise MulticastDeploymentError(f"invalid multicast job configuration: {exc}") from exc


def _write_private(path: str, payload: bytes) -> None:
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def execute_multicast_restore(
    job: DeploymentJob,
    tls_socket: Any,
    approval: LocalTargetApproval,
    *,
    server_identity: str,
    repository: str | os.PathLike[str],
    trusted_server_public_key: str | os.PathLike[str] | None,
    firewall: Any,
    network_interface: str | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    executables: dict[str, str | None] | None = None,
) -> tuple[bool, str]:
    """Receive all signed artifacts privately, verify them, then restore one local disk."""
    if job.transport != "multicast" or job.operation != "restore":
        raise MulticastDeploymentError("multicast runtime currently supports restore jobs only")
    if not network_interface:
        raise MulticastDeploymentError("Client must select its own local multicast receive interface")
    required = f"ERASE {approval.device_path} FROM {server_identity}"
    if approval.confirmation != required:
        raise MulticastDeploymentError("local typed restore confirmation does not match")
    try:
        device_info = os.lstat(approval.device_path)
    except OSError as exc:
        raise MulticastDeploymentError(f"cannot inspect selected local disk: {exc}") from exc
    if not stat.S_ISBLK(device_info.st_mode):
        raise MulticastDeploymentError("selected restore target must be a block device")
    tls_socket.settimeout(120)
    offer = receive_control_message(tls_socket, expected_type="transfer_offer")
    expected_fields = {"type", "job_id", "image_id", "manifest_b64", "signature_b64"}
    if (set(offer) != expected_fields or offer.get("job_id") != job.job_id
            or offer.get("image_id") != job.image_id):
        raise MulticastDeploymentError("multicast manifest offer is not bound to this deployment job")
    try:
        manifest_bytes = base64.b64decode(offer["manifest_b64"], validate=True)
        signature_bytes = base64.b64decode(offer["signature_b64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise MulticastDeploymentError("multicast manifest offer contains invalid base64") from exc
    if not manifest_bytes or len(manifest_bytes) > 8 * 1024 or len(signature_bytes) > 2048:
        raise MulticastDeploymentError("multicast manifest exceeds the control-plane size limit")
    signature_present = bool(signature_bytes)
    if signature_present and not trusted_server_public_key:
        raise MulticastDeploymentError("signed multicast image requires an independently trusted Server minisign key")
    root = os.path.abspath(os.fspath(repository))
    try:
        root_info = os.lstat(root)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise MulticastDeploymentError("Client image repository must be a real directory")
        workdir = tempfile.mkdtemp(prefix=".feclora-multicast-", dir=root)
        os.chmod(workdir, 0o700)
        manifest_path = os.path.join(workdir, job.image_id + ".manifest.json")
        _write_private(manifest_path, manifest_bytes)
        if signature_present:
            _write_private(manifest_path + ".minisig", signature_bytes)
            verify_manifest_signature(manifest_path, trusted_server_public_key)
        manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
        if manifest.image_id != job.image_id:
            raise MulticastDeploymentError("signed image manifest does not match the job image identifier")
        if manifest.image_type != job.target_type:
            raise MulticastDeploymentError("signed image type does not match the locally approved deployment target type")
        if not manifest.artifacts:
            raise MulticastDeploymentError("multicast image manifest contains no artifacts")
        required_bytes = sum(item.size_bytes for item in manifest.artifacts)
        if shutil.disk_usage(workdir).free < required_bytes:
            raise MulticastDeploymentError("insufficient Client staging space for the complete signed image set")
        config = udpcast_config_for_job(
            job, min_receivers=len(job.authorized_clients),
            network_interface=network_interface,
        )
        for artifact in manifest.artifacts:
            staged = receive_multicast_artifact_to_staging(
                workdir, artifact, config, firewall=firewall,
            )
            destination = os.path.join(workdir, artifact.filename)
            os.replace(staged, destination)
            os.rmdir(os.path.dirname(staged))
            verify_staged_multicast_artifact(
                destination, manifest_path, trusted_server_public_key, artifact.filename,
            )
        # The restore function re-verifies any signature, artifact hashes and
        # optional age decryption before opening the selected block device.
        restore_function = restore_partition if manifest.image_type == "partition" else restore_disk
        restore_function(
            manifest_path, workdir, approval.device_path,
            confirmation=f"ERASE {approval.device_path}",
            minisign_public_key=trusted_server_public_key if signature_present else None,
            require_signature=signature_present,
            age_identity_file=age_identity_file,
            progress_callback=progress_callback,
            executables=executables,
        )
        return True, f"multicast image {job.image_id} restored and destination read-back verified"
    except (
        OSError, ValueError, ManifestValidationError, ImageSecurityError,
        DiskRestoreError, PartitionRestoreError, UDPcastError,
    ) as exc:
        raise MulticastDeploymentError(f"multicast restore failed: {exc}") from exc
    finally:
        if "workdir" in locals():
            shutil.rmtree(workdir, ignore_errors=True)

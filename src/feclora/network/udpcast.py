"""Safe UDPcast multicast file transport for authenticated deployment jobs.

This module is deliberately limited to moving one manifested artifact into a
private staging file. It never writes a block device and never treats UDPcast
rendezvous, a MAC address, or multicast reception as client authentication.
The caller must establish the mTLS control plane and register/authorize clients
before invoking this transport.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from feclora.deployment.coordinator import ClientState, DeploymentCoordinator, JobState
from feclora.storage.image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from feclora.storage.image_security import ImageSecurityError, verify_manifest_signature


class UDPcastError(RuntimeError):
    """UDPcast configuration, execution, or staged-artifact verification failed."""


_BITRATE_RE = re.compile(r"^([1-9][0-9]*)([kKmMgG])?$")
_FEC_RE = re.compile(r"^[1-9][0-9]*x[1-9][0-9]*(?:/[1-9][0-9]*)?$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


@dataclass(frozen=True)
class UDPcastConfig:
    interface: str
    data_group: str
    rendezvous_group: str
    portbase: int = 9000
    ttl: int = 1
    max_bitrate: str = "100m"
    fec: str | None = None
    min_receivers: int = 1
    max_wait_seconds: int = 120

    def __post_init__(self) -> None:
        if not isinstance(self.interface, str) or not _INTERFACE_RE.fullmatch(self.interface):
            raise UDPcastError("Invalid multicast network interface")
        for label, value in (("data", self.data_group), ("rendezvous", self.rendezvous_group)):
            try:
                address = ipaddress.ip_address(value)
            except (ValueError, TypeError) as exc:
                raise UDPcastError(f"{label} group must be an IPv4 multicast address") from exc
            if address.version != 4 or not address.is_multicast or address.is_unspecified:
                raise UDPcastError(f"{label} group must be an IPv4 multicast address")
        if self.data_group == self.rendezvous_group:
            raise UDPcastError("Use distinct multicast groups for data and rendezvous")
        if isinstance(self.portbase, bool) or not isinstance(self.portbase, int) or not 1024 <= self.portbase <= 65534 or self.portbase % 2:
            raise UDPcastError("UDPcast portbase must be even and between 1024 and 65534")
        if isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or not 1 <= self.ttl <= 32:
            raise UDPcastError("Multicast TTL must be between 1 and 32")
        bitrate_match = _BITRATE_RE.fullmatch(self.max_bitrate) if isinstance(self.max_bitrate, str) else None
        if not bitrate_match:
            raise UDPcastError("max_bitrate must be a positive integer with optional k, m, or g suffix")
        bitrate = int(bitrate_match.group(1))
        suffix = (bitrate_match.group(2) or "").lower()
        bitrate *= {"": 1, "k": 1000, "m": 1000000, "g": 1000000000}[suffix]
        if bitrate > 10_000_000_000:
            raise UDPcastError("max_bitrate must not exceed 10 Gbit/s")
        if self.fec is not None:
            fec_match = _FEC_RE.fullmatch(self.fec) if isinstance(self.fec, str) else None
            if not fec_match:
                raise UDPcastError("FEC must use stripesxredundancy[/stripesize] syntax")
            stripes, redundancy, *stripe_size = map(int, re.split(r"[x/]", self.fec))
            if stripes > 255 or redundancy > 255 or (stripe_size and stripe_size[0] > 65535):
                raise UDPcastError("FEC values exceed the supported safety bounds")
        if isinstance(self.min_receivers, bool) or not isinstance(self.min_receivers, int) or not 1 <= self.min_receivers <= 4096:
            raise UDPcastError("min_receivers must be between 1 and 4096")
        if isinstance(self.max_wait_seconds, bool) or not isinstance(self.max_wait_seconds, int) or not 1 <= self.max_wait_seconds <= 86400:
            raise UDPcastError("max_wait_seconds must be between 1 and 86400")


def _regular_file(path: str, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise UDPcastError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise UDPcastError(f"{label} must be a regular file, not a symlink")
    return info


def _load_signed_manifest(
    manifest_path: str,
    public_key_path: str,
    *,
    minisign_executable: str | None = None,
) -> ImageManifest:
    _regular_file(manifest_path, "Image manifest")
    _regular_file(public_key_path, "Trusted minisign public key")
    try:
        verify_manifest_signature(
            manifest_path, public_key_path, minisign_executable=minisign_executable,
        )
        with open(manifest_path, "r", encoding="utf-8") as stream:
            return ImageManifest.from_json(stream.read())
    except (OSError, UnicodeError, ManifestValidationError, ImageSecurityError) as exc:
        raise UDPcastError(f"Image manifest signature or schema validation failed: {exc}") from exc


def verify_artifact_file(path: str, artifact: ImageArtifact) -> None:
    """Check the exact stored bytes described by a signed manifest artifact."""
    info = _regular_file(path, "Image artifact")
    if info.st_size != artifact.size_bytes:
        raise UDPcastError("Image artifact size does not match the signed manifest")
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise UDPcastError(f"Cannot read image artifact: {exc}") from exc
    if digest.hexdigest() != artifact.sha256:
        raise UDPcastError("Image artifact SHA-256 does not match the signed manifest")


def build_sender_argv(
    executable: str,
    source_path: str,
    config: UDPcastConfig,
) -> list[str]:
    """Build a shell-free sender command; no automatic-start option is used."""
    return [
        executable, "--file", source_path, "--interface", config.interface,
        "--mcast-data-address", config.data_group,
        "--mcast-rdv-address", config.rendezvous_group,
        "--portbase", str(config.portbase), "--ttl", str(config.ttl),
        "--max-bitrate", config.max_bitrate,
        "--min-receivers", str(config.min_receivers),
        "--max-wait", str(config.max_wait_seconds), "--nokbd",
        *(["--fec", config.fec] if config.fec else []),
    ]


def build_receiver_argv(
    executable: str,
    staging_path: str,
    config: UDPcastConfig,
) -> list[str]:
    """Build a receiver command that can only write to the supplied staging file."""
    return [
        executable, "--file", staging_path, "--interface", config.interface,
        "--mcast-rdv-address", config.rendezvous_group,
        "--portbase", str(config.portbase), "--ttl", str(config.ttl),
        "--nokbd",
    ]


def _run_process(
    argv: list[str],
    *,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: int | None = None,
) -> None:
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = runner_popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=log, close_fds=True,
            )
            while process.poll() is None:
                if cancel_check is not None and cancel_check():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise UDPcastError("UDPcast transfer cancelled by operator")
                if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise UDPcastError("UDPcast transfer timed out")
                time.sleep(0.2)
            if process.returncode != 0:
                log.seek(0)
                detail = log.read(4096).decode("utf-8", errors="replace").strip()
                raise UDPcastError("UDPcast exited unsuccessfully" + (f": {detail}" if detail else ""))
    except UDPcastError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise UDPcastError(f"Could not execute UDPcast: {exc}") from exc


@contextmanager
def multicast_firewall_scope(firewall: Any, interface: str, portbase: int) -> Iterator[None]:
    """Temporarily allow only UDPcast's two UDP ports on the selected interface."""
    if firewall is None:
        raise UDPcastError("A scoped firewalld manager is required for multicast transport")
    ports = [f"{portbase}/udp", f"{portbase + 1}/udp"]
    if firewall.is_open(interface):
        added = firewall.add_ports(interface, ports)
        try:
            yield
        finally:
            if added:
                firewall.remove_ports(interface, added)
        return
    opened = False
    try:
        firewall.open(interface, ports, include_tftp=False)
        opened = True
        yield
    finally:
        if opened:
            firewall.close(interface)


def send_multicast_artifact(
    coordinator: DeploymentCoordinator,
    source_path: str,
    manifest_path: str,
    public_key_path: str,
    config: UDPcastConfig,
    *,
    udp_sender: str | None = None,
    minisign_executable: str | None = None,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    firewall: Any,
) -> None:
    """Send a single artifact only after the deployment coordinator is armed."""
    job = coordinator.job
    if coordinator.state is not JobState.ARMED:
        raise UDPcastError("Deployment job must be explicitly armed before multicast transmission")
    if job.transport != "multicast" or job.network_interface != config.interface:
        raise UDPcastError("UDPcast configuration does not match the deployment job")
    if job.multicast_group != config.data_group or job.multicast_port != config.portbase:
        raise UDPcastError("UDPcast group/port do not match the deployment job")
    ready_count = sum(client.state is ClientState.READY for client in coordinator.clients())
    if ready_count < config.min_receivers:
        raise UDPcastError("Not enough authenticated, ready clients for the configured receiver threshold")
    manifest = _load_signed_manifest(
        manifest_path, public_key_path, minisign_executable=minisign_executable,
    )
    if manifest.image_id != job.image_id:
        raise UDPcastError("Signed image manifest does not match the deployment job image_id")
    artifact_name = os.path.basename(source_path)
    matches = [item for item in manifest.artifacts if item.filename == artifact_name]
    if len(matches) != 1:
        raise UDPcastError("Source artifact is not uniquely listed in the signed manifest")
    verify_artifact_file(source_path, matches[0])
    executable = udp_sender or shutil.which("udp-sender")
    if not executable:
        raise UDPcastError("udp-sender is required for multicast deployment")
    with multicast_firewall_scope(firewall, config.interface, config.portbase):
        _run_process(
            build_sender_argv(executable, os.path.abspath(source_path), config),
            runner_popen=runner_popen, cancel_check=cancel_check,
            timeout_seconds=config.max_wait_seconds + 86400,
        )


def receive_multicast_artifact_to_staging(
    staging_directory: str,
    artifact: ImageArtifact,
    config: UDPcastConfig,
    *,
    udp_receiver: str | None = None,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: int = 86400,
    firewall: Any,
) -> str:
    """Receive into a 0600 temporary file; caller must verify signed manifest before restore."""
    directory = os.path.abspath(staging_directory)
    try:
        directory_info = os.lstat(directory)
        if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode):
            raise UDPcastError("Staging directory must be a real directory")
        if shutil.disk_usage(directory).free < artifact.size_bytes:
            raise UDPcastError("Insufficient free space for a complete staged multicast artifact")
        private_dir = tempfile.mkdtemp(prefix=".feclora-udpcast-", dir=directory)
        os.chmod(private_dir, 0o700)
        fd, path = tempfile.mkstemp(prefix="artifact-", dir=private_dir)
        os.fchmod(fd, 0o600)
        os.close(fd)
    except UDPcastError:
        raise
    except OSError as exc:
        raise UDPcastError(f"Cannot prepare private staging file: {exc}") from exc
    executable = udp_receiver or shutil.which("udp-receiver")
    if not executable:
        shutil.rmtree(private_dir, ignore_errors=True)
        raise UDPcastError("udp-receiver is required for multicast deployment")
    try:
        with multicast_firewall_scope(firewall, config.interface, config.portbase):
            _run_process(
                build_receiver_argv(executable, path, config),
                runner_popen=runner_popen, cancel_check=cancel_check,
                timeout_seconds=timeout_seconds,
            )
        info = _regular_file(path, "Received staging artifact")
        if info.st_size != artifact.size_bytes:
            raise UDPcastError("Received artifact size does not match the expected manifest")
        return path
    except Exception:
        shutil.rmtree(private_dir, ignore_errors=True)
        raise


def verify_staged_multicast_artifact(
    staged_path: str,
    manifest_path: str,
    public_key_path: str,
    artifact_filename: str,
    *,
    minisign_executable: str | None = None,
) -> ImageArtifact:
    """Authenticate manifest and payload before any restore code may consume staging."""
    manifest = _load_signed_manifest(
        manifest_path, public_key_path, minisign_executable=minisign_executable,
    )
    matches = [item for item in manifest.artifacts if item.filename == artifact_filename]
    if len(matches) != 1:
        raise UDPcastError("Received artifact is not uniquely listed in the signed manifest")
    verify_artifact_file(staged_path, matches[0])
    return matches[0]


def discard_staged_multicast_artifact(staged_path: str) -> None:
    """Remove a staged payload and its private per-transfer directory after restore."""
    path = os.path.abspath(staged_path)
    parent = os.path.dirname(path)
    if not os.path.basename(parent).startswith(".feclora-udpcast-"):
        raise UDPcastError("Refusing to remove a file outside a Feclora multicast staging directory")
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise UDPcastError("Staged artifact is not a regular file")
        os.unlink(path)
        os.rmdir(parent)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise UDPcastError(f"Could not remove staged multicast artifact: {exc}") from exc

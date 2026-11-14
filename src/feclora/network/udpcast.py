"""Safe UDPcast multicast file transport for Server-authenticated deployment jobs.

This module is deliberately limited to moving one manifested artifact into a
private staging file. It never writes a block device and never treats UDPcast
rendezvous, a MAC address, or multicast reception as client authentication.
The caller must establish the Server-authenticated TLS control plane and
validate job-scoped Client MAC selection before invoking this transport. This
selection does not authenticate individual Clients.
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
            if not isinstance(value, str):
                raise UDPcastError(f"{label} group must be an IPv4 multicast address")
            try:
                address = ipaddress.ip_address(value)
            except (ValueError, TypeError) as exc:
                raise UDPcastError(f"{label} group must be an IPv4 multicast address") from exc
            if (address.version != 4 or address not in ipaddress.ip_network("239.0.0.0/8")):
                raise UDPcastError(f"{label} group must be in the administratively scoped IPv4 multicast range 239.0.0.0/8")
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


def _load_manifest(manifest_path: str) -> ImageManifest:
    _regular_file(manifest_path, "Image manifest")
    try:
        with open(manifest_path, "r", encoding="utf-8") as stream:
            return ImageManifest.from_json(stream.read())
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise UDPcastError(f"Image manifest or schema validation failed: {exc}") from exc


def verify_artifact_file(path: str, artifact: ImageArtifact) -> None:
    """Check the exact stored bytes described by a manifest artifact."""
    _regular_file(path, "Image artifact")
    digest = hashlib.sha256()
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise UDPcastError("Image artifact changed type while opening")
            if info.st_size != artifact.size_bytes:
                raise UDPcastError("Image artifact size does not match the manifest")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except UDPcastError:
        raise
    except OSError as exc:
        raise UDPcastError(f"Cannot safely read image artifact: {exc}") from exc
    if digest.hexdigest() != artifact.sha256:
        raise UDPcastError("Image artifact SHA-256 does not match the manifest")


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


def build_physical_stream_sender_argv(
    executable: str,
    config: UDPcastConfig,
) -> list[str]:
    """Build a UDPcast stdin sender; no image or staging-file path is accepted."""
    return [
        executable, "--interface", config.interface,
        "--mcast-data-address", config.data_group,
        "--mcast-rdv-address", config.rendezvous_group,
        "--portbase", str(config.portbase), "--ttl", str(config.ttl),
        "--max-bitrate", config.max_bitrate,
        "--min-receivers", str(config.min_receivers),
        "--max-wait", str(config.max_wait_seconds), "--nokbd",
        *(["--fec", config.fec] if config.fec else []),
    ]


def build_physical_stream_receiver_argv(
    executable: str,
    config: UDPcastConfig,
) -> list[str]:
    """Build a UDPcast stdout receiver; no file or block-device path is accepted."""
    return [
        executable, "--interface", config.interface,
        "--mcast-rdv-address", config.rendezvous_group,
        "--portbase", str(config.portbase), "--ttl", str(config.ttl), "--nokbd",
    ]


def feed_physical_stream_to_sender(
    source_stream: Any,
    sender_stdin: Any,
    expected_bytes: int,
    *,
    chunk_size: int = 1024 * 1024,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Feed exactly the approved source byte range to udp-sender stdin and hash it."""
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes <= 0:
        raise UDPcastError("physical multicast source size must be a positive integer")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or not 4096 <= chunk_size <= 16 * 1024 * 1024:
        raise UDPcastError("physical multicast chunk size is outside the supported bounds")
    digest = hashlib.sha256()
    total = 0
    try:
        while total < expected_bytes:
            if cancel_check is not None and cancel_check():
                raise UDPcastError("physical multicast source stream cancelled")
            chunk = source_stream.read(min(chunk_size, expected_bytes - total))
            if not isinstance(chunk, (bytes, bytearray, memoryview)) or not chunk:
                raise UDPcastError(f"physical multicast source ended early ({total}/{expected_bytes} bytes)")
            view = memoryview(chunk)
            if len(view) > expected_bytes - total:
                view = view[:expected_bytes - total]
            digest.update(view)
            offset = 0
            while offset < len(view):
                written = sender_stdin.write(view[offset:])
                if isinstance(written, bool) or not isinstance(written, int) or written <= 0 or written > len(view) - offset:
                    raise UDPcastError("udp-sender stdin returned an invalid or zero-length write")
                offset += written
            total += len(view)
            if progress_callback is not None:
                progress_callback(total, expected_bytes)
        sender_stdin.close()
    except UDPcastError:
        raise
    except (OSError, BrokenPipeError) as exc:
        raise UDPcastError(f"physical multicast sender pipe failed: {exc}") from exc
    return {"bytes_sent": total, "sha256": digest.hexdigest()}


def verify_received_physical_stream(
    receiver_stdout: Any,
    write: Callable[[memoryview], int],
    flush: Callable[[], None],
    readback: Callable[[int], bytes],
    *,
    expected_bytes: int,
    expected_sha256: str,
    chunk_size: int = 1024 * 1024,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Write UDPcast stdout directly through an approved writer and verify source/read-back digests."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise UDPcastError("physical multicast source SHA-256 is invalid")
    from feclora.network.physical_multicast import (
        PhysicalMulticastError, write_and_verify_stream,
    )
    try:
        result = write_and_verify_stream(
            receiver_stdout, write, flush, readback,
            expected_bytes=expected_bytes, chunk_size=chunk_size,
            cancel_check=cancel_check,
        )
    except PhysicalMulticastError as exc:
        raise UDPcastError(f"physical multicast destination verification failed: {exc}") from exc
    if result["sha256"] != expected_sha256:
        raise UDPcastError("Client received stream SHA-256 does not match the Server source digest")
    return result


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
    """Temporarily allow UDPcast ports and IGMP on the selected interface only."""
    if firewall is None:
        raise UDPcastError("A scoped firewalld manager is required for multicast transport")
    ports = [f"{portbase}/udp", f"{portbase + 1}/udp"]
    protocols = ["igmp"]
    if firewall.is_open(interface):
        added_ports: tuple[str, ...] = ()
        added_protocols: tuple[str, ...] = ()
        try:
            added_ports = firewall.add_ports(interface, ports)
            added_protocols = firewall.add_protocols(interface, protocols)
            yield
        finally:
            try:
                if added_protocols:
                    firewall.remove_protocols(interface, added_protocols)
            finally:
                if added_ports:
                    firewall.remove_ports(interface, added_ports)
        return
    opened = False
    try:
        firewall.open(interface, ports, include_tftp=False)
        opened = True
        firewall.add_protocols(interface, protocols)
        yield
    finally:
        if opened:
            firewall.close(interface)


def send_multicast_artifact(
    coordinator: DeploymentCoordinator,
    source_path: str,
    manifest_path: str,
    config: UDPcastConfig,
    *,
    udp_sender: str | None = None,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    firewall: Any,
) -> None:
    """Send one artifact only after the deployment coordinator is armed."""
    job = coordinator.job
    if coordinator.state not in {JobState.ARMED, JobState.RUNNING}:
        raise UDPcastError("Deployment job must be explicitly armed before multicast transmission")
    if job.transport != "multicast" or job.network_interface != config.interface:
        raise UDPcastError("UDPcast configuration does not match the deployment job")
    if job.multicast_group != config.data_group or job.multicast_port != config.portbase:
        raise UDPcastError("UDPcast group/port do not match the deployment job")
    ready_count = sum(
        client.state in {ClientState.READY, ClientState.RUNNING}
        for client in coordinator.clients()
    )
    if ready_count < config.min_receivers:
        raise UDPcastError("Not enough authenticated, ready/running clients for the configured receiver threshold")
    manifest = _load_manifest(manifest_path)
    if manifest.image_id != job.image_id:
        raise UDPcastError("Image manifest does not match the deployment job image_id")
    artifact_name = os.path.basename(source_path)
    matches = [item for item in manifest.artifacts if item.filename == artifact_name]
    if len(matches) != 1:
        raise UDPcastError("Source artifact is not uniquely listed in the manifest")
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
    """Receive into a 0600 temporary file; caller must verify manifest and SHA-256 digests before restore."""
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
    artifact_filename: str,
) -> ImageArtifact:
    """Verify the manifest schema and artifact SHA-256 before restore."""
    manifest = _load_manifest(manifest_path)
    matches = [item for item in manifest.artifacts if item.filename == artifact_filename]
    if len(matches) != 1:
        raise UDPcastError("Received artifact is not uniquely listed in the manifest")
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


def send_physical_multicast_stream(
    source_stream: Any,
    expected_bytes: int,
    config: UDPcastConfig,
    *,
    udp_sender: str | None = None,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    firewall: Any,
) -> dict[str, Any]:
    """Multicast an exact physical-device byte stream through a pipe, never a file."""
    executable = udp_sender or shutil.which("udp-sender")
    if not executable:
        raise UDPcastError("udp-sender is required for physical multicast")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes <= 0:
        raise UDPcastError("physical multicast source size must be a positive integer")
    with multicast_firewall_scope(firewall, config.interface, config.portbase):
        process = None
        try:
            with tempfile.TemporaryFile(mode="w+b") as log:
                process = runner_popen(
                    build_physical_stream_sender_argv(executable, config),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=log, close_fds=True,
                )
                if process.stdin is None:
                    raise UDPcastError("udp-sender did not expose its physical stream input pipe")
                result = feed_physical_stream_to_sender(
                    source_stream, process.stdin, expected_bytes,
                    cancel_check=cancel_check, progress_callback=progress_callback,
                )
                try:
                    return_code = process.wait(timeout=config.max_wait_seconds + 86400)
                except subprocess.TimeoutExpired as exc:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise UDPcastError("physical multicast sender timed out") from exc
                if return_code != 0:
                    log.seek(0)
                    detail = log.read(4096).decode("utf-8", errors="replace").strip()
                    raise UDPcastError("udp-sender failed" + (f": {detail}" if detail else ""))
                return result
        except UDPcastError:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise UDPcastError(f"physical multicast sender failed: {exc}") from exc


def receive_physical_multicast_stream(
    write: Callable[[memoryview], int],
    flush: Callable[[], None],
    readback: Callable[[int], bytes],
    *,
    expected_bytes: int,
    expected_sha256: str,
    config: UDPcastConfig,
    udp_receiver: str | None = None,
    runner_popen: Callable[..., Any] = subprocess.Popen,
    cancel_check: Callable[[], bool] | None = None,
    ready_callback: Callable[[], None] | None = None,
    firewall: Any,
) -> dict[str, Any]:
    """Receive UDPcast bytes directly into an approved block-device writer and verify read-back."""
    executable = udp_receiver or shutil.which("udp-receiver")
    if not executable:
        raise UDPcastError("udp-receiver is required for physical multicast")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes <= 0:
        raise UDPcastError("physical multicast destination size must be a positive integer")
    with multicast_firewall_scope(firewall, config.interface, config.portbase):
        process = None
        try:
            with tempfile.TemporaryFile(mode="w+b") as log:
                process = runner_popen(
                    build_physical_stream_receiver_argv(executable, config),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=log, close_fds=True,
                )
                if process.stdout is None:
                    raise UDPcastError("udp-receiver did not expose its physical stream output pipe")
                if ready_callback is not None:
                    ready_callback()
                result = verify_received_physical_stream(
                    process.stdout, write, flush, readback,
                    expected_bytes=expected_bytes,
                    expected_sha256=expected_sha256,
                    cancel_check=cancel_check,
                )
                # Wait for the receiver to exit before probing for overflow. Reading
                # one more byte while the process is still alive can block forever
                # if a sender stalls exactly at the approved device boundary.
                try:
                    return_code = process.wait(timeout=config.max_wait_seconds + 86400)
                except subprocess.TimeoutExpired as exc:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise UDPcastError("physical multicast receiver timed out") from exc
                extra = process.stdout.read(1)
                if extra:
                    raise UDPcastError("physical multicast receiver supplied bytes beyond the approved device capacity")
                if return_code != 0:
                    log.seek(0)
                    detail = log.read(4096).decode("utf-8", errors="replace").strip()
                    raise UDPcastError("udp-receiver failed" + (f": {detail}" if detail else ""))
                return result
        except UDPcastError:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise UDPcastError(f"physical multicast receiver failed: {exc}") from exc

"""Read-only partition capture using generic Partclone or dd executables.

This module creates capture plans and streams producer stdout into the safe
artifact writer. It never restores data or opens a target block device.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from .process_control import stop_process
import shutil
import stat
import subprocess
import select
import tempfile
from typing import Callable, Mapping

from .artifact_writer import ArtifactWriteError, write_artifact
from .image_manifest import ImageArtifact
from .source_safety import SourceSafetyError, check_capture_source_safe
from .privilege import PrivilegeError, privileged_argv


class CaptureError(RuntimeError):
    """Raised when a partition capture cannot be completed safely."""


class CaptureCancelled(CaptureError):
    """The operator cancelled a running partition capture."""


_FILESYSTEM_TO_PARTCLONE = {
    "btrfs": "partclone.btrfs",
    "ext2": "partclone.extfs",
    "ext3": "partclone.extfs",
    "ext4": "partclone.ext4",
    "exfat": "partclone.exfat",
    "fat": "partclone.fat",
    "fat12": "partclone.fat",
    "fat16": "partclone.fat",
    "fat32": "partclone.fat",
    "vfat": "partclone.fat",
    "f2fs": "partclone.f2fs",
    "ntfs": "partclone.ntfs",
    "ntfs3": "partclone.ntfs",
    "xfs": "partclone.xfs",
}


def _partclone_supports_json_status(executable: str) -> bool:
    """Feature-detect Partclone's native JSON status option without assuming a distro version."""
    try:
        result = subprocess.run(
            [executable, "--help"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "--json-status" in (result.stdout or "") + (result.stderr or "")


def _read_partclone_percent(path: str) -> int | None:
    """Return Partclone's completed-block percentage from its native snapshot."""
    progress = _read_partclone_status(path)
    if progress is None or progress[1] <= 0:
        return None
    return max(0, min(100, int(progress[0] * 100 / progress[1])))


def _read_partclone_status(path: str) -> tuple[int, int] | None:
    """Read a bounded, no-follow Partclone status snapshot as logical data bytes."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o022 or info.st_size > 64 * 1024):
                return None
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        if len(raw) > 64 * 1024:
            return None
        document = json.loads(raw.decode("utf-8"))
        partclone = document.get("partclone") if isinstance(document, dict) else None
        progress = partclone.get("progress") if isinstance(partclone, dict) else None
        if (document.get("schema_version") != 1 or not isinstance(partclone, dict)
                or not isinstance(progress, dict)):
            return None
        block_size = partclone.get("block_size")
        copied = progress.get("copied_blocks")
        total = progress.get("total_block")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (block_size, copied, total)) or block_size < 1:
            return None
        return copied * block_size, total * block_size
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError):
        return None


def _partclone_stderr_progress(line: bytes, expected_size_bytes: int | None) -> tuple[int, int] | None:
    """Convert Partclone's native current/total block counters to partition bytes."""
    if not isinstance(expected_size_bytes, int) or isinstance(expected_size_bytes, bool) or expected_size_bytes <= 0:
        return None
    match = re.search(rb"Current block:\s*([0-9,]+).*?Total block:\s*([0-9,]+)", line, re.IGNORECASE)
    if not match:
        return None
    current = int(match.group(1).replace(b",", b""))
    total = int(match.group(2).replace(b",", b""))
    if total <= 0 or current < 0:
        return None
    return min(expected_size_bytes, current * expected_size_bytes // total), expected_size_bytes


class _CountingReader:
    def __init__(self, stream, progress_callback=None, expected_size_bytes=None,
                 partclone_status_path=None, stderr_stream=None, stderr_capture=None):
        self.stream = stream
        self.bytes_read = 0
        self.progress_callback = progress_callback
        self.expected_size_bytes = expected_size_bytes
        self.partclone_status_path = partclone_status_path
        self.stderr_stream = stderr_stream
        self.stderr_capture = stderr_capture
        self.last_partclone_progress = None
        self.last_legacy_progress = None
        self.stderr_pending = bytearray()
        self.stdout_eof = False

    def _emit_partclone_progress(self) -> None:
        if self.progress_callback is None:
            return
        if self.partclone_status_path is not None:
            progress = _read_partclone_status(self.partclone_status_path)
            if progress is not None and progress != self.last_partclone_progress:
                self.last_partclone_progress = progress
                self.progress_callback(*progress)

    def _consume_stderr(self, chunk: bytes) -> None:
        if self.stderr_capture is not None and chunk:
            self.stderr_capture.write(chunk)
        self.stderr_pending.extend(chunk)
        while b"\r" in self.stderr_pending or b"\n" in self.stderr_pending:
            positions = [p for p in (self.stderr_pending.find(b"\r"), self.stderr_pending.find(b"\n")) if p >= 0]
            end = min(positions)
            line = bytes(self.stderr_pending[:end])
            del self.stderr_pending[:end + 1]
            if self.partclone_status_path is None and self.progress_callback is not None:
                progress = _partclone_stderr_progress(line, self.expected_size_bytes)
                if progress is not None and progress != self.last_legacy_progress:
                    self.last_legacy_progress = progress
                    self.progress_callback(*progress)
        if len(self.stderr_pending) > 8192:
            del self.stderr_pending[:-8192]

    def _drain_stderr(self, timeout: float) -> bool:
        if self.stderr_stream is None:
            return False
        try:
            fd = self.stderr_stream.fileno()
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                return False
            chunk = os.read(fd, 8192)
        except (AttributeError, OSError, ValueError, TypeError):
            self.stderr_stream = None
            return False
        if chunk:
            self._consume_stderr(chunk)
        else:
            self.stderr_stream = None
            if self.stderr_pending and self.partclone_status_path is None and self.progress_callback is not None:
                progress = _partclone_stderr_progress(bytes(self.stderr_pending), self.expected_size_bytes)
                if progress is not None and progress != self.last_legacy_progress:
                    self.last_legacy_progress = progress
                    self.progress_callback(*progress)
            self.stderr_pending.clear()
        return True

    def read(self, size=-1):
        self._emit_partclone_progress()
        read = getattr(self.stream, "read1", self.stream.read)
        if self.stderr_stream is not None:
            try:
                stdout_fd = self.stream.fileno()
                stderr_fd = self.stderr_stream.fileno()
                while True:
                    ready, _, _ = select.select(
                        [fd for fd in (stdout_fd, stderr_fd) if fd >= 0], [], [], 0.5,
                    )
                    if stderr_fd in ready:
                        self._drain_stderr(0)
                        self._emit_partclone_progress()
                    if stdout_fd in ready:
                        chunk = read(size)
                        if not chunk:
                            self.stdout_eof = True
                        else:
                            self.bytes_read += len(chunk)
                            self._emit_partclone_progress()
                            return chunk
                    if self.stdout_eof and self.stderr_stream is None:
                        return b""
            except (AttributeError, OSError, ValueError, TypeError):
                self.stderr_stream = None
        chunk = read(size)
        self.bytes_read += len(chunk)
        if chunk and self.progress_callback is not None and self.partclone_status_path is None and self.stderr_stream is None:
            self.progress_callback(self.bytes_read, self.expected_size_bytes)
        self._emit_partclone_progress()
        return chunk


@dataclass(frozen=True)
class CapturePlan:
    """A read-only command plan for one supported block-storage source."""

    executable: str
    argv: tuple[str, ...]
    image_format: str
    filesystem: str | None


def build_capture_plan(
    source_path: str,
    filesystem: str | None,
    executables: Mapping[str, str | None] | None = None,
) -> CapturePlan:
    """Prefer filesystem-aware Partclone; explicitly fall back to raw dd."""
    if not isinstance(source_path, str) or not source_path.startswith("/dev/") or "\x00" in source_path:
        raise CaptureError("source must be an absolute /dev/ path")
    available = executables or {}
    fs = filesystem.lower() if isinstance(filesystem, str) and filesystem else None
    partclone_name = _FILESYSTEM_TO_PARTCLONE.get(fs) if fs else None
    recorded_filesystem = fs if fs in _FILESYSTEM_TO_PARTCLONE else None
    partclone_path = available.get(partclone_name) if partclone_name else None
    if partclone_path:
        return CapturePlan(
            executable=partclone_path,
            argv=(partclone_path, "-c", "-s", source_path, "-F", "-f", "1"),
            image_format="partclone",
            filesystem=recorded_filesystem,
        )
    dd_path = available.get("dd") if executables is not None else shutil.which("dd")
    if not dd_path:
        raise CaptureError(
            f"No Partclone executable for filesystem {fs or 'unknown'} and dd is unavailable"
        )
    return CapturePlan(
        executable=dd_path,
        argv=(dd_path, f"if={source_path}", "bs=4M", "status=none"),
        image_format="raw",
        filesystem=recorded_filesystem,
    )


def capture_logical_volume(
    source_path: str,
    filesystem: str | None,
    repository: str | os.PathLike[str],
    filename: str,
    inventory: Mapping[str, object],
    executables: Mapping[str, str | None] | None = None,
    *,
    compression: str = "none",
    compression_level: int | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., subprocess.Popen] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> ImageArtifact:
    """Capture one active, uniquely inventoried LVM logical volume."""
    if not isinstance(inventory, Mapping):
        raise CaptureError("logical-volume capture requires a storage inventory")
    topology = inventory.get("volume_topology")
    if not isinstance(topology, Mapping) or topology.get("status") != "available":
        raise CaptureError("LVM topology is unavailable; refusing logical-volume capture")
    def walk(items):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            yield item
            yield from walk(item.get("children") or [])
    source_devices = [
        item for item in walk(inventory.get("devices") or [])
        if item.get("path") == source_path
    ]
    if len(source_devices) != 1:
        raise CaptureError("capture source must exist exactly once in the current block inventory")
    source_device = source_devices[0]
    source_major_minor = source_device.get("major_minor")
    if not isinstance(source_major_minor, str) or not source_major_minor:
        raise CaptureError("capture source has no stable active kernel device identity")
    exact_matches = []
    identity_matches = []
    for group in topology.get("volume_groups", []):
        if not isinstance(group, Mapping):
            continue
        for logical_volume in group.get("logical_volumes", []):
            if not isinstance(logical_volume, Mapping):
                continue
            if logical_volume.get("path") == source_path:
                exact_matches.append((group, logical_volume))
            if logical_volume.get("major_minor") == source_major_minor:
                identity_matches.append((group, logical_volume))
    if len(exact_matches) > 1:
        raise CaptureError("capture source path identifies multiple logical volumes")
    if exact_matches:
        group, logical_volume = exact_matches[0]
        lv_major_minor = logical_volume.get("major_minor")
        if lv_major_minor and lv_major_minor != source_major_minor:
            raise CaptureError("LVM and block-inventory device identities disagree")
        if identity_matches and (
            len(identity_matches) != 1 or identity_matches[0][1] is not logical_volume
        ):
            raise CaptureError("kernel device identity resolves to multiple logical volumes")
    else:
        if len(identity_matches) != 1:
            raise CaptureError("capture source must resolve to exactly one LV by kernel device identity")
        group, logical_volume = identity_matches[0]
    if group.get("status") != "healthy":
        raise CaptureError("logical volume belongs to a non-healthy or incomplete volume group")
    size = logical_volume.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise CaptureError("logical-volume size is unknown; refusing capture")
    if logical_volume.get("hidden") or logical_volume.get("snapshot"):
        raise CaptureError("hidden or snapshot LVs are not valid capture sources")
    if logical_volume.get("health") not in (None, "", "-", "ok", "healthy"):
        raise CaptureError("logical volume reports an unhealthy state")
    if not logical_volume.get("major_minor"):
        raise CaptureError("logical volume is not active; refusing capture")
    source_size = source_device.get("size_bytes")
    if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size != size:
        raise CaptureError("LVM and block-inventory logical-volume sizes are unknown or disagree")
    return capture_partition(
        source_path, filesystem, repository, filename, None, executables,
        compression=compression, compression_level=compression_level,
        device_validator=device_validator, popen_factory=popen_factory,
        source_safety_check=source_safety_check, expected_size_bytes=size,
        effective_uid=effective_uid, progress_callback=progress_callback,
        artifact_role="logical-volume-image",
    )


def _is_block_device(path: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def capture_partition(
    source_path: str,
    filesystem: str | None,
    repository: str | os.PathLike[str],
    filename: str,
    partition_id: str | None,
    executables: Mapping[str, str | None] | None = None,
    *,
    compression: str = "none",
    compression_level: int | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., subprocess.Popen] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    expected_size_bytes: int | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    artifact_role: str = "partition-image",
) -> ImageArtifact:
    """Capture one block source into a repository without overwriting files.

    The source is opened by the selected read-only imaging utility. By default
    it must resolve to a block device. A private staging directory prevents a
    failed producer process from publishing a partial artifact.
    """
    if artifact_role not in {"partition-image", "logical-volume-image"}:
        raise CaptureError("capture artifact role is not supported")
    if artifact_role == "partition-image" and (not isinstance(partition_id, str) or not partition_id):
        raise CaptureError("partition capture requires a partition identifier")
    if artifact_role == "logical-volume-image" and partition_id is not None:
        raise CaptureError("logical-volume artifacts must not carry a partition identifier")
    validator = device_validator or _is_block_device
    if not validator(source_path):
        raise CaptureError(f"source is not an accessible block device: {source_path}")
    initial_device_number = os.stat(source_path).st_rdev if device_validator is None else None
    try:
        (source_safety_check or check_capture_source_safe)(source_path)
    except SourceSafetyError as exc:
        raise CaptureError(f"unsafe capture source: {exc}") from exc
    plan = build_capture_plan(source_path, filesystem, executables)
    repository_path = os.fspath(repository)
    try:
        repo_info = os.lstat(repository_path)
    except OSError as exc:
        raise CaptureError("image repository directory is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise CaptureError("image repository must be a real directory, not a symlink")

    stage_dir = tempfile.mkdtemp(prefix=".feclora-capture-", dir=repository_path)
    process = None
    artifact = None
    final_path = os.path.join(repository_path, filename)
    try:
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            try:
                (source_safety_check or check_capture_source_safe)(source_path)
            except SourceSafetyError as exc:
                raise CaptureError(f"capture source became unsafe before imaging: {exc}") from exc
            if initial_device_number is not None and os.stat(source_path).st_rdev != initial_device_number:
                raise CaptureError("block-device identity changed before imaging")
            factory = popen_factory or subprocess.Popen
            partclone_status_path = None
            process_argv = list(plan.argv)
            if (plan.image_format == "partclone"
                    and _partclone_supports_json_status(plan.executable)):
                partclone_status_path = os.path.join(stage_dir, "partclone-status.json")
                process_argv.extend((
                    f"--json-status={partclone_status_path}", "--json-fresh=1",
                ))
            try:
                command = privileged_argv(process_argv, effective_uid=effective_uid)
                process = factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE if plan.image_format == "partclone" else stderr_file,
                    close_fds=True,
                )
            except (OSError, PrivilegeError) as exc:
                raise CaptureError(f"could not start {plan.executable}: {exc}") from exc
            if process.stdout is None:
                raise CaptureError("capture process did not provide a stdout pipe")
            progress_total = expected_size_bytes
            counted = _CountingReader(
                process.stdout, progress_callback, progress_total,
                partclone_status_path=partclone_status_path,
                stderr_stream=getattr(process, "stderr", None) if plan.image_format == "partclone" else None,
                stderr_capture=stderr_file if plan.image_format == "partclone" else None,
            )
            try:
                artifact = write_artifact(
                    stage_dir,
                    filename,
                    counted,
                    role=artifact_role,
                    image_format=plan.image_format,
                    compression=compression,
                    compression_level=compression_level,
                    compression_executable=(executables or {}).get(compression),
                    partition_id=partition_id,
                    filesystem=plan.filesystem,
                )
            except ArtifactWriteError as exc:
                stop_process(process)
                raise CaptureError(f"could not store capture stream: {exc}") from exc
            finally:
                process.stdout.close()

            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                detail = stderr_file.read(8192).decode("utf-8", errors="replace").strip()
                raise CaptureError(
                    f"{plan.executable} exited with status {return_code}"
                    + (f": {detail}" if detail else "")
                )

            if plan.image_format == "raw" and expected_size_bytes is not None and counted.bytes_read != expected_size_bytes:
                raise CaptureError(
                    f"raw capture size mismatch: expected {expected_size_bytes}, read {counted.bytes_read}"
                )

            # Link is atomic and fails if the destination already exists.
            try:
                os.link(
                    os.path.join(stage_dir, filename),
                    final_path,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise CaptureError(f"artifact already exists: {filename}") from exc
            directory_fd = os.open(repository_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return artifact
        finally:
            stderr_file.close()
    except CaptureError:
        raise
    except OSError as exc:
        raise CaptureError(f"capture failed: {exc}") from exc
    finally:
        if process is not None:
            stop_process(process)
            for stream_name in ("stdout", "stderr"):
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        shutil.rmtree(stage_dir, ignore_errors=True)

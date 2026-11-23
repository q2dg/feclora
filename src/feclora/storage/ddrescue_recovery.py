"""Resumable block-device recovery with GNU ddrescue mapfiles.

Recovery workspaces are deliberately separate from publishable image sets:
a degraded or interrupted acquisition must never look like a verified image.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable

from .source_safety import check_capture_source_safe

_IMAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAP_STATUSES = frozenset({"?", "*", "/", "-", "+"})


class DdrescueRecoveryError(RuntimeError):
    """A recovery acquisition could not be safely started or resumed."""


@dataclass(frozen=True)
class MapfileSummary:
    rescued_bytes: int
    non_tried_bytes: int
    non_trimmed_bytes: int
    non_scraped_bytes: int
    bad_sector_bytes: int
    finished_bytes: int
    block_count: int

    @property
    def complete(self) -> bool:
        return self.block_count > 0 and not any((
            self.non_tried_bytes, self.non_trimmed_bytes,
            self.non_scraped_bytes, self.bad_sector_bytes,
        ))


@dataclass(frozen=True)
class RecoveryResult:
    job_id: str
    state: str
    image_path: str
    mapfile_path: str
    summary: MapfileSummary
    pass_results: tuple[int, ...]


def parse_ddrescue_mapfile(path: str | os.PathLike[str], source_size_bytes: int) -> MapfileSummary:
    """Parse GNU ddrescue's block-status records and reject malformed maps."""
    if isinstance(source_size_bytes, bool) or not isinstance(source_size_bytes, int) or source_size_bytes <= 0:
        raise DdrescueRecoveryError("source size must be a positive integer")
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise DdrescueRecoveryError("ddrescue mapfile must be a bounded regular file")
        with open(path, "r", encoding="ascii", errors="strict") as stream:
            lines = stream.readlines()
    except (OSError, UnicodeError) as exc:
        raise DdrescueRecoveryError(f"cannot read ddrescue mapfile: {exc}") from exc

    totals = {"?": 0, "*": 0, "/": 0, "-": 0, "+": 0}
    ranges: list[tuple[int, int]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        # GNU ddrescue writes a current-position/status/pass header before
        # the actual block-status table.
        if (not ranges and len(fields) == 3 and fields[1] in _MAP_STATUSES
                and fields[2].isdigit()):
            continue
        if len(fields) != 3 or fields[2] not in _MAP_STATUSES:
            raise DdrescueRecoveryError("ddrescue mapfile contains an invalid block-status record")
        try:
            offset, size = int(fields[0], 0), int(fields[1], 0)
        except ValueError as exc:
            raise DdrescueRecoveryError("ddrescue mapfile contains an invalid block range") from exc
        if offset < 0 or size <= 0 or offset + size > source_size_bytes:
            raise DdrescueRecoveryError("ddrescue mapfile block range exceeds the source geometry")
        ranges.append((offset, offset + size))
        totals[fields[2]] += size
    if not ranges:
        raise DdrescueRecoveryError("ddrescue mapfile contains no block-status records")
    ranges.sort()
    cursor = 0
    for start, end in ranges:
        if start != cursor:
            raise DdrescueRecoveryError("ddrescue mapfile has overlapping or uncovered source ranges")
        cursor = end
    if cursor != source_size_bytes:
        raise DdrescueRecoveryError("ddrescue mapfile does not cover the complete source geometry")
    return MapfileSummary(
        rescued_bytes=totals["+"], non_tried_bytes=totals["?"],
        non_trimmed_bytes=totals["*"], non_scraped_bytes=totals["/"],
        bad_sector_bytes=totals["-"], finished_bytes=totals["+"],
        block_count=len(ranges),
    )


def list_recovery_jobs(repository: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """List private local ddrescue workspaces without modifying recovery state."""
    root = Path(os.path.abspath(os.fspath(repository)))
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise DdrescueRecoveryError("recovery repository is unavailable") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise DdrescueRecoveryError("recovery repository must be a real directory")
    jobs: list[dict[str, Any]] = []
    try:
        with os.scandir(root) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
    except OSError as exc:
        raise DdrescueRecoveryError(f"cannot inspect recovery repository: {exc}") from exc
    for entry in entries:
        prefix = ".feclora-recovery-"
        if not entry.name.startswith(prefix):
            continue
        job_id = entry.name[len(prefix):]
        if not _IMAGE_ID.fullmatch(job_id):
            continue
        try:
            workspace = _safe_workspace(root, job_id, create=False)
            state = _load_state(workspace)
            if state.get("job_id") != job_id:
                raise DdrescueRecoveryError("recovery metadata identifier does not match workspace")
            source_size = state.get("source_size_bytes")
            if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0:
                raise DdrescueRecoveryError("recovery metadata has invalid source geometry")
            summary = None
            map_path = workspace / "recovery.map"
            try:
                map_info = os.lstat(map_path)
                if (not stat.S_ISREG(map_info.st_mode) or map_info.st_uid != os.geteuid()
                        or map_info.st_mode & 0o077):
                    raise DdrescueRecoveryError("recovery mapfile is unsafe")
                summary = parse_ddrescue_mapfile(map_path, source_size)
            except FileNotFoundError:
                pass
            recorded = state.get("mapfile")
            counters = {
                "rescued_bytes": summary.rescued_bytes if summary else (
                    recorded.get("rescued_bytes", 0) if isinstance(recorded, dict) else 0
                ),
                "non_tried_bytes": summary.non_tried_bytes if summary else source_size,
                "non_trimmed_bytes": summary.non_trimmed_bytes if summary else 0,
                "non_scraped_bytes": summary.non_scraped_bytes if summary else 0,
                "bad_sector_bytes": summary.bad_sector_bytes if summary else 0,
            }
            unresolved = sum(counters[key] for key in (
                "non_tried_bytes", "non_trimmed_bytes", "non_scraped_bytes", "bad_sector_bytes",
            ))
            jobs.append({
                "job_id": job_id,
                "state": state.get("state") if state.get("state") in {
                    "running", "completed", "degraded", "interrupted", "failed",
                } else "metadata_invalid",
                "source_path": state.get("source_path") if isinstance(state.get("source_path"), str) else None,
                "source_size_bytes": source_size,
                "rescued_bytes": counters["rescued_bytes"],
                "unresolved_bytes": unresolved,
                "progress_percent": round(counters["rescued_bytes"] * 100 / source_size, 2),
            })
        except DdrescueRecoveryError:
            jobs.append({
                "job_id": job_id, "state": "metadata_invalid",
                "source_path": None, "source_size_bytes": None,
                "rescued_bytes": 0, "unresolved_bytes": None, "progress_percent": None,
            })
    return jobs


def _safe_workspace(repository: str | os.PathLike[str], job_id: str, *, create: bool) -> Path:
    if not isinstance(job_id, str) or not _IMAGE_ID.fullmatch(job_id):
        raise DdrescueRecoveryError("recovery job identifier is invalid")
    repo = Path(os.path.abspath(os.fspath(repository)))
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise DdrescueRecoveryError("recovery repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise DdrescueRecoveryError("recovery repository must be a real directory")
    workspace = repo / f".feclora-recovery-{job_id}"
    if create:
        try:
            workspace.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise DdrescueRecoveryError("recovery job already exists; resume it explicitly") from exc
    try:
        info = os.lstat(workspace)
    except OSError as exc:
        raise DdrescueRecoveryError("recovery workspace does not exist") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise DdrescueRecoveryError("recovery workspace must be a private directory owned by the service user")
    return workspace


def _write_state(workspace: Path, state: dict[str, Any]) -> None:
    temporary = workspace / f".job.json.tmp.{uuid.uuid4().hex}"
    final = workspace / "job.json"
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, final)
        directory_fd = os.open(workspace, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_state(workspace: Path) -> dict[str, Any]:
    path = workspace / "job.json"
    try:
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > 64 * 1024):
            raise DdrescueRecoveryError("recovery job metadata is unsafe")
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DdrescueRecoveryError(f"cannot read recovery job metadata: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise DdrescueRecoveryError("recovery job metadata is invalid")
    return value


def _secure_mapfile(path: Path) -> None:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise DdrescueRecoveryError("ddrescue did not create a regular mapfile owned by the service user")
        os.chmod(path, 0o600, follow_symlinks=False)
    except OSError as exc:
        raise DdrescueRecoveryError(f"cannot secure ddrescue mapfile: {exc}") from exc


def _run_ddrescue(
    command: list[str],
    mapfile_path: Path,
    source_size_bytes: int,
    progress_callback: Callable[[int, int], None] | None,
) -> Any:
    """Run ddrescue while sampling its durable mapfile for live progress."""
    previous_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryFile(mode="w+b") as stderr_file:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=stderr_file, close_fds=True,
            )
            deadline = time.monotonic() + 24 * 60 * 60
            last_rescued = -1
            try:
                while True:
                    if os.path.lexists(mapfile_path):
                        try:
                            summary = parse_ddrescue_mapfile(mapfile_path, source_size_bytes)
                        except DdrescueRecoveryError:
                            summary = None
                        if summary is not None and summary.rescued_bytes != last_rescued:
                            last_rescued = summary.rescued_bytes
                            if progress_callback is not None:
                                try:
                                    progress_callback(summary.rescued_bytes, source_size_bytes)
                                except Exception:
                                    pass
                    return_code = process.poll()
                    if return_code is not None:
                        break
                    if time.monotonic() >= deadline:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise subprocess.TimeoutExpired(command, 24 * 60 * 60)
                    time.sleep(1)
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise
            stderr_file.seek(0, os.SEEK_END)
            size = stderr_file.tell()
            stderr_file.seek(max(0, size - 8192))
            detail = stderr_file.read(8192).decode("utf-8", errors="replace")
            return SimpleNamespace(returncode=return_code, stdout="", stderr=detail)
    finally:
        os.umask(previous_umask)


def recover_block_device(
    source_path: str,
    job_id: str,
    repository: str | os.PathLike[str],
    *,
    source_size_bytes: int,
    source_identity: str,
    logical_sector_size: int,
    partition_table: str,
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    identity_reader: Callable[[str], str] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    retry_passes: int = 3,
    resume: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> RecoveryResult:
    """Run ddrescue's non-scraping pass then bounded direct retry passes.

    The mapfile and partial data remain in a private job directory after every
    outcome. Only a fully rescued map is marked completed; this module never
    publishes a partial acquisition as a normal image manifest.
    """
    if not isinstance(source_path, str) or not source_path.startswith("/dev/") or "\x00" in source_path:
        raise DdrescueRecoveryError("recovery source must be an absolute /dev/ path")
    if (not isinstance(source_identity, str) or len(source_identity) > 256
            or not re.fullmatch(r"(?:major_minor:[0-9]+:[0-9]+|(?:wwn|serial):[A-Za-z0-9_.:+/-]{1,240})", source_identity)):
        raise DdrescueRecoveryError("source identity must be a stable WWN/serial or major:minor fallback")
    if isinstance(retry_passes, bool) or not isinstance(retry_passes, int) or not 0 <= retry_passes <= 10:
        raise DdrescueRecoveryError("retry_passes must be an integer between 0 and 10")
    if isinstance(source_size_bytes, bool) or not isinstance(source_size_bytes, int) or source_size_bytes <= 0:
        raise DdrescueRecoveryError("source size must be a positive integer")
    if (isinstance(logical_sector_size, bool) or not isinstance(logical_sector_size, int)
            or logical_sector_size not in {512, 4096}):
        raise DdrescueRecoveryError("logical sector size must be 512 or 4096")
    if not isinstance(partition_table, str) or partition_table not in {"gpt", "mbr", "none", "unknown"}:
        raise DdrescueRecoveryError("partition table type is invalid")
    available = executables or {}
    ddrescue = available.get("ddrescue") or (None if executables is not None else shutil.which("ddrescue"))
    if not ddrescue:
        raise DdrescueRecoveryError("GNU ddrescue is required for recoverable block acquisition")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    def read_device_identity(path: str) -> str:
        lsblk = shutil.which("lsblk")
        if lsblk:
            try:
                result = subprocess.run(
                    [lsblk, "--json", "--nodeps", "--output", "WWN,SERIAL,MAJ:MIN", path],
                    check=True, capture_output=True, text=True, timeout=10,
                )
                devices = json.loads(result.stdout).get("blockdevices", [])
                if len(devices) == 1 and isinstance(devices[0], dict):
                    device = devices[0]
                    wwn, serial, major_minor = (
                        device.get("wwn"), device.get("serial"), device.get("maj:min")
                    )
                    if isinstance(wwn, str) and wwn not in {"", "-"}:
                        return f"wwn:{wwn}"
                    if isinstance(serial, str) and serial not in {"", "-"}:
                        return f"serial:{serial}"
                    if isinstance(major_minor, str):
                        return f"major_minor:{major_minor}"
            except (OSError, subprocess.SubprocessError):
                pass
        device = os.stat(path)
        return f"major_minor:{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}"

    reader = identity_reader or read_device_identity
    safety_check = source_safety_check or check_capture_source_safe

    def check_source() -> None:
        try:
            if not validator(source_path):
                raise DdrescueRecoveryError("recovery source is not an accessible block device")
            if reader(source_path) != source_identity:
                raise DdrescueRecoveryError("source kernel device identity changed")
            safety_check(source_path)
        except DdrescueRecoveryError:
            raise
        except Exception as exc:
            raise DdrescueRecoveryError(f"recovery source safety check failed: {exc}") from exc

    check_source()
    workspace = _safe_workspace(repository, job_id, create=not resume)
    image_path, mapfile_path = workspace / "recovered.img", workspace / "recovery.map"
    expected = {
        "schema_version": 1, "job_id": job_id, "source_path": source_path,
        "source_identity": source_identity, "source_size_bytes": source_size_bytes,
        "logical_sector_size": logical_sector_size, "partition_table": partition_table,
        "state": "running", "retry_passes": retry_passes,
    }
    if resume:
        state = _load_state(workspace)
        identity_is_stable = source_identity.startswith(("wwn:", "serial:"))
        resume_keys = ("job_id", "source_identity", "source_size_bytes", "logical_sector_size", "partition_table", "retry_passes")
        if not identity_is_stable:
            resume_keys += ("source_path",)
        for key in resume_keys:
            if state.get(key) != expected[key]:
                raise DdrescueRecoveryError(f"resume source {key} does not match the original recovery job")
        for path in (image_path, mapfile_path):
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise DdrescueRecoveryError("recovery image or mapfile is missing; cannot resume") from exc
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise DdrescueRecoveryError("recovery image and mapfile must be private regular files")
            if path == image_path and info.st_size != source_size_bytes:
                raise DdrescueRecoveryError("recovery image size does not match the original source geometry")
        summary = parse_ddrescue_mapfile(mapfile_path, source_size_bytes)
    else:
        state = expected
        try:
            fd = os.open(image_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as output:
                output.truncate(source_size_bytes)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise DdrescueRecoveryError(f"cannot create recovery image: {exc}") from exc
        _write_state(workspace, state)
        summary = None

    results: list[int] = []
    commands = [
        [ddrescue, "--force", "--no-scrape", source_path, str(image_path), str(mapfile_path)],
    ]
    if retry_passes:
        commands.append([
            ddrescue, "--force", "--direct", f"--retry-passes={retry_passes}",
            source_path, str(image_path), str(mapfile_path),
        ])
    try:
        for command in commands:
            check_source()
            if runner is not None:
                completed = runner(
                    command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    check=False, timeout=24 * 60 * 60,
                )
            else:
                completed = _run_ddrescue(
                    command, mapfile_path, source_size_bytes, progress_callback,
                )
            code = completed.returncode
            results.append(code)
            if code != 0:
                if os.path.lexists(mapfile_path):
                    _secure_mapfile(mapfile_path)
                state["state"] = "interrupted" if code in {5, 6, 7} else "failed"
                state["last_exit_code"] = code
                _write_state(workspace, state)
                raise DdrescueRecoveryError(
                    f"ddrescue exited with status {code}; recovery data and mapfile were retained"
                )
            _secure_mapfile(mapfile_path)
            summary = parse_ddrescue_mapfile(mapfile_path, source_size_bytes)
            state["mapfile"] = {
                "rescued_bytes": summary.rescued_bytes,
                "non_tried_bytes": summary.non_tried_bytes,
                "non_trimmed_bytes": summary.non_trimmed_bytes,
                "non_scraped_bytes": summary.non_scraped_bytes,
                "bad_sector_bytes": summary.bad_sector_bytes,
            }
            _write_state(workspace, state)
            if progress_callback is not None:
                try:
                    progress_callback(summary.rescued_bytes, source_size_bytes)
                except Exception:
                    pass
            if summary.complete:
                break
        state["state"] = "completed" if summary and summary.complete else "degraded"
        _write_state(workspace, state)
    except subprocess.TimeoutExpired as exc:
        if os.path.lexists(mapfile_path):
            try:
                _secure_mapfile(mapfile_path)
            except DdrescueRecoveryError:
                pass
        state["state"] = "interrupted"
        _write_state(workspace, state)
        raise DdrescueRecoveryError("ddrescue timed out; recovery data and mapfile were retained") from exc
    except DdrescueRecoveryError as exc:
        if state.get("state") == "running":
            state["state"] = "interrupted" if "identity changed" in str(exc) else "failed"
            _write_state(workspace, state)
        raise
    except OSError as exc:
        state["state"] = "failed"
        _write_state(workspace, state)
        raise DdrescueRecoveryError(f"cannot execute ddrescue: {exc}; recovery data and mapfile were retained") from exc
    except BaseException:
        if state.get("state") in {"running", "degraded"}:
            if os.path.lexists(mapfile_path):
                try:
                    _secure_mapfile(mapfile_path)
                except DdrescueRecoveryError:
                    pass
            state["state"] = "interrupted"
            _write_state(workspace, state)
        raise

    if summary is None:
        raise DdrescueRecoveryError("ddrescue did not produce a valid mapfile")
    return RecoveryResult(
        job_id=job_id, state=state["state"], image_path=str(image_path),
        mapfile_path=str(mapfile_path), summary=summary, pass_results=tuple(results),
    )

"""Fetch a shared HTTP PXE answer and run its supported unattended restore.

The JSON is treated as operator-authorized because this deployment explicitly
trusts its configured PXE HTTP server. The client still validates the schema,
uses read-only NFS for repository access, resolves stable disk identity and
delegates destructive writes to the existing verified restore engine.
"""
from __future__ import annotations

import os
import stat
import subprocess
import shutil
from urllib.parse import unquote, urlsplit
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from feclora.network.pxe_answer import MAX_ANSWER_BYTES, parse_pxe_answer
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.restore_profile import RestoreTargetSelector
from feclora.storage.inventory import collect_inventory
from feclora.storage.disk_restore import restore_disk
from feclora.storage.operation_log import operation_record, record_progress
from feclora.network.pxe_boot_request import (
    PXEBootRequestError,
    parse_pxe_boot_request,
)


class PXEAnswerClientError(RuntimeError):
    """The Live client could not safely retrieve its PXE answer."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _download_answer(url: str, *, timeout: float = 15.0) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Feclora-PXE/1"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise PXEAnswerClientError(f"PXE answer server returned HTTP {response.status}")
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "application/octet-stream"}:
                raise PXEAnswerClientError("PXE answer server returned an unexpected content type")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > MAX_ANSWER_BYTES:
                        raise PXEAnswerClientError("PXE answer exceeds the 64 KiB size limit")
                except ValueError as exc:
                    raise PXEAnswerClientError("PXE answer server returned an invalid Content-Length") from exc
            chunks = bytearray()
            while len(chunks) <= MAX_ANSWER_BYTES:
                chunk = response.read(min(8192, MAX_ANSWER_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if not chunks or len(chunks) > MAX_ANSWER_BYTES:
                raise PXEAnswerClientError("PXE answer must be non-empty and at most 64 KiB")
            return bytes(chunks)
    except PXEAnswerClientError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise PXEAnswerClientError(f"cannot download PXE answer over HTTP: {exc}") from exc


def _publish_runtime_answer(raw: bytes, destination: str | os.PathLike[str]) -> Path:
    target = Path(destination)
    parent = target.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_info = os.lstat(parent)
        if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
                or parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o077):
            raise PXEAnswerClientError("PXE runtime answer directory must be root-owned and mode 0700")
        if os.path.lexists(target):
            info = os.lstat(target)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
                raise PXEAnswerClientError("existing PXE runtime answer path is unsafe")
        fd, temporary = tempfile.mkstemp(prefix=".answer-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    except PXEAnswerClientError:
        raise
    except OSError as exc:
        raise PXEAnswerClientError(f"cannot safely store PXE answer in Live runtime: {exc}") from exc
    return target


def fetch_live_pxe_answer(
    command_line: str | None = None,
    *,
    destination: str | os.PathLike[str] = "/run/feclora/pxe/answer.json",
    downloader: Any = _download_answer,
) -> dict[str, Any] | None:
    """Fetch/validate the unattended answer; interactive PXE boots are a no-op."""
    if command_line is None:
        try:
            command_line = Path("/proc/cmdline").read_text(encoding="ascii")
        except OSError as exc:
            raise PXEAnswerClientError(f"cannot read Live kernel command line: {exc}") from exc
    try:
        request = parse_pxe_boot_request(command_line)
    except PXEBootRequestError as exc:
        raise PXEAnswerClientError(f"invalid PXE boot handoff: {exc}") from exc
    if request.mode == "interactive":
        return None
    if not request.answer_url:
        raise PXEAnswerClientError("unattended PXE boot has no answer URL")
    raw = downloader(request.answer_url)
    answer = parse_pxe_answer(raw)
    answer["_pxe_job_id"] = request.job_id
    _publish_runtime_answer(raw, destination)
    return answer



def _flatten_devices(devices: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    pending = list(devices) if isinstance(devices, list) else []
    while pending:
        device = pending.pop()
        if not isinstance(device, dict):
            continue
        flattened.append(device)
        children = device.get("children")
        if isinstance(children, list):
            pending.extend(children)
    return flattened


def _resolve_target(answer: dict[str, Any]) -> dict[str, Any]:
    selector = RestoreTargetSelector(**answer["target"])
    try:
        inventory = collect_inventory()
    except Exception as exc:
        raise PXEAnswerClientError(f"cannot inventory disks before unattended restore: {exc}") from exc
    matches = [
        item for item in _flatten_devices(inventory.get("devices"))
        if item.get("type") == "disk" and selector.matches(item)
    ]
    if len(matches) != 1:
        raise PXEAnswerClientError(
            f"PXE target selector matched {len(matches)} whole disks; exactly one is required"
        )
    target = matches[0]
    path = target.get("path")
    if not isinstance(path, str) or not path.startswith("/dev/"):
        raise PXEAnswerClientError("resolved PXE target has no valid block-device path")
    return target


def _mount_nfs_repository(repository_url: str, mountpoint: Path) -> None:
    parsed = urlsplit(repository_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise PXEAnswerClientError("NFS repository URL has an invalid port") from exc
    host = parsed.hostname or ""
    path = unquote(parsed.path)
    if (parsed.scheme.lower() != "nfs" or not host or port is not None
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or not path.startswith("/")
            or any(part in {".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 for char in path)
            or ":" in host or not all(char.isalnum() or char in ".-" for char in host)):
        raise PXEAnswerClientError("NFS repository URL must be nfs://host/absolute/export/path without credentials or options")
    mount_cmd, umount_cmd, findmnt_cmd = (
        shutil.which("mount"), shutil.which("umount"), shutil.which("findmnt")
    )
    if not mount_cmd or not umount_cmd or not findmnt_cmd:
        raise PXEAnswerClientError("mount, umount and findmnt are required for NFS PXE repositories")
    mountpoint.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(mountpoint)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PXEAnswerClientError("PXE repository mountpoint is not a real directory")
    if any(mountpoint.iterdir()):
        raise PXEAnswerClientError("PXE repository mountpoint is not empty")
    source = f"{host}:{path}"
    try:
        subprocess.run(
            [mount_cmd, "-t", "nfs", "-o",
             "ro,nosuid,nodev,noexec,proto=tcp,timeo=30,retrans=2", source, str(mountpoint)],
            check=True, capture_output=True, text=True, timeout=45,
        )
        check = subprocess.run(
            [findmnt_cmd, "--noheadings", "--mountpoint", str(mountpoint),
             "--output", "FSTYPE,OPTIONS,SOURCE"],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            subprocess.run([umount_cmd, str(mountpoint)], check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
        raise PXEAnswerClientError(f"cannot mount PXE NFS repository read-only: {exc}") from exc
    fields = check.stdout.split()
    if len(fields) < 3 or fields[0].lower() not in {"nfs", "nfs4"} or "ro" not in fields[1].split(","):
        try:
            subprocess.run([umount_cmd, str(mountpoint)], check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
        raise PXEAnswerClientError("PXE repository mount is not verified as a read-only NFS mount")


def _revalidate_target(selector: RestoreTargetSelector, expected_path: str) -> None:
    try:
        inventory = collect_inventory()
    except Exception as exc:
        raise PXEAnswerClientError(f"cannot recheck PXE target immediately before write: {exc}") from exc
    matches = [
        item for item in _flatten_devices(inventory.get("devices"))
        if item.get("type") == "disk" and selector.matches(item)
    ]
    if len(matches) != 1 or matches[0].get("path") != expected_path:
        raise PXEAnswerClientError("PXE target identity or device path changed before the first write")



def _consume_answer_once(job_id: str, directory: str | os.PathLike[str]) -> None:
    """Consume a PXE job UUID once in this Live session, immediately pre-write."""
    import uuid

    try:
        canonical = str(uuid.UUID(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PXEAnswerClientError("PXE job ID is invalid for one-time consumption") from exc
    if canonical != job_id:
        raise PXEAnswerClientError("PXE job ID is not canonical")
    root = Path(directory)
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(root)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise PXEAnswerClientError("PXE one-time ledger directory must be root-owned and mode 0700")
        fd = os.open(
            root / canonical,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write("consumed\n")
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise PXEAnswerClientError("PXE answer job has already been consumed in this Live session") from exc
    except PXEAnswerClientError:
        raise
    except OSError as exc:
        raise PXEAnswerClientError(f"cannot consume PXE answer authorization once: {exc}") from exc


def _wait_for_age_passphrase(
    secret_path: str | os.PathLike[str] = "/run/feclora/pxe/age-passphrase",
    *,
    timeout: float = 300.0,
) -> str:
    """Wait for a one-shot passphrase submitted through the local Cockpit API."""
    import time

    path = Path(secret_path)
    marker = path.with_name(path.name + "-needed")
    try:
        marker_fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(marker_fd)
    except FileExistsError as exc:
        raise PXEAnswerClientError("another PXE age passphrase request is already pending") from exc
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                time.sleep(0.25)
                continue
            if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 1024):
                raise PXEAnswerClientError("submitted age passphrase file is unsafe")
            try:
                value = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise PXEAnswerClientError("cannot read submitted age passphrase") from exc
            try:
                path.unlink()
            except OSError as exc:
                raise PXEAnswerClientError("cannot remove one-shot age passphrase after reading") from exc
            if (not value or len(value.encode("utf-8")) > 1024
                    or any(char in value for char in "\r\n\x00")):
                raise PXEAnswerClientError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
            return value
        raise PXEAnswerClientError("timed out waiting for the age passphrase in Live Cockpit")
    finally:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


def execute_live_pxe_restore(
    answer: dict[str, Any],
    *,
    mountpoint: str | os.PathLike[str] = "/run/feclora/pxe/repository",
    operation_log: str | os.PathLike[str] = "/var/lib/feclora/pxe/operations.jsonl",
    consumption_dir: str | os.PathLike[str] = "/var/lib/feclora/pxe/consumed",
    passphrase_provider: Any = _wait_for_age_passphrase,
) -> str:
    """Execute the requested NFS-backed whole-disk restore; other providers fail closed."""
    repository_url = answer.get("repository_url")
    if not isinstance(repository_url, str) or not repository_url.lower().startswith("nfs://"):
        raise PXEAnswerClientError(
            "PXE restore currently supports NFS repositories only; this URL scheme has no Live adapter yet"
        )
    if answer.get("credential_ref") is not None:
        raise PXEAnswerClientError(
            "credential_ref is not yet connected to the PXE NFS provider; refusing to ignore it"
        )
    job_id = answer.get("_pxe_job_id")
    if not isinstance(job_id, str):
        raise PXEAnswerClientError("PXE job ID is required for one-time restore authorization")
    selector = RestoreTargetSelector(**answer["target"])
    target = _resolve_target(answer)
    target_path = target["path"]
    repository = Path(mountpoint)
    _mount_nfs_repository(repository_url, repository)
    try:
        manifest_path = repository / f"{answer['image_id']}.manifest.json"
        try:
            info = os.lstat(manifest_path)
            if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_size > 1024 * 1024):
                raise PXEAnswerClientError("PXE image manifest must be a regular file no larger than 1 MiB")
            manifest_raw = manifest_path.read_bytes()
            if len(manifest_raw) > 1024 * 1024:
                raise PXEAnswerClientError("PXE image manifest exceeds the 1 MiB size limit")
            manifest = ImageManifest.from_json(manifest_raw.decode("utf-8"))
        except (OSError, UnicodeError, ManifestValidationError) as exc:
            raise PXEAnswerClientError(f"cannot load PXE image manifest: {exc}") from exc
        if manifest.image_id != answer["image_id"] or manifest.image_type != "disk":
            raise PXEAnswerClientError("PXE answer requires a matching whole-disk image manifest")
        encrypted = [item for item in manifest.artifacts if item.encryption == "age"]
        if any(item.encryption not in {"none", "age"} for item in manifest.artifacts):
            raise PXEAnswerClientError("PXE image set uses an unsupported encryption format")
        age_passphrase = passphrase_provider() if encrypted else None
        with operation_record(
            "restore_disk", target_path, image_id=answer["image_id"], log_path=operation_log,
        ):
            def before_write() -> None:
                _revalidate_target(selector, target_path)
                _consume_answer_once(job_id, consumption_dir)

            try:
                restore_disk(
                    str(manifest_path), str(repository), target_path,
                    confirmation=f"ERASE {target_path}",
                    ignore_signature=True,
                    age_passphrase=age_passphrase,
                    progress_callback=record_progress,
                    pre_write_callback=before_write,
                )
            except Exception as exc:
                raise PXEAnswerClientError(f"PXE whole-disk restore failed: {exc}") from exc
            finally:
                age_passphrase = None
        return target_path
    finally:
        umount_cmd = shutil.which("umount") or "umount"
        try:
            subprocess.run(
                [umount_cmd, str(repository)],
                check=True, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PXEAnswerClientError(f"restore ended but NFS repository unmount failed: {exc}") from exc


def main() -> int:
    try:
        answer = fetch_live_pxe_answer()
    except (PXEAnswerClientError, ValueError, OSError) as exc:
        print(f"feclora-pxe-answer: {exc}", file=sys.stderr)
        return 1
    if answer is None:
        return 0
    try:
        target = execute_live_pxe_restore(answer)
    except (PXEAnswerClientError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"feclora-pxe-answer: {exc}", file=sys.stderr)
        return 1
    print(f"PXE restore completed and read-back verified: {answer['image_id']} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

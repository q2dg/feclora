"""Fetch a shared HTTP answer and restore through Feclora repository managers.

The JSON is treated as operator-authorized because this deployment explicitly
trusts its configured PXE HTTP server. Repository credentials remain in the
Live client's normal protected configuration.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from feclora.network.pxe_answer import MAX_ANSWER_BYTES, PXEAnswerError, parse_pxe_answer
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.restore_profile import RestoreTargetSelector
from feclora.storage.inventory import collect_inventory
from feclora.storage.disk_restore import restore_disk
from feclora.storage.operation_log import operation_record, record_progress
from feclora.network.pxe_boot_request import (
    PXEBootRequestError,
    parse_pxe_boot_request,
    parse_dhcp_answer_url,
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


def _discover_dhcp_answer_url() -> str | None:
    """Read Feclora's private DHCP option 224 from the active NetworkManager lease."""
    try:
        result = subprocess.run(
            ["nmcli", "-g", "DHCP4.OPTION", "device", "show"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    urls = set()
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        candidate = value.strip()
        if separator and key.strip().lower() in {"224", "option_224"} and candidate.startswith(("http://", "https://")):
            urls.add(candidate)
    if not urls:
        return None
    if len(urls) != 1:
        raise PXEAnswerClientError("NetworkManager reports conflicting Feclora DHCP answer URLs")
    return next(iter(urls))


def fetch_live_pxe_answer(
    command_line: str | None = None,
    *,
    destination: str | os.PathLike[str] = "/run/feclora/pxe/answer.json",
    downloader: Any = _download_answer,
    dhcp_url_provider: Any = _discover_dhcp_answer_url,
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
        # An explicit interactive PXE selection must never inherit a currently
        # published answer. Only generic ISO boots (no PXE mode argument) use
        # DHCP option 224 for unattended discovery.
        if "feclora.pxe_mode=interactive" in command_line.split():
            return None
        dhcp_url = dhcp_url_provider()
        if dhcp_url is None:
            return None
        try:
            request = parse_dhcp_answer_url(dhcp_url)
        except PXEBootRequestError as exc:
            raise PXEAnswerClientError(f"invalid Feclora DHCP answer URL: {exc}") from exc
    if not request.answer_url:
        raise PXEAnswerClientError("unattended PXE boot has no answer URL")
    raw = downloader(request.answer_url)
    try:
        answer = parse_pxe_answer(raw)
    except PXEAnswerError as exc:
        raise PXEAnswerClientError(f"invalid PXE answer document: {exc}") from exc
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
                secret_fd = os.open(
                    path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                )
            except FileNotFoundError:
                time.sleep(0.25)
                continue
            except OSError as exc:
                raise PXEAnswerClientError("cannot safely open submitted age passphrase") from exc
            try:
                info = os.fstat(secret_fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077 or info.st_size > 1024):
                    raise PXEAnswerClientError("submitted age passphrase file is unsafe")
                chunks = bytearray()
                while len(chunks) <= 1024:
                    chunk = os.read(secret_fd, 1025 - len(chunks))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                if len(chunks) > 1024:
                    raise PXEAnswerClientError("submitted age passphrase file exceeds 1024 bytes")
                try:
                    value = bytes(chunks).decode("utf-8")
                except UnicodeError as exc:
                    raise PXEAnswerClientError("submitted age passphrase is not valid UTF-8") from exc
            finally:
                os.close(secret_fd)
            try:
                path.unlink()
            except OSError as exc:
                raise PXEAnswerClientError("cannot remove one-shot age passphrase after reading") from exc
            if (not value or any(char in value for char in "\r\n\x00")):
                raise PXEAnswerClientError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
            return value
        raise PXEAnswerClientError("timed out waiting for the age passphrase in Live Cockpit")
    finally:
        for stale in (path, marker):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass


def _clear_stale_age_passphrase_files(directory: str | os.PathLike[str] = "/run/feclora/pxe") -> None:
    """Remove one-shot secret files left by an interrupted Cockpit/API process."""
    root = Path(directory)
    for candidate in [root / "age-passphrase", root / "age-passphrase-needed", *root.glob(".age-passphrase-*")]:
        try:
            info = os.lstat(candidate)
        except FileNotFoundError:
            continue
        if (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == os.geteuid() and not info.st_mode & 0o077):
            candidate.unlink()


@contextmanager
def _managed_repository(repository_id: str, image_id: str):
    """Resolve an existing Feclora repository using its normal manager and credentials."""
    from feclora.storage.s3_repository_manager import (
        REGISTRY as S3_REGISTRY, S3RepositoryManager,
    )

    if os.path.lexists(S3_REGISTRY):
        s3_manager = S3RepositoryManager(registry=S3_REGISTRY)
        s3_ids = {item["id"] for item in s3_manager.list()}
    else:
        s3_manager = None
        s3_ids = set()
    if repository_id in s3_ids:
        usage_fd = s3_manager.acquire_usage_lock(repository_id)
        try:
            object_repository = s3_manager.repository(repository_id)
            with tempfile.TemporaryDirectory(prefix="feclora-pxe-s3-") as temporary:
                root = Path(temporary)
                os.chmod(root, 0o700)
                object_repository.download_image_set(image_id, root)
                # The manager's object repository contains decrypted S3
                # credentials in its client configuration. Do not retain that
                # object while the disk restore runs from the local download.
                del object_repository
                yield root
        finally:
            os.close(usage_fd)
        return

    from feclora.storage.repository_manager import (
        REGISTRY as REMOTE_REGISTRY, RemoteRepositoryManager,
    )

    if not os.path.lexists(REMOTE_REGISTRY):
        raise PXEAnswerClientError("selected repository ID is not configured in the Live client's Feclora repository managers")
    manager = RemoteRepositoryManager(registry=REMOTE_REGISTRY)
    definitions = {item["id"]: item for item in manager.list()}
    if repository_id not in definitions:
        raise PXEAnswerClientError("selected repository ID is not configured in the Live client's Feclora repository managers")
    mounted_by_us = False
    lease_fd = None
    try:
        if not definitions[repository_id]["mounted"]:
            manager.mount(repository_id)
            mounted_by_us = True
        lease_fd = manager.acquire_usage_lock(repository_id)
        repository_path = Path(manager.resolve(repository_id, write=False))
        yield repository_path
    finally:
        if lease_fd is not None:
            os.close(lease_fd)
        if mounted_by_us:
            manager.unmount(repository_id)


def execute_live_pxe_restore(
    answer: dict[str, Any],
    *,
    operation_log: str | os.PathLike[str] = "/var/lib/feclora/pxe/operations.jsonl",
    passphrase_provider: Any = _wait_for_age_passphrase,
) -> str:
    """Restore from a repository selected through Feclora's normal managers."""
    repository_id = answer.get("repository_id")
    if not isinstance(repository_id, str):
        raise PXEAnswerClientError("PXE answer has no managed repository ID")
    selector = RestoreTargetSelector(**answer["target"])
    target = _resolve_target(answer)
    target_path = target["path"]

    with _managed_repository(repository_id, answer["image_id"]) as repository:
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
            raise PXEAnswerClientError(f"cannot load managed repository image manifest: {exc}") from exc
        if manifest.image_id != answer["image_id"] or manifest.image_type != "disk":
            raise PXEAnswerClientError("PXE answer requires a matching whole-disk image manifest")
        if any(item.encryption not in {"none", "age"} for item in manifest.artifacts):
            raise PXEAnswerClientError("image set uses an unsupported encryption format")
        age_passphrase = passphrase_provider() if any(
            item.encryption == "age" for item in manifest.artifacts
        ) else None
        try:
            with operation_record(
                "restore_disk", target_path, image_id=answer["image_id"], log_path=operation_log,
            ):
                def before_write() -> None:
                    _revalidate_target(selector, target_path)

                try:
                    restore_disk(
                        str(manifest_path), str(repository), target_path,
                        confirmation=f"ERASE {target_path}",
                        age_passphrase=age_passphrase,
                        progress_callback=record_progress,
                        pre_write_callback=before_write,
                    )
                except Exception as exc:
                    raise PXEAnswerClientError(f"PXE whole-disk restore failed: {exc}") from exc
        finally:
            age_passphrase = None
    return target_path


def main() -> int:
    try:
        _clear_stale_age_passphrase_files()
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

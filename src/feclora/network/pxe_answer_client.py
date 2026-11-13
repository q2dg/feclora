"""Fetch a shared HTTP PXE answer and run its supported unattended restore.

The JSON is treated as operator-authorized because this deployment explicitly
trusts its configured PXE HTTP server. The client still validates the schema,
uses read-only NFS or credential-free HTTPS for repository access, resolves
stable disk identity and
delegates destructive writes to the existing verified restore engine.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import shutil
from urllib.parse import unquote, urljoin, urlsplit
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



def _download_https_object(
    url: str,
    *,
    destination: Path | None = None,
    max_bytes: int,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    timeout: float = 30.0,
) -> bytes | None:
    """Fetch one immutable HTTPS object without redirects and with strict bounds."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, headers={"Accept": "application/octet-stream, application/json",
                      "User-Agent": "Feclora-PXE/1"}, method="GET",
    )
    digest = hashlib.sha256()
    total = 0
    chunks = bytearray() if destination is None else None
    output = None
    try:
        if destination is not None:
            output = destination.open("xb")
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise PXEAnswerClientError(f"HTTPS repository returned HTTP {response.status}")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except (TypeError, ValueError) as exc:
                    raise PXEAnswerClientError("HTTPS repository returned an invalid Content-Length") from exc
                if declared_size < 0 or declared_size > max_bytes:
                    raise PXEAnswerClientError("HTTPS repository object exceeds its size limit")
                if expected_size is not None and declared_size != expected_size:
                    raise PXEAnswerClientError("HTTPS repository object size differs from its manifest")
            while True:
                chunk = response.read(min(1024 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise PXEAnswerClientError("HTTPS repository object exceeds its size limit")
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
                else:
                    chunks.extend(chunk)
        if expected_size is not None and total != expected_size:
            raise PXEAnswerClientError("HTTPS repository object size differs from its manifest")
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise PXEAnswerClientError("HTTPS repository object SHA-256 differs from its manifest")
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
            output.close()
            output = None
            return None
        return bytes(chunks)
    except PXEAnswerClientError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            subprocess.SubprocessError) as exc:
        raise PXEAnswerClientError(f"cannot download HTTPS repository object: {exc}") from exc
    finally:
        if output is not None:
            output.close()
            if destination is not None:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass



def _check_https_staging_capacity(directory: Path, required_bytes: int) -> None:
    """Require local space for the complete HTTPS image set plus a safety reserve."""
    if isinstance(required_bytes, bool) or not isinstance(required_bytes, int) or required_bytes <= 0:
        raise PXEAnswerClientError("HTTPS image set has an invalid total artifact size")
    reserve_bytes = max(256 * 1024 * 1024, min(required_bytes // 20, 2 * 1024 * 1024 * 1024))
    try:
        free_bytes = shutil.disk_usage(directory).free
    except OSError as exc:
        raise PXEAnswerClientError(f"cannot inspect local HTTPS staging capacity: {exc}") from exc
    if free_bytes < required_bytes + reserve_bytes:
        raise PXEAnswerClientError(
            "insufficient local staging space for HTTPS image set: "
            f"{free_bytes} bytes free, {required_bytes} bytes required plus "
            f"{reserve_bytes} bytes safety reserve"
        )

def _stage_https_repository(repository_url: str, image_id: str, directory: Path) -> Path:
    """Stage a public or pre-authorized HTTPS image set using S3-compatible object keys.

    The URL is a base prefix. The manifest is image_id.manifest.json and
    payloads are image_id/filename, matching Feclora's S3 key layout.
    TLS certificate validation uses Python's default verified HTTPS context.
    """
    parsed = urlsplit(repository_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise PXEAnswerClientError("HTTPS repository URL has an invalid port") from exc
    decoded_path = unquote(parsed.path)
    if (parsed.scheme.lower() != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or any(ord(char) < 32 for char in decoded_path)):
        raise PXEAnswerClientError(
            "HTTPS repository URL must be a credential-free HTTPS base prefix without query or fragment"
        )
    if port is not None and not 1 <= port <= 65535:
        raise PXEAnswerClientError("HTTPS repository URL port is invalid")
    base = repository_url.rstrip("/") + "/"
    manifest_url = urljoin(base, f"{image_id}.manifest.json")
    manifest_bytes = _download_https_object(manifest_url, max_bytes=1024 * 1024)
    try:
        manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
    except (UnicodeError, ManifestValidationError) as exc:
        raise PXEAnswerClientError(f"HTTPS repository manifest is invalid: {exc}") from exc
    if manifest.image_id != image_id or manifest.image_type != "disk":
        raise PXEAnswerClientError("PXE answer requires a matching whole-disk image manifest")
    _check_https_staging_capacity(
        directory, sum(artifact.size_bytes for artifact in manifest.artifacts),
    )
    for artifact in manifest.artifacts:
        artifact_path = directory / artifact.filename
        artifact_url = urljoin(base, f"{image_id}/{artifact.filename}")
        _download_https_object(
            artifact_url, destination=artifact_path,
            max_bytes=artifact.size_bytes, expected_size=artifact.size_bytes,
            expected_sha256=artifact.sha256,
        )
    manifest_path = directory / f"{image_id}.manifest.json"
    with manifest_path.open("xb") as output:
        output.write(manifest_bytes)
        output.flush()
        os.fsync(output.fileno())
    return manifest_path

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


def execute_live_pxe_restore(
    answer: dict[str, Any],
    *,
    mountpoint: str | os.PathLike[str] = "/run/feclora/pxe/repository",
    operation_log: str | os.PathLike[str] = "/var/lib/feclora/pxe/operations.jsonl",
    passphrase_provider: Any = _wait_for_age_passphrase,
) -> str:
    """Execute the requested NFS-backed whole-disk restore; other providers fail closed."""
    repository_url = answer.get("repository_url")
    if not isinstance(repository_url, str):
        raise PXEAnswerClientError("PXE answer has no repository URL")
    if answer.get("credential_ref") is not None:
        raise PXEAnswerClientError(
            "credential_ref is not available in the identity-free Live PXE client; refusing to ignore it"
        )
    scheme = urlsplit(repository_url).scheme.lower()
    if scheme not in {"nfs", "https"}:
        raise PXEAnswerClientError(
            "PXE restore supports NFS and credential-free HTTPS repositories; other schemes fail closed"
        )
    selector = RestoreTargetSelector(**answer["target"])
    target = _resolve_target(answer)
    target_path = target["path"]
    mounted_nfs = scheme == "nfs"
    temporary_repository = None
    repository = Path(mountpoint)
    if mounted_nfs:
        _mount_nfs_repository(repository_url, repository)
    elif scheme == "https":
        temporary_repository = tempfile.TemporaryDirectory(prefix="feclora-pxe-repository-")
        repository = Path(temporary_repository.name)
        try:
            _stage_https_repository(repository_url, answer["image_id"], repository)
        except Exception:
            temporary_repository.cleanup()
            raise
    else:
        raise PXEAnswerClientError(
            "PXE restore supports NFS and credential-free HTTPS repositories; other schemes fail closed"
        )
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
        if mounted_nfs:
            umount_cmd = shutil.which("umount") or "umount"
            try:
                subprocess.run(
                    [umount_cmd, str(repository)],
                    check=True, capture_output=True, text=True, timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise PXEAnswerClientError(f"restore ended but NFS repository unmount failed: {exc}") from exc
        if temporary_repository is not None:
            temporary_repository.cleanup()


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

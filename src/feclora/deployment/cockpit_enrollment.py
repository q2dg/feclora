"""Cockpit helpers for public age-recipient export and Server CA backup."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from feclora.deployment.managed_pki import PKIError, ca_fingerprint

CONFIG = "/etc/feclora/deployment-server.json"
PKI = "/etc/feclora/pki"


class CockpitEnrollmentError(RuntimeError):
    """A removable-media security artifact could not be safely handled."""


def _media_file(value: object, label: str, *, optional: bool = False, maximum_size: int = 65536) -> str | None:
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str) or not os.path.isabs(value) or len(value) > 512:
        raise CockpitEnrollmentError(f"{label} must be an absolute removable-media file path")
    path = Path(value)
    # Only explicitly mounted removable-media locations are accepted.
    allowed = (Path("/run/media"), Path("/media"), Path("/mnt"))
    resolved = Path(os.path.realpath(path))
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise CockpitEnrollmentError(f"{label} must be located under /run/media, /media or /mnt")
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        mounted = False
        for line in mountinfo.splitlines():
            fields = line.split(" - ", 1)[0].split()
            if len(fields) < 5:
                continue
            mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
            mount_path = Path(mountpoint)
            if any(mount_path.is_relative_to(root) and resolved.is_relative_to(mount_path)
                   for root in allowed):
                mounted = True
                break
        if not mounted:
            raise CockpitEnrollmentError(f"{label} must be on a mounted removable-media filesystem")
        info = os.lstat(path)
    except OSError as exc:
        raise CockpitEnrollmentError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > maximum_size:
        raise CockpitEnrollmentError(f"{label} must be a regular file no larger than 64 KiB")
    return str(path)



def _media_directory(value: object, label: str) -> str:
    if not isinstance(value, str) or not os.path.isabs(value) or len(value) > 512:
        raise CockpitEnrollmentError(f"{label} must be an absolute removable-media directory")
    path = Path(value)
    resolved = Path(os.path.realpath(path))
    allowed = (Path("/run/media"), Path("/media"), Path("/mnt"))
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise CockpitEnrollmentError(f"{label} must be under /run/media, /media or /mnt")
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        mounted = False
        for line in mountinfo.splitlines():
            fields = line.split(" - ", 1)[0].split()
            if len(fields) < 5:
                continue
            mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\\t").replace("\\134", "\\\\")
            mount_path = Path(mountpoint)
            if any(mount_path.is_relative_to(root) and resolved.is_relative_to(mount_path)
                   for root in allowed):
                mounted = True
                break
        if not mounted:
            raise CockpitEnrollmentError(f"{label} must be on a mounted removable-media filesystem")
        info = os.lstat(path)
    except OSError as exc:
        raise CockpitEnrollmentError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CockpitEnrollmentError(f"{label} must be a real directory, not a symlink")
    return str(path)


def export_server_age_recipients(params: dict[str, object]) -> dict[str, object]:
    if set(params) != {"export_directory"}:
        raise CockpitEnrollmentError("export_server_age_recipients requires exactly export_directory")
    directory = _media_directory(params["export_directory"], "Age recipient export directory")
    source = os.path.join(PKI, "age-recipients.txt")
    source_fd = -1
    try:
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_size > 65536:
            raise CockpitEnrollmentError("Server age recipient inventory must be a root-owned regular file within 64 KiB")
        payload = os.read(source_fd, 65537)
        if len(payload) != info.st_size:
            raise CockpitEnrollmentError("Server age recipient inventory changed while being read")
    except OSError as exc:
        raise CockpitEnrollmentError(f"cannot read Server age recipient inventory: {exc}") from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)
    try:
        recipients = [line.strip() for line in payload.decode("ascii").splitlines() if line.strip()]
    except UnicodeError as exc:
        raise CockpitEnrollmentError("Server age recipient inventory is not valid ASCII") from exc
    if not recipients or len(recipients) != len(set(recipients)) or any(
        not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients
    ):
        raise CockpitEnrollmentError("Server age recipient inventory is empty, duplicated or malformed")
    destination = os.path.join(directory, "age-recipients.txt")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = -1
    try:
        directory_fd = os.open(
            directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open("age-recipients.txt", flags, 0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory_fd)
        except Exception:
            try:
                os.unlink("age-recipients.txt", dir_fd=directory_fd)
            except OSError:
                pass
            raise
    except FileExistsError as exc:
        raise CockpitEnrollmentError("age-recipients.txt already exists on the removable media; refusing to overwrite it") from exc
    except OSError as exc:
        raise CockpitEnrollmentError(f"cannot export age recipient inventory: {exc}") from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
    return {
        "path": destination, "recipient_count": len(recipients),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "message": "Updated public age recipient inventory exported. Copy it to the Clients that need the Server recipient and refresh that Client's local inventory.",
    }


def export_server_ca_backup(params: dict[str, object]) -> dict[str, object]:
    if set(params) != {"export_directory", "age_recipient"}:
        raise CockpitEnrollmentError(
            "export_server_ca_backup requires exactly export_directory and age_recipient"
        )
    export_dir = _media_directory(params["export_directory"], "CA backup export directory")
    recipient = params["age_recipient"]
    if not isinstance(recipient, str) or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
        raise CockpitEnrollmentError("CA backup requires a valid age recipient")
    try:
        from feclora.deployment.managed_pki import backup_server_ca
        fingerprint = ca_fingerprint(os.path.join(PKI, "ca.crt"))
        destination = os.path.join(export_dir, f"feclora-ca-backup-{fingerprint[:16]}.tar.age")
        result = backup_server_ca(destination, recipient, pki_directory=PKI)
        return result
    except (PKIError, OSError, ValueError) as exc:
        raise CockpitEnrollmentError(str(exc)) from exc



def inspect_server_ca_backup(params: dict[str, object]) -> dict[str, object]:
    if set(params) != {"backup_file", "identity_file"}:
        raise CockpitEnrollmentError(
            "inspect_server_ca_backup requires exactly backup_file and identity_file"
        )
    backup = _media_file(
        params["backup_file"], "Encrypted CA backup", maximum_size=16 * 1024 * 1024
    )
    identity = _media_file(params["identity_file"], "age decryption identity")
    try:
        from feclora.deployment.managed_pki import inspect_server_ca_backup as inspect_backup
        result = inspect_backup(backup, identity, pki_directory=PKI)
        return result
    except (PKIError, OSError, ValueError) as exc:
        raise CockpitEnrollmentError(str(exc)) from exc

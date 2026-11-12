"""Cockpit Client-side age-recipient inventory refresh helper."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from feclora.deployment.cockpit_enrollment import CockpitEnrollmentError
from feclora.deployment.runtime_config import load_client_runtime_config

CONFIG = "/etc/feclora/deployment-client.json"


def _mounted_media_directory(value: object) -> str:
    if not isinstance(value, str) or not os.path.isabs(value) or len(value) > 512:
        raise CockpitEnrollmentError("Removable-media directory must be an absolute path")
    path = Path(value)
    resolved = Path(os.path.realpath(path))
    roots = (Path("/run/media"), Path("/media"), Path("/mnt"))
    if not any(resolved.is_relative_to(root) for root in roots):
        raise CockpitEnrollmentError("Directory must be under /run/media, /media or /mnt")
    mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    mounted = False
    for line in mountinfo.splitlines():
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5:
            continue
        mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        mount_path = Path(mountpoint)
        if any(mount_path.is_relative_to(root) and resolved.is_relative_to(mount_path) for root in roots):
            mounted = True
            break
    if not mounted:
        raise CockpitEnrollmentError("Directory must be on a mounted removable-media filesystem")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CockpitEnrollmentError(f"Removable-media directory is unavailable: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CockpitEnrollmentError("Removable-media destination must be a real directory")
    return str(path)


def _bundle_file(directory: str, name: str, *, maximum: int = 65536) -> str:
    path = os.path.join(directory, name)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CockpitEnrollmentError(f"Server response bundle is missing {name}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > maximum:
        raise CockpitEnrollmentError(f"Server response {name} must be a regular file within the size limit")
    return path


def refresh_client_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"inventory_path"}:
        raise CockpitEnrollmentError("refresh_client_age_recipients requires exactly inventory_path")
    inventory_path = params["inventory_path"]
    if not isinstance(inventory_path, str) or os.path.basename(inventory_path) != "age-recipients.txt":
        raise CockpitEnrollmentError("inventory_path must identify age-recipients.txt on removable media")
    media_directory = _mounted_media_directory(os.path.dirname(inventory_path))
    source = _bundle_file(media_directory, "age-recipients.txt", maximum=65536)
    config = load_client_runtime_config(CONFIG)
    if not config.age_identity_file or not config.age_recipients_file:
        raise CockpitEnrollmentError("this Client has no configured age identity and recipient inventory")
    try:
        info = os.lstat(config.age_identity_file)
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o077):
            raise CockpitEnrollmentError("Client age identity must be a private, root-owned regular file")
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            source_info = os.fstat(source_fd)
            if not stat.S_ISREG(source_info.st_mode) or source_info.st_size > 65536:
                raise CockpitEnrollmentError("age recipient inventory must be a regular file within 64 KiB")
            payload = os.read(source_fd, 65537)
            if len(payload) != source_info.st_size:
                raise CockpitEnrollmentError("age recipient inventory changed while being read")
        finally:
            os.close(source_fd)
        recipients = [line.strip() for line in payload.decode("ascii").splitlines() if line.strip()]
    except (OSError, UnicodeError) as exc:
        raise CockpitEnrollmentError(f"cannot read age recipient inventory: {exc}") from exc
    if not recipients or len(recipients) != len(set(recipients)) or any(
        not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients
    ):
        raise CockpitEnrollmentError("age recipient inventory is empty, duplicated or malformed")
    result = subprocess.run(
        ["/usr/bin/age-keygen", "-y", config.age_identity_file],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=15,
    )
    if result.returncode != 0 or result.stdout.strip() not in recipients:
        raise CockpitEnrollmentError("updated recipient inventory does not contain this Client's own age identity")
    destination = config.age_recipients_file
    parent = os.path.dirname(destination)
    try:
        parent_info = os.lstat(parent)
        if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
                or parent_info.st_uid != 0 or parent_info.st_mode & 0o077):
            raise CockpitEnrollmentError("Client age recipient directory must be private, root-owned and real")
        if os.path.lexists(destination):
            destination_info = os.lstat(destination)
            if not stat.S_ISREG(destination_info.st_mode) or stat.S_ISLNK(destination_info.st_mode) or destination_info.st_uid != 0:
                raise CockpitEnrollmentError("existing Client age recipient inventory must be a root-owned regular file")
        fd, temporary = tempfile.mkstemp(prefix=".feclora-age-recipients-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with open(source, "rb") as src, os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise CockpitEnrollmentError(f"cannot install updated age recipient inventory: {exc}") from exc
    return {
        "recipient_count": len(recipients),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "message": "Client age recipient inventory refreshed. This Client can encrypt new images for the current Server recipient set; existing encrypted images are unchanged.",
    }



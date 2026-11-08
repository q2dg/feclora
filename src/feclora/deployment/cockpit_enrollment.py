"""Cockpit-facing removable-media Client enrollment workflow."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from feclora.deployment.managed_pki import (
    PKIError, ca_fingerprint, inspect_client_csr, issue_client_certificate,
    register_age_recipient, remove_age_recipient, _atomic_copy,
)
from feclora.deployment.enrollment import enroll_client_certificate
from feclora.deployment.runtime_config import load_server_runtime_config

CONFIG = "/etc/feclora/deployment-server.json"
PKI = "/etc/feclora/pki"


class CockpitEnrollmentError(RuntimeError):
    """A removable-media enrollment request could not be safely approved."""


def _media_file(value: object, label: str, *, optional: bool = False) -> str | None:
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
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > 65536:
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
        "message": "Updated public age recipient inventory exported. Copy it to each remaining enrolled Client and refresh that Client's local inventory.",
    }


def inspect_client_request(params: dict[str, object]) -> dict[str, str]:
    required = {"csr_path", "age_recipient_path", "mac_address"}
    optional = {"minisign_public_path", "renewal"}
    if set(params) - required - optional or not required.issubset(params):
        raise CockpitEnrollmentError("inspect_client_csr requires CSR, age recipient and MAC")
    renewal = params.get("renewal", False)
    if not isinstance(renewal, bool):
        raise CockpitEnrollmentError("renewal must be boolean")
    csr = _media_file(params["csr_path"], "Client CSR")
    age_file = _media_file(params["age_recipient_path"], "Client age recipient")
    minisign_file = _media_file(params.get("minisign_public_path"), "Client minisign public key", optional=True)
    assert csr is not None and age_file is not None
    mac = params["mac_address"]
    if not isinstance(mac, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise CockpitEnrollmentError("Client MAC address must be six hexadecimal octets")
    identity = inspect_client_csr(csr)
    recipient = Path(age_file).read_text(encoding="ascii").strip()
    if not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
        raise CockpitEnrollmentError("Client age recipient file is malformed")
    config = load_server_runtime_config(CONFIG)
    if renewal:
        if identity not in config.client_identity_to_mac:
            raise CockpitEnrollmentError("renewal CSR identity is not currently enrolled")
        enrolled_mac = config.client_identity_to_mac[identity]
        if enrolled_mac != mac.lower():
            raise CockpitEnrollmentError("renewal MAC must exactly match the currently enrolled Client")
        client_id = identity.removeprefix("URI:feclora-client-")
        mapping = Path(PKI) / "age-recipients" / f"{client_id}.txt"
        try:
            info = os.lstat(mapping)
            current_recipient = mapping.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise CockpitEnrollmentError("current Client age-recipient mapping is unavailable") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise CockpitEnrollmentError("current Client age-recipient mapping is unsafe")
        if recipient != current_recipient:
            raise CockpitEnrollmentError("renewal must preserve the enrolled Client age identity; use the separate recipient-rotation workflow")
        existing_signing_key = config.client_minisign_public_keys.get(mac.lower())
        if minisign_file:
            if not existing_signing_key or Path(minisign_file).read_bytes() != Path(existing_signing_key).read_bytes():
                raise CockpitEnrollmentError("renewal minisign key must match the currently enrolled public key")
        return {
            "identity": identity, "mac_address": mac.lower(),
            "confirmation_phrase": f"RENEW {identity}",
            "image_capture_enabled": str(bool(existing_signing_key)).lower(),
            "renewal": "true",
        }
    if identity in config.client_identity_to_mac:
        raise CockpitEnrollmentError("Client identity is already enrolled; select renewal inspection")
    if any(existing_mac.lower() == mac.lower() for existing_mac in config.client_identity_to_mac.values()):
        raise CockpitEnrollmentError("MAC address is already assigned to another enrolled Client")
    return {
        "identity": identity,
        "mac_address": mac.lower(),
        "confirmation_phrase": f"ENROLL {identity} {mac.lower()}",
        "image_capture_enabled": str(bool(minisign_file)).lower(),
        "renewal": "false",
    }


def approve_client_csr(params: dict[str, object]) -> dict[str, object]:
    required = {"csr_path", "age_recipient_path", "mac_address", "confirmation"}
    optional = {"minisign_public_path"}
    if set(params) - required - optional or not required.issubset(params):
        raise CockpitEnrollmentError("approve_client_csr requires CSR, age recipient, MAC and confirmation")
    csr = _media_file(params["csr_path"], "Client CSR")
    age_file = _media_file(params["age_recipient_path"], "Client age recipient")
    minisign_file = _media_file(params.get("minisign_public_path"), "Client minisign public key", optional=True)
    assert csr is not None and age_file is not None
    mac = params["mac_address"]
    confirmation = params["confirmation"]
    if not isinstance(mac, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise CockpitEnrollmentError("Client MAC address must be six hexadecimal octets")
    if not isinstance(confirmation, str) or len(confirmation) > 320:
        raise CockpitEnrollmentError("enrollment confirmation is invalid")
    try:
        identity = inspect_client_csr(csr)
        client_id = identity.removeprefix("URI:feclora-client-")
        recipient = Path(age_file).read_text(encoding="ascii").strip()
        if not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
            raise CockpitEnrollmentError("Client age recipient file is malformed")
        config = load_server_runtime_config(CONFIG)
        if identity in config.client_identity_to_mac:
            raise CockpitEnrollmentError("Client identity is already enrolled; use the renewal/reconciliation workflow")
        if any(existing_mac.lower() == mac.lower() for existing_mac in config.client_identity_to_mac.values()):
            raise CockpitEnrollmentError("MAC address is already assigned to another enrolled Client")
        export_dir = str(Path(csr).parent)
        certificate = os.path.join(export_dir, f"feclora-{client_id}.crt")
        bundle_files = (certificate, os.path.join(export_dir, "ca.crt"),
                        os.path.join(export_dir, "server.pub"),
                        os.path.join(export_dir, "age-recipients.txt"))
        if any(os.path.lexists(path) for path in bundle_files):
            raise CockpitEnrollmentError("A Server response bundle file already exists; refusing to overwrite removable-media contents")
        public_key_destination = None
        age_mapping = os.path.join(PKI, "age-recipients", client_id + ".txt")
        if os.path.lexists(age_mapping):
            raise CockpitEnrollmentError("A stale age-recipient mapping already exists for this Client identity")
        exported_paths = list(bundle_files)
        age_registered = False
        try:
            issue_client_certificate(csr, certificate, pki_directory=PKI)
            if minisign_file:
                public_key_destination = os.path.join(PKI, f"client-{client_id}.minisign.pub")
                if os.path.lexists(public_key_destination):
                    raise CockpitEnrollmentError("Client minisign public key is already registered locally")
                _atomic_copy(minisign_file, public_key_destination, 0o644)
            register_age_recipient(PKI, identity, recipient)
            age_registered = True
            for source, destination in (
                (config.ca_file, os.path.join(export_dir, "ca.crt")),
                (config.server_minisign_public_key, os.path.join(export_dir, "server.pub")),
                (os.path.join(PKI, "age-recipients.txt"), os.path.join(export_dir, "age-recipients.txt")),
            ):
                _atomic_copy(source, destination, 0o644 if not destination.endswith("age-recipients.txt") else 0o600)
            enroll_client_certificate(
                CONFIG, certificate, mac,
                minisign_public_key=public_key_destination,
                confirmation=confirmation,
            )
        except Exception:
            if age_registered:
                try:
                    remove_age_recipient(PKI, identity)
                except Exception:
                    pass
            for path in exported_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if public_key_destination:
                try:
                    os.unlink(public_key_destination)
                except OSError:
                    pass
            raise
        return {
            "identity": identity, "mac_address": mac.lower(),
            "certificate_file": certificate, "bundle_directory": export_dir,
            "ca_fingerprint": ca_fingerprint(config.ca_file),
            "server_minisign_sha256": hashlib.sha256(Path(config.server_minisign_public_key).read_bytes()).hexdigest(),
            "image_capture_enabled": bool(public_key_destination),
            "message": "Client certificate issued and enrolled. Only public trust material was exported; the Client private keys remain on that Client.",
        }
    except (PKIError, OSError, UnicodeError, ValueError) as exc:
        raise CockpitEnrollmentError(str(exc)) from exc

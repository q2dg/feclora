"""Cockpit-facing removable-media Client enrollment workflow."""
from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from feclora.deployment.managed_pki import (
    PKIError, ca_fingerprint, inspect_client_csr, issue_client_certificate,
    register_age_recipient, _atomic_copy, _regular_file,
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
        info = os.lstat(path)
    except OSError as exc:
        raise CockpitEnrollmentError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > 65536:
        raise CockpitEnrollmentError(f"{label} must be a regular file no larger than 64 KiB")
    return str(path)


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
        if os.path.lexists(certificate):
            raise CockpitEnrollmentError("Client certificate export already exists; refusing to overwrite it")
        issue_client_certificate(csr, certificate, pki_directory=PKI)
        public_key_destination = None
        if minisign_file:
            public_key_destination = os.path.join(PKI, f"client-{client_id}.minisign.pub")
            if os.path.lexists(public_key_destination):
                raise CockpitEnrollmentError("Client minisign public key is already registered locally")
            _atomic_copy(minisign_file, public_key_destination, 0o644)
        expected = f"ENROLL {identity} {mac.lower()}"
        enroll_client_certificate(
            CONFIG, certificate, mac,
            minisign_public_key=public_key_destination,
            confirmation=confirmation,
        )
        register_age_recipient(PKI, identity, recipient)
        ca_out = os.path.join(export_dir, "ca.crt")
        server_pub_out = os.path.join(export_dir, "server.pub")
        recipients_out = os.path.join(export_dir, "age-recipients.txt")
        for source, destination in (
            (config.ca_file, ca_out),
            (config.server_minisign_public_key, server_pub_out),
            (os.path.join(PKI, "age-recipients.txt"), recipients_out),
        ):
            _atomic_copy(source, destination, 0o644 if destination != recipients_out else 0o600)
        return {
            "identity": identity, "mac_address": mac.lower(),
            "certificate_file": certificate, "bundle_directory": export_dir,
            "ca_fingerprint": ca_fingerprint(config.ca_file),
            "server_minisign_sha256": __import__("hashlib").sha256(Path(config.server_minisign_public_key).read_bytes()).hexdigest(),
            "image_capture_enabled": bool(public_key_destination),
            "message": "Client certificate issued and enrolled. Only public trust material was exported; the Client private keys remain on that Client.",
        }
    except (PKIError, OSError, UnicodeError, ValueError) as exc:
        raise CockpitEnrollmentError(str(exc)) from exc

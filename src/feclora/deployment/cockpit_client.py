"""Cockpit Client-side removable-media enrollment helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from feclora.deployment.managed_pki import (
    PKIError, create_client_csr, install_client_certificate,
)
from feclora.deployment.cockpit_enrollment import CockpitEnrollmentError
from feclora.deployment.runtime_config import load_client_runtime_config

PKI = "/etc/feclora/pki"
CONFIG = "/etc/feclora/deployment-client.json"
REPOSITORY = "/var/lib/feclora/images"
_CLIENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_MAC = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


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


def _write_config(path: str, value: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise CockpitEnrollmentError("Client configuration directory must be root-owned")
    fd, temporary = tempfile.mkstemp(prefix=".deployment-client.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


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


def prepare_client_request(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"client_id", "export_directory", "image_capture"}:
        raise CockpitEnrollmentError("prepare_client_request requires client_id, export_directory and image_capture")
    client_id = params["client_id"]
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise CockpitEnrollmentError("Client identifier must contain 1-48 lowercase letters, digits or hyphens")
    if not isinstance(params["image_capture"], bool):
        raise CockpitEnrollmentError("image_capture must be boolean")
    if os.path.lexists(CONFIG):
        raise CockpitEnrollmentError("Client is already configured; use the renewal workflow")
    export = _mounted_media_directory(params["export_directory"])
    secret = os.path.join(PKI, f"client-{client_id}.minisign.key")
    public = os.path.join(PKI, f"client-{client_id}.minisign.pub")
    public_export_path = os.path.join(export, f"feclora-{client_id}.minisign.pub")
    public_export = None
    targets = (
        os.path.join(PKI, f"client-{client_id}.key"),
        os.path.join(PKI, f"client-{client_id}.csr"),
        os.path.join(PKI, f"client-{client_id}.age"),
        os.path.join(export, f"feclora-{client_id}.csr"),
        os.path.join(export, f"feclora-{client_id}.age-recipient"),
        secret, public, public_export_path,
    )
    if any(os.path.lexists(item) for item in targets):
        raise CockpitEnrollmentError("Client identity material or removable-media export already exists")
    try:
        identity, private_key, exported_csr = create_client_csr(PKI, export, client_id)
        if params["image_capture"]:
            result = subprocess.run(
                ["/usr/bin/minisign", "-G", "-s", secret, "-p", public, "-W"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=60,
            )
            if result.returncode != 0:
                raise CockpitEnrollmentError("Could not generate Client minisign keypair")
            os.chmod(secret, 0o600)
            os.chmod(public, 0o644)
            shutil.copyfile(public, public_export_path)
            os.chmod(public_export_path, 0o644)
            public_export = public_export_path
    except Exception:
        for item in targets:
            try:
                os.unlink(item)
            except OSError:
                pass
        raise
    return {
        "identity": identity, "csr_file": exported_csr,
        "age_recipient_file": os.path.join(export, f"feclora-{client_id}.age-recipient"),
        "minisign_public_file": public_export,
        "private_key_stays_local": private_key,
        "message": "Enrollment request prepared. Only the CSR and public age/minisign material were exported.",
    }


def complete_client_enrollment(params: dict[str, Any]) -> dict[str, Any]:
    required = {"client_id", "host", "mac_address", "bundle_directory",
                "ca_fingerprint", "server_minisign_sha256"}
    if set(params) != required:
        raise CockpitEnrollmentError("complete_client_enrollment requires the complete Server response and trust-verification fields")
    client_id, host, mac = params["client_id"], params["host"], params["mac_address"]
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise CockpitEnrollmentError("Client identifier is invalid")
    if not isinstance(host, str) or not host or len(host) > 253 or any(ord(c) < 33 for c in host):
        raise CockpitEnrollmentError("Server address is invalid")
    if not isinstance(mac, str) or not _MAC.fullmatch(mac):
        raise CockpitEnrollmentError("Client MAC address is invalid")
    normalized_mac = mac.lower()
    if int(normalized_mac.split(":", 1)[0], 16) & 1 or normalized_mac == "00:00:00:00:00:00":
        raise CockpitEnrollmentError("Client MAC must be a unicast hardware address")
    if os.path.lexists(CONFIG):
        raise CockpitEnrollmentError("Client deployment configuration already exists")
    bundle = _mounted_media_directory(params["bundle_directory"])
    certificate = _bundle_file(bundle, f"feclora-{client_id}.crt")
    ca_file = _bundle_file(bundle, "ca.crt")
    server_public = _bundle_file(bundle, "server.pub")
    recipients_file = _bundle_file(bundle, "age-recipients.txt")
    local_key = os.path.join(PKI, f"client-{client_id}.key")
    age_identity = os.path.join(PKI, f"client-{client_id}.age")
    for path, label in ((local_key, "local TLS private key"), (age_identity, "local age identity")):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise CockpitEnrollmentError(f"{label} is not a protected root-owned file")
    expected_ca = params["ca_fingerprint"]
    expected_server = params["server_minisign_sha256"]
    if not isinstance(expected_ca, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:?){32}", expected_ca):
        raise CockpitEnrollmentError("CA fingerprint must be a 64-digit SHA-256 hexadecimal value")
    if not isinstance(expected_server, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_server):
        raise CockpitEnrollmentError("Server minisign fingerprint must be a 64-digit SHA-256 hexadecimal value")
    actual_server = hashlib.sha256(Path(server_public).read_bytes()).hexdigest()
    if actual_server != expected_server.lower():
        raise CockpitEnrollmentError("Server minisign public-key fingerprint does not match the value verified from the Server")
    recipients = [line.strip() for line in Path(recipients_file).read_text(encoding="ascii").splitlines() if line.strip()]
    if not recipients or any(not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients):
        raise CockpitEnrollmentError("Server age recipient inventory is empty or malformed")
    os.makedirs(REPOSITORY, mode=0o700, exist_ok=True)
    repo_info = os.lstat(REPOSITORY)
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode) or repo_info.st_uid != 0 or repo_info.st_mode & 0o077:
        raise CockpitEnrollmentError("Client image repository must be a private root-owned directory")
    installed_server_key = os.path.join(PKI, "server.pub")
    installed_recipients = os.path.join(PKI, "age-recipients.txt")
    if any(os.path.lexists(path) for path in (
        os.path.join(PKI, "client.crt"), os.path.join(PKI, "client.key"),
        os.path.join(PKI, "ca.crt"), installed_server_key, installed_recipients,
    )):
        raise CockpitEnrollmentError("Partial Client enrollment files already exist; inspect them before retrying")
    installed = {
        "certificate_file": os.path.join(PKI, "client.crt"),
        "ca_file": os.path.join(PKI, "ca.crt"),
        "private_key_file": os.path.join(PKI, "client.key"),
    }
    try:
        installed = install_client_certificate(
            certificate, ca_file, local_key, PKI,
            f"URI:feclora-client-{client_id}", expected_ca,
        )
        shutil.copyfile(server_public, installed_server_key)
        os.chmod(installed_server_key, 0o644)
        shutil.copyfile(recipients_file, installed_recipients)
        os.chmod(installed_recipients, 0o600)
        minisign_secret = os.path.join(PKI, f"client-{client_id}.minisign.key")
        minisign_public = os.path.join(PKI, f"client-{client_id}.minisign.pub")
        if os.path.exists(minisign_secret) != os.path.exists(minisign_public):
            raise CockpitEnrollmentError("Client minisign keypair is incomplete")
        if os.path.exists(minisign_secret):
            for path in (minisign_secret, minisign_public):
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                    raise CockpitEnrollmentError("Client minisign key files must be root-owned regular files")
            if os.stat(minisign_secret).st_mode & 0o077:
                raise CockpitEnrollmentError("Client minisign secret key must be private")
        config = {
            "schema_version": 1, "host": host, "port": 9443,
            "local_identity": f"URI:feclora-client-{client_id}",
            "server_identity": "URI:feclora-server", "mac_address": normalized_mac,
            "ca_file": installed["ca_file"], "certificate_file": installed["certificate_file"],
            "private_key_file": installed["private_key_file"],
            "trusted_server_public_key": installed_server_key,
            "local_minisign_secret_key": minisign_secret if os.path.exists(minisign_secret) else None,
            "local_minisign_public_key": minisign_public if os.path.exists(minisign_public) else None,
            "age_identity_file": age_identity, "age_recipients_file": installed_recipients,
            "repository": REPOSITORY,
        }
        _write_config(CONFIG, config)
        load_client_runtime_config(CONFIG)
    except Exception:
        for path in (installed["certificate_file"], installed["ca_file"],
                     installed["private_key_file"], installed_server_key,
                     installed_recipients, CONFIG):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return {
        "identity": config["local_identity"], "host": host, "mac_address": normalized_mac,
        "image_capture_enabled": bool(config["local_minisign_secret_key"]),
        "message": "Client certificate and trust bundle installed and validated locally.",
    }

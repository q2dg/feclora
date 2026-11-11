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
    PKIError, create_client_csr, install_client_certificate, _atomic_copy,
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



def _require_pxe_identity_media(path: str) -> None:
    """Require a writable POSIX filesystem suitable for private key permissions."""
    resolved = Path(os.path.realpath(path))
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CockpitEnrollmentError(f"cannot inspect removable-media mount: {exc}") from exc
    matches = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        before = left.split()
        after = right.split()
        if not separator or len(before) < 6 or not after:
            continue
        mountpoint = Path(before[4].replace("\\040", " ").replace("\\011", "\\t").replace("\\134", "\\\\"))
        if resolved.is_relative_to(mountpoint):
            matches.append((len(str(mountpoint)), after[0], before[5].split(",")))
    if not matches:
        raise CockpitEnrollmentError("PXE identity destination is not on a mounted filesystem")
    _depth, filesystem, options = max(matches, key=lambda item: item[0])
    if filesystem not in {"ext4", "xfs", "btrfs"} or "rw" not in options:
        raise CockpitEnrollmentError("PXE identity media must be writable ext4, XFS or Btrfs so private-key permissions are preserved")


def export_pxe_client_identity(params: dict[str, Any]) -> dict[str, Any]:
    """Export one enrolled Client's mTLS identity to dedicated removable media.

    The USB medium is a physical bearer credential: keep it under physical
    control, use one medium per Client, and revoke the certificate if lost.
    """
    if set(params) != {"export_directory"}:
        raise CockpitEnrollmentError("export_pxe_client_identity requires exactly export_directory")
    config = load_client_runtime_config(CONFIG)
    export = _mounted_media_directory(params["export_directory"])
    _require_pxe_identity_media(export)
    root = Path(export)
    root_info = os.lstat(root)
    if root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022:
        raise CockpitEnrollmentError("PXE identity media must be root-owned and not group/other-writable")
    identity_dir = root / "feclora-client-identity"
    if os.path.lexists(identity_dir):
        raise CockpitEnrollmentError("PXE Client identity directory already exists; refusing to overwrite it")
    identity_dir.mkdir(mode=0o700)
    try:
        fields = {
            "ca_file": ("ca.crt", False),
            "certificate_file": ("client.crt", False),
            "private_key_file": ("client.key", True),
            "trusted_server_public_key": ("server.pub", False),
        }
        payload = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
        for field, (filename, private) in fields.items():
            source = getattr(config, field)
            if source is None:
                payload[field] = None
                continue
            try:
                source_info = os.lstat(source)
            except OSError as exc:
                raise CockpitEnrollmentError(f"configured Client identity file is unavailable: {field}") from exc
            if (not stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode)
                    or source_info.st_uid != os.geteuid() or (private and source_info.st_mode & 0o077)):
                raise CockpitEnrollmentError(f"configured Client identity file is unsafe: {field}")
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            destination = identity_dir / filename
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            target_fd = os.open(destination, flags, 0o600 if private else 0o644)
            try:
                opened = os.fstat(source_fd)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
                        or (opened.st_dev, opened.st_ino) != (source_info.st_dev, source_info.st_ino)):
                    raise CockpitEnrollmentError(f"Client identity file changed during export: {field}")
                while True:
                    chunk = os.read(source_fd, 1024 * 1024)
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        written = os.write(target_fd, view)
                        if written <= 0:
                            raise CockpitEnrollmentError("short write while exporting Client identity")
                        view = view[written:]
                os.fsync(target_fd)
            finally:
                os.close(source_fd)
                os.close(target_fd)
            payload[field] = str(destination)
        for field in ("local_minisign_secret_key", "local_minisign_public_key", "age_identity_file", "age_recipients_file"):
            payload[field] = None
        payload["repository"] = REPOSITORY
        config_path = identity_dir / "deployment-client.json"
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\\n").encode("utf-8")
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise CockpitEnrollmentError("short write while saving PXE Client configuration")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        directory_fd = os.open(identity_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {
            "identity": config.local_identity,
            "directory": str(identity_dir),
            "config_file": str(config_path),
            "private_key_exported": True,
            "message": "Per-Client mTLS identity exported to removable media. This medium is a bearer credential; keep it physically secure and revoke this Client certificate immediately if it is lost.",
        }
    except Exception:
        shutil.rmtree(identity_dir, ignore_errors=True)
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
    if set(params) != {"client_id", "export_directory", "image_signing", "age_encryption"}:
        raise CockpitEnrollmentError(
            "prepare_client_request requires client_id, export_directory, image_signing and age_encryption"
        )
    client_id = params["client_id"]
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise CockpitEnrollmentError("Client identifier must contain 1-48 lowercase letters, digits or hyphens")
    if not isinstance(params["image_signing"], bool) or not isinstance(params["age_encryption"], bool):
        raise CockpitEnrollmentError("image_signing and age_encryption must be boolean")
    age_keygen = shutil.which("age-keygen") if params["age_encryption"] else None
    if params["age_encryption"] and not age_keygen:
        raise CockpitEnrollmentError("age-keygen is required only when age decryption is enabled for this Client")
    minisign = shutil.which("minisign") if params["image_signing"] else None
    if params["image_signing"] and not minisign:
        raise CockpitEnrollmentError("minisign is required only when image signing is enabled for this Client")
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
        identity, private_key, exported_csr = create_client_csr(
            PKI, export, client_id, age_keygen=age_keygen,
        )
        if params["image_signing"]:
            result = subprocess.run(
                [minisign, "-G", "-s", secret, "-p", public, "-W"],
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
        "age_recipient_file": (os.path.join(export, f"feclora-{client_id}.age-recipient")
                              if os.path.isfile(os.path.join(export, f"feclora-{client_id}.age-recipient")) else None),
        "minisign_public_file": public_export,
        "private_key_stays_local": private_key,
        "message": "Enrollment request prepared. Only the CSR and public age/minisign material were exported.",
    }


def prepare_client_renewal(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"export_directory"}:
        raise CockpitEnrollmentError("prepare_client_renewal requires exactly export_directory")
    config = load_client_runtime_config(CONFIG)
    prefix = "URI:feclora-client-"
    if not config.local_identity.startswith(prefix):
        raise CockpitEnrollmentError("Client identity is not eligible for managed certificate renewal")
    client_id = config.local_identity.removeprefix(prefix)
    if not _CLIENT_ID.fullmatch(client_id):
        raise CockpitEnrollmentError("configured Client identity is malformed")
    export = _mounted_media_directory(params["export_directory"])
    retained_key = os.path.join(PKI, f"client-{client_id}.key")
    for path, label in ((retained_key, "retained Client private key"), (config.private_key_file, "active Client private key")):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise CockpitEnrollmentError(f"{label} is not a protected root-owned regular file")
    def public_key(path: str) -> bytes:
        result = subprocess.run(
            ["/usr/bin/openssl", "pkey", "-in", path, "-pubout", "-outform", "DER"],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=15,
        )
        if result.returncode != 0 or not result.stdout:
            raise CockpitEnrollmentError("could not validate the existing Client private key")
        return result.stdout
    if public_key(retained_key) != public_key(config.private_key_file):
        raise CockpitEnrollmentError("retained renewal key does not match the active Client TLS identity")
    retained_age_identity = os.path.join(PKI, f"client-{client_id}.age")
    if config.age_identity_file:
        if os.path.realpath(config.age_identity_file) != os.path.realpath(retained_age_identity):
            raise CockpitEnrollmentError("configured age identity does not match the managed Client identity; refusing renewal")
        if not os.path.lexists(retained_age_identity):
            raise CockpitEnrollmentError("Client age identity is missing; renewal cannot preserve the current recipient")
    # Renewal preserves age only when this Client already has an
    # age identity configured. Do not silently enroll a new recipient just
    # because age-keygen happens to be installed.
    age_keygen = shutil.which("age-keygen") if config.age_identity_file else None
    identity, _key, exported_csr = create_client_csr(
        PKI, export, client_id, reuse_existing_key=True,
        age_keygen=age_keygen,
    )
    recipient_file = os.path.join(export, f"feclora-{client_id}-renewal.age-recipient")
    exported_minisign = None
    try:
        if config.local_minisign_public_key:
            exported_minisign = os.path.join(export, f"feclora-{client_id}-renewal.minisign.pub")
            if os.path.lexists(exported_minisign):
                raise CockpitEnrollmentError("Client minisign renewal export already exists")
            _atomic_copy(config.local_minisign_public_key, exported_minisign, 0o644)
    except Exception:
        for path in (exported_csr, recipient_file):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return {
        "identity": identity, "csr_file": exported_csr,
        "age_recipient_file": recipient_file if os.path.isfile(recipient_file) else None,
        "minisign_public_file": exported_minisign,
        "message": "Renewal CSR prepared using the existing TLS private key. The private key, age identity and image-signing key remain local; only public request material was exported.",
    }


def complete_client_renewal(params: dict[str, Any]) -> dict[str, Any]:
    required = {"bundle_directory", "ca_fingerprint"}
    optional = {"server_minisign_sha256"}
    if set(params) - required - optional or not required.issubset(params):
        raise CockpitEnrollmentError("complete_client_renewal requires a response bundle and CA fingerprint; image-security fingerprints are optional")
    config = load_client_runtime_config(CONFIG)
    prefix = "URI:feclora-client-"
    if not config.local_identity.startswith(prefix):
        raise CockpitEnrollmentError("Client identity is not eligible for managed certificate renewal")
    client_id = config.local_identity.removeprefix(prefix)
    if not _CLIENT_ID.fullmatch(client_id):
        raise CockpitEnrollmentError("configured Client identity is malformed")
    bundle = _mounted_media_directory(params["bundle_directory"])
    certificate = _bundle_file(bundle, f"feclora-{client_id}-renewal.crt")
    ca_file = _bundle_file(bundle, "ca-renewal.crt")
    server_public_path = os.path.join(bundle, "server-renewal.pub")
    recipients_path = os.path.join(bundle, "age-recipients-renewal.txt")
    server_public = _bundle_file(bundle, "server-renewal.pub") if os.path.lexists(server_public_path) else None
    recipients_file = _bundle_file(bundle, "age-recipients-renewal.txt") if os.path.lexists(recipients_path) else None
    expected_ca = params["ca_fingerprint"]
    if not isinstance(expected_ca, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:?){32}", expected_ca):
        raise CockpitEnrollmentError("CA fingerprint must be a 64-digit SHA-256 hexadecimal value")
    expected_server = params.get("server_minisign_sha256")
    if expected_server is not None:
        if not isinstance(expected_server, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_server):
            raise CockpitEnrollmentError("Server minisign fingerprint must be a 64-digit SHA-256 hexadecimal value")
        if server_public is None:
            raise CockpitEnrollmentError("Server minisign fingerprint was supplied but server-renewal.pub is missing")
        if hashlib.sha256(Path(server_public).read_bytes()).hexdigest() != expected_server.lower():
            raise CockpitEnrollmentError("Server minisign public-key fingerprint does not match the value verified from the Server")
    recipients = []
    if recipients_file:
        recipients = [line.strip() for line in Path(recipients_file).read_text(encoding="ascii").splitlines() if line.strip()]
        if not recipients or len(recipients) != len(set(recipients)) or any(
            not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients
        ):
            raise CockpitEnrollmentError("Server age recipient inventory is empty, duplicated or malformed")
        if config.age_identity_file:
            age_keygen = shutil.which("age-keygen")
            if age_keygen:
                age_result = subprocess.run(
                    [age_keygen, "-y", config.age_identity_file],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=15,
                )
                own_recipient = age_result.stdout.strip()
                if age_result.returncode != 0 or own_recipient not in recipients:
                    raise CockpitEnrollmentError("renewal response does not retain this Client's current age recipient")
            else:
                # Preserve the existing recipient inventory rather than making
                # TLS renewal depend on an optional age executable.
                recipients_file = None
    installed_server_key = os.path.join(PKI, "server.pub")
    installed_recipients = os.path.join(PKI, "age-recipients.txt")
    update_server_key = server_public is not None and expected_server is not None
    destinations = [os.path.join(PKI, "client.crt"), os.path.join(PKI, "ca.crt"), config.private_key_file, CONFIG]
    if update_server_key:
        destinations.append(installed_server_key)
    if recipients_file:
        destinations.append(installed_recipients)
    backups: dict[str, bytes | None] = {}
    for path in destinations:
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                raise CockpitEnrollmentError("existing Client trust file is not a root-owned regular file")
            backups[path] = Path(path).read_bytes()
        except FileNotFoundError:
            backups[path] = None
    try:
        installed = install_client_certificate(
            certificate, ca_file, config.private_key_file, PKI,
            config.local_identity, expected_ca,
        )
        if update_server_key:
            _atomic_copy(server_public, installed_server_key, 0o644)
        if recipients_file:
            _atomic_copy(recipients_file, installed_recipients, 0o600)
        runtime_value = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
        if update_server_key:
            runtime_value["trusted_server_public_key"] = installed_server_key
        if recipients_file:
            runtime_value["age_recipients_file"] = installed_recipients
        _write_config(CONFIG, runtime_value)
        updated = load_client_runtime_config(CONFIG)
    except Exception:
        for path, content in backups.items():
            if content is None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            else:
                fd, temporary = tempfile.mkstemp(prefix=".feclora-renewal-rollback-", dir=os.path.dirname(path))
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(temporary, 0o600 if path in {config.private_key_file, installed_recipients, CONFIG} else 0o644)
                    os.replace(temporary, path)
                except Exception:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
        raise
    return {
        "identity": updated.local_identity, "certificate_file": installed["certificate_file"],
        "image_signing_enabled": bool(updated.local_minisign_secret_key),
        "message": "Renewed TLS certificate installed and validated. Existing TLS identity is preserved; optional age and minisign material is refreshed only when supplied and verified.",
    }


def complete_client_enrollment(params: dict[str, Any]) -> dict[str, Any]:
    required = {"client_id", "host", "mac_address", "bundle_directory", "ca_fingerprint"}
    optional = {"server_minisign_sha256"}
    if set(params) - required - optional or not required.issubset(params):
        raise CockpitEnrollmentError("complete_client_enrollment requires Client details and a verified CA fingerprint; image-security fingerprints are optional")
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
    server_public_path = os.path.join(bundle, "server.pub")
    recipients_path = os.path.join(bundle, "age-recipients.txt")
    server_public = _bundle_file(bundle, "server.pub") if os.path.lexists(server_public_path) else None
    recipients_file = _bundle_file(bundle, "age-recipients.txt") if os.path.lexists(recipients_path) else None
    local_key = os.path.join(PKI, f"client-{client_id}.key")
    age_identity = os.path.join(PKI, f"client-{client_id}.age")
    info = os.lstat(local_key)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise CockpitEnrollmentError("local TLS private key is not a protected root-owned file")
    has_age_identity = os.path.lexists(age_identity)
    if has_age_identity:
        info = os.lstat(age_identity)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise CockpitEnrollmentError("local age identity is not a protected root-owned file")
    expected_ca = params["ca_fingerprint"]
    if not isinstance(expected_ca, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:?){32}", expected_ca):
        raise CockpitEnrollmentError("CA fingerprint must be a 64-digit SHA-256 hexadecimal value")
    expected_server = params.get("server_minisign_sha256")
    if expected_server is not None:
        if not isinstance(expected_server, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_server):
            raise CockpitEnrollmentError("Server minisign fingerprint must be a 64-digit SHA-256 hexadecimal value")
        if server_public is None:
            raise CockpitEnrollmentError("Server minisign fingerprint was supplied but server.pub is missing from the bundle")
        actual_server = hashlib.sha256(Path(server_public).read_bytes()).hexdigest()
        if actual_server != expected_server.lower():
            raise CockpitEnrollmentError("Server minisign public-key fingerprint does not match the value verified from the Server")
    trusted_server_key = server_public if expected_server is not None else None
    if recipients_file:
        recipients = [line.strip() for line in Path(recipients_file).read_text(encoding="ascii").splitlines() if line.strip()]
        if not recipients or len(recipients) != len(set(recipients)) or any(
            not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients
        ):
            raise CockpitEnrollmentError("Server age recipient inventory is empty, duplicated or malformed")
    os.makedirs(REPOSITORY, mode=0o700, exist_ok=True)
    repo_info = os.lstat(REPOSITORY)
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode) or repo_info.st_uid != 0 or repo_info.st_mode & 0o077:
        raise CockpitEnrollmentError("Client image repository must be a private root-owned directory")
    installed_server_key = os.path.join(PKI, "server.pub")
    installed_recipients = os.path.join(PKI, "age-recipients.txt")
    destinations = [os.path.join(PKI, "client.crt"), os.path.join(PKI, "client.key"), os.path.join(PKI, "ca.crt")]
    if trusted_server_key:
        destinations.append(installed_server_key)
    if recipients_file:
        destinations.append(installed_recipients)
    if any(os.path.lexists(path) for path in destinations):
        raise CockpitEnrollmentError("Partial Client enrollment files already exist; inspect them before retrying")
    installed = {
        "certificate_file": os.path.join(PKI, "client.crt"),
        "ca_file": os.path.join(PKI, "ca.crt"),
        "private_key_file": os.path.join(PKI, "client.key"),
    }
    created_files = list(destinations)
    try:
        installed = install_client_certificate(
            certificate, ca_file, local_key, PKI,
            f"URI:feclora-client-{client_id}", expected_ca,
        )
        if trusted_server_key:
            shutil.copyfile(trusted_server_key, installed_server_key)
            os.chmod(installed_server_key, 0o644)
        if recipients_file:
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
            "trusted_server_public_key": installed_server_key if trusted_server_key else None,
            "local_minisign_secret_key": minisign_secret if os.path.exists(minisign_secret) else None,
            "local_minisign_public_key": minisign_public if os.path.exists(minisign_public) else None,
            "age_identity_file": age_identity if has_age_identity else None,
            "age_recipients_file": installed_recipients if recipients_file else None,
            "repository": REPOSITORY,
        }
        _write_config(CONFIG, config)
        load_client_runtime_config(CONFIG)
    except Exception:
        for path in created_files + [CONFIG]:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return {
        "identity": config["local_identity"], "host": host, "mac_address": normalized_mac,
        "image_signing_enabled": bool(config["local_minisign_secret_key"]),
        "age_encryption_enabled": bool(config["age_recipients_file"]),
        "age_decryption_enabled": bool(config["age_identity_file"]),
        "message": "Client TLS certificate installed. Optional age and minisign image-protection material was installed only when provided and independently verified.",
    }

"""Dialog workflow for an authenticated Client save/restore job."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import socket
import subprocess
import sys
from typing import Any

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.managed_pki import PKIError

from feclora.deployment.multicast_runtime import execute_multicast_restore
from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, join_deployment,
)
from feclora.deployment.runtime_config import (
    ClientRuntimeConfig, RuntimeConfigError, load_client_runtime_config,
)
from feclora.network.remote_clone_protocol import create_tls_context
from feclora.network.multicast_preflight import inspect_multicast_interface
from feclora.network.firewall import PXEFirewall
from feclora.storage.inventory import InventoryError, collect_inventory
from feclora.ui import dialog_app


CONFIG_PATH = "/etc/feclora/deployment-client.json"


def _elevate() -> int:
    sudo = shutil.which("sudo")
    if not sudo:
        dialog_app._message(
            "Client mode requires root",
            "sudo is required to inspect and restore local block devices and manage multicast firewall rules.",
        )
        return 1
    pythonpath = os.environ.get("PYTHONPATH") or "/usr/share/feclora/python"
    term = os.environ.get("TERM") or "linux"
    result = subprocess.run(
        [sudo, "-n", "env", f"PYTHONPATH={pythonpath}", f"TERM={term}",
         sys.executable, "-m", "feclora.deployment.client_ui"],
        check=False,
    )
    return result.returncode



def _generate_client_minisign_keypair(pki_directory: str, export_directory: str, client_id: str) -> tuple[str, str]:
    secret = os.path.join(pki_directory, f"client-{client_id}.minisign.key")
    public = os.path.join(pki_directory, f"client-{client_id}.minisign.pub")
    exported = os.path.join(export_directory, f"feclora-{client_id}.minisign.pub")
    if any(os.path.lexists(path) for path in (secret, public, exported)):
        raise PKIError("Client image-signing keypair or public export already exists")
    result = subprocess.run(
        ["/usr/bin/minisign", "-G", "-s", secret, "-p", public, "-W"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        check=False, timeout=60,
    )
    if result.returncode != 0:
        raise PKIError("could not generate Client minisign keypair: " + (result.stderr or result.stdout).strip()[:256])
    os.chmod(secret, 0o600)
    os.chmod(public, 0o644)
    shutil.copyfile(public, exported)
    os.chmod(exported, 0o644)
    return secret, public



def _capture_image_security_options(config: ClientRuntimeConfig) -> tuple[str | None, str | None] | None:
    """Ask for per-image protection; expose only modes whose local keys/tools exist."""
    age_ready = bool(
        config.age_recipients_file
        and os.path.isfile(config.age_recipients_file)
        and shutil.which("age")
    )
    sign_ready = bool(
        config.local_minisign_secret_key
        and config.local_minisign_public_key
        and os.path.isfile(config.local_minisign_secret_key)
        and os.path.isfile(config.local_minisign_public_key)
        and shutil.which("minisign")
    )
    choices = [("none", "Neither encryption nor signature")]
    if age_ready:
        choices.append(("age", "Encrypt this image with age"))
    if sign_ready:
        choices.append(("minisign", "Sign this image with minisign"))
    if age_ready and sign_ready:
        choices.append(("both", "Encrypt with age and sign with minisign"))
    selected = dialog_app._menu(
        "Image security",
        "Choose protection for this image only. No protection is the default; unavailable tools or keys are not required.",
        choices,
    )
    if selected is None:
        return None
    return (
        config.age_recipients_file if selected in {"age", "both"} else None,
        config.local_minisign_secret_key if selected in {"minisign", "both"} else None,
    )


def _write_client_config(path: str, value: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise PKIError("Client configuration directory must be a real root-owned directory")
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


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _client_enrollment_wizard(config_path: str) -> bool:
    """Configure Server trust; Clients do not enroll or present certificates."""
    host = dialog_app._input("Feclora Server address", "Enter the Server IPv4 address or hostname:")
    if not host:
        return False
    mac = dialog_app._input("Client MAC address", "Enter this Client's unicast MAC address:")
    if not mac:
        return False
    bundle = dialog_app._input(
        "Server trust bundle",
        "Path to a directory containing the Server CA certificate (ca.crt), optionally server.pub and age-recipients.txt:",
    )
    if not bundle or not os.path.isdir(bundle) or os.path.islink(bundle):
        raise PKIError("Server trust bundle must be an existing real directory")
    ca_source = os.path.join(bundle, "ca.crt")
    if not os.path.isfile(ca_source) or os.path.islink(ca_source):
        raise PKIError("Server trust bundle must contain ca.crt")
    fingerprint = _sha256_file(ca_source)
    expected = dialog_app._input(
        "Verify Server CA fingerprint",
        "Compare the SHA-256 fingerprint with the value shown by the Server, then type it exactly:
" + fingerprint,
    )
    if expected is None or expected.replace(":", "").lower() != fingerprint.lower():
        raise PKIError("Server CA fingerprint did not match")
    server_identity = dialog_app._input(
        "Server certificate identity",
        "Expected SAN identity of the Server certificate (normally URI:feclora-server):",
    ) or "URI:feclora-server"
    pki_directory = "/etc/feclora/pki"
    os.makedirs(pki_directory, mode=0o700, exist_ok=True)
    ca_file = os.path.join(pki_directory, "ca.crt")
    if os.path.lexists(ca_file):
        raise PKIError("Server CA file already exists; inspect it before replacing trust material")
    shutil.copyfile(ca_source, ca_file)
    os.chmod(ca_file, 0o644)
    server_key_source = os.path.join(bundle, "server.pub")
    trusted_server_key = None
    if os.path.isfile(server_key_source) and not os.path.islink(server_key_source):
        trusted_server_key = os.path.join(pki_directory, "server.pub")
        if os.path.lexists(trusted_server_key):
            raise PKIError("trusted Server image-signing key already exists")
        shutil.copyfile(server_key_source, trusted_server_key)
        os.chmod(trusted_server_key, 0o644)
    recipients_source = os.path.join(bundle, "age-recipients.txt")
    recipients_file = None
    age_identity = None
    if os.path.isfile(recipients_source) and not os.path.islink(recipients_source):
        recipients_file = os.path.join(pki_directory, "age-recipients.txt")
        if os.path.lexists(recipients_file):
            raise PKIError("age recipient inventory already exists")
        shutil.copyfile(recipients_source, recipients_file)
        os.chmod(recipients_file, 0o600)
        age_keygen = shutil.which("age-keygen")
        if age_keygen:
            age_identity = os.path.join(pki_directory, "client.age")
            if os.path.lexists(age_identity):
                raise PKIError("Client age identity already exists")
            result = subprocess.run(
                [age_keygen, "-o", age_identity], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, check=False, timeout=60,
            )
            if result.returncode != 0:
                raise PKIError("could not create optional Client age identity")
            os.chmod(age_identity, 0o600)
    repository = "/var/lib/feclora/images"
    os.makedirs(repository, mode=0o700, exist_ok=True)
    os.chmod(repository, 0o700)
    config = {
        "schema_version": 1,
        "host": host,
        "port": 9443,
        "server_identity": server_identity,
        "mac_address": mac.lower(),
        "ca_file": ca_file,
        "trusted_server_public_key": trusted_server_key,
        "local_minisign_secret_key": None,
        "local_minisign_public_key": None,
        "age_identity_file": age_identity,
        "age_recipients_file": recipients_file,
        "repository": repository,
    }
    _write_client_config(config_path, config)
    dialog_app._message(
        "Client configured",
        "Server certificate verification is configured. The Client presents no certificate and has no individual authentication identity.",
    )
    return True


def _refresh_client_age_recipients(config: ClientRuntimeConfig) -> None:
    if not config.age_identity_file or not config.age_recipients_file:
        raise PKIError("this Client has no configured age identity/recipient inventory")
    bundle = dialog_app._input(
        "Updated age recipient inventory",
        "Path to a removable-media directory containing age-recipients.txt exported by the Server:",
    )
    if not bundle:
        return
    source = os.path.join(bundle, "age-recipients.txt")
    info = os.lstat(source)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PKIError("age recipient inventory must be a regular file, not a symlink")
    with open(source, encoding="ascii") as stream:
        recipients = [line.strip() for line in stream if line.strip()]
    if not recipients or any(not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients):
        raise PKIError("age recipient inventory is empty or malformed")
    result = subprocess.run(
        ["/usr/bin/age-keygen", "-y", config.age_identity_file],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=15,
    )
    if result.returncode != 0 or result.stdout.strip() not in recipients:
        raise PKIError("updated recipient inventory does not contain this Client's own age identity")
    destination = config.age_recipients_file
    parent = os.path.dirname(destination)
    fd, temporary = tempfile.mkstemp(prefix=".feclora-age-recipients-", dir=parent)
    try:
        with open(source, "rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    dialog_app._message(
        "Age recipient inventory refreshed",
        "This Client can now encrypt new images for the current enrolled recipient set. Existing encrypted images are unchanged.",
    )


def _prepare_client_renewal(config: ClientRuntimeConfig) -> None:
    prefix = "URI:feclora-client-"
    if not config.local_identity.startswith(prefix):
        raise PKIError("this Client identity cannot use Feclora-managed renewal")
    client_id = config.local_identity[len(prefix):]
    export_directory = dialog_app._input(
        "Export renewal request",
        "Path to an existing removable-media directory. The current Client private key will be reused and will not leave this machine:",
    )
    if not export_directory:
        return
    identity, _key, exported = create_client_csr(
        "/etc/feclora/pki", export_directory, client_id, reuse_existing_key=True,
    )
    signing_public = os.path.join("/etc/feclora/pki", f"client-{client_id}.minisign.pub")
    if os.path.isfile(signing_public):
        exported_public = os.path.join(export_directory, f"feclora-{client_id}-renewal.minisign.pub")
        if os.path.lexists(exported_public):
            raise PKIError("Client minisign public-key renewal export already exists")
        shutil.copyfile(signing_public, exported_public)
        os.chmod(exported_public, 0o644)
    dialog_app._message(
        "Renewal request prepared",
        f"Identity: {identity}\nCSR: {exported}\n\n"
        "Take the CSR and age-recipient file to the Server. Approve the CSR there, then return the signed response bundle and choose Install renewed certificate.",
    )


def run_client_ui(*, config_path: str = CONFIG_PATH) -> int:
    """Join one Server job after local device selection and typed approval."""
    if os.geteuid() != 0:
        return _elevate()
    try:
        if not os.path.exists(config_path):
            if not _client_enrollment_wizard(config_path):
                return 0
        config = load_client_runtime_config(config_path)
        identity_choices = [("join", "Join deployment job")]
        if config.age_identity_file and config.age_recipients_file:
            identity_choices.append(("refresh-age", "Refresh age recipient inventory"))
        identity_choices.append(("cancel", "Cancel"))
        identity_action = dialog_app._menu(
            "Client",
            "Server certificate verification is enabled; no Client certificate or individual authentication is used.",
            identity_choices,
        )
        if identity_action in (None, "cancel"):
            return 0
        if identity_action == "refresh-age":
            _refresh_client_age_recipients(config)
            return 0
        job_id = dialog_app._input(
            "Join deployment job",
            "Enter the job UUID shown by the Feclora Server operator:",
        )
        if job_id is None:
            return 0
        context = create_tls_context("client", ca_file=config.ca_file)
        state: dict[str, Any] = {}

        def prepare_local_target(job):
            if job.transport == "multicast":
                try:
                    interfaces = [
                        (name, f"{name} (local multicast receiver interface)")
                        for _index, name in socket.if_nameindex() if name != "lo"
                    ]
                except OSError as exc:
                    raise DeploymentControlError(f"cannot enumerate local network interfaces: {exc}") from exc
                selected_interface = dialog_app._menu(
                    "Client multicast interface",
                    "Select this Client's local interface for receiving the multicast image. "
                    "It may have a different name from the Server interface.",
                    interfaces,
                )
                if selected_interface is None:
                    raise DeploymentControlError("local multicast interface selection cancelled")
                preflight = inspect_multicast_interface(
                    selected_interface, job.multicast_group, role="receiver",
                )
                dialog_app._message(
                    "Client multicast preflight",
                    f"Interface: {preflight.interface} ({preflight.ipv4_address})\nKernel route: {preflight.route_interface}\n\n"
                    + "\n".join(preflight.warnings),
                )
                state["multicast_interface"] = selected_interface
            if job.operation == "save" and not config.local_minisign_secret_key:
                raise DeploymentControlError("this Client has no enrolled minisign signing key and cannot create images")
            inventory = collect_inventory()
            target_kind = "partition" if job.target_type == "partition" else "disk"
            if job.target_type == "logical_volume":
                topology = inventory.get("volume_topology", {})
                if topology.get("status") != "available":
                    raise DeploymentControlError("LVM topology is unavailable; cannot select a logical-volume target")
                lv_items = [
                    (lv, group) for group in topology.get("volume_groups", [])
                    for lv in group.get("logical_volumes", [])
                    if isinstance(lv, dict) and lv.get("path")
                    and lv.get("segment_type") in {"linear", "thin"}
                    and not lv.get("snapshot") and not lv.get("hidden")
                ]
                choices = [
                    (lv["path"], f"{group.get('name')}/{lv.get('name')} | {lv.get('size_bytes') or '?'} bytes | {lv.get('segment_type')}")
                    for lv, group in lv_items
                ]
                selected_path = dialog_app._menu(
                    "Local deployment logical volume",
                    "Choose an existing active LV. It must be unmounted, healthy and large enough; Feclora will not create or resize LVM metadata.",
                    choices,
                )
                selected = next((lv for lv, _group in lv_items if lv.get("path") == selected_path), None)
                if selected is None:
                    raise DeploymentControlError("local logical-volume selection cancelled")
            else:
                target_label = "Local deployment partition" if target_kind == "partition" else "Local deployment disk"
                target_help = (
                    "Select the existing destination partition. It must be at least as large as the source image; "
                    "Feclora will not create or resize partitions."
                    if target_kind == "partition" else
                    "Select the whole disk for this job. Root, mounted or busy disks will be rejected before any write."
                )
                selected = dialog_app._select_device(inventory, target_kind, target_label, target_help)
                if selected is None:
                    raise DeploymentControlError("local disk selection cancelled")
            path = selected.get("path")
            if not isinstance(path, str):
                raise DeploymentControlError("selected disk has no stable device path")
            if job.operation == "restore":
                phrase = f"ERASE {path} FROM {config.server_identity}"
                prompt = (
                    "This operation overwrites the selected existing logical volume. Type the exact confirmation phrase:"
                    if job.target_type == "logical_volume" else
                    "This operation overwrites the selected existing partition. Type the exact confirmation phrase:"
                    if target_kind == "partition" else
                    "This operation overwrites the selected whole disk. Type the exact confirmation phrase:"
                )
            else:
                phrase = f"READ {path} TO {config.server_identity}"
                prompt = "This operation reads the selected whole disk to create an image. You will choose optional age encryption and minisign signing for this image in the next step. Type the exact confirmation phrase:"
            dialog_app._message("Selected local target", dialog_app.device_details(selected))
            typed = dialog_app._input("Explicit local authorization", f"{prompt}\n\n{phrase}")
            if typed != phrase:
                raise DeploymentControlError("local typed confirmation did not match; no disk operation was started")
            description = " ".join(
                str(value) for value in (
                    selected.get("model"), selected.get("size_bytes"), selected.get("serial"),
                ) if value
            ) or ("Selected local logical volume" if job.target_type == "logical_volume" else "Selected local whole disk")
            if job.operation == "save":
                compression_choice = dialog_app._menu(
                    "Capture compression", "Choose whole-disk image compression.",
                    [("none", "None"), ("gzip", "gzip (balanced)"), ("xz", "xz (smaller, slower)"),
                     ("zstd", "zstd (fast, balanced)"), ("lz4", "lz4 (fastest)")],
                )
                if compression_choice is None:
                    raise DeploymentControlError("capture compression selection cancelled")
                state["compression"] = compression_choice
                security = _capture_image_security_options(config)
                if security is None:
                    raise DeploymentControlError("image security selection cancelled")
                state["age_recipients_file"], state["minisign_secret_key"] = security
            state["device_path"] = path
            state["confirmation"] = phrase
            return LocalTargetApproval(path, description, phrase)

        def execute_job(job, tls_socket, approval):
            if job.transport == "multicast":
                operation = lambda progress: execute_multicast_restore(
                    job, tls_socket, approval,
                    server_identity=config.server_identity,
                    repository=config.repository,
                    trusted_server_public_key=config.trusted_server_public_key,
                    firewall=PXEFirewall(),
                    network_interface=state.get("multicast_interface"),
                    age_identity_file=config.age_identity_file,
                    progress_callback=progress,
                )
                return dialog_app._run_restore_gauge(
                    "Multicast image restore",
                    "Receiving image artifacts into private staging, verifying any signature and all digests, then restoring the locally approved target.",
                    operation,
                )
            compression = state.get("compression", "gzip")
            if compression == "none":
                level = None
            elif compression == "gzip":
                level = 6
            elif compression == "xz":
                level = 6
            elif compression == "zstd":
                level = 3
            elif compression == "lz4":
                level = 3
            else:
                level = None
            operation = lambda progress: execute_client_image_job(
                job, tls_socket, approval,
                server_identity=config.server_identity,
                repository=config.repository,
                trusted_server_public_key=config.trusted_server_public_key,
                local_minisign_secret_key=state.get("minisign_secret_key"),
                local_minisign_public_key=(
                    config.local_minisign_public_key
                    if state.get("minisign_secret_key") else None
                ),
                age_identity_file=config.age_identity_file,
                age_recipients_file=state.get("age_recipients_file"),
                encrypt_image=bool(state.get("age_recipients_file")),
                sign_image=bool(state.get("minisign_secret_key")),
                compression=compression,
                compression_level=level,
                progress_callback=progress,
            )
            if job.operation == "restore":
                return dialog_app._run_restore_gauge(
                    "Network image restore", "Receiving and verifying the image set, including any present signature, then restoring the selected target.",
                    operation,
                )
            return dialog_app._run_capture_gauge(
                "Network disk capture", "Capturing, optionally encrypting/signing and transferring the selected disk image.",
                operation,
            )

        job, success, detail = join_deployment(
            config.host, config.port, context,
            local_identity=config.local_identity,
            expected_server_identity=config.server_identity,
            mac_address=config.mac_address,
            job_id=job_id,
            prepare_local_target=prepare_local_target,
            execute_job=execute_job,
            timeout=120,
        )
        dialog_app._message(
            "Deployment succeeded" if success else "Deployment failed",
            f"Job: {job.job_id}\nOperation: {job.operation}\nImage: {job.image_id}\n\n{detail}",
        )
        return 0 if success else 1
    except Exception as exc:
        dialog_app._message("Client deployment failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(run_client_ui())

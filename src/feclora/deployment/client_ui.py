"""Dialog workflow for an authenticated Client save/restore job."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import socket
import subprocess
import sys
from typing import Any

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.managed_pki import (
    PKIError, certificate_expiry_days, create_client_csr, install_client_certificate,
)
from feclora.deployment.multicast_runtime import execute_multicast_restore
from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, join_deployment,
)
from feclora.deployment.runtime_config import (
    ClientRuntimeConfig, RuntimeConfigError, load_client_runtime_config,
)
from feclora.network.remote_clone_protocol import create_mutual_tls_context
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
    """Bootstrap a Client from a CSR response bundle without exporting its key."""
    choice = dialog_app._menu(
        "Client certificate setup",
        "The Client has no deployment identity yet. Prepare a CSR or install a Server-approved response bundle.",
        [
            ("prepare", "Prepare enrollment request (first step)"),
            ("complete", "Complete enrollment from Server response"),
            ("cancel", "Cancel"),
        ],
    )
    if choice in (None, "cancel"):
        return False
    pki_directory = "/etc/feclora/pki"
    if choice == "prepare":
        client_id = dialog_app._input(
            "Client identity",
            "Choose a short lowercase identifier (letters, digits and hyphens):",
        )
        if not client_id:
            return False
        export_directory = dialog_app._input(
            "Export enrollment request",
            "Path to an existing removable-media directory. Only the CSR will be copied there; the private key stays on this Client:",
        )
        if not export_directory:
            return False
        identity, _private_key, exported_csr = create_client_csr(
            pki_directory, export_directory, client_id,
        )
        dialog_app._message(
            "Enrollment request prepared",
            f"Identity: {identity}\nCSR: {exported_csr}\n\n"
            "Take the removable media to the Feclora Server and choose Trusted Clients → Approve Client CSR. "
            "Do not copy or export the private key. After the Server returns the signed certificate bundle, "
            "bring that media back and choose Complete enrollment.",
        )
        return False

    client_id = dialog_app._input("Client identity", "Enter the same lowercase identifier used when preparing the CSR:")
    if not client_id:
        return False
    host = dialog_app._input("Feclora Server address", "Enter the Server IPv4 address or hostname:")
    if not host:
        return False
    mac = dialog_app._input("Client MAC address", "Enter this Client's unicast MAC address:")
    if not mac:
        return False
    bundle = dialog_app._input(
        "Server response bundle",
        "Path to the removable-media directory containing feclora-<id>.crt, ca.crt and server.pub:",
    )
    if not bundle or not os.path.isdir(bundle) or os.path.islink(bundle):
        raise PKIError("Server response bundle must be an existing real directory")
    certificate = os.path.join(bundle, f"feclora-{client_id}.crt")
    ca_file = os.path.join(bundle, "ca.crt")
    server_public_key = os.path.join(bundle, "server.pub")
    age_recipients_bundle = os.path.join(bundle, "age-recipients.txt")
    local_key = os.path.join(pki_directory, f"client-{client_id}.key")
    if not os.path.isfile(local_key):
        raise PKIError("locally generated Client private key is missing; prepare the CSR on this Client first")
    ca_expected = dialog_app._input(
        "Verify Feclora CA fingerprint",
        "Enter the SHA-256 fingerprint displayed by the Server when its CA was created (hexadecimal, colons optional):",
    )
    if not ca_expected:
        return False
    installed = install_client_certificate(
        certificate, ca_file, local_key, pki_directory,
        f"URI:feclora-client-{client_id}", ca_expected,
    )
    if not os.path.isfile(server_public_key):
        raise PKIError("Server response bundle is missing server.pub")
    if not os.path.isfile(age_recipients_bundle):
        raise PKIError("Server response bundle is missing the age recipient inventory")
    server_fingerprint = _sha256_file(server_public_key)
    expected_server_key = dialog_app._input(
        "Verify Server image-signing key",
        "Compare this SHA-256 fingerprint with the one shown by the Server during CSR approval, then type it exactly:\n" + server_fingerprint,
    )
    if expected_server_key != server_fingerprint:
        raise PKIError("Server image-signing key fingerprint did not match")
    installed_server_key = os.path.join(pki_directory, "server.pub")
    shutil.copyfile(server_public_key, installed_server_key)
    os.chmod(installed_server_key, 0o644)
    installed_recipients = os.path.join(pki_directory, "age-recipients.txt")
    shutil.copyfile(age_recipients_bundle, installed_recipients)
    os.chmod(installed_recipients, 0o600)
    age_identity = os.path.join(pki_directory, f"client-{client_id}.age")
    if not os.path.isfile(age_identity):
        raise PKIError("locally generated age identity is missing; prepare enrollment on this Client first")
    os.chmod(age_identity, 0o600)
    repository = "/var/lib/feclora/images"
    os.makedirs(repository, mode=0o700, exist_ok=True)
    os.chmod(repository, 0o700)
    config = {
        "schema_version": 1,
        "host": host,
        "port": 9443,
        "local_identity": f"URI:feclora-client-{client_id}",
        "server_identity": "URI:feclora-server",
        "mac_address": mac.lower(),
        "ca_file": installed["ca_file"],
        "certificate_file": installed["certificate_file"],
        "private_key_file": installed["private_key_file"],
        "trusted_server_public_key": installed_server_key,
        "local_minisign_secret_key": None,
        "local_minisign_public_key": None,
        "age_identity_file": age_identity,
        "age_recipients_file": installed_recipients,
        "repository": repository,
    }
    _write_client_config(config_path, config)
    dialog_app._message(
        "Client enrollment complete",
        f"Client identity {config['local_identity']} is installed and trusted. This Client is configured for signed restore jobs. "
        "To enable Client-side image capture later, provision a separate minisign signing keypair and enroll its public key on the Server.",
    )
    return True

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
    dialog_app._message(
        "Renewal request prepared",
        f"Identity: {identity}\\nCSR: {exported}\\n\\n"
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
        expiry_days = certificate_expiry_days(config.certificate_file)
        expiry_label = (
            f"expires in {expiry_days} days" if expiry_days >= 0
            else f"expired {-expiry_days} days ago"
        )
        identity_action = dialog_app._menu(
            "Client identity",
            f"TLS certificate {expiry_label}. Renew it before expiry; private keys remain local.",
            [
                ("join", "Join deployment job"),
                ("renew", "Prepare certificate renewal request"),
                ("install", "Install Server-approved certificate response"),
                ("cancel", "Cancel"),
            ],
        )
        if identity_action in (None, "cancel"):
            return 0
        if identity_action == "renew":
            _prepare_client_renewal(config)
            return 0
        if identity_action == "install":
            _client_enrollment_wizard(config_path)
            return 0
        job_id = dialog_app._input(
            "Join deployment job",
            "Enter the job UUID shown by the Feclora Server operator:",
        )
        if job_id is None:
            return 0
        context = create_mutual_tls_context(
            "client", ca_file=config.ca_file,
            certificate_file=config.certificate_file,
            private_key_file=config.private_key_file,
        )
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
                state["multicast_interface"] = selected_interface
            if job.operation == "save" and not config.local_minisign_secret_key:
                raise DeploymentControlError("this Client has no enrolled minisign signing key and cannot create images")
            inventory = collect_inventory()
            target_kind = "partition" if job.target_type == "partition" else "disk"
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
                prompt = "This operation overwrites the selected partition. Type the exact confirmation phrase:"
            else:
                phrase = f"READ {path} TO {config.server_identity}"
                prompt = "This operation reads the selected whole disk to create a signed image. Type the exact confirmation phrase:"
            dialog_app._message("Selected local disk", dialog_app.device_details(selected))
            typed = dialog_app._input("Explicit local authorization", f"{prompt}\n\n{phrase}")
            if typed != phrase:
                raise DeploymentControlError("local typed confirmation did not match; no disk operation was started")
            description = " ".join(
                str(value) for value in (
                    selected.get("model"), selected.get("size_bytes"), selected.get("serial"),
                ) if value
            ) or "Selected local whole disk"
            if job.operation == "save":
                compression_choice = dialog_app._menu(
                    "Capture compression", "Choose whole-disk image compression.",
                    [("none", "None"), ("gzip", "gzip (balanced)"), ("xz", "xz (smaller, slower)")],
                )
                if compression_choice is None:
                    raise DeploymentControlError("capture compression selection cancelled")
                state["compression"] = compression_choice
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
                    "Receiving signed image artifacts into private staging, verifying them, then restoring the locally approved target.",
                    operation,
                )
            compression = state.get("compression", "gzip")
            if compression == "none":
                level = None
            elif compression == "gzip":
                level = 6
            else:
                level = 6
            operation = lambda progress: execute_client_image_job(
                job, tls_socket, approval,
                server_identity=config.server_identity,
                repository=config.repository,
                trusted_server_public_key=config.trusted_server_public_key,
                local_minisign_secret_key=config.local_minisign_secret_key,
                local_minisign_public_key=config.local_minisign_public_key,
                age_identity_file=config.age_identity_file,
                age_recipients_file=config.age_recipients_file,
                compression=compression,
                compression_level=level,
                progress_callback=progress,
            )
            if job.operation == "restore":
                return dialog_app._run_restore_gauge(
                    "Network image restore", "Receiving and verifying the signed image, then restoring the selected target.",
                    operation,
                )
            return dialog_app._run_capture_gauge(
                "Network disk capture", "Capturing, signing and transferring the selected disk image.",
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

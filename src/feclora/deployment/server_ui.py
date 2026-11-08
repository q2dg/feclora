"""Dialog workflow for one authenticated unicast Server deployment."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from feclora.deployment.control import DeploymentControlError, DeploymentControlServer
from feclora.deployment.coordinator import DeploymentCoordinator
from feclora.deployment.job import DeploymentJob
from feclora.deployment.journal import DeploymentJournal
from feclora.deployment.runtime_config import (
    RuntimeConfigError, ServerRuntimeConfig, load_server_runtime_config,
)
from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.ui import dialog_app


CONFIG_PATH = "/etc/feclora/deployment-server.json"


def _available_images(repository: str) -> list[tuple[str, ImageManifest]]:
    found = []
    for path in sorted(Path(repository).glob("*.manifest.json")):
        try:
            manifest = ImageManifest.from_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError):
            continue
        if os.path.isfile(str(path) + ".minisig"):
            found.append((path.name, manifest))
    return found


def _choose_job(config: ServerRuntimeConfig, interface: str) -> tuple[DeploymentJob, str | None, str]:
    operation = dialog_app._menu("Deployment operation", "Choose the one-client unicast operation.", [
        ("restore", "Restore a signed image to the Client disk"),
        ("save", "Capture the Client disk and store a signed image"),
    ])
    if operation is None:
        raise DeploymentControlError("job creation cancelled")
    manifest_path = None
    if operation == "restore":
        images = _available_images(config.repository)
        choices = [(manifest.image_id, f"{manifest.image_id} | {manifest.source_size_bytes:,} bytes")
                   for _filename, manifest in images]
        image_id = dialog_app._menu("Select signed image", "Only images with a detached signature are listed.", choices)
        if image_id is None:
            raise DeploymentControlError("image selection cancelled")
        selected = next((name for name, manifest in images if manifest.image_id == image_id), None)
        if selected is None:
            raise DeploymentControlError("selected image is no longer available")
        manifest_path = os.path.join(config.repository, selected)
    else:
        image_id = dialog_app._input("New image identifier", "Enter a unique image identifier:")
        if image_id is None:
            raise DeploymentControlError("image creation cancelled")
        if os.path.lexists(os.path.join(config.repository, image_id + ".manifest.json")):
            raise DeploymentControlError("an image with this identifier already exists")

    enrolled = [
        (identity, f"{identity} -> {mac}")
        for identity, mac in config.client_identity_to_mac.items()
    ]
    identity = dialog_app._menu("Enrolled Client", "Select exactly one enrolled certificate identity for this job.", enrolled)
    if identity is None:
        raise DeploymentControlError("Client selection cancelled")
    mac = config.client_identity_to_mac[identity]
    job = DeploymentJob.from_dict({
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "operation": operation,
        "image_id": image_id,
        "authorized_clients": [mac],
        "network_interface": interface,
        "transport": "unicast",
        "multicast_group": None,
        "multicast_port": None,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
    })
    return job, manifest_path, mac


def run_deployment_server_ui(
    interface: str,
    address: str,
    *,
    firewall: Any,
    config_path: str = CONFIG_PATH,
) -> int:
    """Load root-provisioned trust material and run one authenticated unicast job."""
    control = None
    try:
        config = load_server_runtime_config(config_path)
        if config.bind_address != address:
            raise RuntimeConfigError(
                "deployment control bind_address must equal the selected PXE interface address"
            )
        job, manifest_path, selected_mac = _choose_job(config, interface)
        context = create_mutual_tls_context(
            "server", ca_file=config.ca_file,
            certificate_file=config.certificate_file,
            private_key_file=config.private_key_file,
        )
        journal_dir = "/var/lib/feclora/deployments"
        os.makedirs(journal_dir, mode=0o700, exist_ok=True)
        journal_info = os.lstat(journal_dir)
        if (not os.path.isdir(journal_dir) or journal_info.st_uid != 0
                or journal_info.st_mode & 0o077):
            raise RuntimeConfigError("deployment journal directory must be root-owned with mode 0700")
        journal_path = os.path.join(journal_dir, job.job_id + ".jsonl")
        journal = DeploymentJournal(journal_path, job.job_id)
        coordinator = DeploymentCoordinator(job, event_sink=journal)
        control = DeploymentControlServer(
            coordinator, context,
            local_identity=config.local_identity,
            client_identity_to_mac=config.client_identity_to_mac,
            firewall=firewall,
            interface=interface,
        )
        bound_address, port = control.start(config.bind_address, config.port)
        dialog_app._message(
            "Authenticated deployment listener",
            f"Job: {job.job_id}\nOperation: {job.operation}\nImage: {job.image_id}\n"
            f"Authorized Client MAC: {selected_mac}\nControl endpoint: {bound_address}:{port}\nJournal: {journal_path}\n\n"
            "The listener requires TLS 1.3 mutual authentication. The Client must use "
            "its enrolled certificate and enter this job UUID. No image write starts "
            "until the Client selects its local disk, types the exact confirmation "
            "and the Server operator explicitly arms the job.",
        )
        while True:
            clients = coordinator.clients()
            ready = [item for item in clients if item.state.value == "ready"]
            state_text = "\n".join(
                f"{item.mac_address}: {item.state.value}" for item in clients
            ) or "No Client has connected yet."
            choice = dialog_app._menu(
                "Authenticated deployment",
                f"Job state: {coordinator.state.value}\n{state_text}\n\n"
                "Refresh to wait for the enrolled Client, or explicitly arm the job.",
                [
                    ("refresh", "Refresh Client readiness"),
                    ("arm", "ARM and execute the one-client job"),
                    ("stop", "Stop the control listener"),
                ],
            )
            if choice == "refresh":
                continue
            if choice == "stop" or choice is None:
                return 0
            if choice == "arm":
                if len(ready) != 1 or len(clients) != 1:
                    dialog_app._message(
                        "Client not ready",
                        "Exactly one authenticated Client must be READY before arming.",
                    )
                    continue
                trusted_key = (
                    config.server_minisign_public_key
                    if job.operation == "restore"
                    else config.client_minisign_public_keys[selected_mac]
                )
                results = control.run_one_client_job(
                    config.repository,
                    trusted_public_key=trusted_key,
                    manifest_path=manifest_path,
                )
                dialog_app._message(
                    "Deployment result",
                    f"Job state: {coordinator.state.value}\n"
                    + "\n".join(f"{mac}: {state}" for mac, state in results.items()),
                )
                return 0
    except Exception as exc:
        dialog_app._message("Deployment setup failed", str(exc))
        return 1
    finally:
        if control is not None:
            try:
                control.stop()
            except DeploymentControlError as exc:
                dialog_app._message("Control firewall cleanup warning", str(exc))

"""Dialog workflow for an authenticated Client save/restore job."""
from __future__ import annotations

from typing import Any

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, join_deployment,
)
from feclora.deployment.runtime_config import (
    ClientRuntimeConfig, RuntimeConfigError, load_client_runtime_config,
)
from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.storage.inventory import InventoryError, collect_inventory
from feclora.ui import dialog_app


CONFIG_PATH = "/etc/feclora/deployment-client.json"


def run_client_ui(*, config_path: str = CONFIG_PATH) -> int:
    """Join one Server job after local device selection and typed approval."""
    try:
        config = load_client_runtime_config(config_path)
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
            inventory = collect_inventory()
            selected = dialog_app._select_device(
                inventory, "disk", "Local deployment disk",
                "Select the whole disk for this job. Root, mounted or busy disks will be rejected before any write.",
            )
            if selected is None:
                raise DeploymentControlError("local disk selection cancelled")
            path = selected.get("path")
            if not isinstance(path, str):
                raise DeploymentControlError("selected disk has no stable device path")
            if job.operation == "restore":
                phrase = f"ERASE {path} FROM {config.server_identity}"
                prompt = "This operation overwrites the selected whole disk. Type the exact confirmation phrase:"
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
                compression=compression,
                compression_level=level,
                progress_callback=progress,
            )
            if job.operation == "restore":
                return dialog_app._run_restore_gauge(
                    "Network disk restore", "Receiving and verifying the signed image, then restoring the selected disk.",
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
    except (RuntimeConfigError, DeploymentControlError, InventoryError, OSError, ValueError) as exc:
        dialog_app._message("Client deployment failed", str(exc))
        return 1

"""Dialog workflow for one authenticated unicast Server deployment."""
from __future__ import annotations

import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

from feclora.deployment.control import DeploymentControlError, DeploymentControlServer
from feclora.deployment.coordinator import DeploymentCoordinator
from feclora.deployment.job import DeploymentJob
from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
from feclora.deployment.multicast_runtime import udpcast_config_for_job
from feclora.deployment.enrollment import (
    enroll_client_certificate, inspect_client_certificate,
    revoke_client_certificate,
)
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


def _choose_job(
    config: ServerRuntimeConfig, interface: str,
) -> tuple[DeploymentJob, str | None, list[str]]:
    transport = dialog_app._menu(
        "Deployment transport",
        "Choose authenticated unicast or one-to-many multicast restore.",
        [
            ("unicast", "Unicast (one Client; save or restore)"),
            ("multicast", "Multicast (multiple Clients; restore only)"),
        ],
    )
    if transport is None:
        raise DeploymentControlError("transport selection cancelled")
    operation_choices = (
        [("restore", "Restore a signed image to multiple Client disks")]
        if transport == "multicast" else
        [
            ("restore", "Restore a signed image to one Client disk"),
            ("save", "Capture one Client disk and store a signed image"),
        ]
    )
    operation = dialog_app._menu(
        "Deployment operation", "Choose the image operation.", operation_choices,
    )
    if operation is None:
        raise DeploymentControlError("job creation cancelled")
    manifest_path = None
    if operation == "restore":
        images = _available_images(config.repository)
        choices = [
            (manifest.image_id, f"{manifest.image_id} | {manifest.source_size_bytes:,} bytes")
            for _filename, manifest in images
        ]
        image_id = dialog_app._menu(
            "Select signed image", "Only images with a detached signature are listed.", choices,
        )
        if image_id is None:
            raise DeploymentControlError("image selection cancelled")
        selected_manifest = next(
            (name for name, manifest in images if manifest.image_id == image_id), None,
        )
        if selected_manifest is None:
            raise DeploymentControlError("selected image is no longer available")
        manifest_path = os.path.join(config.repository, selected_manifest)
    else:
        image_id = dialog_app._input("New image identifier", "Enter a unique image identifier:")
        if image_id is None:
            raise DeploymentControlError("image creation cancelled")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
            raise DeploymentControlError("image identifier must be a safe basename of at most 128 characters")
        if os.path.lexists(os.path.join(config.repository, image_id + ".manifest.json")):
            raise DeploymentControlError("an image with this identifier already exists")

    enrolled = [
        (identity, f"{identity} -> {mac}")
        for identity, mac in sorted(config.client_identity_to_mac.items())
        if operation != "save" or mac in config.client_minisign_public_keys
    ]
    if transport == "unicast":
        identity = dialog_app._menu(
            "Enrolled Client", "Select exactly one enrolled certificate identity.", enrolled,
        )
        if identity is None:
            raise DeploymentControlError("Client selection cancelled")
        selected_macs = [config.client_identity_to_mac[identity]]
    else:
        args = ["--title", "Enrolled Clients", "--checklist", 
                "Select at least two authenticated Clients for this multicast job.",
                "22", "92", "12", "--separate-output"]
        for identity, label in enrolled:
            args.extend([identity, label, "off"])
        result = dialog_app._dialog(args)
        if result.returncode != 0:
            raise DeploymentControlError("multicast Client selection cancelled")
        selected_identities = [item.strip() for item in result.stdout.splitlines() if item.strip()]
        selected_macs = [config.client_identity_to_mac[item] for item in selected_identities
                         if item in config.client_identity_to_mac]
        if len(selected_macs) < 2 or len(selected_macs) != len(selected_identities):
            raise DeploymentControlError("multicast restore requires at least two valid enrolled Clients")

    group = None
    port = None
    if transport == "multicast":
        group = dialog_app._input(
            "Multicast data group",
            "Enter an administratively scoped IPv4 multicast group (recommended 239.0.0.0/8):",
            "239.10.10.1",
        )
        port_text = dialog_app._input(
            "UDPcast port base",
            "Enter an even UDP port base between 1024 and 65534:",
            "9000",
        )
        if group is None or port_text is None:
            raise DeploymentControlError("multicast network configuration cancelled")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise DeploymentControlError("multicast port base must be an integer") from exc

    job = DeploymentJob.from_dict({
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "operation": operation,
        "image_id": image_id,
        "authorized_clients": selected_macs,
        "network_interface": interface,
        "transport": transport,
        "multicast_group": group,
        "multicast_port": port,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
    })
    return job, manifest_path, selected_macs


def _journal_directory() -> str:
    path = "/var/lib/feclora/deployments"
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RuntimeConfigError("deployment journal directory must be root-owned with mode 0700")
    return path


def _review_previous_journals(directory: str) -> None:
    summaries = []
    interrupted: list[tuple[str, str]] = []
    for path in sorted(Path(directory).glob("*.jsonl"))[-20:]:
        try:
            journal = DeploymentJournal.inspect(path)
            report = journal.recovery_report()
            state = str(report["job_state"])
            if report["interrupted"]:
                status = "INTERRUPTED — manual disk inspection required"
                interrupted.append((str(path), str(report["job_id"])))
            elif report.get("operator_reconciled"):
                status = "FAILED — operator inspected/reconciled"
            else:
                status = state.upper()
            clients = ", ".join(
                str(mac) + "=" + str(item["state"])
                for mac, item in sorted(report["clients"].items())
            ) or "no clients recorded"
            summaries.append(
                str(report["job_id"]) + ": " + status +
                " (events: " + str(report["event_count"]) + "; " + clients + ")"
            )
        except Exception as exc:
            raise RuntimeConfigError(
                "deployment journal " + path.name + " is corrupt or unsafe; refusing new jobs: " + str(exc)
            ) from exc
    for journal_path, job_id in interrupted:
        choice = dialog_app._menu(
            "Interrupted deployment recovery",
            f"Job {job_id} was interrupted. Feclora has replayed its verified journal, "
            "but deliberately has not recreated a session or resumed disk I/O. "
            "Inspect the source and every destination disk on every listed Client. "
            "Only acknowledge after checking actual on-disk state.",
            [
                ("reconcile", "I inspected every target; record operator reconciliation"),
                ("later", "Leave this journal awaiting inspection"),
            ],
        )
        if choice != "reconcile":
            continue
        confirmation = dialog_app._input(
            "Confirm manual recovery",
            f"Type exactly: RECONCILE {job_id}",
        )
        if confirmation is None:
            continue
        try:
            report = DeploymentJournal.inspect(journal_path).reconcile_after_operator_inspection(
                confirmation
            )
            if not report.get("operator_reconciled"):
                raise DeploymentJournalError("operator reconciliation was not persisted")
            summaries.append(
                f"{job_id}: FAILED — operator inspected/reconciled; no restart or disk I/O performed"
            )
        except Exception as exc:
            raise RuntimeConfigError(
                "could not record operator reconciliation for " + job_id + ": " + str(exc)
            ) from exc
    if summaries:
        dialog_app._message(
            "Previous deployment journal review",
            "Journal events and per-client states were replayed from verified hash chains. "
            "Interrupted jobs are never resumed automatically. An operator reconciliation "
            "record means only that you asserted that every target was manually inspected; "
            "it does not mean the deployment succeeded or that partial writes were rolled back.\n\n"
            + "\n".join(summaries),
        )

def _manage_client_enrollment(config_path: str) -> None:
    """Offer explicit certificate enrollment, rotation and revocation before job setup."""
    config = load_server_runtime_config(config_path)
    choice = dialog_app._menu(
        "Client certificate trust",
        "Manage the Server's allowlist of TLS Client certificate identities. "
        "Private keys are never imported or generated here; provision them out of band.",
        [
            ("continue", "Continue to deployment"),
            ("enroll", "Enroll or rotate a Client certificate"),
            ("revoke", "Revoke an enrolled Client certificate"),
        ],
    )
    if choice in (None, "continue"):
        return
    if choice == "enroll":
        certificate = dialog_app._input(
            "Client certificate",
            "Absolute path to the root-owned PEM Client certificate (not its private key):",
        )
        if not certificate:
            return
        identity = inspect_client_certificate(certificate, config.ca_file)
        mac = dialog_app._input(
            "Client MAC address",
            "Enter the unicast MAC address authorized for this certificate:",
        )
        if not mac:
            return
        public_key = dialog_app._input(
            "Client image-signing key",
            "Optional root-owned minisign PUBLIC key path; leave blank for restore-only Client:",
        )
        public_key = public_key or None
        dialog_app._message(
            "Review Client enrollment",
            f"Certificate identity: {identity}\nMAC allowlist entry: {mac.lower()}\n"
            f"Image signing key: {public_key or 'none (restore-only)'}\n\n"
            "The certificate chain and TLS client purpose have been verified against "
            "the configured CA. Re-enrolling the same MAC rotates its certificate identity.",
        )
        confirmation = dialog_app._input(
            "Confirm Client enrollment",
            f"Type exactly: ENROLL {identity} {mac.lower()}",
        )
        if confirmation is None:
            return
        enrolled = enroll_client_certificate(
            config_path, certificate, mac,
            minisign_public_key=public_key, confirmation=confirmation,
        )
        dialog_app._message("Client enrolled", f"Enrolled certificate identity: {enrolled}")
        return
    selected = dialog_app._menu(
        "Revoke Client certificate",
        "Select the certificate identity to remove. Its associated minisign public key is also removed.",
        [(identity, f"{identity} -> {mac}") for identity, mac in config.client_identity_to_mac.items()],
    )
    if selected is None:
        return
    confirmation = dialog_app._input(
        "Confirm Client revocation",
        f"Type exactly: REVOKE {selected}",
    )
    if confirmation is None:
        return
    mac = revoke_client_certificate(config_path, selected, confirmation=confirmation)
    dialog_app._message(
        "Client revoked",
        f"Revoked {selected} and removed image-signing trust for {mac}. "
        "The Client must reconnect with a newly enrolled certificate.",
    )


def run_deployment_server_ui(
    interface: str,
    address: str,
    *,
    firewall: Any,
    config_path: str = CONFIG_PATH,
) -> int:
    """Load root-provisioned trust material and run one authenticated deployment job."""
    control = None
    try:
        _manage_client_enrollment(config_path)
        config = load_server_runtime_config(config_path)
        if config.bind_address != address:
            raise RuntimeConfigError(
                "deployment control bind_address must equal the selected PXE interface address"
            )
        journal_dir = _journal_directory()
        _review_previous_journals(journal_dir)
        job, manifest_path, selected_macs = _choose_job(config, interface)
        multicast_config = None
        if job.transport == "multicast":
            multicast_config = udpcast_config_for_job(
                job, min_receivers=len(selected_macs),
            )
            dialog_app._message(
                "Multicast network preflight",
                f"Data group: {multicast_config.data_group}\n"
                f"Rendezvous group: {multicast_config.rendezvous_group}\n"
                f"UDP ports: {multicast_config.portbase} and {multicast_config.portbase + 1}\n"
                f"Interface: {multicast_config.interface}\nTTL: 1\n"
                f"Required receivers: {multicast_config.min_receivers}\n\n"
                "All selected Clients must be on the same multicast-enabled VLAN/L2 segment. "
                "Ensure switch IGMP snooping has a working querier, multicast is not filtered "
                "by Wi-Fi/client isolation, and the selected interface is correct. "
                "Cross-VLAN multicast routing is not supported by this TTL=1 profile. "
                "Feclora will temporarily open only the two UDPcast ports on this interface.",
            )
            confirmation = dialog_app._input(
                "Confirm multicast network readiness",
                f"Type exactly: MULTICAST READY {job.job_id}",
            )
            if confirmation != f"MULTICAST READY {job.job_id}":
                raise DeploymentControlError("multicast network preflight was not confirmed")
        context = create_mutual_tls_context(
            "server", ca_file=config.ca_file,
            certificate_file=config.certificate_file,
            private_key_file=config.private_key_file,
        )
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
        selected_mac_text = ", ".join(selected_macs)
        dialog_app._message(
            "Authenticated deployment listener",
            f"Job: {job.job_id}\nOperation: {job.operation}\nImage: {job.image_id}\n"
            f"Authorized Client MACs: {selected_mac_text}\nTransport: {job.transport}\nControl endpoint: {bound_address}:{port}\nJournal: {journal_path}\n\n"
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
            if control.listener_errors:
                state_text += "\nRecent listener errors: " + " | ".join(control.listener_errors[-3:])
            choice = dialog_app._menu(
                "Authenticated deployment",
                f"Job state: {coordinator.state.value}\n{state_text}\n\n"
                f"Refresh to wait for {len(selected_macs)} enrolled Client(s), or explicitly arm the job.",
                [
                    ("refresh", "Refresh Client readiness"),
                    ("arm", "ARM and execute the deployment job"),
                    ("stop", "Stop the control listener"),
                ],
            )
            if choice == "refresh":
                continue
            if choice == "stop" or choice is None:
                return 0
            if choice == "arm":
                expected_clients = len(job.authorized_clients)
                if len(ready) != expected_clients or len(clients) != expected_clients:
                    dialog_app._message(
                        "Clients not ready",
                        f"All {expected_clients} authorized Client(s) must be authenticated and READY before arming.",
                    )
                    continue
                if job.transport == "multicast":
                    results = control.run_multicast_restore_job(
                        config.repository,
                        manifest_path,
                        trusted_public_key=config.server_minisign_public_key,
                        udpcast_config=multicast_config,
                    )
                else:
                    selected_mac = selected_macs[0]
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

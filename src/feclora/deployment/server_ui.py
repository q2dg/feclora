"""Dialog workflows for unicast and multi-client multicast deployments."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any

from feclora.deployment.control import DeploymentControlError, DeploymentControlServer
from feclora.deployment.coordinator import DeploymentCoordinator
from feclora.deployment.job import DeploymentJob
from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
from feclora.deployment.multicast_runtime import udpcast_config_for_job
from feclora.deployment.bootstrap import ensure_server_deployment_config
from feclora.deployment.managed_pki import ca_fingerprint

from feclora.deployment.runtime_config import (
    RuntimeConfigError, ServerRuntimeConfig, load_server_runtime_config,
)
from feclora.network.remote_clone_protocol import create_tls_context
from feclora.network.multicast_preflight import inspect_multicast_interface
from feclora.network.pxe_config import PXENetworkConfig
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import collect_inventory
from feclora.storage.source_safety import check_capture_source_safe, SourceSafetyError
from feclora.ui import dialog_app


CONFIG_PATH = "/etc/feclora/deployment-server.json"


def _available_images(
    repository: str, trusted_public_key: str | None,
) -> list[tuple[str, ImageManifest]]:
    found = []
    for path in sorted(Path(repository).glob("*.manifest.json")):
        try:
            manifest = ImageManifest.from_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError):
            continue
        signature_present = os.path.lexists(str(path) + ".minisig")
        if not signature_present or trusted_public_key:
            found.append((path.name, manifest))
    return found


def _flatten_devices(devices: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if not isinstance(devices, list):
        return flattened
    for item in devices:
        if not isinstance(item, dict):
            continue
        flattened.append(item)
        flattened.extend(_flatten_devices(item.get("children")))
    return flattened


def _choose_job(
    config: ServerRuntimeConfig, interface: str,
) -> tuple[DeploymentJob, str | None, list[str]]:
    transport = dialog_app._menu(
        "Deployment transport",
        "Choose unicast or one-to-many multicast restore. Multicast supports whole-disk and partition images, including raw LUKS2 containers.",
        [
            ("unicast", "Unicast (one Client; save or restore)"),
            ("multicast", "Multicast (multiple Clients; restore only)"),
        ],
    )
    if transport is None:
        raise DeploymentControlError("transport selection cancelled")
    operation_choices = (
        [("restore", "Restore a disk or partition image to multiple Clients")]
        if transport == "multicast" else
        [
            ("restore", "Restore an image to one Client disk or partition"),
            ("save", "Capture one Client disk and store an image"),
            ("clone", "Clone a Server disk or partition directly to one Client"),
        ]
    )
    operation = dialog_app._menu(
        "Deployment operation", "Choose the image operation.", operation_choices,
    )
    if operation is None:
        raise DeploymentControlError("job creation cancelled")
    manifest_path = None
    if operation == "restore":
        images = [
            entry for entry in _available_images(config.repository, config.server_minisign_public_key)
            if entry[1].image_type in {"disk", "partition"}
        ]
        choices = [
            (manifest.image_id, f"{manifest.image_id} | {manifest.image_type} | {manifest.source_size_bytes:,} bytes")
            for _filename, manifest in images
        ]
        image_id = dialog_app._menu(
            "Select image", "Signed images are listed only when a trusted Server verification key is configured.", choices,
        )
        if image_id is None:
            raise DeploymentControlError("image selection cancelled")
        selected_entry = next(
            ((name, manifest) for name, manifest in images if manifest.image_id == image_id), None,
        )
        selected_manifest = selected_entry[0] if selected_entry else None
        target_type = selected_entry[1].image_type if selected_entry else "disk"
        if selected_manifest is None:
            raise DeploymentControlError("selected image is no longer available")
        manifest_path = os.path.join(config.repository, selected_manifest)
    elif operation == "clone":
        target_type = dialog_app._menu(
            "Clone source type", "Choose the Server-local source block-device type.",
            [("disk", "Whole disk"), ("partition", "Partition")],
        )
        if target_type is None:
            raise DeploymentControlError("clone source type selection cancelled")
        inventory = collect_inventory()
        expected_type = "disk" if target_type == "disk" else "part"
        sources = [
            item for item in _flatten_devices(inventory.get("devices", []))
            if item.get("type") == expected_type and item.get("read_only") is True
            and isinstance(item.get("path"), str)
        ]
        if not sources:
            raise DeploymentControlError(
                f"no read-only Server {target_type} source is available for remote cloning"
            )
        source_device = dialog_app._menu(
            "Server clone source",
            "Choose a source already marked read-only. Feclora will also check geometry and in-use state.",
            [(item["path"], f'{item["path"]} | {item.get("model") or expected_type} | {item.get("size_bytes", "?")} bytes') for item in sources],
        )
        if source_device is None:
            raise DeploymentControlError("clone source selection cancelled")
        try:
            check_capture_source_safe(source_device)
        except (SourceSafetyError, OSError) as exc:
            raise DeploymentControlError(f"clone source is unsafe or in use: {exc}") from exc
        image_id = None
    else:
        target_type = "disk"
        image_id = dialog_app._input("New image identifier", "Enter a unique image identifier:")
        if image_id is None:
            raise DeploymentControlError("image creation cancelled")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
            raise DeploymentControlError("image identifier must be a safe basename of at most 128 characters")
        if os.path.lexists(os.path.join(config.repository, image_id + ".manifest.json")):
            raise DeploymentControlError("an image with this identifier already exists")

    mac_text = dialog_app._input(
        "Client MAC addresses",
        "Enter one unicast MAC address per line. No Client certificate enrollment or authentication is used:",
    )
    if mac_text is None:
        raise DeploymentControlError("Client selection cancelled")
    selected_macs = [item.strip().lower() for item in mac_text.replace(",", "\\n").splitlines() if item.strip()]
    if (not selected_macs or len(selected_macs) != len(set(selected_macs))
            or any(not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", item) for item in selected_macs)):
        raise DeploymentControlError("Client MAC list is empty, duplicated or malformed")
    if transport == "unicast" and len(selected_macs) != 1:
        raise DeploymentControlError("unicast jobs require exactly one Client MAC")
    if transport == "multicast" and len(selected_macs) < 2:
        raise DeploymentControlError("multicast restore requires at least two Client MAC addresses")

    target_bindings: dict[str, dict[str, str | None]] = {}
    if operation == "restore" and target_type == "disk":
        bind_choice = dialog_app._menu(
            "Stable Client target binding",
            "Optional for this Remote jobs workflow. Bind each selected Client to its physical target by WWN and/or serial; transient /dev names are never used as identity.",
            [("bind", "Bind stable target identity for every selected Client"),
             ("skip", "Keep interactive local target selection")],
        )
        if bind_choice is None:
            raise DeploymentControlError("stable target-binding choice was cancelled")
        if bind_choice not in {"bind", "skip"}:
            raise DeploymentControlError("stable target-binding choice is invalid")
        if bind_choice == "bind":
            for mac in selected_macs:
                wwn = dialog_app._input(
                    "Client target WWN",
                    f"Enter the expected target WWN for Client {mac}; leave blank only if unavailable:",
                )
                if wwn is None:
                    raise DeploymentControlError("stable target binding was cancelled")
                serial = dialog_app._input(
                    "Client target serial number",
                    f"Enter the expected target serial for Client {mac}; leave blank only if unavailable:",
                )
                if serial is None:
                    raise DeploymentControlError("stable target binding was cancelled")
                wwn = wwn.strip() or None
                serial = serial.strip() or None
                if wwn is None and serial is None:
                    raise DeploymentControlError(
                        f"Client {mac} target binding requires a WWN, serial number, or both"
                    )
                target_bindings[mac] = {"wwn": wwn, "serial": serial}

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
        "target_type": target_type,
        **({"source_device": source_device} if operation == "clone" else {}),
        "authorized_clients": selected_macs,
        "network_interface": interface,
        "transport": transport,
        "multicast_group": group,
        "multicast_port": port,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
        **({"target_bindings": target_bindings} if target_bindings else {}),
    })
    return job, manifest_path, selected_macs


def _run_unicast_job(
    control: DeploymentControlServer,
    config: ServerRuntimeConfig,
    job: DeploymentJob,
    selected_mac: str,
    manifest_path: str | None,
) -> dict[str, str]:
    """Dispatch the selected unicast operation to its matching runtime."""
    if job.operation == "clone":
        return control.run_remote_clone_job()
    trusted_key = (
        config.server_minisign_public_key
        if job.operation == "restore"
        else config.client_minisign_public_keys.get(selected_mac)
    )
    return control.run_one_client_job(
        config.repository,
        trusted_public_key=trusted_key,
        manifest_path=manifest_path,
    )


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
    for path in sorted(Path(directory).glob("*.jsonl")):
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
    pending = [
        job_id for journal_path, job_id in interrupted
        if DeploymentJournal.inspect(journal_path).recovery_report()["interrupted"]
    ]
    if pending:
        raise RuntimeConfigError(
            "previous deployment(s) still require manual disk inspection and explicit reconciliation; "
            "refusing to arm a new job: " + ", ".join(pending)
        )
    if summaries:
        dialog_app._message(
            "Previous deployment journal review",
            "Journal events and per-client states were replayed from verified hash chains. "
            "Interrupted jobs are never resumed automatically. An operator reconciliation "
            "record means only that you asserted that every target was manually inspected; "
            "it does not mean the deployment succeeded or that partial writes were rolled back.\n\n"
            + "\n".join(summaries),
        )

def run_deployment_server_ui(
    interface: str,
    address: str,
    *,
    firewall: Any,
    config_path: str = CONFIG_PATH,
    pxe_config: PXENetworkConfig | None = None,
) -> int:
    """Load root-provisioned trust material and run one deployment job without Client authentication."""
    control = None
    try:
        created = ensure_server_deployment_config(address, config_path=config_path)
        config = load_server_runtime_config(config_path)
        if created:
            fingerprint = ca_fingerprint(config.ca_file)
            dialog_app._message(
                "Feclora deployment CA created",
                "A local deployment CA and Server identity have been created. Record and verify this SHA-256 fingerprint; install the CA certificate and Server identity on each Client:\n\n"
                + fingerprint + "\n\nThe CA private key stays on this Server. Back it up encrypted and offline. "
                "Clients do not present certificates or authenticate individually.",
            )
        if config.bind_address != address:
            raise RuntimeConfigError(
                "deployment control bind_address must equal the selected PXE interface address"
            )
        journal_dir = _journal_directory()
        _review_previous_journals(journal_dir)
        if pxe_config is not None:
            pxe_config.validated()
            if pxe_config.address != address or pxe_config.interface != interface:
                raise DeploymentControlError("PXE boot profile does not match the active deployment interface/address")
        job, manifest_path, selected_macs = _choose_job(config, interface)
        multicast_config = None
        if job.transport == "multicast":
            multicast_config = udpcast_config_for_job(
                job, min_receivers=len(selected_macs),
            )
            preflight = inspect_multicast_interface(
                multicast_config.interface, multicast_config.data_group, role="sender",
            )
            dialog_app._message(
                "Local multicast preflight",
                f"Interface: {preflight.interface} ({preflight.ipv4_address})\nKernel route: {preflight.route_interface}\n\n"
                + "\n".join(preflight.warnings),
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
                "Age encryption is optional and should be enabled when artifact confidentiality is required. The Server-authenticated TLS control session protects the manifest in transit; any detached signature is additionally checked when present, and every received artifact is checked against its manifest digest. UDPcast itself does not encrypt or authenticate datagrams, so an on-path attacker can still observe metadata or cause denial of service. "
                "Feclora will temporarily open only the two UDPcast ports and IGMP on this interface.",
            )
            confirmation = dialog_app._input(
                "Confirm multicast network readiness",
                f"Type exactly: MULTICAST READY {job.job_id}",
            )
            if confirmation != f"MULTICAST READY {job.job_id}":
                raise DeploymentControlError("multicast network preflight was not confirmed")
        context = create_tls_context(
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
            firewall=firewall,
            interface=interface,
        )
        bound_address, port = control.start(config.bind_address, config.port)
        selected_mac_text = ", ".join(selected_macs)
        dialog_app._message(
            "Deployment listener",
            f"Job: {job.job_id}\nOperation: {job.operation}\nImage: {job.image_id}\n"
            f"Selected Client MACs: {selected_mac_text}\nTransport: {job.transport}\nControl endpoint: {bound_address}:{port}\nJournal: {journal_path}\n"
            + "\n\nThe listener uses TLS with Server-certificate verification only; Clients present no certificate and have no individual identity. "
            "Each selected Client enters this job UUID, selects its local target and types the exact confirmation. "
            "For all jobs, the Server operator explicitly arms the job before any image write.",
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
                "Deployment job",
                f"Job state: {coordinator.state.value}\n{state_text}\n\n"
                f"Refresh to wait for {len(selected_macs)} selected Client(s), or explicitly arm the job.",
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
                        f"All {expected_clients} selected Client(s) must be READY before arming.",
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
                    results = _run_unicast_job(
                        control, config, job, selected_macs[0], manifest_path,
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

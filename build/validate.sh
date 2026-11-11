#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
errors=0
fail() { printf 'ERROR: %s\n' "$*" >&2; errors=$((errors + 1)); }

for file in "$ROOT_DIR/build/build-iso.sh" "$ROOT_DIR/build/preflight.sh" "$ROOT_DIR/build/install-host-deps.sh" "$ROOT_DIR/kickstart/feclora-live.ks" "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/src/feclora/storage/inventory.py" "$ROOT_DIR/src/feclora/storage/partition_image_capture.py" "$ROOT_DIR/tests/test_partition_image_capture.py" "$ROOT_DIR/src/feclora/storage/capture.py" "$ROOT_DIR/tests/test_capture.py" "$ROOT_DIR/src/feclora/storage/capture_plan.py" "$ROOT_DIR/tests/test_capture_plan.py" "$ROOT_DIR/src/feclora/storage/image_manifest.py" "$ROOT_DIR/tests/test_image_manifest.py" "$ROOT_DIR/src/feclora/storage/volume_metadata.py" "$ROOT_DIR/tests/test_volume_metadata.py" "$ROOT_DIR/src/feclora/storage/volume_topology.py" "$ROOT_DIR/tests/test_volume_topology.py" "$ROOT_DIR/src/feclora/storage/topology_graph.py" "$ROOT_DIR/tests/test_storage_topology_graph.py" "$ROOT_DIR/src/feclora/storage/btrfs_inventory.py" "$ROOT_DIR/tests/test_btrfs_inventory.py" "$ROOT_DIR/src/feclora/storage/stratis_inventory.py" "$ROOT_DIR/tests/test_stratis_inventory.py" "$ROOT_DIR/src/feclora/network/interface_discovery.py" "$ROOT_DIR/tests/test_interface_discovery.py" "$ROOT_DIR/src/feclora/network/pxe_config.py" "$ROOT_DIR/src/feclora/network/pxe_preflight.py" "$ROOT_DIR/tests/test_pxe_preflight.py" "$ROOT_DIR/src/feclora/network/pxe_service.py" "$ROOT_DIR/tests/test_pxe_service.py" "$ROOT_DIR/src/feclora/network/firewall.py" "$ROOT_DIR/tests/test_firewall.py" "$ROOT_DIR/src/feclora/network/boot_assets.py" "$ROOT_DIR/tests/test_boot_assets.py" "$ROOT_DIR/src/feclora/network/boot_tree.py" "$ROOT_DIR/tests/test_boot_tree.py" "$ROOT_DIR/src/feclora/network/pxe_boot_request.py" "$ROOT_DIR/tests/test_pxe_boot_request.py" "$ROOT_DIR/src/feclora/network/pxe_boot.py" "$ROOT_DIR/tests/test_pxe_boot.py" "$ROOT_DIR/src/feclora/network/server_mode.py" "$ROOT_DIR/src/feclora/deployment/control.py" "$ROOT_DIR/src/feclora/deployment/artifact_transfer.py" "$ROOT_DIR/src/feclora/deployment/client_runtime.py" "$ROOT_DIR/src/feclora/deployment/runtime_config.py" "$ROOT_DIR/src/feclora/deployment/journal.py" "$ROOT_DIR/src/feclora/deployment/service.py" "$ROOT_DIR/src/feclora/deployment/client_service.py" "$ROOT_DIR/src/feclora/data/feclora-deployment@.service" "$ROOT_DIR/src/feclora/data/feclora-client@.service" "$ROOT_DIR/tests/test_deployment_service.py" "$ROOT_DIR/tests/test_client_service.py" "$ROOT_DIR/src/feclora/deployment/server_ui.py" "$ROOT_DIR/src/feclora/deployment/client_ui.py" "$ROOT_DIR/tests/test_deployment_control.py" "$ROOT_DIR/tests/test_artifact_transfer.py" "$ROOT_DIR/tests/test_client_runtime.py" "$ROOT_DIR/tests/test_runtime_config.py" "$ROOT_DIR/tests/test_deployment_journal.py" "$ROOT_DIR/tests/vm/README.md" "$ROOT_DIR/tests/vm/run-pxe-matrix.sh" "$ROOT_DIR/tests/test_server_mode.py" "$ROOT_DIR/tests/test_pxe_config.py" "$ROOT_DIR/src/feclora/storage/restore_profile.py" "$ROOT_DIR/src/feclora/storage/profile_executor.py" "$ROOT_DIR/tests/test_logical_volume_restore.py" "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" "$ROOT_DIR/src/feclora/data/feclora-restore-profile.service" "$ROOT_DIR/src/feclora/webapi.py" "$ROOT_DIR/src/feclora/kiosk_bootstrap.py" "$ROOT_DIR/tests/test_kiosk_bootstrap.py" "$ROOT_DIR/src/feclora/data/feclora-cockpit-certificate" "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" "$ROOT_DIR/src/feclora/data/feclora-kiosk-bootstrap-ready" "$ROOT_DIR/src/feclora/data/feclora-cockpit-certificate.service" "$ROOT_DIR/src/feclora/data/feclora-kiosk-bootstrap.service" "$ROOT_DIR/src/feclora/data/feclora-kiosk.service" "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" "$ROOT_DIR/src/feclora/storage/local_operations.py" "$ROOT_DIR/src/feclora/storage/local_operation_service.py" "$ROOT_DIR/src/feclora/data/feclora-local-operation@.service" "$ROOT_DIR/src/feclora/data/feclora-local-operation-recovery.service" "$ROOT_DIR/tests/test_webapi.py" "$ROOT_DIR/tests/test_bootstrap.py" "$ROOT_DIR/tests/test_local_operations.py" "$ROOT_DIR/tests/test_local_operation_service.py" "$ROOT_DIR/webui/package.json" "$ROOT_DIR/webui/src/App.jsx" "$ROOT_DIR/webui/src/api.js" "$ROOT_DIR/build/build-webui.sh" "$ROOT_DIR/docs/COCKPIT.md" "$ROOT_DIR/build/README.md"; do
  [[ -f "$file" ]] || fail "Required project file is missing: $file"
done

if [[ -f "$ROOT_DIR/build/README.md" ]]; then
  grep -q 'Fedora 45' "$ROOT_DIR/build/README.md" || fail "Build README does not identify Fedora 45 as the current baseline."
  if grep -Eiq 'Fedora 43|F43|fc43|fedora-43' "$ROOT_DIR/build/README.md"; then
    fail "Build README still contains a stale Fedora 43 baseline reference."
  fi
fi

if [[ -f "$ROOT_DIR/README.md" ]]; then
  grep -q 'Fedora Linux 45' "$ROOT_DIR/README.md" || fail "README does not identify Fedora Linux 45 as the current project baseline."
  if grep -Eiq 'Fedora 43|F43|fc43|fedora-43' "$ROOT_DIR/README.md"; then
    fail "README still contains a stale Fedora 43 baseline reference."
  fi
fi

if [[ -f "$ROOT_DIR/kickstart/feclora-live.ks" ]]; then
  grep -q '^#version=F45$' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not declare Fedora 45 (#version=F45)."
  grep -q '^part / ' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not define a root partition."
  grep -q '^%post --nochroot --erroronfail$' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not copy the app payload outside the chroot."
  grep -q 'APP_SOURCE=/run/install/repo/feclora-app/src/feclora' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart payload path does not match the mkksiso staging directory."
  grep -q 'enable cockpit.socket' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not enable Cockpit socket activation."
  grep -q 'usr/libexec/feclora/cockpit-api' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the Cockpit API helper."
  grep -q 'usr/local/bin/feclora-restore-profile' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the unattended restore profile launcher."
  grep -q 'feclora-restore-profile.service' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the opt-in unattended restore service."
fi

if [[ -f "$ROOT_DIR/build/build-iso.sh" ]]; then
  grep -Fq "bash \"\${ROOT_DIR}/build/preflight.sh\"" "$ROOT_DIR/build/build-iso.sh" || fail "Build script must run host preflight before staging the ISO."
  grep -q -- '--make-iso' "$ROOT_DIR/build/build-iso.sh" || fail "Build script does not request ISO output."
  grep -Fq "mkksiso --add \"\${APP_STAGE}\" \"\${KS_FILE}\" \"\${INSTALL_ISO}\" \"\${AUGMENTED_ISO}\"" "$ROOT_DIR/build/build-iso.sh" || fail "mkksiso must receive the app payload, Kickstart, input ISO and output ISO in that order."
  if grep -Eq '^[[:space:]]+--no-virt([[:space:]]|$)' "$ROOT_DIR/build/build-iso.sh"; then
    fail "Unsafe --no-virt mode must not be enabled by the default build."
  fi
fi

if [[ -f "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" ]]; then
  bash -n "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" || fail "Unattended restore environment wrapper has invalid Bash syntax."
fi

if ! grep -q 'network_interfaces|' "$ROOT_DIR/kickstart/feclora-live.ks" \
   || ! grep -q 'bootstrap_server|' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow the Server identity bootstrap actions."
fi
if ! grep -q '"network_interfaces"' "$ROOT_DIR/webui/src/api.js" \
   || ! grep -q '"bootstrap_server"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow the Server identity bootstrap actions."
fi
if ! grep -q 'def _bootstrap_server' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing the Server identity bootstrap implementation."
fi
if ! grep -q 'local-operation-recovery.service' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart does not install local operation recovery."
fi
if ! grep -q 'enable feclora-local-operation-recovery.service' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart does not enable boot-time local operation recovery."
fi
if ! grep -q 'submit_local_operation|local_operation_status|local_operations' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Cockpit API wrapper does not allow durable local operation actions."
fi
if ! grep -q 'def _submit_local_operation' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit API is missing durable local operation submission."
fi
if ! grep -q 'cancel_local_operation' "$ROOT_DIR/kickstart/feclora-live.ks" \
   || ! grep -q '"cancel_local_operation"' "$ROOT_DIR/webui/src/api.js" \
   || ! grep -q 'def _cancel_local_operation' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit local operation cancellation is not wired through the Live wrapper, client and backend."
fi
if ! grep -q 'def _validate_pxe_profile' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing PXE profile preflight."
fi
if ! grep -q '"validate_pxe_profile"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow PXE profile preflight."
fi
if ! grep -q 'validate_pxe_profile|start_pxe_services|stop_pxe_services|pxe_service_status' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow PXE service lifecycle actions."
fi
if ! grep -q '"start_pxe_services", "stop_pxe_services", "pxe_service_status"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow PXE service lifecycle actions."
fi
if ! grep -q 'inspect_client_csr|approve_client_csr' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow Client CSR trust actions."
fi
if ! grep -q '"approve_client_csr", "inspect_client_csr"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow Client CSR trust actions."
fi
if ! grep -q 'prepare_client_request|complete_client_enrollment' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow Client enrollment lifecycle actions."
fi
if ! grep -q '"prepare_client_request", "complete_client_enrollment"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow Client enrollment lifecycle actions."
fi
if ! grep -q 'def _complete_client_enrollment' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing Client enrollment completion."
fi
if ! grep -q 'def _approve_client_csr' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing Client CSR approval."
fi
if ! grep -q 'def _start_pxe_services' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing PXE service activation."
fi

if ! grep -q 'def _reconcile_deployment_job' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing explicit audit-only job reconciliation."
fi
if ! grep -q '"reconcile_deployment_job"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow job journal reconciliation."
fi
if ! grep -q 'reconcile_deployment_job' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart API wrapper does not allow job journal reconciliation."
fi
if ! grep -q 'Close for audit' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit frontend is missing manual job journal reconciliation."
fi

if ! grep -q 'def _create_deployment_job' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing safe remote deployment job persistence."
fi
if ! grep -q '"deployment_jobs", "create_deployment_job"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow remote deployment job actions."
fi
if ! grep -q 'deployment_jobs|create_deployment_job' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart API wrapper does not allow remote deployment job actions."
fi
if ! grep -q 'eventKey="remote-jobs"' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit frontend is missing the remote deployment job definition wizard."
fi
if ! grep -q 'execute_multicast_restore' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Persistent Client service is missing the multicast restore receiver path."
fi
if ! grep -q 'inspect_multicast_interface' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Client multicast receive interface preflight is missing."
fi
if ! grep -q 'test_create_deployment_job_reaches_server_validation_for_multicast' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit multicast Server job validation regression test is missing."
fi
if ! grep -q 'test_start_deployment_service_accepts_fresh_multicast_restore_journal' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit multicast Server service-start regression test is missing."
fi
if ! grep -q 'test_start_deployment_service_reconnects_to_active_job_without_revalidating_freshness' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit active-service reconnect regression test is missing."
fi

if grep -qx 'dialog' "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "The legacy dialog package must not be included in the Cockpit-first Live image."
fi

for package in cockpit cockpit-system cockpit-storaged dnsmasq ipxe-bootimgs-x86 caddy iproute firewalld; do
  grep -qx "$package" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $package."
  grep -qx "$package" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $package."
done

for optional_package in age minisign; do
  grep -qx "$optional_package" "$ROOT_DIR/packages/optional-image-security.txt" || fail "Optional image-security package list is missing $optional_package."
done

for package in lvm2 stratisd stratis-cli btrfs-progs exfatprogs f2fs-tools partclone; do
  grep -qx "$package" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $package."
  grep -qx "$package" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $package."
done

for codec in zstd lz4; do
  grep -qx "$codec" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $codec."
  grep -qx "$codec" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $codec."
done

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" "$ROOT_DIR/tests/vm" -type f -name '*.sh' -print0)

if ! grep -q 'class DeploymentService' "$ROOT_DIR/src/feclora/deployment/service.py"; then
  fail "Persistent deployment service runtime is missing."
fi
if ! grep -q 'feclora-deployment@.service' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart does not install the persistent deployment service unit."
fi
if ! grep -q 'start_deployment_service|deployment_service_status|stop_deployment_service|arm_deployment_job|cancel_deployment_job|inspect_remote_job' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow deployment service lifecycle actions."
fi
if ! grep -q '"start_deployment_service", "deployment_service_status", "stop_deployment_service", "arm_deployment_job", "cancel_deployment_job", "inspect_remote_job"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow persistent deployment service actions."
fi
if ! grep -q 'ExecStopPost=.*--recover-runtime' "$ROOT_DIR/src/feclora/data/feclora-deployment@.service"; then
  fail "Deployment service unit does not recover stale runtime socket and firewall state after exit."
fi
if ! grep -q 'TimeoutStopSec=infinity' "$ROOT_DIR/src/feclora/data/feclora-deployment@.service"; then
  fail "Deployment service must not time out and kill a worker during storage I/O."
fi
if ! grep -q 'self._worker.join()' "$ROOT_DIR/src/feclora/deployment/service.py"; then
  fail "Deployment service shutdown must wait for an active storage worker before closing Client sessions."
fi
if ! grep -q 'service shutdown has begun' "$ROOT_DIR/src/feclora/deployment/service.py"; then
  fail "Deployment service must reject new arm requests after shutdown begins."
fi
if ! grep -q 'test_arm_is_rejected_after_shutdown_begins' "$ROOT_DIR/tests/test_deployment_service.py"; then
  fail "Deployment service shutdown race regression test is missing."
fi
if ! grep -q 'feclora-client@.service' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart does not install the persistent Client service unit."
fi
if ! grep -q 'ExecStopPost=.*--mark-interrupted' "$ROOT_DIR/src/feclora/data/feclora-client@.service"; then
  fail "Client service unit does not mark interrupted work without resuming it."
fi
if ! grep -q 'TimeoutStopSec=infinity' "$ROOT_DIR/src/feclora/data/feclora-client@.service"; then
  fail "Client service must not time out and kill a block-device operation during shutdown."
fi
if ! grep -q 'test_orderly_signal_does_not_interrupt_active_block_device_io' "$ROOT_DIR/tests/test_client_service.py"; then
  fail "Client service shutdown safety regression test is missing."
fi
if ! grep -q '^Environment=PYTHONPATH=/usr/share/feclora/python$' "$ROOT_DIR/src/feclora/data/feclora-client@.service"; then
  fail "Client service unit does not configure the Feclora Python module path."
fi
if ! grep -q '^TimeoutStopSec=infinity$' "$ROOT_DIR/src/feclora/data/feclora-client@.service"; then
  fail "Client service unit must not force-kill an active storage operation on timeout."
fi
if ! grep -q 'inspect_remote_job|start_client_job|client_job_status' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit wrapper does not allow Client job lifecycle actions."
fi
if ! grep -q '"inspect_remote_job", "start_client_job", "client_job_status"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow Client job lifecycle actions."
fi

if ! grep -q 'execute_multicast_restore' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Persistent Client service does not invoke the multicast restore receiver."
fi
if ! grep -q 'inspect_multicast_interface' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Persistent Client service does not preflight its selected multicast interface."
fi
if ! grep -q 'network_interface' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Persistent Client request schema is missing the selected multicast interface."
fi
if ! grep -q 'test_multicast_job_preflights_selected_interface_and_uses_receiver_runtime' "$ROOT_DIR/tests/test_client_service.py"; then
  fail "Persistent Client multicast receiver regression test is missing."
fi
if ! grep -q 'test_start_client_job_preflights_and_persists_multicast_interface' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit Client multicast API preflight regression test is missing."
fi
if ! grep -q 'IGMP-VERIFIED' "$ROOT_DIR/src/feclora/deployment/service.py"; then
  fail "Server multicast arm must require explicit IGMP verification."
fi
if ! grep -q 'igmp_confirmed is not True' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Client multicast READY must require explicit IGMP acknowledgement."
fi
if ! grep -q 'clientRemoteIgmpConfirmed' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit Client multicast flow is missing the IGMP verification checkbox."
fi
if ! grep -q 'test_multicast_arm_requires_igmp_verification_phrase' "$ROOT_DIR/tests/test_deployment_service.py"; then
  fail "Server multicast IGMP confirmation regression test is missing."
fi
if ! grep -q 'test_multicast_job_preflights_selected_interface_and_uses_receiver_runtime' "$ROOT_DIR/tests/test_client_service.py"; then
  fail "Client multicast receive and IGMP acknowledgement regression test is missing."
fi
if ! grep -q 'test_start_client_job_preflights_and_persists_multicast_interface' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit Client multicast API and IGMP acknowledgement regression test is missing."
fi
if ! grep -q 'Local multicast receive interface' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit Client jobs tab is missing multicast interface selection."
fi
if ! grep -q 'Client selects its own receive interface' "$ROOT_DIR/docs/COCKPIT.md"; then
  fail "Cockpit documentation does not describe Client multicast interface selection."
fi

if ! grep -q 'class LocalControlServer' "$ROOT_DIR/src/feclora/deployment/local_control.py"; then
  fail "Deployment service local IPC server primitive is missing."
fi
if ! grep -q 'SO_PEERCRED' "$ROOT_DIR/src/feclora/deployment/local_control.py"; then
  fail "Deployment service IPC does not authenticate local peer credentials."
fi
if ! grep -q 'test_rejects_duplicate_fields' "$ROOT_DIR/tests/test_local_control.py"; then
  fail "Deployment service IPC protocol tests are missing."
fi

if ! grep -q '"transfer_ready", "progress"' "$ROOT_DIR/src/feclora/deployment/control.py"; then
  fail "Authenticated deployment control protocol is missing progress frames."
fi
if ! grep -q 'def _record_client_progress' "$ROOT_DIR/src/feclora/deployment/control.py"; then
  fail "Server-side Client progress validation is missing."
fi
if ! grep -q '"phase": phase' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Client service is not reporting disk-operation and transfer progress over mTLS."
fi
if ! grep -q 'transfer_progress_callback=transfer_progress' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Client service is not tracking its local image-transfer phase."
fi
if ! grep -q '"transfer"' "$ROOT_DIR/src/feclora/deployment/control.py"; then
  fail "Server control plane is not accepting the separate transfer progress phase."
fi
if ! grep -q 'self.control.client_progress()' "$ROOT_DIR/src/feclora/deployment/service.py"; then
  fail "Persistent Server status is not exposing per-Client progress."
fi
if ! grep -q 'test_progress_frame_is_validated_and_exposed_with_throughput' "$ROOT_DIR/tests/test_deployment_control.py"; then
  fail "Authenticated Client progress regression tests are missing."
fi
if ! grep -q 'test_status_includes_per_client_progress' "$ROOT_DIR/tests/test_deployment_service.py"; then
  fail "Cockpit Server progress status regression test is missing."
fi
if ! grep -q 'MiB/s' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit does not display per-Client transfer throughput."
fi
if ! grep -q 'setInterval' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit does not refresh active deployment progress automatically."
fi


# Fedora Server minimal Live kiosk validation
bash -n "$ROOT_DIR/src/feclora/data/feclora-cockpit-certificate" || fail "Cockpit certificate provisioning script has invalid Bash syntax."
bash -n "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" || fail "Firefox kiosk launcher has invalid Bash syntax."
bash -n "$ROOT_DIR/src/feclora/data/feclora-kiosk-bootstrap-ready" || fail "Kiosk bootstrap readiness probe has invalid Bash syntax."
python3 -m json.tool "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" >/dev/null || fail "Firefox kiosk policy is not valid JSON."
grep -Fq '@^server-product-environment' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not select Fedora Server."
grep -Fq -- '-@container-management' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Minimal Server base must exclude container-management packages."
grep -Fq -- '-@headless-management' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Minimal Server base must avoid duplicate headless-management packages."
for package in cage firefox; do
  grep -qx "$package" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $package."
  grep -qx "$package" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $package."
done
if grep -Eiq 'agetty --autologin|NOPASSWD|passwd --delete feclora' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart must not configure automatic login, empty passwords or passwordless sudo."
fi
grep -q 'passwd --lock feclora' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Administrator must remain locked until local first-boot setup."
grep -q '127.0.0.1:9090' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Cockpit must bind to IPv4 loopback."
grep -Fq '[::1]:9090' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Cockpit must bind to IPv6 loopback."
grep -Fq '"<all_urls>"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox WebsiteFilter must block all URLs by default."
grep -Fq '"http://127.0.0.1/*"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox WebsiteFilter must allow the local setup host."
grep -Fq '"https://localhost/*"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox WebsiteFilter must allow Cockpit pages."
grep -Fq '"wss://localhost/*"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox WebsiteFilter must allow Cockpit websockets."
grep -Fq '/usr/lib/mozilla/certificates/feclora-kiosk-ca.crt' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox must install the local CA using its Linux certificate policy."
grep -q 'Requires=feclora-cockpit-certificate.service' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Cockpit socket must wait for local TLS certificate provisioning."
grep -q 'feclora-kiosk-bootstrap-ready' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the bootstrap readiness probe."
grep -q 'feclora-kiosk.service' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not enable the Firefox kiosk service."
grep -Fq 'https://localhost:9090/cockpit/@localhost/feclora/index.html' "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" || fail "Kiosk launcher does not open the Feclora Cockpit application."
grep -Fq 'https://localhost:9090/cockpit/@localhost/feclora/index.html' "$ROOT_DIR/src/feclora/kiosk_bootstrap.py" || fail "First-boot assistant does not redirect into the Feclora Cockpit application."
grep -q '^Restart=on-failure$' "$ROOT_DIR/src/feclora/data/feclora-kiosk-bootstrap.service" || fail "First-boot assistant service must restart after failure."
grep -q '^IPAddressDeny=any$' "$ROOT_DIR/src/feclora/data/feclora-kiosk.service" || fail "Firefox kiosk must deny non-loopback network access."
grep -q '^IPAddressAllow=127.0.0.1/32$' "$ROOT_DIR/src/feclora/data/feclora-kiosk.service" || fail "Firefox kiosk must allow IPv4 loopback."
grep -q '^IPAddressAllow=::1/128$' "$ROOT_DIR/src/feclora/data/feclora-kiosk.service" || fail "Firefox kiosk must allow IPv6 loopback."
grep -q '^IPAddressDeny=any$' "$ROOT_DIR/src/feclora/data/feclora-kiosk-bootstrap.service" || fail "Bootstrap service must deny non-loopback network access."
grep -q 'AF_NETLINK' "$ROOT_DIR/src/feclora/data/feclora-kiosk.service" || fail "Cage service must retain udev netlink access."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_kiosk_bootstrap.py' || fail "First-boot kiosk bootstrap tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_inventory.py' || fail "Block-device inventory tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_volume_topology.py' || fail "Read-only LVM topology tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_btrfs_inventory.py' || fail "Btrfs inventory tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_stratis_inventory.py' || fail "Stratis inventory tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_storage_topology_graph.py' || fail "Cross-layer storage topology graph tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_capture.py' || fail "Block-device and logical-volume capture tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_capture_plan.py' || fail "Layered storage capture planning tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_image_manifest.py' || fail "Image manifest schema tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_logical_volume_restore.py' || fail "Logical-volume restore preflight tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_boot_tree.py' || fail "PXE Live boot-tree tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_pxe_boot_request.py' || fail "PXE boot-mode and job-handoff validation tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_pxe_config.py' || fail "PXE network configuration tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_pxe_preflight.py' || fail "PXE daemon preflight tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_pxe_service.py' || fail "PXE service lifecycle tests failed."
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_pxe_boot.py' || fail "PXE boot staging tests failed."

if (( errors > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$errors" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'

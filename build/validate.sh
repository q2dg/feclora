#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
errors=0
fail() { printf 'ERROR: %s\n' "$*" >&2; errors=$((errors + 1)); }

for file in "$ROOT_DIR/build/build-iso.sh" "$ROOT_DIR/build/preflight.sh" "$ROOT_DIR/build/install-host-deps.sh" "$ROOT_DIR/kickstart/feclora-live.ks" "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/src/feclora/storage/inventory.py" "$ROOT_DIR/src/feclora/storage/partition_image_capture.py" "$ROOT_DIR/tests/test_partition_image_capture.py" "$ROOT_DIR/src/feclora/storage/volume_metadata.py" "$ROOT_DIR/tests/test_volume_metadata.py" "$ROOT_DIR/src/feclora/storage/volume_topology.py" "$ROOT_DIR/tests/test_volume_topology.py" "$ROOT_DIR/src/feclora/storage/btrfs_inventory.py" "$ROOT_DIR/tests/test_btrfs_inventory.py" "$ROOT_DIR/src/feclora/storage/stratis_inventory.py" "$ROOT_DIR/tests/test_stratis_inventory.py" "$ROOT_DIR/src/feclora/network/interface_discovery.py" "$ROOT_DIR/tests/test_interface_discovery.py" "$ROOT_DIR/src/feclora/network/pxe_config.py" "$ROOT_DIR/src/feclora/network/pxe_preflight.py" "$ROOT_DIR/tests/test_pxe_preflight.py" "$ROOT_DIR/src/feclora/network/pxe_service.py" "$ROOT_DIR/tests/test_pxe_service.py" "$ROOT_DIR/src/feclora/network/firewall.py" "$ROOT_DIR/tests/test_firewall.py" "$ROOT_DIR/src/feclora/network/boot_assets.py" "$ROOT_DIR/tests/test_boot_assets.py" "$ROOT_DIR/src/feclora/network/boot_tree.py" "$ROOT_DIR/tests/test_boot_tree.py" "$ROOT_DIR/src/feclora/network/pxe_boot.py" "$ROOT_DIR/tests/test_pxe_boot.py" "$ROOT_DIR/src/feclora/network/server_mode.py" "$ROOT_DIR/src/feclora/deployment/control.py" "$ROOT_DIR/src/feclora/deployment/artifact_transfer.py" "$ROOT_DIR/src/feclora/deployment/client_runtime.py" "$ROOT_DIR/src/feclora/deployment/runtime_config.py" "$ROOT_DIR/src/feclora/deployment/journal.py" "$ROOT_DIR/src/feclora/deployment/service.py" "$ROOT_DIR/src/feclora/deployment/client_service.py" "$ROOT_DIR/src/feclora/data/feclora-deployment@.service" "$ROOT_DIR/src/feclora/data/feclora-client@.service" "$ROOT_DIR/tests/test_deployment_service.py" "$ROOT_DIR/tests/test_client_service.py" "$ROOT_DIR/src/feclora/deployment/server_ui.py" "$ROOT_DIR/src/feclora/deployment/client_ui.py" "$ROOT_DIR/tests/test_deployment_control.py" "$ROOT_DIR/tests/test_artifact_transfer.py" "$ROOT_DIR/tests/test_client_runtime.py" "$ROOT_DIR/tests/test_runtime_config.py" "$ROOT_DIR/tests/test_deployment_journal.py" "$ROOT_DIR/tests/vm/README.md" "$ROOT_DIR/tests/vm/run-pxe-matrix.sh" "$ROOT_DIR/tests/test_server_mode.py" "$ROOT_DIR/tests/test_pxe_config.py" "$ROOT_DIR/src/feclora/storage/restore_profile.py" "$ROOT_DIR/src/feclora/storage/profile_executor.py" "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" "$ROOT_DIR/src/feclora/data/feclora-restore-profile.service" "$ROOT_DIR/src/feclora/webapi.py" "$ROOT_DIR/tests/test_webapi.py" "$ROOT_DIR/webui/package.json" "$ROOT_DIR/webui/src/App.jsx" "$ROOT_DIR/webui/src/api.js" "$ROOT_DIR/build/build-webui.sh" "$ROOT_DIR/docs/COCKPIT.md" "$ROOT_DIR/build/README.md"; do
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

if ! grep -q 'network_interfaces|bootstrap_server' "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "Kickstart Cockpit API wrapper does not allow the Server identity bootstrap actions."
fi
if ! grep -q '"network_interfaces", "bootstrap_server"' "$ROOT_DIR/webui/src/api.js"; then
  fail "Cockpit API client does not allow the Server identity bootstrap actions."
fi
if ! grep -q 'def _bootstrap_server' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit backend is missing the Server identity bootstrap implementation."
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
if ! grep -q 'Cockpit multicast deployment is not yet end-to-end' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit API must reject multicast jobs until Client receiver orchestration is implemented."
fi
if ! grep -q 'UDPcast multicast restore — Client workflow pending' "$ROOT_DIR/webui/src/App.jsx"; then
  fail "Cockpit must not offer an incomplete multicast Client workflow as an executable job."
fi
if ! grep -q 'test_create_deployment_job_rejects_multicast_until_client_receiver_exists' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Cockpit multicast safety regression test is missing."
fi
if ! grep -q 'cannot start multicast jobs until the Client-side multicast receiver workflow is integrated' "$ROOT_DIR/src/feclora/webapi.py"; then
  fail "Cockpit must refuse to start legacy multicast journals without Client receiver integration."
fi
if ! grep -q 'test_start_deployment_service_rejects_legacy_multicast_journal' "$ROOT_DIR/tests/test_webapi.py"; then
  fail "Legacy multicast service-start regression test is missing."
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

for package in lvm2 stratisd stratis-cli btrfs-progs; do
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
if ! grep -q '"phase": job.operation' "$ROOT_DIR/src/feclora/deployment/client_service.py"; then
  fail "Client service is not reporting disk-operation progress over mTLS."
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

if (( errors > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$errors" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

require_file() {
  [[ -s "$ROOT_DIR/$1" ]] || fail "Required file is missing or empty: $1"
}

require_text() {
  local pattern="$1" file="$2" message="$3"
  grep -Eq -- "$pattern" "$ROOT_DIR/$file" || fail "$message"
}

for file in \
  build/build-iso.sh build/preflight.sh build/install-host-deps.sh kickstart/feclora-live.ks \
  packages/base.txt packages/build-host.txt requirements-test.txt requirements-gui.txt \
  src/feclora/tui.py src/feclora/tui_api.py src/feclora/gui_gtk.py src/feclora/gtk_api.py src/feclora/api.py \
  src/feclora/data/feclora-api src/feclora/data/feclora-tui.service \
  src/feclora/data/feclora-tui-ready src/feclora/data/feclora-root-terminal.service \
  src/feclora/data/feclora-local-operation-recovery.service \
  tests/test_gtk_api.py tests/test_gtk_frontend.py tests/test_ui_catalog.py build/validate-text-boot.sh build/verify-iso-text-boot.sh \
  build/check_docs.py; do
  require_file "$file"
done

require_text '^#version=F45$' kickstart/feclora-live.ks "Kickstart must target Fedora 45."
require_text 'packages/build-host\.txt' build/install-host-deps.sh "Build dependencies must come from the build-host package manifest."
require_text '^python3-textual$' packages/base.txt "The current Live image must keep Textual until GUI feature parity is reached."
require_text '^textual==8\.1\.1$' requirements-test.txt "Legacy TUI tests must use the runtime Textual version during migration."
require_text '^# GTK4 and PyGObject are supplied by Fedora RPMs' requirements-gui.txt "GTK4 and PyGObject must use Fedora system packages, not pip."
require_text 'create_subprocess_exec' src/feclora/tui_api.py "The privileged API client must invoke its helper without a shell."
require_text 'ThreadPoolExecutor|GLib\.idle_add' src/feclora/gtk_api.py "The GTK API bridge must keep blocking subprocess work off the GLib main loop."
require_text 'GDK_BACKEND.*wayland' src/feclora/gui_gtk.py "The GTK frontend must force the native Wayland backend."
require_text 'WAYLAND_DISPLAY' src/feclora/gui_gtk.py "The GTK frontend must require a Wayland compositor socket."
require_text 'os\.environ\.pop\("DISPLAY", None\)' src/feclora/gui_gtk.py "The GTK frontend must remove any inherited X11 display variable."
require_text 'self\.api\.submit\("status"' src/feclora/gui_gtk.py "GTK overview must call the real status API."
require_text 'self\.api\.submit\("inventory"' src/feclora/gui_gtk.py "GTK inventory must call the real inventory API."
require_text 'action = "capture_disk"' src/feclora/gui_gtk.py "GTK operations must invoke the real disk capture API."
require_text 'action = "capture_partition"' src/feclora/gui_gtk.py "GTK operations must invoke the real partition capture API."
require_text 'action = "capture_logical_volume"' src/feclora/gui_gtk.py "GTK operations must invoke the real logical-volume capture API."
require_text '"capture_stratis_filesystem"' src/feclora/api.py "Privileged API dispatch must expose Stratis capture."
require_text '"capture_btrfs_subvolume"' src/feclora/api.py "Privileged API dispatch must expose Btrfs capture."
require_text '"receive_btrfs_subvolume"' src/feclora/api.py "Privileged API dispatch must expose Btrfs receive."
require_text '"recover_disk"' src/feclora/api.py "Privileged API dispatch must expose ddrescue recovery."
require_text '"finalize_recovery"' src/feclora/api.py "Privileged API dispatch must expose recovery finalization."
require_text 'action = "capture_stratis_filesystem"' src/feclora/gui_gtk.py "GTK operations must invoke the real Stratis capture API."
require_text 'self\.api\.submit\("capture_btrfs_subvolume"' src/feclora/gui_gtk.py "GTK operations must invoke the real Btrfs capture API."
require_text 'self\.api\.submit\("receive_btrfs_subvolume"' src/feclora/gui_gtk.py "GTK operations must invoke the real Btrfs receive API."
require_text 'self\.api\.submit\("recover_disk"' src/feclora/gui_gtk.py "GTK operations must invoke the real ddrescue recovery API."
require_text 'self\.api\.submit\("finalize_recovery"' src/feclora/gui_gtk.py "GTK operations must invoke the real recovery finalization API."
require_text 'def _flatten_logical_volumes' src/feclora/gui_gtk.py "GTK must filter logical volumes before capture."
require_text 'self\.api\.submit\("local_operation_status"' src/feclora/gui_gtk.py "GTK disk capture must poll real operation status."
require_text 'self\.api\.submit\("cancel_local_operation"' src/feclora/gui_gtk.py "GTK disk capture must expose operation cancellation."
require_text 'def _show_capture_status' src/feclora/gui_gtk.py "GTK disk capture must handle operation progress and terminal states."
if grep -Eiq 'customtkinter|tkinter|xwayland|xorg' requirements-gui.txt src/feclora/gui_gtk.py src/feclora/gtk_api.py; then
  fail "The GTK4 target runtime must not depend on Tk or X11 compatibility."
fi
require_text 'fullscreen\(\)' src/feclora/gui_gtk.py "The GTK kiosk window must request fullscreen mode."
require_text 'set_decorated\(False\)' src/feclora/gui_gtk.py "The GTK kiosk window must remove window decorations."
require_text 'close-request' src/feclora/gui_gtk.py "The GTK frontend must suppress ordinary window closure."
if grep -Fq 'create_subprocess_shell' "$ROOT_DIR/src/feclora/tui_api.py"; then
  fail "API requests must not use a command shell."
fi

require_text '^User=feclora$' src/feclora/data/feclora-tui.service "The current UI must run as its unprivileged appliance user."
require_text '^ExecStart=/usr/bin/python3 -m feclora\.tui$' src/feclora/data/feclora-tui.service "The existing interface must remain bootable until the GTK4 port reaches feature parity."
require_text '^ExecStartPost=\+/usr/libexec/feclora/feclora-tui-ready$' src/feclora/data/feclora-tui.service "The current UI unit must report the QEMU smoke-test readiness event."
require_text 'feclora ALL=\(root\) NOPASSWD: /usr/libexec/feclora/feclora-api \*' kickstart/feclora-live.ks "Passwordless root access must be limited to the validated API helper."
if grep -Eq '^(NoNewPrivileges=true|ProtectSystem=full)$' "$ROOT_DIR/src/feclora/data/feclora-tui.service"; then
  fail "The UI service must allow its scoped sudo helper to perform privileged appliance operations."
fi
require_text 'set-default multi-user\.target' kickstart/feclora-live.ks "The default boot target must remain text-only during the staged GUI migration."
require_text 'mask getty@tty1\.service' kickstart/feclora-live.ks "tty1 must remain reserved for the current interface."
require_text '^TTYPath=/dev/tty2$' src/feclora/data/feclora-root-terminal.service "The diagnostic root shell must use tty2."
require_text 'feclora-tui\.service' src/feclora/data/feclora-local-operation-recovery.service "Durable operations must recover before the interface starts."
require_text 'FECLORA_SELINUX_PERMISSIVE:-1' build/build-iso.sh "SELinux permissive mode must remain the diagnostic build default."
require_text 'mkksiso --cmdline selinux=0' build/build-iso.sh "Only the temporary Anaconda build VM may disable SELinux."

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston(-libs)?|gtk4|libadwaita|firefox)([[:space:]]|$)' \
  "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "The Live image must not install stock GTK4/Weston RPMs before X11-disabled Feclora builds are available."
fi
if grep -Eiq '(^|[[:space:]])(xorg-x11-server-Xwayland|xorg-x11-server-Xorg|openbox)([[:space:]]|$)' \
  "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "The Wayland-only appliance must not install XWayland, Xorg or Openbox."
fi
if grep -Eiq 'cockpit|weston|firefox|webui' "$ROOT_DIR/build/build-iso.sh"; then
  fail "ISO construction must not stage an unrelated graphical desktop or web UI."
fi

if ! python3 - "$ROOT_DIR" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
base = {
    line.strip() for line in (root / "packages/base.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
kickstart = (root / "kickstart/feclora-live.ks").read_text(encoding="utf-8")
match = re.search(r"(?ms)^%packages[^\n]*\n(.*?)^%end\s*$", kickstart)
if match is None:
    raise SystemExit("Kickstart %packages block was not found.")
ks = {
    line.strip() for line in match.group(1).splitlines()
    if line.strip() and not line.lstrip().startswith(("#", "@", "-"))
}
if base != ks:
    raise SystemExit(
        f"Package manifests differ. Missing from base.txt: {sorted(ks - base)}; "
        f"only in base.txt: {sorted(base - ks)}"
    )
exclusions = {
    line.strip()[1:] for line in match.group(1).splitlines()
    if line.strip().startswith("-")
}
expected_exclusions = {
    "plymouth", "plymouth-plugin-script", "plymouth-plugin-two-step", "plymouth-scripts"
}
if exclusions != expected_exclusions:
    raise SystemExit(
        f"Kickstart splash-package exclusions differ. Expected {sorted(expected_exclusions)}; "
        f"found {sorted(exclusions)}."
    )
if "openssh-clients" not in ks:
    raise SystemExit("Kickstart must install openssh-clients.")
PY
then
  fail "The package manifest and Kickstart package set must match."
fi

if ! bash "$ROOT_DIR/build/validate-text-boot.sh"; then
  fail "Text-only boot configuration validation failed."
fi

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" -maxdepth 1 -type f -name '*.sh' -print0)
bash -n "$ROOT_DIR/kickstart/feclora-live.ks" \
  || fail "Kickstart contains invalid embedded shell syntax."
bash -n "$ROOT_DIR/src/feclora/data/feclora-api" || fail "Privileged API helper has invalid shell syntax."
python3 -m compileall -q "$ROOT_DIR/src" "$ROOT_DIR/tests" || fail "Python compilation failed."

if ! PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'; then
  fail "Python unit tests failed."
fi
if ! python3 "$ROOT_DIR/build/check_docs.py"; then
  fail "Documentation links and guide assets failed validation."
fi


require_text 'self\.api\.submit\("images"' src/feclora/gui_gtk.py "GTK restore workflow must load image manifests through the privileged API."
require_text '"restore_disk".*"restore_partition".*"restore_logical_volume"' src/feclora/gui_gtk.py "GTK must expose disk, partition and logical-volume restore operations."
require_text '"clone_disk".*"clone_partition"' src/feclora/gui_gtk.py "GTK must expose disk and partition cloning."

require_text '"restore_stratis_filesystem"' src/feclora/api.py "Privileged API dispatch must expose Stratis filesystem restoration."
require_text '"restore_stratis_filesystem"' src/feclora/gui_gtk.py "GTK must expose Stratis filesystem restoration."

require_text 'self\.api\.submit\("remote_repositories"' src/feclora/gui_gtk.py "GTK image-building workflows must load repository state."
require_text '"build_recovery_iso"' src/feclora/gui_gtk.py "GTK must expose recovery ISO generation."
require_text '"build_deployment_bundle"' src/feclora/gui_gtk.py "GTK must expose deployment bundle generation."

require_text 'target_wwn and not target_serial' src/feclora/gui_gtk.py "GTK recovery ISO generation must require a target identity selector."
require_text 'base_iso\.lower\(\)\.endswith\("\.iso"\)' src/feclora/gui_gtk.py "GTK recovery artifacts must require an ISO base path."

require_text '"restore_stratis_filesystem"' src/feclora/api.py "Stratis restoration must be present in the public API dispatch."
require_text '"build_recovery_iso".*"build_deployment_bundle"' src/feclora/api.py "Recovery ISO and deployment bundle must be exposed by the public API dispatch."
require_text 'json\.loads\(job_text\)' src/feclora/gui_gtk.py "GTK deployment bundle form must parse DeploymentJob JSON."

require_text 'self\.api\.submit\("repository_images"' src/feclora/gui_gtk.py "GTK must load image manifests from the selected mounted repository."

require_text 'self\.capture_repository\.connect\("notify::selected"' src/feclora/gui_gtk.py "GTK repository selection must refresh repository-scoped image catalogs."

require_text 'self\.api\.submit\("inspect_image_layout"' src/feclora/gui_gtk.py "GTK image page must inspect verified partition layouts."
require_text 'self\.api\.submit\("browse_image"' src/feclora/gui_gtk.py "GTK image page must browse files inside disk images."
require_text 'self\.api\.submit\("extract_partition_image"' src/feclora/gui_gtk.py "GTK image page must expose partition extraction."
require_text '"restore_proportional_disk"' src/feclora/gui_gtk.py "GTK must expose proportional restore to a smaller disk."
require_text 'target_device\["size_bytes"\] >= source_device\["size_bytes"\]' src/feclora/gui_gtk.py "Proportional restore must reject targets that are not strictly smaller."

require_text '"restore_proportional_disk"' src/feclora/api.py "Proportional restore must be available through the privileged API dispatch."
require_text '"extract_partition_image"' src/feclora/api.py "Partition extraction must be available through the privileged API dispatch."

require_text 'self\.api\.submit\("capture_p2v"' src/feclora/gui_gtk.py "GTK must expose virtual-disk QCOW2 P2V capture."

require_text 'self\.api\.submit\("restore_profiles"' src/feclora/gui_gtk.py "GTK restore profiles page must load persisted profiles."
require_text 'self\.api\.submit\("create_restore_profile"' src/feclora/gui_gtk.py "GTK restore profiles page must create bound single-use profiles."
require_text 'self\.api\.submit\("execute_restore_profile"' src/feclora/gui_gtk.py "GTK restore profiles page must execute selected profiles through the durable worker."
require_text 'self\.api\.submit\("capture_p2v"' src/feclora/gui_gtk.py "GTK must expose P2V capture."

require_text 'self\.api\.submit\("apply_network_profile"' src/feclora/gui_gtk.py "GTK network page must apply NetworkManager profiles through the privileged API."
require_text '"rollback_timeout": 120' src/feclora/gui_gtk.py "GTK network changes must retain the automatic rollback checkpoint."

require_text 'self\.api\.submit\("local_operations"' src/feclora/gui_gtk.py "GTK operation log must read durable local operation history."
require_text 'self\.api\.submit\("recovery_jobs"' src/feclora/gui_gtk.py "GTK recovery history must read persistent ddrescue jobs."

require_text 'page_scroller\.set_child\(self\.page_body\)' src/feclora/gui_gtk.py "GTK navigation must keep long operator forms accessible in a scroll container."

require_text 'self\._history_page\("Trabajos remotos"' src/feclora/gui_gtk.py "GTK remote jobs page must list persistent deployment jobs."
require_text 'self\._history_page\("Historial de despliegues"' src/feclora/gui_gtk.py "GTK deployment history page must render journals."
require_text 'self\.api\.submit\("deployment_jobs"' src/feclora/gui_gtk.py "GTK client jobs page must list client deployment states."

require_text 'self\.api\.submit\("s3_repositories"' src/feclora/gui_gtk.py
require_text '"check_remote_repository"' src/feclora/gui_gtk.py "GTK must expose remote repository verification."
require_text '"mount_remote_repository"' src/feclora/gui_gtk.py "GTK must expose guarded remote repository mounting."
require_text '"unmount_remote_repository"' src/feclora/gui_gtk.py "GTK must expose verified remote repository unmounting."
require_text '"remove_remote_repository"' src/feclora/gui_gtk.py "GTK must expose confirmed remote repository removal."
require_text '"check_s3_repository"' src/feclora/gui_gtk.py "GTK must expose S3 repository checks."
require_text '"remove_s3_repository"' src/feclora/gui_gtk.py "GTK must expose S3 repository removal."
require_text 'add_remote_repository' src/feclora/gui_gtk.py "GTK must expose SSHFS repository definitions."
require_text 'Gtk\.DropDown\.new_from_strings\(\["SSHFS", "NFS", "SMB/CIFS"\]\)' src/feclora/gui_gtk.py "GTK must expose all managed SSHFS, NFS and SMB repository providers."
require_text 'self\.remote_credential\.set_visible\(provider == "smb"\)' src/feclora/gui_gtk.py "GTK must expose encrypted SMB credentials only for SMB provider."
require_text 'self\._selected_remote_credential_path\(self\.remote_credential' src/feclora/gui_gtk.py "GTK SMB repository definitions must reference protected systemd credentials."
require_text 'self\.remote_identity\.set_visible\(provider == "sshfs"\)' src/feclora/gui_gtk.py "GTK SSHFS definitions must use protected SSH key and known_hosts selectors."

require_text 'add_s3_repository' src/feclora/gui_gtk.py "GTK must expose S3 repository definitions."
require_text 'update_remote_repository' src/feclora/gui_gtk.py "GTK must expose SSHFS repository definition updates."
require_text 'update_s3_repository' src/feclora/gui_gtk.py "GTK must expose S3 repository definition updates."
require_text 'self\.api\.submit\("put_systemd_credential"' src/feclora/gui_gtk.py "GTK must expose encrypted systemd credential import."
require_text 'self\.api\.submit\("remove_systemd_credential"' src/feclora/gui_gtk.py "GTK must expose guarded encrypted credential removal."
require_text 'self\.api\.submit\("systemd_credentials"' src/feclora/gui_gtk.py "GTK must load the encrypted credential inventory."

require_text 'self\.api\.submit\("import_p2v"' src/feclora/gui_gtk.py "GTK must expose legacy P2V bundle import."
require_text 'self\.api\.submit\("export_p2v_s3"' src/feclora/gui_gtk.py "GTK must expose legacy P2V export from S3."
require_text 'def _import_legacy_p2v' src/feclora/gui_gtk.py "GTK must validate and submit legacy P2V imports."
require_text 'def _export_legacy_p2v' src/feclora/gui_gtk.py "GTK must validate and submit legacy P2V S3 exports." "GTK repository inventory must include S3 repositories."
require_text 'self\.api\.submit\("remote_repositories"' src/feclora/gui_gtk.py "GTK repository inventory must include filesystem repositories."

require_text 'self\.api\.submit\("verify_image"' src/feclora/gui_gtk.py "GTK image page must support full artifact integrity verification."
require_text 'operation_confirmation\.get_text\(\) != expected' src/feclora/gui_gtk.py "GTK operation cancellation must require the exact operation ID phrase."

require_text 'self\.api\.submit\("pxe_service_status"' src/feclora/gui_gtk.py
require_text 'self\.api\.submit\("bootstrap_server"' src/feclora/gui_gtk.py "GTK must expose guarded server bootstrap."
require_text 'self\.api\.submit\("renew_server_certificate"' src/feclora/gui_gtk.py "GTK must expose confirmed server certificate renewal."
require_text 'self\.api\.submit\("rotate_server_keypair"' src/feclora/gui_gtk.py "GTK must expose confirmed TLS keypair rotation."
require_text 'self\.api\.submit\("validate_pxe_profile"' src/feclora/gui_gtk.py "GTK must validate PXE profiles before enabling service startup."
require_text 'self\.api\.submit\("start_pxe_services"' src/feclora/gui_gtk.py "GTK must expose validated PXE service startup."
require_text 'self\.api\.submit\("stop_pxe_services"' src/feclora/gui_gtk.py "GTK must expose PXE service shutdown."
require_text 'self\.api\.submit\("publish_pxe_answer"' src/feclora/gui_gtk.py "GTK must expose validated PXE answer publication."
require_text 'self\.api\.submit\("revoke_pxe_answer"' src/feclora/gui_gtk.py "GTK must expose PXE answer and boot-script revocation."
require_text 'self\.api\.submit\("pxe_age_passphrase_status"' src/feclora/gui_gtk.py "GTK must expose one-shot PXE age passphrase request status."
require_text 'self\.api\.submit\("provide_pxe_age_passphrase"' src/feclora/gui_gtk.py "GTK must expose secure one-shot PXE age passphrase delivery."
require_text 'self\.api\.submit\("export_server_age_recipients"' src/feclora/gui_gtk.py "GTK must expose server age recipient export."
require_text 'self\.api\.submit\("refresh_client_age_recipients"' src/feclora/gui_gtk.py "GTK must expose client age recipient inventory refresh."
require_text 'self\.api\.submit\("create_deployment_job"' src/feclora/gui_gtk.py "GTK must expose remote deployment definition creation."
require_text 'self\.api\.submit\("import_deployment_job"' src/feclora/gui_gtk.py "GTK must expose bounded remote deployment definition import."
require_text 'self\.api\.submit\("arm_deployment_job"' src/feclora/gui_gtk.py "GTK must expose exact-phrase deployment authorization."
require_text 'self\.api\.submit\("cancel_deployment_job"' src/feclora/gui_gtk.py "GTK must expose confirmed deployment cancellation."
require_text 'self\.api\.submit\("reconcile_deployment_job"' src/feclora/gui_gtk.py "GTK must expose confirmed interrupted deployment reconciliation."
require_text 'self\.api\.submit\("start_deployment_service"' src/feclora/gui_gtk.py "GTK must expose deployment service startup."
require_text 'self\.api\.submit\("stop_deployment_service"' src/feclora/gui_gtk.py "GTK must expose guarded deployment service shutdown."
require_text 'self\.api\.submit\("deployment_service_status"' src/feclora/gui_gtk.py "GTK must expose deployment service status checks."
require_text 'def _stop_remote_job_after_status' src/feclora/gui_gtk.py "GTK must preflight active clients before stopping deployment workers."
require_text 'self\.api\.submit\("inspect_remote_job"' src/feclora/gui_gtk.py "GTK must expose authenticated remote client inspection."
require_text 'self\.api\.submit\("start_client_job"' src/feclora/gui_gtk.py "GTK must expose explicitly confirmed client operation startup."
require_text 'self\.api\.submit\("client_job_status"' src/feclora/gui_gtk.py "GTK must expose persistent client job status."
require_text 'self\.api\.submit\("network_interfaces"' src/feclora/gui_gtk.py "GTK client must select an active IPv4 network binding."
require_text 'self\.api\.submit\("inventory"' src/feclora/gui_gtk.py "GTK client must inspect local storage inventory before target selection."
require_text 'self\._remote_import_remote_rows =' src/feclora/gui_gtk.py "GTK remote imports must preserve remote filesystem repository results."
require_text 'self\._remote_import_s3_rows =' src/feclora/gui_gtk.py "GTK remote imports must preserve S3 repository results independently."
require_text 'def _update_client_inventory_summary' src/feclora/gui_gtk.py "GTK client must refresh local target inventory and active network summary."

require_text 'f"ERASE \{target\}"' src/feclora/gui_gtk.py "GTK destructive client operations must require exact target confirmation."
require_text 'f"READ \{target\} TO \{inspection.get' src/feclora/gui_gtk.py "GTK capture client operations must bind confirmation to server identity."


require_text 'base64\.b64encode\(payload\)\.decode\("ascii"\)' src/feclora/gui_gtk.py "GTK must bound and encode local PXE answer uploads."
require_text 'self\.pxe_passphrase\.set_visibility\(False\)' src/feclora/gui_gtk.py "GTK must mask one-shot age passphrases."

require_text 'self\.api\.submit\("pxe_service_status"' src/feclora/gui_gtk.py "GTK server status must include PXE service health."
require_text 'status\.get\("certificate_status"\)' src/feclora/gui_gtk.py "GTK system status must include certificate health."

require_text 'self\.capture_passphrase = Gtk\.PasswordEntry\(\)' src/feclora/gui_gtk.py "GTK RAW capture must provide a masked age passphrase field."
require_text 'self\.capture_passphrase_toggle = Gtk\.CheckButton' src/feclora/gui_gtk.py "GTK RAW capture must expose the separate one-shot passphrase mode."
require_text 'self\.capture_encrypt = Gtk\.CheckButton\(label="Cifrar con destinatarios age"\)' src/feclora/gui_gtk.py "GTK capture must preserve recipient-based age encryption."
require_text 'self\.capture_passphrase_toggle\.set_active\(False\)' src/feclora/gui_gtk.py "GTK age encryption modes must be mutually exclusive."
require_text 'params\["encrypt_passphrase"\] = True' src/feclora/gui_gtk.py "GTK passphrase capture must select the dedicated API encryption mode."
require_text '"provide_capture_passphrase"' src/feclora/gui_gtk.py "GTK must deliver the one-shot age passphrase to the accepted operation."
require_text 'self\.capture_passphrase\.set_text\(""\)' src/feclora/gui_gtk.py "GTK must clear the age passphrase field after submission."

require_text 'self\.active_capture_passphrase = ""' src/feclora/gui_gtk.py "GTK must clear a pending age passphrase after capture failure."
require_text 'self\.capture_cancel\.set_sensitive\(False\)' src/feclora/gui_gtk.py "GTK must disable capture cancellation after failure."

require_text 'gi\.require_version\("Adw", "1"\)' src/feclora/gui_gtk.py "GTK frontend must require the supported libadwaita namespace."
require_text 'Adw\.ApplicationWindow\(application=application\)' src/feclora/gui_gtk.py "GTK frontend must use the libadwaita application window."
require_text 'Adw\.ToolbarView\(\)' src/feclora/gui_gtk.py "GTK frontend must use libadwaita toolbar layout."
require_text 'Adw\.ToastOverlay\(\)' src/feclora/gui_gtk.py "GTK frontend must provide libadwaita transient notifications."
require_text 'libadwaita' requirements-gui.txt "GUI runtime metadata must include Fedora libadwaita packages."

require_text 'Adw\.NavigationSplitView\(\)' src/feclora/gui_gtk.py "GTK frontend must use adaptive libadwaita navigation."
require_text 'Adw\.PreferencesGroup\(title="Secciones"\)' src/feclora/gui_gtk.py "GTK navigation must group page destinations semantically."
require_text 'row\.connect\("activated", self\._select_page, page_id\)' src/feclora/gui_gtk.py "GTK navigation rows must preserve page selection callbacks."
require_text 'row\.set_activatable\(True\)' src/feclora/gui_gtk.py "GTK navigation rows must be keyboard and pointer activatable."
require_text 'row\.set_subtitle\("Página actual" if selected else ""\)' src/feclora/gui_gtk.py "GTK navigation must identify the current page."
require_text 'icon\.set_from_icon_name\("emblem-ok-symbolic" if selected else "go-next-symbolic"\)' src/feclora/gui_gtk.py "GTK navigation must provide a distinct current-page icon."
require_text 'Adw\.NavigationPage\.new\(sidebar_scroller' src/feclora/gui_gtk.py "GTK frontend must wrap the navigation sidebar in an Adw page."
require_text 'notify::collapsed' src/feclora/gui_gtk.py "GTK frontend must respond to compact navigation transitions."
require_text 'set_show_content\(True\)' src/feclora/gui_gtk.py "GTK frontend must reveal the selected page in compact navigation."


require_text 'Adw\.StatusPage\(' src/feclora/gui_gtk.py "GTK histories must use native libadwaita empty and error states."
require_text 'self\.operation_log_stack\.set_visible_child_name\("records" if operations else "empty"\)' src/feclora/gui_gtk.py "GTK operation history must distinguish empty from populated results."
require_text 'self\.recovery_jobs_stack\.set_visible_child_name\("jobs" if jobs else "empty"\)' src/feclora/gui_gtk.py "GTK recovery history must distinguish empty from populated results."

require_text 'Adw\.PreferencesGroup\(' src/feclora/gui_gtk.py "GTK network settings must use a libadwaita preferences group."
require_text 'Adw\.ActionRow\(title=title\)' src/feclora/gui_gtk.py "GTK network settings must use semantic libadwaita action rows."
require_text 'row\.set_activatable_widget\(widget\)' src/feclora/gui_gtk.py "GTK network setting rows must preserve direct control activation."
require_text 'Adw\.ComboRow\(title=title\)' src/feclora/gui_gtk.py "GTK network selectors must use native libadwaita combo rows."
require_text 'Adw\.EntryRow\(title=title\)' src/feclora/gui_gtk.py "GTK network text fields must use native libadwaita entry rows."

require_text 'self\.image_catalog_stack = Gtk\.Stack\(\)' src/feclora/gui_gtk.py "GTK image catalog must use a stack for asynchronous states."
require_text 'title="No hay imágenes de disco"' src/feclora/gui_gtk.py "GTK image catalog must use a libadwaita empty state."
require_text 'title="Cargando catálogo"' src/feclora/gui_gtk.py "GTK image catalog must use a libadwaita loading state."
require_text 'title="No se pudo cargar el catálogo"' src/feclora/gui_gtk.py "GTK image catalog must distinguish lookup failures from empty repositories."
require_text 'self\.image_catalog_stack\.set_visible_child_name\("images" if self\.image_catalog else "empty"\)' src/feclora/gui_gtk.py "GTK image selector must appear only when disk images are available."

require_text 'Adw\.PreferencesGroup\(' src/feclora/gui_gtk.py "GTK system status must use a libadwaita preferences group."
require_text 'status_row = Adw\.ActionRow\(title="Resumen del sistema"\)' src/feclora/gui_gtk.py "GTK system status must use a semantic libadwaita status row."
require_text 'refresh_row = Adw\.ActionRow\(title="Actualizar estado"\)' src/feclora/gui_gtk.py "GTK system refresh must use a libadwaita action row."
require_text 'refresh_row\.set_activatable_widget\(refresh\)' src/feclora/gui_gtk.py "GTK system refresh row must preserve direct button activation."

require_text 'title="Estado del servidor"' src/feclora/gui_gtk.py "GTK server health must use a libadwaita preferences group."
require_text 'title="Identidad y certificados TLS"' src/feclora/gui_gtk.py "GTK TLS administration must use a semantic preferences group."
require_text 'title="Servicios PXE"' src/feclora/gui_gtk.py "GTK PXE profile controls must use a semantic preferences group."
require_text 'title="Respuestas PXE desatendidas"' src/feclora/gui_gtk.py "GTK unattended PXE answer actions must use a semantic preferences group."
require_text 'title="Cifrado age y destinatarios"' src/feclora/gui_gtk.py "GTK age recipient and passphrase workflows must use a semantic preferences group."
require_text 'row.set_activatable_widget(widget)' src/feclora/gui_gtk.py "GTK server preference rows must preserve direct control activation."
require_text 'self.pxe_start.set_sensitive(False)' src/feclora/gui_gtk.py "GTK PXE services must remain disabled until profile validation succeeds."
require_text 'self.pxe_passphrase.set_visibility(False)' src/feclora/gui_gtk.py "GTK one-shot PXE age passphrases must remain masked."


require_text 'title="Origen y destino"' src/feclora/gui_gtk.py "GTK restore profiles must group source and target selection."
require_text 'title="Definición del perfil"' src/feclora/gui_gtk.py "GTK restore profiles must separate profile creation from execution."
require_text 'title="Ejecución controlada"' src/feclora/gui_gtk.py "GTK restore profiles must group guarded execution controls."
require_text 'row\.set_activatable_widget\(widget\)' src/feclora/gui_gtk.py "GTK restore profile rows must preserve direct control activation."
require_text 'self\.profile_cancel\.set_sensitive\(False\)' src/feclora/gui_gtk.py "GTK restore profile cancellation must remain disabled until an operation is active."


require_text 'title="Estado del registro"' src/feclora/gui_gtk.py "GTK operation log must group persistent status and refresh."
require_text 'title="Cancelación controlada"' src/feclora/gui_gtk.py "GTK operation cancellation must remain a distinct guarded section."
require_text 'title="Operaciones registradas"' src/feclora/gui_gtk.py "GTK operation records must be grouped separately from controls."
require_text 'title="Estado de recuperación"' src/feclora/gui_gtk.py "GTK ddrescue history must group persistent recovery status."
require_text 'title="Trabajos ddrescue"' src/feclora/gui_gtk.py "GTK ddrescue records must use a semantic history group."
require_text 'row\.set_activatable_widget\(cancel\)' src/feclora/gui_gtk.py "GTK operation cancellation rows must preserve direct button activation."
require_text 'self\.operation_confirmation\.set_placeholder_text\("CANCEL <operation_id>"\)' src/feclora/gui_gtk.py "GTK operation cancellation must retain the exact confirmation phrase."


require_text 'title="Consulta del historial"' src/feclora/gui_gtk.py "GTK remote and deployment histories must group status and refresh controls."
require_text 'title="Definición del trabajo"' src/feclora/gui_gtk.py "GTK remote jobs must group validated definition creation."
require_text 'title="Importar definición"' src/feclora/gui_gtk.py "GTK remote jobs must group import source controls."
require_text 'title="Servicio de despliegue"' src/feclora/gui_gtk.py "GTK remote jobs must group guarded deployment service actions."
require_text 'job_row\\.set_activatable_widget\\(self\\.remote_job_select\\)' src/feclora/gui_gtk.py "GTK remote job selection must remain directly activatable."
require_text 'title="Historial de clientes"' src/feclora/gui_gtk.py "GTK client job history must use a semantic preferences group."
require_text 'client_refresh_row\\.set_activatable_widget\\(refresh\\)' src/feclora/gui_gtk.py "GTK client history refresh must remain directly activatable."


require_text 'title="Conexión e inspección autenticada"' src/feclora/gui_gtk.py "GTK client jobs must group authenticated server inspection controls."
require_text 'title="Transferencia y protección"' src/feclora/gui_gtk.py "GTK client jobs must group transfer protection options."
require_text 'capture_group\\("Ejecución y seguimiento"' src/feclora/gui_gtk.py "GTK client jobs must group execution and status controls."
require_text 'host_row\\.set_activatable_widget\\(self\\.client_server_host\\)' src/feclora/gui_gtk.py "GTK client server host row must preserve direct activation."
require_text 'self\.client_confirmation\.set_placeholder_text\("Escribe exactamente ERASE destino o READ destino TO identidad"\)' src/feclora/gui_gtk.py "GTK client jobs must retain exact destructive/read confirmation guidance."

require_text 'add_group\\("Repositorios SSHFS, NFS y SMB/CIFS"' src/feclora/gui_gtk.py "GTK repository definitions must use a semantic libadwaita preferences group."
require_text 'add_group\\("Repositorios S3"' src/feclora/gui_gtk.py "GTK S3 definitions must use a semantic libadwaita preferences group."
require_text 'add_group\\("Credenciales systemd cifradas"' src/feclora/gui_gtk.py "GTK protected credential management must use a semantic preferences group."
require_text 'add_row\(remote_group, "Clave SSH protegida", self\.remote_identity\)' src/feclora/gui_gtk.py "GTK SSH identity selection must remain in the SSHFS repository preferences."
require_text 'add_row\(remote_group, "Credencial SMB protegida", self\.remote_credential\)' src/feclora/gui_gtk.py "GTK SMB credential selection must remain in the SMB repository preferences."
require_text 'self\.remote_credential\.set_visible\(provider == "smb"\)' src/feclora/gui_gtk.py "GTK SMB credentials must remain conditional on the SMB provider."
require_text 'self\.remote_identity\.set_visible\(provider == "sshfs"\)' src/feclora/gui_gtk.py "GTK SSH identities must remain conditional on the SSHFS provider."
require_text 'self\.api\.submit\("put_systemd_credential"' src/feclora/gui_gtk.py "GTK repository credential import must continue using the privileged credential API."

require_text 'capture_group\\("Inventario y selección de operación"' src/feclora/gui_gtk.py "GTK local operations must group operation selection in libadwaita preferences."
require_text 'capture_group\\("Origen, destino e imagen"' src/feclora/gui_gtk.py "GTK local operations must group source and target selection."
require_text 'capture_group\\("Confirmación y generación"' src/feclora/gui_gtk.py "GTK local operations must separate destructive confirmation and artifact generation."
require_text 'capture_group\\("Formato y protección"' src/feclora/gui_gtk.py "GTK local operations must group format and encryption controls."
require_text 'capture_group\\("Recuperación ddrescue"' src/feclora/gui_gtk.py "GTK ddrescue controls must use a semantic preferences group."
require_text 'title="Ejecución y seguimiento"' src/feclora/gui_gtk.py "GTK local operation progress and cancellation must use a semantic preferences group."
require_text 'self\.capture_passphrase = Gtk\.PasswordEntry\(\)' src/feclora/gui_gtk.py "GTK local operation age passphrases must remain masked."
require_text 'self\.capture_confirmation\.set_placeholder_text\("ERASE /dev/… o BUILD <imagen>"\)' src/feclora/gui_gtk.py "GTK destructive operation confirmation guidance must remain visible."
require_text 'self\.capture_retry_row\.set_visible\(is_recovery\)' src/feclora/gui_gtk.py "GTK ddrescue controls must hide and show as complete preference rows."
require_text 'self\.capture_btrfs_source_row\.set_visible\(is_btrfs_capture\)' src/feclora/gui_gtk.py "GTK Btrfs capture controls must hide and show as complete preference rows."


require_text 'title="Repositorio e imagen"' src/feclora/gui_gtk.py "GTK image selection must use a semantic preferences group."
require_text 'title="Inspección y verificación"' src/feclora/gui_gtk.py "GTK image inspection and integrity verification must be grouped."
require_text 'title="Exploración y descarga"' src/feclora/gui_gtk.py "GTK image browsing and download controls must be grouped."
require_text 'title="Extracción de particiones"' src/feclora/gui_gtk.py "GTK partition extraction controls must be grouped."
require_text 'title="Resultado y actividad"' src/feclora/gui_gtk.py "GTK image operation results must have a dedicated group."
require_text 'self\.image_catalog_stack\.set_visible_child_name\("loading"\)' src/feclora/gui_gtk.py "GTK image catalog loading state must remain explicit."
require_text 'self\.image_cancel\.set_sensitive\(False\)' src/feclora/gui_gtk.py "GTK image extraction cancellation must remain disabled until accepted."
require_text 'self\.api\.submit\("verify_image"' src/feclora/gui_gtk.py "GTK image integrity verification must retain its privileged API request."
require_text 'self\.api\.submit\("extract_partition_image"' src/feclora/gui_gtk.py "GTK partition extraction must retain its privileged API request."


require_text 'title="Idioma de la interfaz"' src/feclora/gui_gtk.py "GTK welcome must group interface language preferences."
require_text 'title="Distribución del teclado"' src/feclora/gui_gtk.py "GTK welcome must group keyboard layout preferences."
require_text 'title="Acciones"' src/feclora/gui_gtk.py "GTK welcome actions must use a semantic preferences group."
require_text 'self\._keyboard_layout_applied\(layout\)' src/feclora/gui_gtk.py "GTK must retain the selected keyboard layout after a successful apply."
require_text 'title="Estado del inventario"' src/feclora/gui_gtk.py "GTK inventory must group its live device count in libadwaita preferences."
require_text 'title="Dispositivos detectados"' src/feclora/gui_gtk.py "GTK inventory must label the device summary semantically."
require_text 'title="Acciones"' src/feclora/gui_gtk.py "GTK inventory refresh must use a semantic action group."
require_text 'Adw\.StatusPage\(' src/feclora/gui_gtk.py "GTK inventory must provide a native empty state."
require_text 'Adw\.ActionRow\(' src/feclora/gui_gtk.py "GTK inventory devices must use semantic action rows."
require_text 'self\._append_inventory_device\(group, child, depth \+ 1\)' src/feclora/gui_gtk.py "GTK inventory must preserve nested device hierarchy."
require_text 'title="Identidad del equipo"' src/feclora/gui_gtk.py "GTK overview must group host and platform identity."
require_text 'title="Configuración de Feclora"' src/feclora/gui_gtk.py "GTK overview must group server/client configuration status."
require_text 'title="Servicios del sistema"' src/feclora/gui_gtk.py "GTK overview must group local service status."
require_text 'title="Acciones"' src/feclora/gui_gtk.py "GTK overview refresh must have a dedicated action group."
require_text 'self\.overview_configuration\.set_text\(' src/feclora/gui_gtk.py "GTK overview must render server and client configuration status."
require_text 'self\.overview_services\.set_text\(' src/feclora/gui_gtk.py "GTK overview must render local service status."
require_text 'self\.api\.submit\("status"' src/feclora/gui_gtk.py "GTK overview must retain the local status API request."

if (( ERRORS > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'

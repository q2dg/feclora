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

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston|firefox)([[:space:]]|$)' \
  "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "The Live image package set must not include Cockpit, Weston or Firefox."
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

if (( ERRORS > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'

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

require_text 'self\.api\.submit\("pxe_service_status"' src/feclora/gui_gtk.py "GTK server status must include PXE service health."
require_text 'status\.get\("certificate_status"\)' src/feclora/gui_gtk.py "GTK system status must include certificate health."

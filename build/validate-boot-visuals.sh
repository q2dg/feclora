#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BUILD="$ROOT_DIR/build/build-iso.sh"
SERVICE="$ROOT_DIR/src/feclora/data/feclora-kiosk.service"
LAUNCH="$ROOT_DIR/src/feclora/data/feclora-kiosk-launch"
FIREFOX_LAUNCH="$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-launch"
DIAGNOSTICS="$ROOT_DIR/src/feclora/data/feclora-kiosk-diagnostics"
RECOVERY="$ROOT_DIR/src/feclora/data/feclora-recovery-boot.service"
PAM="$ROOT_DIR/src/feclora/data/feclora-kiosk.pam"
THEME="$ROOT_DIR/src/feclora/data/plymouth"

fail() {
  printf 'BOOT VISUAL VALIDATION ERROR: %s\n' "$*" >&2
  exit 1
}

# Packages and source assets required by the graphical boot path.
grep -Fq 'retries=20' "$KS" || fail "Anaconda DNF retry count is not increased for transient mirror failures."
grep -Fq 'timeout=60' "$KS" || fail "Anaconda DNF download timeout is not increased."
grep -Fq 'max_parallel_downloads=3' "$KS" || fail "Anaconda DNF parallel downloads are not bounded."
for package in plymouth plymouth-plugin-script librsvg2-tools weston firefox cockpit-ws-selinux policycoreutils-python-utils; do
  grep -Fxq "$package" "$KS" || fail "Required boot/kiosk package is missing: $package"
done
if grep -Eiq '^[[:space:]]*xorg-x11-server-Xwayland([[:space:]]|$)' "$KS"; then
  fail "Pure Wayland kiosk image must not install XWayland."
fi

grep -Fq "groupadd --system feclora-logs" "$KS" || fail "Dedicated read-only diagnostics group is not created."
grep -Fq "useradd --create-home --groups feclora-logs,systemd-journal --shell /bin/bash pepe" "$KS" || fail "Temporary local console user must have read-only journal and diagnostics access."
grep -Fq "usermod --append --groups feclora-logs feclora-kiosk" "$KS" || fail "Kiosk user is not assigned to the diagnostics group."
grep -Fq "pepe:1234" "$KS" || fail "Temporary local console password is not configured."
grep -Fq "enable firewalld.service" "$KS" || fail "Guest firewall is not enabled."
if grep -Eq "openssh-server|sshd\.service|sshd_config|add-service=ssh" "$KS"; then
  fail "Diagnostic SSH server configuration must not be included in the ISO."
fi
[[ -s "$DIAGNOSTICS" ]] || fail "Offline kiosk diagnostics collector is missing."
[[ -s "$FIREFOX_LAUNCH" ]] || fail "Firefox kiosk client launcher and exit logger are missing."
grep -Fq 'feclora-kiosk-firefox-launch" "$TARGET_ROOT/usr/libexec/feclora/feclora-kiosk-firefox-launch"' "$KS" || fail "Kickstart does not install the Firefox kiosk client launcher."
grep -Fq 'journalctl --boot' "$DIAGNOSTICS" || fail "Diagnostics collector does not capture the current boot journal."
grep -Fq 'lspci -nnk' "$DIAGNOSTICS" || fail "Diagnostics collector does not capture graphics hardware and drivers."
grep -Fq 'diagnostics.tar.gz' "$DIAGNOSTICS" || fail "Diagnostics collector does not create a portable log archive."
grep -Fq 'chgrp feclora-logs "$REPORT"' "$DIAGNOSTICS" || fail "Diagnostic report is not readable by the dedicated logs group."
grep -Fq 'chmod 0640 "$REPORT"' "$DIAGNOSTICS" || fail "Diagnostic report permissions are not read-only for the logs group."
grep -Fq 'chmod 0640 "$LOG_DIR/launcher.log"' "$DIAGNOSTICS" || fail "Launcher log is not readable by the dedicated logs group."
grep -Fq 'install -d -o feclora-kiosk -g feclora-logs -m 2750 /var/log/feclora-kiosk' "$KS" || fail "Kiosk log directory does not preserve the diagnostics group."
grep -Fq 'ExecStopPost=+/usr/libexec/feclora/feclora-kiosk-diagnostics stop' "$SERVICE" || fail "Kiosk exit must trigger a final diagnostics snapshot."
grep -Fq 'feclora-kiosk-diagnostics' "$KS" || fail "Kickstart does not install the offline diagnostics collector."
[[ -s "$THEME/feclora.plymouth" ]] || fail "Plymouth theme descriptor is missing."
[[ -s "$THEME/feclora.script" ]] || fail "Plymouth script is missing."
[[ -s "$THEME/feclora-logo-dark.svg" ]] || fail "Plymouth source logo is missing."
grep -Fxq 'ModuleName=script' "$THEME/feclora.plymouth" || fail "Feclora must use the script Plymouth renderer."
grep -Fxq 'ScriptFile=feclora.script' "$THEME/feclora.plymouth" || fail "Plymouth script entry point is not configured."
grep -Fq 'Image("feclora-logo.png")' "$THEME/feclora.script" || fail "Plymouth script does not load the generated PNG logo."
grep -Fq 'rsvg-convert --width=640 --output=' "$KS" || fail "Kickstart does not generate the PNG logo."
grep -Fq 'test -s ' "$KS" || fail "Kickstart does not verify the generated logo."
grep -Fq 'plymouth-set-default-theme feclora -R' "$KS" || fail "Feclora Plymouth theme is not selected and rebuilt into initramfs."
if grep -Fq 'Colordrawn_Sun.svg' "$KS"; then fail "External diagnostic Plymouth artwork must not replace Feclora branding."; fi
grep -Fq 'feclora-logo.png' "$KS" || fail "Feclora logo is not installed in the initramfs."
grep -Fq 'Theme=feclora' "$KS" || fail "Feclora theme is not verified in Plymouth configuration."
grep -Fq 'add_dracutmodules+=" plymouth "' "$KS" || fail "Plymouth dracut module is not explicitly included."
grep -Fq 'install_items+=' "$KS" || fail "Plymouth assets are not explicitly included in initramfs."
grep -Fq '/usr/lib64/plymouth/script.so' "$KS" || fail "Plymouth script renderer plugin is not included in initramfs."
grep -Fq 'lsinitrd -m' "$KS" || fail "Kickstart does not inspect initramfs module contents."
grep -Fq 'lsinitrd -f /etc/plymouth/plymouthd.conf' "$KS" || fail "Kickstart does not verify the initramfs Plymouth theme selection."
grep -Fq 'feclora/feclora-logo.png' "$KS" || fail "Kickstart does not verify the Feclora logo in the initramfs."

# Keep the recovery service's systemd sandbox path present before namespace setup.
grep -Fxq 'RuntimeDirectory=feclora' "$RECOVERY" || fail "Recovery service does not create its writable runtime directory."
grep -Fxq 'ReadWritePaths=/var/lib/feclora /run/feclora' "$RECOVERY" || fail "Recovery service writable paths do not match its runtime directory."

# The ISO bootloader is generated by Lorax templates, not installed-system GRUB.
grep -Fq 's/^set default=.*/set default=' "$BUILD" || fail "Lorax template override does not select the first boot entry."
grep -Fq 'set timeout_style=hidden' "$BUILD" || fail "Lorax menu is not configured as hidden."
grep -Fq 'set timeout=0' "$BUILD" || fail "Lorax menu timeout is not zero."
grep -Fq -- '--lorax-templates' "$BUILD" || fail "ISO build does not pass the customized Lorax templates."
grep -Fq 'rhgb quiet vt.global_cursor_default=0' "$BUILD" || fail "Graphical boot must enable the Plymouth splash without diagnostic console output."
if grep -Fq 'rd.plymouth=0' "$BUILD"; then fail "ISO boot arguments must not disable Plymouth."; fi

COCKPIT_KIOSK_SERVICE="$ROOT_DIR/src/feclora/data/feclora-cockpit-kiosk.service"
grep -Fq 'systemctl --root=/ mask cockpit.socket' "$KS" || fail "The standard Cockpit socket must be masked so it cannot claim port 9090."
if grep -Eq 'systemctl --root=/ enable cockpit\\.socket|cockpit\\.socket\\.d|cockpit\\.service\\.d|9091' "$KS"; then
  fail "Kickstart must not enable standard Cockpit socket activation or configure a second kiosk port."
fi
grep -Fq 'Requires=feclora-cockpit-certificate.service feclora-local-operation-recovery.service' "$COCKPIT_KIOSK_SERVICE" || fail "Local Cockpit kiosk must require certificate provisioning and local-operation recovery."
grep -Fq 'After=local-fs.target feclora-cockpit-certificate.service feclora-local-operation-recovery.service' "$COCKPIT_KIOSK_SERVICE" || fail "Local Cockpit kiosk must start after its certificate and recovery prerequisites."
grep -Fq -- '--address 127.0.0.1 --port 9090 --local-session /usr/bin/cockpit-bridge' "$COCKPIT_KIOSK_SERVICE" || fail "Feclora must own port 9090 with a loopback-only local session."
if grep -Fq '9091' "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json"; then
  fail "Kiosk URL and readiness probe must not retain the obsolete port 9091."
fi
grep -Fxq "cockpit-bridge" "$KS" || fail "Cockpit bridge package is missing."
grep -Fq "restorecon -v /usr/libexec/cockpit-ws /usr/bin/cockpit-bridge" "$KS" || fail "Cockpit RPM executables are not relabeled with their SELinux policy contexts."
grep -Fq -- "--local-session /usr/bin/cockpit-bridge" "$ROOT_DIR/src/feclora/data/feclora-cockpit-kiosk.service" || fail "Cockpit kiosk must invoke the packaged cockpit-bridge path."
grep -Fq 'systemd-detect-virt --vm' "$LAUNCH" || fail "Kiosk must detect the VM vendor before selecting a renderer."
grep -Fq 'if [[ "$virt_vendor" == "oracle" ]]' "$LAUNCH" || fail "Pixman must be restricted to VirtualBox guests."
grep -Fq 'WESTON_ARGS+=(--renderer=pixman)' "$LAUNCH" || fail "VirtualBox guests must use Weston's Pixman software renderer."
grep -Fq "cockpit-bridge" "$DIAGNOSTICS" || fail "Diagnostics do not verify the Cockpit bridge package and executable."
# The live overlay may lose RPM xattrs while the ISO is assembled; relabel the two packaged executables before Cockpit starts.
grep -Fq 'ExecStartPre=+/usr/sbin/restorecon -F /usr/libexec/cockpit-ws /usr/bin/cockpit-bridge' "$ROOT_DIR/src/feclora/data/feclora-cockpit-kiosk.service" || fail "Cockpit executables are not relabeled before systemd executes them."
# Ensure Weston uses the DRM backend and kiosk shell without loading XWayland.
if grep -Fxq 'Environment=LIBSEAT_BACKEND=logind' "$SERVICE"; then fail "wlroots libseat environment must not be carried over to Weston."; fi
grep -Fxq 'Environment=XDG_RUNTIME_DIR=/run/feclora-kiosk' "$SERVICE" || fail "Kiosk XDG_RUNTIME_DIR does not use its systemd-managed runtime directory."
grep -Fxq 'RuntimeDirectory=feclora-kiosk' "$SERVICE" || fail "Systemd must create the kiosk runtime directory before sandbox setup."
grep -Fxq 'RuntimeDirectoryMode=0700' "$SERVICE" || fail "Kiosk runtime directory must be private."
grep -Fxq 'ExecStartPre=+/usr/bin/chvt 1' "$SERVICE" || fail "Kiosk VT1 must be activated before Weston requests a DRM session."
grep -Fq '"/run/feclora-kiosk/wayland-*"' "$SERVICE" || fail "Kiosk readiness watcher does not monitor the systemd-managed Wayland socket directory."
if grep -Fq 'chvt 1' <(sed -n '/^ExecStartPost=/p' "$SERVICE"); then
  fail "Kiosk must not wait for the Wayland socket before activating its VT; that deadlocks DRM session acquisition."
fi
grep -Fq 'WESTON_ARGS=(--backend=drm-backend.so --shell=kiosk-shell.so --no-config)' "$LAUNCH" || fail "Kiosk launcher must select Weston's DRM backend, kiosk shell and isolated configuration."
grep -Fq 'exec /usr/bin/weston "${WESTON_ARGS[@]}" -- /usr/libexec/feclora/feclora-kiosk-firefox-launch' "$LAUNCH" || fail "Kiosk launcher must start the logging Firefox wrapper as Weston's Wayland child."
grep -Fq '/usr/bin/firefox "$@" >>"$LOG_FILE" 2>&1' "$FIREFOX_LAUNCH" || fail "Firefox wrapper must execute the packaged browser and capture its output."
grep -Fq 'Firefox exited at' "$FIREFOX_LAUNCH" || fail "Firefox wrapper must record the browser exit timestamp and status."
grep -Fq 'WESTON_ARGS+=(--log="$LOG_DIR/weston.log")' "$LAUNCH" || fail "Weston compositor output must be captured in its dedicated log."
if grep -Eq -- '(^|[[:space:]])--xwayland([[:space:]]|$)|xwayland\.so' "$LAUNCH"; then fail "Pure Wayland kiosk must not enable or load XWayland."; fi
grep -Fxq 'export XDG_RUNTIME_DIR=/run/feclora-kiosk' "$LAUNCH" || fail "Weston and Firefox must use the systemd-managed runtime directory."
grep -Fxq 'export MOZ_ENABLE_WAYLAND=1' "$LAUNCH" || fail "Firefox is not explicitly configured for native Wayland."
grep -Fq '/usr/libexec/feclora/feclora-kiosk-firefox-launch --kiosk --private-window --new-instance' "$LAUNCH" || fail "Firefox must start in private kiosk mode through the exit-logging wrapper."
grep -Fq '"DisablePrivateBrowsing": false' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox private-window kiosk launch must not be disabled by enterprise policy."
grep -Fq '"http://localhost/*"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox website filter must allow Cockpit localhost HTTP requests."
grep -Fq '"ws://localhost/*"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox website filter must allow Cockpit localhost WebSocket requests."
grep -Fq 'Kiosk preflight elapsed: ${SECONDS}s.' "$LAUNCH" || fail "Kiosk launcher must report startup preflight duration."
grep -Fq '"UserMessaging"' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox onboarding and recommendation messages must be disabled for kiosk use."
grep -Fq '"SkipOnboarding": true' "$ROOT_DIR/src/feclora/data/feclora-kiosk-firefox-policies.json" || fail "Firefox first-run onboarding must be disabled."
grep -Fq 'weston --version' "$DIAGNOSTICS" || fail "Diagnostics do not record the Weston version."
grep -Fq 'KIOSK_UID' "$DIAGNOSTICS" || fail "Diagnostics do not inspect the PAM/logind runtime directory."
grep -Fq 'Weston XDG_RUNTIME_DIR: /run/feclora-kiosk' "$DIAGNOSTICS" || fail "Diagnostics do not inspect Weston's runtime directory."
grep -Fq 'using Weston renderer autodetection.' "$LAUNCH" || fail "Physical-machine Weston renderer autodetection must be logged."
grep -Fq 'tee -a "$LOG_DIR/launcher.log"' "$LAUNCH" || fail "Kiosk launcher must preserve a plain-text diagnostic log."
grep -Fq 'section "WESTON COMPOSITOR LOG"' "$DIAGNOSTICS" || fail "Diagnostics must include the dedicated Weston compositor log."
grep -Fq 'section "FIREFOX KIOSK CLIENT LOG"' "$DIAGNOSTICS" || fail "Diagnostics must include Firefox output and exit status."
grep -Fq 'firefox.log' "$DIAGNOSTICS" || fail "Firefox log must be included in the portable diagnostic archive."
grep -Fq '/dev/dri' "$LAUNCH" || fail "Kiosk launcher must record DRM device availability."
grep -Fq '/dev/tcp/127.0.0.1/9091' "$LAUNCH" || fail "Kiosk launcher must check the local Cockpit endpoint."
grep -Fq 'for attempt in {1..15}' "$LAUNCH" || fail "Cockpit readiness check must be bounded to 15 seconds."
grep -Fq 'Starting Weston/Firefox anyway' "$LAUNCH" || fail "Kiosk must start Weston even when Cockpit is unavailable."
grep -Fxq 'Wants=feclora-cockpit-kiosk.service' "$SERVICE" || fail "Cockpit must be optional for the graphical kiosk."
if grep -Fxq 'Requires=feclora-cockpit-kiosk.service' "$SERVICE"; then
  fail "Cockpit failure must not stop the graphical kiosk."
fi
grep -Fq 'ausearch -m AVC,USER_AVC -ts boot' "$DIAGNOSTICS" || fail "Diagnostics do not collect SELinux access denials."
grep -Fq 'ls -lZ /usr/libexec/cockpit-ws' "$DIAGNOSTICS" || fail "Diagnostics do not capture Cockpit executable SELinux labels."
grep -Fxq 'Restart=always' "$SERVICE" || fail "Kiosk must recover after its browser/compositor exits."
grep -Fq 'wayland-*' "$SERVICE" || fail "Kiosk readiness diagnostics must monitor Weston's Wayland socket."
grep -Fq '/var/log/feclora-kiosk' "$SERVICE" || fail "Kiosk log directory must be writable inside the service sandbox."
grep -Fq 'ReadWritePaths=/var/lib/feclora-kiosk /var/log/feclora-kiosk' "$SERVICE" || fail "Kiosk writable paths must be limited to persistent data and logs; systemd manages /run/feclora-kiosk."
if grep -Fq '/run/user' <(sed -n '/^ReadWritePaths=/p' "$SERVICE"); then
  fail "Do not expose PAM's late-created /run/user tree through ReadWritePaths."
fi
grep -Fq 'pam_permit.so' "$PAM" || fail "Password-locked kiosk account must not be rejected by PAM authentication."
grep -Fxq 'StartLimitIntervalSec=0' "$SERVICE" || fail "Kiosk restart recovery must not be permanently rate-limited."

# Validate the Plymouth-to-kiosk DRM handoff and the final graphical target.
if grep -Eq '^After=.*plymouth-quit-wait\.service' "$SERVICE"; then
  fail "Kiosk must not wait for Plymouth to disappear before starting Weston."
fi
grep -Fxq 'Before=plymouth-quit.service graphical.target' "$SERVICE" || fail "Plymouth must not quit before the kiosk startup handoff."
grep -Fq 'plymouth deactivate || true' "$SERVICE" || fail "Kiosk must ask Plymouth to release DRM while retaining its splash frame."
grep -Fq 'pgrep -u feclora-kiosk -x firefox' "$SERVICE" || fail "Plymouth splash must remain until the Firefox kiosk process starts."
grep -Fq 'plymouth quit --retain-splash' "$SERVICE" || fail "Plymouth must retain its final frame during the Firefox handoff."
grep -Fxq 'Wants=dbus.socket systemd-logind.service plymouth-start.service' "$SERVICE" || fail "Kiosk must pull in D-Bus, logind and Plymouth."
grep -Fxq 'PAMName=feclora-kiosk' "$SERVICE" || fail "Kiosk must use its dedicated PAM session."
grep -Fxq 'StandardInput=tty-fail' "$SERVICE" || fail "Kiosk must fail clearly if it cannot acquire its VT."
grep -Fxq 'WantedBy=graphical.target' "$SERVICE" || fail "Kiosk must be enabled for graphical.target."
[[ -s "$PAM" ]] || fail "Dedicated kiosk PAM configuration is missing."
grep -Fq 'etc/pam.d/feclora-kiosk' "$KS" || fail "Kickstart does not install the dedicated kiosk PAM stack."
grep -Fq 'enable feclora-kiosk.service' "$KS" || fail "ISO must enable the Weston/Firefox kiosk service."
grep -Fq 'var/log/feclora-kiosk' "$KS" || fail "Kickstart does not create the offline-retrievable kiosk log directory."
grep -Fq 'rm -f /etc/kernel/cmdline' "$KS" || fail "Kickstart must remove Anaconda's installed-system kernel command line from the LiveOS image."
grep -Fq '$2 != "/"' "$KS" || fail "Kickstart must remove Anaconda's installed-root fstab entry from the LiveOS image."
grep -Fq 'enable feclora-cockpit-certificate.service feclora-cockpit-kiosk.service' "$KS" || fail "Kickstart does not enable local Cockpit kiosk dependencies."
grep -Fq 'set-default graphical.target' "$KS" || fail "Live system default target is not graphical.target."
grep -Fq 'unmask getty@tty1.service' "$KS" || fail "Diagnostic ISO must leave tty1 available for display isolation."
grep -Fq 'mask getty@tty3.service getty@tty4.service getty@tty5.service getty@tty6.service' "$KS" || fail "Only unused VTs 3-6 may have getty masked." 
if grep -Fq 'mask getty@tty2.service' "$KS"; then fail "Diagnostic VT2 must remain available for the pepe console account."; fi

printf 'Boot visual configuration checks passed. ISO build and BIOS/UEFI boot are not verified.\n'

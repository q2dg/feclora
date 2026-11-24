# GTK4 migration

## Status

The migration is staged. Textual remains the production boot interface until
every operator workflow has been ported, tested and accepted. All 14 navigation
pages now have GTK content, but several are read-only or have incomplete controls;
page presence is not feature parity.

The native frontend is `gui_gtk.py`, built with GTK4 and PyGObject.
`gtk_api.py` dispatches allowlisted API calls in worker threads and marshals
results onto the GLib main loop. All navigation content is vertically scrollable.

Implemented GTK workflows:

- Overview, nested storage inventory, system status, server bootstrap, confirmed certificate renewal/TLS key rotation, and PXE profile validation/start/stop controls.
- Whole-disk RAW/QCOW2, partition, LVM, Stratis XFS and Btrfs send/receive capture.
- ddrescue recovery/resume and finalization; progress polling and cancellation.
- Disk, partition, LVM and Stratis restoration; proportional disk restore with
  kernel major:minor identity checks and a strictly smaller target preflight.
- Disk and partition cloning with exact destructive confirmation.
- QCOW2 P2V capture; legacy QCOW2 bundle import from local/mounted filesystem repositories and export from S3 to local/mounted filesystem repositories.
- Recovery ISO and deployment-bundle generation with repository state checks.
- Image integrity verification, verified partition-table inspection, filesystem
  browsing, safe file download under `~/Downloads`, and partition extraction.
- Single-use restore profiles bound to stable WWN/serial identities, with
  timezone-aware expiry and exact destination confirmation.
- NetworkManager IPv4 DHCP/static configuration with the existing 120-second
  rollback checkpoint.
- Repository inventory and management: SSHFS/S3 definition creation, remote repository check/mount/unmount/removal with mount-state guards, S3 check/removal, encrypted systemd credential import/removal with backend reference checks, remote deployment/client history, operation log with exact-phrase cancellation, and persistent ddrescue recovery history.

Known remaining migration work includes PXE answer publication/revocation and the age passphrase workflow; full certificate lifecycle parity beyond renewal/key rotation; provider-specific NFS/SMB definition flows (SSHFS and S3 definition editing are available);
remote job creation/inspection/import/reconciliation and deployment controls;
client-job actions; remaining operational workflows
present in Textual. These pages must not be treated as complete merely because
their status/history views are present.

The CustomTkinter/Tk prototype and its dedicated tests have been removed.
GTK4/PyGObject is the sole graphical frontend target; no Tk or X11 compatibility
runtime is retained. The frontend is not production-ready.

## Target runtime: native Wayland only

The intended appliance stack is Weston on its DRM/KMS backend with
`kiosk-shell`, running the GTK4 application as a native Wayland client.

The GTK process must set `GDK_BACKEND=wayland` and must fail closed if
`WAYLAND_DISPLAY` is absent. Do not install, enable, start, or fall back to
XWayland, Xorg, Openbox, or another X11 compatibility layer. Do not set
`DISPLAY`. Fedora's system GTK4 and PyGObject packages provide the runtime;
do not vendor GTK or install Python GUI bindings from PyPI.

Weston is to be started from a dedicated tty1 systemd session with DRM/KMS and
kiosk-shell. The exact Fedora 45 package names, Weston CLI/configuration,
logind/seat permissions, and service lifecycle must be verified before the
runtime is added to the ISO. The GUI service must start only after Weston has
created its Wayland socket. No display manager or general-purpose desktop
session is required.

## Migration sequence

1. Keep Textual bootable while sharing catalog data and introducing the GTK/GLib
   API bridge.
2. Port and structurally test the GTK shell, overview, inventory and core local
   storage operations.
3. Complete image inspection/browsing/extraction, restore profiles, network and
   remaining local operations, including P2V import/export and full preflight parity.
4. Complete server/PXE, repository management, remote deployment, client-job and
   remaining history actions. Keep operational controls functional rather than
   replacing them with read-only summaries.
5. Run unit/contract tests and `build/validate.sh`; then add Weston DRM +
   kiosk-shell configuration, a native Wayland-only service and VM smoke tests.
   Keep tty2 as the independent maintenance/recovery path.
6. Switch the default boot service only after feature parity and BIOS/UEFI
   acceptance. Then remove Textual and obsolete text-boot checks.

## Kiosk and recovery requirements

The final kiosk session must present the GTK application fullscreen without
decorations or ordinary close controls. GTK's close-request handling is
supplementary; Weston kiosk-shell and the compositor/session configuration
must enforce the kiosk policy.

The operator must retain an independent maintenance path on tty2. A failed
GUI must not prevent access to that path or leave durable storage operations
without their existing systemd recovery handling.

## Acceptance criteria

- All 14 current navigation pages and every implemented operation are present in the
   migrated frontend before the production boot switch.
- All 25 interface-language catalogs remain available.
- API requests remain restricted to the existing root-owned allowlisted helper.
- Long-running actions do not block the GTK/GLib main loop; progress and
  cancellation remain responsive.
- Destructive operations retain their exact confirmation and preflight checks.
- The process runs with `GDK_BACKEND=wayland`, a valid Wayland socket, and no
  X11/XWayland runtime or fallback.
- BIOS and UEFI VM smoke tests prove that the GUI has rendered before reporting
  readiness.
- Manual kiosk testing verifies fullscreen behavior, no close/minimize route,
  keyboard and pointer operation, VT2 maintenance access and recovery after
  application restart.

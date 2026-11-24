# GTK4 migration

## Status

The migration is staged. The existing Textual application remains the production
boot interface until every operator workflow has been ported and accepted.

The native frontend is `gui_gtk.py`, built with GTK4 and PyGObject.
`gtk_api.py` dispatches the existing allowlisted API calls in worker threads
and marshals results/events onto the GLib main loop. The overview reads real
system status, the inventory renders nested storage devices, and the operations
page supports whole-disk capture (RAW/QCOW2), partition capture, LVM logical-volume
capture, Stratis XFS filesystem capture and incremental Btrfs subvolume send/receive streams,
compression, age encryption, progress polling and cancellation through the privileged API.
The operations page also exposes ddrescue disk recovery (retry-pass and resume
controls), recovery finalization, whole-disk/partition/logical-volume/Stratis restoration
and whole-disk/partition cloning. Restore and clone actions retain exact destructive
confirmation phrases and use the privileged asynchronous operation API. Recovery ISO
and deployment-bundle workflows remain in Textual; other
navigation pages are still placeholders. This frontend is not production-ready.

The CustomTkinter/Tk prototype and its dedicated tests have been removed.
GTK4/PyGObject is the sole graphical frontend target; no Tk or X11 compatibility
runtime is retained.

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

1. Keep the current Textual application bootable while sharing catalog data
   and introducing the GTK/GLib API bridge.
2. Port the welcome/setup flow and shared GTK application shell. The initial
   overview and storage inventory pages now call the real backend and render
   live results; structural regression tests cover these paths.
3. Complete the operations page: port the remaining capture modes and the
   recovery ISO/deployment-bundle actions, preserving
   confirmation phrases, validation, progress events, cancellation and error handling.
4. Port inventory, image browsing, restore profiles, network, repositories,
   server/PXE, remote deployment and recovery workflows; do not replace
   operational controls with read-only placeholders.
5. Add Weston DRM + kiosk-shell configuration, a native Wayland-only service,
   graphical readiness reporting and VM smoke tests. Keep tty2 as the
   independent maintenance/recovery path.
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

- All 14 current navigation pages and every implemented operation are present.
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

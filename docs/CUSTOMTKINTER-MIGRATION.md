# CustomTkinter migration

## Status

The migration is staged. The existing Textual application remains the production
boot interface until every operator workflow has been ported and accepted.

The first implementation slice establishes three reusable pieces:

- `ui_catalog.py` contains language, navigation and operator-choice data shared
  by both frontends.
- `gui_api.py` dispatches the existing allowlisted API calls in worker threads
  and returns events/results to Tk on its main thread.
- `gui.py` is the initial fullscreen, borderless CustomTkinter shell. Its
  operational navigation entries are intentionally placeholders and must not
  be enabled as the appliance's production interface yet.

## Target runtime

The intended appliance stack is Weston on its DRM/KMS backend, Weston
kiosk-shell, XWayland, Fedora's Tkinter runtime and CustomTkinter. Weston is the
Wayland compositor and kiosk shell; XWayland is only the X11 compatibility
server needed by Tkinter. The Xorg server and Openbox are not part of this
design. Weston documents kiosk-shell as a single-app shell that makes
top-level windows fullscreen, and supports XWayland clients.

CustomTkinter is pinned in `requirements-gui.txt` and will be installed into a
private application vendor directory during the runtime image build, rather
than modifying Fedora's system Python.

Weston is to be started from the existing tty1 systemd handoff using the DRM
backend and XWayland support. The kiosk-shell configuration will match the
Feclora X11 window class so the CustomTkinter window occupies the output.
No display manager or general-purpose desktop session is required.

## Migration sequence

1. Keep the current Textual application bootable while extracting frontend-
   independent catalog data and introducing the non-blocking Tk API bridge.
2. Port the welcome/setup flow and shared application shell.
3. Port each existing page and action, preserving confirmation phrases,
   validation, progress events, cancellation and error handling.
4. Port inventory, image browsing, restore profiles, network, repositories,
   server/PXE, remote deployment and recovery workflows; do not replace
   operational controls with read-only placeholders.
5. Add Weston DRM + kiosk-shell + XWayland configuration, graphical service readiness reporting
   and VM smoke tests. Keep tty2 as the independent maintenance/recovery path.
6. Switch the default boot service only after feature parity and BIOS/UEFI
   acceptance. Then remove Textual and its obsolete text-boot checks.

## Kiosk and recovery requirements

The final kiosk session must start after the visible tty1 boot messages. Weston
kiosk-shell must present the CustomTkinter/XWayland window fullscreen, with no
decorations or ordinary minimize/close controls. Tk-level shortcut bindings
are supplementary; Weston kiosk-shell and the compositor/session configuration
must enforce the kiosk policy.

The operator must retain an independent maintenance path on tty2. A failed
GUI must not prevent access to that path or leave durable storage operations
without their existing systemd recovery handling.

## Acceptance criteria

- All 14 current navigation pages and every implemented operation are present.
- All 25 interface-language catalogs remain available.
- API requests remain restricted to the existing root-owned allowlisted helper.
- Long-running actions do not block Tk's event loop; progress and cancellation
  remain responsive.
- Destructive operations retain their exact confirmation and preflight checks.
- BIOS and UEFI VM smoke tests prove that the GUI has rendered before reporting
  readiness.
- Manual kiosk testing verifies fullscreen behavior, no minimize/close route,
  keyboard and pointer operation, VT2 maintenance access and recovery after
  application restart.

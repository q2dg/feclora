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

The intended appliance stack is Xorg, Openbox, Fedora's Tkinter runtime and
CustomTkinter. CustomTkinter is pinned in `requirements-gui.txt` and will be
installed into a private application vendor directory during the runtime
image build, rather than modifying Fedora's system Python.

The X session is to be started from the existing tty1 systemd handoff. No
display manager or general-purpose desktop session is required.

## Migration sequence

1. Keep the current Textual application bootable while extracting frontend-
   independent catalog data and introducing the non-blocking Tk API bridge.
2. Port the welcome/setup flow and shared application shell.
3. Port each existing page and action, preserving confirmation phrases,
   validation, progress events, cancellation and error handling.
4. Port inventory, image browsing, restore profiles, network, repositories,
   server/PXE, remote deployment and recovery workflows; do not replace
   operational controls with read-only placeholders.
5. Add Xorg/Openbox kiosk configuration, graphical service readiness reporting
   and VM smoke tests. Keep tty2 as the independent maintenance/recovery path.
6. Switch the default boot service only after feature parity and BIOS/UEFI
   acceptance. Then remove Textual and its obsolete text-boot checks.

## Kiosk and recovery requirements

The final kiosk session must start after the visible tty1 boot messages, use a
fullscreen undecorated window, and prevent ordinary window-manager minimize,
close and task-switch shortcuts. Tk-level key bindings alone are insufficient:
the Openbox configuration must enforce the kiosk policy too.

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

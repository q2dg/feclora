# GTK4 migration

## Status

The migration is staged. Textual remains the production boot interface until
every operator workflow has been ported, tested and accepted. All 14 navigation
pages now have GTK content, but several are read-only or have incomplete controls;
page presence is not feature parity. The shared catalogue still contains all 25
languages.

A source-level API audit found that every one of the 49 literal
`call_feclora(...)` action names in Textual is represented in the GTK source.
A regression test now checks that relationship. This proves action-name
coverage only; it does not prove that GTK preserves each form's validation,
parameter semantics, confirmation wording, progress, cancellation or failure
handling. Those still require behavioral review and tests.

The native frontend is `gui_gtk.py`, built with GTK4, PyGObject and libadwaita.
The application uses `Adw.Application`/`Adw.ApplicationWindow`, an
`Adw.ToolbarView` with `Adw.HeaderBar` and `Adw.WindowTitle`, an `Adw.Clamp`
for the welcome flow, and an `Adw.ToastOverlay` for transient error feedback.
Navigation uses `Adw.NavigationSplitView` with separately titled sidebar and
content pages, width constraints and a compact-mode back control; selecting a
page updates both the split-view page title and the window title. The existing
fullscreen, undecorated kiosk policy is retained. The graphical
runtime requires Fedora's `libadwaita` RPM; no PyPI
binding, GNOME Shell, Mutter or X11 compatibility layer is required.
`gtk_api.py` dispatches allowlisted API calls in worker threads and marshals
results onto the GLib main loop. All navigation content is vertically scrollable.

Implemented GTK workflows:

- Overview, nested storage inventory, system status, server bootstrap, confirmed certificate renewal/TLS key rotation, PXE profile validation/start/stop, validated unattended-answer publication/revocation, and age recipient/passphrase workflows.
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
- Repository inventory and management: SSHFS/NFS/SMB/S3 definition creation/editing, remote repository check/mount/unmount/removal with mount-state guards, S3 check/removal, encrypted systemd credential import/removal with backend reference checks; remote deployment definition creation/import, exact-phrase arm/cancel/reconcile actions, guarded service start/stop/status; authenticated Client inspection, local disk/partition/healthy-LVM target selection, exact READ/ERASE confirmation, multicast IGMP confirmation, client start/status; operation log with exact-phrase cancellation and persistent ddrescue recovery history.

The current Textual certificate controls—server bootstrap, confirmed
certificate renewal and confirmed TLS keypair rotation—also have GTK
counterparts. Their end-to-end confirmation, success and failure behavior
still needs testing. No additional literal Textual API action was missing in
the source audit, but that does not rule out semantic gaps in individual forms
or workflows. Pages must not be treated as complete merely because their
status/history views are present.

The CustomTkinter/Tk prototype and its dedicated tests have been removed.
GTK4/PyGObject with libadwaita is the sole graphical frontend target; no Tk or
X11 compatibility runtime is retained. The frontend is not production-ready.

## Target runtime: native Wayland only

The intended appliance stack is Weston on its DRM/KMS backend with
`kiosk-shell`, running the GTK4 application as a native Wayland client.

The GTK process sets `GDK_BACKEND=wayland`, removes an inherited
`DISPLAY`, and fails closed if `WAYLAND_DISPLAY` is absent. The compositor
must not be started with `--xwayland`. Do not install, enable, start, or fall
back to XWayland, Xorg, Openbox, or another X11 compatibility layer. Fedora's
system GTK4, PyGObject and libadwaita RPMs provide the runtime; do not vendor
GTK or install Python GUI bindings from PyPI.

### Fedora 45 package and CLI verification

Checked against Fedora's Fedora 45 package metadata on 2026-11-25:

| RPM | Fedora 45 stable build | Purpose |
| --- | --- | --- |
| `weston` | `15.0.1-3.fc45` source baseline | **Do not ship the stock RPM unchanged**; it depends on `weston-libs` |
| `weston-libs` | `15.0.1-3.fc45` source baseline | Stock RPM contains `xwayland.so` and `x11-backend.so`, and has X11 library dependencies |
| `gtk4` | `4.24.1-1.fc45` source baseline | Stock RPM includes the optional GDK X11 backend and X11 library dependencies |
| `python3-gobject` | `3.58.0-6.fc45` | PyGObject Python bindings; keep as a Fedora system package |
| `libadwaita` | `1.10.0-2.fc45` source baseline | Rebuild against the custom GTK4 package |

**Important packaging constraint:** stock Fedora 45 `weston-libs` is not
strict-Wayland-only. Its file list includes both `xwayland.so` and
`x11-backend.so`; its dependency set includes `libX11`, `libX11-xcb`,
`libXcursor` and `libxcb`. The stock Fedora `gtk4` RPM likewise includes
`GdkX11-4.0.typelib` and depends on `libX11`, `libXcursor`, `libXdamage`,
`libXext`, `libXfixes`, `libXi`, `libXinerama` and `libXrandr`.
Consequently, simply not running an X server is enough for a Wayland-only
session, but it is not enough for the stricter appliance policy of shipping
no X11 backends or X11 libraries. Do not install the stock `weston`,
`weston-libs` or `gtk4` RPMs unchanged in the appliance.

Weston 15.0.1 upstream Meson options explicitly provide `xwayland` and
`backend-x11`, both enabled by default. Rebuild the Fedora 45-matched 15.0.1
source with `-Dxwayland=false -Dbackend-x11=false`, while retaining
`-Dbackend-drm=true -Dshell-kiosk=true`. The GTK 4.24.1 source likewise
provides `x11-backend` and `wayland-backend` options; rebuild with
`-Dx11-backend=false -Dwayland-backend=true`. Rebuild libadwaita against that
GTK4 RPM, and retain Fedora's `python3-gobject` system binding package.
Package the custom builds as Feclora-specific RPMs using Fedora's packaging
integration. Inspect the RPMs before adding them to the Live image: no installed
file may provide `xwayland.so`, `x11-backend.so`, `GdkX11-4.0.typelib`, and
no runtime dependency may pull `libX11`, `libX11-xcb`, `libXcursor`,
`libXdamage`, `libXext`, `libXfixes`, `libXi`, `libXinerama`,
`libXrandr`, `libxcb` or the XWayland server. These custom builds have not
yet been produced or tested.

The Weston 15.0.1 command-line interface documents `-B drm` for the DRM/KMS
backend, `--shell=kiosk-shell.so` for kiosk mode, `--idle-time=0` to disable
the idle timeout, and `--no-config` to ignore all `weston.ini` files and
configured modules. Weston can launch the GUI as its child with the mandatory
`--` separator; it supplies `WAYLAND_DISPLAY` to that child. The production
command must omit `--xwayland` and use `--no-config`.

The verified command shape for a seat-enabled session is:

```sh
env -u DISPLAY weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- \
  /usr/bin/python3 -m feclora.gui_gtk
```

This is a CLI/package verification, not yet an approved systemd unit. The
Weston process must receive a real logind/libseat session, the active tty and
DRM/input seat access, plus a valid `XDG_RUNTIME_DIR`. The existing
`feclora` account uses `/sbin/nologin`; the exact system-service/PAM/logind
arrangement must be validated in a VM before the runtime is added to the ISO.
Do not work around seat permissions by running Weston as root or by making
`/dev/dri` world-writable.

No Weston, GTK, or libadwaita runtime packages have been added to the Live
image yet. Textual remains the enabled production interface until the GTK
workflow audit, Weston session lifecycle, VM smoke tests and BIOS/UEFI
acceptance are complete.

Package references:
- [Fedora 45 weston](https://packages.fedoraproject.org/pkgs/weston/weston/fedora-45.html)
- [Fedora 45 weston-libs](https://packages.fedoraproject.org/pkgs/weston/weston-libs/fedora-45.html)
- [Fedora 45 gtk4](https://packages.fedoraproject.org/pkgs/gtk4/gtk4/fedora-45.html)
- [Fedora 45 python3-gobject](https://packages.fedoraproject.org/pkgs/pygobject3/python3-gobject/fedora-45.html)
- [Fedora 45 libadwaita](https://packages.fedoraproject.org/pkgs/libadwaita/libadwaita/fedora-45.html)
- [Weston 15.0.1 Meson options](https://github.com/wayland-mirror/weston/blob/15.0.1/meson_options.txt)
- [GTK 4.24.1 Meson options](https://github.com/GNOME/gtk/blob/4.24.1/meson.options)
- [Weston 15.0.1 man page](https://www.mankier.com/1/weston)

## Migration sequence

1. **Source foundation in place:** keep Textual bootable, share the UI catalogue,
   and use the GTK/GLib API bridge.
2. **GTK shell and core pages in place:** the shell, overview and nested inventory
   are implemented; their runtime rendering still needs GTK/Wayland VM validation.
3. **Operational pages ported at source level:** image inspection/browsing/
   extraction, restore profiles, network, local storage operations and P2V
   import/export have GTK implementations. Confirm semantic parity with tests.
4. **Server and orchestration pages ported at source level:** server/PXE,
   repositories, remote deployment, client jobs and history controls are present.
   Complete behavioral review of confirmations, preflight, progress, cancellation
   and error paths; verify bootstrap, certificate renewal and TLS keypair rotation end to end.
5. **Pending runtime/acceptance work:** run unit/contract tests and
   `build/validate.sh`; build the X11-disabled Fedora-source GTK4/libadwaita and
   Weston RPMs; validate Weston DRM + kiosk-shell session/seat lifecycle; then
   run VM smoke tests. Keep tty2 as the independent maintenance/recovery path.
6. Switch the default boot service only after behavioral feature parity and
   BIOS/UEFI acceptance. Then remove Textual and obsolete text-boot checks.

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

- RAW whole-disk capture preserves both mutually exclusive Textual age
  encryption modes: recipient-based encryption and one-shot passphrase
  encryption. The passphrase mode uses a masked GTK password field; the secret
  is delivered only to the accepted operation ID, then cleared. Delivery
  failure requests cancellation of the capture. QCOW2 remains unencrypted.

- Capture failure handling also clears any pending age passphrase from both the
  in-memory handoff field and the GTK password entry, and disables the cancel
  control when the capture cannot be accepted.


## libadwaita history states

The operation log and persistent ddrescue recovery history use Adw.StatusPage inside Gtk.Stack containers for genuine empty results. Populated results retain their existing tabular views; backend inspection failures are presented as explicit status-page errors rather than being confused with an empty history. Refresh controls, operation cancellation confirmation and recovery data contracts remain unchanged.


The Network page uses Adw.ComboRow for active NetworkManager profile, interface/address binding and DHCP/static method selection, plus Adw.EntryRow for IPv4 address, prefix, gateway and DNS. The controls are direct children of the IPv4 Adw.PreferencesGroup rather than generic GTK widgets embedded in ActionRow suffixes. Existing validation, NetworkManager selection, rollback-protected apply action and conditional visibility of static fields are retained.


## libadwaita image catalog states

The image browser's repository catalog is presented through a `Gtk.Stack` with dedicated `Adw.StatusPage` views for loading, an empty repository, and lookup failures. The image selector is shown only when disk images are available; an empty catalog is represented as an actual empty state rather than a placeholder selectable item. Repository changes return the view to loading, and lookup errors remain distinguishable from a valid empty repository. Image inspection, verification, browsing and extraction actions are unchanged.


## libadwaita system status

The System page now presents its read-only status summary and refresh action in an `Adw.PreferencesGroup` using `Adw.ActionRow` rows. The refresh button remains directly activatable from its row. The privileged status request and the displayed host, platform, service and certificate data are unchanged.


## libadwaita server administration

The Server page groups the server health summary, TLS identity and certificate actions, PXE profile controls, unattended PXE answer publication/revocation, and age recipient/passphrase workflows into semantic `Adw.PreferencesGroup` sections. Editable controls and action buttons use `Adw.ActionRow` suffixes with direct activation, while status/result labels remain selectable. Existing privileged API calls, exact confirmation requirements, PXE validation-before-start sequence, initially disabled PXE start control, and masked one-shot age passphrase handling are preserved.


## libadwaita restore profiles

The single-use restore profile page is grouped into source/target selection, profile definition, and controlled execution sections using `Adw.PreferencesGroup` and `Adw.ActionRow`. Existing repository and inventory lookups, timezone-aware expiry input, exact destructive target confirmation, disabled initial cancellation control, and privileged execution/cancellation callbacks are preserved. Creating a profile remains separate from starting a restore.


## libadwaita operation and recovery histories

The local operation log now separates status/refresh, exact-phrase cancellation, and persisted records into `Adw.PreferencesGroup` sections with `Adw.ActionRow` controls. The ddrescue recovery page groups job status and refresh separately from the persistent job history. Both pages retain their `Gtk.Stack` empty states, populated grids, existing API requests, and cancellation confirmation contract.


## libadwaita remote deployment history

Remote deployment and journal history now place their status and refresh controls in an Adw.PreferencesGroup with Adw.ActionRow entries. Remote job definition, import-source selection and deployment-service actions are grouped into semantic preference sections; the JSON editor, exact confirmation entry, repository lookups, and existing privileged callbacks remain intact. Client job history status and refresh are likewise grouped without changing TLS inspection, target selection, confirmation, start, or status workflows.


## libadwaita client execution controls

The client-job page now separates authenticated server connection and inspection, local target selection, transfer/protection options, and execution/status into Adw.PreferencesGroup sections with Adw.ActionRow controls. TLS inspection, interface and inventory discovery, eligible-target filtering, compression/encryption options, isolated-network IGMP acknowledgement, exact ERASE/READ confirmation text, and existing start/status callbacks are retained.


## libadwaita repository administration

The Repositories page now groups repository inventory, legacy P2V compatibility, managed repository actions, SSHFS/NFS/SMB definitions, S3 definitions, and encrypted systemd credential administration into Adw.PreferencesGroup sections. Editable fields and action buttons are presented through Adw.ActionRow controls. Provider-dependent SSH identity and SMB credential visibility, read-only flags, explicit removal phrases, protected credential references, and the existing repository/P2V API callbacks are retained. This is a presentation-only reorganization; mount, credential, validation and backend semantics are unchanged. The S3 credential control is a populated selector restricted to imported `s3` credentials; editing an existing S3 repository restores its credential selection instead of accepting a free-form ID.


## libadwaita local operations

The local operations form now uses separate Adw.PreferencesGroup sections for operation selection, source/target/image selection, destructive confirmation and artifact generation, Btrfs paths, format/encryption, ddrescue recovery, and execution progress. Controls use Adw.ActionRow suffixes while mode-dependent visibility is applied to complete rows, including Btrfs and recovery-specific fields. The operation selector, device filtering, exact ERASE/BUILD confirmation, one-shot masked age passphrase, progress/cancellation controls, and all existing privileged API calls remain unchanged.


## libadwaita image operations

The Images page now separates repository/image selection, partition inspection and integrity verification, filesystem browsing/download, partition extraction, and operation results into semantic Adw.PreferencesGroup sections with Adw.ActionRow controls. The existing loading/empty/error catalog stack remains intact. Repository selection, verified-layout checks, safe download handling, writable-repository requirements, extraction cancellation/progress, and all privileged API requests are unchanged.


## libadwaita overview status

The Overview page now separates host/platform identity, Feclora server/client configuration, and local service status into dedicated Adw.PreferencesGroup sections with Adw.ActionRow summaries. The refresh action is presented in its own semantic row. The existing status API request and source fields are unchanged; the response is rendered into the corresponding summaries.


The Inventory page now presents storage topology as one `Adw.PreferencesGroup` per top-level device, with nested devices and partitions represented by `Adw.ActionRow` entries. Each row retains the reported type, byte size, model, filesystem and mountpoints; an `Adw.StatusPage` explains an empty inventory. Refresh and summary controls use semantic preference rows. The inventory API and underlying device data are unchanged.


## libadwaita welcome and input preferences

The welcome screen now organizes interface language, keyboard layout, configuration status, and actions into semantic `Adw.PreferencesGroup` and `Adw.ActionRow` sections. The selected keyboard layout is initialized from the current in-memory setting, and a successful privileged apply updates that setting so rebuilding the welcome screen after a language change does not reset the selection. Language persistence and keyboard API behavior remain unchanged.


## libadwaita navigation sidebar

The adaptive `Adw.NavigationSplitView` keeps its existing sidebar/content pages,
width constraints, compact-mode back navigation, and page identifiers. The
sidebar entries are now activatable `Adw.ActionRow` items grouped under
`Adw.PreferencesGroup`, replacing generic GTK buttons while preserving the
existing page-selection callback and all page/API behavior.


The navigation sidebar now also marks the current destination explicitly:
the active row displays a short current-page subtitle and a confirmation
icon, while inactive rows retain the forward-navigation icon. Selection is
updated centrally by the existing page callback, including the initial
Overview selection; page IDs and compact-mode behavior are unchanged.


## Native libadwaita control audit

The migration is not a blanket replacement of GTK4 primitives: GTK remains the
foundation for layout containers, text views, grids, stacks and scrolling.
Where libadwaita provides a semantic preference control, prefer it over a
generic GTK control embedded in an ActionRow. The Network page is the first
completed pass of this refinement: its selectors use Adw.ComboRow (the
accessible combo-box row) and its text fields use Adw.EntryRow. Other pages
still contain Gtk.DropDown and Gtk.Entry controls and remain candidates for
the same page-by-page review. This structural audit does not constitute a
screen-reader, keyboard-only, contrast or live GTK runtime acceptance test.


The local capture form keeps recipient-based age encryption separate from
one-shot passphrase encryption. The two controls are mutually exclusive, the
passphrase entry is exposed only for RAW whole-disk capture when that mode is
selected, and the submitted API payload distinguishes the passphrase mode with
`encrypt_passphrase`. This preserves the Textual encryption contract rather
than treating the password as a generic replacement for recipient encryption.

The GTK image selector mirrors Textual's repository choices: it includes mounted and identity-verified file repositories plus configured S3 repositories. Extraction rejects read-only targets; file repositories additionally require a mounted, verified state, while S3 repositories follow the existing Textual read-only restriction.


Disk, partition, logical-volume and Stratis captures, Btrfs subvolume capture/receive, and ddrescue recovery/finalization forward the selected repository ID, matching Textual's explicit repository routing. When no remote repository is selected, the backend retains its local/default behavior. The structural GTK test guards all five shared routing sites.


The local operations repository selector now mirrors Textual's three-way catalog: local storage, mounted and verified file repositories, and configured S3 repositories. The selector remains visible across operation types; repository-scoped image inventory is loaded for either remote backend, while local selection uses the local image catalog. Read-only and operation-specific write restrictions remain enforced by the existing backend/API contract.


Remote DeploymentJob import now also exposes the SCP source supported by Textual. GTK requires the selected managed repository to be an SSHFS definition before submitting `source="scp"`; the API continues to read the SSH key and known_hosts material through the existing protected credential path. Repository and S3 imports remain separate `source="repository"` requests.

The unattended PXE answer publisher also exposes SCP over managed SSHFS repositories, matching Textual. The selected repository must be SSHFS for SCP; the API still owns the bounded read and protected SSH credential handling. Its repository selector includes configured S3 object repositories directly; only filesystem repositories are filtered by mounted and identity-verified state.


The remote deployment action selector includes both status inspection and an explicit refresh action, matching the Textual workflow. Both use the same read-only deployment-service status endpoint; start, arm, cancel, stop and reconcile retain their separate guards.


### Paridad de controles PXE

La pantalla GTK muestra los campos de rango DHCP, gateway, DNS y confirmación de DHCP autoritativo únicamente en modo de red aislada, igual que Textual. Cambiar el modo invalida cualquier perfil previamente validado y deshabilita el inicio PXE hasta repetir el preflight. El backend sigue siendo la autoridad para validar y arrancar los servicios.


### Confirmaciones destructivas dinámicas en operaciones

La interfaz GTK actualiza la ayuda de confirmación al cambiar el destino o la imagen: `ERASE <destino>` para restauraciones y clonación de disco, `ERASE <destino> FROM <origen>` para clonación de partición y `BUILD <imagen>` para ISO de recuperación. La comprobación de la frase exacta sigue realizándose antes de enviar la operación, y el backend privilegiado conserva su validación independiente.


### Paridad de formularios de operaciones

El selector GTK oculta el campo de identificador de imagen al finalizar una recuperación ddrescue: esa acción recibe un identificador de trabajo, no un identificador de imagen de captura. La visibilidad se mantiene alineada con la lógica de estados de Textual y queda cubierta por una comprobación estructural.

# GTK4 migration

## Status

The production boot route remains Textual on tty1. The earlier experimental
Cage boot configuration has been withdrawn: Cage is not the requested
compositor. The GTK kiosk service is staged but not enabled. The replacement
target is Weston DRM/KMS with `kiosk-shell`, launching the GTK welcome screen
fullscreen for language and keyboard selection. GTK source now contains
routes and views for all 14 navigation pages and the full 18-operation local
operation selector. The GTK structural suite checks that every catalogue page
has an explicit route, and separately checks the privileged API action surface.
This is source-level coverage, not proof of runtime behavioral parity:
the GTK/Wayland session, operator workflows and BIOS/UEFI boot acceptance still
require execution in the target image. Textual remains the production interface
until those acceptance gates pass; it is not a permanent fallback.
The shared catalogue contains all 25 languages.

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

A deeper Client-workflow contract audit found mismatches inherited from the
Textual frontend: its codec selector offered Zstandard/LZ4 although the
persistent Client API accepts only gzip, XZ and no compression; its save
confirmation included a Server-identity suffix rejected by both the API and
Client runtime; and the API treated unicast clone confirmation as a read rather
than a destructive write. Both frontends now share the API-supported codec
catalog, use READ <device> for save and ERASE <device> for restore/clone,
and restrict age encryption to save jobs. GTK also disables IGMP acknowledgement
outside multicast restore, which is the only multicast Client operation accepted
by the current API. Physical multicast clone remains a separate backend blocker:
the lower-level Client service and documentation describe it, but the current
API and persistent Server-service validation still reject it. It must not be
counted as migrated or accepted until those gates and their end-to-end tests are
reconciled.

A separate source-level audit compared the 18 local-operation form branches
against Textual, including parameter construction, destructive phrases,
repository state checks, progress polling, cancellation and error paths. It
found that restore, clone and proportional-restore branches passed an optional
capture passphrase before that local variable had been initialized, which
would raise `UnboundLocalError` before the privileged API call. The GTK handler
now initializes the optional value at entry and clears the password field when
leaving RAW-disk capture or selecting QCOW2. A regression test checks the
initialization order and mode-scoped clearing. This is a static code correction;
the Python suite and real storage workflows have not yet been executed.

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

### Fedora 45 official package selection

The appliance uses Fedora 45's official runtime RPMs; no Feclora-specific
rebuild is required merely to run a native Wayland session:

| RPM | Fedora 45 package | Relevant detail |
| --- | --- | --- |
| `weston` | `15.0.1-3.fc45` | Includes the DRM/KMS compositor and `kiosk-shell.so`; depends on `weston-libs` |
| `weston-libs` | `15.0.1-3.fc45` | Includes DRM and Wayland backends; also ships optional `x11-backend.so` and `xwayland.so` modules |
| `gtk4` | Fedora 45 stable | Includes Wayland and optional GDK X11 support |
| `libadwaita` | Fedora 45 stable | Uses the distribution GTK4 runtime |
| `python3-gobject` | Fedora 45 | System PyGObject bindings |

The presence of optional X11 client backends, GDK X11 typelibs or X11 client
libraries in these RPMs does **not** mean an X server is installed or running.
Fedora's Weston split puts the XWayland server executable in the separate
`xorg-x11-server-Xwayland` package; that package is not selected for Feclora.
Likewise, GTK chooses its Wayland backend through `GDK_BACKEND=wayland`.
Feclora's runtime policy is therefore enforced at the session boundary:
install the official Fedora packages, do not install `xorg-x11-server-Xwayland`
or `xorg-x11-server-Xorg`, do not pass `--xwayland` to Weston, clear
`DISPLAY`/ `XAUTHORITY`, and set GTK's backend to Wayland.

The repository RPM admission check validates Fedora 45 provenance and rejects
Xorg/XWayland server executables or server-package dependencies. It deliberately
allows optional X11 backend modules and client libraries supplied by Fedora.
This is the correct distinction for a Wayland-only runtime; it does not claim
that the RPM payloads are stripped of all X11 compatibility code.

Install the official packages in the Kickstart and base manifest. The GTK
systemd unit remains a staged candidate, not enabled, until behavioral parity
and the graphical boot acceptance tests pass. The package selection itself
does not prove Weston starts successfully on the target hardware.

### Fedora 45 KMSCON and VT ownership

Fedora 45 replaces the traditional userspace-facing virtual-console path on
VTs 1–6 with KMSCON. KMSCON is a DRM/KMS console emulator and holds exclusive
access to the GPU while it owns a VT; Fedora provides `kmscon-launch-gui` to
release that ownership before starting a graphics application. Feclora does
not use that wrapper for its kiosk session. Instead, the Kickstart masks
`kmsconvt@tty1.service` through `kmsconvt@tty6.service`: tty1 remains available
for the current Textual UI and future Weston compositor, tty2 remains a raw
independent maintenance VT, and tty3–tty6 do not acquire a userspace DRM
console. The Textual and root-terminal units also declare conflicts and
ordering against the corresponding KMSCON instance as a defensive measure.

This avoids a second compositor/console competing for DRM; it does not imply
that Weston has already been integrated or that the VT/seat handoff has passed
VM acceptance. Verify the actual unit state and DRM ownership in both BIOS and
UEFI boots before enabling the graphical service. KMSCON is a VT console, not
an X11 component.

This is a CLI/package verification, not yet an approved systemd unit. The
Weston process must receive a real logind/libseat session, the active tty and
DRM/input seat access, plus a valid `XDG_RUNTIME_DIR`. The existing
`feclora` account uses `/sbin/nologin`; the exact system-service/PAM/logind
arrangement must be validated in a VM before the runtime is added to the ISO.
Do not work around seat permissions by running Weston as root or by making
`/dev/dri` world-writable.

A candidate unit now defines the intended Weston DRM/KMS + kiosk-shell
session on tty1 and launches `feclora.gui_gtk` as the unprivileged
`feclora` user. It requests a PAM login session, explicitly selects libseat's
logind backend, and removes inherited `DISPLAY`/`XAUTHORITY` so the
compositor cannot accidentally inherit an X11 session. The exact
`PAMName=login` arrangement, PAM-created `XDG_RUNTIME_DIR`, seat activation
and input/DRM handoff still require VM verification. The `feclora` account
remains locked with `/sbin/nologin`; the service executes Weston directly
rather than opening an interactive shell. The unit and its GTK-specific first-render helper are now staged in the image,
but Kickstart deliberately does not enable the unit or change the current boot
route. The VM smoke protocol
now distinguishes a GTK window-render event from the legacy Textual event.

The official Fedora Weston, GTK4, libadwaita and PyGObject runtime packages
are now selected by both the Kickstart and base manifest. No custom RPM build
pipeline is required. Textual therefore remains the enabled production
interface. The candidate service is boot wiring groundwork, not a proven
GTK boot path; the full GTK/Weston session lifecycle, workflow parity, VM
smoke tests and BIOS/UEFI acceptance remain outstanding.

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
   `build/validate.sh`; use the official Fedora 45 Weston/GTK4/libadwaita
   packages already selected in the image; validate the Weston DRM +
   kiosk-shell session/seat lifecycle; then run VM smoke tests. Keep tty2 as
   the independent maintenance/recovery path.
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


The Network page uses Adw.ComboRow for active NetworkManager profile, interface/address binding and DHCP/static method selection, plus Adw.EntryRow for IPv4 address, prefix, gateway and DNS. The controls are direct children of the IPv4 Adw.PreferencesGroup rather than generic GTK widgets embedded in ActionRow suffixes. Existing validation, NetworkManager selection, rollback-protected apply action and conditional visibility of static fields are retained. Profile and interface discovery, plus the post-apply refresh, are guarded against responses from a previous instance of the Network page. Cached profile and interface targets are cleared before discovery and after applying a change, so an old address cannot remain actionable while refreshed NetworkManager data is loading. The profile and interface selectors require explicit operator selection before apply, matching the TUI's neutral initial state. Profile and interface/address selectors start at explicit placeholder entries, matching the TUI's requirement that the operator choose both before applying a network change; no active profile or address is silently preselected.


## libadwaita image catalog states

The image browser's repository catalog is presented through a `Gtk.Stack` with dedicated `Adw.StatusPage` views for loading, an empty repository, and lookup failures. The image selector is shown only when disk images are available; an empty catalog is represented as an actual empty state rather than a placeholder selectable item. Repository changes return the view to loading, and lookup errors remain distinguishable from a valid empty repository. Image inspection, verification, browsing and extraction actions are unchanged. Repository discovery and image-catalog callbacks are generation-guarded across repository changes and page re-entry, preventing delayed responses from replacing the active catalog. Image-layout inspection results are also discarded if the repository or page changed while inspection was running. Pending filesystem-browse results are invalidated when the image, repository, or page changes, so an old mount session cannot replace the active view. The current image selection, inspected layout and browse session are cleared immediately when a catalog reload begins, closing the window in which actions could combine an old image with a newly selected repository. Changing the selected partition also invalidates any pending browse response and clears its session token.


## libadwaita system status

The System page now presents its read-only status summary and refresh action in an `Adw.PreferencesGroup` using `Adw.ActionRow` rows. The refresh button remains directly activatable from its row. The privileged status request and the displayed host, platform, service and certificate data are unchanged. Status requests are guarded by navigation-page and refresh generations, so late responses cannot replace the summary after navigating away or after a newer refresh.


## libadwaita server administration

The Server page groups the server health summary, TLS identity and certificate actions, PXE profile controls, unattended PXE answer publication/revocation, and age recipient/passphrase workflows into semantic `Adw.PreferencesGroup` sections. Editable controls and action buttons use `Adw.ActionRow` suffixes with direct activation, while status/result labels remain selectable. Existing privileged API calls, exact confirmation requirements, PXE validation-before-start sequence, initially disabled PXE start control, and masked one-shot age passphrase handling are preserved.


## libadwaita restore profiles

The single-use restore profile page is grouped into source/target selection, profile definition, and controlled execution sections using `Adw.PreferencesGroup` and `Adw.ActionRow`. Existing repository and inventory lookups, timezone-aware expiry input, exact destructive target confirmation, disabled initial cancellation control, and privileged execution/cancellation callbacks are preserved. Creating a profile remains separate from starting a restore. Repository image/profile callbacks are generation-guarded, so a slow response from a previously selected repository cannot overwrite the currently selected repository's lists.


## libadwaita operation and recovery histories

The local operation log now separates status/refresh, exact-phrase cancellation, and persisted records into `Adw.PreferencesGroup` sections with `Adw.ActionRow` controls. The ddrescue recovery page groups job status and refresh separately from the persistent job history. Both pages retain their `Gtk.Stack` empty states, populated grids, existing API requests, and cancellation confirmation contract.


## libadwaita remote deployment history

Remote deployment and journal history now place their status and refresh controls in an Adw.PreferencesGroup with Adw.ActionRow entries. Remote job definition, import-source selection and deployment-service actions are grouped into semantic preference sections; the JSON editor, exact confirmation entry, repository lookups, and existing privileged callbacks remain intact. Client job history status and refresh are likewise grouped without changing TLS inspection, target selection, confirmation, start, or status workflows. The remote-job page guards repository and job lookups against page re-entry and publishes the combined import-repository selector only after both file and S3 inventories complete.


## libadwaita client execution controls

The client-job page now separates authenticated server connection and inspection, local target selection, transfer/protection options, and execution/status into Adw.PreferencesGroup sections with Adw.ActionRow controls. TLS inspection, interface and inventory discovery, eligible-target filtering, compression/encryption options, isolated-network IGMP acknowledgement, exact ERASE/READ confirmation text, and existing start/status callbacks are retained. Inspection responses are generation-guarded against page re-entry and changes to server host, job ID, interface or local inventory; changing any inspection input clears the authenticated inspection, eligible targets and destructive confirmation.


## libadwaita repository administration

The Repositories page now groups repository inventory, legacy P2V compatibility, managed repository actions, SSHFS/NFS/SMB definitions, S3 definitions, and encrypted systemd credential administration into Adw.PreferencesGroup sections. Editable fields and action buttons are presented through Adw.ActionRow controls. Provider-dependent SSH identity and SMB credential visibility, read-only flags, explicit removal phrases, protected credential references, and the existing repository/P2V API callbacks are retained. This is a presentation-only reorganization; mount, credential, validation and backend semantics are unchanged. The S3 credential control is a populated selector restricted to imported `s3` credentials; editing an existing S3 repository restores its credential selection instead of accepting a free-form ID. Repository, S3 and systemd-credential refresh callbacks are generation-guarded across repeated refreshes and page re-entry, preventing an older response from replacing the latest inventory. The management selector preserves its selected repository by type and ID when the combined remote/S3 inventory is rendered after both responses complete; a removed repository falls back to the neutral selection. A failed remote or S3 lookup does not publish a partially refreshed management list.


## libadwaita local operations

The local operations form now uses separate Adw.PreferencesGroup sections for operation selection, source/target/image selection, destructive confirmation and artifact generation, Btrfs paths, format/encryption, ddrescue recovery, and execution progress. Controls use Adw.ActionRow suffixes while mode-dependent visibility is applied to complete rows, including Btrfs and recovery-specific fields. The operation selector, device filtering, exact ERASE/BUILD confirmation, one-shot masked age passphrase, progress/cancellation controls, and all existing privileged API calls remain unchanged.


## libadwaita image operations

The Images page now separates repository/image selection, partition inspection and integrity verification, filesystem browsing/download, partition extraction, and operation results into semantic Adw.PreferencesGroup sections with Adw.ActionRow controls. The existing loading/empty/error catalog stack remains intact. Repository selection, verified-layout checks, safe download handling, writable-repository requirements, extraction cancellation/progress, and all privileged API requests are unchanged.


## libadwaita overview status

The Overview page now separates host/platform identity, Feclora server/client configuration, and local service status into dedicated Adw.PreferencesGroup sections with Adw.ActionRow summaries. The refresh action is presented in its own semantic row. The existing status API request and source fields are unchanged; the response is rendered into the corresponding summaries.


The Inventory page now presents storage topology as one `Adw.PreferencesGroup` per top-level device, with nested devices and partitions represented by `Adw.ActionRow` entries. Each row retains the reported type, byte size, model, filesystem and mountpoints; an `Adw.StatusPage` explains an empty inventory. Refresh and summary controls use semantic preference rows. The inventory API and underlying device data are unchanged. Inventory refreshes are guarded by page and request generations, preventing an older scan from replacing a newer result or updating the page after navigation.


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


The local operations repository selector now mirrors Textual's three-way catalog: local storage, mounted and verified file repositories, and configured S3 repositories. The selector remains visible across operation types; repository-scoped image inventory is loaded for either remote backend, while local selection uses the local image catalog. Read-only and operation-specific write restrictions remain enforced by the existing backend/API contract. Initial inventory and repository lookups are bound to the current operations-page generation. Changing repositories clears the previous image list immediately and discards delayed catalog responses, preventing an image from another repository from remaining selectable.


Remote DeploymentJob import now also exposes the SCP source supported by Textual. GTK requires the selected managed repository to be an SSHFS definition before submitting `source="scp"`; the API continues to read the SSH key and known_hosts material through the existing protected credential path. Repository and S3 imports remain separate `source="repository"` requests.

The unattended PXE answer publisher also exposes SCP over managed SSHFS repositories, matching Textual. The selected repository must be SSHFS for SCP; the API still owns the bounded read and protected SSH credential handling. Its repository selector includes configured S3 object repositories directly; only filesystem repositories are filtered by mounted and identity-verified state.


The remote deployment action selector includes both status inspection and an explicit refresh action, matching the Textual workflow. Both use the same read-only deployment-service status endpoint; start, arm, cancel, stop and reconcile retain their separate guards.


### Paridad de controles PXE

La pantalla GTK muestra los campos de rango DHCP, gateway, DNS y confirmación de DHCP autoritativo únicamente en modo de red aislada, igual que Textual. Cambiar el modo invalida cualquier perfil previamente validado y deshabilita el inicio PXE hasta repetir el preflight. El backend sigue siendo la autoridad para validar y arrancar los servicios.


### Confirmaciones destructivas dinámicas en operaciones

La interfaz GTK actualiza la ayuda de confirmación al cambiar el destino o la imagen: `ERASE <destino>` para restauraciones y clonación de disco, `ERASE <destino> FROM <origen>` para clonación de partición y `BUILD <imagen>` para ISO de recuperación. La comprobación de la frase exacta sigue realizándose antes de enviar la operación, y el backend privilegiado conserva su validación independiente.


### Paridad de formularios de operaciones

El selector GTK oculta el campo de identificador de imagen al finalizar una recuperación ddrescue: esa acción recibe un identificador de trabajo, no un identificador de imagen de captura. La visibilidad se mantiene alineada con la lógica de estados de Textual y queda cubierta por una comprobación estructural.


La recuperación ddrescue mantiene el valor fijo de tres pasadas de reintento, igual que Textual. GTK no expone un selector configurable para este parámetro; la opción de reanudación mediante mapfile sí permanece disponible.


El selector de imágenes de operaciones filtra por tipo compatible con la operación activa (disco, partición, volumen lógico o filesystem Stratis), igual que Textual. La validación del tipo se mantiene también al enviar la operación; el filtrado mejora la selección, no sustituye las comprobaciones del backend.


PXE preflight validation is generation-guarded: edits to profile fields, DHCP mode or server interface invalidate pending and completed validation responses, so only the exact currently displayed profile can be started.


Server status, PXE status and interface discovery are guarded by page and refresh generations, so delayed responses from earlier refreshes or page instances cannot overwrite the current summary or interface list. The unattended PXE-answer repository selector is populated only after both remote and S3 inventories complete, and callbacks from previous server-page instances are ignored. The TLS bootstrap interface selector also starts at an explicit placeholder, matching the TUI and preventing automatic selection of the first active address.


Generic deployment, remote-job and journal history pages guard refresh responses by both navigation-page and request generations. Late responses from earlier refreshes or a page that has since been left cannot replace the currently displayed history.


The local operation log and persistent ddrescue recovery history guard refreshes by page and request generation. Late results from an earlier refresh or page instance cannot replace the currently displayed records.


Client-job start responses are retained by job identifier even if navigation or a newer TLS inspection makes the initiating view stale; only the matching page/inspection may update its widgets. Client status refreshes additionally use a request generation and job-identifier check, preventing delayed status or error callbacks from replacing the state of another inspected job. These guards affect presentation only: they do not cancel or suppress a privileged action already submitted to the API.

Server administration and PXE start/stop callbacks capture the server-page generation at submission time. Results of completed actions are retained in the window state, while stale callbacks cannot write into widgets belonging to a later server-page instance. This is a presentation guard only and does not cancel a submitted privileged action.

Remote deployment actions (start, arm, cancel, stop and reconcile) now bind their UI callbacks to the page instance and selected job identifier. The stop workflow rechecks that context after its status preflight and before submitting the stop request, so a delayed preflight cannot stop a different selection. Completed action results are retained independently of the current view; only matching callbacks update controls or refresh the job list. Definition creation/import callbacks are likewise page-scoped.


Local capture, restore, clone, ddrescue and image-build submissions now bind their
acceptance and error callbacks to a request generation and the operations-page
generation. The one-shot age passphrase is captured by that specific submission
and delivered only to the operation ID returned for it; it is no longer read from
mutable window-wide pending state. Operation acceptance and status results are
retained by operation ID, while stale callbacks cannot update a later page
instance. Status polling and cancellation carry the operation ID explicitly, and
reopening the operations page resumes polling the currently tracked operation.
These guards preserve already-submitted backend actions and do not replace the
backend's authorization or destructive-operation checks. Structural source
tests were added; GTK runtime, privileged-operation and BIOS/UEFI acceptance
tests have not been run.


Restore-profile creation and execution callbacks now retain their originating page
and request generations. Durable restore execution results and status snapshots
are associated with their operation IDs; polling and cancellation callbacks carry
that ID explicitly, and reopening the restore-profile page resumes monitoring
the latest accepted operation. Repository-specific image/profile responses are
also scoped to both the active page and repository selection. The operation-log
cancellation path similarly binds its feedback to the original operation ID and
only updates the view while that operation remains selected on the same page.
These UI guards do not change the privileged API, single-use profile semantics,
or backend cancellation behavior. Structural tests were added; no GTK runtime,
privileged-operation, BIOS or UEFI acceptance test was executed.


Network-profile loading, application, and post-apply refresh callbacks now carry
both the Network page instance and the global navigation generation; apply
responses additionally carry an apply-request generation. This prevents delayed
responses from a previous navigation or an earlier apply from repopulating the
current selectors. TLS administration and PXE validation/start/stop callbacks
capture their originating server-page context. PXE validation retains the exact
profile snapshot submitted for preflight rather than reading a mutable pending
profile when the response arrives. TLS and PXE action results/errors are retained
even when the originating page is stale, but stale outcomes cannot update the
current widgets. No service, privileged API contract, checkpoint/rollback
behavior, or PXE backend semantics were changed. Structural tests were updated;
runtime GTK, live network rollback, TLS/PXE service operations and BIOS/UEFI
acceptance have not been executed.
 The final review also closed navigation-generation gaps in the post-apply
NetworkManager interface refresh, server status error handling, and PXE answer
repository loading, so those responses cannot repopulate hidden or superseded
page instances.


PXE answer publication/revocation now records each result against its requested
job ID and only updates the active server page for the latest matching request;
revocation feedback also checks that the same job ID remains selected. age
passphrase-status reads and one-shot passphrase submissions capture the server
page, navigation generation and request generation. A delayed secret-delivery
callback therefore cannot clear or re-enable the secret field on a newer page;
the result/error is retained without retaining the secret in UI state. Server
and client age-recipient maintenance actions also use page-scoped callbacks.
These changes preserve the existing privileged API payloads and secret-delivery
semantics. Structural tests were added; no live PXE worker, age delivery,
certificate, or server runtime test was executed.


Repository definition and systemd-credential mutations now pass through a
single request-scoped submit path. Results/errors are retained independently,
while only the latest action on the same repository page and navigation
generation may refresh its controls. Legacy P2V import/export acceptance is
likewise associated with its originating request and durable operation ID.

Image verification results are keyed by repository and image identity and are
shown only while that exact selection remains current. Image browsing and
catalog responses are guarded by page, catalog and navigation generations.
Downloads still complete their requested secure file write even if navigation
occurs while the backend response is pending, but stale responses cannot alter
the new page's status text. Partition-extraction acceptance/status is retained
by operation ID, polling uses an explicit ID, and reopening the Images page
resumes monitoring the latest accepted extraction. These are frontend lifecycle
guards only; image storage, verification, file permissions and backend operation
contracts are unchanged. Structural tests were added; no runtime image,
repository-mount, credential, or P2V operation was executed.
 Image-layout inspection also now stores its response under the originating
repository/image pair and discards it from the visible view if the selection
changed before the response arrived.


P2V legacy import/export now follows the durable operation through
`local_operation_status`, rather than stopping at the accepted response. The
latest operation ID and its status are retained, stale page/request callbacks
cannot update the repository view, and reopening that page resumes polling.
Terminal states (completed, failed, cancelled, interrupted) are reported in
the P2V result area, matching the Textual export flow's wait-for-completion
behavior.

Image browsing now invalidates its session ID and clears the stale directory
listing when a browse request fails, matching the Textual behavior. Browse
errors are kept local to the explorer and no longer mark the repository image
catalog itself as failed. Individual-file downloads remain an independent
side effect: a valid response is still saved securely even if the user changes
the selected image while it is in flight, but success/error feedback is shown
only if the same image, repository, page and download request remain selected.
Structural regression tests cover these lifecycle rules. No P2V conversion,
repository transfer, image mount, filesystem traversal, or file download was
executed against a live appliance.
 The accepted operation ID is retained before the page-visibility check, so
navigation during submission does not lose the handle; returning to Repositories
can resume status polling for that operation.


The welcome/setup screen now versions its own lifetime. Applying a keyboard
layout still records the successful system setting, but a delayed response
cannot update a setup label after the user has continued into the main
navigation. Leaving setup invalidates outstanding setup callbacks. Root-terminal
success is reported through the persistent libadwaita toast overlay instead of
a potentially detached setup widget. Structural regression coverage was added.


Capture-operation status responses are now checked against the requested
operation ID before being accepted. On successful completion, the GTK Operations
page refreshes its device inventory and the selected repository's image catalog,
matching the Textual completion flow so newly created images become selectable
without leaving and re-entering the page. Setup-screen asynchronous callbacks
also carry a screen generation; stale keyboard responses cannot update detached
widgets, and root-terminal success uses the persistent toast overlay.


Client-job history refreshes now use a dedicated request generation in addition to
the client-page generation. If an operator requests another refresh before an
earlier `deployment_jobs` response arrives, only the newest response (or its
error) may replace the displayed history. This matches the refresh ordering
guards used by the other history pages; it does not alter the deployment API.
Structural regression coverage was added; no live client transfer or GTK
runtime test was executed.


A further lifecycle audit added the global page-generation guard to client
interface/inventory callbacks and to both PXE answer repository lookups
(remote and S3), including their error paths. A response arriving after
navigation away from the page can no longer mutate detached GTK controls or
replace the repository selector. Structural regression tests cover both paths.
No GTK runtime or appliance integration tests were run.


Server administration and PXE start/stop callbacks now carry the exact global window generation captured when each request is submitted, in addition to the server-page generation. This prevents a delayed bootstrap, TLS certificate/key rotation, age-recipient maintenance, or PXE service response from updating a newly re-entered Server page. Accepted results and errors remain retained for diagnostics before the visibility guard. Structural regression coverage was added; no GTK runtime, TLS rotation, PXE service operation, or live appliance test was executed.

The follow-up review also corrected the client age-recipient inventory refresh callbacks to forward that captured window generation into the shared completion/error handlers (rather than relying on the handler's former implicit current-window check). The regression test now asserts that both callbacks forward the captured value.

PXE answer publication now retains the accepted result and uses the requested job UUID as the revoke-field fallback when the backend response omits `job_id`, matching the Textual workflow. Successful revocation clears the retained published-answer state. Structural regression assertions cover both behaviors; no live PXE answer was published or revoked.

### Paridad de la página de estado del sistema

La página GTK de sistema muestra ahora, además del hostname y la plataforma, el estado de configuración del servidor y del cliente, cada servicio comunicado por la API y el estado de cada certificado. Los detalles se reconstruyen al recibir cada respuesta de estado, evitando conservar filas obsoletas entre actualizaciones. Esta corrección recupera los campos que ya exponía la tabla de estado Textual.

La cobertura añadida es estructural (AST); no implica que se hayan ejecutado pruebas con GTK/GI ni validaciones en el appliance.

### Selector de trabajos remotos

El selector GTK de trabajos de despliegue usa índices para resolver la definición elegida. Su lista de respaldo ahora excluye registros que no tengan un `job_id` de texto no vacío, igual que las opciones visibles. Así, una entrada incompleta del historial no desplaza los índices ni puede asociar una acción a otro trabajo persistido.

### Errores de inspección del registro de operaciones

La vista GTK del registro local presenta ahora cada elemento de `inspection_errors` devuelto por la API, con su ruta o identificador y el motivo comunicado. Mantiene además la advertencia de no repetir operaciones afectadas hasta una inspección manual. El grupo de errores se crea como parte de cada instancia de página y se repuebla al actualizar, evitando referencias a widgets desconectados tras navegar fuera y volver.

La prueba añadida verifica la estructura y el enlace del grupo a la página actual; no sustituye pruebas de ejecución con GTK/GI.

## Weston kiosk boot target

The GTK frontend is not enabled at boot. The current production interface
continues to run Textual on tty1 until the parity and acceptance gates above
are complete. Cage is explicitly excluded.

The intended replacement is Weston 15.0.1 on its DRM/KMS backend with
`kiosk-shell`, launching `/usr/bin/python3 -m feclora.gui_gtk` as a native
Wayland client. The verified command shape is:

```sh
env -u DISPLAY weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- \
  /usr/bin/python3 -m feclora.gui_gtk
```

Do not enable the Weston systemd unit until GTK behavioral parity and the
logind/libseat/DRM session have passed VM testing. The official Fedora runtime
packages are already selected; do not install the separate XWayland server
package. Do not run Weston as root or weaken device permissions.
The final cutover must replace Textual and remove its package, service,
application, tests and obsolete boot checks; Textual is not a permanent
fallback.

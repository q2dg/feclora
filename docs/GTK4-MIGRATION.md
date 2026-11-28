# GTK4 / Wayland migration record

## Current status

GTK4/PyGObject/libadwaita is a staged candidate. **Textual remains the
production interface on tty1**; the Live image must not enable
**feclora-gtk.service** or remove the Textual runtime until every acceptance
gate below is met. tty2 remains the independent root maintenance and recovery
terminal.

The GTK source contains the 14 navigation sections and a literal inventory
matching the 49 direct privileged API action names in the legacy Textual
source. That is an API-name coverage check only. It does not establish
semantic parity: parameter shapes, default values, form validation,
confirmation wording, destructive-scope checks, progress interpretation,
cancellation races, retry behavior, error recovery and persisted state must
also be compared. The audit remains open for every section and workflow.

## Required graphics architecture

- Weston 15.0.1 using DRM/KMS and **kiosk-shell**.
- GTK 4.24.1 with PyGObject and libadwaita 1.10.0.
- GDK must use **GDK_BACKEND=wayland** only.
- The frontend must remove **DISPLAY** and fail before importing GTK when
  **WAYLAND_DISPLAY** is missing.
- Weston must start with **--no-config -B drm --renderer=pixman --shell=kiosk-shell.so** and
  must not receive **--xwayland**. The GTK process must use **GSK_RENDERER=cairo**.
- No XWayland, Xorg, Openbox, Weston X11 backend, GDK X11 backend, X11
  libraries, X11 headers or X11 development metadata may be installed,
  included, started or exposed.

The GTK systemd unit and source enforce the Wayland environment, but they are
not production-enabled. The candidate unit is staged only so its configuration
can be inspected and tested.

### Software-renderer constraint

Fedora 45's stock Weston runtime depends on `mesa-dri-drivers`; that package
advertises `libX11-xcb`, `libxcb` and `libxshmfence` dependencies. The stock
Mesa EGL package also depends on X11 client libraries. Those packages cannot
enter a strict X11-free image. The candidate therefore disables Weston's GL and Vulkan
renderers at build time (`-Drenderer-gl=false -Drenderer-vulkan=false`) and selects Pixman explicitly
with `--renderer=pixman`; DRM/KMS and kiosk-shell remain enabled. The GTK build
disables its Vulkan renderer and the app selects the Cairo GSK renderer. This
is a deliberate software-compositing trade-off: UI rendering consumes CPU and
must be measured on the target hardware. The runtime dependency-closure audit
must prove that no Mesa DRI/EGL package with X11 dependencies is pulled in.

Fedora package metadata: [Weston 15.0.1-3.fc45](https://packages.fedoraproject.org/pkgs/weston/weston/fedora-45.html), [Mesa DRI drivers](https://packages.fedoraproject.org/pkgs/mesa/mesa-dri-drivers/fedora-45.html), [Mesa EGL](https://packages.fedoraproject.org/pkgs/mesa/mesa-libEGL/fedora-45.html).

## Fedora 45 source rebuilds

The required source baselines and Meson options are:

```text
Cairo 1.18.6:
  -Dxlib=disabled -Dxcb=disabled -Dxlib-xcb=disabled

Weston 15.0.1:
  -Dxwayland=false -Dbackend-x11=false
  -Dbackend-drm=true -Dshell-kiosk=true -Dsystemd=true
  -Drenderer-gl=false -Drenderer-vulkan=false

GTK 4.24.1:
  -Dx11-backend=false -Dwayland-backend=true -Dvulkan=disabled

libadwaita 1.10.0:
  Rebuild against the custom GTK4 and Cairo RPMs.
```

### Why Cairo must also be rebuilt

The candidate must retain Fedora's system python3-gobject and
python3-cairo packages rather than installing PyGObject through pip. Their
dependency graph matters: python3-gobject requires libcairo,
libcairo-gobject and python3-cairo. The stock Fedora 45 Cairo 1.18.6
runtime RPM in turn requires libX11, libXext and libXrender. Therefore the
PyGObject packages are staged in packages/wayland-candidate-runtime.txt and
deliberately excluded from the current Textual Live image until the custom
X11-free Cairo and Cairo-GObject RPMs have been built and verified. Rebuilding
only Weston and GTK4 would otherwise pull X11 libraries into the appliance
through the retained system PyGObject package.

The build pipeline now rebuilds Fedora 45 Cairo 1.18.6 first, with Xlib and
XCB surfaces disabled. Its Cairo spec patch removes X11-specific dependency
declarations and Xlib/XCB headers/pkg-config file entries from the generated
RPM metadata. The resulting cairo and cairo-gobject runtime RPMs must be
installed alongside the unchanged Fedora python3-gobject and python3-cairo
packages. The Cairo development RPMs are build-only artifacts and are
separated under out/wayland-rpms/build-deps/; they must not be added to the
Live image.

This is a prerequisite, not evidence of success: the Fedora Cairo spec
rewrite and the resulting RPMs still need to be built and inspected on a
Fedora 45 host.

### RPM inspection gate

Before incorporation, inspect every generated non-source binary RPM from all
four Fedora builds (runtime, development and debug subpackages) with:

```bash
build/verify-wayland-rpms.sh \
  weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm \
  cairo.rpm cairo-gobject.rpm \
  build-deps/gtk4-devel.rpm \
  build-deps/cairo-devel.rpm build-deps/cairo-gobject-devel.rpm
```

The verifier rejects:
- xwayland.so, XWayland/Xorg executables, x11-backend.so and
  backend-x11.h;
- GdkX11-4.0.typelib, GIR, GDK-X11 libraries and headers;
- Cairo Xlib/XCB headers, libraries and pkg-config metadata;
- X11/XCB/GLX headers, pkg-config files, shared libraries and RPM
  requirements;
- RPM Provides, Recommends, Suggests, Supplements or Enhances that advertise
  X11 capabilities;
- Openbox packages and binaries.

Use its --installed-root mode on the completed target root before release.
That mode also requires the retained python3-gobject and python3-cairo
packages and audits every installed RPM's files, requirements and advertised
capabilities. Static fixtures are not substitutes for actual RPM inspection.

## Building the Fedora 45 RPM candidates

On a Fedora 45 x86_64 build host, install the host tools with make deps,
then add the build user to the mock group and start a new login session:

```bash
sudo usermod -aG mock "$USER"
# Log out and back in, then:
make wayland-rpms
```

The build pipeline checks out these exact Fedora 45 dist-git release tags,
rather than a moving branch head:

- cairo-1.18.6-1.fc45
- weston-15.0.1-3.fc45
- gtk4-4.24.1-1.fc45
- libadwaita-1.10.0-2.fc45

The GTK 4.24.1 source is intentionally pinned: Fedora 45 package metadata has
also listed 4.24.2 builds, but the requested 4.24.1 baseline must not silently
drift. The builder records each dist-git tag and resolved commit in its source
manifest.

The pipeline verifies exact source RPM provenance for every generated binary
subpackage, patches the Meson switches, assigns the reserved Feclora RPM epoch
1, and sets the custom release
99.fc45.feclora1. Epoch 1 prevents any stock Fedora epoch-0 build, including
a future higher upstream version, from superseding these packages. Release 99
orders the custom rebuild above same-version Fedora builds.

Weston 15.0.1 has no `launcher-libseat` Meson option. Its DRM backend
unconditionally resolves the `libseat` dependency; the generated `weston-libs`
RPM must therefore require `libseat.so.1`, which the RPM verifier checks.

The build order is:
1. Build Cairo 1.18.6 and locate its runtime and development subpackages.
2. Install the custom Cairo runtime/development RPMs into the persistent
   Fedora 45 Mock root.
3. Build Weston 15.0.1 with DRM/kiosk enabled and XWayland/X11 disabled.
4. Build GTK 4.24.1 with Wayland enabled and GDK X11 disabled.
5. Install the custom GTK4 runtime/development RPMs into that same Mock root.
6. Rebuild libadwaita 1.10.0 against the custom GTK4/Cairo stack.
7. Inspect the actual binary RPMs before copying runtime RPMs and build-only
   development RPMs into separate output locations.

The pipeline does not modify Kickstart or install the RPMs into the Live
image. A successful run retains the patched Fedora source RPMs under
`sources/`, per-package Mock logs under `build-logs/`, the source commit
manifest and `build-environment.txt`. On failure, the temporary build
workspace is deliberately retained and its path is printed so the failure
logs and partial artifacts can be inspected. Review these records and all RPM
metadata before considering package admission. If the host cannot reach Fedora
dist-git or Fedora repositories, the build is blocked; do not substitute
stock RPMs or unverified upstream builds.

## Semantic parity audit

For each Textual workflow, compare the GTK implementation and tests at the
form and state-transition level:

1. Input fields, types, required/optional status, defaults and parameter names.
2. Validation order and messages, including server-side preflight calls.
3. Destructive confirmation scope, destination identity and irreversible
   effects; cancellation must not bypass confirmation.
4. Asynchronous request state, progress units, operation IDs and stale-page
   callback handling.
5. Cancellation request/acknowledgement races, repeated clicks and the
   possibility of partially written destinations.
6. Terminal states: completed, failed, cancelled, interrupted and unknown;
   status polling errors must not imply that a job stopped.
7. Refresh, retry, recovery and persistence after navigation or process loss.
8. Secret handling: no passphrases or credentials in logs, API events,
   persisted UI state or exception text.

The audit must cover all 14 sections, not only the 18 named disk operations.
Every semantic difference must be documented and either corrected or approved
as an intentional product change. Add behavioral tests for each workflow;
AST/string checks and action-name comparisons are insufficient.

## Weston session and appliance integration

Before enabling GTK:

- Run Weston as the unprivileged feclora user, not root.
- Establish a real PAM/logind session and verify XDG_RUNTIME_DIR,
  WAYLAND_DISPLAY, libseat logind seat acquisition and DRM device access.
- Ensure no inherited DISPLAY or XAUTHORITY; do not provide X11 sockets.
- Confirm Weston owns tty1 and DRM, kiosk-shell keeps the application
  fullscreen, and a compositor/application crash has a deterministic recovery
  path.
- Verify the root maintenance service on tty2 remains independently usable
  while Weston owns tty1; exiting maintenance returns to tty1.
- Keep KMSCON and getty from competing for the appliance VTs.

## Release gates

- [ ] Fedora 45 Cairo 1.18.6 custom RPMs built and inspected.
- [ ] Fedora 45 Weston 15.0.1 custom RPMs built and inspected.
- [ ] Fedora 45 GTK 4.24.1 custom RPMs built and inspected.
- [ ] libadwaita 1.10.0 rebuilt against custom GTK/Cairo and inspected.
- [ ] Complete target RPM database and payload pass the strict X11 audit.
- [ ] Semantic parity audit completed for all 14 sections and workflows.
- [ ] Behavioral GTK tests cover forms, parameters, confirmation, progress,
      cancellation, errors, retries and recovery.
- [ ] Weston/logind/libseat/DRM/VT session accepted.
- [ ] Automated project tests and ISO build pass on the exact commit.
- [ ] BIOS and UEFI VM boot and visible interaction accepted.
- [ ] Physical hardware, keyboard, display recovery and tty2 maintenance
      accepted and recorded.

Until every gate is checked with recorded evidence, Textual remains the
production boot interface. Do not claim a successful ISO build, VM boot,
BIOS/UEFI acceptance or RPM audit unless that exact operation has been run.

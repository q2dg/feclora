# Fedora 45 compatibility baseline

Feclora targets Fedora Linux 45 x86_64 for the ISO build host and Live
runtime. Build against Fedora 45 source packages; do not substitute Rawhide,
a later Fedora branch or arbitrary upstream snapshots.

## Production interface

The current Live image uses Textual on tty1. The root maintenance shell stays
on tty2. GTK4/PyGObject/libadwaita with Weston DRM/KMS and kiosk-shell is a
candidate migration only and is not enabled in the Live boot path.

## Strict Wayland-only target

The target must not install, include, start or expose XWayland, Xorg, Openbox,
the Weston X11 backend, the GDK X11 backend or X11 libraries. The GTK process
must set `GDK_BACKEND=wayland`, remove `DISPLAY`, and fail before importing
GTK if `WAYLAND_DISPLAY` is absent. Weston must run with `--no-config`,
`-B drm` and `--shell=kiosk-shell.so`, without `--xwayland`.

Stock Fedora 45 graphical RPMs are not admissible. The recorded source
baselines are:

| Package | Fedora 45 source baseline | Required Feclora build |
| --- | --- | --- |
| Weston / weston-libs | 15.0.1 | `-Dxwayland=false -Dbackend-x11=false -Drenderer-gl=false -Drenderer-vulkan=false`; retain DRM and kiosk-shell, run `--renderer=pixman` |
| GTK4 | 4.24.1 | `-Dx11-backend=false -Dwayland-backend=true -Dvulkan=disabled`; run with `GSK_RENDERER=cairo` |
| libadwaita | 1.10.0 | Rebuild against the custom GTK4 package |
| PyGObject | Fedora 45 system package | Keep `python3-gobject` and `python3-cairo` in the staged candidate manifest; do not pip-install bindings |

The current Textual Live image does not install python3-gobject or
python3-cairo. They are staged for the GTK candidate only, alongside the
custom Cairo RPMs, because the stock Cairo dependency chain would otherwise
introduce X11 libraries before the strict Wayland-only stack is ready.

The stock Weston runtime libraries contain XWayland and X11 backend modules
and link to X11 client libraries. The stock GTK4 package exposes the GDK X11
backend and X11 library dependencies. Therefore, excluding only the X server
packages or setting a Wayland environment variable is insufficient for this
appliance's no-X11 policy.

The stock Weston package also depends on `mesa-dri-drivers`; Fedora 45's Mesa
DRI package advertises `libX11-xcb`, `libxcb` and `libxshmfence`, while the Mesa
EGL package advertises `libX11`, `libX11-xcb` and `libxcb`. The candidate
therefore disables Weston's GL renderer and explicitly uses Pixman, retaining
the DRM/KMS backend and GBM dependency. GTK's Vulkan renderer is disabled and
GSK is pinned to Cairo. This trades GPU compositing for CPU rendering and must
be performance-tested on target hardware. The final installed-root audit is
required to prove the resolved Fedora 45 dependency closure is X11-free.

Before any custom RPM is added to Kickstart, run
`build/verify-wayland-rpms.sh` against the actual binary RPMs. It rejects
`xwayland.so`, `x11-backend.so`, `GdkX11-4.0.typelib`, X11 headers and
pkg-config metadata, X11 shared libraries, X11 package names and X11 runtime
or build dependencies. The installed-root mode audits the complete RPM
database and payload. Fedora 45 source-RPM provenance and the exact source
versions are mandatory.

## Build and acceptance gates

1. Fetch the Fedora 45 dist-git source branches for Weston, GTK4 and
   libadwaita.
2. Rebuild Weston 15.0.1 with XWayland and its X11 backend disabled, retaining
   DRM and kiosk-shell.
3. Rebuild GTK 4.24.1 with its X11 backend disabled and Wayland enabled.
4. Rebuild libadwaita 1.10.0 against that GTK4 build; retain Fedora's
   `python3-gobject` system package.
5. Inspect every generated RPM's file list and dependency metadata with the
   strict verifier before adding any of them to the Live image.
6. Complete semantic comparison of GTK forms and workflows against Textual:
   parameters, validation, destructive confirmation, progress, cancellation,
   errors, retries and recovery.
7. Validate the Weston systemd/logind/libseat session, DRM ownership, VT
   transitions and tty2 recovery.
8. Run automated tests, build the ISO, boot BIOS and UEFI guests, and complete
   physical hardware acceptance before changing the production boot route.

A source-level test, static RPM fixture or GTK window does not prove that the
custom packages build or that the complete appliance works. No graphical RPM
is considered admitted until the actual Fedora 45 build artifacts pass the
strict audit.

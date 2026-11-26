# Fedora 45 compatibility baseline

Feclora targets Fedora Linux 45 x86_64 for both the ISO build host and Live
runtime. Update packages through Fedora 45 repositories; do not substitute
Rawhide or an arbitrary upstream release for the system toolchain.

## Live interface

The current appliance boots Textual through `feclora-tui.service` on tty1.
GTK4/libadwaita is being migrated as the replacement frontend. The intended
compositor is Weston 15 DRM/KMS with `kiosk-shell`; Cage is explicitly not
used. The appliance uses Fedora's official Weston, GTK4 and libadwaita RPMs.
Those packages may contain optional X11 client backends and libraries, but
Feclora does not install the separate Xorg or XWayland server packages, does
not pass `--xwayland` to Weston, clears inherited X11 display variables and
forces GTK's Wayland backend. The GTK service remains disabled until behavioral
parity, VM testing and BIOS/UEFI acceptance are complete.
The application continues to use the root-owned allowlisted helper at
`/usr/libexec/feclora/feclora-api`; the `feclora` user has no general-purpose
passwordless root shell.

The test environment pins `textual==8.1.1` in `requirements-test.txt` so
automated UI tests are repeatable. This test dependency is separate from the
Fedora package installed in the Live image. Record the resolved Fedora package
version (`rpm -q python3-textual`) in release evidence and run the visible
keyboard-navigation acceptance checks against the built image.

## Build enforcement and acceptance

- `packages/base.txt` and the Kickstart `%packages` block must remain in sync.
- `build/validate.sh` verifies the Textual boot service, privileged helper
  boundary, official Fedora graphical runtime packages and absence of Xorg/
  XWayland server packages.
- The staged GTK candidate must select `LIBSEAT_BACKEND=logind`, unset
  inherited X11 display variables and obtain its user runtime directory through
  its PAM session; VM acceptance is required before enabling it.
- GitHub Actions runs the pinned Textual tests and static checks.
- `docs/BUILD.md` describes the ISO build and BIOS/UEFI smoke-test procedure.

Passing source tests does not establish that the package version in Fedora 45
renders correctly on every supported terminal or hardware configuration.
BIOS/UEFI boot, tty1 handoff, keyboard navigation, VT switching and display
recovery remain separate maintainer acceptance tasks. Weston/GTK runtime
acceptance is an additional gate before the Textual replacement.

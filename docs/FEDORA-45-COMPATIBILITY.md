# Fedora 45 compatibility baseline

Feclora targets Fedora Linux 45 x86_64 for both the ISO build host and Live
runtime. Update packages through Fedora 45 repositories; do not substitute
Rawhide or an arbitrary upstream release for the system toolchain.

## Live interface

The appliance installs `cage`, `gtk4`, `libadwaita` and `python3-gobject`.
The enabled `feclora-gtk.service` starts Cage on tty1 with
`cage -x -s -- /usr/bin/python3 -m feclora.gui_gtk`; `-x` disables XWayland
and `-s` permits switching to the tty2 recovery shell. A PAM/logind session
provides the Wayland runtime directory and seat access. Textual and its
`feclora-tui.service` remain installed as a mutually exclusive manual fallback,
but the TUI unit is not enabled by default. The application uses the root-owned,
allowlisted helper at `/usr/libexec/feclora/feclora-api`; the `feclora` user
has no general-purpose passwordless root shell.

The test environment pins `textual==8.1.1` in `requirements-test.txt` so
automated UI tests are repeatable. This test dependency is separate from the
Fedora package installed in the Live image. Record the resolved Fedora package
version (`rpm -q python3-textual`) in release evidence and run the visible
keyboard-navigation acceptance checks against the built image.

## Build enforcement and acceptance

- `packages/base.txt` and the Kickstart `%packages` block must remain in sync.
- `build/validate.sh` verifies the Textual boot service, privileged helper
  boundary and absence of the removed graphical packages.
- GitHub Actions runs the pinned Textual tests and static checks.
- `docs/BUILD.md` describes the ISO build and BIOS/UEFI smoke-test procedure.

Passing source tests does not establish that the package version in Fedora 45
renders correctly on every supported terminal or hardware configuration.
BIOS/UEFI Cage/Wayland startup, tty1 handoff, keyboard navigation, VT switching
and display recovery remain separate maintainer acceptance tasks.

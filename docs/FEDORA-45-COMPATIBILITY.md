# Fedora 45 compatibility baseline

Feclora targets Fedora Linux 45 x86_64 for both the ISO build host and Live
runtime. Update packages through Fedora 45 repositories; do not substitute
Rawhide or an arbitrary upstream release for the system toolchain.

## Live interface

The appliance boots GTK4/libadwaita through `feclora-gtk.service` on tty1.
Weston 15 uses DRM/KMS with `kiosk-shell`; Cage is not used. The appliance
uses Fedora's official Weston, GTK4 and libadwaita RPMs. Those packages may
contain optional X11 client backends and libraries, but Feclora does not
install the separate Xorg or XWayland server packages, does not pass
`--xwayland` to Weston, clears inherited X11 display variables and forces
GTK's Wayland backend.

The frontend calls the root-owned allowlisted helper at
`/usr/libexec/feclora/feclora-api`. The `feclora` account is unprivileged
and password-locked. tty2 is reserved for the local maintenance root shell;
physical access to the appliance must therefore be controlled.

## Build enforcement and acceptance

- `packages/base.txt` and the Kickstart `%packages` block must remain in sync.
- `build/validate.sh` verifies the GTK boot service, privileged helper
  boundary, official Fedora graphical runtime packages and absence of Xorg/
  XWayland server packages.
- The GTK service selects `LIBSEAT_BACKEND=logind`, unsets inherited X11
  display variables and obtains its user runtime directory through its PAM
  session.
- GitHub Actions runs the hardware-independent unit tests and static checks.
- `docs/BUILD.md` describes the ISO build and BIOS/UEFI smoke-test procedure.

Passing source tests does not establish that the package version in Fedora 45
renders correctly on every supported hardware configuration. BIOS/UEFI boot,
tty1 handoff, keyboard navigation, VT switching, display recovery and
destructive storage workflows remain separate maintainer acceptance tasks.

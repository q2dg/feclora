# Build pipeline

## Initial target

The build target is a Fedora 45 x86_64 Live appliance ISO for BIOS and UEFI
systems. Its userspace is based on a minimal Fedora Server package set, with
no general-purpose desktop environment. The intended local presentation is a
Cage Wayland kiosk running Firefox against Cockpit on localhost. The image
build uses Lorax `livemedia-creator` with QEMU virtualization and deliberately
avoids `--no-virt`, which bypasses the isolated virtualized build path.

The current Kickstart is still transitional: it builds the older console-led
Live image. The kiosk runtime, trusted local Cockpit certificate and secure
first-boot account provisioning must be implemented and accepted before the
image can be described as a completed kiosk appliance.

## Static validation and automated tests

Run the repository checks before building:

```bash
make validate
make test
make webui
```

GitHub Actions runs frontend compilation, Bash syntax checks, project-input
validation, ShellCheck, Python compilation and hardware-independent unit
tests. A passing CI run does not prove that an ISO can be built or booted.

## Build host

Use a disposable Fedora 45 x86_64 virtual machine if possible. Allocate at
least 4 CPU cores, 8 GiB RAM and 30 GiB free disk space. Install dependencies:

```bash
sudo bash build/install-host-deps.sh
```

Obtain the Fedora 45 x86_64 **DVD installation ISO** and verify its checksum
against Fedora's published checksum. Then run:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso bash build/build-iso.sh
```

The script compiles the Cockpit frontend, runs host preflight, stages the
Python package and frontend into the installer media, and invokes Lorax.
Results and logs are written under `out/`; inspect the complete result
directory before treating the build as successful.

## Important limitations

- The Kickstart and ISO pipeline are source-level build inputs, not a
  validated Live image. ISO generation and boot acceptance remain operator
  tasks.
- The current transitional Live Kickstart still contains an automatically
  logged-in `feclora` account with passwordless sudo. Anyone with physical
  access who can boot that image can obtain root. This is not the target kiosk
  security model and must be removed when secure first-boot provisioning and
  administrator access are implemented. Do not reuse this policy on an
  installed system.
- BIOS and UEFI boot, Secure Boot, Cockpit login, device discovery and all
  destructive storage operations require testing in disposable virtual
  machines or on disposable media before release.
- PXE boot, remote deployment, multicast networking and switch IGMP behavior
  require validation on the actual network. UDPcast multicast traffic is not
  encrypted or authenticated by UDPcast itself.

## Troubleshooting

Preserve the entire result directory, especially Anaconda and
livemedia-creator logs. Reproduce failures in a disposable VM and record the
Fedora release, package versions, installer ISO checksum and exact command
line. Do not use `--no-virt` as a workaround on a normal workstation.

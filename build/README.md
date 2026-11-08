# Build pipeline

## Initial target

The current build target is a Fedora 45 x86_64 rescue Live ISO for BIOS and
UEFI systems. The build uses Lorax `livemedia-creator` with QEMU
virtualization. It deliberately avoids `--no-virt`, which bypasses the
isolated virtualized build path.

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
- The Live console uses an automatically logged-in `feclora` account with
  passwordless sudo. Anyone with physical access who can boot this media can
  obtain root. Do not reuse this policy on an installed system.
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

# Build pipeline

## Initial target

The build target is a Fedora 45 x86_64 Live appliance ISO for BIOS and UEFI
systems. Its userspace is based on a minimal Fedora Server package set, with
no general-purpose desktop environment. The intended local presentation is a
Cage Wayland kiosk running Firefox against Cockpit on localhost. The image
build uses Lorax `livemedia-creator` with QEMU virtualization and deliberately
avoids `--no-virt`, which bypasses the isolated virtualized build path.

The Kickstart now selects Fedora's Server product environment, installs Cage
and Firefox, creates separate locked-administrator and unprivileged-kiosk
accounts, generates/trusts the local Cockpit certificate, and enables the
first-boot assistant and kiosk systemd services. This is source-level wiring;
BIOS/UEFI boot, Firefox policy behavior and physical kiosk acceptance have not
yet been run.

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


## Coordinated deployment bundle

For a single build-host workflow that builds the generic Feclora Live ISO,
selects or captures a Feclora whole-disk image, and publishes one shared
unattended answer with the image into a versioned bundle, use:

```bash
sudo python3 build/create-deployment-bundle.py \
  --fedora-iso /path/to/Fedora-45-x86_64-DVD.iso \
  --repository /mnt/feclora-images \
  --repository-id primary \
  --image-id fleet-image \
  --answer-file /path/to/shared-deployment-job.json \
  --output /mnt/feclora-images/fleet-bundle
```

The image ID must already exist in the selected repository. To capture a new
offline physical source before building the ISO and bundle, add
`--capture-source /dev/disk/by-id/...` and use a new image ID. The capture
engine performs its normal source-safety checks and never writes to the source.

The answer file is one schema-v1 automatic whole-disk `DeploymentJob` for the
entire Client group. Its repository/image IDs must match the command, and it
must contain all authorized MAC addresses and their stable target bindings.
The workflow canonicalizes this one answer once; it does not create per-client
answer files or embed repository credentials in the ISO.

The command runs the existing `build/build-iso.sh` in a private temporary
directory, then validates and atomically publishes the bundle. It requires the
same Fedora x86_64 build host, root privileges, KVM and ISO build dependencies
as the ordinary ISO build. The output directory must not already exist. The
ISO is included in the bundle; the temporary standalone ISO build directory is
removed afterwards. A P2V QCOW2 must first be imported with the Cockpit
`import_p2v` operation into a native Feclora disk image.

This is a build-host workflow, not a Live Cockpit ISO builder. The Cockpit
bundle operation remains available for assembling already-built inputs. ISO
boot, target hardware, repository-provider and real multicast acceptance are
still maintainer-run tasks.

## Important limitations

- The recovery-media workflow is exposed in Cockpit and runs as a durable local operation. It uses the Live runtime's `xorriso` package to replay El Torito boot metadata while adding a validated image set and target-bound restore answer under `/FECLORA/RECOVERY`; output is a separate ISO in a local or mounted filesystem repository. Boot-time embedded-image discovery and restore dispatch are still pending. See [Recovery ISO operator procedure](../docs/RECOVERY-ISO.md) for the documented xorriso command sequence, inspection and optional BIOS/UEFI acceptance. Repository development and CI never build the ISO.
- The Kickstart and ISO pipeline are source-level build inputs, not a
  validated Live image. ISO generation and boot acceptance remain operator
  tasks.
- The Live root filesystem is ephemeral by design. The first-boot administrator
  password, completion marker, local CA/private key and temporary session
  configuration are regenerated on every fresh boot. No Live-session
  persistence is required. Durable images/manifests belong in explicitly
  selected repositories; Feclora must not select a potential restore target
  disk implicitly.
- Cage disables ordinary VT switching by default; tty1–tty6 getty services
  are masked. Physical firmware/boot-menu access and keyboard escape behavior
  still require testing. The authenticated Cockpit Terminal remains an
  administrator capability inside Cockpit.
- BIOS and UEFI boot, Cockpit login, device discovery and all destructive
  storage operations require testing in disposable virtual machines or on
  disposable media before release.
- PXE boot, remote deployment, multicast networking and switch IGMP behavior
  require validation on the actual network. UDPcast multicast traffic is not
  encrypted or authenticated by UDPcast itself.

## Troubleshooting

Preserve the entire result directory, especially Anaconda and
livemedia-creator logs. Reproduce failures in a disposable VM and record the
Fedora release, package versions, installer ISO checksum and exact command
line. Do not use `--no-virt` as a workaround on a normal workstation.

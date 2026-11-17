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

## Generate the one shared unattended answer

Generate the canonical schema-v1 `DeploymentJob` before running the bundle
coordinator. Supply one `--client` argument per machine; the binding syntax is
`MAC=WWN|SERIAL`. Either selector may be empty, but not both. The generated
file is a single fleet-wide answer, not a set of per-client files.

```bash
python3 build/generate-shared-answer.py \
  --image-id fleet-image \
  --repository-id primary \
  --client '02:00:00:00:00:01=naa.0001|disk-1' \
  --client '02:00:00:00:00:02=|disk-2' \
  --network-interface enp2s0 \
  --transport multicast \
  --multicast-group 239.10.10.10 \
  --multicast-port 9000 \
  --boot-method iso \
  --output /secure/path/shared-deployment-job.json
```

For unicast, set `--transport unicast`; multicast settings are omitted from
the canonical job. For PXE boot, set `--boot-method pxe`; the job uses
`network_interface=auto`. The generator validates the complete job contract,
requires at least two authorized Clients for multicast, writes mode 0600, and
refuses to overwrite an existing answer. The answer contains no credentials.

## Coordinated deployment bundle

This is a separate consumer of the answer file, not an extension of the
answer generator. First create the shared answer with
`build/generate-shared-answer.py` (or prepare it in Cockpit). Then pass that
existing file to the bundle coordinator. The coordinator builds the generic
Live ISO, selects or captures a Feclora whole-disk image, validates the answer
against those inputs, and publishes the versioned bundle. It never generates
or edits the answer file:

```bash
sudo python3 build/create-deployment-bundle.py \
  --fedora-iso /path/to/Fedora-45-x86_64-DVD.iso \
  --repository /mnt/feclora-images \
  --repository-id primary \
  --image-id fleet-image \
  --answer-file /secure/path/shared-deployment-job.json \
  --output /mnt/feclora-images/fleet-bundle
```

The image ID must already exist in the selected repository. To capture a new
offline physical source before building the ISO and bundle, add
`--capture-source /dev/disk/by-id/...` and use a new image ID. The capture
engine performs its normal source-safety checks and never writes to the source.

The answer file is one schema-v1 automatic whole-disk `DeploymentJob` for the
entire Client group. Its repository/image IDs must match the command, and it
must contain all authorized MAC addresses and their stable target bindings.
The coordinator validates and packages this supplied shared answer; it does
not regenerate it, split it, or create per-client answer files. The ISO never
contains repository credentials.

The command runs the existing `build/build-iso.sh` in a private temporary
directory, then validates and atomically publishes the bundle. If `/tmp` lacks
space for the ISO build, pass `--work-directory /path/to/local-build-scratch`
on a local filesystem with the free space required by the normal build. It requires the
same Fedora x86_64 build host, root privileges, KVM and ISO build dependencies
as the ordinary ISO build. The output directory must not already exist. The
ISO is included in the bundle; the temporary standalone ISO build directory is
removed afterwards. Whole-disk images may use either the native RAW
artifact format or QCOW2; both are manifest-backed and can be selected directly
for local or coordinated restore.

This is a build-host workflow, not a Live Cockpit ISO builder. The Cockpit
bundle operation remains available for assembling already-built inputs. ISO
boot, target hardware, repository-provider and real multicast acceptance are
still maintainer-run tasks.

## Important limitations

- The Recovery ISO workflow is exposed in Cockpit and runs as a durable local operation. The Live image installs and enables `feclora-recovery-boot.service`; at boot it discovers exactly one mounted `/FECLORA/RECOVERY` payload, rejects symlinked or ambiguous payload directories, validates the answer and manifest, and dispatches the shared guarded restore engine after WWN/serial revalidation. The builder replays El Torito metadata and publishes a separate ISO to a local or mounted filesystem repository. Repository development and CI mock `xorriso`: they do not build or boot a real ISO. BIOS/UEFI and destructive-media acceptance remain operator responsibilities. See [Recovery ISO operator procedure](../docs/RECOVERY-ISO.md).
- Cockpit includes a legacy P2V bundle export form for copying a committed QCOW2 plus its `.p2v.json` sidecar from S3 to the local repository or a mounted writable filesystem repository. Ordinary manifest-backed QCOW2 images already use the standard image workflow and do not need this compatibility export.
- Cockpit restore profiles create, list and explicitly execute single-use whole-disk restore authorizations from a mounted persistent filesystem repository. Execution requires a typed destructive confirmation, stable WWN/serial identity and read-back verification. S3 storage, proportional profile execution and automatic boot-time profile execution are unsupported; the profile service remains opt-in and separate from PXE fleet restore.
- Proportional whole-disk restore is a separate Cockpit durable operation limited to supported GPT layouts whose final partition is ext2/3/4 or NTFS. It probes the original source filesystem read-only, shrinks only private staging, validates the rewritten GPT, and uses the guarded exact-capacity destination writer with identity revalidation and read-back verification. Other filesystems/layouts fail closed; this is not a general filesystem resize facility.
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

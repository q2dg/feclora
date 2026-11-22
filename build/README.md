# Build pipeline

## Initial target

The build target is a Fedora 45 x86_64 Live appliance ISO for BIOS and UEFI
systems. Its userspace is based on Fedora's `@core` package group plus Feclora's
explicit runtime package set. The Kickstart package list is unchanged by the
build-speed optimizations described here.

The image build uses Lorax `livemedia-creator` with QEMU virtualization and
deliberately avoids `--no-virt`, which bypasses the isolated virtualized build
path.

## Faster repeated builds

The frontend build now reuses `webui/node_modules` when its fingerprint still
matches both `package.json` and `package-lock.json`. A lockfile change or a
missing dependency directory triggers a fresh, reproducible `npm ci`. Frontend
tests and the production build still run on every invocation. npm's own download
cache is also retained by npm between builds.

QEMU resources are selected from the build host by default: up to 8 vCPUs and
approximately half of host RAM (bounded to 4–16 GiB). Override them when
necessary:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso \
  FECLORA_BUILD_VCPUS=8 FECLORA_BUILD_RAM=8192 make build
```

The Live ISO defaults to SELinux permissive while continuing to record AVC
denials. To build an enforcing image instead:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso \
  FECLORA_SELINUX_PERMISSIVE=0 make build
```

The default adds `enforcing=0` to the ISO's BIOS and UEFI kernel command lines.
Permissive mode does not change SELinux configuration on disk; review AVC
denials and explicitly select enforcing mode for release images.

If Fedora package downloads are the bottleneck, an HTTP caching proxy can be
provided. It must be reachable from the QEMU installer environment:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso \
  FECLORA_BUILD_PROXY=http://127.0.0.1:3128 make build
```

For a proxy running on the host, ensure the guest can reach it; guest loopback
is not host loopback. Lorax supports forwarding the proxy setting to the
installer. A local Fedora package mirror or a correctly configured caching
proxy can avoid downloading the same RPMs on every build.

The QEMU installation and Live image assembly still run on every build.
Lorax installs the package set afresh into its temporary image; this pipeline
does not yet cache that installed root filesystem. Therefore these changes
remove repeated Node dependency installation and allow better CPU/RAM use, but
cannot guarantee a specific build time. The biggest remaining gain is a
network-side RPM cache or mirror.

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

Use a Fedora 45 x86_64 build host with KVM enabled and at least 8 GiB RAM and
30 GiB free disk space. Install dependencies:

```bash
sudo bash build/install-host-deps.sh
```

Obtain the Fedora 45 x86_64 **DVD installation ISO** and verify its checksum
against Fedora's published checksum. Then run:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso make build
```

The script compiles and tests the Cockpit frontend, runs host preflight, stages
the Python package and frontend into the installer media, and invokes Lorax.
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
directory, then validates and atomically publishes the bundle. If `/tmp`
lacks space for the ISO build, pass `--work-directory` on a local filesystem
with sufficient free space. It requires the same Fedora x86_64 build host,
root privileges, KVM and ISO build dependencies as the ordinary ISO build.
The output directory must not already exist. The ISO is included in the bundle;
the temporary standalone ISO build directory is removed afterwards.
Whole-disk images may use either the native RAW artifact format or QCOW2; both
are manifest-backed and can be selected directly for local or coordinated
restore.

This is a build-host workflow, not a Live Cockpit ISO builder. The Cockpit
bundle operation remains available for assembling already-built inputs. ISO
boot, target hardware, repository-provider and real multicast acceptance are
still maintainer-run tasks.

## Important limitations

- The Recovery ISO workflow is exposed in Cockpit and runs as a durable local
  operation. The Live image installs and enables
  `feclora-recovery-boot.service`; at boot it discovers exactly one mounted
  `/FECLORA/RECOVERY` payload, rejects symlinked or ambiguous payload
  directories, validates the answer and manifest, and dispatches the shared
  guarded restore engine after WWN/serial revalidation. The builder replays
  El Torito metadata and publishes a separate ISO to a local or mounted
  filesystem repository. BIOS/UEFI and destructive-media acceptance remain
  operator responsibilities. See [Recovery ISO operator procedure](../docs/RECOVERY-ISO.md).
- Cockpit restore profiles create, list and explicitly execute single-use
  whole-disk restore authorizations from a mounted persistent filesystem
  repository. Execution requires a typed destructive confirmation, stable
  WWN/serial identity and read-back verification.
- The Kickstart and ISO pipeline are source-level build inputs, not a
  validated Live image. ISO generation and boot acceptance remain operator
  tasks.
- The Live root filesystem is ephemeral by design. The local CA/private key and
  temporary session configuration are regenerated on every fresh boot; no
  user password is created or requested. No Live-session persistence is
  required.
- PXE boot, remote deployment, multicast networking and switch IGMP behavior
  require validation on the actual network. UDPcast multicast traffic is not
  encrypted or authenticated by UDPcast itself.

## Troubleshooting

Preserve the entire result directory, especially Anaconda and
livemedia-creator logs. Reproduce failures in a disposable VM and record the
Fedora release, package versions, installer ISO checksum and exact command
line. Do not use `--no-virt` as a workaround on a normal workstation.

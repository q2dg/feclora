# Build and validate the live ISO

This procedure describes how to build the Fedora 45 x86_64 Feclora Live kiosk appliance and how to validate it in disposable QEMU virtual machines.
It is a runbook, not evidence that the build or boot tests have passed.

> **Implementation status:** the reproducible build pipeline, application-payload integration, and operator runbook are implemented. Executing the build and BIOS/UEFI boot acceptance remains an operator validation step; this document is not evidence that those tests have passed. Do not distribute an image as tested until the checks below have been executed and recorded.

## 1. Scope and build host

The initial build target is Fedora 45 on an x86_64 host. The build uses
Anaconda/Kickstart through Lorax `livemedia-creator`, with QEMU virtualization.
The script intentionally does not use `--no-virt`.

Use a dedicated build machine or VM with:

- Node.js and npm (the build-host dependency installer provides both) to compile the React/PatternFly Cockpit package.

- Fedora 45 x86_64 and working Fedora package repositories.
- Hardware virtualization enabled in firmware and KVM available to the host.
- Enough free disk space for the source DVD, augmented installer ISO,
  intermediate build tree, logs, and final ISO. Allow tens of GiB rather than
  planning around the final ISO size alone.
- A graphical session for the interactive QEMU smoke tests, or a separately
  configured display/serial workflow.
- A Fedora 45 x86_64 DVD installer ISO.

Fedora releases have finite support windows. Fedora 45 is the project's
initial baseline, not a promise that it will remain a supported build host.
If Fedora 45 repositories are no longer available, do not silently substitute
another release: first update and test the project baseline and build inputs.

## 2. Prepare the host

Clone the repository and enter its working tree:

```bash
git clone https://github.com/q2dg/feclora.git
cd feclora
git checkout main
```

Install the build dependencies:

```bash
make deps
```

This invokes `build/install-host-deps.sh`, which installs the Fedora packages
`lorax`, `lorax-lmc-virt`, `qemu-kvm`, and `edk2-ovmf`.

Check the host architecture, virtualization device, and available space:

```bash
uname -m
test -c /dev/kvm && echo "KVM device available" || echo "KVM unavailable"
df -h .
```

The expected host is Fedora 45 on `x86_64`. If `/dev/kvm` is unavailable,
fix host virtualization permissions/configuration before building; the normal
build path requires QEMU virtualization.

After setting `FEDORA_INSTALL_ISO` in the next section, run the automated
preflight before the build:

```bash
make preflight FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
```

The preflight checks the Fedora release, architecture, input files, required
commands, KVM access, and free space on the output filesystem. It reserves a
conservative default minimum of 20 GiB; override this with
`FECLORA_MIN_FREE_GIB` only after checking the actual space requirements for
the selected installer ISO and build workload. Passing preflight does not
guarantee that the build will fit or complete.

## 3. Obtain and verify the Fedora installer ISO

Download the Fedora 45 x86_64 DVD installer ISO from an official Fedora
distribution mirror. Verify its SHA-256 digest against the checksum published
by Fedora for that exact image before using it.

For example:

```bash
sha256sum Fedora-45-x86_64-DVD.iso
```

Compare the result manually with the official published checksum. Do not
treat a checksum calculated locally, without comparison to the published
value, as authenticity verification.

Set the path to the verified ISO:

```bash
export FEDORA_INSTALL_ISO="$PWD/Fedora-45-x86_64-DVD.iso"
test -f "$FEDORA_INSTALL_ISO"
```

The build script also accepts an absolute path elsewhere on the host.

## 4. Run static checks and unit tests

Before building:

```bash
make validate
make test
make preflight FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
```

These checks cover shell syntax/project validation and hardware-independent
Python unit tests. They do not build an ISO, exercise Anaconda, or prove that
the image boots.

## 5. Build the ISO

Run the Makefile target:

```bash
make build FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
```

The target invokes `build/build-iso.sh` with root privileges. The script:

1. Runs the host preflight: checks Fedora 45, x86_64, the input ISO,
   Kickstart, application source, required executables, KVM access, and a
   configurable minimum of free output space.
2. Builds the React/PatternFly Cockpit frontend with `build/build-webui.sh`.
3. Stages the Python application at `out/feclora-app/src/feclora` and the
   frontend build at `out/feclora-app/webui/dist`.
4. Uses `mkksiso --add` to add the complete application payload and Kickstart
   to a temporary installer ISO named `out/feclora-installer.iso`.
5. Runs `livemedia-creator --make-iso` against the augmented installer ISO,
   using QEMU virtualization and the project's Kickstart.
6. Requests the final image as `out/feclora-live.iso`.

The expected final artifact is:

```text
out/feclora-live.iso
```

If the build fails, preserve the complete terminal output and the contents of
`out/` (especially Lorax/Anaconda logs) before cleaning or retrying. Do not
delete the output directory until the failure has been diagnosed.

## 6. Inspect the generated artifact

After a successful build command:

```bash
test -s out/feclora-live.iso
file out/feclora-live.iso
ls -lh out/feclora-live.iso
sha256sum out/feclora-live.iso
```

Record the checksum and file size with the test results. A successful build
process and a non-empty ISO are necessary but not sufficient acceptance
criteria: the image must still boot in both firmware modes.

## Runtime behavior

The Kickstart selects Fedora's Server product environment and adds Cage and
Firefox as the only local graphical shell. The kiosk starts on tty1; no
general-purpose desktop or display manager is installed. On each fresh Live
boot the first-boot page asks the operator to set the `feclora` administrator
password before redirecting to Cockpit. The local Cockpit CA/certificate is
generated and trusted automatically before the Cockpit socket starts.

The Live root is intentionally ephemeral. The administrator password, local CA
private key, first-boot completion marker and temporary Feclora configuration
are session-local and reset on reboot. Each boot begins a new session; this is
the intended operating model, not a missing persistence feature. Images,
manifests and other data that must survive are written to repositories or
storage explicitly selected by the operator. Never select a potential restore
target disk implicitly.

## 7. Boot-test BIOS and UEFI

Follow [the VM smoke-test procedure](../tests/VM-SMOKE-TEST.md). Run the BIOS
and UEFI tests separately. Use disposable virtual storage only; do not attach
host block devices.

At minimum, verify:

- BIOS and UEFI boot reach the Firefox kiosk on tty1 without a desktop or
  console login prompt.
- The first-boot assistant appears and accepts a new 14–128 character
  administrator password; the administrator account was locked before setup.
- The assistant redirects to `https://localhost:9090/cockpit/@localhost/feclora/index.html` without a certificate
  warning.
- `systemctl status cockpit.socket feclora-cockpit-certificate.service
  feclora-kiosk-bootstrap.service feclora-kiosk.service` shows expected states.
- `test -s /usr/share/cockpit/feclora/index.html` succeeds and Cockpit
  displays storage inventory and the local Operations wizard.
- `/usr/share/feclora/python/feclora` contains the Python application.
- Firefox `WebsiteFilter` blocks external URLs and systemd cgroup IP filters
  deny all kiosk network destinations except loopback.
- The kiosk account is not in `wheel`; getty@tty1–tty6 are masked; there is
  no autologin configuration or NOPASSWD sudo rule.
- Firefox and Cage restart after terminating the kiosk process.
- After reboot, the Live session asks for the administrator password again;
  this confirms the documented ephemeral-session behavior, not persistence.

The bootstrap assistant is loopback-only and is not exposed through QEMU
port forwarding or the LAN. Complete password setup in the VM's local display.
Cockpit is bound to guest loopback only; QEMU host port forwarding for 9090 is
not part of the supported kiosk test path.

The Cockpit Terminal page is available for diagnostics; the old `dialog` menu is not part of the supported startup flow. Remote Server/Client deployment is integrated through the persistent service and authenticated TLS control path. The unattended PXE answer workflow publishes a validated JSON answer and answer-specific script through Caddy; the Live client resolves the repository ID through its normal SSHFS, NFS, SMB/CIFS or S3 repository manager and invokes the guarded whole-disk restore engine. Repository credentials are not placed in the answer file. This workflow is distinct from Server-authenticated Remote jobs and does not provide Server-side operation-result reconciliation. Consult the [feature matrix](FEATURE-MATRIX.md) for exact scope and limitations.

### Kiosk operator acceptance (pending)

The kiosk implementation is now present in source and Kickstart. It is not
accepted until BIOS and UEFI cold boots, Firefox enterprise policy behavior,
Cockpit TLS trust, administrator bootstrap, service restart and physical
keyboard/TTY escape behavior have been exercised on disposable VMs and
representative hardware. Follow [the VM smoke-test procedure](../tests/VM-SMOKE-TEST.md)
and record results; do not infer hardware acceptance from static validation.

A successful Cockpit page load does not validate destructive workflows.
Verify capture/restore/clone only with disposable virtual disks and follow
the dedicated imaging acceptance checks.
## 8. Record results

For every build/test run, record:

- Git commit ID and build date.
- Host Fedora release, architecture, and kernel.
- Input DVD ISO filename and verified SHA-256.
- Build command and whether `livemedia-creator` completed successfully.
- Final ISO filename, size, and SHA-256.
- QEMU version and whether KVM acceleration was enabled.
- BIOS and UEFI firmware details (including OVMF file paths/versions).
- BIOS boot result, UEFI boot result, launcher result, and inventory result.
- Relevant logs and any deviations or failures.

Do not mark the live-image milestone complete until the ISO build, BIOS boot,
UEFI boot, payload/launcher, and virtual-device inventory checks have all
passed. A VM boot test does not validate disk imaging or restoration; those
require separate tests using disposable virtual disks.

# Build and validate the live ISO

This procedure describes how to build the initial Fedora 45 x86_64 feclora
rescue image and how to validate it in disposable QEMU virtual machines.
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
2. Stages the Python application at `out/feclora-app/src/feclora`.
3. Uses `mkksiso --add` to add that payload and the Kickstart to a temporary
   installer ISO named `out/feclora-installer.iso`.
4. Runs `livemedia-creator --make-iso` against the augmented installer ISO,
   using QEMU virtualization and the project's Kickstart.
5. Requests the final image as `out/feclora-live.iso`.

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

## 7. Boot-test BIOS and UEFI

Follow [the VM smoke-test procedure](../tests/VM-SMOKE-TEST.md). Run the BIOS
and UEFI tests separately. Use disposable virtual storage only; do not attach
host block devices.

At minimum, verify:

- BIOS boot reaches the expected live session.
- UEFI boot reaches the expected live session.
- The feclora user/session starts as configured.
- `sudo -n true` succeeds in this explicitly privileged rescue image.
- The feclora launcher exists and starts:
  `/usr/local/bin/feclora-ui`.
- The UI displays the virtual block device and its metadata.
- The application payload was copied into the live root filesystem at
  `/usr/share/feclora/python/feclora`.

For payload diagnosis in the live session, inspect:

```bash
test -d /usr/share/feclora/python/feclora
test -x /usr/local/bin/feclora-ui
/usr/local/bin/feclora-ui
```

A successful launcher invocation should display the Local rescue / Server / Client mode selector. Local rescue exposes the dialog-based storage and imaging workflows; Server and Client networking remain opt-in. The startup menu also offers a live-session keyboard-layout selector (including Spanish); it changes the active console keymap using `loadkeys` and does not alter the image language or persist across reboots. Verify capture/restore workflows only with disposable virtual disks and follow the dedicated imaging acceptance checks. A successful launcher start alone does not validate destructive workflows.

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

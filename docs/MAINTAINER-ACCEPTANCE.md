# Maintainer acceptance checklist

This checklist records release evidence that cannot be established by unit
tests, static checks, documentation validation or CI. It is committed in the
public repository: never add passwords, private keys, personal data or
unpublished credentials.

## Owner-run acceptance

- [ ] Build the ISO using [the documented procedure](BUILD.md). Record the
      tested commit, Fedora build host, installer ISO checksum, build logs,
      output size and final SHA-256.
- [ ] Boot the ISO on physical hardware in BIOS and UEFI modes. Record firmware,
      hardware, kernel command line and results separately from QEMU smoke
      tests.
- [ ] Test the GTK/Weston kiosk on physical hardware, including first-boot
      language selection, keyboard-only navigation, keyboard-layout changes,
      tty2 maintenance handoff and return to tty1, DRM/KMS recovery and service
      restart behavior.
- [ ] Verify the appliance account remains password-locked and that physical
      access to the passwordless root maintenance shell on tty2 is restricted.
- [ ] Perform restore and clone operations against disposable real disks.
      Verify source/target identity, overwrite confirmation, read-back
      verification and failure behavior. Never use production data or a disk
      whose contents are not disposable.
- [ ] Validate SSHFS, NFS, SMB/CIFS and S3 against real endpoints, including
      permissions, invalid credentials, disconnects, interrupted transfers
      and recovery.
- [ ] Validate multi-Client unicast and multicast deployment. Record Client
      count, network topology, IGMP/switch configuration, per-Client outcomes
      and failures.
- [ ] Capture a disposable/offline physical source in RAW and QCOW2 formats.
      Verify manifests, artifact digests, logical sector size and partition
      table; restore to disposable media and verify sectors. Separately record
      guest boot tests and any remediation.
- [ ] Exercise deployment-bundle creation on the documented disposable
      Fedora x86_64/KVM host, both with an existing image and with
      --capture-source. Verify ISO logs/checksum, image manifest and digests,
      shared answer, MAC bindings, no-overwrite behavior and interrupted
      publication cleanup.
- [ ] Test interactive and unattended PXE on an isolated network, including
      DHCP/ProxyDHCP, BIOS/UEFI, answer publication/revocation, admission
      limits, repository resolution and restore failure paths.
- [ ] Review visible UI strings and verify advertised locale coverage. Record
      untranslated strings and test physical keyboard layouts and RTL behavior.
- [ ] Review Dependabot proposals and resolve CodeQL findings before release.
- [ ] Add version-matched real screenshots where useful. Keep illustrative
      SVGs visibly labeled as mockups, never runtime evidence.

## Evidence to record

For every run, record the tested commit SHA, date, host/VM hardware,
Fedora/kernel/tool versions, exact procedure, expected and actual results,
logs or screenshots, deviations and a clear PASS/FAIL/BLOCKED outcome.

An unexecuted or failed check remains pending. Do not mark a release complete
solely because CI passes.

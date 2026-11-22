# Maintainer acceptance checklist

> **Repository visibility:** this file is committed in the public Feclora repository. It is an internal-style maintainer checklist, not a private document. Do not put passwords, private keys, personal data, or unpublished credentials here. Move it to a private repository or local untracked file if confidential handling is required.

This checklist records the remaining hands-on validation owned by the maintainer. These tasks are deliberately not represented as completed by unit tests, CI, static checks, or documentation. CI covers Python tests and source-level boot checks; those automated checks do not replace runtime acceptance.

## Owner-run release tasks

- [ ] Build the ISO using the documented procedure and record the commit, Fedora build host, installer ISO checksum, build logs, output size and final SHA-256.
- [ ] Boot the ISO in BIOS and UEFI modes; record firmware/VM configuration and results separately.
- [ ] Verify that no diagnostic password or unnecessary console account remains, and that the `feclora` appliance account stays password-locked.
- [ ] Test the Textual interface on physical hardware and virtual machines, including first-boot language selection, keyboard-only navigation, keyboard-layout changes, root-terminal handoff to tty2 and return to tty1, and recovery after service restart.
- [ ] Perform restore operations against disposable real disks. Verify source/target identity, overwrite confirmation, read-back verification and failure behavior. Never use production data or a disk whose contents are not disposable.
- [ ] Validate each remote repository provider against a real endpoint: SSHFS, NFS, SMB/CIFS and S3-compatible storage. Include permissions, bad credentials, disconnects, interrupted transfers and recovery.
- [ ] Validate deployment with multiple Clients, including unicast and multicast where applicable. Record Client count, network topology, IGMP/switch configuration, per-Client results and failures.
- [ ] Capture a disposable/offline physical source through the normal whole-disk workflow in both RAW and QCOW2 formats. Verify each manifest, artifact digest, logical sector size and partition-table snapshot; restore the QCOW2 image directly to a disposable VM disk and compare the restored sectors. Then boot under documented hypervisor/firmware combinations. Record guest OS, virtual hardware, firmware, storage controller and any manual boot remediation; do not equate a successful sector restore with a bootable guest.
- [ ] Run `build/create-deployment-bundle.py` on the documented disposable Fedora x86_64/KVM build host using an existing Feclora image, then repeat with `--capture-source` against a disposable/offline source. Verify the ISO build logs/checksum, image manifest and artifact digests, one shared answer in the published bundle, complete MAC target bindings, no-overwrite behavior and cleanup after interrupted publication. Do not count this as BIOS/UEFI boot or real-network deployment acceptance.
- [ ] Exercise the Textual bundle assembly operation separately using already-built inputs. Verify every bundle-manifest digest, byte-identical shared answer content, complete MAC target bindings, no-overwrite behavior and cleanup after interrupted publication. Removable-media answer discovery and Caddy/DHCP delivery remain separate acceptance items; do not claim ISO/USB or PXE discovery from bundle co-location alone.
- [ ] Test interactive and unattended PXE in an isolated network, including DHCP/ProxyDHCP, BIOS/UEFI, answer publication/revocation, client admission limits, repository resolution and restore failure paths.
- [ ] After runtime acceptance, add version-matched real screenshots where useful. Task-specific illustrative SVG mockups are published for the operator workflows; keep their mockup labels and never present them as runtime evidence.
- [ ] Review all visible UI strings and complete/verify the 14 advertised locale dictionaries; record any intentionally untranslated text rather than silently claiming full localization.
- [ ] Review Dependabot proposals for GitHub Actions and resolve CodeQL findings before a release.

## Evidence to record

For each run, record the tested commit SHA, date, host/VM hardware, Fedora/kernel/tool versions, exact procedure, expected result, actual result, logs or screenshots, deviations and a clear PASS/FAIL/BLOCKED outcome. Keep automated test results and operator acceptance evidence separate.

A failed or unexecuted check remains pending. Do not mark the release complete solely because CI passes.

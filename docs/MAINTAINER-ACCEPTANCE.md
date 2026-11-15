# Maintainer acceptance checklist

> **Repository visibility:** this file is committed in the public Feclora repository. It is an internal-style maintainer checklist, not a private document. Do not put passwords, private keys, personal data, or unpublished credentials here. Move it to a private repository or local untracked file if confidential handling is required.

This checklist records the remaining hands-on validation owned by the maintainer. These tasks are deliberately not represented as completed by unit tests, CI, static checks, or documentation.

## Owner-run release tasks

- [ ] Build the ISO using the documented procedure and record the commit, Fedora build host, installer ISO checksum, build logs, output size and final SHA-256.
- [ ] Boot the ISO in BIOS and UEFI modes; record firmware/VM configuration and results separately.
- [ ] Test Cockpit and the Firefox kiosk on physical hardware and virtual machines, including first-boot password setup, TLS trust, keyboard/layout, service restart and kiosk escape-path behavior.
- [ ] Perform restore operations against disposable real disks. Verify source/target identity, overwrite confirmation, read-back verification and failure behavior. Never use production data or a disk whose contents are not disposable.
- [ ] Validate each remote repository provider against a real endpoint: SSHFS, NFS, SMB/CIFS and S3-compatible storage. Include permissions, bad credentials, disconnects, interrupted transfers and recovery.
- [ ] Validate deployment with multiple Clients, including unicast and multicast where applicable. Record Client count, network topology, IGMP/switch configuration, per-Client results and failures.
- [ ] Run P2V against a disposable/offline physical source, verify the QCOW2 and `.p2v.json` digests, import/convert it through the supported Feclora restore-image path when available, then boot the resulting VM under the documented hypervisor/firmware combinations. Record guest OS, virtual hardware, firmware, storage controller and any manual boot remediation; do not equate successful QCOW2 conversion with a bootable guest.
- [ ] Exercise the current Cockpit bundle assembly operation using an existing generic Live ISO, a verified Feclora whole-disk image and one shared schema-v1 automatic DeploymentJob answer. Verify every bundle-manifest digest, byte-identical shared answer content, complete MAC target bindings, no-overwrite behavior and cleanup after interrupted publication. Separately track the still-pending one-flow ISO/image/answer generation and removable-media answer discovery; do not claim ISO/USB or PXE discovery from bundle co-location alone.
- [ ] Test interactive and unattended PXE in an isolated network, including DHCP/ProxyDHCP, BIOS/UEFI, answer publication/revocation, client admission limits, repository resolution and restore failure paths.
- [ ] After runtime acceptance, add version-matched real screenshots where useful. Three illustrative SVG mockups are already published; keep their mockup labels and never present them as runtime evidence.
- [ ] Verify that a clean checkout installs and builds successfully with `npm ci` using the committed `webui/package-lock.json`; update the lockfile only when intentionally changing frontend dependencies.
- [ ] Review all visible UI strings and complete/verify the 14 advertised locale dictionaries; record any intentionally untranslated text rather than silently claiming full localization.
- [ ] Review Dependabot proposals and resolve high-severity npm audit and CodeQL findings before a release.

## Evidence to record

For each run, record the tested commit SHA, date, host/VM hardware, Fedora/kernel/tool versions, exact procedure, expected result, actual result, logs or screenshots, deviations and a clear PASS/FAIL/BLOCKED outcome. Keep automated test results and operator acceptance evidence separate.

A failed or unexecuted check remains pending. Do not mark the release complete solely because CI passes.

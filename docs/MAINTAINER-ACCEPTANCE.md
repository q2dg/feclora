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
- [ ] Test interactive and unattended PXE in an isolated network, including DHCP/ProxyDHCP, BIOS/UEFI, answer publication/revocation, client admission limits, repository resolution and restore failure paths.
- [ ] Add real screenshots or mockups to the documentation. Label every mockup clearly as illustrative; never present it as a screenshot or runtime evidence.

## Evidence to record

For each run, record the tested commit SHA, date, host/VM hardware, Fedora/kernel/tool versions, exact procedure, expected result, actual result, logs or screenshots, deviations and a clear PASS/FAIL/BLOCKED outcome. Keep automated test results and operator acceptance evidence separate.

A failed or unexecuted check remains pending. Do not mark the release complete solely because CI passes.

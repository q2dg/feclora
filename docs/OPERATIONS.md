---
layout: default
title: Operational lifecycle - backup, upgrade, rollback and distribution
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# Operational lifecycle: backup, upgrade, rollback and distribution

This runbook describes the current Live-appliance operating model. It does not
claim that Feclora has an in-place updater, persistent system configuration
backup, artifact provenance or a published release pipeline.

## Persistence boundary

A fresh Feclora Live boot creates a new ephemeral system session. The local
administrator password, CA/private key, temporary configuration and service
state are regenerated or reset. Images and manifests must live in explicitly
selected repositories outside the ephemeral Live root.

Treat repository contents and the Feclora Live environment as separate backup
domains:

- Back up image artifacts and their manifests using the repository owner's
  normal backup policy. Preserve the complete image set; do not copy only a
  manifest or a subset of its artifacts.
- Verify each image set using its manifest byte counts and SHA-256 digests
  before and after copying. Keep an independent backup of important data.
- Back up external NFS/SMB/SSH/S3 service configuration using the procedures
  of the service owner. Feclora does not administer those services.
- Do not export passwords, private keys, age identities or repository
  credentials into ordinary documentation, issue trackers or screenshots.
  Because the Live session is ephemeral, expect to re-enter or reprovision
  credentials after a fresh boot.
- Record non-secret connection metadata (provider type, endpoint, export/share,
  bucket/prefix and repository ID) in the maintainer's protected operational
  records.

## Upgrade procedure

There is currently no supported in-place Feclora Live system upgrade. Updating
the source tree does not update a running Live session. The supported
operational approach is to build and boot a new ISO using
[the build procedure](BUILD.html).

1. Review the release notes and the exact source commit intended for the new
   image. Check CI, Python tests, frontend build, localization checks,
   dependency audit and CodeQL results for that commit.
2. Back up and verify all required repository image sets and any external
   provider configuration using the provider's own backup process.
3. Build the new ISO by following [BUILD](BUILD.html). Record the installer
   ISO checksum, source commit, build logs, output size and resulting ISO
   SHA-256.
4. Boot the candidate ISO in disposable BIOS and UEFI VMs. Validate Cockpit,
   kiosk startup, storage discovery and repository connectivity before using
   it on operational machines.
5. On disposable target media, exercise the storage operations relevant to
   the deployment. Never use a production disk as a test target.
6. Boot the new ISO in the intended environment. Reconfigure network profiles,
   repositories and credentials as required by the ephemeral-session model.
7. Verify repository identity and read access, list known image manifests,
   validate a selected image set, and only then enable any deployment service.
8. Record the tested commit, ISO checksum, test results and any deviations in
   [the maintainer acceptance checklist](MAINTAINER-ACCEPTANCE.html).

## Interrupted S3 image publication

S3 image publication uses the manifest as its commit marker: Feclora uploads
and verifies every artifact first, then publishes the manifest last. If the
final manifest write fails, the payload objects may remain in the bucket but
the image is intentionally absent from the Feclora image inventory. This is
an incomplete publication, not a committed backup.

Do not treat an object prefix by itself as a valid image set and do not create
or copy a manifest manually to make it visible. Retry publication only after
checking the original manifest and every artifact's size and SHA-256. If the
image is no longer needed, inspect the exact object keys and remove orphaned
payloads using the S3 provider's own administrative tooling; Feclora does not
automatically delete partially uploaded objects because it cannot safely
assume that no other writer or recovery process needs them. Keep provider
versioning/retention policy and independent backups in force.

## Interrupted Server/Client deployment recovery

A Server/Client job is an audit trail, not a resumable transfer checkpoint.
The Server journal is stored at
`/var/lib/feclora/deployments/<job-uuid>.jsonl`; the Client keeps its local
request/status records under `/var/lib/feclora/client-jobs/`, including
`<job-uuid>.status.json`. Preserve both endpoints' records before rebooting,
restarting services or cleaning temporary files. The Server journal is
append-only and SHA-256 hash-chained; do not edit, truncate, concatenate or
recreate it manually.

After an unexpected exit, use this sequence:

1. Stop attempts to restart or re-arm the same job. Feclora deliberately
   rejects a job definition whose journal already contains session history.
   A Client process exit marks a nonterminal local status as
   `interrupted`; it does not reconnect or resume block-device I/O.
2. Preserve the Server journal, each selected Client's status record and
   operation logs. Record the job UUID, last durable event, per-Client
   terminal state and last persisted byte count. Progress is the last durable
   observation, not proof of how many bytes reached stable media.
3. Inspect every destination independently. Match the physical device using
   stable identity (WWN/serial where available), then verify its current
   geometry and contents. Do not rely on a saved `/dev/sdX` path: device names
   can change after reboot. For clone jobs, inspect both source and receiver.
4. Treat every destination without a successful terminal verification result
   as untrusted, including a Client that disconnected after reporting progress.
   A successful result from one Client does not make another Client's
   incomplete destination safe.
5. Reconcile the interrupted job only after the operator has inspected every
   selected Client and target. Keep the original journal as evidence; do not
   manufacture terminal success events or reset the job to `created`.
6. If another operation is required, create a new job with fresh approvals and
   revalidate the source image and every destination. Never reuse an interrupted
   job as a retry mechanism.

A journal hash chain detects accidental or unauthorized modification of its
records; it does not prove that a disk write completed or that the journal
came from an authenticated publisher. The Client status file is local
operational evidence and must be correlated with the Server journal. If either
endpoint's evidence is missing, corrupt or contradictory, stop and resolve
the discrepancy before writing to any target.

## Rollback and interrupted operations

Because the system is Live and has no in-place upgrade mechanism, rollback
means booting a previously retained, known-good Feclora ISO and reapplying its
session configuration. Keep the previous ISO and its checksum until the new
version has passed the required acceptance checks.

Booting an older ISO does **not** roll back writes already made to target disks.
Feclora cannot transactionally undo a partially completed raw disk restore or
clone. If a destructive operation is interrupted, treat the destination as
untrusted, preserve the operation journal/logs, inspect the device identity and
geometry, and restore again from a verified source only after explicit review.
Never automatically resume a destructive write.

## Distribution and release evidence

The build pipeline currently creates a local ISO under `out/`; this repository
does not provide a complete signed-release publication pipeline. Before
sharing an ISO:

- retain the exact source commit and complete build logs;
- calculate and publish the ISO SHA-256 separately from the artifact;
- state the Fedora baseline and supported architecture;
- distinguish "built", "boot-tested in VM", "tested on hardware" and
  "release-accepted";
- do not claim a checksum proves publisher authenticity; use a trusted,
  authenticated distribution channel;

The image-manifest integrity model is byte count plus SHA-256. A digest
verifies artifact integrity against the manifest; it does not authenticate
the publisher.

## Quality and localization status

The frontend's direct dependencies are pinned in `webui/package.json`, and
the complete transitive dependency graph is committed in
`webui/package-lock.json` (lockfile version 3). CI and
`build/build-webui.sh` install from that lockfile with `npm ci`; the build
script fails if the lockfile is missing rather than silently resolving a new
dependency graph. CI verifies clean-checkout installation and frontend builds;
update the lockfile only for intentional dependency changes.

Dependabot proposes updates for npm dependencies and GitHub Actions. CodeQL
runs scheduled and on changes for Python and JavaScript/TypeScript. These
automated scanners complement, but do not replace, code review, tests and
maintainer release acceptance.

The interface currently offers 14 locales, but translation coverage is not
complete across all visible text and all workflows. Missing translations may
fall back to English. Do not advertise the interface as fully translated
until each locale has been reviewed end to end.

## Screenshots and mockups

Use genuine screenshots from a tested runtime where available. If a mockup is
used, label it visibly as **Illustrative mockup — not a runtime screenshot**.
Record the application version/commit for real screenshots and avoid exposing
hostnames, serial numbers, repository paths, user names, credentials or other
sensitive information. See the [screenshot policy](assets/screenshots/README.html).

# Recovery ISO: operator build and verification procedure

This document describes how an operator would create and inspect a self-contained
Feclora recovery ISO. It is a procedure, not evidence that a real ISO has been
built or boot-tested. Repository development and CI must not run the assembly
command or produce recovery media.

## What the recovery ISO contains

The output is a new ISO based on an existing, bootable Feclora Live ISO. The
builder preserves the base ISO's El Torito boot configuration by asking
`xorriso` to replay it, and adds these files under
`/FECLORA/RECOVERY/`:

- Every artifact named by the selected whole-disk image manifest.
- The validated image manifest as `manifest.json`.
- A narrowly scoped `answer.json` containing the image ID, target WWN and/or
  serial, and explicit restore/start authorization.

The base ISO and source image artifacts are inputs and are not intentionally
modified. The result is a separate `<image_id>.recovery.iso` file in the
selected local or mounted filesystem repository. S3 object repositories are
not supported as the output destination.

The embedded answer contains no repository credentials, passwords, age
passphrases, private keys or arbitrary commands. If the selected image is
age-encrypted, the corresponding decryption identity must be provisioned
separately on the recovery Live environment. Never place that identity on the
ISO.

**Important implementation boundary:** the current code can assemble and
inspect this ISO, but Live boot-time discovery of the embedded image set and
dispatch to the safe restore engine are not yet integrated. Do not treat the
current output as a completed unattended recovery appliance until that
runtime path exists.

## Prerequisites

On the Feclora Live environment or other supported host that runs the builder:

1. A Feclora Live base ISO for the same supported release, obtained from a
   trusted source.
2. The base ISO's published checksum, verified before use.
3. A complete Feclora whole-disk image set and its manifest in a local or
   mounted writable filesystem repository. The image manifest and every
   artifact must pass size and SHA-256 validation.
4. A stable target identity: preferably the destination disk WWN, and
   optionally its serial number as an additional selector. Confirm these
   identifiers independently; do not guess them.
5. Enough free space in the output filesystem. The builder requires space for
   the base ISO plus the payload and a safety margin (at least 64 MiB or 1%
   of the base ISO, whichever is larger).
6. The `xorriso` executable. The Feclora Live runtime package set includes
   `xorriso`.

Keep the base ISO, image artifacts and output on filesystems with sufficient
space. Do not use a physical disk or block device as the output path.

## Cockpit procedure

When the recovery ISO workflow is available in the deployed Feclora Live
version:

1. Open Cockpit and select **Build a self-contained recovery ISO**.
2. Enter the absolute path to the trusted Feclora Live base `.iso` file. The
   path must be readable by the Feclora service.
3. Select the repository containing the image set. It must be a writable local
   or mounted filesystem repository; S3 is not an output option.
4. Select the intended whole-disk image. Check that its image ID and manifest
   identify the correct source image.
5. Enter the destination disk WWN and/or serial. At least one is mandatory.
   Prefer WWN where available and use both when the values are known.
6. Read the warning and type the exact confirmation `BUILD <image_id>`.
   This authorizes creation of the ISO file only; it does not write to a target
   disk at build time.
7. Submit the operation and wait for the durable worker to report completion.
   Record the resulting path, byte size and SHA-256 digest.

Do not boot the resulting media on a machine with valuable writable disks
until the embedded-answer runtime and target-identity enforcement have been
completed and tested. The current embedded answer requests an unattended
destructive restore when consumed by a compatible runtime.

## xorriso assembly sequence (manual reference)

The Feclora engine performs the following operations. The commands below show
the equivalent command shape for an operator reviewing or independently
reproducing the process. Replace every placeholder with a real path. Do not
paste the placeholders literally.

First inspect the base ISO's boot catalog:

```bash
xorriso -indev /path/to/feclora-live.iso -report_el_torito plain
```

The report must identify an El Torito boot catalog. If it does not, stop: do
not attempt to manufacture boot entries or guess BIOS/UEFI boot parameters.

Prepare a new temporary output path on the same filesystem as the intended
final ISO. It must not already exist. The assembly command uses the base ISO
as input and the new temporary file as output, maps the verified artifacts
and metadata into the recovery directory, then replays the base boot setup:

```bash
xorriso \
  -indev /path/to/feclora-live.iso \
  -outdev /path/to/repository/.recovery-build/recovery.tmp.iso \
  -mkdir /FECLORA \
  -mkdir /FECLORA/RECOVERY \
  -map /path/to/image/disk.raw /FECLORA/RECOVERY/disk.raw \
  -map /path/to/image/partition-table.bin /FECLORA/RECOVERY/partition-table.bin \
  -map /path/to/image/manifest.json /FECLORA/RECOVERY/manifest.json \
  -map /path/to/private-staging/answer.json /FECLORA/RECOVERY/answer.json \
  -boot_image any replay \
  -commit
```

The artifact mapping lines are illustrative: use one `-map` pair for every
artifact listed in the selected manifest, with the exact source filename and
destination filename. Do not omit auxiliary artifacts such as partition-table
metadata. The answer file should be canonical JSON in a private temporary
directory with restrictive permissions (0600); remove it after assembly.
Never include credentials or decryption identities.

The production Feclora engine creates its own private temporary directory,
validates the manifest and each artifact before invoking xorriso, replays the
base boot catalog, checks the assembled ISO, fsyncs it and publishes it
without overwriting an existing output. The illustrative command above is not
a replacement for those validations or the Cockpit authorization path.

## Inspect the assembled ISO

Before publishing or transferring the result, inspect its boot catalog and
directory tree:

```bash
xorriso -indev /path/to/recovery.tmp.iso -report_el_torito plain
xorriso -indev /path/to/recovery.tmp.iso \
  -find /FECLORA/RECOVERY -type f -exec lsdl
sha256sum /path/to/recovery.tmp.iso
```

Check all of the following:

- The output still reports an El Torito boot catalog.
- Every artifact from the manifest is present under
  `/FECLORA/RECOVERY/`.
- `manifest.json` and `answer.json` are present.
- The embedded manifest identifies the intended image ID and its artifact
  hashes match the files in the ISO.
- The recorded output SHA-256 and byte size are saved with the operation
  record.
- The base ISO checksum still matches the trusted original checksum.

A successful xorriso command and a directory listing are not sufficient proof
that the media boots on every firmware. They also do not prove that the
currently unfinished embedded-image restore runtime works.

## BIOS/UEFI acceptance (separate, optional operator activity)

When boot-time discovery and safe restore dispatch have been implemented,
validate the media in disposable virtual machines before any production use:

1. Use a disposable VM with BIOS firmware and a disposable destination disk.
2. Boot the recovery ISO and confirm that the Feclora Live environment starts.
3. Repeat with UEFI firmware, including Secure Boot only if the product
   explicitly supports the selected signing configuration.
4. Confirm that the embedded manifest and every artifact are discovered
   read-only and pass integrity verification.
5. Confirm that the unattended answer is accepted only when the selected
   destination's WWN/serial matches exactly and all capacity, sector-size and
   destructive-operation checks pass.
6. Confirm that a mismatched identity, missing selector, corrupt artifact,
   wrong decryption identity, insufficient target capacity or cancelled
   operation fails closed without writing to a disk.
7. On disposable media only, verify the restore result by read-back before
   allowing any configured final action.

Record VM firmware type, virtual hardware configuration, Feclora revision,
base ISO checksum, recovery ISO checksum and test outcome. Never use a
production disk for acceptance testing.

## What CI does and does not verify

Automated tests mock the xorriso process. They exercise manifest/artifact
validation, answer-file restrictions, command construction, boot-catalog
report handling, output checks and no-overwrite behavior. Static checks and
unit tests do not invoke xorriso to assemble a real ISO, do not boot the
result, and do not establish BIOS/UEFI compatibility. That is intentional:
the repository CI must not generate recovery media.

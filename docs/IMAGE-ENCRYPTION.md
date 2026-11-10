# Image encryption and signatures

Feclora delegates optional artifact encryption and detached signatures to the upstream `age` and `minisign` executables when an operator enables those integrations. It does not implement cryptographic primitives. Neither executable is a mandatory dependency for installing or using Feclora's ordinary local imaging workflows.

## Encryption model

- Compress first, then encrypt the stored artifact with `age`.
- Use an age recipients file containing one public recipient per line. Multiple
  recipients can decrypt the same artifact independently.
- Store the encrypted bytes as `<artifact filename>.age`; the manifest records
  `"encryption": "age"` and the SHA-256/size of the ciphertext.
- Existing manifests without an encryption field remain valid and mean
  `"encryption": "none"`.
- Restore must verify the ciphertext digest before invoking age, decrypt and
  authenticate to a private staging file, and only then decompress or write to
  a block device. Never write unauthenticated plaintext to a target.
- Private age identity files must be kept separately from the image repository
  and protected by the operator. Recipient files contain public keys.

Example key setup:

```sh
age-keygen -o feclora-identity.txt
age-keygen -y feclora-identity.txt > feclora-recipients.txt
chmod 600 feclora-identity.txt
```

## Manifest signatures

Sign the completed manifest with a detached minisign signature:

```sh
minisign -S -s feclora-minisign.key -m image.manifest.json
minisign -V -m image.manifest.json -p trusted-minisign.pub
```

The public key used for verification must be provisioned independently and
trusted by the operator. A public key shipped beside an image is not, by itself,
a trust anchor. The detached `.minisig` file signs the manifest, which binds
the artifact names, encryption modes, sizes and SHA-256 digests.

## Current implementation boundary

Capture UI exposes independent optional choices for age encryption and
minisign signing. Both are opt-in; selecting neither is a supported baseline path. When either option is selected, capture preflights the corresponding key file and executable before starting the disk or partition read, so a missing optional tool fails early rather than after a long capture. Restore detects age-encrypted artifacts and requires an
identity file; it verifies ciphertext SHA-256 before invoking age, then
authenticates/decrypts to a private staging file before decompression or disk
writes. When a detached signature is present, restore must verify it against an
independently provisioned trusted public key before any target-device write.
There is no unverified continuation for a signed image. If the signature is
missing, invalid, or cannot be checked because minisign or a trusted key is
unavailable, restoration stops before writing. A caller may require signatures
for workflows where unsigned images are not acceptable. `minisign` is one supported signature mechanism, not
a universal requirement. If signatures are not used, SHA-256 detects accidental
corruption but does not authenticate an image against malicious substitution;
for destructive fleet/unattended workflows, authenticate the manifest and
bind its digest to a separately trusted deployment authorization mechanism.

These flows have mocked unit coverage, but have not yet been exercised with
the real age/minisign binaries on Fedora Live. Their optional status must be
preserved in packaging, capability detection and documentation; missing
binaries should disable only the corresponding optional feature. Compression offers none, gzip,
xz, zstd and lz4. gzip/xz use Python's standard library; zstd/lz4 use the
Fedora system executables with bounded streaming. The selected level is
recorded in the manifest.

## Interactive capture choices

Each disk or partition capture asks independently whether to encrypt and/or
sign. Both are optional; choosing neither leaves a conventional unencrypted,
unsigned image. The UI asks for an age recipients file only when encryption is
selected, and for a minisign secret-key path only when signing is selected.
Private keys are not copied into the image repository.

Compression is selected per capture: none, gzip, xz, zstd or lz4. The UI asks
for a level when a codec is selected: gzip 1-9, xz 0-9, zstd 1-19 and lz4
1-12. Representative choices are offered in the menu. The selected level is
recorded in the artifact manifest. Compression is performed before age
encryption. zstd/lz4 are delegated to the installed system CLI tools; feclora
does not implement these codecs itself.

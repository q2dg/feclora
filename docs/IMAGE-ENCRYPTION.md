# Image encryption and signatures

feclora delegates encryption and signatures to the upstream `age` and
`minisign` executables. It does not implement cryptographic primitives.

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

The repository now has command adapters, an optional per-artifact encryption
field in manifest schema v1, and Fedora 43 package dependencies. Capture and
restore workflows are not yet wired to prompt for recipients/identities or
enforce signature policy. Until that integration is complete, do not treat an
image as encrypted or signed merely because the tools are installed. The
adapters have mocked tests; they are not a substitute for testing against the
real age/minisign binaries on Fedora Live.

## Interactive capture choices

Each disk or partition capture asks independently whether to encrypt and/or
sign. Both are optional; choosing neither leaves a conventional unencrypted,
unsigned image. The UI asks for an age recipients file only when encryption is
selected, and for a minisign secret-key path only when signing is selected.
Private keys are not copied into the image repository.

Compression is also selected per capture: none, gzip, or xz. When gzip or xz
is selected, the UI asks for a compression level. gzip accepts levels 1-9;
xz accepts levels 0-9. The selected level is recorded in the artifact
manifest. Compression is performed before age encryption. The current capture
writer intentionally exposes only gzip and xz until additional compressors
have safe streaming implementations and restore support.

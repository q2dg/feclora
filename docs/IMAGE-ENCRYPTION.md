# Image encryption and integrity

Feclora does not sign image manifests. Image integrity is checked with the SHA-256 digest and byte count recorded for every artifact in the manifest. There is no detached-signature sidecar and no signing-key setup step.

## Optional age encryption

Artifact encryption is optional and uses the upstream `age` tools. Feclora does not implement cryptographic primitives or key derivation.

- The capture workflow can encrypt each completed artifact to the configured age recipient set.
- The manifest records which artifacts use age encryption.
- Restore and verification require an age identity only when at least one selected artifact is encrypted.
- Private age identities must remain in protected local storage; they are never embedded in an image, manifest, job record or browser request.
- A missing age executable or recipient inventory blocks only an operation that explicitly selects age encryption. Ordinary unencrypted capture and restore remain available.

## SHA-256 integrity checks

For each artifact, the manifest records its stored byte count and SHA-256 digest. Feclora verifies these values during local image verification, SFTP import/publication, TLS image-set transfer, multicast staging and restore preflight. Compressed and age-encrypted artifacts are also decoded/authenticated as applicable before a destructive restore is allowed to proceed.

The manifest itself is not cryptographically signed. A digest stored in the same manifest as the artifact is an integrity check, not an independent authenticity proof. The trust boundary therefore comes from the authenticated transport or the operator-controlled local repository:

- SFTP uses pinned SSH host keys and encrypted systemd credential references.
- Unicast deployment uses the Server-authenticated TLS control session.
- Multicast distributes the manifest over that TLS control session; UDPcast carries the artifact bytes and does not provide datagram confidentiality or peer authentication.
- Local image repositories and unattended restore profiles rely on root-owned directories and protected file permissions.

An attacker able to replace both a manifest and its artifacts in a trusted repository or transport endpoint can replace the image coherently. SHA-256 alone does not prevent that. Protect repository write access and the transport trust anchors accordingly.

## Unattended restore profiles

Unattended profiles are authorized by local filesystem policy rather than detached signatures. The profile and its containing directory must be root-owned; the profile must have mode 0600 and the directory must not be writable by group or other users. Profiles remain single-use, expire, bind to stable target identity and require post-write verification. The replay ledger must be on persistent storage.

This policy assumes the local root account and boot environment are trusted. It is not a substitute for a cryptographic signature when profiles must be distributed across mutually untrusted systems.

## Operational acceptance

Unit tests cover digest mismatch, interrupted transfers, no-overwrite publication and age encryption/decryption paths. Operators must still perform the documented physical-device acceptance tests on their target Fedora Live environment.

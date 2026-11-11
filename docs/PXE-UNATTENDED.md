# Unattended PXE restore design and implementation status

## Implemented boot handoff

Interactive and unattended boot use the same Fedora Live kernel, initramfs and
squashfs payload. The normal iPXE menu exposes both paths. The unattended path
chains to `unattended.ipxe`, which is published only while an active Server
restore job is running.

The job-bound script contains only:
- the public Server IPv4 address;
- the actual TLS control port returned by the Server listener;
- the non-secret deployment job UUID;
- the unattended boot-mode selector.

It contains no certificate, private key, password, enrollment token or restore
authorization. The Live command-line parser validates the UUID and endpoint,
but these values are only a handoff request. They do not authorize a write.
The Server publishes the script atomically, refuses to overwrite another
active job's script, revokes the matching script when the job UI exits, and a
new PXE session removes a safe stale script left by an interrupted Server
process.

## Implemented stable target-binding groundwork

Server restore-job creation can optionally bind each selected Client MAC to a
physical target WWN, serial number, or both. The binding is part of the
validated job document sent over the TLS 1.3 mTLS control session. The Client
compares every supplied identifier with its own current block-device inventory
before it reports READY; a missing or mismatching identifier rejects the
selection. The Server UI collects these values per selected Client, and the
job schema rejects selectors for non-authorized Clients, incomplete Client
coverage, empty selectors, non-restore/partition targets, unknown fields and
control characters.

This is a preflight constraint, not unattended target discovery or a
signed per-Client profile. WWN/serial matching reduces accidental
mis-targeting but is not cryptographic hardware attestation. The operator still selects the local /dev target
and types the local confirmation in Cockpit. No profile expiry, nonce/replay
ledger, automatic Client startup or write authorization is provided by this
binding alone. Existing jobs without target_bindings retain the interactive
workflow.

## Required authenticated flow

1. The Client boots the shared Live image and parses the unattended handoff.
2. A pre-enrolled Client identity establishes TLS 1.3 mutual authentication to
   the advertised Server control endpoint. MAC address, IP address and job
   UUID are not authentication credentials.
3. The Server verifies that the certificate identity is enrolled, not revoked,
   and explicitly authorized for this job.
4. The Client obtains a signed, immutable per-Client restore profile over the
   authenticated control channel. The profile binds the job UUID, Client
   certificate identity, image-manifest digest, expiry, single-use nonce and
   a stable target selector (WWN and/or serial). It must not select a disk by
   transient `/dev/sdX` name.
5. The Client verifies the profile signature against pinned Server trust,
   checks expiry and replay state, verifies the manifest and artifact digests,
   resolves exactly one target by WWN/serial, and runs all local restore
   preflights. It sends READY only after all checks pass.
6. The Server requires every expected Client to be authenticated and READY.
   No storage write begins until the Server operator explicitly ARMs the job.
7. The Client rechecks target identity immediately before writing, restores,
   performs read-back verification, and reports a terminal per-Client result.
   The Server persists the job/replay outcome and reconciles every Client.

## Credential provisioning constraint

The Live session is intentionally ephemeral. A PXE boot script, TFTP payload,
HTTP response, kernel command line, DHCP option or unauthenticated network
request must never carry a Client private key or reusable bootstrap secret.

Therefore unattended PXE requires a secure way to make the already-enrolled
Client mTLS identity available inside the fresh Live session. That provisioning
mechanism is not implemented yet and must be selected before Client auto-start
is enabled. Acceptable designs must bind the credential to the intended Client
and protect it at rest and in use (for example, a hardware-backed/TPM-sealed
identity or an explicitly provisioned secure local medium). MAC-only
enrollment, public boot parameters and shared fleet-wide secrets are not
acceptable substitutes.

Until that mechanism exists, the unattended boot script is only a safe
job-bound handoff. It must not start a writer or fall back to interactive
credentials silently.

## Feasibility decision: TPM2-bound Client identity

A network-only Live PXE session cannot currently authenticate as an enrolled
Client: its root filesystem, /etc/feclora/deployment-client.json and TLS
private key are ephemeral and are intentionally discarded on reboot. Fetching
a private key from the Server over the public handoff would create a circular
trust problem; placing it in iPXE, DHCP, TFTP, HTTP or the kernel command line
would disclose a reusable fleet credential. A shared bootstrap password or
MAC-derived secret is not an acceptable workaround.

The viable hardware-backed route is a per-Client identity sealed on that
Client's TPM2, using systemd's encrypted-credential format with an explicitly
TPM2-bound key (not the existing generic --with-key=auto repository
credential path). The encrypted blob and public certificate/configuration may
then be staged in a per-Client PXE credential directory: the blob is portable
as ciphertext but only the enrolled TPM should be able to decrypt it. The
Live Client must retrieve the bundle, verify its signature and job/server
binding, ask the local TPM to decrypt the key into volatile root-only
storage, and establish TLS 1.3 mTLS. No plaintext key may be sent to or stored
by the Server. Missing TPM2, failed unseal, wrong device identity or invalid
bundle must stop before READY.

TPM sealing alone is not sufficient boot integrity. A compromised
network-delivered kernel/initramfs running as root on the enrolled machine
could request TPM unsealing and exfiltrate the key. The present PXE path loads
kernel and initramfs as separate HTTP assets; it does not yet establish a
measured, signed Live boot chain suitable for PCR-bound release. Before
enabling unattended identity unsealing, Feclora must boot a signed Unified
Kernel Image (UKI) through a Secure Boot-verifiable chain, define and test a
stable PCR policy (including recovery/firmware update procedures), and bind
the credential release policy to that measured boot. Do not treat Secure Boot
being enabled, by itself, as proof that the current HTTP initramfs is trusted.

Once that trust chain exists, the unattended Client can use the existing
mTLS HELLO/JOB protocol and the job's per-Client WWN/serial binding to resolve
exactly one local target. The target path and destructive confirmation remain
local; the Client synthesizes the confirmation only after the authenticated
job and unique hardware binding pass. The Server's existing explicit ARM
remains the final fleet-wide write gate. The authenticated journal must
record single-use session/profile consumption before READY, and the Client
must recheck target identity immediately before the first write. This keeps
the operator's approval at the Server while removing the need for an operator
at each Client.

This is a staged implementation decision, not a claim that unattended PXE is
now available. First validate TPM2-bound systemd credentials and the signed
UKI/PCR policy on the supported Fedora 45 hardware/VM matrix. Until then the
existing unattended menu remains a non-authorizing handoff and must not
auto-start a disk writer.
## Signed UKI build primitive

The repository now includes `build/build-pxe-uki.sh`, an opt-in build
primitive for a signed UKI assembled from a Fedora Live kernel and initramfs.
It uses systemd `ukify` with a protected configuration containing both
Secure Boot signing material and at least one systemd PCR-signature section.
It requires `systemd-measure` and verifies the resulting PE signature with
`sbverify` before atomically publishing a new output file. Existing output
files are never overwritten.

The script is deliberately separate from the default ISO/PXE build: it does
not guess the Live kernel command line, alter the current iPXE menu, enroll a
firmware trust key, or publish the UKI. Build a distinct UKI for each job when
the non-secret Server endpoint/job handoff parameters differ. Embed those
parameters in the signed `.cmdline` section; do not pass overrides as EFI load
options, because an embedded command line under Secure Boot is immutable and
is included in the UKI's measured content. The operator must provide:

- A root-protected ukify configuration with `[UKI]` Secure Boot key/certificate
  and one or more `[PCRSignature:name]` sections containing PCR private/public
  keys and explicit phase lists. See [the illustrative configuration](FECLORA-UKI-CONFIG.example); its PCR phase policy is not a production default.
- The exact kernel and initramfs from the same Fedora Live build.
- A one-line kernel command line file with only non-secret boot parameters.
- A pre-existing output directory and a firmware trust chain that accepts the
  configured signing certificate.

Example invocation:

```bash
FECLORA_UKI_CONFIG=/root/uki/feclora-uki.conf \
FECLORA_UKI_CMDLINE=/root/uki/feclora.cmdline \
FECLORA_UKI_KERNEL=/boot/vmlinuz-<version> \
FECLORA_UKI_INITRD=/boot/initramfs-<version>.img \
FECLORA_UKI_OUTPUT=/srv/feclora/boot/feclora-live.efi \
bash build/build-pxe-uki.sh
```

The config, command-line file and private keys must be regular files with
0600-or-stricter permissions. PCR phase selection, PCR bank choice, PCR
signature enrollment and recovery after firmware/kernel updates remain
operator-defined and are not certified by this builder. The script's
successful signature check proves only that the output verifies against the
provided certificate; it does not prove that firmware trusts it or that the
TPM will release a credential under the intended measured-boot policy.

The current PXE tree still boots its existing kernel/initramfs assets. The
signed UKI is not wired into production PXE selection until bootloader/firmware
compatibility, UKI signature trust, PCR measurements and recovery paths have
been tested on the Fedora 45 BIOS/UEFI matrix.

### TPM2 Client-key sealing primitives

Two opt-in helpers now implement the local credential cryptography step:

- `build/seal-pxe-client-key.sh` runs on the enrolled Client. It accepts an
  existing root-protected TLS private key and a PCR public key, then invokes
  `systemd-creds encrypt` with explicit `--with-key=tpm2`,
  `--tpm2-device=auto` and `--tpm2-public-key-pcrs=11`. It has no host-key,
  null-key or no-TPM fallback. Only the resulting ciphertext may be copied to
  the Server; the plaintext private key stays on the Client.
- `build/unseal-pxe-client-key.sh` requires UEFI Secure Boot to be enabled,
  a TPM2 resource-manager device, and the systemd-stub PCR signature/public-key
  files under `/run/systemd`. It decrypts through the local TPM and publishes
  plaintext only under `/run/feclora` on tmpfs, mode 0600, with no overwrite.
  This also prevents systemd-creds' null-key fallback. Failure to access
  Secure Boot, TPM2 or the PCR policy stops the operation.

These helpers are cryptographic building blocks, not a complete enrollment
or deployment workflow. They do not generate or rotate the Client keypair,
sign the Server's per-Client credential bundle, fetch it from PXE, update the
Client runtime configuration, start the Client service, bind a profile to the
TLS certificate, or implement nonce/replay consumption. In particular, the
unseal helper must not be enabled in the current separate HTTP kernel/initramfs
boot. It is only eligible for integration after the signed UKI and measured
boot have passed the hardware acceptance gates above.

## Multi-Client and transport constraints

- Each Client receives its own profile and target selector, even when all
  Clients restore the same immutable image.
- A single Client may be targeted by one job at a time. Duplicate or replayed
  profile consumption is rejected by Server-side persistent state.
- Unicast and multicast share the same authenticated control plane and
  per-Client READY/ARM gate. Multicast changes only artifact data transport.
- UDPcast datagrams are not authenticated or encrypted by UDPcast itself;
  network isolation and optional artifact encryption remain separate controls.
- Partial failure is reported per Client. A failed receiver must not cause
  another Client's successful result to be overwritten or misreported.
- No automatic resume or replay of disk I/O occurs after reboot. Operators
  inspect interrupted targets before creating a new job.

## Remaining release-critical work

- Select and implement secure per-Client credential provisioning into Live.
- Add automatic Client service startup for unattended boot.
- Add Server-to-Client signed profile delivery and certificate/job/profile
  binding.
- Extend the implemented optional job-level WWN/serial preflight binding into signed per-Client profile authoring and automatic unique target resolution.
- Integrate expiry, nonce/replay protection, manifest digest binding and
  Server-side single-use state.
- Add unattended local preflight, READY, ARM, progress, read-back verification
  and terminal result reconciliation.
- Validate BIOS and UEFI PXE, one Client and multiple Clients, unicast and
  multicast, missing credentials, revoked identities, expired/replayed
  profiles, ambiguous targets, target swaps and network interruption.

# Deployment artifact bundle

## Goal

Define how independently produced deployment artifacts can be validated and
assembled into a coordinated deployment bundle. The answer generator and the
artifact consumers are deliberately separate tools:

1. A bootable Feclora Live ISO.
2. A selected or newly captured Feclora-restorable disk image and its manifest/artifacts.
3. One shared unattended answer file describing the deployment for the complete Client group.

The output is a versioned bundle with integrity metadata. The ISO, image and already-generated shared answer are selected as separate inputs and validated together. The bundle coordinator must not generate or modify the answer file.

## Keep the artifact roles distinct

- The Live ISO contains the generic Feclora runtime. It must not contain repository credentials, age identities, passphrases, private keys or per-machine target data.
- The image is a Feclora image set with a validated manifest and all referenced artifacts. Current whole-disk capture can publish either RAW or QCOW2 directly as a normal manifest-backed disk image; both formats use the regular repository and restore workflows. Only legacy standalone QCOW2 plus `.p2v.json` bundles require the explicit `import_p2v` compatibility operation. That importer verifies the sidecar and QCOW2, rejects external backing dependencies, converts the virtual disk to raw sectors, preserves the recorded logical sector size, creates a native disk manifest and atomically publishes a new Feclora image set. It attaches the staged raw image read-only through a loop device, inspects and validates its GPT/MBR partition table with `sfdisk`, and stores that dump with the native manifest. Unpartitioned/superfloppy disks are rejected by this legacy import path. QCOW2/RAW sector capture does not repair guest boot dependencies or guarantee guest bootability.
- The answer is one schema-v1 `DeploymentJob` JSON document for every Client. It contains the managed repository/image references, operation and transport, authorized MAC addresses, stable `target_bindings`, and explicit destructive authorization. It contains no credentials, arbitrary commands or per-client answer copies.

## Target workflow

1. Build or select a Feclora Live ISO from pinned Fedora/Kickstart/application inputs. Record source revision, Fedora release, architecture, build-tool versions and ISO SHA-256.
2. Select an existing compatible Feclora image or capture one through the normal whole-disk capture workflow. Choose RAW (with optional compression/encryption) or QCOW2. Both formats produce an ordinary disk manifest and can be selected directly for deployment; QCOW2 restore validates the container and converts it to private RAW staging on the Client. QCOW2 conversion preserves disk sectors but does not repair guest boot dependencies or prove VM bootability.
3. Independently generate the single shared schema-v1 answer with `build/generate-shared-answer.py` (or prepare it in the Remote Jobs editor). Supply the image/repository IDs, one `MAC=WWN|SERIAL` binding per Client, boot method and transport settings. The generator validates the `DeploymentJob`, requires at least two Clients for multicast, writes mode 0600 and never overwrites an existing answer.
4. Select the intended consumer workflow: local deployment, client/server unicast, client/server multicast, or PXE boot. These are consumers of the same answer contract; PXE changes only the Live boot/answer-delivery path. For unattended multicast, all Clients consume the exact same JSON and select their own target binding locally by MAC.
5. When a bundle is required, pass the already-generated answer file, ISO and image to `build/create-deployment-bundle.py` or the Textual bundle operation. The coordinator revalidates schema, cross-references, sizes and SHA-256 values; it does not generate, rewrite or split the answer.
6. Stage the bundle in a private temporary directory and publish atomically only after all checks succeed. Never overwrite an existing bundle. Emit a manifest/checksum file identifying the ISO, image artifacts and one shared answer.

## Boot and transport behavior

The same Live ISO supports USB/ISO boot and optional PXE boot. PXE only supplies the Live boot path and, where configured, the shared answer locator. It is not a repository proxy. Clients access the configured repository directly through the existing repository manager.

For unattended multicast, every Client downloads and processes the exact same answer JSON. Each Client selects its own target binding locally by MAC, validates the destination, and joins the same authenticated DeploymentJob. The Server starts one multicast transmission only after all authorized Clients are READY. Unicast remains a supported transport. Do not generate per-client answer files or add PXE-specific CA, TLS or credential infrastructure.

The bundle generator must make answer delivery explicit: either include the shared answer as a removable-media file with a documented import/discovery path, or publish it through the existing Caddy/DHCP answer mechanism. Do not claim that simply placing a JSON file beside an ISO makes firmware or Live discover it automatically.

## Existing implementation versus remaining work

Already present in source:
- Fedora Live ISO build inputs and `build/build-iso.sh`.
- A build-host coordinator, `build/create-deployment-bundle.py`, that runs the Live ISO build, optionally captures an offline source disk or selects an existing image, validates a supplied shared automatic answer, and invokes the atomic bundle publisher. It is intentionally a consumer: it does not invoke the answer generator or alter the answer.
- `build/generate-shared-answer.py` generates and validates one canonical schema-v1 unattended job from explicit Client MAC-to-WWN/serial bindings and transport/boot settings. It is independent of the ISO build and can be used for USB/ISO or PXE boot.
- Feclora disk/partition image capture, manifest validation and repository publication.
- P2V QCOW2 conversion, sidecar publication, S3-to-filesystem export and explicit QCOW2-to-native-disk import. Import validates the QCOW2 and sidecar, rejects backing/data-file dependencies, converts to raw sectors, records source logical sector geometry, writes a standard Feclora disk manifest and atomically publishes without overwriting. It records the inspected GPT/MBR table and does not repair guest drivers, initramfs, bootloader or UEFI/BIOS configuration.
- Shared schema-v1 unattended answer and ISO/USB/PXE Client runtime, including one-job multicast coordination.
- A separate recovery-ISO builder and Live boot service that embed an existing image and a target-bound, single-machine recovery answer under `/FECLORA/RECOVERY`, discover the mounted payload at boot and dispatch the guarded restore engine after revalidating target identity. This recovery answer is not the shared schema-v1 `DeploymentJob` used for unattended fleet restore and must not be substituted for it. The coordinated bundle workflow must generate the one shared answer unchanged for every Client, with per-MAC target bindings inside that same document.

Implemented bundle engine and durable Textual operation:
- `src/feclora/storage/deployment_bundle.py` assembles an already-built generic Live ISO, an existing Feclora whole-disk image set and one schema-v1 automatic `DeploymentJob` answer. It validates the El Torito boot catalog, manifest, every artifact size/SHA-256, image/job identity, repository reference, destructive confirmation, multicast receiver count and complete MAC-to-target bindings.
- The builder canonicalizes the shared answer once, copies it byte-identically for every Client, emits a versioned `bundle-manifest.json` with file digests and optional source revision, stages privately, and publishes the completed directory with atomic no-replace rename. Existing output is never overwritten.
- A Textual imaging operation now accepts the base ISO path, selected mounted filesystem repository, disk image, bundle directory name and the exact shared schema-v1 DeploymentJob JSON. It persists the work through the existing durable local-operation worker. The shared answer can be generated in the existing Remote Jobs editor and copied into this operation with the “Use generated shared answer” control, or pasted manually; the repository/image/job references are checked again by the worker.
- Automated unit tests cover bundle assembly, cross-reference failures, corrupt artifacts, missing bindings, existing outputs and worker/API validation; execution/CI status must be checked separately.

Intentional tool boundary:
- The shared-answer generator remains an independent tool. The bundle coordinator and Textual bundle operation consume a previously generated or manually prepared answer. Do not merge these tools into a single wizard or command; keeping generation separate allows the same answer to be consumed by local deployment, unicast, multicast and PXE workflows.
- A supported answer-file import/discovery mechanism for a bundle carried on USB/removable media, or a fully orchestrated publication through the existing answer endpoint.
- End-to-end integration/fault-injection coverage for interrupted staging, concurrent publication, stale repository/image references and actual multicast deployment.
- The imported native image is now eligible for this builder after its manifest and artifacts pass normal validation. VM boot repair and hypervisor acceptance remain separate.

## Acceptance criteria

- The answer generator independently creates one canonical shared answer. The build-host coordinator consumes that answer alongside the Fedora installer ISO and selected/captured Feclora disk image, then reports the published bundle and manifest digests.
- No partial bundle is visible after any failure; an existing bundle is never silently overwritten.
- The ISO is generic and contains no repository secrets or deployment-specific destructive target data.
- Exactly one answer file is generated and all Clients receive byte-identical JSON.
- Every authorized Client has exactly one stable WWN/serial target binding; no device path is embedded in the answer.
- Image type and manifest are compatible with the selected restore engine. P2V QCOW2 is rejected; use `import_p2v` to create a new Feclora disk image set first.
- The answer can be delivered through the existing trusted mechanism without new PXE authentication infrastructure.
- Unit/fault-injection tests cover all validation and publication failure paths. ISO creation, firmware boot, repository-provider behavior and real multi-host multicast remain separate maintainer-run acceptance tests.

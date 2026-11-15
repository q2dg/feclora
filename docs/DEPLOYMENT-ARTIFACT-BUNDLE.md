# Deployment artifact bundle

## Goal

Provide one repeatable workflow that produces a coordinated deployment set:

1. A bootable Feclora Live ISO.
2. A selected or newly captured Feclora-restorable disk image and its manifest/artifacts.
3. One shared unattended answer file describing the deployment for the complete Client group.

The output is a versioned bundle with integrity metadata. The ISO, image and answer file must be generated or selected as one operation and validated together; producing three unrelated files is not sufficient.

## Keep the artifact roles distinct

- The Live ISO contains the generic Feclora runtime. It must not contain repository credentials, age identities, passphrases, private keys or per-machine target data.
- The image is a Feclora image set with a validated manifest and all referenced artifacts. A P2V QCOW2 plus `.p2v.json` is a separate artifact type until the explicit `import_p2v` operation verifies the sidecar and QCOW2, rejects external backing dependencies, converts the virtual disk to raw sectors, preserves the recorded logical sector size, creates a native disk manifest and atomically publishes a new Feclora image set. The imported image is selectable by the existing disk restore engine; guest bootability is still not guaranteed.
- The answer is one schema-v1 `DeploymentJob` JSON document for every Client. It contains the managed repository/image references, operation and transport, authorized MAC addresses, stable `target_bindings`, and explicit destructive authorization. It contains no credentials, arbitrary commands or per-client answer copies.

## Target workflow

1. Build or select a Feclora Live ISO from pinned Fedora/Kickstart/application inputs. Record source revision, Fedora release, architecture, build-tool versions and ISO SHA-256.
2. Select an existing compatible Feclora image or capture one through the existing capture workflow. For P2V, first produce and verify the physical-source QCOW2 and sidecar, then run `import_p2v` into a new Feclora disk image ID before selecting it for deployment. The import preserves disk bytes and sector geometry but records the partition-table type as unknown and does not repair guest boot dependencies.
3. Construct the single shared schema-v1 answer from the selected image manifest and deployment settings. Validate that every authorized MAC has exactly one stable target binding, that the image and repository exist, and that multicast has the required receiver set and configuration.
4. Validate the ISO, image manifest and all artifacts, answer schema, cross-references, sizes and SHA-256 values. Reject mismatched image IDs, missing artifacts, unsupported image types, incomplete target bindings and unsafe output paths.
5. Stage the complete output in a private temporary directory. Publish atomically only after all checks succeed. Never overwrite an existing bundle without an explicit, separate replacement workflow.
6. Emit a bundle manifest/checksum file and a human-readable summary identifying which file is the ISO, which files comprise the image set, and which single JSON is the shared answer.

## Boot and transport behavior

The same Live ISO supports USB/ISO boot and optional PXE boot. PXE only supplies the Live boot path and, where configured, the shared answer locator. It is not a repository proxy. Clients access the configured repository directly through the existing repository manager.

For unattended multicast, every Client downloads and processes the exact same answer JSON. Each Client selects its own target binding locally by MAC, validates the destination, and joins the same authenticated DeploymentJob. The Server starts one multicast transmission only after all authorized Clients are READY. Unicast remains a supported transport. Do not generate per-client answer files or add PXE-specific CA, TLS or credential infrastructure.

The bundle generator must make answer delivery explicit: either include the shared answer as a removable-media file with a documented import/discovery path, or publish it through the existing Caddy/DHCP answer mechanism. Do not claim that simply placing a JSON file beside an ISO makes firmware or Live discover it automatically.

## Existing implementation versus remaining work

Already present in source:
- Fedora Live ISO build inputs and `build/build-iso.sh`.
- Feclora disk/partition image capture, manifest validation and repository publication.
- P2V QCOW2 conversion, sidecar publication, S3-to-filesystem export and explicit QCOW2-to-native-disk import. Import validates the QCOW2 and sidecar, rejects backing/data-file dependencies, converts to raw sectors, records source logical sector geometry, writes a standard Feclora disk manifest and atomically publishes without overwriting. It records partition-table type as unknown and does not repair guest drivers, initramfs, bootloader or UEFI/BIOS configuration.
- Shared schema-v1 unattended answer and ISO/USB/PXE Client runtime, including one-job multicast coordination.
- A separate recovery-ISO builder that embeds an existing image and a target-bound, single-machine recovery answer under `/FECLORA/RECOVERY`; boot-time discovery and restore dispatch for that recovery format remain unfinished. This legacy recovery answer is not the shared schema-v1 `DeploymentJob` used for unattended fleet restore and must not be substituted for it. The coordinated bundle workflow must generate the one shared answer unchanged for every Client, with per-MAC target bindings inside that same document.

Implemented bundle engine and durable Cockpit operation:
- `src/feclora/storage/deployment_bundle.py` assembles an already-built generic Live ISO, an existing Feclora whole-disk image set and one schema-v1 automatic `DeploymentJob` answer. It validates the El Torito boot catalog, manifest, every artifact size/SHA-256, image/job identity, repository reference, destructive confirmation, multicast receiver count and complete MAC-to-target bindings.
- The builder canonicalizes the shared answer once, copies it byte-identically for every Client, emits a versioned `bundle-manifest.json` with file digests and optional source revision, stages privately, and publishes the completed directory with atomic no-replace rename. Existing output is never overwritten.
- A Cockpit imaging operation now accepts the base ISO path, selected mounted filesystem repository, disk image, bundle directory name and the exact shared schema-v1 DeploymentJob JSON. It persists the work through the existing durable local-operation worker. The shared answer can be generated in the existing Remote Jobs editor and copied into this operation with the “Use generated shared answer” control, or pasted manually; the repository/image/job references are checked again by the worker.
- Automated unit tests cover bundle assembly, cross-reference failures, corrupt artifacts, missing bindings, existing outputs and worker/API validation; execution/CI status must be checked separately.

Still not implemented:
- Full guided source preparation: the current Cockpit operation selects an existing ISO and native disk image, while image capture/import and shared-answer generation remain separate steps. It does not invoke `build/build-iso.sh` or capture a physical source as part of the same wizard.
- A supported answer-file import/discovery mechanism for a bundle carried on USB/removable media, or a fully orchestrated publication through the existing answer endpoint.
- End-to-end integration/fault-injection coverage for interrupted staging, concurrent publication, stale repository/image references and actual multicast deployment.
- The imported native image is now eligible for this builder after its manifest and artifacts pass normal validation. VM boot repair and hypervisor acceptance remain separate.

## Acceptance criteria

- One operator action creates a complete bundle from compatible inputs and reports each artifact path and digest.
- No partial bundle is visible after any failure; an existing bundle is never silently overwritten.
- The ISO is generic and contains no repository secrets or deployment-specific destructive target data.
- Exactly one answer file is generated and all Clients receive byte-identical JSON.
- Every authorized Client has exactly one stable WWN/serial target binding; no device path is embedded in the answer.
- Image type and manifest are compatible with the selected restore engine. P2V QCOW2 is rejected; use `import_p2v` to create a new Feclora disk image set first.
- The answer can be delivered through the existing trusted mechanism without new PXE authentication infrastructure.
- Unit/fault-injection tests cover all validation and publication failure paths. ISO creation, firmware boot, repository-provider behavior and real multi-host multicast remain separate maintainer-run acceptance tests.

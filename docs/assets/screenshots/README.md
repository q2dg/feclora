# Runtime screenshots and illustrative UI mockups

Documentation may use either:

1. screenshots captured from a real, version-matched Feclora build; or
2. clearly labeled illustrative mockups when a real runtime capture is not
   available.

Never present a mockup as a real screenshot, and never imply that a depicted
control or workflow is implemented merely because it appears in a mockup.
Every mockup must carry a visible **ILLUSTRATIVE MOCKUP — NOT A LIVE SCREEN**
label, preferably inside the image itself, and its surrounding caption must
identify the feature status (implemented, partial or planned).

## Published illustrative mockups

The current operator guides use task-specific conceptual screens under
`docs/assets/mockups/`. They are conceptual illustrations, not screenshots of the Textual terminal UI:

| File | Subject | Purpose |
|---|---|---|
| `capture-wizard.svg` | Source disk selection | Explain the capture wizard and read-only source selection |
| `restore-wizard.svg` | Destination review | Emphasize image/target review and destructive confirmation |
| `network-deployment.svg` | Server and Clients | Explain per-Client readiness and the explicit ARM barrier |
| `partition-workflow.svg` | Partition capture/restore | Show single-partition scope and existing-target constraint |
| `local-clone.svg` | Local disk clone | Contrast source and destructive destination |
| `repository-setup.svg` | Repository configuration | Compare mounted filesystem and S3 providers |
| `pxe-workflow.svg` | PXE boot modes | Separate interactive Live from unattended answer flow |
| `multicast-workflow.svg` | Multicast restore | Explain READY barrier and shared stream |
| `recovery-workflow.svg` | Recovery media | Show artifact inputs and guarded Live boot-time restore dispatch |
| `restore-profile.svg` | Single-use restore profile | Explain persistent profile storage, WWN/serial binding and one-time execution |
| `proportional-restore.svg` | Proportional whole-disk restore | Explain private staging, eligible filesystem shrink and exact-size target write |

These SVGs are design illustrations, not captures of the current Textual UI.
Sample disk names, capacities, addresses and statuses are fictional. The
published guides use them only to explain the operator flow.

## Real screenshot procedure

1. Build and boot the commit being documented in a disposable VM.
2. Record the Feclora commit SHA, Fedora release, terminal dimensions and
   relevant test fixture.
3. Use disposable disks and synthetic data only. Never expose real serial
   numbers, WWNs, hostnames, IP addresses, usernames, credentials, key
   material or customer data.
4. Capture the complete relevant wizard context. Do not crop warnings,
   confirmation phrases or status labels.
5. Review every image for secrets and personal data. Replace or remove images
   when the corresponding UI changes.

## Mockup procedure

- Base the workflow and labels on the current Textual implementation.
- Do not invent a completed workflow or imply backend behavior not present in
  the code.
- Keep destructive confirmation, source/target identity and safety warnings
  visible where relevant.
- Use synthetic device names, addresses and image identifiers.
- Include the visible mockup disclaimer and a text caption describing what is
  illustrative versus implemented.

No image is evidence of runtime acceptance. BIOS/UEFI, PXE, destructive
storage and physical-network acceptance must be recorded separately.

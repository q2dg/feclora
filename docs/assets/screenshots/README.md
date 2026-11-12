# Cockpit screenshots and UI mockups

Documentation may use either:

1. screenshots captured from a real, version-matched Feclora build; or
2. clearly labeled illustrative mockups when a real runtime capture is not
   available.

Never present a mockup as a real screenshot, and never imply that a depicted
control or workflow is implemented merely because it appears in a mockup.
Every mockup must carry a visible **ILLUSTRATIVE MOCKUP — NOT A LIVE SCREEN**
label, preferably inside the image itself, and its surrounding caption must
identify the feature status (implemented, partial or planned).

## Real screenshot procedure

1. Build and boot the commit being documented in a disposable VM.
2. Record the Feclora commit SHA, Fedora release, browser resolution and
   relevant test fixture.
3. Use disposable disks and synthetic data only. Never expose real serial
   numbers, WWNs, hostnames, IP addresses, usernames, credentials, key
   material or customer data.
4. Capture the complete relevant wizard context. Do not crop warnings,
   confirmation phrases or status labels.
5. Review every image for secrets and personal data. Replace or remove images
   when the corresponding UI changes.

## Mockup procedure

- Base the layout and labels on the current React/PatternFly source.
- Do not invent a completed workflow or imply backend behavior not present in
  the code.
- Keep destructive confirmation, source/target identity and safety warnings
  visible where relevant.
- Use synthetic device names, addresses and image identifiers.
- Include the visible mockup disclaimer and a text caption describing what is
  illustrative versus implemented.

## Suggested visual set

| File | Subject | Preferred representation |
|---|---|---|
| `01-operations-overview` | Operations wizard and available local actions | Mockup or real screenshot |
| `02-storage-source-selection` | Disk, partition and supported LV source selection | Mockup or real screenshot |
| `03-image-capture-options` | Compression and optional age/not used settings | Mockup or real screenshot |
| `04-operation-progress` | Progress and terminal status | Mockup or real screenshot |
| `05-image-inventory` | Manifest, integrity and protection metadata | Mockup or real screenshot |
| `06-restore-target-review` | Image, destination and destructive confirmation | Mockup or real screenshot |
| `07-server-client-jobs` | Enrolled Clients, job and transport | Mockup or real screenshot |
| `08-pxe-modes` | Interactive Live boot versus job-handoff menu | Clearly labeled mockup until VM-tested |
| `09-unattended-pxe-boundary` | Handoff metadata versus authenticated job authorization | Architecture diagram, not a UI screenshot |

No image is evidence of runtime acceptance. BIOS/UEFI, PXE, destructive
storage and physical-network acceptance must be recorded separately.

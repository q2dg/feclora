# Cockpit screenshots

This directory contains only screenshots captured from a real Feclora build.
Do not add mockups, reconstructed UI, browser wireframes or screenshots from
a different frontend revision.

## Capture procedure

1. Build the ISO from the commit being documented and boot it in a disposable
   VM with a blank virtual disk. Record the Feclora commit SHA and Fedora
   release used for the capture.
2. Open Cockpit on the management interface and sign in to the Live account.
3. Use a disposable source disk with non-sensitive test data. Never expose
   real serial numbers, WWNs, hostnames, IP addresses, usernames, credentials,
   key material or customer data.
4. Capture the screens below at their natural browser resolution. Keep the
   full wizard context visible; crop only browser chrome, not labels, warnings
   or confirmation text.
5. Review every image for secrets and personal data before committing it.
   Keep the screenshots synchronized with the UI revision; remove or replace
   them when the corresponding flow changes.

## Planned screenshot set

| File | Screen / purpose |
|---|---|
| `01-operations-overview.png` | Operations wizard and available image actions |
| `02-capture-device-selection.png` | Whole-disk or partition source selection |
| `03-capture-compression-security.png` | Compression and independent age/minisign options |
| `04-capture-progress.png` | Live capture progress |
| `05-image-inventory.png` | Newly created image and its protection metadata |
| `06-restore-image-selection.png` | Selecting an image to restore |
| `07-restore-verification.png` | Signature / encryption verification status |
| `08-restore-target-confirmation.png` | Destination summary and exact destructive confirmation |
| `09-restore-progress.png` | Restore progress and verification state |

Screenshots are intentionally absent until the above procedure can be run
against a real, version-matched Fedora Live build. The table is a capture plan,
not a claim that those screens have already been validated.

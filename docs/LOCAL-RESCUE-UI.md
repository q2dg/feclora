# Local rescue operations

Local rescue operations are performed from Feclora's Cockpit application.
The Operations wizard supports:
- whole-disk capture;
- partition capture (Partclone where supported, raw fallback otherwise);
- whole-disk restore;
- partition restore;
- whole-disk cloning;
- partition-to-partition cloning.

The operator selects devices from the current `lsblk` inventory. Restore and
clone operations require typing the exact destination confirmation phrase.
The Python storage engines revalidate block-device identity, source safety,
geometry and image integrity before writing. Images are stored in the
root-owned `/var/lib/feclora/images` repository.

Progress events are streamed from the privileged backend to Cockpit. A
browser disconnect does not make an in-progress operation safe to interrupt;
do not close the browser or power off the machine while a write is active.
Use disposable test disks until you have completed your own ISO and hardware
acceptance tests.

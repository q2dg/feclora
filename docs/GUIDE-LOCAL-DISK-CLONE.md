---
layout: default
title: Local disk-to-disk cloning
---

# Local disk-to-disk cloning

**Status: available in Cockpit**

This procedure copies one complete block device directly to another on the
same Feclora machine. The destination is overwritten. It does not create an
image file and does not resize partitions or filesystems.

## Before you start

- Boot Feclora and open its Cockpit application.
- Identify the source and destination by model, capacity and, where available,
  serial number. Do not rely on `/dev/sdX` names alone.
- The source must be safe to read. Do not use a mounted/running system disk
  as a source if Feclora's safety checks reject it.
- The destination must be a different, writable block device and large enough
  for the source. Back up anything on it: cloning destroys its existing data.
- Disconnect unrelated removable disks where practical to reduce selection
  mistakes.

## Procedure

1. Open **Imaging operations** in the Feclora Cockpit application.
2. In **Operation**, select **Clone disk to disk**.
3. Under **Source disk**, select the disk to copy. Check its displayed path,
   capacity and model.
4. Under **Destination disk**, select the disk to overwrite. Check its path,
   capacity and model again. The source disk is excluded from the destination
   list.
5. Read the destructive-operation warning. It displays the exact phrase
   required for this destination: `ERASE /dev/DEVICE`.
6. Type that phrase exactly in **Typed confirmation**. Do not copy a phrase
   from an earlier operation; changing the target changes the required text.
7. Select **Start operation**. Keep the machine powered and do not disconnect
   either disk while the operation is running.
8. Follow the streamed progress in the wizard. On success, inspect the
   operation result and the **Operation log** tab.

## Verify the result

A successful return means the local clone engine completed its copy operation.
Before putting the destination into service:

- Shut down or disconnect the source if both disks contain identical filesystem
  UUIDs and labels; simultaneous attachment can confuse some operating systems.
- Boot or inspect the destination independently.
- Check the partition table and filesystems with appropriate read-only tools.
- If the destination is larger, expect extra capacity to remain unused; this
  workflow does not perform filesystem-aware growth.
- Keep the source unchanged until the destination has been independently
  checked and any required application-level validation has passed.

## Failure and recovery

A failed or interrupted clone can leave the destination partially overwritten.
There is no rollback. Treat the destination as untrusted; do not boot it or use
it as a verified copy. Inspect the persistent operation history, correct the
underlying issue, and repeat the clone only after rechecking both devices.

## Scope and limitations

This guide covers the local whole-disk clone workflow exposed in Cockpit.
Partition-to-partition cloning is a separate operation. Remote disk cloning,
remote repository mounting, fleet restore, and unattended PXE restore are
tracked separately and must not be inferred from this local workflow.

# Clonezilla Live functional parity

## Product goal

feclora is a Fedora-based Live rescue ISO intended to provide the practical
features users expect from Clonezilla Live. Clonezilla is the functional
benchmark only: feclora must not depend on Clonezilla, DRBL, or any `ocs-*`
program or script.

## Feature-to-tool map

| User-visible capability | Generic implementation primitives | Status |
|---|---|---|
| Discover disks, partitions and filesystems | `lsblk`, `blkid`, `findmnt`, udev | Inventory exists; further safety checks pending |
| Save/restore whole-disk images | `partclone.*`, `dd`, `sfdisk`, `sgdisk` | Not implemented |
| Save/restore individual partitions | `partclone.*`, `dd` | Not implemented |
| Direct disk-to-disk cloning | Partition-table tools + Partclone per partition; raw copy fallback | Not implemented |
| Filesystem-aware used-block imaging | Partclone filesystem-specific programs | Not implemented |
| Raw imaging for unsupported filesystems | `dd` | Not implemented |
| Compression | `gzip`, `pigz`, `zstd`, `xz` | Discovery only |
| Image integrity checks | `sha256sum` or equivalent | Discovery only |
| GPT/MBR partition-table handling | `sfdisk`, `sgdisk`, `parted` | Discovery only |
| LVM and encrypted volumes | `lvm2`, `cryptsetup` | Packages/discovery; workflows not implemented |
| Remote image save/restore | SSH and standard stream/network tools | Not implemented |
| Multicast deployment | Standard multicast transport tooling, to be selected and tested | Not implemented |
| Bootloader/boot-area preservation | `dd`, partition-table tools, bootloader utilities | Not implemented |
| Interactive rescue UI | `dialog` initially | Read-only device browser exists |
| Logs and operation summaries | Standard logging and metadata files | Not implemented |

Tool availability is not feature completion. Each row requires integration and
end-to-end testing in the generated ISO before it can be marked implemented.

## Implementation rules

1. Prefer generic tools already packaged for Fedora.
2. Do not invoke or port `ocs-sr`, `ocs-onthefly`, `ocs-live`, any other
   `ocs-*` script, or DRBL.
3. Keep custom code to command orchestration, UI, validation, progress,
   logging, metadata and recovery behavior.
4. Use Partclone for supported filesystems and raw copying when necessary;
   do not invent a new filesystem imaging engine.
5. Preserve safety: identify source and target independently, reject busy or
   mounted devices, protect the live system and revalidate immediately before
   any future write.
6. Add network and multicast workflows after local save, restore and direct
   clone have been validated.
7. Treat parity as user-visible behavior, not as a requirement to reproduce
   Clonezilla's internal image container or command interface.

## Acceptance

A capability is complete only when it can be selected in the feclora UI,
executes the intended generic tools with safe arguments, reports progress and
errors, produces/verifies the expected result, and passes repeatable tests in
BIOS and UEFI virtual machines. Hardware validation follows before release.

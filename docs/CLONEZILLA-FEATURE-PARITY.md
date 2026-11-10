# Feclora functional scope and Clonezilla reference matrix

Clonezilla is a functional reference, not a dependency. Feclora is implemented
independently on Fedora and uses a shared Python storage/deployment engine
with Cockpit as its primary operator interface. This matrix distinguishes
engine implementation from availability in the supported web UI and from
hardware verification.

## Local imaging workflows

| Workflow | Python engine | Cockpit UI | Automated verification | Laboratory verification |
|---|---|---|---|---|
| Inventory disks and partitions | Implemented | Implemented | Unit tests | Operator |
| Save whole-disk image | Implemented | Implemented | Unit tests | Operator |
| Save partition image | Implemented | Implemented | Unit tests | Operator |
| Restore whole-disk image | Implemented | Implemented | Unit tests | Operator |
| Restore partition image | Implemented | Implemented | Unit tests | Operator |
| Clone disk to disk | Implemented | Implemented | Unit tests | Operator |
| Clone partition to partition | Implemented | Implemented | Unit tests | Operator |
| Extract a partition from a disk image | Implemented in storage layer | Not exposed yet | Unit tests | Operator |
| Compression (none/gzip/zstd/lz4 and engine codecs) | Implemented | Basic choices exposed | Unit tests and CI | Operator |
| Optional age encryption and minisign signatures | Implemented as optional integrations | Local key setup/capture controls when configured | Unit tests | Operator |
| Image manifest and SHA-256 integrity | Implemented | Inventory and guarded restore | Unit tests | Operator |
| Larger-destination layout growth | Partial / conservative GPT handling | Not exposed | Unit tests | Operator |
| LVM/LUKS/Stratis/Btrfs-aware backup and restore | Inventory and selected safety checks only | Inventory only | Unit tests | Operator |

All destructive Cockpit operations pass through the root-owned allowlisted
helper and the same Python storage engines. The browser supplies no shell
commands. The backend revalidates device paths, source safety, target geometry
and exact typed confirmation before writing.

## Network and remote workflows

| Workflow | Engine | Cockpit UI | Status |
|---|---|---|---|
| PXE/iPXE BIOS and UEFI boot asset staging | Implemented | Not yet complete | Needs VM/lab validation |
| PXE service lifecycle (dnsmasq/TFTP/Caddy/firewalld) | Implemented | Not yet complete | Needs VM/lab validation |
| Server deployment configuration and managed CA bootstrap | Implemented | Not yet complete | Requires web setup workflow |
| Client CSR creation/import and certificate renewal | Implemented | Not yet complete | Requires web enrollment workflow |
| Authenticated one-client unicast save/restore | Implemented | Not yet complete | Requires web job workflow |
| Authenticated multicast restore to multiple clients | Implemented for disk and partition images | Not yet complete | Requires web job orchestration and per-client progress |
| Direct remote disk-to-disk clone | Implemented in engine/protocol | Not yet complete | Requires web source/receiver workflow |
| Client identity allowlist and local target approval | Implemented | Not yet complete | Requires web administration workflow |
| Job journals and recovery inspection | Implemented | Read-only summary | Operator reconciliation remains explicit |
| Live per-client progress and results | Partial | Not implemented | Outstanding |
| Switch IGMP snooping/querier verification | Operator network task | Guidance only | Cannot be proven by endpoint software |

## User-interface contract

Cockpit is the supported primary UI. It must expose the complete local
Clonezilla-style question/confirmation flow for capture, restore and cloning.
Cockpit's Terminal page is available for system administration and diagnostics;
it is not an alternate storage engine or a bypass around the guarded API.

The former `dialog` local-rescue UI is not included in the Live package.
Server/Client setup, PXE deployment jobs, enrollment, remote clone and
per-client multicast monitoring must be completed in Cockpit before the web
interface can be considered feature-complete.

## Explicit exclusions

The current project scope does not include multicast capture, concurrent
unicast deployment to many clients, Wake-on-LAN, automatic reboot/poweroff
after deployment, or automatic destructive resume after interruption.
These must not be inferred from the presence of related lower-level modules.

## Verification policy

A source implementation is not equivalent to a verified feature. Automated
unit tests and frontend compilation are expected in CI. Building the ISO,
booting BIOS/UEFI/PXE guests, and performing real restoration/deployment
acceptance on disposable laboratory machines are operator-owned tasks and are
not claimed by this document.


The age/minisign row describes optional integrations, not mandatory Feclora
installation requirements. Current unattended and some deployment workflows
still have minisign-specific requirements; see the completion plan and tooling
strategy for the work needed to make those paths verifier-configurable.

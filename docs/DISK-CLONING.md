# Disk-to-disk cloning

## Local, one-machine operation

Local rescue provides direct whole-disk cloning when both block devices are
connected to the same running feclora system. It invokes GNU dd directly from
the source disk to the destination disk; it does not create an intermediate
image file.

Before starting, feclora:
- requires an exact destructive confirmation naming the destination;
- rejects identical source and target paths;
- verifies both are whole disks, writable, and have supported logical sector
  sizes;
- requires the target capacity to be at least the source capacity and the
  logical sector sizes to match;
- rejects mounted, active-swap, busy, device-mapper-held, or live-system
  backing devices;
- repeats safety and device identity checks immediately before starting dd.

The command is bounded to the exact source byte size. If the destination is
larger, its trailing capacity is left untouched. The operation copies the
partition table, boot areas, gaps, and all sectors as raw data. It does not
resize partitions or filesystems to fill a larger destination.

The current implementation reads dd's progress reporting on stderr and
renders a live dialog gauge. Pressing Esc closes the gauge and terminates dd;
the destination may then contain a partial clone and must be treated as
unusable. A successful dd exit is not a substitute for read-back verification,
which remains pending.

## Remote, two-machine operation

The product requirement also includes direct cloning where the source disk is
attached to one machine and the destination disk to another. This is a
separate network workflow and is not implemented yet.

Planned roles:
- Source host: explicitly selects and safety-checks the source disk, then
  offers one authorized clone session.
- Receiver host: explicitly selects and safety-checks its target disk, checks
  capacity and logical sector size, and presents the destructive confirmation
  locally before accepting data.
- Control plane: authenticates both hosts, binds the source, receiver, job ID,
  disk geometry and operation, and requires explicit arming.
- Data plane: streams bounded raw bytes over an authenticated encrypted
  transport. The receiver checks framing, byte count and end-to-end digest
  before reporting success.

The network protocol must not trust MAC allowlisting as authentication. It
must use cryptographic host/session authentication, reject replayed or
mismatched jobs, report receiver-side write errors, and keep the destination
closed to writes until the receiver has validated and armed the session.
Multicast is a separate one-to-many deployment feature, not a prerequisite
for one-to-one remote cloning.

The remote workflow will share the same image/job contracts and generic
storage primitives as Server and Client modes in the single ISO. It must not
start DHCP or PXE services merely to perform a one-to-one clone.

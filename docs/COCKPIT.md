# Cockpit web interface

Cockpit is Feclora's primary operator interface. The React/PatternFly
application is installed at `/usr/share/cockpit/feclora`. The physical kiosk
uses Cockpit's loopback-only `--local-session` mode without a login prompt;
the dedicated service owns port 9090 and the standard authenticated socket is masked.

## Live kiosk startup, bootstrap and authentication

The Live image uses Fedora's `@core` package group plus Feclora's explicit
runtime packages, with no general-purpose desktop. Weston runs the DRM backend with kiosk-shell; Firefox is the only local
interactive application. `feclora-kiosk.service` starts it on tty1 under the
dedicated `feclora-kiosk` account. The kiosk account has no login shell, is
not a member of `wheel`. The separate root-owned local Cockpit service starts
the bridge for this dedicated physical-kiosk session.

The `feclora` administrator account is created as a member of `wheel`, but
starts locked. On each fresh Live boot, Firefox opens the Feclora Cockpit application directly at
`http://127.0.0.1:9090/cockpit/@localhost/feclora/index.html`. The dedicated
`feclora-cockpit-kiosk.service` starts Cockpit Web Service with its documented
`--local-session` mode and binds it only to IPv4 loopback. This skips Cockpit's
login flow for the physical kiosk. The bridge runs with system privileges so
Feclora's existing privileged API actions can execute without an interactive
password prompt. The standard `cockpit.socket` is masked; Feclora uses only the dedicated
passwordless local-session service on port 9090, which is not reachable from
the LAN. This is a local physical-appliance trust model, not a
secure multi-user local-host boundary: other processes running on the same
machine can also reach the loopback kiosk endpoint.

The Live filesystem is currently ephemeral: generated local CA/private keys
and session configuration are lost on reboot. A persistent configuration
store is a separate design requirement; Feclora must not silently choose one
of the disks that may be a restore target as its persistence device.

Before the local Cockpit service starts, a root-owned systemd oneshot generates
a local CA and a server certificate with SANs for `localhost`,
`127.0.0.1` and `::1`. The CA is installed in the Fedora system trust store and explicitly
installed into Firefox using its Linux enterprise certificate policy. Cockpit receives the
certificate and private key as separate files in
`/etc/cockpit/ws-certs.d/50-feclora.cert` and
`50-feclora.key`; private keys are root-only. Firefox does not bypass TLS
warnings or accept an untrusted certificate interactively.

Firefox runs with `--kiosk` and a managed enterprise policy. Firefox's
`WebsiteFilter` blocks all URLs except the loopback Feclora Cockpit host. Firefox match patterns do not constrain port numbers, so these
loopback hosts are allowed on any port. Independently, systemd's cgroup IP
filters restrict the kiosk browser to IPv4/IPv6 loopback; the browser cannot
open connections to LAN or Internet addresses. Firefox opens a normal
(non-private) kiosk window; password storage, developer tools, add-ons
management, Safe Mode and certificate-warning bypass are disabled. The local
CA is installed through Firefox's supported Linux `Certificates.Install`
policy and separately into Fedora's system trust store. The Weston/Firefox systemd service
restarts after failure. Weston is launched with `--no-config` and without
`--xwayland`, so no X11 compatibility server or user configuration is loaded.

This is defense in depth, not a claim of tamper-proof physical kiosk
security. Firmware/boot-menu access and hardware-level keyboard escape
behavior still require operator testing. The local no-login bridge runs with system privileges. This is deliberately
a single-user physical-appliance trust model: any other process already
running on the same host can connect to the loopback endpoint. Do not expose
port 9090 on a network interface or forward it through SSH/QEMU.

## Build and package

On the Fedora 45 build host, install Node.js and npm with
`build/install-host-deps.sh`. The Live build invokes
`build/build-webui.sh`, which installs the frontend dependencies and builds
`webui/dist/`. The generated package is staged on the augmented installer
media and installed at `/usr/share/cockpit/feclora`.

The target image includes `cockpit`, `cockpit-system`,
`cockpit-storaged`, `weston` and `firefox`; it does not install a desktop
environment. The standard `cockpit.socket` is masked by Kickstart. The certificate unit,
local passwordless kiosk service and Firefox kiosk unit are enabled; the
kiosk service itself binds port 9090 only to `127.0.0.1`. No Cockpit listener
is exposed on a LAN interface.

## Storage workflows

The Operations wizard provides:
- whole-disk, partition and active LVM logical-volume image capture;
- whole-disk capture with a selectable image format: Feclora RAW (with optional compression and age encryption) or QCOW2. Both formats are stored as ordinary manifest-backed disk images in local, mounted filesystem or S3 repositories. QCOW2 is the P2V format; restore accepts either RAW or QCOW2 directly and converts QCOW2 to private RAW staging before writing the selected physical disk. QCOW2 preserves disk sectors and partition metadata, but does not guarantee guest bootability; OS-specific drivers, initramfs or firmware changes may still be required.
- whole-disk, partition and existing-LV image restoration;
- whole-disk and partition-to-partition cloning;
- legacy P2V bundle export from an S3 object repository to the local repository or a mounted, identity-verified, read/write filesystem repository. In the Repositories tab, select the S3 source, enter the legacy image identifier, choose the destination (or Local repository), and submit the durable export. This compatibility path is for a QCOW2 plus `.p2v.json` sidecar; new manifest-backed QCOW2 captures do not need this export step.
- device discovery, image selection, compression selection and typed
  destructive confirmation;
- streamed byte-progress events from the storage engine;
- LVM capture and restore are limited to active, uniquely identified logical volumes in healthy volume groups; hidden, snapshot, RAID, striped, cache and unknown LV layouts are excluded. Restore overwrites data in an existing unmounted LV and does not create or resize LVM metadata. Raw LV images receive exact read-back verification; Partclone images receive a filesystem-specific read-only consistency check.
- optional image-security key initialization and age encryption when
  configured; artifact integrity is recorded and verified with SHA-256;
- durable local operation history, with a Cancel control for queued,
  preflight and running jobs, plus JSON export of the latest 100 loaded records.
  The history also reconciles the Live PXE restore journal, including interrupted
  results; PXE entries are read-only and cannot be cancelled through this view.

The Operation history tab can request cancellation of queued, preflight or
running local jobs. Feclora stops the worker and waits for its storage child
processes to exit before completing cancellation. Cancellation does not roll
back disk writes: a cancelled restore or clone may leave its destination
partially written, and the history records this warning. Jobs in verification
or terminal states cannot be cancelled.

The browser calls the same Python storage engines as the rest of Feclora.
The root-owned `/usr/libexec/feclora/cockpit-api` wrapper accepts a fixed
allowlist of actions. Requests are bounded JSON on stdin; device paths,
operation parameters, image identifiers and typed confirmations are
validated again by the backend. No shell or arbitrary command execution is
exposed through the API. Optional image-security keys are generated or installed for the current Live
session under `/etc/feclora/pki`. That directory is ephemeral in the default
Live appliance. Before reboot, the operator must preserve any age identity
needed to decrypt existing images. Losing an age identity
makes images encrypted to it unrecoverable. Age is not required for basic
local imaging.

## Current scope and limitations

The Cockpit application currently exposes local imaging operations, storage
inventory, image inventory, deployment journal summaries and system status.
Cockpit now includes an initial Server identity bootstrap step. It discovers
active IPv4 interface addresses, warns when NetworkManager reports an existing
DHCP server, verifies the selected address is still assigned to the interface,
and initializes or validates the managed CA and Server TLS identity, plus any
optional age recipient material configured by the operator, without
enabling DHCP/PXE services.

The Server setup tab also provides a PXE network-profile preflight. It
validates ProxyDHCP or explicitly confirmed isolated DHCP, checks pool bounds,
verifies the selected interface and runs dnsmasq/Caddy configuration tests.
It reports an existing DHCP server when NetworkManager has lease information
and blocks isolated authoritative DHCP in that case. A missing DHCP lease
identifier is not proof of an isolated network. This step does not start
services, alter firewall rules or persist a network profile.

The Server **Remote jobs** tab now provides the persistent deployment
lifecycle for supported jobs. Cockpit can start a non-boot-enabled
`feclora-deployment@<UUID>.service`, inspect its Server-authenticated TLS listener and live
per-Client READY/running/terminal states, disk-operation byte progress and
sampled throughput reported over each authenticated TLS control session, with
Cockpit refreshing active service status every two seconds. The Client's local
status also tracks image-transfer phase and byte count. During restore, the Server
also records the sender-side artifact byte count and throughput in the existing
journal using a local progress callback; no telemetry frames are injected into
the TLS artifact stream. Operators can explicitly arm a job after every selected Client is
READY, cancel only before arming, and stop the service when it is not
performing storage I/O. The service uses the existing
coordinator, hash-chained journal, TLS control protocol and transfer engines;
the local IPC socket accepts root peers only and validates the exact job UUID
and typed confirmation.

Unicast whole-disk capture and disk/partition restore are supported by
the Cockpit Server/Client services. Cockpit multicast restore now uses the
persistent Client service: each Client selects its own receive interface and
local destination, passes interface/route/udp-receiver preflight, approves
the exact destructive target, and reports READY only after those checks.
The Server derives the total staging requirement from the verified
manifest and includes it in the authenticated job offer. Before reporting READY,
each Client compares that requirement with free space in its configured image
repository and requires an additional 64 MiB safety reserve. A failed or
unavailable capacity check prevents READY; the runtime repeats a capacity check
before receiving artifacts. This is a point-in-time preflight, so operators must
avoid concurrent use of the staging filesystem during deployment.
The Server can require every selected Client, a configured minimum READY count, or a UTC deadline with at least one READY Client. The deadline opens the start gate but never starts disk I/O automatically: the Server operator must still enter the exact job-specific authorization. Only Clients READY at arm time are dispatched. Each Client stages
and verifies every artifact's manifest/digest and any configured encryption
before writing its local disk.

The Cockpit Remote jobs panel remains an operator-driven workflow. Unattended
multicast restore is a separate answer-file workflow: every Live Client downloads
the same schema-v1 DeploymentJob, selects its own WWN/serial target binding by
MAC and reports READY. With `start_policy: automatic`, the Server starts the
single multicast transmission only after every authorized Client is READY; the
job must carry explicit destructive confirmation and a managed repository ID.
Confirm switch IGMP snooping and an active querier on the same VLAN before
arming. UDPcast data packets themselves are not encrypted or authenticated;
Server-authenticated TLS protects the control channel, not the multicast payload. Multicast
capture and concurrent unicast deployments remain out of scope.

The Server service is never enabled at boot and never resumes an interrupted
job. A stop request closes the local IPC listener first, refuses new arm
requests, and waits for an active storage worker to reach its own terminal
state before closing Client sessions; its systemd stop timeout is therefore
unbounded. Interrupted journals require operator inspection and audit-only
reconciliation. Client-local target approval remains mandatory before READY.

No ISO build, hardware restore, PXE boot or multi-machine laboratory test is
claimed by source-level checks.

## Client remote jobs

On a configured Client, the **Client jobs** tab can inspect a Server job over
Server-authenticated TLS. The Client does not present a certificate or authenticate individually. It then
lists local disks/partitions, displays the exact Server-bound authorization
phrase, and starts a non-boot-enabled `feclora-client@<UUID>.service`.
The Client repeats the Server-authenticated TLS job handshake, rechecks the selected
block device against live inventory and mounted/root-device safety, and only
then reports READY. It waits for the Server's explicit ARM command before
starting disk I/O. Cockpit can inspect the Client's phase, target description,
byte progress (including physical-clone write and read-back phases) and terminal result after the browser disconnects.

The Cockpit Client service supports unicast whole-disk capture, whole-disk
and partition restore, multicast image restore, and direct whole-disk physical
multicast clone using the Client's independently approved destination. A host
runs only one storage/deployment job at a time across Server, Client and local
Cockpit operations.
Interrupted Client services are marked for inspection and are never
automatically reconnected or resumed. An orderly systemd stop is deferred
while the Client is in its storage-I/O phase; the unit has no stop timeout that
could kill an active write. To cancel a Client that is waiting for ARM, cancel
the unarmed job from the Server Cockpit. For multicast restore, each
Client selects its own active IPv4 interface/address before authenticated
job inspection. Feclora binds the preflight and persistent unicast TLS session
to that source address and revalidates it before connecting. Multicast restore
also uses the selected interface for the receiver preflight before READY.
The next hop and policy routing remain controlled by the Client kernel routing
table; per-job route-table overrides are not yet exposed. No automatic poweroff/reboot is performed.

## PXE service lifecycle

Cockpit can now activate and stop a preflighted PXE profile. Activation stages
the boot tree, validates the selected interface and generated daemon
configurations, creates transient dnsmasq and Caddy systemd units, and opens a
temporary firewalld zone bound exclusively to the selected interface. The
unit names and firewall restoration metadata are recorded in a private
runtime-state file so a later Cockpit API process can stop the same services.
The services are not enabled at boot.

Use **Stop PXE services and restore firewall** when network boot is no longer
needed. If shutdown reports an incomplete cleanup, inspect systemd and
firewalld before retrying; do not manually delete the runtime-state file while
the temporary zone or services may still exist. Isolated authoritative DHCP
must only be activated on a dedicated VLAN where Feclora is the sole DHCP
server. A missing DHCP server in the NetworkManager lease is not proof of
network isolation.

## Optional age recipient inventory

When age encryption is enabled, the Server setup tab can export the current
public recipient inventory. Each Client can refresh its local recipient list
from that public inventory after verifying that it includes the Client's own
age identity. Private age identities remain local. This manages image confidentiality recipients only.

## Cockpit deployment-job API

The Server Cockpit API can validate and persist a deployment-job definition in the
root-owned hash-chained journal. Creation validates selected Client MACs, the
selected interface and image type, and validates manifest SHA-256 digests and authenticates any
age-encrypted artifact when present. Age recipient registrations are required only when the operator selects encryption
for a specific image.
Persisting a job does not contact Clients, arm the job, or start disk I/O.
The persistent systemd service can now load a fresh definition, verify its
journal/configuration, bind the Server-authenticated TLS listener and expose root-only local
IPC to Cockpit. It owns one active job at a time and continues if the browser
disconnects. It refuses interrupted journals and never recreates TLS sessions
or resumes storage work after a service/process restart.

## Remote deployment job definitions

The **Remote jobs** tab creates and lists validated Server-side job definitions.
For restore, select an existing disk or partition image. Select Client MAC addresses for this job, the
Server interface and unicast or multicast transport. Multicast is available
for image restore and whole-disk physical clone. The backend revalidates job
MAC selection and image type, and checks registered age recipients only when
the image is age-encrypted. Manifests are transferred over the Server-authenticated TLS control session; Clients are not individually authenticated.

The persisted-job table also shows each Client's last journaled state,
the event count and whether a job was interrupted. After inspecting every
Client and destination manually, the operator can close an interrupted journal
for audit by entering the exact `RECONCILE <job-UUID>` phrase. This records
that manual inspection occurred; it does not resume, retry, roll back or touch
any storage device. The action is rejected for non-interrupted jobs.

Unicast save/restore jobs are limited to one Client. Direct disk/partition
clone jobs can target multiple selected Clients over independent TLS sessions;
the Server serializes reads from its single source, while each Client retains
its own local target approval and read-back verification. UDPcast multicast restore and physical-disk multicast clone require at least
two selected Clients. Physical clone binds the Server source identity when the
job is created and requires every selected Client to report READY, revalidate
its own destination, open it exclusively and start its UDPcast receiver before
the Server emits the first data byte. No image staging artifact is created.

For each fresh job, use **Start / connect service** to start its
non-boot-enabled `feclora-deployment@<UUID>.service` instance. The service
holds the Server-authenticated TLS listener and journal independently of the browser. Clients
verify the Server certificate, then select a local target and type
its destructive/read confirmation through the Cockpit **Client jobs** tab
before reporting READY. For multicast, each Client also selects its receive
interface and confirms the VLAN's IGMP snooping/querier configuration.
Cockpit exposes three start policies for image restore and unicast jobs: manual (all selected Clients READY),
minimum READY count, or a UTC deadline (at least one Client READY). Physical
multicast clone is restricted to manual start and requires every selected Client
plus every receiver-open acknowledgement. The deadline opens the start gate but
never starts storage I/O automatically. Only READY Clients at arm time are dispatched. The Server operator must still enter the
exact job-specific phrase: `ARM <UUID>` for unicast save/restore,
`ARM <UUID> AND READ /dev/<source>` for unicast direct clone,
`ARM PHYSICAL MULTICAST <UUID> FROM /dev/<source> IGMP-VERIFIED` for
physical multicast clone, or `ARM MULTICAST <UUID> IGMP-VERIFIED` for
multicast image restore, then select
**Arm and execute**. Each successful remote restore/clone Client can be
configured independently to do nothing, reboot or power off after its own
write/read-back verification and after reporting its terminal result. Failed
Clients are never rebooted or powered off.

Cancellation is intentionally limited to the unarmed state. Feclora does not
offer a button that pretends to interrupt a disk write already in progress.
The service cannot be stopped while its worker or any Client is actively
writing. If the service exits during an armed/running job, the journal remains
interrupted and must be manually inspected/reconciled; it is never restarted
automatically. The service supports one job per Server at a time and is not
enabled at boot. Multicast preflight reports local interface/route warnings,
but switch IGMP snooping/querier and VLAN isolation still require operator
validation. UDPcast multicast data is not encrypted or authenticated; only
the control plane uses Server-authenticated TLS; Clients are not authenticated individually.

## Optional age recipient inventory refresh

When age encryption is enabled, the Server trust panel can export the current public `age-recipients.txt` to mounted removable media without overwriting an existing file. Each remaining Client verifies that the inventory includes its own age identity before refreshing the local recipient list. Private identities remain local. This workflow is optional; deployments that do not use age do not need recipient inventories.

## Read-only image browsing

The image repository panel also provides **Explore image files** for whole-disk
RAW and QCOW2 images. After selecting a partition from the verified layout
preview, the operator can browse directories and download individual regular
files up to 16 MiB. RAW artifacts are checked against their manifest and
decrypted/decompressed into private temporary storage when required; QCOW2
artifacts are checked for digest, virtual capacity and external backing/data
dependencies before inspection. Filesystem access uses the isolated libguestfs
appliance with read-only drives and read-only mounts. Feclora does not attach a
host loop/NBD device or mount guest filesystems in the host namespace. Symbolic
links are not followed; directory listings are bounded to 1000 entries. Decoded RAW images are cached in a private root-owned session directory so navigation does not repeatedly decompress the whole disk; inactive sessions and their cached data are removed by systemd-tmpfiles after 24 hours.
Supported filesystem types are ext2/3/4, XFS, NTFS, FAT variants, exFAT and
Btrfs, subject to the filesystem drivers available inside libguestfs. LVM,
LUKS-encrypted partitions, multi-device Btrfs and unsupported filesystem
layouts are not exposed by this initial browser. Browsing never modifies the
source image.

## Partition extraction

The image repository panel also exposes extraction of a selected partition from a whole-disk image. The operator selects a disk image, reviews a verified read-only partition-table preview (including start sectors and sizes), and selects the unambiguous partition node from the preview (the underlying engine also accepts PARTUUID and PARTLABEL selectors). Feclora verifies the source manifest and any configured authenticity evidence, decrypts and decompresses the disk artifact as needed, extracts the exact byte range, and publishes a separate partition manifest/artifact transactionally. If the source artifact was age-encrypted, the extracted partition artifact is re-encrypted only when the optional age feature is enabled and recipients are configured. The source image is never modified.

Disk restore also presents a read-only layout preview after selecting a whole-disk image and destination disk. It verifies the manifest and partition-table artifact, displays the source partitions and compares the source image size with the selected target capacity. The current restore preserves the captured partition layout; larger target disks retain unused trailing capacity. No automatic partition or filesystem growth is performed.

Cockpit image inventory provides an on-demand read-only verification report for every artifact. It verifies stored artifact SHA-256 and size, age authentication when the artifact is age-encrypted, compression integrity and decoded whole-disk size. Images are reported as verified only when every stored digest and decoded artifact check succeeds.

## Certificate status and renewal

Cockpit reports the local managed Server TLS certificate expiry and the associated deployment CA expiry. Certificates with 30 days or fewer remaining are flagged for renewal; expired Server or CA certificates and configuration/inspection errors are surfaced as critical status. This is read-only and does not rotate certificates automatically.

Server TLS certificate renewal is also available in the Cockpit Server setup tab. It requires typing `RENEW SERVER CERTIFICATE`, refuses to proceed while any deployment service is active, renews the certificate using the existing CA and Server private key, verifies the resulting chain, SAN and key match, and atomically replaces `server.crt`. The CA and Server identity remain unchanged. This is certificate renewal, not CA rotation or Server key rotation.

## Network configuration status

Cockpit's privileged API enumerates NetworkManager connection profiles through
a read-only, JSON-based inventory. The response is sanitized to expose only
profile identity, interface/device, autoconnect state and IPv4 method, addresses,
gateway and DNS; Wi-Fi credentials and other secret properties are never
returned. The Network tab can apply DHCP or static IPv4 settings to a profile
attached to a device, as described below.

### DHCP and static IPv4 profile application

The Network tab exposes active NetworkManager profiles on the current host
(Server or Client) and can apply DHCP or static IPv4 settings. Static mode
validates the address, prefix, gateway and DNS values before changing the
selected profile. Activation is performed inside a NetworkManager checkpoint
with a 120-second automatic rollback deadline. Feclora verifies the selected
profile and resulting IPv4 address before destroying the checkpoint; failures
request an immediate rollback. If Cockpit disconnects or the API process is
interrupted, NetworkManager's checkpoint timeout remains the recovery path.

Only profiles currently attached to a device are selectable. Keep local
console access available during changes, especially when changing the
management interface. This workflow currently covers IPv4 only; IPv6, Wi-Fi
secret provisioning, inactive profile binding and multi-interface routing
policy are not configured here.

## Remote repository credentials

See [Remote image repositories](REMOTE-REPOSITORIES.md) for the Cockpit encrypted-credential import, selection, rotation and removal workflow.

## Optional image security and repository transports

Remote repository types are SSHFS, NFS and SMB/CIFS mounted filesystems, plus S3 object storage through its HTTPS API. Cockpit exposes the mounted-provider and S3 object-repository workflows separately; S3 is not mounted as a filesystem.

For Server/Client deployment jobs, the persistent Cockpit Client can select an existing local logical volume for capture or restore when the job target type is `logical_volume`. Capture runs the manifest-backed LV planner and existing safe capture pipeline; restore validates healthy local LVM topology and repeats its preflight immediately before writing. Neither path creates or resizes LVM metadata.

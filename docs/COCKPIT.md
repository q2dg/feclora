# Cockpit web interface

Cockpit is Feclora's primary operator interface. The React/PatternFly
application is installed at `/usr/share/cockpit/feclora` and uses Cockpit's
authenticated session and explicit superuser authorization for privileged
operations.

## First login

The live console prints the Cockpit URL and setup instructions. From the
console, set a password for the live account:

```bash
sudo passwd feclora
```

Then allow Cockpit through firewalld only on the trusted management network
(or use the host's existing interface-specific firewall policy):

```bash
sudo firewall-cmd --add-service=cockpit
```

Then open `https://<management-interface-address>:9090` from a trusted
management workstation and sign in as `feclora`. The firewall rule above is
runtime-only; do not make it permanent unless the management VLAN/interface
is correctly isolated. Cockpit's Terminal page is available for system
administration and diagnostics; it is not used as a substitute for Feclora's
validated storage workflows.

## Build and package

On the Fedora 45 build host, install Node.js and npm with
`build/install-host-deps.sh`. The ISO build invokes
`build/build-webui.sh`, which installs the frontend dependencies and builds
`webui/dist/`. The generated package is staged on the augmented installer
media and installed at `/usr/share/cockpit/feclora`.

The Live image includes `cockpit`, `cockpit-system` and
`cockpit-storaged`; `cockpit.socket` is enabled. The operator must set a
non-empty live-account password before browser login.

## Storage workflows

The Operations wizard provides:
- whole-disk and partition image capture;
- whole-disk and partition image restoration;
- whole-disk and partition-to-partition cloning;
- device discovery, image selection, compression selection and typed
  destructive confirmation;
- streamed byte-progress events from the storage engine;
- local age identity and minisign key initialization, optional age encryption
  and manifest signing on capture;
- durable local operation history.

The browser calls the same Python storage engines as the rest of Feclora.
The root-owned `/usr/libexec/feclora/cockpit-api` wrapper accepts a fixed
allowlist of actions. Requests are bounded JSON on stdin; device paths,
operation parameters, image identifiers and typed confirmations are
validated again by the backend. No shell or arbitrary command execution is
exposed through the API. Local image keys are generated once and kept under
`/etc/feclora/pki`; back up private keys securely and offline. Losing the age
identity makes encrypted local images unrecoverable, and losing the signing
key prevents future signatures with the same identity.

## Current scope and limitations

The Cockpit application currently exposes local imaging operations, storage
inventory, image inventory, deployment journal summaries and system status.
Cockpit now includes an initial Server identity bootstrap step. It discovers
active IPv4 interface addresses, warns when NetworkManager reports an existing
DHCP server, verifies the selected address is still assigned to the interface,
and initializes or validates the managed CA, mTLS Server identity, age
recipient and minisign signing material without enabling DHCP/PXE services.

The Server setup tab also provides a PXE network-profile preflight. It
validates ProxyDHCP or explicitly confirmed isolated DHCP, checks pool bounds,
verifies the selected interface and runs dnsmasq/Caddy configuration tests.
It reports an existing DHCP server when NetworkManager has lease information
and blocks isolated authoritative DHCP in that case. A missing DHCP lease
identifier is not proof of an isolated network. This step does not start
services, alter firewall rules or persist a network profile.

The Cockpit workflows now cover PXE profile preflight and service
activation/shutdown, removable-media Client enrollment, Server-side CSR
approval, and validated remote-job definition. These steps do not yet form a
complete remote deployment lifecycle: jobs are persisted as definitions, but
Cockpit does not start Clients, collect local destructive-target approvals,
run the deployment coordinator as a persistent service, or display live
per-client progress. Multicast partition restore is supported by the runtime
but still awaits that execution and monitoring integration. The old
dialog-based modules are migration-era code and are not part of the supported
Cockpit workflow.

No ISO build, hardware restore, PXE boot or multi-machine laboratory test is
claimed by the source-level checks.


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


## Trusted Client enrollment

The Server setup tab now includes **Trusted Clients · Approve CSR**. On a
Client, prepare the enrollment request and public age recipient on removable
media. Optionally include its minisign public key only when that Client is
authorized to capture images for the Server.

On the Server, provide the CSR path, age-recipient path and Client unicast MAC.
Paths must refer to regular files on mounted media under `/run/media`,
`/media` or `/mnt`. Inspect the request first; Cockpit verifies the CSR
signature and its single Feclora Client URI SAN, validates the age recipient,
and displays the identity/MAC confirmation phrase. The approval action requires
typing that exact phrase. It then issues and enrolls the certificate and
exports `feclora-<id>.crt`, `ca.crt`, `server.pub` and
`age-recipients.txt` alongside the CSR. Existing bundle files are never
overwritten.

Only public enrollment material is copied to removable media. TLS and age
private keys remain on the Client. The Client-side preparation and response-import stages are also integrated
in Cockpit; no dialog workflow is required for enrollment.


## Client enrollment

The **Client enrollment** tab provides both stages of the removable-media
ceremony. On a not-yet-enrolled Client, prepare a request by choosing a stable
Client ID and a mounted media directory. The Client creates its TLS private key
and age identity locally; only the CSR and public age recipient are exported.
Optionally enable image capture to create a separate local minisign keypair
and export only its public key.

After the Server approves the CSR, return the media and provide the Server
address, Client unicast MAC, response bundle directory, CA SHA-256 fingerprint
and Server minisign public-key SHA-256 fingerprint. Cockpit verifies both
fingerprints, the CA chain, the certificate SAN and private-key match, then
installs the identity and writes the Client runtime configuration. Existing
Client configuration or partial identity files are not overwritten. This
wizard does not initiate a remote deployment job.


## Cockpit deployment-job API

The Server Cockpit API can validate and persist a deployment-job definition in the
root-owned hash-chained journal. Creation verifies enrolled Client MACs, the
selected interface, required per-Client signing keys for capture, and the
Server signature and Client age-recipient registrations for encrypted restore.
Persisting a job does not contact Clients, arm the job, or start disk I/O.
The persistent systemd service can now load a fresh definition, verify its
journal/configuration, bind the TLS 1.3 mTLS listener and expose root-only local
IPC to Cockpit. It owns one active job at a time and continues if the browser
disconnects. It refuses interrupted journals and never recreates TLS sessions
or resumes storage work after a service/process restart.


## Remote deployment job definitions

The **Remote jobs** tab creates and lists validated Server-side job definitions.
For restore, select an existing signed disk or partition image; for capture,
choose a new image identifier. Select already enrolled Client MAC addresses,
the Server interface and unicast or multicast restore transport. The backend
revalidates enrollment, signing-key availability, image signature, image type
and age-recipient registrations before persisting a hash-chained journal.

The persisted-job table also shows each Client's last journaled state,
the event count and whether a job was interrupted. After inspecting every
Client and destination manually, the operator can close an interrupted journal
for audit by entering the exact `RECONCILE <job-UUID>` phrase. This records
that manual inspection occurred; it does not resume, retry, roll back or touch
any storage device. The action is rejected for non-interrupted jobs.

For each fresh job, use **Start / connect service** to start its
non-boot-enabled `feclora-deployment@<UUID>.service` instance. The service
holds the mTLS listener and journal independently of the browser. Clients
connect with their enrolled certificates and must select a local target and
type its destructive/read confirmation through the existing Client-local
runtime before reporting READY; the Client-side Cockpit target-selection
wizard remains outstanding. Cockpit shows
live Client states and the service listener. Only after every authorized
Client is READY can the operator enter the exact job-specific phrase
`ARM <UUID>` (unicast) or `ARM MULTICAST <UUID>` (multicast) and select
**Arm and execute**. The existing unicast save/restore or multicast restore
engine then runs in the service process.

Cancellation is intentionally limited to the unarmed state. Feclora does not
offer a button that pretends to interrupt a disk write already in progress.
The service cannot be stopped while its worker or any Client is actively
writing. If the service exits during an armed/running job, the journal remains
interrupted and must be manually inspected/reconciled; it is never restarted
automatically. The service supports one job per Server at a time and is not
enabled at boot. Multicast preflight reports local interface/route warnings,
but switch IGMP snooping/querier and VLAN isolation still require operator
validation. UDPcast multicast data is not encrypted or authenticated; only
the control plane uses mTLS.

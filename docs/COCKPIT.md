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

The rest of Server/Client provisioning and the complete PXE deployment
lifecycle still require web workflows: network mode and address-pool setup,
PXE service activation, CSR approval and Client enrollment, job creation and
control, and live per-client progress. The old dialog-based modules are
migration-era code and are not part of the supported Cockpit workflow.
Multicast partition restore is supported by the runtime but still requires
complete Cockpit job orchestration and live per-client progress reporting.

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

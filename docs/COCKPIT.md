# Cockpit web interface

Feclora ships a dedicated Cockpit package built with React and PatternFly.
It is an optional web dashboard; local rescue remains available without
Cockpit or a network service.

## Build and package

On the Fedora 45 build host, install Node.js and npm with
`build/install-host-deps.sh`. The ISO build invokes
`build/build-webui.sh`, which installs the exact top-level versions pinned
in `webui/package.json` and produces `webui/dist/`. The generated package
is staged on the augmented installer media and installed at
`/usr/share/cockpit/feclora`.

The Live image includes `cockpit`, `cockpit-system` and
`cockpit-storaged`, but `cockpit.socket` is disabled by default. Feclora
does not expose a web listener automatically.

## Explicit operator activation

The Live user has no password by default. Before enabling Cockpit, set a
strong password locally:

```bash
sudo passwd feclora
sudo systemctl start cockpit.socket
```

Then access `https://<management-interface-address>:9090` from a trusted
management workstation and authenticate as `feclora`. Configure firewall
access only on a trusted management interface/VLAN; do not expose port 9090
on a shared or untrusted network. Cockpit uses its normal TLS and PAM login
flow. The web page's privileged inventory calls use Cockpit's superuser
authorization.

## Current functionality and security boundary

The React/PatternFly page currently provides read-only:
- host and Cockpit/PXE service status;
- manifest-backed image inventory, including signature and age-encryption
  indicators;
- hash-chained deployment journal summaries and interrupted-job flags;
- local storage inventory.

The root-owned `/usr/libexec/feclora/cockpit-api` wrapper accepts only four
fixed actions: `status`, `inventory`, `images` and `journals`. The Python
API rejects unknown actions and exposes no shell, arbitrary argv, disk write,
capture, restore, clone, job-arm, PXE-start or firewall mutation operation.

Destructive imaging and deployment remain in the existing guarded dialog
workflows. React forms for those operations, full server/client management,
and live multicast progress are not yet implemented. Do not interpret the
dashboard as a replacement for the explicit local-target approval gates.

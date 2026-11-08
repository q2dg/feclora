# ADR 0006: Embedded PXE/DHCP service stack

- Status: Accepted
- Date: 2026-11-08
- Scope: Server-mode DHCP, ProxyDHCP, TFTP and HTTP network boot

## Context

feclora is a single Fedora Live ISO with Local rescue, Server and Client
roles. Server mode must provide network boot for BIOS and UEFI clients without
requiring a separate PXE appliance. It must also coexist safely with networks
that already have a DHCP server.

## Decision

Use the following Fedora-native components:

- **dnsmasq** for DHCPv4, ProxyDHCP/PXE discovery and its built-in read-only
  TFTP service. dnsmasq is small, designed for embedded systems, supports PXE
  proxy mode, and can classify clients and provide architecture-specific boot
  choices.
- **iPXE boot images** from the Fedora `ipxe-bootimgs-x86` package:
  `undionly.kpxe` for legacy BIOS and `snponly.efi` for UEFI x86_64.
  Chainload iPXE, then use an HTTP-delivered iPXE script and kernel/initramfs
  payloads for the feclora client environment.
- **Caddy** for HTTP delivery of iPXE scripts, kernel/initramfs, signed job
  descriptors and deployment metadata. Do not use TFTP for large payloads.

Do not add ISC DHCP (`dhcpd`): ISC DHCP is end-of-life and Fedora labels its
package best-effort. Do not introduce Kea for the first embedded implementation:
it is a capable standalone DHCP server, but would still require separate
TFTP/HTTP services and adds operational/configuration surface that dnsmasq
already covers for this appliance use case. Reconsider Kea only if measured
requirements demand large-scale DHCP lease management, HA or its API.

## Server operating profiles

1. **Isolated DHCP mode:** only when the operator explicitly selects a
   dedicated interface/subnet and confirms that feclora is authoritative for
   DHCP on that isolated network. dnsmasq provides leases and PXE boot options.
2. **Existing-DHCP Proxy mode:** dnsmasq runs as ProxyDHCP and provides PXE
   boot information only. The existing DHCP server remains responsible for
   address allocation. This is the preferred mode on an existing LAN.
3. **Disabled:** default state in Local rescue and Client modes; no DHCP, PXE,
   TFTP or HTTP service is started.

Never start an ordinary DHCP pool merely because Server mode was selected.
Require explicit operator confirmation of the selected interface, subnet,
address pool and operating profile. Bind dnsmasq to the selected interface
and local address, enable DHCP authoritative mode only for an isolated
operator-confirmed subnet, and validate the generated configuration with
`dnsmasq --test` before activation. Reject ambiguous interfaces, overlapping
local subnets, and any configuration that would bind wildcard DHCP sockets.

## Boot flow

1. Firmware PXE obtains network configuration from the existing DHCP server
   (ProxyDHCP profile) or feclora's isolated DHCP service.
2. dnsmasq identifies client architecture and supplies the matching BIOS or
   UEFI iPXE chainloader over TFTP.
3. iPXE retrieves its script and the feclora kernel/initramfs over HTTP.
4. The client presents its authenticated identity to the feclora control
   plane. MAC allowlisting is an additional filter, not authentication.
5. The control plane exposes only an explicitly armed, authorized job.
   Booting a client must never automatically start a destructive operation.

## Security and operations

- Role services are systemd units started by the Server runtime, not enabled
  at image boot. They are stopped on leaving Server mode and on shutdown.
- TFTP is restricted to a dedicated read-only boot tree; no client uploads.
- HTTP boot content is read-only. Deployment data transport is a separate
  authenticated protocol and is not implemented by nginx.
- Firewalld rules are scoped to the selected interface and required ports.
  Do not disable the firewall.
- DHCP/TFTP/HTTP services must bind only to the configured deployment
  interface/address. Never listen on all interfaces by default.
- Detect likely DHCP servers before enabling isolated DHCP; a scan is only a
  warning/safety signal, not proof that a subnet is isolated.
- Log service startup, selected interface/profile, client requests, job IDs,
  and shutdown. No network boot request may arm a job.
- The Server UI must make DHCP mode and address scope explicit and show a
  final confirmation before sockets are opened.

## Consequences

The Fedora 45 image includes dnsmasq, iPXE x86 boot images and Caddy so all
three roles can run from the same ISO. Installing packages does not activate
network services. The runtime configuration generator, interface/network
validation, systemd lifecycle, firewall integration, BIOS/UEFI chainloading,
authenticated PXE client protocol, and multi-client deployment remain
implementation and test work.

## References

- dnsmasq manual: https://dnsmasq.org/docs/dnsmasq-man.html
- iPXE ProxyDHCP notes: https://ipxe.org/appnote/proxydhcp
- Fedora dnsmasq package: https://packages.fedoraproject.org/pkgs/dnsmasq/dnsmasq/
- Fedora iPXE x86 boot images: https://packages.fedoraproject.org/pkgs/ipxe/ipxe-bootimgs-x86/
- Fedora Caddy package: https://packages.fedoraproject.org/pkgs/caddy/caddy/

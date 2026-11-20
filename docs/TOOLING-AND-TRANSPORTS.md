# Tooling and transports

Feclora reuses established Linux utilities and libraries rather than
reimplementing storage and network protocols.

## Repository providers

| Provider | Mechanism | Notes |
|---|---|---|
| SSHFS | `sshfs` | Host-key verification and protected SSH credentials |
| NFS | `mount.nfs` | NFSv4.2; server-side export permissions remain external |
| SMB/CIFS | `mount.cifs` | SMB 3.1.1, protocol signing/encryption options and protected credentials |
| S3 | S3-compatible object API | SigV4, scoped credentials, multipart transfer and manifest-last publication; not a filesystem mount |

S3 is implemented as an object repository through an HTTPS API, not a FUSE mount. The repository manager, protected credential handling, API and Cockpit workflows are integrated.
Self-hosted Garage and managed S3-compatible services can expose the same API.
The endpoint, bucket and prefix are configured per repository.

## Design constraints

- Remote services are provisioned and administered by their owners.
- Secrets are never accepted inline in repository definitions or returned by
  the management API.
- File-system mounts use restrictive `nosuid,nodev,noexec` options and
  verify the mounted source before image operations.
- Object storage uses immutable artifact keys, verifies SHA-256 and byte
  counts, aborts failed multipart uploads, and publishes the manifest last.
- TLS certificate validation remains enabled for HTTPS endpoints.
- Repository operations must preserve cancellation, progress reporting and
  failure visibility.

## Upstream projects and tools

Feclora integrates the following projects and system utilities. Links point to
their upstream documentation or project home pages.

| Component | Role in Feclora | Upstream |
|---|---|---|
| Fedora Server | Base Live userspace and package environment | [fedoraproject.org/server](https://fedoraproject.org/server/) |
| Cockpit | Primary browser-based administration interface | [cockpit-project.org](https://cockpit-project.org/) |
| Firefox | Restricted kiosk browser | [mozilla.org/firefox](https://www.mozilla.org/firefox/) |
| Weston | Wayland kiosk compositor with kiosk-shell | [wayland.freedesktop.org](https://wayland.freedesktop.org/) |
| React | Cockpit application UI | [react.dev](https://react.dev/) |
| PatternFly | UI component system | [patternfly.org](https://www.patternfly.org/) |
| Vite | Frontend build tooling | [vite.dev](https://vite.dev/) |
| Partclone | Filesystem-aware image capture and restore | [partclone.org](https://partclone.org/) |
| util-linux (lsblk, findmnt, losetup) | Block-device inventory and safe storage inspection | [github.com/util-linux](https://github.com/util-linux/util-linux) |
| LVM2 | Logical-volume inventory and supported LV operations | [sourceware.org/lvm2](https://sourceware.org/lvm2/) |
| cryptsetup | LUKS2 metadata inspection and container validation | [gitlab.com/cryptsetup](https://gitlab.com/cryptsetup/cryptsetup) |
| Btrfs-progs | Btrfs filesystem and metadata inspection | [github.com/kdave/btrfs-progs](https://github.com/kdave/btrfs-progs) |
| Stratis | Stratis storage inventory | [stratis-storage.github.io](https://stratis-storage.github.io/) |
| OpenSSH / SSHFS | Secure shell transport and mounted SSH repositories | [openssh.com](https://www.openssh.com/) · [github.com/libfuse/sshfs](https://github.com/libfuse/sshfs) |
| NFS utilities | NFS client mounts | [linux-nfs.org](https://linux-nfs.org/) |
| CIFS utilities | SMB/CIFS client mounts | [wiki.samba.org](https://wiki.samba.org/index.php/LinuxCIFS_utils) |
| AWS SDK for Python (boto3) | S3-compatible object API and SigV4 | [boto3.amazonaws.com](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html) |
| dnsmasq | DHCP/ProxyDHCP and PXE network boot services | [thekelleys.org.uk/dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) |
| iPXE | Network bootloader and PXE handoff | [ipxe.org](https://ipxe.org/) |
| Caddy | HTTP delivery of Live boot assets and PXE answer files | [caddyserver.com](https://caddyserver.com/) |
| UDPcast | Multicast artifact and disk-data transport | [udpcast.linux.lu](https://www.udpcast.linux.lu/) |
| firewalld | Temporary interface-scoped network rules | [firewalld.org](https://firewalld.org/) |
| NetworkManager | Network profiles, DHCP/static configuration and link state | [networkmanager.dev](https://networkmanager.dev/) |
| systemd / systemd-creds | Service lifecycle, durable workers and protected credentials | [systemd.io](https://systemd.io/) |
| age | Optional image-artifact encryption | [age-encryption.org](https://age-encryption.org/) |
| QEMU (qemu-img) | Physical-to-virtual QCOW2 conversion and ISO build virtualization | [qemu.org](https://www.qemu.org/) |
| xorriso | Recovery ISO assembly and inspection | [gnu.org/software/xorriso](https://www.gnu.org/software/xorriso/) |
| Lorax (livemedia-creator) | Fedora Live ISO construction | [weldr.io/lorax](https://weldr.io/lorax/) |

The presence of a tool in this list does not imply that every capability it
provides is exposed by Feclora. Consult the [feature matrix](FEATURE-MATRIX.md)
for the exact integration scope and current limitations.

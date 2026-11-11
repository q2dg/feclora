# PXE and Server/Client VM lab

This lab creates an isolated libvirt network with no libvirt DHCP service. Feclora Server must be the only DHCP/PXE authority on this test segment. Do not attach this network to a production bridge or a physical LAN.

The harness creates one Feclora Server VM and two PXE clients (legacy BIOS and UEFI). The Server VM starts from the Live ISO; both PXE clients are deliberately powered off after creation so they cannot attempt PXE before the Server is configured. PXE boot, authenticated unicast save/restore, and multi-client multicast restore acceptance remain operator-driven and must be recorded separately. The Server/Client control and data paths plus this multi-VM runbook are implemented, but the VM orchestrator does not drive them unattended.

## Host requirements

On a Fedora test host install qemu-kvm, libvirt, virt-install, virt-viewer, edk2-ovmf and qemu-img; start the libvirt daemon and verify that KVM/OVMF are usable. Fedora documents virt-install and PXE guest boot support: https://github.com/virt-manager/virt-manager/blob/main/man/virt-install.rst

## Run

~~~bash
sudo bash tests/vm/run-pxe-matrix.sh /path/to/feclora-live.iso
~~~

The script creates a private libvirt network named feclora-pxe-lab and three guests. Connect to their consoles with virt-viewer or virsh console. The client VMs remain powered off until explicitly started after Server setup. The host-side bridge is normally virbr-feclora with 192.0.2.1/24; configure the Server guest's test NIC as a static address such as 192.0.2.2/24. Do not configure a gateway or forward this test network.

In the Server guest:
1. Select the test NIC in Feclora Server mode.
2. Choose isolated DHCP and a small pool such as 192.0.2.100-192.0.2.150.
3. Type the exact authoritative-DHCP confirmation shown by Feclora.
4. Start PXE services; confirm dnsmasq, Caddy and firewalld are active.
5. Start the clients only after Server PXE services are active: `sudo virsh start feclora-pxe-bios` and `sudo virsh start feclora-pxe-uefi`. Confirm BIOS loads undionly.kpxe and UEFI loads ipxe-snponly-x86_64.efi, then iPXE fetches the Feclora kernel, initramfs and squashfs over HTTP. If a client is already running, shut it down and start it again after Server readiness.
6. Provision the root-owned Server/Client config files and test certificates described in docs/DEPLOYMENT-SETUP.md.
7. Create a signed whole-disk image, run one authenticated unicast restore to a disposable client disk, and verify the journal, destination read-back and result.

## Acceptance checklist

- [ ] Server Live ISO boots and discovers the isolated test NIC.
- [ ] ProxyDHCP mode does not allocate client addresses.
- [ ] Isolated DHCP mode serves only the isolated pool.
- [ ] BIOS iPXE chainloads and boots Feclora Live.
- [ ] UEFI iPXE chainloads and boots Feclora Live.
- [ ] HTTP boot assets are served from the selected Server interface only.
- [ ] Stop restores the original firewalld interface zone and stops transient units.
- [ ] Authenticated control-plane mTLS test passes in CI.
- [ ] A disposable client target is selected and authorized locally before any write.
- [ ] End-to-end image transfer, restore, read-back and per-client result are verified.

Do not mark the mTLS/artifact-transfer, disposable-disk restore or read-back items complete until those operations have actually run and the results have been recorded. VM PXE boot success alone does not prove a deployment or restore succeeded.

## Multi-client multicast restore acceptance

The same isolated lab has one Server and two independently bootable Clients (BIOS and UEFI), which is the minimum useful multi-receiver test. This is an operator acceptance procedure; creating the VMs does not execute it.

1. Boot the Server ISO and both Client ISOs on the isolated libvirt network. Give the Server a static address and start Feclora PXE. Confirm both clients can reach the control listener over the isolated network.
2. Provision a distinct CA-issued TLS client certificate and identity for each Client, map each certificate to that VM's unique MAC in the Server enrollment UI, and provision the matching private key only on that Client. Use the same trusted Server CA/public minisign key on both Clients.
3. Ensure the switch/bridge path forwards IPv4 multicast on this isolated segment. Configure IGMP snooping with a working querier. The current profile uses TTL 1 and cannot route between VLANs.
   On a Linux test host, inspect the libvirt bridge with `ip -d link show dev virbr-feclora` and `bridge mdb show dev virbr-feclora`. If multicast snooping is enabled but no querier is present, record the current value and enable a temporary querier for the lab: `cat /sys/class/net/virbr-feclora/bridge/multicast_querier`, then `sudo ip link set dev virbr-feclora type bridge mcast_querier 1`. Restore the recorded value after the test with the same command and the original value. The bridge name can differ; use the actual bridge created by the script.
4. Place one signed whole-disk image set in the Server repository. Use disposable qcow2 target disks on both Clients; never attach host block devices.
5. In Server mode choose **Multicast**, **Restore**, select both enrolled Clients, select the signed image, and use a group in 239.0.0.0/8 with an even UDPcast port base such as 9000. Confirm the displayed network preflight using the exact job-specific phrase.
6. On each Client select **Client**, enter the same job UUID, select its own local multicast receive interface, select its disposable target disk and type the exact confirmation phrase for that disk and Server identity. The Server must show both MACs READY before it will arm.
7. Arm once on Server. Each Client receives the signed manifest over mTLS, receives every artifact over UDPcast into private staging, verifies signature/size/SHA-256, restores its selected disk and performs destination read-back verification.
8. Record the Server per-client result, job journal, both destination read-back results and the interface/firewall state. Confirm UDPcast's temporary UDP rules are removed on both Clients and Server.
9. Repeat negative tests: leave one Client unready (arming must be refused); use a wrong Server minisign public key (no disk write); interrupt one receiver (the job must fail rather than report success); and verify no automatic restart after powering a VM off mid-transfer.

The multicast receiver count is deliberately set to the full selected Client count. The sender must not start unless every selected Client is authenticated and READY. The current sender is bounded by its configured wait and bitrate limits. If the multicast path or IGMP behavior is unreliable, do not weaken the receiver threshold to hide packet loss; use unicast instead.


## LUKS2 encrypted-partition restore acceptance

The dedicated loop-device test exercises the full raw encrypted-container path,
including the check that metadata-only verification cannot establish: the
restored container must unlock with the original key and expose the exact
plaintext bytes written before capture.

On a disposable Fedora/Linux test host, install `cryptsetup`, `util-linux`
(`losetup`, `sfdisk`, `lsblk`), `psmisc` (`fuser`), `coreutils`, and Python. From the repository
root run:

~~~bash
sudo bash tests/vm/run-luks2-partition-acceptance.sh
~~~

The script creates two sparse 160 MiB files in a private temporary directory,
partitions them, attaches them only as loop devices, formats the source
partition as LUKS2 with a temporary test key, writes a random plaintext payload
through the source mapping, and captures the raw encrypted partition. It then
runs the real unicast `execute_client_image_job` runtime with a locally
approved partition target and a job-bound transfer offer. A local stream
socket pair connects Feclora's actual framed control-message and
`send_image_set`/`receive_image_set` transfer protocol; the socket pair
stands in for an already-authenticated TLS stream and does not exercise TLS
certificate negotiation or network routing. The actual `restore_partition`
engine performs the destructive write, safety checks, raw read-back and
LUKS2 header verification against the second loop partition. The harness
confirms an incorrect key is rejected, opens the restored container using
the original key, and compares the decrypted payload byte-for-byte. Temporary
mappings, loop devices, key and files are removed by the exit trap. This
validates unicast Client-to-storage integration and framed artifact transfer,
not live mTLS/network behavior or multicast transport.

This is an opt-in destructive test. It refuses to run without root and its
restore target is constrained to the exact loop partition created by the
script. Do not edit it to point at a physical disk, production volume, or
existing loop device. A successful run is evidence for this host/kernel/
cryptsetup combination only; record the OS, kernel, cryptsetup version and
commit SHA with the result. It does not replace hardware acceptance or test
LUKS2-on-LV, opened-mapping restore, key rotation, or remote deployment.

## Cleanup

After recording results, remove the guests and isolated network:

~~~bash
for vm in feclora-pxe-uefi feclora-pxe-bios feclora-pxe-server; do
  sudo virsh destroy "$vm" 2>/dev/null || true
  sudo virsh undefine "$vm" --nvram --remove-all-storage 2>/dev/null || true
done
sudo virsh net-destroy feclora-pxe-lab
sudo virsh net-undefine feclora-pxe-lab
~~~
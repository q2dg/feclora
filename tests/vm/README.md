# PXE and Server/Client VM lab

This lab creates an isolated libvirt network with no libvirt DHCP service. Feclora Server must be the only DHCP/PXE authority on this test segment. Do not attach this network to a production bridge or a physical LAN.

The harness creates one Feclora Server VM and two PXE clients (legacy BIOS and UEFI). It does not claim an automated end-to-end deployment: the Server UI, client local-disk confirmation, TLS enrollment and storage operation still require operator interaction until the image data plane and unattended VM orchestrator are complete.

## Host requirements

On a Fedora test host install qemu-kvm, libvirt, virt-install, virt-viewer, edk2-ovmf and qemu-img; start the libvirt daemon and verify that KVM/OVMF are usable. Fedora documents virt-install and PXE guest boot support: https://developer.fedoraproject.org/tools/virtualization/installing-libvirt-and-virt-install-on-fedora-linux.html

## Run

~~~bash
sudo tests/vm/run-pxe-matrix.sh /path/to/feclora-live.iso
~~~

The script creates a private libvirt network named feclora-pxe-lab and three guests. Connect to their consoles with virt-viewer or virsh console. The host-side bridge is normally virbr-feclora with 192.0.2.1/24; configure the Server guest's test NIC as a static address such as 192.0.2.2/24. Do not configure a gateway or forward this test network.

In the Server guest:
1. Select the test NIC in Feclora Server mode.
2. Choose isolated DHCP and a small pool such as 192.0.2.100-192.0.2.150.
3. Type the exact authoritative-DHCP confirmation shown by Feclora.
4. Start PXE services; confirm dnsmasq, Caddy and firewalld are active.
5. Boot both client VMs from the network. Confirm BIOS loads undionly.kpxe and UEFI loads ipxe-snponly-x86_64.efi, then iPXE fetches the Feclora kernel, initramfs and squashfs over HTTP.

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

Do not mark the final three items complete until the authenticated artifact data plane is integrated and the tests have actually run. VM PXE boot success alone does not prove a deployment or restore succeeded.

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
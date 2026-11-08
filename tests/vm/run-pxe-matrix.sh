#!/usr/bin/env bash
set -Eeuo pipefail

ISO=${1:-}
if [[ -z "$ISO" || ! -f "$ISO" ]]; then
  echo "Usage: sudo bash $0 /path/to/feclora-live.iso" >&2
  exit 2
fi
if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo (libvirt system network and VM creation required)." >&2
  exit 1
fi
for command in virsh virt-install; do
  command -v "$command" >/dev/null || { echo "Missing host command: $command" >&2; exit 1; }
done
[[ -r /usr/share/OVMF/OVMF_CODE.fd || -r /usr/share/edk2/ovmf/OVMF_CODE.fd ]] || {
  echo "UEFI firmware (edk2-ovmf) was not found." >&2
  exit 1
}
ISO=$(readlink -f "$ISO")
LAB_DIR=${FECLORA_VM_DIR:-/var/lib/libvirt/images/feclora-pxe-lab}
mkdir -p "$LAB_DIR"
chmod 0750 "$LAB_DIR"
NETWORK=feclora-pxe-lab
created_network=0
created_vms=()

cleanup_on_error() {
  local status=$?
  if (( status != 0 )); then
    for vm in "${created_vms[@]}"; do
      virsh destroy "$vm" >/dev/null 2>&1 || true
      virsh undefine "$vm" --nvram --remove-all-storage >/dev/null 2>&1 || true
    done
    if (( created_network )); then
      virsh net-destroy "$NETWORK" >/dev/null 2>&1 || true
      virsh net-undefine "$NETWORK" >/dev/null 2>&1 || true
    fi
  fi
  exit "$status"
}
trap cleanup_on_error EXIT

if virsh net-info "$NETWORK" >/dev/null 2>&1; then
  echo "Network $NETWORK already exists; refusing to reuse unknown configuration." >&2
  exit 1
fi
cat > "$LAB_DIR/$NETWORK.xml" <<'XML'
<network>
  <name>feclora-pxe-lab</name>
  <forward mode='none'/>
  <bridge name='virbr-feclora' stp='on' delay='0'/>
  <ip address='192.0.2.1' netmask='255.255.255.0'/>
</network>
XML
virsh net-define "$LAB_DIR/$NETWORK.xml"
created_network=1
virsh net-start "$NETWORK"

create_vm() {
  local name=$1 disk=$2
  shift 2
  if virsh dominfo "$name" >/dev/null 2>&1; then
    echo "VM $name already exists; refusing to overwrite it." >&2
    return 1
  fi
  if ! virt-install --connect qemu:///system --name "$name" \
    --memory 4096 --vcpus 2 \
    --disk "path=$disk,size=24,format=qcow2,bus=virtio" \
    --network "network=$NETWORK,model=virtio" \
    --graphics none --console pty,target_type=serial \
    --noautoconsole --wait 0 "$@"; then
    virsh destroy "$name" >/dev/null 2>&1 || true
    virsh undefine "$name" --nvram --remove-all-storage >/dev/null 2>&1 || true
    return 1
  fi
  created_vms+=("$name")
}

create_vm feclora-pxe-server "$LAB_DIR/server.qcow2" \
  --cdrom "$ISO" --osinfo detect=on,require=off

create_vm feclora-pxe-bios "$LAB_DIR/client-bios.qcow2" \
  --pxe --osinfo detect=on,require=off

create_vm feclora-pxe-uefi "$LAB_DIR/client-uefi.qcow2" \
  --pxe --boot uefi --osinfo detect=on,require=off

# virt-install starts guests immediately. Keep PXE clients powered off until
# the operator has configured and started Feclora Server DHCP/PXE services.
virsh destroy feclora-pxe-bios >/dev/null 2>&1 || true
virsh destroy feclora-pxe-uefi >/dev/null 2>&1 || true

trap - EXIT
cat <<EOF
VM lab created successfully (VM creation only; no PXE boot test has run).

Network: $NETWORK (isolated, no libvirt DHCP)
Server VM: feclora-pxe-server
BIOS client: feclora-pxe-bios
UEFI client: feclora-pxe-uefi
VM disks: $LAB_DIR

Connect with:
  virsh console feclora-pxe-server
  virsh console feclora-pxe-bios
  virsh console feclora-pxe-uefi

Configure the Server VM NIC with a static 192.0.2.2/24 address and use only
this isolated network for authoritative DHCP testing. See tests/vm/README.md.
EOF
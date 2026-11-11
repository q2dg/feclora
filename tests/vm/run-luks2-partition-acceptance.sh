#!/usr/bin/env bash
set -euo pipefail

# Destructive acceptance test, restricted to disposable loop-backed partitions.
# Never replace these loop devices with physical disks or production paths.
if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash tests/vm/run-luks2-partition-acceptance.sh" >&2
  exit 1
fi

for command in cryptsetup losetup sfdisk lsblk dd fuser python3; do
  command -v "$command" >/dev/null || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/var/tmp}/feclora-luks2-acceptance.XXXXXX")"
SOURCE_LOOP=""
TARGET_LOOP=""
SOURCE_MAPPING="feclora-luks2-source-$$"
TARGET_MAPPING="feclora-luks2-target-$$"

cleanup() {
  cryptsetup close "$TARGET_MAPPING" 2>/dev/null || true
  cryptsetup close "$SOURCE_MAPPING" 2>/dev/null || true
  if [[ -n "$TARGET_LOOP" ]]; then losetup -d "$TARGET_LOOP" 2>/dev/null || true; fi
  if [[ -n "$SOURCE_LOOP" ]]; then losetup -d "$SOURCE_LOOP" 2>/dev/null || true; fi
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT INT TERM

SOURCE_DISK="$WORK_DIR/source-disk.img"
TARGET_DISK="$WORK_DIR/target-disk.img"
KEY_FILE="$WORK_DIR/test.key"
WRONG_KEY_FILE="$WORK_DIR/wrong-test.key"
EXPECTED="$WORK_DIR/expected-plaintext.bin"
REPOSITORY="$WORK_DIR/image-repository"
mkdir -m 700 "$REPOSITORY"
printf 'Feclora disposable LUKS2 acceptance key\n' > "$KEY_FILE"
chmod 600 "$KEY_FILE"
printf 'deliberately incorrect acceptance key\n' > "$WRONG_KEY_FILE"
chmod 600 "$WRONG_KEY_FILE"

# Two sparse, equal-size virtual disks with one equal-size 128 MiB partition.
for disk in "$SOURCE_DISK" "$TARGET_DISK"; do
  truncate -s 160M "$disk"
  sfdisk "$disk" >/dev/null <<'PARTITION_TABLE'
label: dos
unit: sectors

start=2048, size=262144, type=83
PARTITION_TABLE
done

SOURCE_LOOP="$(losetup --find --show --partscan "$SOURCE_DISK")"
TARGET_LOOP="$(losetup --find --show --partscan "$TARGET_DISK")"
SOURCE_PART="${SOURCE_LOOP}p1"
TARGET_PART="${TARGET_LOOP}p1"
for _ in {1..20}; do
  [[ -b "$SOURCE_PART" && -b "$TARGET_PART" ]] && break
  sleep 0.1
done
[[ -b "$SOURCE_PART" && -b "$TARGET_PART" ]] || {
  echo "Kernel did not expose the disposable loop partitions." >&2
  exit 1
}

cryptsetup luksFormat --batch-mode --type luks2 --pbkdf-memory 65536 --key-file "$KEY_FILE" "$SOURCE_PART"
SOURCE_UUID="$(cryptsetup luksUUID "$SOURCE_PART")"
cryptsetup open --key-file "$KEY_FILE" "$SOURCE_PART" "$SOURCE_MAPPING"

# Write non-trivial plaintext through the mapping and retain an exact oracle.
dd if=/dev/urandom of="/dev/mapper/$SOURCE_MAPPING" bs=1M count=4 conv=fsync status=none
dd if="/dev/mapper/$SOURCE_MAPPING" of="$EXPECTED" bs=1M count=4 iflag=fullblock status=none
cryptsetup close "$SOURCE_MAPPING"

# Build the real Feclora partition manifest around the captured raw container.
python3 - "$REPOSITORY" "$SOURCE_PART" "$TARGET_PART" "$SOURCE_UUID" "$EXPECTED" <<'PY'
import hashlib
import json
import os
import shutil
import stat
import json
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.control import LocalTargetApproval
from feclora.deployment.job import DeploymentJob

repository, source, target, luks_uuid, _expected_path = sys.argv[1:]
repo = Path(repository)
artifact_name = "luks2-acceptance.img"
artifact_path = repo / artifact_name
with artifact_path.open("wb") as output:
    subprocess.run(
        ["dd", f"if={source}", "bs=4M", "iflag=fullblock", "status=none"],
        check=True, stdout=output,
    )
digest_state = hashlib.sha256()
with artifact_path.open("rb") as artifact_stream:
    for chunk in iter(lambda: artifact_stream.read(1024 * 1024), b""):
        digest_state.update(chunk)
digest = digest_state.hexdigest()
size = artifact_path.stat().st_size
manifest = {
    "schema_version": 1,
    "image_id": "luks2-acceptance",
    "image_type": "partition",
    "source_size_bytes": size,
    "logical_sector_size": 512,
    "partition_table": "none",
    "artifacts": [{
        "filename": artifact_name,
        "role": "partition-image",
        "format": "raw",
        "compression": "none",
        "size_bytes": size,
        "sha256": digest,
        "partition_id": "loop-source1",
    }],
    "storage": {
        "schema_version": 1,
        "capture_scope": "encrypted_container_bytes",
        "source_layer": "luks2_container",
        "luks_uuid": luks_uuid,
        "dependencies": [{
            "kind": "luks2_metadata",
            "identity": luks_uuid,
            "included_in_source_bytes": True,
        }],
    },
}
manifest_path = repo / "luks2-acceptance.manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

# Exercise the real unicast Client runtime and its locally approved
# partition target. Only the network artifact receiver is replaced: it returns
# this locally generated manifest, while restore_partition performs real I/O.
job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
job = DeploymentJob.from_dict({
    "schema_version": 1,
    "job_id": job_id,
    "operation": "restore",
    "image_id": "luks2-acceptance",
    "target_type": "partition",
    "authorized_clients": ["52:54:00:12:34:56"],
    "network_interface": "lo",
    "transport": "unicast",
    "multicast_group": None,
    "multicast_port": None,
    "start_policy": "manual",
    "expected_clients": None,
    "start_deadline": None,
})
server_identity = "URI:feclora-acceptance-server"
approval = LocalTargetApproval(
    target, "Disposable LUKS2 loop partition",
    f"ERASE {target} FROM {server_identity}",
)
offer = {
    "type": "transfer_offer",
    "job_id": job_id,
    "image_id": "luks2-acceptance",
}
encoded_offer = json.dumps(offer, separators=(",", ":")).encode("ascii")

class FakeTLS:
    def __init__(self):
        self.incoming = bytearray(struct.pack("!I", len(encoded_offer)) + encoded_offer)

    def settimeout(self, _timeout):
        pass

    def recv(self, count):
        chunk = bytes(self.incoming[:count])
        del self.incoming[:count]
        return chunk

tls = FakeTLS()
with patch(
    "feclora.deployment.client_runtime.receive_image_set",
    return_value=str(manifest_path),
):
    success, detail = execute_client_image_job(
        job, tls, approval,
        server_identity=server_identity,
        repository=repo,
        trusted_server_public_key=None,
        executables={
            "lsblk": shutil.which("lsblk"),
            "dd": shutil.which("dd"),
            "cryptsetup": shutil.which("cryptsetup"),
        },
    )
if not success:
    raise RuntimeError(f"unicast Client runtime reported failure: {detail}")
print(f"Unicast Client runtime: {detail}")
print(f"Restored LUKS2 UUID: {luks_uuid}")
print(f"Raw container bytes restored and read back: {size}")
PY

# The decisive check: the original key must unlock the restored ciphertext,
# and the plaintext bytes must match exactly.
if cryptsetup open --test-passphrase --key-file "$WRONG_KEY_FILE" "$TARGET_PART" >/dev/null 2>&1; then
  echo "FAIL: restored LUKS2 container accepted an incorrect key." >&2
  exit 1
fi
cryptsetup open --key-file "$KEY_FILE" "$TARGET_PART" "$TARGET_MAPPING"
dd if="/dev/mapper/$TARGET_MAPPING" of="$WORK_DIR/restored-plaintext.bin" bs=1M count=4 iflag=fullblock status=none
cmp -- "$EXPECTED" "$WORK_DIR/restored-plaintext.bin"
cryptsetup close "$TARGET_MAPPING"
TARGET_UUID="$(cryptsetup luksUUID "$TARGET_PART")"
[[ "$TARGET_UUID" == "$SOURCE_UUID" ]]

echo "PASS: restored LUKS2 container unlocks with the original key."
echo "PASS: restored plaintext payload matches byte-for-byte."
echo "PASS: source and restored LUKS2 UUIDs match ($SOURCE_UUID)."

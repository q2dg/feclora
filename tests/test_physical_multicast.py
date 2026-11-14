import hashlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.network.physical_multicast import (
    PhysicalMulticastError,
    assert_device_identity_unchanged,
    build_physical_device_record,
    open_approved_block_device,
    block_device_stream_callbacks,
    validate_physical_multicast_pair,
    write_and_verify_stream,
    validate_physical_multicast_cohort,
)


def device(path, major_minor, *, read_only, size=8192, logical=512, physical=4096,
           mounts=None, holders=None, backs_system=False, busy=False):
    return {
        "path": path, "major_minor": major_minor, "sysfs_path": f"/sys/devices/{major_minor}",
        "wwn": f"wwn-{major_minor}", "serial": f"serial-{major_minor}",
        "size_bytes": size, "logical_sector_size": logical,
        "physical_sector_size": physical, "read_only": read_only,
        "mountpoints": mounts or [], "holders": holders or [],
        "backs_system": backs_system, "busy": busy,
    }


class PhysicalMulticastPreflightTests(unittest.TestCase):
    def setUp(self):
        self.source = device("/dev/sda", "8:0", read_only=True, size=4096)
        self.target = device("/dev/sdb", "8:16", read_only=False, size=8192)

    def test_builds_kernel_identity_and_safe_use_record_from_sysfs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "devices" / "pci" / "block" / "sda"
            (target / "queue").mkdir(parents=True)
            (target / "holders").mkdir()
            (target / "queue" / "physical_block_size").write_text("4096", encoding="ascii")
            dev = root / "dev" / "block"
            dev.mkdir(parents=True)
            (dev / "8:0").symlink_to(target)
            item = {
                "path": "/dev/sda", "major_minor": "8:0", "wwn": "wwn-1",
                "serial": "serial-1", "size_bytes": 8192,
                "logical_sector_size": 512, "read_only": True,
                "mountpoints": [], "children": [],
            }
            record = build_physical_device_record(item, sysfs_root=temporary)
            self.assertEqual(record["physical_sector_size"], 4096)
            self.assertEqual(record["major_minor"], "8:0")
            self.assertEqual(record["holders"], [])
            self.assertFalse(record["busy"])
            self.assertFalse(record["backs_system"])

    def test_physical_identity_builder_marks_mounted_descendant_busy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "devices" / "pci" / "block" / "sda"
            (target / "queue").mkdir(parents=True)
            (target / "holders").mkdir()
            (target / "queue" / "physical_block_size").write_text("4096", encoding="ascii")
            dev = root / "dev" / "block"
            dev.mkdir(parents=True)
            (dev / "8:0").symlink_to(target)
            partition = root / "devices" / "pci" / "block" / "sda" / "sda1"
            (partition / "holders").mkdir(parents=True)
            (dev / "8:1").symlink_to(partition)
            item = {
                "path": "/dev/sda", "major_minor": "8:0", "wwn": "wwn-1",
                "serial": "serial-1", "size_bytes": 8192,
                "logical_sector_size": 512, "read_only": True,
                "mountpoints": [], "children": [{
                    "major_minor": "8:1", "mountpoints": ["/"], "children": [],
                }],
            }
            record = build_physical_device_record(item, sysfs_root=temporary)
            self.assertTrue(record["busy"])
            self.assertTrue(record["backs_system"])

    def test_physical_identity_builder_fails_closed_when_sysfs_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            item = {
                "path": "/dev/sda", "major_minor": "8:0", "wwn": "wwn-1",
                "serial": "serial-1", "size_bytes": 8192,
                "logical_sector_size": 512, "read_only": True,
                "mountpoints": [], "children": [],
            }
            with self.assertRaisesRegex(PhysicalMulticastError, "sysfs identity"):
                build_physical_device_record(item, sysfs_root=temporary)

    def test_source_descriptor_is_opened_read_only_and_verified_as_block_device(self):
        info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))
        with patch("feclora.network.physical_multicast.os.open", return_value=41) as open_device, \
             patch("feclora.network.physical_multicast.os.fstat", return_value=info), patch("feclora.network.physical_multicast.os.path.exists", return_value=True), patch("feclora.network.physical_multicast.os.path.realpath", return_value=self.source["sysfs_path"]):
            descriptor = open_approved_block_device(
                self.source, self.source, role="Server source",
            )
        self.assertEqual(descriptor, 41)
        self.assertEqual(open_device.call_args.args[0], "/dev/sda")
        flags = open_device.call_args.args[1]
        self.assertFalse(flags & os.O_WRONLY)
        self.assertFalse(flags & os.O_RDWR)
        self.assertFalse(flags & os.O_EXCL)

    def test_destination_descriptor_uses_kernel_exclusive_open(self):
        info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 16))
        with patch("feclora.network.physical_multicast.os.open", return_value=42) as open_device, \
             patch("feclora.network.physical_multicast.os.fstat", return_value=info), patch("feclora.network.physical_multicast.os.path.exists", return_value=True), patch("feclora.network.physical_multicast.os.path.realpath", return_value=self.target["sysfs_path"]):
            descriptor = open_approved_block_device(
                self.target, self.target, role="Client destination",
            )
        self.assertEqual(descriptor, 42)
        flags = open_device.call_args.args[1]
        self.assertTrue(flags & os.O_RDWR)
        self.assertTrue(flags & os.O_EXCL)

    def test_descriptor_open_rejects_device_path_reuse_and_closes_fd(self):
        info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 32))
        with patch("feclora.network.physical_multicast.os.open", return_value=43), \
             patch("feclora.network.physical_multicast.os.fstat", return_value=info), \
             patch("feclora.network.physical_multicast.os.close") as close_fd:
            with self.assertRaisesRegex(PhysicalMulticastError, "identity changed"):
                open_approved_block_device(self.source, self.source, role="Server source")
        close_fd.assert_called_once_with(43)

    def test_block_device_callbacks_use_positional_io_and_flush(self):
        stored = bytearray()
        def pwrite(fd, view, offset):
            payload = bytes(view[:37])
            stored[offset:offset + len(payload)] = payload
            return len(payload)
        def pread(fd, count, offset):
            return bytes(stored[offset:offset + count])
        with patch("feclora.network.physical_multicast.os.pwrite", side_effect=pwrite), \
             patch("feclora.network.physical_multicast.os.pread", side_effect=pread), \
             patch("feclora.network.physical_multicast.os.fsync") as fsync:
            write, flush, readback = block_device_stream_callbacks(9)
            payload = memoryview(b"positional block stream")
            offset = 0
            while offset < len(payload):
                offset += write(payload[offset:])
            flush()
            self.assertEqual(readback(len(payload)), bytes(payload))
        fsync.assert_called_once_with(9)

    def test_accepts_distinct_read_only_source_and_safe_larger_target(self):
        source, target = validate_physical_multicast_pair(self.source, self.target)
        self.assertEqual(source["path"], "/dev/sda")
        self.assertEqual(target["path"], "/dev/sdb")

    def test_rejects_identical_device_path(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "same device path"):
            validate_physical_multicast_pair(self.source, {**self.target, "path": self.source["path"]})

    def test_rejects_major_minor_alias_even_when_paths_differ(self):
        alias = {**self.target, "major_minor": self.source["major_minor"]}
        with self.assertRaisesRegex(PhysicalMulticastError, "major/minor"):
            validate_physical_multicast_pair(self.source, alias)

    def test_rejects_multipath_aliases_with_same_wwn_or_serial(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "WWN"):
            validate_physical_multicast_pair(self.source, {**self.target, "wwn": self.source["wwn"]})
        with self.assertRaisesRegex(PhysicalMulticastError, "serial"):
            validate_physical_multicast_pair(self.source, {**self.target, "serial": self.source["serial"]})

    def test_rejects_source_not_read_only_and_target_read_only(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "read-only"):
            validate_physical_multicast_pair({**self.source, "read_only": False}, self.target)
        with self.assertRaisesRegex(PhysicalMulticastError, "writable"):
            validate_physical_multicast_pair(self.source, {**self.target, "read_only": True})

    def test_rejects_mounted_busy_system_backed_and_held_devices(self):
        for changes in ({"mountpoints": ["/"]}, {"holders": ["dm-0"]},
                        {"backs_system": True}, {"busy": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(PhysicalMulticastError):
                    validate_physical_multicast_pair(self.source, {**self.target, **changes})

    def test_rejects_capacity_and_sector_mismatch(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "smaller"):
            validate_physical_multicast_pair(self.source, {**self.target, "size_bytes": 1024})
        with self.assertRaisesRegex(PhysicalMulticastError, "logical sector"):
            validate_physical_multicast_pair(self.source, {**self.target, "logical_sector_size": 4096})

    def test_revalidation_detects_reused_device_path(self):
        approved = self.target
        current = {**approved, "serial": "replacement-disk"}
        with self.assertRaisesRegex(PhysicalMulticastError, "serial"):
            assert_device_identity_unchanged(approved, current, role="Client destination")


class PhysicalMulticastStreamTests(unittest.TestCase):
    def run_stream(self, payload, *, max_write=None, altered_readback=False):
        stored = bytearray()
        read_offset = 0
        def write(view):
            count = min(len(view), max_write or len(view))
            stored.extend(view[:count])
            return count
        def readback(count):
            nonlocal read_offset
            data = bytes(stored[read_offset:read_offset + count])
            read_offset += len(data)
            if altered_readback and read_offset >= len(stored):
                return data[:-1] + bytes([data[-1] ^ 1]) if data else data
            return data
        flushed = []
        result = write_and_verify_stream(
            io.BytesIO(payload), write, lambda: flushed.append(True), readback,
            expected_bytes=len(payload), chunk_size=4096,
        )
        return result, stored, flushed

    def test_reports_write_and_readback_progress_separately(self):
        payload = b"progress-bytes" * 400
        stored = bytearray()
        read_offset = 0
        progress = []
        def readback(count):
            nonlocal read_offset
            chunk = bytes(stored[read_offset:read_offset + count])
            read_offset += len(chunk)
            return chunk
        result = write_and_verify_stream(
            io.BytesIO(payload),
            lambda view: stored.extend(view) or len(view),
            lambda: None, readback,
            expected_bytes=len(payload), chunk_size=4096,
            progress_callback=lambda phase, done, total: progress.append((phase, done, total)),
        )
        self.assertTrue(result["verified"])
        self.assertEqual({item[0] for item in progress}, {"write", "verify"})
        self.assertEqual(progress[-1][1:], (len(payload), len(payload)))

    def test_handles_short_writes_flushes_and_verifies_readback(self):
        payload = b"feclora-physical-multicast" * 300
        result, stored, flushed = self.run_stream(payload, max_write=113)
        self.assertEqual(bytes(stored), payload)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["readback_sha256"], result["sha256"])
        self.assertEqual(flushed, [True])

    def test_cancellation_stops_before_next_destination_write(self):
        checks = iter((False, True))
        writes = []
        with self.assertRaisesRegex(PhysicalMulticastError, "cancelled"):
            write_and_verify_stream(
                io.BytesIO(b"x" * 8192),
                lambda view: writes.append(bytes(view)) or len(view),
                lambda: None, lambda count: b"x" * count,
                expected_bytes=8192, chunk_size=4096,
                cancel_check=lambda: next(checks),
            )
        self.assertEqual(len(writes), 1)

    def test_cancellation_stops_during_readback(self):
        checks = iter((False, False, True))
        with self.assertRaisesRegex(PhysicalMulticastError, "read-back"):
            write_and_verify_stream(
                io.BytesIO(b"x" * 8192), lambda view: len(view),
                lambda: None, lambda count: b"x" * count,
                expected_bytes=8192, chunk_size=4096,
                cancel_check=lambda: next(checks),
            )

    def test_rejects_early_stream_eof(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "ended early"):
            write_and_verify_stream(io.BytesIO(b"short"), lambda view: len(view),
                                     lambda: None, lambda count: b"x" * count,
                                     expected_bytes=10, chunk_size=4096)

    def test_rejects_zero_length_write(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "zero-length"):
            write_and_verify_stream(io.BytesIO(b"payload"), lambda view: 0,
                                     lambda: None, lambda count: b"x" * count,
                                     expected_bytes=7, chunk_size=4096)

    def test_rejects_readback_digest_mismatch(self):
        payload = b"verify-this"
        stored = bytearray(payload)
        def readback(count):
            return bytes([stored.pop(0) ^ 1]) + bytes(stored[:count - 1])
        with self.assertRaisesRegex(PhysicalMulticastError, "SHA-256"):
            write_and_verify_stream(io.BytesIO(payload), lambda view: len(view),
                                     lambda: None, readback,
                                     expected_bytes=len(payload), chunk_size=4096)


class PhysicalMulticastCohortTests(unittest.TestCase):
    def setUp(self):
        self.source = device("/dev/sda", "8:0", read_only=True, size=4096)
        self.first = device("/dev/sdb", "8:16", read_only=False, size=8192)
        self.second = device("/dev/sdc", "8:32", read_only=False, size=8192)
        self.macs = ("52:54:00:12:34:5a", "52:54:00:12:34:5b")

    def validate(self, **changes):
        values = {
            "source_approved": self.source,
            "source_current": self.source,
            "expected_clients": self.macs,
            "client_states": {mac: "ready" for mac in self.macs},
            "approved_destinations": {
                self.macs[0]: self.first, self.macs[1]: self.second,
            },
            "current_destinations": {
                self.macs[0]: self.first, self.macs[1]: self.second,
            },
        }
        values.update(changes)
        return validate_physical_multicast_cohort(**values)

    def test_complete_ready_cohort_returns_each_independently_approved_destination(self):
        result = self.validate()
        self.assertEqual(tuple(mac for mac, _target in result), tuple(sorted(self.macs)))
        self.assertEqual(
            {target["path"] for _mac, target in result},
            {"/dev/sdb", "/dev/sdc"},
        )

    def test_no_client_may_be_missing_or_not_ready(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "present"):
            self.validate(client_states={self.macs[0]: "ready"})
        with self.assertRaisesRegex(PhysicalMulticastError, "READY"):
            self.validate(client_states={
                self.macs[0]: "ready", self.macs[1]: "running",
            })

    def test_every_selected_client_must_have_its_own_approved_destination(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "independently approve"):
            self.validate(approved_destinations={self.macs[0]: self.first})
        with self.assertRaisesRegex(PhysicalMulticastError, "duplicate Client MACs"):
            self.validate(client_states={
                self.macs[0].upper(): "ready", self.macs[0]: "ready",
            })

    def test_rejects_destination_alias_and_identity_drift_before_returning_cohort(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "major/minor"):
            self.validate(approved_destinations={
                self.macs[0]: self.first,
                self.macs[1]: {**self.second, "major_minor": self.source["major_minor"]},
            }, current_destinations={
                self.macs[0]: self.first,
                self.macs[1]: {**self.second, "major_minor": self.source["major_minor"]},
            })
        with self.assertRaisesRegex(PhysicalMulticastError, "changed after approval"):
            self.validate(current_destinations={
                self.macs[0]: self.first,
                self.macs[1]: {**self.second, "serial": "replacement"},
            })

    def test_rejects_source_identity_drift_before_returning_cohort(self):
        with self.assertRaisesRegex(PhysicalMulticastError, "Server source identity"):
            self.validate(source_current={**self.source, "serial": "replacement"})




if __name__ == "__main__":
    unittest.main()

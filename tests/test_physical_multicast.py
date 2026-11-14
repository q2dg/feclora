import hashlib
import io
import unittest

from feclora.network.physical_multicast import (
    PhysicalMulticastError,
    assert_device_identity_unchanged,
    validate_physical_multicast_pair,
    write_and_verify_stream,
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

    def test_handles_short_writes_flushes_and_verifies_readback(self):
        payload = b"feclora-physical-multicast" * 300
        result, stored, flushed = self.run_stream(payload, max_write=113)
        self.assertEqual(bytes(stored), payload)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["readback_sha256"], result["sha256"])
        self.assertEqual(flushed, [True])

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


if __name__ == "__main__":
    unittest.main()

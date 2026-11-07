import unittest
from types import SimpleNamespace

from feclora.storage.disk_clone import DiskCloneError, clone_disk


class FakeProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.terminated = False
    def wait(self):
        return self.returncode
    def poll(self):
        return -15 if self.terminated else self.returncode
    def terminate(self):
        self.terminated = True


class DiskCloneTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.safety = []
        self.started = []
        self.sizes = {"/dev/source": "100000 disk 512 0\n", "/dev/target": "120000 disk 512 0\n"}
    def runner(self, command, **kwargs):
        self.commands.append(command)
        return SimpleNamespace(stdout=self.sizes[command[-1]])
    def clone(self, **kwargs):
        return clone_disk(
            "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
            executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
            device_validator=lambda _path: True, runner=self.runner,
            device_safety_check=lambda path: self.safety.append(path),
            effective_uid=lambda: 0,
            popen_factory=lambda argv, **opts: self.started.append((argv, opts)) or FakeProcess(),
            **kwargs,
        )
    def test_direct_clone_uses_exact_source_byte_count(self):
        copied = self.clone()
        self.assertEqual(copied, 100000)
        argv = self.started[0][0]
        self.assertIn("if=/dev/source", argv)
        self.assertIn("of=/dev/target", argv)
        self.assertIn("count=100000", argv)
        self.assertIn("iflag=count_bytes", argv)
        self.assertIn("conv=fsync", argv)
        self.assertEqual(self.safety, ["/dev/source", "/dev/target"] * 2)
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(DiskCloneError, "confirmation"):
            clone_disk("/dev/source", "/dev/target", confirmation="yes",
                       device_validator=lambda _path: True)
        self.assertEqual(self.started, [])
    def test_rejects_same_path(self):
        with self.assertRaisesRegex(DiskCloneError, "different"):
            clone_disk("/dev/source", "/dev/source", confirmation="ERASE /dev/source",
                       device_validator=lambda _path: True)
    def test_rejects_small_target_before_starting_dd(self):
        self.sizes["/dev/target"] = "99999 disk 512 0\n"
        with self.assertRaisesRegex(DiskCloneError, "smaller"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_rejects_different_logical_sector_size(self):
        self.sizes["/dev/target"] = "120000 disk 4096 0\n"
        with self.assertRaisesRegex(DiskCloneError, "sector"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_allows_read_only_source(self):
        self.sizes["/dev/source"] = "100000 disk 512 1\\n"
        self.assertEqual(self.clone(), 100000)
    def test_rejects_read_only_target(self):
        self.sizes["/dev/target"] = "120000 disk 512 1\n"
        with self.assertRaisesRegex(DiskCloneError, "read-only"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_rejects_unsafe_target(self):
        def safety(path):
            if path == "/dev/target":
                from feclora.storage.source_safety import SourceSafetyError
                raise SourceSafetyError("busy")
        with self.assertRaisesRegex(DiskCloneError, "unsafe"):
            clone_disk(
                "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
                executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                device_validator=lambda _path: True, runner=self.runner,
                device_safety_check=safety, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )


if __name__ == "__main__":
    unittest.main()

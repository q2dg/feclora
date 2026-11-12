import io
import json
import unittest
from types import SimpleNamespace

from feclora.storage.disk_clone import DiskCloneCancelled, DiskCloneError, clone_disk


class FakeProcess:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = io.BytesIO(stderr)
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
        self.backing = {"/dev/source": "/dev/source", "/dev/target": "/dev/target"}
        self.sizes = {"/dev/source": self.geometry(100000, 512, False, "dos"), "/dev/target": self.geometry(120000, 512, False, "dos")}
    def geometry(self, size, sector, read_only, pttype):
        return json.dumps({"blockdevices": [{"size": size, "type": "disk", "log-sec": sector, "ro": read_only, "pttype": pttype}]})
    def runner(self, command, **kwargs):
        self.commands.append(command)
        if command[0].endswith("sgdisk"):
            return SimpleNamespace(stdout="")
        if "--inverse" in command:
            path = command[-1]
            return SimpleNamespace(stdout=json.dumps({"blockdevices": [{"path": self.backing[path], "type": "disk"}]}))
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
    def test_reports_dd_progress(self):
        progress = []
        proc = FakeProcess(stderr=b"50000 bytes copied, 1.0 s, 50 kB/s\r100000 bytes copied, 2.0 s, 50 kB/s\r")
        clone_disk(
            "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
            executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
            device_validator=lambda _path: True, runner=self.runner,
            device_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda *a, **k: proc,
            progress_callback=lambda done, total, detail: progress.append((done, total)),
        )
        self.assertEqual(progress, [(50000, 100000), (100000, 100000)])
    def test_progress_callback_value_error_is_not_treated_as_malformed_dd_output(self):
        proc = FakeProcess(stderr=b"50000 bytes copied\\r")
        with self.assertRaisesRegex(ValueError, "callback failed"):
            clone_disk(
                "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
                executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                device_validator=lambda _path: True, runner=self.runner,
                device_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: proc,
                progress_callback=lambda *_args: (_ for _ in ()).throw(ValueError("callback failed")),
            )
        self.assertTrue(proc.terminated)
    def test_progress_dialog_closure_cancels_dd(self):
        proc = FakeProcess(returncode=None, stderr=b"50000 bytes copied\r")
        with self.assertRaises(DiskCloneCancelled):
            clone_disk(
                "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
                executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                device_validator=lambda _path: True, runner=self.runner,
                device_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: proc,
                progress_callback=lambda *_args: (_ for _ in ()).throw(BrokenPipeError()),
            )
        self.assertTrue(proc.terminated)
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(DiskCloneError, "confirmation"):
            clone_disk("/dev/source", "/dev/target", confirmation="yes",
                       device_validator=lambda _path: True)
        self.assertEqual(self.started, [])
    def test_rejects_same_path(self):
        with self.assertRaisesRegex(DiskCloneError, "different"):
            clone_disk("/dev/source", "/dev/source", confirmation="ERASE /dev/source",
                       device_validator=lambda _path: True)
    def test_rejects_shared_physical_backing_disk(self):
        self.backing["/dev/target"] = "/dev/source"
        with self.assertRaisesRegex(DiskCloneError, "share"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_rejects_small_target_before_starting_dd(self):
        self.sizes["/dev/target"] = self.geometry(99999, 512, False, "dos")
        with self.assertRaisesRegex(DiskCloneError, "smaller"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_rejects_different_logical_sector_size(self):
        self.sizes["/dev/target"] = self.geometry(120000, 4096, False, "dos")
        with self.assertRaisesRegex(DiskCloneError, "sector"):
            self.clone()
        self.assertEqual(self.started, [])
    def test_allows_read_only_source(self):
        self.sizes["/dev/source"] = self.geometry(100000, 512, True, "dos")
        self.assertEqual(self.clone(), 100000)
    def test_relocates_backup_gpt_header_on_larger_target(self):
        self.sizes["/dev/source"] = self.geometry(100000, 512, False, "gpt")
        self.sizes["/dev/target"] = self.geometry(120000, 512, False, "gpt")
        self.commands = []
        self.clone_with_sgdisk()
        self.assertIn(["/usr/sbin/sgdisk", "-e", "/dev/target"], self.commands)
    def clone_with_sgdisk(self):
        return clone_disk(
            "/dev/source", "/dev/target", confirmation="ERASE /dev/target",
            executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd", "sgdisk": "/usr/sbin/sgdisk"},
            device_validator=lambda _path: True, runner=self.runner,
            device_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda argv, **opts: self.started.append((argv, opts)) or FakeProcess(),
        )
    def test_rejects_read_only_target(self):
        self.sizes["/dev/target"] = self.geometry(120000, 512, True, "dos")
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

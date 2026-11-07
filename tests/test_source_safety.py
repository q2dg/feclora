import json
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe


class SourceSafetyTests(unittest.TestCase):
    def runner_for(self, tree):
        def runner(command, **kwargs):
            if command[0] == "fuser":
                return subprocess.CompletedProcess(command, 1, "", "")
            return subprocess.CompletedProcess(command, 0, json.dumps(tree), "")
        return runner

    def test_rejects_mounted_partition(self):
        tree = {"blockdevices": [{"path": "/dev/sda1", "type": "part", "mountpoints": ["/data"]}]}
        with self.assertRaisesRegex(SourceSafetyError, "mounted"):
            check_capture_source_safe(
                "/dev/sda1", runner=self.runner_for(tree), which=lambda name: name,
                root_disk_resolver=lambda **kwargs: {"/dev/nvme0n1"},
                swaps_path="/dev/null", stat_device=lambda _path: SimpleNamespace(st_mode=0), effective_uid=lambda: 0,
            )

    def test_rejects_live_root_backing_disk(self):
        tree = {"blockdevices": [{"path": "/dev/sda", "type": "disk", "mountpoints": [],
                                  "children": [{"path": "/dev/sda1", "type": "part", "mountpoints": []}]}]}
        with self.assertRaisesRegex(SourceSafetyError, "live system root"):
            check_capture_source_safe(
                "/dev/sda1", runner=self.runner_for(tree), which=lambda name: name,
                root_disk_resolver=lambda **kwargs: {"/dev/sda"},
                swaps_path="/dev/null", stat_device=lambda _path: SimpleNamespace(st_mode=0), effective_uid=lambda: 0,
            )

    def test_rejects_unverifiable_root_protection(self):
        tree = {"blockdevices": [{"path": "/dev/sdb1", "type": "part", "mountpoints": []}]}
        def fail(**kwargs):
            raise RuntimeError("findmnt failed")
        with self.assertRaisesRegex(SourceSafetyError, "live root"):
            check_capture_source_safe(
                "/dev/sdb1", runner=self.runner_for(tree), which=lambda name: name,
                root_disk_resolver=fail, swaps_path="/dev/null",
                stat_device=lambda _path: SimpleNamespace(st_mode=0), effective_uid=lambda: 0,
            )

    def test_rejects_active_swap_partition(self):
        tree = {"blockdevices": [{"path": "/dev/sdb1", "type": "part", "mountpoints": []}]}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as swaps:
            swaps.write("Filename Type Size Used Priority\n/dev/sdb1 partition 1000 0 -2\n")
            swaps.flush()
            with self.assertRaisesRegex(SourceSafetyError, "active swap"):
                check_capture_source_safe(
                    "/dev/sdb1", runner=self.runner_for(tree), which=lambda name: name,
                    root_disk_resolver=lambda **kwargs: {"/dev/sda"},
                    swaps_path=swaps.name, stat_device=lambda _path: SimpleNamespace(st_mode=0),
                    effective_uid=lambda: 0,
                )

    def test_rejects_busy_device(self):
        tree = {"blockdevices": [{"path": "/dev/sdb1", "type": "part", "mountpoints": []}]}
        def runner(command, **kwargs):
            if command[0] == "fuser":
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, json.dumps(tree), "")
        with self.assertRaisesRegex(SourceSafetyError, "open by a process"):
            check_capture_source_safe(
                "/dev/sdb1", runner=runner, which=lambda name: name,
                root_disk_resolver=lambda **kwargs: {"/dev/sda"},
                swaps_path="/dev/null", stat_device=lambda _path: SimpleNamespace(st_mode=0), effective_uid=lambda: 0,
            )

    def test_non_root_checks_sudo_and_runs_fuser_privileged(self):
        tree = {"blockdevices": [{"path": "/dev/sdb1", "type": "part", "mountpoints": []}]}
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            if command[:3] == ["sudo", "-n", "true"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:3] == ["sudo", "-n", "--"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            return subprocess.CompletedProcess(command, 0, json.dumps(tree), "")
        check_capture_source_safe(
            "/dev/sdb1", runner=runner, which=lambda name: name,
            root_disk_resolver=lambda **kwargs: {"/dev/sda"},
            swaps_path="/dev/null", stat_device=lambda _path: SimpleNamespace(st_mode=0),
            effective_uid=lambda: 1000,
        )
        self.assertIn(["sudo", "-n", "--", "fuser", "-s", "/dev/sdb1"], commands)

    def test_requires_safety_utilities(self):
        with self.assertRaisesRegex(SourceSafetyError, "lsblk and fuser"):
            check_capture_source_safe("/dev/sda1", which=lambda name: name if name == "lsblk" else None)


if __name__ == "__main__":
    unittest.main()

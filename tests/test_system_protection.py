import json
import subprocess
import unittest

from feclora.storage.system_protection import (
    SystemProtectionError,
    collect_root_backing_disks,
)


class RootBackingDiskTests(unittest.TestCase):
    def test_resolves_mapper_root_to_backing_physical_disk(self):
        responses = [
            {"filesystems": [{"source": "/dev/mapper/vg-root"}]},
            {"blockdevices": [{
                "path": "/dev/sda", "type": "disk", "children": [{
                    "path": "/dev/mapper/vg-root", "type": "lvm"
                }]
            }]},
        ]
        commands = []
        def runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(responses.pop(0)), "")
        result = collect_root_backing_disks(runner, lambda name: f"/usr/bin/{name}")
        self.assertEqual(result, {"/dev/sda"})
        self.assertIn("--inverse", commands[1])
        self.assertEqual(commands[1][-1], "/dev/mapper/vg-root")

    def test_fails_closed_for_non_block_root_source(self):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"filesystems": [{"source": "overlay"}]}), ""
            )
        with self.assertRaisesRegex(SystemProtectionError, "not a resolvable"):
            collect_root_backing_disks(runner, lambda name: name)

    def test_fails_closed_when_no_backing_disk_is_found(self):
        responses = [
            {"filesystems": [{"source": "/dev/dm-0"}]},
            {"blockdevices": [{"path": "/dev/dm-0", "type": "lvm"}]},
        ]
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps(responses.pop(0)), "")
        with self.assertRaisesRegex(SystemProtectionError, "Could not resolve"):
            collect_root_backing_disks(runner, lambda name: name)

    def test_requires_both_utilities(self):
        with self.assertRaisesRegex(SystemProtectionError, "required"):
            collect_root_backing_disks(which=lambda name: None)


if __name__ == "__main__":
    unittest.main()

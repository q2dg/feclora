import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from feclora.storage.stratis_inventory import collect_stratis_topology
from feclora.storage.stratis_cli_inventory import parse_filesystem_list, parse_pool_list


POOL_TABLE = (
    "Name     Total/Used/Free                 Properties   UUID                                   Alerts\n"
    "poolA    100 GiB / 20 GiB / 80 GiB       -Ca,-Cr,Op   e22772c2-afe9-446c-9be5-2f78f682284e   -\n"
)
FILESYSTEM_TABLE = (
    "Pool     Filesystem   Total/Used/Free/Limit                 Created   Device                       UUID\n"
    "poolA    fs1          1 TiB / 2 GiB / 1022 GiB / None       today     /dev/stratis/poolA/fs1      223265f5-8f17-4cc2-bf12-c3e9e71ff7bf\n"
)


class StratisInventoryTests(unittest.TestCase):
    def test_parses_pool_capacity_uuid_and_alerts(self):
        result = parse_pool_list(POOL_TABLE)
        self.assertEqual(result["poolA"]["free_physical_bytes"], 80 * 1024**3)
        self.assertFalse(result["poolA"]["alerts_reported"])
        self.assertEqual(result["poolA"]["status"], "unknown")
        self.assertEqual(result["poolA"]["uuid"], "e22772c2-afe9-446c-9be5-2f78f682284e")

    def test_parses_filesystem_logical_capacity_and_identity(self):
        result = parse_filesystem_list(FILESYSTEM_TABLE)
        filesystem = result[("poolA", "fs1")]
        self.assertEqual(filesystem["logical_size_bytes"], 1024**4)
        self.assertEqual(filesystem["used_bytes"], 2 * 1024**3)
        self.assertEqual(filesystem["device"], "/dev/stratis/poolA/fs1")

    def test_pool_without_alerts_is_not_claimed_healthy(self):
        result = parse_pool_list(POOL_TABLE)
        self.assertFalse(result["poolA"]["alerts_reported"])
        self.assertEqual(result["poolA"]["status"], "unknown")

    def test_missing_pool_metadata_keeps_inventory_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stratis"
            pool = root / "poolA"
            pool.mkdir(parents=True)
            sysfs = Path(tmp) / "sys" / "class" / "block"
            (sysfs / "dm-3" / "slaves").mkdir(parents=True)
            (sysfs / "dm-3" / "slaves" / "sda1").symlink_to(sysfs / "sda1")
            (sysfs / "sda1").mkdir()
            os.symlink("/dev/dm-3", pool / "fs1")

            def runner(command, **kwargs):
                return Mock(stdout="" if command[1] == "pool" else FILESYSTEM_TABLE)

            result = collect_stratis_topology(
                str(root), str(sysfs), which=lambda _: "/usr/bin/stratis", runner=runner,
            )
            self.assertEqual(result["status"], "metadata_incomplete")

    def test_empty_active_pool_inventory_is_not_reported_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stratis"
            root.mkdir()
            result = collect_stratis_topology(
                str(root), tmp, which=lambda _: "/usr/bin/stratis",
                runner=lambda command, **kwargs: Mock(stdout=POOL_TABLE if command[1] == "pool" else ""),
            )
            self.assertEqual(result["status"], "metadata_incomplete")

    def test_unparseable_capacity_is_unknown_not_zero(self):
        result = parse_pool_list(
            "Name     Total/Used/Free    Properties   UUID                                   Alerts\n"
            "poolA    unknown            -Ca,-Cr,Op    e22772c2-afe9-446c-9be5-2f78f682284e   -\n"
        )
        self.assertIsNone(result["poolA"]["free_physical_bytes"])
        self.assertEqual(result["poolA"]["status"], "unknown")

    def test_discovers_pool_filesystems_and_recursive_backing_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dev" / "stratis"
            sysfs = Path(tmp) / "sys" / "class" / "block"
            (root / "poolA").mkdir(parents=True)
            (sysfs / "dm-3" / "slaves").mkdir(parents=True)
            (sysfs / "dm-3" / "slaves" / "dm-2").symlink_to(sysfs / "dm-2")
            (sysfs / "dm-2" / "slaves").mkdir(parents=True)
            (sysfs / "dm-2" / "slaves" / "sda1").symlink_to(sysfs / "sda1")
            (sysfs / "sda1").mkdir()
            os.symlink("/dev/dm-3", root / "poolA" / "fs1")

            def runner(command, **kwargs):
                if command[1] == "pool":
                    return Mock(stdout=POOL_TABLE)
                return Mock(stdout=FILESYSTEM_TABLE)

            result = collect_stratis_topology(
                str(root), str(sysfs), which=lambda _: "/usr/bin/stratis", runner=runner,
            )
            self.assertEqual(result["status"], "available")
            pool = result["pools"][0]
            self.assertEqual(pool["name"], "poolA")
            self.assertEqual(pool["uuid"], "e22772c2-afe9-446c-9be5-2f78f682284e")
            filesystem = pool["filesystems"][0]
            self.assertEqual(filesystem["name"], "fs1")
            self.assertEqual(filesystem["uuid"], "223265f5-8f17-4cc2-bf12-c3e9e71ff7bf")
            self.assertEqual(filesystem["backing_block_devices"], ["sda1"])
            self.assertEqual(filesystem["backing_device_paths"], ["/dev/sda1"])

    def test_missing_stratis_device_root_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_stratis_topology(str(Path(tmp) / "missing"), tmp)
            self.assertEqual(result, {"status": "unavailable", "pools": []})

    def test_missing_stratis_cli_reports_metadata_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stratis"
            root.mkdir()
            result = collect_stratis_topology(str(root), tmp, which=lambda _: None)
            self.assertEqual(result, {"status": "metadata_unavailable", "pools": []})


if __name__ == "__main__":
    unittest.main()

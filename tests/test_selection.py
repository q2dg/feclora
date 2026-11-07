import unittest

from feclora.storage.selection import SelectionError, validate_clone_selection


def disk(path, size, *, read_only=False, children=None):
    return {
        "path": path, "type": "disk", "size_bytes": size,
        "read_only": read_only, "mountpoints": [], "children": children or [],
    }


def part(path, mountpoints=None):
    return {
        "path": path, "type": "part", "size_bytes": 100,
        "read_only": False, "mountpoints": mountpoints or [], "children": [],
    }


class CloneSelectionTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {"devices": [
            disk("/dev/sda", 1000),
            disk("/dev/sdb", 1200),
            disk("/dev/sdc", 2000, children=[part("/dev/sdc1", ["/"])]),
        ]}

    def validate(self, source, target, protected_disk_paths=None):
        return validate_clone_selection(
            self.inventory, source, target,
            protected_disk_paths=set() if protected_disk_paths is None else protected_disk_paths,
        )

    def test_accepts_distinct_unmounted_disks_with_sufficient_capacity(self):
        selection = self.validate("/dev/sda", "/dev/sdb")
        self.assertEqual(selection.source_path, "/dev/sda")
        self.assertEqual(selection.target_path, "/dev/sdb")
        self.assertEqual(selection.source_size_bytes, 1000)

    def test_rejects_same_disk(self):
        with self.assertRaisesRegex(SelectionError, "different"):
            self.validate("/dev/sda", "/dev/sda")

    def test_rejects_partition_selection(self):
        with self.assertRaisesRegex(SelectionError, "Whole-disk"):
            self.validate("/dev/sdc1", "/dev/sdb")

    def test_rejects_mounted_target_descendant(self):
        self.inventory["devices"][1]["children"] = [part("/dev/sdb1", ["/mnt/data"])]
        with self.assertRaisesRegex(SelectionError, "Target disk has mounted"):
            self.validate("/dev/sda", "/dev/sdb")

    def test_rejects_mounted_source_descendant(self):
        self.inventory["devices"][0]["children"] = [part("/dev/sda1", ["/mnt/source"])]
        with self.assertRaisesRegex(SelectionError, "Source disk has mounted"):
            self.validate("/dev/sda", "/dev/sdb")

    def test_rejects_live_root_disk(self):
        with self.assertRaisesRegex(SelectionError, "live system root"):
            self.validate("/dev/sda", "/dev/sdc")

    def test_requires_root_protection_data(self):
        with self.assertRaisesRegex(SelectionError, "protection data is required"):
            validate_clone_selection(self.inventory, "/dev/sda", "/dev/sdb")

    def test_rejects_root_backing_disk_reported_by_independent_probe(self):
        with self.assertRaisesRegex(SelectionError, "backs the live system root"):
            self.validate(
                "/dev/sda", "/dev/sdb", protected_disk_paths={"/dev/sda"}
            )

    def test_rejects_read_only_target(self):
        self.inventory["devices"][1]["read_only"] = True
        with self.assertRaisesRegex(SelectionError, "read-only"):
            self.validate("/dev/sda", "/dev/sdb")

    def test_rejects_insufficient_capacity(self):
        with self.assertRaisesRegex(SelectionError, "too small"):
            self.validate("/dev/sdb", "/dev/sda")

    def test_rejects_missing_or_ambiguous_path(self):
        with self.assertRaisesRegex(SelectionError, "missing or ambiguous"):
            validate_clone_selection(self.inventory, "/dev/missing", "/dev/sdb")
        self.inventory["devices"].append(disk("/dev/sda", 1000))
        with self.assertRaisesRegex(SelectionError, "ambiguous"):
            validate_clone_selection(self.inventory, "/dev/sda", "/dev/sdb")


if __name__ == "__main__":
    unittest.main()

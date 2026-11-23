import unittest

from feclora.storage.btrfs_send_manifest import (
    BtrfsSendManifest, BtrfsSendManifestError,
)


def full_manifest(**changes):
    value = {
        "schema_version": 1,
        "image_id": "root-subvolume",
        "filesystem_uuid": "11111111-1111-1111-1111-111111111111",
        "subvolume_id": 256,
        "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
        "device_count": 2,
        "send_mode": "full",
        "stream_parent_uuid": None,
        "stream_filename": "root-subvolume.btrfs.zst",
        "stream_size_bytes": 8192,
        "stream_sha256": "a" * 64,
        "compression": "zstd",
    }
    value.update(changes)
    return value


class BtrfsSendManifestTests(unittest.TestCase):
    def test_full_stream_round_trips(self):
        manifest = BtrfsSendManifest.from_dict(full_manifest())
        self.assertEqual(BtrfsSendManifest.from_json(manifest.to_json()), manifest)

    def test_incremental_stream_requires_parent_uuid(self):
        value = full_manifest(send_mode="incremental",
                              stream_parent_uuid="33333333-3333-3333-3333-333333333333")
        manifest = BtrfsSendManifest.from_dict(value)
        self.assertEqual(manifest.stream_parent_uuid, "33333333-3333-3333-3333-333333333333")
        for invalid in (None, "not-a-uuid"):
            with self.subTest(parent=invalid):
                with self.assertRaises(BtrfsSendManifestError):
                    BtrfsSendManifest.from_dict({**value, "stream_parent_uuid": invalid})

    def test_full_stream_rejects_parent_uuid(self):
        with self.assertRaisesRegex(BtrfsSendManifestError, "full send"):
            BtrfsSendManifest.from_dict(full_manifest(
                stream_parent_uuid="33333333-3333-3333-3333-333333333333"))

    def test_rejects_invalid_device_count_and_subvolume_id(self):
        for field, invalid in (("device_count", 0), ("device_count", True),
                               ("subvolume_id", 5), ("subvolume_id", False)):
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaises(BtrfsSendManifestError):
                    BtrfsSendManifest.from_dict(full_manifest(**{field: invalid}))

    def test_rejects_path_traversal_and_bad_digest(self):
        for changes in ({"stream_filename": "../payload"},
                        {"stream_filename": "nested/payload"},
                        {"stream_sha256": "A" * 64},
                        {"stream_size_bytes": 0}):
            with self.subTest(changes=changes):
                with self.assertRaises(BtrfsSendManifestError):
                    BtrfsSendManifest.from_dict(full_manifest(**changes))

    def test_rejects_unknown_fields(self):
        with self.assertRaisesRegex(BtrfsSendManifestError, "fields"):
            BtrfsSendManifest.from_dict(full_manifest(command="btrfs receive"))


if __name__ == "__main__":
    unittest.main()

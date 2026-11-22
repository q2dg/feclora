import base64
import json
import stat
import struct
import sys
from types import SimpleNamespace
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage import image_browser


class FakeGuestFS:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.drive_options = None
        self.mounted = None
        self.closed = False

    def add_drive_opts(self, path, **kwargs):
        self.drive_options = (path, kwargs)

    def launch(self):
        pass

    def list_partitions(self):
        return ["/dev/sda1"]

    def list_filesystems(self):
        return {"/dev/sda1": "ext4"}

    def mount_ro(self, device, mountpoint):
        self.mounted = (device, mountpoint)

    def lstat(self, path):
        entries = {
            "/": {"mode": stat.S_IFDIR | 0o755, "size": 0},
            "/docs": {"mode": stat.S_IFDIR | 0o755, "size": 0},
            "/hello.txt": {"mode": stat.S_IFREG | 0o644, "size": 5},
            "/link": {"mode": stat.S_IFLNK | 0o777, "size": 4},
            "/docs/nested.txt": {"mode": stat.S_IFREG | 0o644, "size": 3},
        }
        return entries[path]

    def ls(self, path):
        return ["docs", "hello.txt", "link"] if path == "/" else ["nested.txt"]

    def download(self, path, destination):
        Path(destination).write_bytes(b"hello")

    def shutdown(self):
        pass

    def close(self):
        self.closed = True


class ImageBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = Path(self.temp.name)
        self.manifest_path = self.repository / "image.manifest.json"
        manifest = {
            "schema_version": 1,
            "image_id": "image",
            "image_type": "disk",
            "source_size_bytes": 4096,
            "logical_sector_size": 512,
            "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.raw", "role": "disk-image", "format": "raw",
                 "compression": "none", "size_bytes": 4096, "sha256": "a" * 64},
                {"filename": "table.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1, "sha256": "b" * 64},
            ],
        }
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.image_path = self.repository / "prepared.raw"
        self.image_path.write_bytes(b"image")

    def _browse(self, *, path="/", download=False, session_id=None, expected_partition_selector=None):
        fake = FakeGuestFS()
        module = types.ModuleType("guestfs")
        module.GuestFS = lambda **kwargs: fake
        with patch.dict(sys.modules, {"guestfs": module}), patch(
            "feclora.storage.image_browser._prepare_image",
            return_value=(self.image_path, "raw"),
        ), patch("feclora.storage.image_browser._CACHE_PARENT", self.repository / "cache"):
            result = image_browser.browse_image(
                self.manifest_path, self.repository, 1, path, download=download,
                session_id=session_id, expected_partition_selector=expected_partition_selector,
            )
        return result, fake

    def test_lists_directory_read_only_in_guestfs_appliance(self):
        result, guest = self._browse()
        self.assertEqual(result["filesystem"], "ext4")
        self.assertEqual([item["name"] for item in result["entries"]], ["docs", "hello.txt", "link"])
        self.assertEqual([item["kind"] for item in result["entries"]], ["directory", "file", "symlink"])
        self.assertEqual(guest.drive_options[1]["readonly"], 1)
        self.assertEqual(guest.mounted, ("/dev/sda1", "/"))
        self.assertTrue(guest.closed)

    def test_selects_verified_partition_device_instead_of_assuming_list_order(self):
        result, guest = self._browse(expected_partition_selector="/dev/sda1")
        self.assertEqual(result["partition"], "/dev/sda1")
        self.assertEqual(guest.mounted, ("/dev/sda1", "/"))

    def test_rejects_verified_partition_missing_from_guestfs_inventory(self):
        with self.assertRaisesRegex(image_browser.ImageBrowserError, "does not match"):
            self._browse(expected_partition_selector="/dev/sda2")

    def test_browser_session_is_reused_for_directory_navigation(self):
        first, _ = self._browse()
        second, _ = self._browse(path="/docs", session_id=first["session_id"])
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["path"], "/docs")

    def test_downloads_only_regular_files_and_returns_bounded_content(self):
        result, _ = self._browse(path="/hello.txt", download=True)
        self.assertEqual(base64.b64decode(result["content_base64"]), b"hello")
        self.assertEqual(result["filename"], "hello.txt")

    def test_refuses_symlink_traversal(self):
        with self.assertRaisesRegex(image_browser.ImageBrowserError, "symbolic links"):
            self._browse(path="/link/secret")

    def test_rejects_parent_directory_traversal(self):
        with self.assertRaisesRegex(image_browser.ImageBrowserError, "normalized"):
            image_browser._guest_path("/docs/../etc")

    def test_reuses_cached_decoded_raw_image_without_redecoding(self):
        artifact = SimpleNamespace(
            role="disk-image", format="raw", compression="gzip",
            encryption="none", filename="disk.raw.gz", sha256="a" * 64,
        )
        manifest = SimpleNamespace(artifacts=[artifact], source_size_bytes=4096)
        source = self.repository / artifact.filename
        source.write_bytes(b"compressed")
        cache = self.repository / "session"
        cache.mkdir(mode=0o700)
        staged = cache / "disk.raw"
        staged.write_bytes(b"x" * 4096)
        with patch("feclora.storage.disk_restore._verified_artifact_stream") as verified:
            path, image_format = image_browser._prepare_image(
                manifest, self.repository, cache, None,
            )
        verified.assert_not_called()
        self.assertEqual(path, staged)
        self.assertEqual(image_format, "raw")

    def test_qcow2_header_rejects_backing_file_before_qemu_inspection(self):
        header = bytearray(104)
        header[:4] = b"QFI\xfb"
        struct.pack_into(">I", header, 4, 3)
        struct.pack_into(">Q", header, 8, 104)
        struct.pack_into(">I", header, 16, 12)
        self.image_path.write_bytes(header)
        with self.assertRaisesRegex(image_browser.ImageBrowserError, "external backing"):
            image_browser._qcow2_header_is_self_contained(self.image_path)

    def test_qcow2_header_rejects_external_data_file_feature(self):
        header = bytearray(104)
        header[:4] = b"QFI\xfb"
        struct.pack_into(">I", header, 4, 3)
        struct.pack_into(">Q", header, 72, 0x4)
        self.image_path.write_bytes(header)
        with self.assertRaisesRegex(image_browser.ImageBrowserError, "external data files"):
            image_browser._qcow2_header_is_self_contained(self.image_path)

    def test_qcow2_external_dependencies_are_rejected(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "format": "qcow2", "virtual-size": 4096,
                "backing-filename": "/outside/base.qcow2",
            }),
        )
        with patch("feclora.storage.image_browser.shutil.which", return_value="/usr/bin/qemu-img"), patch(
            "feclora.storage.image_browser.subprocess.run", return_value=completed,
        ):
            with self.assertRaisesRegex(image_browser.ImageBrowserError, "external backing"):
                image_browser._qcow2_info(self.image_path, 4096)


if __name__ == "__main__":
    unittest.main()

import base64
import json
import os
import stat
import sys
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

    def _browse(self, *, path="/", download=False):
        fake = FakeGuestFS()
        module = types.SimpleNamespace(GuestFS=lambda **kwargs: fake)
        with patch.dict(sys.modules, {"guestfs": module}), patch(
            "feclora.storage.image_browser._prepare_image",
            return_value=(self.image_path, "raw"),
        ):
            result = image_browser.browse_image(
                self.manifest_path, self.repository, 1, path, download=download,
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

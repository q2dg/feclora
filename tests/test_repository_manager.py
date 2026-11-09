import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.repository_manager import (
    RemoteRepositoryManager, RepositoryManagerError,
)


class RemoteRepositoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.registry = root / "etc" / "repositories.json"
        self.mount_root = root / "var" / "repositories"
        self.key = root / "id_ed25519"
        self.known_hosts = root / "known_hosts"
        self.key.write_text("private key", encoding="ascii")
        self.known_hosts.write_text("host key", encoding="ascii")
        self.key.chmod(0o600)
        self.known_hosts.chmod(0o644)
        self.calls = []
        def runner(argv, **kwargs):
            self.calls.append(argv)
            if argv[0].endswith("findmnt"):
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        self.runner = runner
        self.manager = RemoteRepositoryManager(
            registry=self.registry, mount_root=self.mount_root,
            runner=runner, which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        self.definition = {
            "provider": "sshfs", "host": "nas.example.net",
            "remote_path": "/images", "username": "backup",
            "credential_file": None, "identity_file": str(self.key),
            "known_hosts_file": str(self.known_hosts), "port": 22,
            "read_only": True,
        }

    def test_add_persists_only_credential_references_and_creates_private_mountpoint(self):
        result = self.manager.add("images", self.definition)
        self.assertEqual(result["mountpoint"], str(self.mount_root / "images"))
        self.assertEqual((self.mount_root / "images").stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.registry.stat().st_mode & 0o777, 0o600)
        content = self.registry.read_text(encoding="utf-8")
        self.assertNotIn("private key", content)
        self.assertIn(str(self.key), content)

    def test_mount_uses_argv_and_requires_verified_mount_state(self):
        self.manager.add("images", self.definition)
        with self.assertRaisesRegex(RepositoryManagerError, "not mounted"):
            self.manager.mount("images")
        self.assertTrue(any(call[0] == "/usr/bin/sshfs" for call in self.calls))

    def test_rejects_unprotected_ssh_private_key(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(RepositoryManagerError, "mode 0600"):
            self.manager.add("images", self.definition)

    def test_add_accepts_webdav_with_root_owned_system_secrets(self):
        secrets = Path(self.temp.name) / "dav-secrets"
        secrets.write_text("https://dav.example.net/images user password\\n", encoding="utf-8")
        secrets.chmod(0o600)
        definition = {**self.definition, "provider": "webdav", "host": "dav.example.net",
                      "remote_path": "/images", "username": None,
                      "credential_file": str(secrets), "identity_file": None,
                      "known_hosts_file": None, "port": None}
        # davfs2 only reads its system secrets path; the manager rejects alternate paths.
        definition["credential_file"] = "/etc/davfs2/secrets"
        with patch("feclora.storage.repository_manager._check_secret_reference"):
            result = self.manager.add("images", definition)
        self.assertEqual(result["provider"], "webdav")

    def test_add_accepts_s3_with_protected_rclone_config(self):
        config = Path(self.temp.name) / "rclone.conf"
        config.write_text("[feclora_s3]\\ntype = s3\\n", encoding="utf-8")
        config.chmod(0o600)
        definition = {**self.definition, "provider": "s3", "host": "s3.example.net",
                      "remote_path": "/bucket/images", "username": None,
                      "credential_file": str(config), "identity_file": None,
                      "known_hosts_file": None, "port": None,
                      "rclone_remote": "feclora_s3"}
        result = self.manager.add("images", definition)
        self.assertEqual(result["provider"], "s3")

    def test_resolve_verifies_webdav_source_and_fuse_type(self):
        definition = {**self.definition, "provider": "webdav", "host": "dav.example.net",
                      "remote_path": "/images", "username": None,
                      "credential_file": "/etc/davfs2/secrets", "identity_file": None,
                      "known_hosts_file": None, "port": None}
        with patch("feclora.storage.repository_manager._check_secret_reference"):
            self.manager.add("dav", definition)
        self.manager._mount_record = lambda _path: (
            "fuse.davfs", "https://dav.example.net/images", "ro,relatime",
        )
        with patch("feclora.storage.repository_manager._check_secret_reference"):
            self.assertEqual(self.manager.resolve("dav"), str(self.mount_root / "dav"))
            self.manager._mount_record = lambda _path: (
                "fuse.davfs", "https://evil.example/other", "ro,relatime",
            )
            with self.assertRaisesRegex(RepositoryManagerError, "does not match"):
                self.manager.resolve("dav")

    def test_resolve_verifies_s3_remote_and_enforces_read_only(self):
        config = Path(self.temp.name) / "rclone.conf"
        config.write_text("[feclora_s3]\\ntype = s3\\n", encoding="utf-8")
        config.chmod(0o600)
        definition = {**self.definition, "provider": "s3", "host": "s3.example.net",
                      "remote_path": "/bucket/images", "username": None,
                      "credential_file": str(config), "identity_file": None,
                      "known_hosts_file": None, "port": None,
                      "rclone_remote": "feclora_s3", "read_only": True}
        self.manager.add("objects", definition)
        self.manager._mount_record = lambda _path: (
            "fuse.rclone", "feclora_s3:bucket/images", "ro,relatime",
        )
        self.assertEqual(self.manager.resolve("objects"), str(self.mount_root / "objects"))
        with self.assertRaisesRegex(RepositoryManagerError, "read-only"):
            self.manager.resolve("objects", write=True)

    def test_remove_refuses_mounted_repository(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        with self.assertRaisesRegex(RepositoryManagerError, "unmount"):
            self.manager.remove("images")

    def test_active_restore_lease_blocks_repository_unmount(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime",
        )
        lease_fd = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active deployment restore"):
                self.manager.unmount("images")
        finally:
            os.close(lease_fd)

    def test_restore_lease_blocks_unmount_through_another_manager_instance(self):
        self.manager.add("images", self.definition)
        other_manager = RemoteRepositoryManager(
            registry=self.registry, mount_root=self.mount_root,
            runner=self.runner, which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        other_manager._is_mounted = lambda _path: True
        lease_fd = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active restore"):
                other_manager.unmount("images")
        finally:
            os.close(lease_fd)

    def test_unknown_repository_cannot_acquire_usage_lease(self):
        with self.assertRaisesRegex(RepositoryManagerError, "unknown repository"):
            self.manager.acquire_usage_lock("missing")

    def test_active_restore_lease_blocks_definition_removal_even_if_mount_disappeared(self):
        self.manager.add("images", self.definition)
        lease_fd = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active deployment restore"):
                self.manager.remove("images")
            self.assertIn("images", self.manager._load())
            self.assertTrue((self.mount_root / "images").is_dir())
        finally:
            os.close(lease_fd)

    def test_registry_rejects_symlink(self):
        self.manager.add("images", self.definition)
        real = self.registry
        link = self.registry.parent / "link.json"
        link.symlink_to(real)
        manager = RemoteRepositoryManager(
            registry=link, mount_root=self.mount_root, runner=self.runner,
            which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        with self.assertRaisesRegex(RepositoryManagerError, "private root-owned"):
            manager.list()



    def test_resolve_requires_expected_sshfs_source_and_access_mode(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime",
        )
        self.assertEqual(self.manager.resolve("images"), str(self.mount_root / "images"))
        with self.assertRaisesRegex(RepositoryManagerError, "read-only"):
            self.manager.resolve("images", write=True)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "attacker@other.example:/other", "ro,relatime",
        )
        with self.assertRaisesRegex(RepositoryManagerError, "does not match"):
            self.manager.resolve("images")


    def test_list_marks_mount_verified_only_when_source_and_type_match(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime",
        )
        item = self.manager.list()[0]
        self.assertTrue(item["mounted"])
        self.assertTrue(item["verified"])
        self.assertIsNone(item["mount_error"])

    def test_list_exposes_unexpected_mount_without_trusting_it(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "nfs4", "attacker.example.net:/other", "ro,relatime",
        )
        item = self.manager.list()[0]
        self.assertTrue(item["mounted"])
        self.assertFalse(item["verified"])
        self.assertIn("does not match", item["mount_error"])

    def test_unmount_refuses_unexpected_filesystem_at_managed_mountpoint(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "nfs4", "other.example.net:/wrong", "ro,relatime",
        )
        with self.assertRaisesRegex(RepositoryManagerError, "does not match"):
            self.manager.unmount("images")
        self.assertFalse(any(call[0].endswith("umount") for call in self.calls))

if __name__ == "__main__":
    unittest.main()

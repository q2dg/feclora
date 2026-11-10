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

    def test_credential_reference_inventory_and_guard(self):
        encrypted_root = self.mount_root / "encrypted"
        encrypted_root.mkdir(parents=True)
        key = encrypted_root / "feclora-nas-ssh-key.cred"
        known_hosts = encrypted_root / "feclora-nas-known-hosts.cred"
        key.write_bytes(b"encrypted-key")
        known_hosts.write_bytes(b"encrypted-known-hosts")
        key.chmod(0o600)
        known_hosts.chmod(0o600)
        self.manager.credential_root = encrypted_root
        self.manager.add("nas", {
            "provider": "sshfs", "host": "nas.example", "remote_path": "/images",
            "username": "backup", "credential_file": None,
            "identity_file": str(key), "known_hosts_file": str(known_hosts),
            "port": 22, "read_only": True,
        })
        self.assertTrue(self.manager.credential_is_referenced(str(key)))
        self.assertFalse(self.manager.credential_is_referenced(str(encrypted_root / "unused.cred")))
        self.assertEqual(len(self.manager.list()[0]["credential_refs"]), 2)

    def test_update_replaces_definition_only_when_unmounted(self):
        self.manager.add("images", self.definition)
        updated = dict(self.definition, host="nas-new.example.net", remote_path="/archive")
        result = self.manager.update("images", updated)
        self.assertEqual(result, {"id": "images", "updated": True, "provider": "sshfs"})
        self.assertEqual(self.manager.list()[0]["host"], "nas-new.example.net")
        self.assertEqual(self.manager.list()[0]["remote_path"], "/archive")

    def test_active_restore_lease_blocks_repository_update(self):
        self.manager.add("images", self.definition)
        lease = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active deployment restore"):
                self.manager.update("images", dict(self.definition, remote_path="/archive"))
        finally:
            os.close(lease)

    def test_update_refuses_mounted_repository(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        with self.assertRaisesRegex(RepositoryManagerError, "unmount the repository"):
            self.manager.update("images", dict(self.definition, remote_path="/archive"))

    def test_check_reports_verified_mount_and_unknown_id(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime",
        )
        self.assertTrue(self.manager.check("images")["verified"])
        with self.assertRaisesRegex(RepositoryManagerError, "unknown repository"):
            self.manager.check("missing")

    def test_active_restore_lease_blocks_repository_mount(self):
        self.manager.add("images", self.definition)
        lease = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active deployment restore"):
                self.manager.mount("images")
        finally:
            os.close(lease)

    def test_mount_uses_argv_and_requires_verified_mount_state(self):
        self.manager.add("images", self.definition)
        with self.assertRaisesRegex(RepositoryManagerError, "not mounted"):
            self.manager.mount("images")
        self.assertTrue(any(call[0] == "/usr/bin/sshfs" for call in self.calls))

    def test_encrypted_ssh_key_and_known_hosts_are_both_bound_to_mount_service(self):
        from feclora.storage.repository_manager import _repository
        encrypted_root = self.mount_root / "encrypted-bindings"
        encrypted_root.mkdir(parents=True)
        key = encrypted_root / "feclora-nas-ssh-key.cred"
        known_hosts = encrypted_root / "feclora-nas-known-hosts.cred"
        key.write_bytes(b"encrypted-key")
        known_hosts.write_bytes(b"encrypted-known-hosts")
        key.chmod(0o600)
        known_hosts.chmod(0o600)
        self.manager.credential_root = encrypted_root
        definition = dict(self.definition)
        definition["identity_file"] = str(key)
        definition["known_hosts_file"] = str(known_hosts)
        repository = _repository("nas", definition, owner_uid=os.getuid())
        inventory = [
            {"id": "nas", "kind": "ssh-key", "name": "feclora-nas-ssh-key", "path": str(key)},
            {"id": "nas", "kind": "known-hosts", "name": "feclora-nas-known-hosts", "path": str(known_hosts)},
        ]
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore.list", return_value=inventory):
            bindings = self.manager._encrypted_credential_bindings(repository)
        self.assertEqual(bindings, [
            ("feclora-nas-ssh-key", str(key)),
            ("feclora-nas-known-hosts", str(known_hosts)),
        ])

    def test_rejects_symlinked_credential_file(self):
        target = Path(self.temp.name) / "real-key"
        target.write_text("private key", encoding="ascii")
        target.chmod(0o600)
        link = Path(self.temp.name) / "linked-key"
        link.symlink_to(target)
        definition = {**self.definition, "identity_file": str(link)}
        with self.assertRaisesRegex(RepositoryManagerError, "unavailable"):
            self.manager.add("images", definition)

    def test_rejects_hard_linked_credential_file(self):
        linked = Path(self.temp.name) / "linked-key"
        os.link(self.key, linked)
        definition = {**self.definition, "identity_file": str(linked)}
        with self.assertRaisesRegex(RepositoryManagerError, "hard links"):
            self.manager.add("images", definition)

    def test_known_hosts_may_be_world_readable_but_not_writable(self):
        self.known_hosts.chmod(0o666)
        with self.assertRaisesRegex(RepositoryManagerError, "not group/other-writable"):
            self.manager.add("images", self.definition)

    def test_rejects_unprotected_ssh_private_key(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(RepositoryManagerError, "mode 0600"):
            self.manager.add("images", self.definition)

    def test_add_rejects_webdav_until_isolated_credentials_exist(self):
        definition = {**self.definition, "provider": "webdav", "host": "dav.example.net",
                      "remote_path": "/images", "username": None,
                      "credential_file": "/etc/davfs2/secrets", "identity_file": None,
                      "known_hosts_file": None, "port": None}
        with self.assertRaisesRegex(RepositoryManagerError, "global davfs2 secrets file is not accepted"):
            self.manager.add("images", definition)

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

    def test_resolve_rejects_webdav_until_isolated_credentials_exist(self):
        definition = {**self.definition, "provider": "webdav", "host": "dav.example.net",
                      "remote_path": "/images", "username": None,
                      "credential_file": "/etc/davfs2/secrets", "identity_file": None,
                      "known_hosts_file": None, "port": None}
        with self.assertRaisesRegex(RepositoryManagerError, "global davfs2 secrets file is not accepted"):
            self.manager.add("dav", definition)

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
            with self.assertRaisesRegex(RepositoryManagerError, "active deployment restore"):
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

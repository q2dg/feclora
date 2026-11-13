import multiprocessing
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.repository_manager import (
    RemoteRepositoryManager, RepositoryManagerError,
)


def _try_exclusive_repository_lock(registry, mount_root, result_queue):
    manager = RemoteRepositoryManager(
        registry=Path(registry), mount_root=Path(mount_root),
        runner=lambda _argv, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
        which=lambda name: "/usr/bin/" + name,
        effective_uid=lambda: 0, owner_uid=os.getuid(),
    )
    try:
        fd = manager._acquire_usage_lock("images", exclusive=True)
    except RepositoryManagerError as exc:
        result_queue.put(("blocked", str(exc)))
    else:
        os.close(fd)
        result_queue.put(("acquired", ""))


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

    def test_concurrent_adds_preserve_both_registry_entries(self):
        definitions = [
            ("images-a", dict(self.definition, host="nas-a.example.net")),
            ("images-b", dict(self.definition, host="nas-b.example.net")),
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda item: self.manager.add(item[0], item[1]), definitions,
            ))
        self.assertEqual({item["id"] for item in results}, {"images-a", "images-b"})
        entries = self.manager._load()
        self.assertEqual(set(entries), {"images-a", "images-b"})
        self.assertEqual(entries["images-a"]["host"], "nas-a.example.net")
        self.assertEqual(entries["images-b"]["host"], "nas-b.example.net")

    def test_registry_lock_rejects_symlink(self):
        lock = self.registry.parent / ".repositories.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        target = Path(self.temp.name) / "attacker-lock"
        target.write_text("", encoding="ascii")
        target.chmod(0o600)
        lock.symlink_to(target)
        with self.assertRaisesRegex(RepositoryManagerError, "cannot open repository registry lock"):
            self.manager.add("images", self.definition)
        self.assertFalse((self.mount_root / "images").exists())

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
            with self.assertRaisesRegex(RepositoryManagerError, "active image operation or deployment job"):
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
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        )
        self.assertTrue(self.manager.check("images")["verified"])
        with self.assertRaisesRegex(RepositoryManagerError, "unknown repository"):
            self.manager.check("missing")


    def test_acquire_usage_lock_rechecks_registry_after_lock_and_releases_on_failure(self):
        self.manager.add("images", self.definition)
        acquired_fds = []
        original_acquire = self.manager._acquire_usage_lock

        def acquire(identifier, *, exclusive):
            fd = original_acquire(identifier, exclusive=exclusive)
            acquired_fds.append(fd)
            return fd

        self.manager._acquire_usage_lock = acquire
        self.manager._load = lambda: {}
        with self.assertRaisesRegex(RepositoryManagerError, "unknown repository ID"):
            self.manager.acquire_usage_lock("images")
        self.assertEqual(len(acquired_fds), 1)
        with self.assertRaises(OSError):
            os.fstat(acquired_fds[0])

    def test_active_restore_lease_blocks_repository_mount(self):
        self.manager.add("images", self.definition)
        lease = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active image operation or deployment job"):
                self.manager.mount("images")
        finally:
            os.close(lease)

    def test_mount_identity_probe_uses_bounded_findmnt_timeout(self):
        captured = {}

        def runner(argv, **kwargs):
            captured["argv"] = argv
            captured.update(kwargs)
            return SimpleNamespace(
                returncode=0,
                stdout=f"{self.mount_root / 'images'} fuse.sshfs backup@nas.example.net:/images ro,relatime,nosuid,nodev,noexec\n",
                stderr="",
            )

        manager = RemoteRepositoryManager(
            registry=self.registry, mount_root=self.mount_root,
            runner=runner, which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        record = manager._mount_record(str(self.mount_root / "images"))
        self.assertEqual(record, (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        ))
        self.assertEqual(captured["timeout"], 5)
        self.assertTrue(captured["argv"][0].endswith("findmnt"))
        self.assertIn("--mountpoint", captured["argv"])

    def test_mount_identity_probe_fails_closed_on_timeout(self):
        def runner(_argv, **_kwargs):
            raise TimeoutError("findmnt timed out")

        manager = RemoteRepositoryManager(
            registry=self.registry, mount_root=self.mount_root,
            runner=runner, which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        with self.assertRaisesRegex(RepositoryManagerError, "cannot verify repository mount state"):
            manager._mount_record(str(self.mount_root / "images"))

    def test_mount_identity_probe_rejects_malformed_findmnt_output(self):
        manager = RemoteRepositoryManager(
            registry=self.registry, mount_root=self.mount_root,
            runner=lambda _argv, **_kwargs: SimpleNamespace(
                returncode=0, stdout="unexpected output\\n", stderr="",
            ),
            which=lambda name: "/usr/bin/" + name,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        with self.assertRaisesRegex(RepositoryManagerError, "unexpected mountpoint record"):
            manager._mount_record(str(self.mount_root / "images"))

    def test_mount_uses_argv_and_requires_verified_mount_state(self):
        self.manager.add("images", self.definition)
        with self.assertRaisesRegex(RepositoryManagerError, "not mounted"):
            self.manager.mount("images")
        self.assertTrue(any(call[0] == "/usr/bin/sshfs" for call in self.calls))

    def test_mount_reports_success_only_after_matching_mount_verification(self):
        self.manager.add("images", self.definition)
        record = ("fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec")
        records = iter([None, record, record])
        self.manager._mount_record = lambda _path: next(records)
        result = self.manager.mount("images")
        self.assertEqual(result, {
            "id": "images", "mounted": True,
            "mountpoint": str(self.mount_root / "images"),
        })

    def test_mount_rejects_wrong_filesystem_even_when_mountpoint_is_occupied(self):
        self.manager.add("images", self.definition)
        records = iter([
            None,
            ("nfs4", "other.example.net:/wrong", "ro,relatime,nosuid,nodev,noexec"),
            ("nfs4", "other.example.net:/wrong", "ro,relatime,nosuid,nodev,noexec"),
        ])
        self.manager._mount_record = lambda _path: next(records)
        with self.assertRaisesRegex(RepositoryManagerError, "source/type/access-mode verification"):
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

    def test_remove_restores_mountpoint_if_registry_commit_fails(self):
        self.manager.add("images", self.definition)
        mountpoint = self.mount_root / "images"
        with patch("feclora.storage.repository_manager._write_registry",
                   side_effect=OSError("simulated registry write failure")):
            with self.assertRaisesRegex(OSError, "simulated registry write failure"):
                self.manager.remove("images")
        self.assertIn("images", self.manager._load())
        self.assertTrue(mountpoint.is_dir())
        self.assertEqual(mountpoint.stat().st_mode & 0o777, 0o700)

    def test_remove_refuses_mounted_repository(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        with self.assertRaisesRegex(RepositoryManagerError, "unmount"):
            self.manager.remove("images")

    def test_active_restore_lease_blocks_repository_unmount(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        )
        lease_fd = self.manager.acquire_usage_lock("images")
        try:
            with self.assertRaisesRegex(RepositoryManagerError, "active image operation or deployment job"):
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
            with self.assertRaisesRegex(RepositoryManagerError, "active image operation or deployment job"):
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
            with self.assertRaisesRegex(RepositoryManagerError, "active image operation or deployment job"):
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
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        )
        self.assertEqual(self.manager.resolve("images"), str(self.mount_root / "images"))
        with self.assertRaisesRegex(RepositoryManagerError, "read-only"):
            self.manager.resolve("images", write=True)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "attacker@other.example:/other", "ro,relatime,nosuid,nodev,noexec",
        )
        with self.assertRaisesRegex(RepositoryManagerError, "does not match"):
            self.manager.resolve("images")


    def test_resolve_rejects_mount_missing_restrictive_safety_options(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev",
        )
        with self.assertRaisesRegex(RepositoryManagerError, "missing restrictive safety options.*noexec"):
            self.manager.resolve("images")

    def test_list_marks_mount_verified_only_when_source_and_type_match(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        )
        item = self.manager.list()[0]
        self.assertTrue(item["mounted"])
        self.assertTrue(item["verified"])
        self.assertIsNone(item["mount_error"])

    def test_list_exposes_unexpected_mount_without_trusting_it(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "nfs4", "attacker.example.net:/other", "ro,relatime,nosuid,nodev,noexec",
        )
        item = self.manager.list()[0]
        self.assertTrue(item["mounted"])
        self.assertFalse(item["verified"])
        self.assertIn("does not match", item["mount_error"])

    def test_unmount_refuses_unexpected_filesystem_at_managed_mountpoint(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "nfs4", "other.example.net:/wrong", "ro,relatime,nosuid,nodev,noexec",
        )
        with self.assertRaisesRegex(RepositoryManagerError, "does not match"):
            self.manager.unmount("images")
        self.assertFalse(any(call[0].endswith("umount") for call in self.calls))

    def test_nfs_unmount_retries_with_force_after_stale_mount_failure(self):
        definition = {
            "provider": "nfs", "host": "nas.example.net",
            "remote_path": "/exports/images", "username": None,
            "credential_file": None, "identity_file": None,
            "known_hosts_file": None, "port": None, "read_only": True,
        }
        self.manager.add("images", definition)
        self.manager._mount_record = lambda _path: (
            "nfs4", "nas.example.net:/exports/images", "ro,relatime,nosuid,nodev,noexec",
        )
        mounted_states = iter([True, True, False])
        self.manager._is_mounted = lambda _path: next(mounted_states)
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[-1] == "feclora-repository-images.service":
                return SimpleNamespace(returncode=3, stdout="", stderr="")
            if argv[0].endswith("umount") and "--force" not in argv:
                return SimpleNamespace(returncode=32, stdout="", stderr="server unavailable")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.manager.runner = runner
        result = self.manager.unmount("images")
        self.assertEqual(result, {"id": "images", "mounted": False})
        umount_calls = [call for call in calls if call[0].endswith("umount")]
        self.assertEqual(len(umount_calls), 2)
        self.assertNotIn("--force", umount_calls[0])
        self.assertIn("--force", umount_calls[1])
        self.assertEqual(umount_calls[1][-1], str(self.mount_root / "images"))

    def test_non_nfs_unmount_does_not_force_detach(self):
        self.manager.add("images", self.definition)
        self.manager._mount_record = lambda _path: (
            "fuse.sshfs", "backup@nas.example.net:/images", "ro,relatime,nosuid,nodev,noexec",
        )
        mounted_states = iter([True, True, True])
        self.manager._is_mounted = lambda _path: next(mounted_states)
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[-1] == "feclora-repository-images.service":
                return SimpleNamespace(returncode=3, stdout="", stderr="")
            if argv[0].endswith("umount"):
                return SimpleNamespace(returncode=32, stdout="", stderr="busy")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.manager.runner = runner
        with self.assertRaisesRegex(RepositoryManagerError, "repository remains mounted"):
            self.manager.unmount("images")
        umount_calls = [call for call in calls if call[0].endswith("umount")]
        self.assertEqual(len(umount_calls), 1)
        self.assertNotIn("--force", umount_calls[0])


    def test_ensure_mounted_returns_shared_lease_without_exclusive_gap(self):
        self.manager.add("images", self.definition)
        self.manager._is_mounted = lambda _path: True
        self.manager.resolve = lambda _identifier, write=False: str(self.mount_root / "images")
        lease_fd, mounted_by_us = self.manager.ensure_mounted_and_acquire_usage_lock("images")
        self.assertFalse(mounted_by_us)
        context = multiprocessing.get_context("fork")
        result_queue = context.Queue()
        try:
            process = context.Process(
                target=_try_exclusive_repository_lock,
                args=(str(self.registry), str(self.mount_root), result_queue),
            )
            process.start()
            process.join(timeout=5)
            self.assertFalse(process.is_alive(), "exclusive lock contender did not terminate")
            self.assertEqual(process.exitcode, 0)
            status, message = result_queue.get(timeout=2)
            self.assertEqual(status, "blocked")
            self.assertIn("active image operation or deployment job", message)
        finally:
            os.close(lease_fd)
            result_queue.close()
            result_queue.join_thread()

    def test_usage_lock_excludes_other_process_and_recovers_after_release(self):
        self.manager.add("images", self.definition)
        context = multiprocessing.get_context("fork")
        result_queue = context.Queue()
        lease_fd = self.manager.acquire_usage_lock("images")
        try:
            process = context.Process(
                target=_try_exclusive_repository_lock,
                args=(str(self.registry), str(self.mount_root), result_queue),
            )
            process.start()
            process.join(timeout=5)
            self.assertFalse(process.is_alive(), "lock contender did not terminate")
            self.assertEqual(process.exitcode, 0)
            status, message = result_queue.get(timeout=2)
            self.assertEqual(status, "blocked")
            self.assertIn("active image operation or deployment job", message)
        finally:
            os.close(lease_fd)

        process = context.Process(
            target=_try_exclusive_repository_lock,
            args=(str(self.registry), str(self.mount_root), result_queue),
        )
        process.start()
        process.join(timeout=5)
        self.assertFalse(process.is_alive(), "lock contender did not terminate after lease release")
        self.assertEqual(process.exitcode, 0)
        status, message = result_queue.get(timeout=2)
        self.assertEqual((status, message), ("acquired", ""))
        result_queue.close()
        result_queue.join_thread()


if __name__ == "__main__":
    unittest.main()

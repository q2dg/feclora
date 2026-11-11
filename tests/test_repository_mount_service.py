import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from feclora.storage.repository import RemoteRepository, RepositoryError
from feclora.storage.repository_mount_service import build_mount_argv
from feclora.storage.repository_manager import RemoteRepositoryManager, RepositoryManagerError


class RepositoryMountServiceTests(unittest.TestCase):
    def test_sshfs_uses_private_systemd_credential_and_stays_foreground(self):
        encrypted = "/etc/credstore.encrypted/feclora/feclora-nas-ssh-key.cred"
        repo = RemoteRepository(
            provider="sshfs", host="nas.example.net", remote_path="/images",
            mountpoint="/var/lib/feclora/repositories/nas", username="backup",
            credential_file=None, identity_file=encrypted,
            known_hosts_file="/etc/feclora/known_hosts", port=22, read_only=True,
        )
        argv = build_mount_argv(
            repo, [("feclora-nas-ssh-key", encrypted)], "/run/credentials/unit",
        )
        self.assertEqual(argv[1], "-f")
        self.assertIn("IdentityFile=/run/credentials/unit/feclora-nas-ssh-key", argv[3])
        self.assertNotIn(encrypted, " ".join(argv))

    def test_ssh_known_hosts_uses_private_systemd_credential(self):
        encrypted = "/etc/credstore.encrypted/feclora/feclora-nas-known-hosts.cred"
        identity = "/etc/credstore.encrypted/feclora/feclora-nas-ssh-key.cred"
        repo = RemoteRepository(
            provider="sshfs", host="nas.example.net", remote_path="/images",
            mountpoint="/var/lib/feclora/repositories/nas", username="backup",
            credential_file=None, identity_file=identity,
            known_hosts_file=encrypted, port=22, read_only=True,
        )
        argv = build_mount_argv(
            repo, [
                ("feclora-nas-ssh-key", identity),
                ("feclora-nas-known-hosts", encrypted),
            ], "/run/credentials/unit",
        )
        self.assertIn("IdentityFile=/run/credentials/unit/feclora-nas-ssh-key", " ".join(argv))
        self.assertIn("UserKnownHostsFile=/run/credentials/unit/feclora-nas-known-hosts", " ".join(argv))
        self.assertNotIn(identity, " ".join(argv))
        self.assertNotIn(encrypted, " ".join(argv))

    def test_smb_credentials_path_is_replaced_in_mount_options(self):
        encrypted = "/etc/credstore.encrypted/feclora/feclora-nas-smb.cred"
        repo = RemoteRepository(
            provider="smb", host="nas.example.net", remote_path="/images",
            mountpoint="/var/lib/feclora/repositories/nas", username="backup",
            credential_file=encrypted, identity_file=None,
            known_hosts_file=None, port=None, read_only=True,
        )
        argv = build_mount_argv(
            repo, [("feclora-nas-smb", encrypted)], "/run/credentials/unit",
        )
        self.assertIn("credentials=/run/credentials/unit/feclora-nas-smb", argv[4])
        self.assertNotIn(encrypted, " ".join(argv))

    def test_unmount_stops_service_owned_fuse_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            credential_root = root / "encrypted"
            credential_root.mkdir(mode=0o700)
            encrypted = credential_root / "feclora-nas-smb.cred"
            encrypted.write_bytes(b"encrypted-payload")
            encrypted.chmod(0o600)
            calls = []

            def runner(argv, **kwargs):
                calls.append(argv)
                if argv[0].endswith("/findmnt"):
                    mountpoint = str(root / "mounts" / "nas")
                    return SimpleNamespace(
                        returncode=0,
                        stdout=f"{mountpoint} cifs //nas.example.net/images ro\n",
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            manager = RemoteRepositoryManager(
                registry=root / "etc" / "repositories.json",
                mount_root=root / "mounts", credential_root=credential_root,
                runner=runner, which=lambda name: "/usr/bin/" + name,
                effective_uid=lambda: 0, owner_uid=os.getuid(),
            )
            manager.add("nas", {
                "provider": "smb", "host": "nas.example.net",
                "remote_path": "/images", "username": "backup",
                "credential_file": str(encrypted), "identity_file": None,
                "known_hosts_file": None, "port": None, "read_only": True,
            })
            manager._mount_record = lambda _path: ("cifs", "//nas.example.net/images", "ro,relatime")
            states = iter([True, False, False])
            manager._is_mounted = lambda _path: next(states)
            result = manager.unmount("nas")
            self.assertFalse(result["mounted"])
            self.assertIn(
                ["/usr/bin/systemctl", "stop", "feclora-repository-nas.service"],
                calls,
            )

    def test_manager_launches_transient_service_with_encrypted_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            credential_root = root / "encrypted"
            credential_root.mkdir(mode=0o700)
            encrypted = credential_root / "feclora-nas-smb.cred"
            encrypted.write_bytes(b"encrypted-payload")
            encrypted.chmod(0o600)
            calls = []

            def runner(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            manager = RemoteRepositoryManager(
                registry=root / "etc" / "repositories.json",
                mount_root=root / "mounts", credential_root=credential_root,
                runner=runner, which=lambda name: "/usr/bin/" + name,
                effective_uid=lambda: 0, owner_uid=os.getuid(),
            )
            definition = {
                "provider": "smb", "host": "nas.example.net",
                "remote_path": "/images", "username": "backup",
                "credential_file": str(encrypted), "identity_file": None,
                "known_hosts_file": None, "port": None, "read_only": True,
            }
            manager.add("nas", definition)
            states = iter([False, True])
            manager._is_mounted = lambda _path: next(states)
            result = manager.mount("nas")
            self.assertTrue(result["mounted"])
            command = next(argv for argv in calls if argv[0].endswith("/systemd-run"))
            self.assertIn("--unit=feclora-repository-nas.service", command)
            self.assertIn(
                f"--property=LoadCredentialEncrypted=feclora-nas-smb:{encrypted}",
                command,
            )
            self.assertIn("feclora.storage.repository_mount_service", command)


    def test_webdav_rejects_encrypted_credentials_until_davfs2_user_config_design(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            encrypted = root / "feclora-webdav-password.cred"
            with self.assertRaisesRegex(RepositoryError, "global davfs2 secrets file is not accepted"):
                RemoteRepository(
                    provider="webdav", host="dav.example.net", remote_path="/images",
                    mountpoint=str(root / "mounts" / "dav"), username="backup",
                    credential_file=str(encrypted), identity_file=None,
                    known_hosts_file=None, port=None, read_only=True,
                )



if __name__ == "__main__":
    unittest.main()

import unittest

from feclora.storage.repository import RemoteRepository, RepositoryError, required_tools


class RemoteRepositoryTests(unittest.TestCase):
    def test_sshfs_uses_identity_file_and_never_inline_secret(self):
        repo = RemoteRepository(
            provider="sshfs", host="images.example.net", remote_path="/backup/feclora",
            mountpoint="/mnt/images", username="backup", identity_file="/etc/feclora/ssh/id_ed25519",
            known_hosts_file="/etc/feclora/ssh/known_hosts",
        )
        argv = repo.mount_argv()
        self.assertEqual(argv[0], "sshfs")
        self.assertIn("IdentityFile=/etc/feclora/ssh/id_ed25519", argv[2])
        self.assertIn("StrictHostKeyChecking=yes", argv[2])
        self.assertIn("UserKnownHostsFile=/etc/feclora/ssh/known_hosts", argv[2])
        self.assertFalse(any("password" in item.lower() for item in argv))

    def test_nfs_uses_hard_mount_and_nfs4(self):
        repo = RemoteRepository(
            provider="nfs", host="nas.example.net", remote_path="/exports/images",
            mountpoint="/mnt/images",
        )
        argv = repo.mount_argv()
        self.assertIn("vers=4.2", argv[4])
        self.assertIn("hard", argv[4])

    def test_all_remote_mounts_disable_setuid_devices_and_execution(self):
        repositories = [
            RemoteRepository(
                provider="sshfs", host="images.example.net", remote_path="/backup",
                mountpoint="/mnt/ssh", username="backup",
                identity_file="/etc/feclora/ssh/id_ed25519",
                known_hosts_file="/etc/feclora/ssh/known_hosts", read_only=True,
            ),
            RemoteRepository(
                provider="nfs", host="nas.example.net", remote_path="/exports/images",
                mountpoint="/mnt/nfs", read_only=True,
            ),
            RemoteRepository(
                provider="smb", host="nas.example.net", remote_path="/images",
                mountpoint="/mnt/smb", credential_file="/etc/feclora/smb.creds", read_only=True,
            ),
        ]
        for repository in repositories:
            with self.subTest(provider=repository.provider):
                options = repository.mount_argv()[
                    2 if repository.provider == "sshfs" else 4
                ]
                self.assertIn("nosuid", options)
                self.assertIn("nodev", options)
                self.assertIn("noexec", options)
                self.assertIn("ro", options)

    def test_smb_requires_credentials_file(self):
        with self.assertRaises(RepositoryError):
            RemoteRepository(
                provider="smb", host="nas.example.net", remote_path="/images",
                mountpoint="/mnt/images",
            )
        repo = RemoteRepository(
            provider="smb", host="nas.example.net", remote_path="/images/feclora",
            mountpoint="/mnt/images", credential_file="/etc/feclora/smb.creds",
        )
        argv = repo.mount_argv()
        self.assertIn("credentials=/etc/feclora/smb.creds", argv[4])
        self.assertIn("prefixpath=feclora", argv[4])
        self.assertEqual(argv[-2], "//nas.example.net/images")

    def test_smb_rejects_comma_in_prefixpath_mount_option_injection(self):
        for remote_path in ("/images/feclora,vers", "/images/archive,ro"):
            with self.subTest(remote_path=remote_path):
                with self.assertRaisesRegex(RepositoryError, "mount-option separators"):
                    RemoteRepository(
                        provider="smb", host="nas.example.net",
                        remote_path=remote_path, mountpoint="/mnt/images",
                        credential_file="/etc/feclora/smb.creds",
                    )

    def test_rejects_shell_metacharacters_and_parent_paths(self):
        with self.assertRaises(RepositoryError):
            RemoteRepository(
                provider="nfs", host="nas.example.net", remote_path="/exports/$(touch x)",
                mountpoint="/mnt/images",
            )
        with self.assertRaises(RepositoryError):
            RemoteRepository(
                provider="nfs", host="nas.example.net", remote_path="/exports/../etc",
                mountpoint="/mnt/images",
            )

    def test_provider_dependencies(self):
        self.assertEqual(required_tools("sshfs"), ("sshfs",))

    def test_s3_uses_object_api_not_filesystem_mount_provider(self):
        with self.assertRaisesRegex(RepositoryError, "provider must be one of"):
            RemoteRepository(
                provider="s3", host="objects.example.net", remote_path="/bucket/images",
                mountpoint="/mnt/images", read_only=True,
            )

    def test_sshfs_rejects_missing_pinned_host_keys(self):
        with self.assertRaises(RepositoryError):
            RemoteRepository(
                provider="sshfs", host="images.example.net", remote_path="/backup",
                mountpoint="/mnt/images", username="backup",
                identity_file="/etc/feclora/ssh/id_ed25519",
            )


if __name__ == "__main__":
    unittest.main()

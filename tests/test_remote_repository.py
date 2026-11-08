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
        self.assertIn("credentials=/etc/feclora/smb.creds", repo.mount_argv()[4])

    def test_webdav_uses_https(self):
        repo = RemoteRepository(
            provider="webdav", host="dav.example.net", remote_path="/images",
            mountpoint="/mnt/images",
        )
        self.assertIn("https://dav.example.net/images", repo.mount_argv())

    def test_s3_uses_rclone_alias_and_vfs_cache(self):
        repo = RemoteRepository(
            provider="s3", host="s3.example.net", remote_path="/bucket/images",
            mountpoint="/mnt/images", rclone_remote="feclora_s3",
        )
        argv = repo.mount_argv()
        self.assertEqual(argv[1:3], ["mount", "feclora_s3:bucket/images"])
        self.assertIn("writes", argv)
        self.assertNotIn("--allow-other", argv)

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
        self.assertEqual(required_tools("s3"), ("rclone",))

    def test_sshfs_rejects_missing_pinned_host_keys(self):
        with self.assertRaises(RepositoryError):
            RemoteRepository(
                provider="sshfs", host="images.example.net", remote_path="/backup",
                mountpoint="/mnt/images", username="backup",
                identity_file="/etc/feclora/ssh/id_ed25519",
            )


if __name__ == "__main__":
    unittest.main()

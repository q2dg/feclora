import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.repository_manager import RemoteRepositoryManager, RepositoryManagerError
from feclora.storage.sftp_transfer_service import (
    build_systemd_transfer_argv, credential_bindings, run_sftp_transfer,
)


class FakeManager:
    credential_root = "/etc/credstore.encrypted/feclora"
    effective_uid = staticmethod(lambda: 0)
    owner_uid = 0
    which = staticmethod(lambda name: f"/usr/bin/{name}")


class SFTPTransferServiceTests(unittest.TestCase):
    def test_systemd_argv_loads_encrypted_credentials_not_plaintext(self):
        bindings = [
            ("feclora-backup-ssh-key", "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"),
            ("feclora-backup-known-hosts", "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"),
        ]
        argv = build_systemd_transfer_argv(
            systemd_run="/usr/bin/systemd-run", python="/usr/bin/python3",
            unit="feclora-sftp-1234567890abcdef1234567890abcdef.service", bindings=bindings,
            operation="download", host="sftp.example.net", username="backup",
            remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
            expected_sha256="a" * 64,
        )
        self.assertIn("--property=LoadCredentialEncrypted=feclora-backup-ssh-key:/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred", argv)
        self.assertIn("--property=LoadCredentialEncrypted=feclora-backup-known-hosts:/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred", argv)
        self.assertIn("--expected-sha256", argv)
        self.assertNotIn("PRIVATE KEY", " ".join(argv))

    def test_rejects_incomplete_or_wrong_credential_bindings(self):
        with self.assertRaises(RepositoryManagerError):
            build_systemd_transfer_argv(
                systemd_run="systemd-run", python="python3",
                unit="feclora-sftp-1234567890abcdef1234567890abcdef.service",
                bindings=[("feclora-backup-ssh-key", "/key")],
                operation="upload", host="sftp.example.net", username="backup",
                remote_path="/images/a", local_path="/tmp/a",
            )

    def test_credential_binding_requires_registered_kind(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"id": "backup", "kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"id": "backup", "kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store):
            bindings = credential_bindings(
                "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                manager=manager,
            )
        self.assertEqual(len(bindings), 2)
        self.assertTrue(bindings[0][0].endswith("-ssh-key"))
        self.assertTrue(bindings[1][0].endswith("-known-hosts"))

    def test_run_transfer_uses_transient_systemd_unit(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store):
            result = run_sftp_transfer(
                identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                operation="upload", host="sftp.example.net", username="backup",
                remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                manager=manager, runner=runner,
            )
        self.assertTrue(result["completed"])
        self.assertIn("--wait", calls[0][0])
        self.assertIn("--pipe", calls[0][0])
        self.assertEqual(calls[0][1]["timeout"], 86430)


    def test_interrupted_wait_stops_the_named_transient_service(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.subprocess.run") as stop:
            with self.assertRaises(KeyboardInterrupt):
                run_sftp_transfer(
                    identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                    known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                    operation="download", host="sftp.example.net", username="backup",
                    remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                    manager=manager, runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
                )
        stop.assert_called_once()
        command = stop.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/systemctl", "stop", "--no-block"])
        self.assertRegex(command[3], r"^feclora-sftp-[a-f0-9]{32}\\.service$")

    def test_unverified_download_mode_is_explicit_and_limited_to_download(self):
        bindings = [
            ("feclora-backup-ssh-key", "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"),
            ("feclora-backup-known-hosts", "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"),
        ]
        argv = build_systemd_transfer_argv(
            systemd_run="/usr/bin/systemd-run", python="/usr/bin/python3",
            unit="feclora-sftp-1234567890abcdef1234567890abcdef.service", bindings=bindings,
            operation="download", host="sftp.example.net", username="backup",
            remote_path="/images/manifest.json", local_path="/var/lib/feclora/stage/manifest.json",
            allow_unverified_metadata=True,
        )
        self.assertIn("--allow-unverified-metadata", argv)
        with self.assertRaises(RepositoryManagerError):
            build_systemd_transfer_argv(
                systemd_run="/usr/bin/systemd-run", python="/usr/bin/python3",
                unit="feclora-sftp-1234567890abcdef1234567890abcdef.service", bindings=bindings,
                operation="upload", host="sftp.example.net", username="backup",
                remote_path="/images/manifest.json", local_path="/var/lib/feclora/stage/manifest.json",
                allow_unverified_metadata=True,
            )


    def test_run_inventory_parses_only_valid_manifest_names_from_service(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        def runner(_argv, **_kwargs):
            return SimpleNamespace(returncode=0, stdout='{"manifests":["manifest.json"]}', stderr="")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store):
            result = run_sftp_transfer(
                identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                operation="inventory", host="sftp.example.net", username="backup",
                remote_path="/images", manager=manager, runner=runner,
            )
        self.assertEqual(result["manifests"], ["manifest.json"])
        self.assertTrue(result["completed"])

    def test_run_inventory_rejects_invalid_service_payload(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        def runner(_argv, **_kwargs):
            return SimpleNamespace(returncode=0, stdout='{"manifests":["../evil.manifest.json"]}', stderr="")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store):
            with self.assertRaisesRegex(RepositoryManagerError, "invalid data"):
                run_sftp_transfer(
                    identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                    known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                    operation="inventory", host="sftp.example.net", username="backup",
                    remote_path="/images", manager=manager, runner=runner,
                )


if __name__ == "__main__":
    unittest.main()

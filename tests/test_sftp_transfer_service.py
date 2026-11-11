import io
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.repository_manager import RemoteRepositoryManager, RepositoryManagerError
from feclora.storage.sftp_transfer_service import (
    _stop_transient_unit, build_systemd_transfer_argv, credential_bindings, run_sftp_transfer,
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


    def test_stop_transient_unit_reports_uncertain_state_when_kill_times_out(self):
        timeout = subprocess.TimeoutExpired(["systemctl", "kill"], 5)
        with patch("feclora.storage.sftp_transfer_service.subprocess.run", side_effect=[
            timeout, timeout,
        ]) as run:
            with self.assertRaisesRegex(RepositoryManagerError, "state is uncertain"):
                _stop_transient_unit("/usr/bin/systemctl", "feclora-sftp-" + "a" * 32 + ".service")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][1], "kill")

    def test_stop_transient_unit_reports_uncertain_state_when_kill_fails(self):
        timeout = __import__("subprocess").TimeoutExpired(["systemctl", "stop"], 20)
        with patch("feclora.storage.sftp_transfer_service.subprocess.run", side_effect=[
            timeout, SimpleNamespace(returncode=1, stdout="", stderr="failed"),
        ]) as run:
            with self.assertRaisesRegex(RepositoryManagerError, "state is uncertain"):
                _stop_transient_unit("/usr/bin/systemctl", "feclora-sftp-" + "b" * 32 + ".service")
        self.assertEqual(run.call_count, 2)

    def test_interrupted_wait_stops_the_named_transient_service(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as stop:
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
        self.assertEqual(command[:2], ["/usr/bin/systemctl", "stop"])
        self.assertRegex(command[2], r"^feclora-sftp-[a-f0-9]{32}\.service$")
        self.assertEqual(stop.call_args.kwargs["timeout"], 20)

    def test_local_operation_sigterm_cancellation_stops_sftp_child_and_propagates(self):
        from feclora.storage.local_operation_service import LocalOperationCancelled

        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        cancellation = LocalOperationCancelled("cancellation requested by operator")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as stop:
            with self.assertRaisesRegex(LocalOperationCancelled, "cancellation requested"):
                run_sftp_transfer(
                    identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                    known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                    operation="download", host="sftp.example.net", username="backup",
                    remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                    expected_sha256="a" * 64, manager=manager,
                    runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(cancellation),
                )
        stop.assert_called_once()
        command = stop.call_args.args[0]
        self.assertEqual(command[:2], ["/usr/bin/systemctl", "stop"])
        self.assertRegex(command[2], r"^feclora-sftp-[a-f0-9]{32}\.service$")

    def test_local_operation_cancellation_is_not_reported_safe_if_sftp_child_stop_is_uncertain(self):
        from feclora.storage.local_operation_service import LocalOperationCancelled

        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        cancellation = LocalOperationCancelled("cancellation requested by operator")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["systemctl", "stop"], 20)):
            with self.assertRaisesRegex(RepositoryManagerError, "state is uncertain"):
                run_sftp_transfer(
                    identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                    known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                    operation="download", host="sftp.example.net", username="backup",
                    remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                    expected_sha256="a" * 64, manager=manager,
                    runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(cancellation),
                )

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

    def test_service_main_runs_inventory_and_emits_manifest_names(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": "/run/credentials/test"}), \
             patch("feclora.storage.sftp_transfer_service._credential_path", side_effect=["/key", "/known_hosts"]), \
             patch("feclora.storage.sftp_transfer_service.list_image_manifests", return_value=["manifest.json"]) as inventory, \
             redirect_stdout(output):
            result = __import__("feclora.storage.sftp_transfer_service", fromlist=["main"]).main([
                "inventory", "--host", "sftp.example.net", "--username", "backup",
                "--remote-path", "/images", "--local-path", "/unused",
                "--identity-credential-name", "feclora-backup-ssh-key",
                "--known-hosts-credential-name", "feclora-backup-known-hosts",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), '{"manifests":["manifest.json"]}')
        inventory.assert_called_once_with(
            "/images", host="sftp.example.net", username="backup",
            identity_file="/key", known_hosts_file="/known_hosts", port=22,
        )

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


    def test_download_retries_transient_transport_failure_with_new_unit(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="Connection timed out")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.time.sleep") as pause:
            result = run_sftp_transfer(
                identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                operation="download", host="sftp.example.net", username="backup",
                remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                expected_sha256="a" * 64, manager=manager, runner=runner,
            )
        self.assertTrue(result["completed"])
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(
            next(arg for arg in calls[0] if arg.startswith("--unit=")),
            next(arg for arg in calls[1] if arg.startswith("--unit=")),
        )
        pause.assert_called_once_with(0.25)

    def test_upload_does_not_retry_ambiguous_publication_failure(self):
        manager = FakeManager()
        fake_store = SimpleNamespace(list=lambda: [
            {"kind": "ssh-key", "name": "feclora-backup-ssh-key",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred"},
            {"kind": "known-hosts", "name": "feclora-backup-known-hosts",
             "path": "/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred"},
        ])
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=1, stdout="", stderr="Connection reset by peer")
        with patch("feclora.storage.systemd_credential_store.SystemdCredentialStore", return_value=fake_store), \
             patch("feclora.storage.sftp_transfer_service.time.sleep") as pause:
            with self.assertRaisesRegex(RepositoryManagerError, "SFTP transfer failed"):
                run_sftp_transfer(
                    identity_credential="/etc/credstore.encrypted/feclora/feclora-backup-ssh-key.cred",
                    known_hosts_credential="/etc/credstore.encrypted/feclora/feclora-backup-known-hosts.cred",
                    operation="upload", host="sftp.example.net", username="backup",
                    remote_path="/images/disk.img", local_path="/var/lib/feclora/stage/disk.img",
                    manager=manager, runner=runner,
                )
        self.assertEqual(len(calls), 1)
        pause.assert_not_called()


if __name__ == "__main__":
    unittest.main()

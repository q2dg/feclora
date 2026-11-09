import os
import tempfile
import tarfile
import json
import hashlib
from pathlib import Path
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.managed_pki import (
    PKIError, certificate_expiry_days, create_client_csr, inspect_client_csr, renew_server_certificate, rotate_server_keypair,
)


class ManagedPKITests(unittest.TestCase):
    def test_csr_requires_one_feclora_uri_san_and_valid_signature(self):
        with tempfile.NamedTemporaryFile() as csr:
            with patch(
                "feclora.deployment.managed_pki._run",
                side_effect=[
                    SimpleNamespace(stdout="Certificate request self-signature verify OK"),
                    SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-client-lab-01\n"),
                ],
            ):
                self.assertEqual(inspect_client_csr(csr.name), "URI:feclora-client-lab-01")

    def test_csr_rejects_multiple_or_non_feclora_sans(self):
        with tempfile.NamedTemporaryFile() as csr:
            with patch(
                "feclora.deployment.managed_pki._run",
                side_effect=[
                    SimpleNamespace(stdout="verified"),
                    SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-client-lab-01, DNS:untrusted.example\n"),
                ],
            ):
                with self.assertRaisesRegex(PKIError, "exactly one"):
                    inspect_client_csr(csr.name)

    def test_client_age_recipient_is_added_and_removed_from_future_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            recipients_file = os.path.join(root, "age-recipients.txt")
            os.mkdir(os.path.join(root, "age-recipients"))
            server_recipient = "age1" + "s" * 40
            client_recipient = "age1" + "c" * 40
            with open(recipients_file, "w", encoding="ascii") as stream:
                stream.write(server_recipient + "\n")
            with (
                patch("feclora.deployment.managed_pki.os.geteuid", return_value=0),
                patch("feclora.deployment.managed_pki._root_only_directory", side_effect=lambda path: os.fspath(path)),
                patch("feclora.deployment.managed_pki._regular_file"),
            ):
                from feclora.deployment.managed_pki import register_age_recipient, remove_age_recipient
                register_age_recipient(root, "URI:feclora-client-lab", client_recipient)
                self.assertTrue(remove_age_recipient(root, "URI:feclora-client-lab"))
            with open(recipients_file, encoding="ascii") as stream:
                self.assertEqual(stream.read(), server_recipient + "\n")
            self.assertFalse(os.path.exists(os.path.join(root, "age-recipients", "lab.txt")))

    def test_age_recipient_registration_rejects_recipient_already_owned_by_another_client(self):
        with tempfile.TemporaryDirectory() as root:
            recipients_file = os.path.join(root, "age-recipients.txt")
            os.mkdir(os.path.join(root, "age-recipients"))
            shared_recipient = "age1" + "c" * 40
            with open(recipients_file, "w", encoding="ascii") as stream:
                stream.write(shared_recipient + "\n")
            with (
                patch("feclora.deployment.managed_pki.os.geteuid", return_value=0),
                patch("feclora.deployment.managed_pki._root_only_directory", side_effect=lambda path: os.fspath(path)),
                patch("feclora.deployment.managed_pki._regular_file"),
            ):
                from feclora.deployment.managed_pki import register_age_recipient
                with self.assertRaisesRegex(PKIError, "must have a unique age identity"):
                    register_age_recipient(root, "URI:feclora-client-another", shared_recipient)
            with open(recipients_file, encoding="ascii") as stream:
                self.assertEqual(stream.read(), shared_recipient + "\n")
            self.assertFalse(os.path.exists(os.path.join(root, "age-recipients", "another.txt")))

    def test_age_recipient_registration_rolls_back_inventory_if_mapping_write_fails(self):
        with tempfile.TemporaryDirectory() as root:
            recipients_file = os.path.join(root, "age-recipients.txt")
            os.mkdir(os.path.join(root, "age-recipients"))
            server_recipient = "age1" + "s" * 40
            client_recipient = "age1" + "c" * 40
            with open(recipients_file, "w", encoding="ascii") as stream:
                stream.write(server_recipient + "\n")
            real_atomic_text = __import__(
                "feclora.deployment.managed_pki", fromlist=["_atomic_text"]
            )._atomic_text
            calls = 0

            def fail_mapping_once(path, content, mode=0o600):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated removable-media/state write failure")
                return real_atomic_text(path, content, mode)

            with (
                patch("feclora.deployment.managed_pki.os.geteuid", return_value=0),
                patch("feclora.deployment.managed_pki._root_only_directory", side_effect=lambda path: os.fspath(path)),
                patch("feclora.deployment.managed_pki._regular_file"),
                patch("feclora.deployment.managed_pki._atomic_text", side_effect=fail_mapping_once),
            ):
                from feclora.deployment.managed_pki import register_age_recipient
                with self.assertRaisesRegex(OSError, "simulated"):
                    register_age_recipient(root, "URI:feclora-client-lab", client_recipient)
            with open(recipients_file, encoding="ascii") as stream:
                self.assertEqual(stream.read(), server_recipient + "\n")
            self.assertFalse(os.path.exists(os.path.join(root, "age-recipients", "lab.txt")))

    def test_server_certificate_renewal_preserves_ca_and_private_key(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {
                "ca.key": os.path.join(root, "ca.key"),
                "ca.crt": os.path.join(root, "ca.crt"),
                "server.key": os.path.join(root, "server.key"),
                "server.crt": os.path.join(root, "server.crt"),
            }
            for name, path in paths.items():
                with open(path, "w", encoding="ascii") as stream:
                    stream.write("existing " + name)
                os.chmod(path, 0o600 if name.endswith(".key") else 0o644)
            original_key = open(paths["server.key"], "rb").read()
            calls = []

            def fake_run(argv, _runner=None):
                calls.append(argv)
                if argv[1:3] == ["x509", "-in"] and argv[-1:] == ["-enddate"]:
                    return SimpleNamespace(stdout="notAfter=Jan  2 00:00:00 2030 GMT")
                if argv[1:3] == ["x509", "-in"] and argv[-3:] == ["-noout", "-ext", "subjectAltName"]:
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-server\n")
                if argv[1:2] == ["req"] and "-out" in argv:
                    output = argv[argv.index("-out") + 1]
                    Path(output).write_text("new CSR", encoding="ascii")
                elif argv[1:3] == ["x509", "-req"]:
                    output = argv[argv.index("-out") + 1]
                    Path(output).write_text("renewed certificate", encoding="ascii")
                elif argv[1:3] == ["x509", "-in"] and "-pubkey" in argv:
                    return SimpleNamespace(stdout="PUBLIC KEY")
                elif argv[1:2] == ["pkey"]:
                    return SimpleNamespace(stdout="PUBLIC KEY")
                elif argv[1:3] == ["x509", "-in"] and "-fingerprint" in argv:
                    return SimpleNamespace(stdout="sha256 Fingerprint=" + "A" * 64)
                return SimpleNamespace(stdout="verified")

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki._regular_file"
            ), patch("feclora.deployment.managed_pki._run", side_effect=fake_run):
                result = renew_server_certificate(root)
            self.assertEqual(Path(paths["server.crt"]).read_text(encoding="ascii"), "renewed certificate")
            self.assertEqual(Path(paths["server.key"]).read_bytes(), original_key)
            self.assertEqual(result["ca_fingerprint"], "a" * 64)
            self.assertTrue(any("-no_check_time" in command for command in calls))

    def test_server_keypair_rotation_replaces_key_and_certificate_but_preserves_ca(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {
                "ca.key": os.path.join(root, "ca.key"),
                "ca.crt": os.path.join(root, "ca.crt"),
                "server.key": os.path.join(root, "server.key"),
                "server.crt": os.path.join(root, "server.crt"),
            }
            for name, path in paths.items():
                Path(path).write_text("old " + name, encoding="ascii")
                os.chmod(path, 0o600 if name.endswith(".key") else 0o644)
            original_ca_key = Path(paths["ca.key"]).read_bytes()
            original_ca_cert = Path(paths["ca.crt"]).read_bytes()
            original_server_key = Path(paths["server.key"]).read_bytes()
            calls = []

            def fake_run(argv, _runner=None):
                calls.append(argv)
                if argv[1:3] == ["x509", "-in"] and argv[-1:] == ["-enddate"]:
                    return SimpleNamespace(stdout="notAfter=Jan  2 00:00:00 2030 GMT")
                if argv[1:3] == ["genpkey", "-algorithm"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new private key", encoding="ascii")
                elif argv[1:3] == ["req", "-new"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new CSR", encoding="ascii")
                elif argv[1:3] == ["x509", "-req"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new certificate", encoding="ascii")
                elif argv[1:3] == ["x509", "-in"] and argv[-3:] == ["-noout", "-ext", "subjectAltName"]:
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\\n    URI:feclora-server\\n")
                elif argv[1:3] == ["x509", "-in"] and "-pubkey" in argv:
                    return SimpleNamespace(stdout="NEW PUBLIC KEY")
                elif argv[1:2] == ["pkey"]:
                    return SimpleNamespace(stdout="NEW PUBLIC KEY")
                elif argv[1:3] == ["x509", "-in"] and "-fingerprint" in argv:
                    return SimpleNamespace(stdout="sha256 Fingerprint=" + "B" * 64)
                return SimpleNamespace(stdout="verified")

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki._regular_file"
            ), patch("feclora.deployment.managed_pki._run", side_effect=fake_run):
                result = rotate_server_keypair(root)
            self.assertEqual(Path(paths["server.key"]).read_text(encoding="ascii"), "new private key")
            self.assertEqual(Path(paths["server.crt"]).read_text(encoding="ascii"), "new certificate")
            self.assertNotEqual(Path(paths["server.key"]).read_bytes(), original_server_key)
            self.assertEqual(Path(paths["ca.key"]).read_bytes(), original_ca_key)
            self.assertEqual(Path(paths["ca.crt"]).read_bytes(), original_ca_cert)
            self.assertEqual(os.stat(paths["server.key"]).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(paths["server.crt"]).st_mode & 0o777, 0o644)
            self.assertEqual(result["ca_fingerprint"], "b" * 64)
            self.assertTrue(result["key_rotated"])
            self.assertTrue(any(command[1:2] == ["genpkey"] for command in calls))

    def test_server_keypair_rotation_rejects_certificate_key_mismatch_before_install(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {
                "ca.key": os.path.join(root, "ca.key"),
                "ca.crt": os.path.join(root, "ca.crt"),
                "server.key": os.path.join(root, "server.key"),
                "server.crt": os.path.join(root, "server.crt"),
            }
            for name, path in paths.items():
                Path(path).write_text("old " + name, encoding="ascii")
                os.chmod(path, 0o600 if name.endswith(".key") else 0o644)
            original_key = Path(paths["server.key"]).read_bytes()
            original_cert = Path(paths["server.crt"]).read_bytes()

            def fake_run(argv, _runner=None):
                if argv[1:3] == ["x509", "-in"] and argv[-1:] == ["-enddate"]:
                    return SimpleNamespace(stdout="notAfter=Jan  2 00:00:00 2030 GMT")
                if argv[1:3] == ["genpkey", "-algorithm"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new private key", encoding="ascii")
                elif argv[1:3] == ["req", "-new"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new CSR", encoding="ascii")
                elif argv[1:3] == ["x509", "-req"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new certificate", encoding="ascii")
                elif argv[1:3] == ["x509", "-in"] and argv[-3:] == ["-noout", "-ext", "subjectAltName"]:
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\\n    URI:feclora-server\\n")
                elif argv[1:3] == ["x509", "-in"] and "-pubkey" in argv:
                    return SimpleNamespace(stdout="CERTIFICATE PUBLIC KEY")
                elif argv[1:2] == ["pkey"]:
                    return SimpleNamespace(stdout="DIFFERENT PRIVATE KEY")
                return SimpleNamespace(stdout="verified")

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki._regular_file"
            ), patch("feclora.deployment.managed_pki._run", side_effect=fake_run):
                with self.assertRaisesRegex(PKIError, "does not match"):
                    rotate_server_keypair(root)
            self.assertEqual(Path(paths["server.key"]).read_bytes(), original_key)
            self.assertEqual(Path(paths["server.crt"]).read_bytes(), original_cert)

    def test_server_keypair_rotation_rolls_back_certificate_if_key_install_fails(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {
                "ca.key": os.path.join(root, "ca.key"),
                "ca.crt": os.path.join(root, "ca.crt"),
                "server.key": os.path.join(root, "server.key"),
                "server.crt": os.path.join(root, "server.crt"),
            }
            for name, path in paths.items():
                Path(path).write_text("old " + name, encoding="ascii")
                os.chmod(path, 0o600 if name.endswith(".key") else 0o644)
            original_key = Path(paths["server.key"]).read_bytes()
            original_cert = Path(paths["server.crt"]).read_bytes()

            def fake_run(argv, _runner=None):
                if argv[1:3] == ["x509", "-in"] and argv[-1:] == ["-enddate"]:
                    return SimpleNamespace(stdout="notAfter=Jan  2 00:00:00 2030 GMT")
                if argv[1:3] == ["genpkey", "-algorithm"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new private key", encoding="ascii")
                elif argv[1:3] == ["req", "-new"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new CSR", encoding="ascii")
                elif argv[1:3] == ["x509", "-req"]:
                    Path(argv[argv.index("-out") + 1]).write_text("new certificate", encoding="ascii")
                elif argv[1:3] == ["x509", "-in"] and argv[-3:] == ["-noout", "-ext", "subjectAltName"]:
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\\n    URI:feclora-server\\n")
                elif argv[1:3] == ["x509", "-in"] and "-pubkey" in argv:
                    return SimpleNamespace(stdout="NEW PUBLIC KEY")
                elif argv[1:2] == ["pkey"]:
                    return SimpleNamespace(stdout="NEW PUBLIC KEY")
                return SimpleNamespace(stdout="verified")

            real_replace = os.replace
            replace_calls = 0

            def fail_second_replace(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("simulated private-key installation failure")
                return real_replace(source, destination)

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki._regular_file"
            ), patch("feclora.deployment.managed_pki._run", side_effect=fake_run), patch(
                "feclora.deployment.managed_pki.os.replace", side_effect=fail_second_replace
            ):
                with self.assertRaisesRegex(OSError, "simulated private-key installation failure"):
                    rotate_server_keypair(root)
            self.assertEqual(Path(paths["server.key"]).read_bytes(), original_key)
            self.assertEqual(Path(paths["server.crt"]).read_bytes(), original_cert)

    def test_encrypted_ca_backup_contains_ca_only_and_never_overwrites(self):
        from feclora.deployment.managed_pki import backup_server_ca

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as export:
            for name, value, mode in (
                ("ca.key", "PRIVATE CA KEY", 0o600),
                ("ca.crt", "PUBLIC CA CERT", 0o644),
            ):
                path = os.path.join(root, name)
                Path(path).write_text(value, encoding="ascii")
                os.chmod(path, mode)
            destination = os.path.join(export, "feclora-ca-backup.tar.age")
            seen = {}

            def fake_run(argv, **kwargs):
                self.assertEqual(argv[1:4], ["-r", "age1" + "a" * 40, "-o"])
                archive = argv[-1]
                with tarfile.open(archive, "r") as bundle:
                    seen["names"] = sorted(bundle.getnames())
                    seen["key"] = bundle.extractfile("ca.key").read()
                    seen["manifest"] = json.load(bundle.extractfile("manifest.json"))
                Path(argv[argv.index("-o") + 1]).write_bytes(b"AGE ENCRYPTED BACKUP")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki.ca_fingerprint", return_value="a" * 64
            ):
                result = backup_server_ca(
                    destination, "age1" + "a" * 40, pki_directory=root,
                    runner=fake_run,
                )
            self.assertEqual(seen["names"], ["ca.crt", "ca.key", "manifest.json"])
            self.assertEqual(seen["key"], b"PRIVATE CA KEY")
            self.assertEqual(seen["manifest"]["ca_sha256_fingerprint"], "a" * 64)
            self.assertEqual(Path(destination).read_bytes(), b"AGE ENCRYPTED BACKUP")
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            self.assertEqual(result["sha256"], hashlib.sha256(b"AGE ENCRYPTED BACKUP").hexdigest())
            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki.ca_fingerprint", return_value="a" * 64
            ):
                with self.assertRaisesRegex(PKIError, "refusing to overwrite"):
                    backup_server_ca(destination, "age1" + "a" * 40, pki_directory=root)

    def test_encrypted_ca_backup_rejects_invalid_age_recipient(self):
        from feclora.deployment.managed_pki import backup_server_ca
        with self.assertRaisesRegex(PKIError, "valid age recipient"):
            backup_server_ca("/tmp/backup.tar.age", "not-a-recipient")

    def test_certificate_expiry_uses_utc_and_returns_negative_when_expired(self):
        with tempfile.NamedTemporaryFile() as certificate:
            with patch(
                "feclora.deployment.managed_pki._run",
                return_value=SimpleNamespace(stdout="notAfter=Jan  2 00:00:00 2030 GMT"),
            ):
                days = certificate_expiry_days(
                    certificate.name,
                    now=datetime(2030, 1, 1, tzinfo=timezone.utc),
                )
        self.assertEqual(days, 1)

    def test_client_csr_exports_no_private_key_and_generates_age_recipient(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as export:
            def fake_run(argv, _runner=None):
                if argv[1:3] == ["req", "-new"]:
                    key = argv[argv.index("-keyout") + 1]
                    csr = argv[argv.index("-out") + 1]
                    with open(key, "w", encoding="ascii") as stream:
                        stream.write("PRIVATE KEY")
                    with open(csr, "w", encoding="ascii") as stream:
                        stream.write("CSR")
                    return SimpleNamespace(stdout="")
                if os.path.basename(argv[0]) == "age-keygen" and argv[1:2] == ["-o"]:
                    with open(argv[-1], "w", encoding="ascii") as stream:
                        stream.write("AGE-SECRET-KEY")
                    return SimpleNamespace(stdout="Public key: " + "age1" + "a" * 40 + "\n")
                if os.path.basename(argv[0]) == "age-keygen" and argv[1:2] == ["-y"]:
                    return SimpleNamespace(stdout="age1" + "a" * 40 + "\n")
                raise AssertionError(argv)

            with patch("feclora.deployment.managed_pki._root_only_directory", return_value=root), patch(
                "feclora.deployment.managed_pki._run", side_effect=fake_run,
            ):
                identity, private_key, exported = create_client_csr(root, export, "lab-01")
            self.assertEqual(identity, "URI:feclora-client-lab-01")
            self.assertTrue(os.path.isfile(private_key))
            self.assertTrue(os.path.isfile(exported))
            self.assertNotIn("PRIVATE KEY", open(exported, encoding="ascii").read())
            self.assertTrue(os.path.isfile(os.path.join(export, "feclora-lab-01.age-recipient")))
            self.assertEqual(os.stat(private_key).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.managed_pki import (
    PKIError, renew_server_certificate, rotate_server_keypair,
)


class ManagedPKITests(unittest.TestCase):
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
            original_key = Path(paths["server.key"]).read_bytes()
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
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-server\n")
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
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-server\n")
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
                    return SimpleNamespace(stdout="X509v3 Subject Alternative Name:\n    URI:feclora-server\n")
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




if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.managed_pki import (
    PKIError, certificate_expiry_days, create_client_csr, inspect_client_csr,
)


class ManagedPKITests(unittest.TestCase):
    def test_csr_requires_one_feclora_uri_san_and_valid_signature(self):
        with tempfile.NamedTemporaryFile() as csr:
            with patch(
                "feclora.deployment.managed_pki._run",
                side_effect=[
                    SimpleNamespace(stdout="Certificate request self-signature verify OK"),
                    SimpleNamespace(stdout="X509v3 Subject Alternative Name:\\n    URI:feclora-client-lab-01\\n"),
                ],
            ):
                self.assertEqual(inspect_client_csr(csr.name), "URI:feclora-client-lab-01")

    def test_csr_rejects_multiple_or_non_feclora_sans(self):
        with tempfile.NamedTemporaryFile() as csr:
            with patch(
                "feclora.deployment.managed_pki._run",
                side_effect=[
                    SimpleNamespace(stdout="verified"),
                    SimpleNamespace(stdout="X509v3 Subject Alternative Name:\\n    URI:feclora-client-lab-01, DNS:untrusted.example\\n"),
                ],
            ):
                with self.assertRaisesRegex(PKIError, "exactly one"):
                    inspect_client_csr(csr.name)

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
                if argv[1:3] == ["age-keygen", "-o"]:
                    with open(argv[-1], "w", encoding="ascii") as stream:
                        stream.write("AGE-SECRET-KEY")
                    return SimpleNamespace(stdout="")
                if argv[1:3] == ["age-keygen", "-y"]:
                    return SimpleNamespace(stdout="age1" + "a" * 40 + "\\n")
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

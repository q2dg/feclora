import unittest

from feclora.storage.systemd_credential_cli import build_parser
from feclora.storage.systemd_credential_store import CREDENTIAL_KINDS


class SystemdCredentialCliTests(unittest.TestCase):
    def test_every_store_kind_is_accepted_for_put_and_remove(self):
        for kind in CREDENTIAL_KINDS:
            with self.subTest(kind=kind):
                put = build_parser().parse_args([
                    "put", "--id", "archive", "--kind", kind, "--source", "/root/credential",
                ])
                remove = build_parser().parse_args([
                    "remove", "--id", "archive", "--kind", kind,
                ])
                self.assertEqual(put.kind, kind)
                self.assertEqual(remove.kind, kind)


if __name__ == "__main__":
    unittest.main()

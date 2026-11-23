import unittest

from feclora.storage.systemd_credential_cli import build_parser


class SystemdCredentialCliTests(unittest.TestCase):
    def test_s3_credentials_can_be_removed(self):
        args = build_parser().parse_args(["remove", "--id", "archive", "--kind", "s3"])
        self.assertEqual(args.command, "remove")
        self.assertEqual(args.id, "archive")
        self.assertEqual(args.kind, "s3")


if __name__ == "__main__":
    unittest.main()

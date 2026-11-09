import os
import tempfile
import unittest
from pathlib import Path
from feclora.storage.credential_cli import read_source_file
from feclora.storage.credential_store import CredentialStoreError


class CredentialCliSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.source.write_bytes(b"secret material")
        self.source.chmod(0o600)

    def test_reads_private_regular_source(self):
        self.assertEqual(read_source_file(str(self.source), owner_uid=os.getuid()), b"secret material")

    def test_rejects_group_or_world_accessible_source(self):
        self.source.chmod(0o640)
        with self.assertRaisesRegex(CredentialStoreError, "private regular file"):
            read_source_file(str(self.source), owner_uid=os.getuid())

    def test_rejects_symlink_source(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(CredentialStoreError, "symlink"):
            read_source_file(str(link), owner_uid=os.getuid())

    def test_rejects_hard_link_source(self):
        os.link(self.source, Path(self.temp.name) / "hard-link")
        with self.assertRaisesRegex(CredentialStoreError, "private regular file"):
            read_source_file(str(self.source), owner_uid=os.getuid())

import tempfile
import stat
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.cockpit_enrollment import (
    CockpitEnrollmentError, export_server_age_recipients,
)


class CockpitEnrollmentTests(unittest.TestCase):
    def test_media_file_rejects_paths_outside_removable_media(self):
        with tempfile.NamedTemporaryFile() as source:
            with self.assertRaisesRegex(CockpitEnrollmentError, "under /run/media"):
                from feclora.deployment.cockpit_enrollment import _media_file
                _media_file(source.name, "CSR")

    def test_export_server_age_recipients_writes_private_non_overwriting_bundle(self):
        import hashlib
        import os
        import stat
        import tempfile

        payload = ("age1" + "a" * 40 + "\n").encode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            pki_directory = Path(directory) / "pki"
            pki_directory.mkdir()
            source = pki_directory / "age-recipients.txt"
            source.write_bytes(payload)
            with patch("feclora.deployment.cockpit_enrollment.PKI", str(pki_directory)), patch(
                "feclora.deployment.cockpit_enrollment._media_directory", return_value=directory
            ), patch("feclora.deployment.cockpit_enrollment.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=len(payload)
            )):
                result = export_server_age_recipients({"export_directory": directory})
            self.assertEqual(Path(result["path"]).read_bytes(), payload)
            self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(os.stat(result["path"]).st_mode & 0o777, 0o600)
            with patch("feclora.deployment.cockpit_enrollment.PKI", str(pki_directory)), patch(
                "feclora.deployment.cockpit_enrollment._media_directory", return_value=directory
            ), patch("feclora.deployment.cockpit_enrollment.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=len(payload)
            )):
                with self.assertRaisesRegex(CockpitEnrollmentError, "refusing to overwrite"):
                    export_server_age_recipients({"export_directory": directory})



if __name__ == "__main__":
    unittest.main()

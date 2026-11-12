import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.deployment.bootstrap import ensure_server_deployment_config


class OptionalImageSecurityBootstrapTests(unittest.TestCase):
    def test_tls_bootstrap_succeeds_without_age_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pki = root / "pki"
            pki.mkdir()
            config = root / "etc" / "deployment-server.json"
            repository = root / "images"

            def ensure_directory(path, mode=0o700):
                os.makedirs(path, mode=mode, exist_ok=True)
                os.chmod(path, mode)
                return path

            tls = {
                "ca_file": str(pki / "ca.crt"),
                "server_certificate": str(pki / "server.crt"),
                "server_key": str(pki / "server.key"),
            }
            with (
                patch("feclora.deployment.bootstrap.os.geteuid", return_value=0),
                patch("feclora.deployment.bootstrap._ensure_directory", side_effect=ensure_directory),
                patch("feclora.deployment.bootstrap.initialize_server_pki", return_value=tls),
                patch("feclora.deployment.bootstrap.shutil.which", return_value=None),
            ):
                created = ensure_server_deployment_config(
                    "192.0.2.10",
                    config_path=str(config),
                    pki_directory=str(pki),
                    repository=str(repository),
                    runner=lambda *args, **kwargs: self.fail("optional tools must not be invoked"),
                )

            self.assertTrue(created)
            value = json.loads(config.read_text(encoding="utf-8"))
            self.assertFalse((pki / "server.age").exists())
            self.assertFalse((pki / "age-recipients.txt").exists())


if __name__ == "__main__":
    unittest.main()

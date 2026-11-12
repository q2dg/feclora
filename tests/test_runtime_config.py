import json
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.runtime_config import (
    RuntimeConfigError, load_client_runtime_config, load_server_runtime_config,
)


def fake_lstat(path):
    mode = stat.S_IFDIR | 0o700 if path == "/repo" else stat.S_IFREG | 0o600
    return SimpleNamespace(st_mode=mode, st_uid=0)


class RuntimeConfigTests(unittest.TestCase):
    def write_config(self, directory, value):
        path = os.path.join(directory, "config.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        return path

    def server_config(self):
        return {
            "schema_version": 1,
            "bind_address": "192.0.2.2",
            "port": 9443,
            "local_identity": "URI:feclora-server",
            "ca_file": "/pki/ca.crt",
            "certificate_file": "/pki/server.crt",
            "private_key_file": "/pki/server.key",
            "client_identity_to_mac": {
                "URI:feclora-client-01": "52:54:00:12:34:56",
            },
            "client_minisign_public_keys": {
                "52:54:00:12:34:56": "/pki/client.pub",
            },
            "server_minisign_public_key": "/pki/server.pub",
            "repository": "/repo",
        }

    def client_config(self):
        return {
            "schema_version": 1,
            "host": "192.0.2.2",
            "port": 9443,
            "local_identity": "URI:feclora-client-01",
            "server_identity": "URI:feclora-server",
            "mac_address": "52:54:00:12:34:56",
            "ca_file": "/pki/ca.crt",
            "certificate_file": "/pki/client.crt",
            "private_key_file": "/pki/client.key",
            "trusted_server_public_key": "/pki/server.pub",
            "local_minisign_secret_key": "/pki/client.key.minisign",
            "local_minisign_public_key": "/pki/client.pub",
            "age_identity_file": None,
            "age_recipients_file": None,
            "repository": "/repo",
        }

    def test_loads_server_enrollment_and_trust_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, self.server_config())
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_server_runtime_config(path)
        self.assertEqual(config.bind_address, "192.0.2.2")
        self.assertEqual(config.client_minisign_public_keys["52:54:00:12:34:56"], "/pki/client.pub")

    def test_server_tls_config_does_not_require_optional_minisign_key(self):
        payload = self.server_config()
        payload["server_minisign_public_key"] = None
        payload["client_minisign_public_keys"] = {}
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_server_runtime_config(path)
        self.assertIsNone(config.server_minisign_public_key)

    def test_server_config_allows_empty_allowlist_after_revoking_all_clients(self):
        payload = self.server_config()
        payload["client_identity_to_mac"] = {}
        payload["client_minisign_public_keys"] = {}
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_server_runtime_config(path)

    def test_server_config_allows_restore_only_enrolled_client(self):
        payload = self.server_config()
        payload["client_minisign_public_keys"] = {}
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_server_runtime_config(path)
        self.assertEqual(dict(config.client_minisign_public_keys), {})

    def test_loads_client_tls_and_local_signing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, self.client_config())
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_client_runtime_config(path)
        self.assertEqual(config.server_identity, "URI:feclora-server")
        self.assertEqual(config.mac_address, "52:54:00:12:34:56")
        self.assertIsNone(config.age_identity_file)
        self.assertIsNone(config.age_recipients_file)

    def test_client_tls_config_can_omit_optional_server_minisign_key(self):
        payload = self.client_config()
        payload["trusted_server_public_key"] = None
        payload["local_minisign_secret_key"] = None
        payload["local_minisign_public_key"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_client_runtime_config(path)
        self.assertIsNone(config.trusted_server_public_key)
        self.assertIsNone(config.local_minisign_secret_key)

    def test_restore_only_client_does_not_need_a_minisign_secret_key(self):
        payload = self.client_config()
        payload["local_minisign_secret_key"] = None
        payload["local_minisign_public_key"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_client_runtime_config(path)
        self.assertIsNone(config.local_minisign_secret_key)
        self.assertIsNone(config.local_minisign_public_key)

    def test_client_signing_keys_must_be_configured_as_a_pair(self):
        payload = self.client_config()
        payload["local_minisign_secret_key"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                with self.assertRaisesRegex(RuntimeConfigError, "must be configured together"):
                    load_client_runtime_config(path)
    def test_restore_only_client_may_omit_its_signing_keypair(self):
        payload = self.client_config()
        payload["local_minisign_secret_key"] = None
        payload["local_minisign_public_key"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_client_runtime_config(path)
        self.assertIsNone(config.local_minisign_secret_key)
        self.assertIsNone(config.local_minisign_public_key)

    def test_legacy_client_identity_mapping_is_ignored(self):
        payload = self.server_config()
        payload["client_identity_to_mac"]["URI:other-client"] = "52:54:00:12:34:56"
        payload["client_minisign_public_keys"]["52:54:00:12:34:57"] = "/pki/other.pub"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                config = load_server_runtime_config(path)
        self.assertEqual(dict(config.client_minisign_public_keys), {"52:54:00:12:34:57": "/pki/other.pub"})

    def test_rejects_non_ipv4_or_unspecified_server_bind(self):
        payload = self.server_config()
        payload["bind_address"] = "0.0.0.0"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=fake_lstat):
                with self.assertRaisesRegex(RuntimeConfigError, "concrete unicast"):
                    load_server_runtime_config(path)

    def test_rejects_world_accessible_configuration(self):
        payload = self.client_config()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, payload)
            def unsafe_lstat(_path):
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0)
            with patch("feclora.deployment.runtime_config.os.lstat", side_effect=unsafe_lstat):
                with self.assertRaisesRegex(RuntimeConfigError, "group or other users"):
                    load_client_runtime_config(path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from feclora.webapi import WebAPIError, _import_deployment_job, _publish_pxe_answer, _provide_pxe_age_passphrase, _read_pxe_answer_source


class PXEAnswerAPITests(unittest.TestCase):
    JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"

    def answer(self) -> bytes:
        return json.dumps({
            "schema_version": 2,
            "operation": "restore",
            "image_id": "fedora",
            "repository_id": "nas-images",
            "target": {"wwn": "0x5000abcd", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }).encode("utf-8")

    def test_rejects_invalid_base64_before_touching_pxe_services(self):
        with self.assertRaisesRegex(WebAPIError, "valid base64"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "source": "upload",
                "answer_base64": "%%%not-base64%%%",
            })

    def test_upload_source_is_bounded_and_decoded(self):
        raw = self.answer()
        result = _read_pxe_answer_source({
            "job_id": self.JOB_ID, "source": "upload",
            "answer_base64": base64.b64encode(raw).decode("ascii"),
        })
        self.assertEqual(result, raw)

    def test_remote_deployment_job_import_validates_and_normalizes_schema(self):
        job = {
            "schema_version": 1, "job_id": self.JOB_ID, "operation": "restore",
            "image_id": "fedora", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "auto", "transport": "multicast",
            "multicast_group": "239.10.10.10", "multicast_port": 9000,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with patch("feclora.webapi._read_pxe_answer_source",
                   return_value=json.dumps(job).encode("utf-8")) as reader:
            result = _import_deployment_job({
                "source": "url", "url": "https://jobs.example.test/restore.json",
            })
        self.assertEqual(result["job"]["job_id"], self.JOB_ID)
        self.assertEqual(result["job"]["transport"], "multicast")
        self.assertIn("Review", result["message"])
        self.assertEqual(reader.call_args.args[0]["source"], "url")
        self.assertIn("job_id", reader.call_args.args[0])

    def test_local_deployment_job_upload_uses_the_same_validated_import_path(self):
        job = {
            "schema_version": 1, "job_id": self.JOB_ID, "operation": "restore",
            "image_id": "fedora", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "eno1", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        raw = json.dumps(job).encode("utf-8")
        with patch("feclora.webapi._read_pxe_answer_source", return_value=raw):
            result = _import_deployment_job({
                "source": "upload",
                "answer_base64": base64.b64encode(raw).decode("ascii"),
            })
        self.assertEqual(result["job"]["network_interface"], "eno1")

    def test_remote_deployment_job_import_rejects_invalid_documents(self):
        for raw in (b"not-json", b'{"schema_version":1,"job_id":"invalid"}'):
            with self.subTest(raw=raw), patch(
                "feclora.webapi._read_pxe_answer_source", return_value=raw,
            ), self.assertRaisesRegex(WebAPIError, "import validation failed"):
                _import_deployment_job({"source": "url", "url": "https://jobs.example.test/job.json"})

    def test_shared_deployment_job_is_accepted_by_the_pxe_validator(self):
        from feclora.network.pxe_answer import parse_pxe_answer
        job = {
            "schema_version": 1, "job_id": self.JOB_ID, "operation": "restore",
            "image_id": "fedora", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "auto", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "automatic", "expected_clients": None, "start_deadline": None,
            "repository_id": "nas-images", "boot_method": "pxe",
            "confirm_destructive": True,
            "target_bindings": {"52:54:00:12:34:56": {"wwn": "0x5000abcd", "serial": None}},
        }
        self.assertEqual(parse_pxe_answer(json.dumps(job))["job_id"], self.JOB_ID)

    def test_http_source_downloads_without_redirects_and_checks_size(self):
        raw = self.answer()
        response = MagicMock()
        response.status = 200
        response.headers = {"Content-Length": str(len(raw))}
        response.read.return_value = raw
        response.__enter__.return_value = response
        with patch("urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.return_value = response
            result = _read_pxe_answer_source({
                "job_id": self.JOB_ID, "source": "url",
                "url": "https://answers.example.test/restore.json",
            })
        self.assertEqual(result, raw)
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://answers.example.test/restore.json")

    def test_http_source_rejects_credentials_and_non_http_schemes(self):
        for url in ("file:///etc/passwd", "https://user:secret@example.test/answer.json",
                    "https://example.test/answer.json#fragment"):
            with self.subTest(url=url), self.assertRaises(WebAPIError):
                _read_pxe_answer_source({
                    "job_id": self.JOB_ID, "source": "url", "url": url,
                })

    def test_repository_source_reads_only_bounded_relative_regular_files(self):
        import os
        import tempfile
        from pathlib import Path

        class FakeS3Manager:
            def list(self):
                return []
        class FakeRemoteManager:
            def __init__(self, root):
                self.root = root
            def acquire_usage_lock(self, _identifier):
                return os.open(os.devnull, os.O_RDONLY)
            def resolve(self, _identifier):
                return str(self.root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.answer()
            (root / "answers").mkdir()
            (root / "answers" / "restore.json").write_bytes(raw)
            with patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                       return_value=FakeS3Manager()), \
                 patch("feclora.webapi._remote_repository_manager",
                       return_value=FakeRemoteManager(root)):
                result = _read_pxe_answer_source({
                    "job_id": self.JOB_ID, "source": "repository",
                    "repository_id": "nas-images",
                    "source_path": "answers/restore.json",
                })
            self.assertEqual(result, raw)

    def test_scp_source_uses_saved_ssh_credentials_and_checks_host_keys(self):
        import os
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock

        class FakeS3Manager:
            def list(self):
                return []
        class FakeRemoteManager:
            def acquire_usage_lock(self, _identifier):
                return os.open(os.devnull, os.O_RDONLY)
            def _load(self):
                return {"ssh-backup": {"provider": "sshfs"}}
        class FakeCredentialStore:
            root = Path("/fake/credentials")
            def read(self, identifier, kind):
                return f"{identifier}:{kind}".encode("ascii")

        repo = SimpleNamespace(
            provider="sshfs", identity_file="/fake/credentials/feclora-ssh-backup-ssh-key.cred",
            known_hosts_file="/fake/credentials/feclora-ssh-backup-known-hosts.cred",
            remote_path="/srv/answer-files", username="deploy",
            host="ssh.example.test", port=2222,
        )
        completed = Mock(returncode=0, stderr=b"")
        def run(command, **_kwargs):
            Path(command[-1]).write_bytes(self.answer())
            return completed

        with patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                   return_value=FakeS3Manager()), \
             patch("feclora.webapi._remote_repository_manager",
                   return_value=FakeRemoteManager()), \
             patch("feclora.storage.repository_manager._repository", return_value=repo), \
             patch("feclora.storage.systemd_credential_store.SystemdCredentialStore",
                   return_value=FakeCredentialStore()), \
             patch("feclora.webapi.shutil.which", return_value="/usr/bin/scp"), \
             patch("feclora.webapi.subprocess.run", side_effect=run) as scp_run:
            result = _read_pxe_answer_source({
                "job_id": self.JOB_ID, "source": "scp",
                "repository_id": "ssh-backup", "source_path": "production/answer.json",
            })
        self.assertEqual(result, self.answer())
        command = scp_run.call_args.args[0]
        self.assertIn("-oStrictHostKeyChecking=yes", command)
        self.assertIn("-P", command)
        self.assertIn("2222", command)
        self.assertIn("deploy@ssh.example.test:/srv/answer-files/production/answer.json", command)

    def test_repository_source_rejects_parent_path_components(self):
        with self.assertRaisesRegex(WebAPIError, "safe relative path"):
            _read_pxe_answer_source({
                "job_id": self.JOB_ID, "source": "repository",
                "repository_id": "nas-images", "source_path": "../answer.json",
            })

    def test_age_passphrase_requires_a_nonempty_single_line_secret(self):
        with self.assertRaisesRegex(WebAPIError, "1-1024 UTF-8 bytes"):
            _provide_pxe_age_passphrase({"passphrase": "bad\nsecret"})
        with self.assertRaisesRegex(WebAPIError, "requires exactly passphrase"):
            _provide_pxe_age_passphrase({"passphrase": "secret", "job_id": self.JOB_ID})

    def test_rejects_unknown_or_missing_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "requires job_id, source and answer_base64"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "source": "upload",
                "answer_base64": base64.b64encode(self.answer()).decode("ascii"),
                "signature_base64": "unused",
            })


if __name__ == "__main__":
    unittest.main()

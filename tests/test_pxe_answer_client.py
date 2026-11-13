from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.network.pxe_answer_client import (
    PXEAnswerClientError,
    fetch_live_pxe_answer,
    execute_live_pxe_restore,
    _wait_for_age_passphrase,
    _download_https_object,
    _check_https_staging_capacity,
    _discover_dhcp_answer_url,
)


JOB = "3b241101-e2bb-4255-8caf-4136c566a962"
URL = f"http://192.0.2.10:8080/answers/{JOB}/answer.json"


def answer() -> bytes:
    return json.dumps({
        "schema_version": 1,
        "operation": "restore",
        "image_id": "golden",
        "repository_url": "nfs://repo.example/images",
        "target": {"wwn": "0x5000c50012345678", "serial": None},
        "confirm_destructive": True,
        "start": True,
    }).encode("utf-8")


class PXEAnswerClientTests(unittest.TestCase):
    def test_interactive_boot_does_not_download_or_publish(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "answer.json"
            result = fetch_live_pxe_answer(
                "quiet feclora.pxe_mode=interactive",
                destination=destination,
                downloader=lambda _url: self.fail("interactive boot must not download"),
                dhcp_url_provider=lambda: (_ for _ in ()).throw(AssertionError("interactive PXE must not inspect DHCP")),
            )
            self.assertIsNone(result)
            self.assertFalse(destination.exists())

    def test_networkmanager_dhcp_option_224_is_discovered(self):
        expected = "http://192.0.2.10:8080/unattended-answer.json"
        result = SimpleNamespace(returncode=0, stdout=f"domain_name = example\n224 = {expected}\n")
        with patch("feclora.network.pxe_answer_client.subprocess.run", return_value=result):
            self.assertEqual(_discover_dhcp_answer_url(), expected)

    def test_conflicting_dhcp_answer_options_fail_closed(self):
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "224 = http://192.0.2.10:8080/unattended-answer.json\n"
                "224 = http://192.0.2.11:8080/unattended-answer.json\n"
            ),
        )
        with patch("feclora.network.pxe_answer_client.subprocess.run", return_value=result):
            with self.assertRaisesRegex(PXEAnswerClientError, "conflicting"):
                _discover_dhcp_answer_url()

    def test_iso_boot_discovers_current_answer_url_from_dhcp(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            stable_url = "http://192.0.2.10:8080/unattended-answer.json"
            seen = []
            result = fetch_live_pxe_answer(
                "quiet ro",
                destination=destination,
                downloader=lambda url: (seen.append(url) or answer()),
                dhcp_url_provider=lambda: stable_url,
            )
            self.assertEqual(seen, [stable_url])
            self.assertEqual(result["image_id"], "golden")
            self.assertEqual(destination.read_bytes(), answer())

    def test_unattended_boot_downloads_validates_and_publishes_answer(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            seen = []
            result = fetch_live_pxe_answer(
                f"quiet feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                f"feclora.pxe_answer_url={URL}",
                destination=destination,
                downloader=lambda url: (seen.append(url) or answer()),
            )
            self.assertEqual(seen, [URL])
            self.assertEqual(result["image_id"], "golden")
            self.assertEqual(destination.read_bytes(), answer())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)

    def test_answer_without_expiry_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            result = fetch_live_pxe_answer(
                f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                f"feclora.pxe_answer_url={URL}",
                destination=destination,
                downloader=lambda _url: answer(),
            )
            self.assertEqual(result["image_id"], "golden")
            self.assertNotIn("expires_at", result)
            self.assertTrue(destination.is_file())

    def test_invalid_download_is_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            with self.assertRaises(PXEAnswerClientError):
                fetch_live_pxe_answer(
                    f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                    f"feclora.pxe_answer_url={URL}",
                    destination=destination,
                    downloader=lambda _url: b'{"schema_version":1}',
                )
            self.assertFalse(destination.exists())

    def test_invalid_handoff_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PXEAnswerClientError):
                fetch_live_pxe_answer(
                    "feclora.pxe_mode=unattended-answer feclora.pxe_job_id=bad",
                    destination=Path(root) / "answer.json",
                    downloader=lambda _url: self.fail("invalid handoff must not download"),
                )


    def test_nfs_restore_uses_existing_engine_and_revalidates_target_before_write(self):
        with tempfile.TemporaryDirectory() as root:
            mountpoint = Path(root) / "repository"
            mountpoint.mkdir(mode=0o700)
            (mountpoint / "golden.manifest.json").write_text("{}", encoding="utf-8")
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            manifest = SimpleNamespace(image_id="golden", image_type="disk", artifacts=())
            target = {"path": "/dev/sdb", "type": "disk", "wwn": "0x5000c50012345678", "serial": None}
            def restore(*args, **kwargs):
                kwargs["pre_write_callback"]()
            with patch("feclora.network.pxe_answer_client._mount_nfs_repository"), \
                 patch("feclora.network.pxe_answer_client._resolve_target", return_value=target), \
                 patch("feclora.network.pxe_answer_client._revalidate_target") as revalidate, \
                 patch("feclora.network.pxe_answer_client.ImageManifest.from_json", return_value=manifest), \
                 patch("feclora.network.pxe_answer_client.restore_disk", side_effect=restore) as restore_call, \
                 patch("feclora.network.pxe_answer_client.subprocess.run"):
                resolved = execute_live_pxe_restore({
                    "image_id": "golden",
                    "repository_url": "nfs://nfs.example/images",
                    "target": {"wwn": "0x5000c50012345678", "serial": None},
                }, mountpoint=mountpoint, operation_log=log_dir / "operations.jsonl")
            self.assertEqual(resolved, "/dev/sdb")
            revalidate.assert_called_once()
            self.assertTrue(restore_call.call_args.kwargs["ignore_signature"])
            self.assertTrue((log_dir / "operations.jsonl").is_file())

    def test_https_repository_uses_verified_temporary_staging_and_existing_restore_engine(self):
        with tempfile.TemporaryDirectory() as root:
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            manifest = SimpleNamespace(image_id="golden", image_type="disk", artifacts=())
            target = {"path": "/dev/sdb", "type": "disk", "wwn": "0x5000c50012345678", "serial": None}
            staged = []
            def stage(url, image_id, directory):
                staged.append((url, image_id, directory))
                path = directory / "golden.manifest.json"
                path.write_text("{}", encoding="utf-8")
                return path
            def restore(*args, **kwargs):
                kwargs["pre_write_callback"]()
            with patch("feclora.network.pxe_answer_client._stage_https_repository", side_effect=stage), \
                 patch("feclora.network.pxe_answer_client._resolve_target", return_value=target), \
                 patch("feclora.network.pxe_answer_client._revalidate_target") as revalidate, \
                 patch("feclora.network.pxe_answer_client.ImageManifest.from_json", return_value=manifest), \
                 patch("feclora.network.pxe_answer_client.restore_disk", side_effect=restore) as restore_call:
                resolved = execute_live_pxe_restore({
                    "image_id": "golden",
                    "repository_url": "https://objects.example.net/feclora/images",
                    "target": {"wwn": "0x5000c50012345678", "serial": None},
                }, operation_log=log_dir / "operations.jsonl")
            self.assertEqual(resolved, "/dev/sdb")
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0][0], "https://objects.example.net/feclora/images")
            self.assertTrue(staged[0][2].is_dir() is False)
            revalidate.assert_called_once()
            self.assertTrue(restore_call.call_args.kwargs["ignore_signature"])
            self.assertTrue((log_dir / "operations.jsonl").is_file())

    def test_https_staging_requires_artifact_space_plus_reserve(self):
        required = 10 * 1024 * 1024 * 1024
        reserve = max(256 * 1024 * 1024, min(required // 20, 2 * 1024 * 1024 * 1024))
        with patch("feclora.network.pxe_answer_client.shutil.disk_usage",
                   return_value=SimpleNamespace(free=required + reserve - 1)):
            with self.assertRaisesRegex(PXEAnswerClientError, "insufficient local staging space"):
                _check_https_staging_capacity(Path("/tmp"), required)
        with patch("feclora.network.pxe_answer_client.shutil.disk_usage",
                   return_value=SimpleNamespace(free=required + reserve)):
            _check_https_staging_capacity(Path("/tmp"), required)

    def test_https_object_download_checks_size_and_sha256(self):
        payload = b"verified artifact bytes"
        class Headers(dict):
            pass
        class Response(io.BytesIO):
            status = 200
            headers = Headers({"Content-Length": str(len(payload))})
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                self.close()
        class Opener:
            def open(self, *_args, **_kwargs):
                return Response(payload)
        with patch("feclora.network.pxe_answer_client.urllib.request.build_opener", return_value=Opener()):
            result = _download_https_object(
                "https://objects.example.net/prefix/golden/disk.img",
                max_bytes=len(payload), expected_size=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )
        self.assertEqual(result, payload)

    def test_https_object_download_rejects_checksum_mismatch_and_removes_partial_file(self):
        payload = b"untrusted artifact"
        class Headers(dict):
            pass
        class Response(io.BytesIO):
            status = 200
            headers = Headers({"Content-Length": str(len(payload))})
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                self.close()
        class Opener:
            def open(self, *_args, **_kwargs):
                return Response(payload)
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "artifact.img"
            with patch("feclora.network.pxe_answer_client.urllib.request.build_opener", return_value=Opener()):
                with self.assertRaisesRegex(PXEAnswerClientError, "SHA-256"):
                    _download_https_object(
                        "https://objects.example.net/prefix/golden/disk.img",
                        destination=destination, max_bytes=len(payload),
                        expected_size=len(payload), expected_sha256="0" * 64,
                    )
            self.assertFalse(destination.exists())

    def test_age_encrypted_pxe_image_requests_passphrase_and_forwards_it_to_restore(self):
        with tempfile.TemporaryDirectory() as root:
            mountpoint = Path(root) / "repository"
            mountpoint.mkdir(mode=0o700)
            (mountpoint / "golden.manifest.json").write_text("{}", encoding="utf-8")
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            manifest = SimpleNamespace(
                image_id="golden", image_type="disk",
                artifacts=(SimpleNamespace(encryption="age"),),
            )
            target = {"path": "/dev/sdb", "type": "disk", "wwn": "0x5000c50012345678", "serial": None}
            def restore(*args, **kwargs):
                kwargs["pre_write_callback"]()
            provider = unittest.mock.Mock(return_value="correct horse battery staple")
            with patch("feclora.network.pxe_answer_client._mount_nfs_repository"), \
                 patch("feclora.network.pxe_answer_client._resolve_target", return_value=target), \
                 patch("feclora.network.pxe_answer_client._revalidate_target"), \
                 patch("feclora.network.pxe_answer_client.ImageManifest.from_json", return_value=manifest), \
                 patch("feclora.network.pxe_answer_client.restore_disk", side_effect=restore) as restore_call, \
                 patch("feclora.network.pxe_answer_client.subprocess.run"):
                execute_live_pxe_restore({
                    "image_id": "golden",
                    "repository_url": "nfs://nfs.example/images",
                    "target": {"wwn": "0x5000c50012345678", "serial": None},
                }, mountpoint=mountpoint, operation_log=log_dir / "operations.jsonl",
                passphrase_provider=provider)
            provider.assert_called_once_with()
            self.assertEqual(restore_call.call_args.kwargs["age_passphrase"], "correct horse battery staple")

    def test_wait_for_age_passphrase_consumes_private_one_shot_file(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "age-passphrase"
            secret.write_text("correct horse battery staple", encoding="utf-8")
            secret.chmod(0o600)
            with patch("feclora.network.pxe_answer_client.os.geteuid", return_value=os.geteuid()):
                value = _wait_for_age_passphrase(secret, timeout=1)
            self.assertEqual(value, "correct horse battery staple")
            self.assertFalse(secret.exists())

    def test_wait_for_age_passphrase_rejects_unsafe_file_mode(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "age-passphrase"
            secret.write_text("secret", encoding="utf-8")
            secret.chmod(0o644)
            with patch("feclora.network.pxe_answer_client.os.geteuid", return_value=os.geteuid()):
                with self.assertRaisesRegex(PXEAnswerClientError, "unsafe"):
                    _wait_for_age_passphrase(secret, timeout=1)

    def test_wait_for_age_passphrase_rejects_symlink_without_reading_target(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "age-passphrase"
            target = Path(root) / "outside-secret"
            target.write_text("must not be read", encoding="utf-8")
            target.chmod(0o600)
            secret.symlink_to(target)
            with patch("feclora.network.pxe_answer_client.os.geteuid", return_value=os.geteuid()):
                with self.assertRaisesRegex(PXEAnswerClientError, "safely open"):
                    _wait_for_age_passphrase(secret, timeout=1)
            self.assertEqual(target.read_text(encoding="utf-8"), "must not be read")

    def test_non_nfs_provider_fails_closed(self):
        with self.assertRaisesRegex(PXEAnswerClientError, "supports NFS and credential-free HTTPS"):
            execute_live_pxe_restore({
                "image_id": "golden",
                "repository_url": "sftp://repo.example/images",
                "target": {"wwn": "0x5000c50012345678", "serial": None},
            })




if __name__ == "__main__":
    unittest.main()

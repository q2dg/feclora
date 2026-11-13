from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.network.pxe_answer_client import (
    PXEAnswerClientError, _discover_dhcp_answer_url, _managed_repository,
    _wait_for_age_passphrase, execute_live_pxe_restore, fetch_live_pxe_answer,
)


JOB = "3b241101-e2bb-4255-8caf-4136c566a962"
URL = f"http://192.0.2.10:8080/answers/{JOB}/answer.json"


def answer() -> bytes:
    return json.dumps({
        "schema_version": 2, "operation": "restore", "image_id": "golden",
        "repository_id": "nas-images",
        "target": {"wwn": "0x5000c50012345678", "serial": None},
        "confirm_destructive": True, "start": True,
    }).encode("utf-8")


class PXEAnswerClientTests(unittest.TestCase):
    def test_interactive_boot_does_not_download_or_publish(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "answer.json"
            result = fetch_live_pxe_answer(
                "quiet feclora.pxe_mode=interactive", destination=destination,
                downloader=lambda _url: self.fail("interactive boot must not download"),
                dhcp_url_provider=lambda: (_ for _ in ()).throw(AssertionError("must not inspect DHCP")),
            )
            self.assertIsNone(result)
            self.assertFalse(destination.exists())

    def test_networkmanager_dhcp_option_224_is_discovered(self):
        expected = "http://192.0.2.10:8080/unattended-answer.json"
        result = SimpleNamespace(returncode=0, stdout=f"domain_name = example\n224 = {expected}\n")
        with patch("feclora.network.pxe_answer_client.subprocess.run", return_value=result):
            self.assertEqual(_discover_dhcp_answer_url(), expected)

    def test_conflicting_dhcp_answer_options_fail_closed(self):
        result = SimpleNamespace(returncode=0, stdout=(
            "224 = http://192.0.2.10:8080/unattended-answer.json\n"
            "224 = http://192.0.2.11:8080/unattended-answer.json\n"
        ))
        with patch("feclora.network.pxe_answer_client.subprocess.run", return_value=result):
            with self.assertRaisesRegex(PXEAnswerClientError, "conflicting"):
                _discover_dhcp_answer_url()

    def test_iso_boot_discovers_current_answer_url_from_dhcp(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            stable_url = "http://192.0.2.10:8080/unattended-answer.json"
            seen = []
            result = fetch_live_pxe_answer(
                "quiet ro", destination=destination,
                downloader=lambda url: (seen.append(url) or answer()),
                dhcp_url_provider=lambda: stable_url,
            )
            self.assertEqual(seen, [stable_url])
            self.assertEqual(result["repository_id"], "nas-images")
            self.assertEqual(destination.read_bytes(), answer())

    def test_unattended_boot_downloads_validates_and_publishes_answer(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            seen = []
            result = fetch_live_pxe_answer(
                f"quiet feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} feclora.pxe_answer_url={URL}",
                destination=destination, downloader=lambda url: (seen.append(url) or answer()),
            )
            self.assertEqual(seen, [URL])
            self.assertEqual(result["repository_id"], "nas-images")
            self.assertEqual(destination.read_bytes(), answer())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_download_is_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            with self.assertRaises(PXEAnswerClientError):
                fetch_live_pxe_answer(
                    f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} feclora.pxe_answer_url={URL}",
                    destination=destination, downloader=lambda _url: b'{"schema_version":2}',
                )
            self.assertFalse(destination.exists())

    def test_remote_repository_uses_normal_manager_mount_and_lease(self):
        with tempfile.TemporaryDirectory() as root:
            mount_root = Path(root)
            events = []
            fake_manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images", "mounted": False}],
                mount=lambda identifier: events.append(("mount", identifier)),
                acquire_usage_lock=lambda identifier: os.open(os.devnull, os.O_RDONLY),
                resolve=lambda identifier, write=False: str(mount_root),
                unmount=lambda identifier: events.append(("unmount", identifier)),
            )
            fake_s3 = SimpleNamespace(list=lambda: [])
            remote_registry = mount_root / "repositories.json"
            remote_registry.touch()
            with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=fake_s3), \
                 patch("feclora.storage.repository_manager.REGISTRY", remote_registry), \
                 patch("feclora.storage.repository_manager.RemoteRepositoryManager", return_value=fake_manager):
                with _managed_repository("nas-images", "golden") as repository:
                    self.assertEqual(repository, mount_root)
                    events.append(("restore", "golden"))
            self.assertEqual(events, [
                ("mount", "nas-images"), ("restore", "golden"), ("unmount", "nas-images"),
            ])

    def test_remote_repository_unmounts_if_lease_acquisition_fails(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            def fail_lease(_identifier):
                events.append(("lease-failed", "nas-images"))
                raise RuntimeError("simulated lease failure")
            fake_manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images", "mounted": False}],
                mount=lambda identifier: events.append(("mount", identifier)),
                acquire_usage_lock=fail_lease,
                unmount=lambda identifier: events.append(("unmount", identifier)),
            )
            fake_s3 = SimpleNamespace(list=lambda: [])
            registry = Path(root) / "repositories.json"
            registry.touch()
            with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=fake_s3), \
                 patch("feclora.storage.repository_manager.REGISTRY", registry), \
                 patch("feclora.storage.repository_manager.RemoteRepositoryManager", return_value=fake_manager):
                with self.assertRaisesRegex(RuntimeError, "lease failure"):
                    with _managed_repository("nas-images", "golden"):
                        self.fail("repository must not be yielded without a usage lease")
            self.assertEqual(events, [
                ("mount", "nas-images"), ("lease-failed", "nas-images"),
                ("unmount", "nas-images"),
            ])

    def test_remote_repository_closes_lease_and_unmounts_if_resolution_fails(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            lease_fd = os.open(os.devnull, os.O_RDONLY)
            fake_manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images", "mounted": False}],
                mount=lambda identifier: events.append(("mount", identifier)),
                acquire_usage_lock=lambda _identifier: lease_fd,
                resolve=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad mount")),
                unmount=lambda identifier: events.append(("unmount", identifier)),
            )
            fake_s3 = SimpleNamespace(list=lambda: [])
            registry = Path(root) / "repositories.json"
            registry.touch()
            with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=fake_s3), \
                 patch("feclora.storage.repository_manager.REGISTRY", registry), \
                 patch("feclora.storage.repository_manager.RemoteRepositoryManager", return_value=fake_manager):
                with self.assertRaisesRegex(RuntimeError, "bad mount"):
                    with _managed_repository("nas-images", "golden"):
                        self.fail("unverified mount must not be yielded")
            with self.assertRaises(OSError):
                os.fstat(lease_fd)
            self.assertEqual(events, [("mount", "nas-images"), ("unmount", "nas-images")])

    def test_s3_repository_closes_lease_if_image_download_fails(self):
        with tempfile.TemporaryDirectory() as root:
            lease_fd = os.open(os.devnull, os.O_RDONLY)
            class FakeS3:
                def list(self):
                    return [{"id": "s3-images"}]
                def acquire_usage_lock(self, _identifier):
                    return lease_fd
                def repository(self, _identifier):
                    class ObjectRepo:
                        def download_image_set(self, _image_id, _directory):
                            raise RuntimeError("simulated S3 download failure")
                    return ObjectRepo()
            registry = Path(root) / "s3-repositories.json"
            registry.touch()
            with patch("feclora.storage.s3_repository_manager.REGISTRY", registry), \
                 patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=FakeS3()):
                with self.assertRaisesRegex(RuntimeError, "download failure"):
                    with _managed_repository("s3-images", "golden"):
                        self.fail("failed S3 download must not yield a repository")
            with self.assertRaises(OSError):
                os.fstat(lease_fd)

    def test_unknown_repository_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            absent_s3 = Path(root) / "absent-s3.json"
            absent_remote = Path(root) / "absent-remote.json"
            with patch("feclora.storage.s3_repository_manager.REGISTRY", absent_s3), \
                 patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                       return_value=SimpleNamespace(list=lambda: [])), \
                 patch("feclora.storage.repository_manager.REGISTRY", absent_remote), \
                 patch("feclora.storage.repository_manager.RemoteRepositoryManager",
                       return_value=SimpleNamespace(list=lambda: [])):
                with self.assertRaisesRegex(PXEAnswerClientError, "not configured"):
                    with _managed_repository("missing", "golden"):
                        self.fail("unknown repository must not yield a path")

    def test_s3_repository_uses_existing_manager_and_downloads_image_set(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            class FakeS3:
                def list(self):
                    return [{"id": "s3-images"}]
                def acquire_usage_lock(self, identifier):
                    events.append(("lease", identifier))
                    return os.open(os.devnull, os.O_RDONLY)
                def repository(self, identifier):
                    class ObjectRepo:
                        def download_image_set(self, image_id, directory):
                            events.append(("download", identifier, image_id))
                            (directory / f"{image_id}.manifest.json").write_text("{}", encoding="utf-8")
                    return ObjectRepo()
            s3_registry = Path(root) / "s3-repositories.json"
            s3_registry.touch()
            with patch("feclora.storage.s3_repository_manager.REGISTRY", s3_registry), \
                 patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=FakeS3()):
                with _managed_repository("s3-images", "golden") as repository:
                    self.assertTrue((repository / "golden.manifest.json").is_file())
            self.assertEqual(events, [("lease", "s3-images"), ("download", "s3-images", "golden")])

    def test_s3_client_object_is_released_before_restore_yields_local_copy(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            class FakeObjectRepository:
                def download_image_set(self, image_id, directory):
                    events.append(("download", image_id))
                    (directory / f"{image_id}.manifest.json").write_text("{}", encoding="utf-8")
                def __del__(self):
                    events.append(("client-released",))
            class FakeS3:
                def list(self):
                    return [{"id": "s3-images"}]
                def acquire_usage_lock(self, _identifier):
                    return os.open(os.devnull, os.O_RDONLY)
                def repository(self, _identifier):
                    return FakeObjectRepository()
            registry = Path(root) / "s3-repositories.json"
            registry.touch()
            with patch("feclora.storage.s3_repository_manager.REGISTRY", registry), \\
                 patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=FakeS3()):
                with _managed_repository("s3-images", "golden") as repository:
                    self.assertTrue((repository / "golden.manifest.json").is_file())
                    self.assertIn(("client-released",), events)
                    events.append(("restore-started",))
            self.assertLess(events.index(("client-released",)), events.index(("restore-started",)))

    def test_restore_uses_existing_verified_engine_and_revalidates_target(self):
        with tempfile.TemporaryDirectory() as root:
            repository = Path(root) / "repository"
            repository.mkdir(mode=0o700)
            (repository / "golden.manifest.json").write_text("{}", encoding="utf-8")
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            manifest = SimpleNamespace(image_id="golden", image_type="disk", artifacts=())
            target = {"path": "/dev/sdb", "type": "disk", "wwn": "0x5000c50012345678", "serial": None}
            @contextmanager
            def managed(*_args):
                yield repository
            def restore(*args, **kwargs):
                kwargs["pre_write_callback"]()
            with patch("feclora.network.pxe_answer_client._managed_repository", managed), \
                 patch("feclora.network.pxe_answer_client._resolve_target", return_value=target), \
                 patch("feclora.network.pxe_answer_client._revalidate_target") as revalidate, \
                 patch("feclora.network.pxe_answer_client.ImageManifest.from_json", return_value=manifest), \
                 patch("feclora.network.pxe_answer_client.restore_disk", side_effect=restore) as restore_call:
                resolved = execute_live_pxe_restore({
                    "image_id": "golden", "repository_id": "nas-images",
                    "target": {"wwn": "0x5000c50012345678", "serial": None},
                }, operation_log=log_dir / "operations.jsonl")
            self.assertEqual(resolved, "/dev/sdb")
            revalidate.assert_called_once()
            self.assertNotIn("ignore_signature", restore_call.call_args.kwargs)
            self.assertTrue((log_dir / "operations.jsonl").is_file())

    def test_age_encrypted_image_requests_passphrase_and_forwards_it_to_restore(self):
        with tempfile.TemporaryDirectory() as root:
            repository = Path(root) / "repository"
            repository.mkdir(mode=0o700)
            (repository / "golden.manifest.json").write_text("{}", encoding="utf-8")
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            manifest = SimpleNamespace(
                image_id="golden", image_type="disk",
                artifacts=(SimpleNamespace(encryption="age"),),
            )
            target = {"path": "/dev/sdb", "type": "disk", "wwn": "0x5000c50012345678", "serial": None}
            @contextmanager
            def managed(*_args):
                yield repository
            def restore(*args, **kwargs):
                kwargs["pre_write_callback"]()
            provider = unittest.mock.Mock(return_value="correct horse battery staple")
            with patch("feclora.network.pxe_answer_client._managed_repository", managed), \
                 patch("feclora.network.pxe_answer_client._resolve_target", return_value=target), \
                 patch("feclora.network.pxe_answer_client._revalidate_target"), \
                 patch("feclora.network.pxe_answer_client.ImageManifest.from_json", return_value=manifest), \
                 patch("feclora.network.pxe_answer_client.restore_disk", side_effect=restore) as restore_call:
                execute_live_pxe_restore({
                    "image_id": "golden", "repository_id": "nas-images",
                    "target": {"wwn": "0x5000c50012345678", "serial": None},
                }, operation_log=log_dir / "operations.jsonl", passphrase_provider=provider)
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


if __name__ == "__main__":
    unittest.main()

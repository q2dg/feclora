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
    _wait_for_age_passphrase, _pxe_report_callback, execute_live_pxe_restore, fetch_live_pxe_answer,
    _start_shared_deployment_job,
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

    def test_shared_deployment_job_is_validated_and_client_bound(self):
        from feclora.network.pxe_answer import parse_pxe_answer
        job = {
            "schema_version": 1, "job_id": JOB, "operation": "restore",
            "image_id": "golden", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "auto", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "automatic", "expected_clients": None, "start_deadline": None,
            "repository_id": "nas-images", "boot_method": "pxe",
            "confirm_destructive": True,
            "target_bindings": {"52:54:00:12:34:56": {"wwn": "wwn-first", "serial": None}},
        }
        parsed = parse_pxe_answer(json.dumps(job))
        self.assertEqual(parsed["job_id"], JOB)
        self.assertEqual(parsed["target_bindings"]["52:54:00:12:34:56"]["wwn"], "wwn-first")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(PXEAnswerClientError, "not authorized"):
                fetch_live_pxe_answer(
                    f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                    f"feclora.pxe_answer_url={URL} feclora.pxe_client_mac=52:54:00:12:34:99",
                    destination=Path(root) / "answer.json",
                    downloader=lambda _url: json.dumps(job).encode(),
                )


    def test_shared_multicast_answer_starts_authenticated_client_job(self):
        job = {
            "schema_version": 1, "job_id": JOB, "operation": "restore",
            "image_id": "golden", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
            "network_interface": "auto", "transport": "multicast",
            "multicast_group": "239.10.10.10", "multicast_port": 5000,
            "start_policy": "automatic", "expected_clients": None, "start_deadline": None,
            "repository_id": "nas-images", "boot_method": "pxe",
            "confirm_destructive": True,
            "target_bindings": {
                "52:54:00:12:34:56": {"wwn": "wwn-first", "serial": None},
                "52:54:00:12:34:57": {"wwn": "wwn-second", "serial": None},
            },
        }
        with tempfile.TemporaryDirectory() as root:
            request_dir = Path(root) / "client-jobs"
            config = SimpleNamespace(port=9555)
            with patch("feclora.deployment.runtime_config.load_client_runtime_config", return_value=config), \\
                 patch("feclora.network.pxe_answer_client.Path", side_effect=lambda value: request_dir if value == "/var/lib/feclora/client-jobs" else Path(value)), \\
                 patch("feclora.network.pxe_answer_client.subprocess.run", return_value=SimpleNamespace(returncode=0, stderr="", stdout="")) as run:
                unit = _start_shared_deployment_job({
                    **job, "_server_address": "192.0.2.10",
                })
            self.assertEqual(unit, f"feclora-client@{JOB}.service")
            payload = json.loads((request_dir / f"{JOB}.request.json").read_text())
            self.assertEqual(payload["host"], "192.0.2.10")
            self.assertEqual(payload["port"], 9555)
            self.assertTrue(payload["unattended"])
            self.assertIsNone(payload["network_interface"])
            run.assert_called_once_with(
                ["/usr/bin/systemctl", "start", "--no-block", unit],
                stdin=__import__("subprocess").DEVNULL, capture_output=True,
                text=True, check=False, timeout=10,
            )

    def test_report_callback_posts_job_scoped_client_events_best_effort(self):
        import uuid
        from unittest.mock import MagicMock, Mock
        command_line = (
            f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
            f"feclora.pxe_answer_url={URL} feclora.pxe_client_mac=aa:bb:cc:dd:ee:01"
        )
        response = MagicMock()
        opener = Mock()
        opener.open.return_value = response
        with patch("feclora.network.pxe_answer_client.Path.read_text",
                   return_value=command_line), \
             patch("feclora.network.pxe_answer_client.urllib.request.build_opener",
                   return_value=opener):
            callback = _pxe_report_callback()
            callback({
                "operation_id": str(uuid.uuid4()), "operation": "restore_disk",
                "timestamp": "2026-11-15T12:00:00Z", "status": "started",
                "target": "/dev/sda", "image_id": "golden",
            })
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, f"http://192.0.2.10:8080/pxe/report/{JOB}")
        payload = json.loads(request.data)
        self.assertEqual(payload["client_mac"], "aa:bb:cc:dd:ee:01")
        self.assertEqual(payload["event"]["status"], "started")
        self.assertTrue(payload["event"]["event_id"])

    def test_report_callback_ignores_transport_errors(self):
        command_line = (
            f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
            f"feclora.pxe_answer_url={URL} feclora.pxe_client_mac=aa:bb:cc:dd:ee:01"
        )
        with patch("feclora.network.pxe_answer_client.Path.read_text",
                   return_value=command_line), \
             patch("feclora.network.pxe_answer_client.urllib.request.build_opener",
                   side_effect=OSError("offline")):
            callback = _pxe_report_callback()
            self.assertIsNotNone(callback)
            callback({
                "operation_id": JOB, "operation": "restore_disk",
                "timestamp": "2026-11-15T12:00:00Z", "status": "completed",
                "target": "/dev/sda", "image_id": "golden",
            })

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
                ensure_mounted_and_acquire_usage_lock=lambda identifier: (events.append(("mount", identifier)), (os.open(os.devnull, os.O_RDONLY), True))[1],
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

    def test_remote_repository_propagates_lease_setup_failure(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            def fail_lease(_identifier):
                events.append(("lease-failed", "nas-images"))
                raise RuntimeError("simulated lease failure")
            fake_manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images", "mounted": False}],
                ensure_mounted_and_acquire_usage_lock=lambda identifier: (events.append(("mount", identifier)), fail_lease(identifier))[1],
                unmount=lambda identifier: events.append(("unexpected-client-unmount", identifier)),
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
            ])

    def test_remote_repository_closes_lease_and_unmounts_if_resolution_fails(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            lease_fd = os.open(os.devnull, os.O_RDONLY)
            fake_manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images", "mounted": False}],
                ensure_mounted_and_acquire_usage_lock=lambda identifier: (events.append(("mount", identifier)), (lease_fd, True))[1],
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
            with (
                patch("feclora.storage.s3_repository_manager.REGISTRY", registry),
                patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=FakeS3()),
            ):
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
                 patch("feclora.deployment.restore_execution.restore_disk", side_effect=restore) as restore_call:
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
                 patch("feclora.deployment.restore_execution.restore_disk", side_effect=restore) as restore_call:
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


    def test_restore_failure_releases_remote_repository_lease_and_unmounts(self):
        with tempfile.TemporaryDirectory() as root:
            repository = Path(root) / "repository"
            repository.mkdir(mode=0o700)
            (repository / "golden.manifest.json").write_text("{}", encoding="utf-8")
            registry = Path(root) / "repositories.json"
            registry.touch()
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            lease_fd = os.open(os.devnull, os.O_RDONLY)
            events = []
            manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images"}],
                ensure_mounted_and_acquire_usage_lock=lambda _identifier: (lease_fd, True),
                resolve=lambda _identifier, write=False: str(repository),
                unmount=lambda identifier: events.append(("unmount", identifier)),
            )
            manifest = SimpleNamespace(
                image_id="golden", image_type="disk", artifacts=(),
            )
            target = {
                "path": "/dev/sdb", "type": "disk",
                "wwn": "0x5000c50012345678", "serial": None,
            }
            with (
                patch("feclora.storage.s3_repository_manager.REGISTRY", Path(root) / "s3.json"),
                patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                      return_value=SimpleNamespace(list=lambda: [])),
                patch("feclora.storage.repository_manager.REGISTRY", registry),
                patch("feclora.storage.repository_manager.RemoteRepositoryManager",
                      return_value=manager),
                patch("feclora.network.pxe_answer_client._resolve_target",
                      return_value=target),
                patch("feclora.network.pxe_answer_client._revalidate_target"),
                patch("feclora.network.pxe_answer_client.ImageManifest.from_json",
                      return_value=manifest),
                patch("feclora.deployment.restore_execution.restore_disk",
                      side_effect=RuntimeError("simulated interrupted restore")),
            ):
                with self.assertRaisesRegex(PXEAnswerClientError, "interrupted restore"):
                    execute_live_pxe_restore({
                        "image_id": "golden", "repository_id": "nas-images",
                        "target": {"wwn": "0x5000c50012345678", "serial": None},
                    }, operation_log=log_dir / "operations.jsonl")
            with self.assertRaises(OSError):
                os.fstat(lease_fd)
            self.assertEqual(events, [("unmount", "nas-images")])


    def test_passphrase_cancellation_releases_remote_repository_lease(self):
        with tempfile.TemporaryDirectory() as root:
            repository = Path(root) / "repository"
            repository.mkdir(mode=0o700)
            (repository / "golden.manifest.json").write_text("{}", encoding="utf-8")
            registry = Path(root) / "repositories.json"
            registry.touch()
            log_dir = Path(root) / "state"
            log_dir.mkdir(mode=0o700)
            lease_fd = os.open(os.devnull, os.O_RDONLY)
            events = []
            manager = SimpleNamespace(
                list=lambda: [{"id": "nas-images"}],
                ensure_mounted_and_acquire_usage_lock=lambda _identifier: (lease_fd, True),
                resolve=lambda _identifier, write=False: str(repository),
                unmount=lambda identifier: events.append(("unmount", identifier)),
            )
            manifest = SimpleNamespace(
                image_id="golden", image_type="disk",
                artifacts=(SimpleNamespace(encryption="age"),),
            )
            target = {
                "path": "/dev/sdb", "type": "disk",
                "wwn": "0x5000c50012345678", "serial": None,
            }
            with (
                patch("feclora.storage.s3_repository_manager.REGISTRY", Path(root) / "s3.json"),
                patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                      return_value=SimpleNamespace(list=lambda: [])),
                patch("feclora.storage.repository_manager.REGISTRY", registry),
                patch("feclora.storage.repository_manager.RemoteRepositoryManager",
                      return_value=manager),
                patch("feclora.network.pxe_answer_client._resolve_target",
                      return_value=target),
                patch("feclora.network.pxe_answer_client.ImageManifest.from_json",
                      return_value=manifest),
                patch("feclora.deployment.restore_execution.restore_disk") as restore,
            ):
                with self.assertRaisesRegex(PXEAnswerClientError, "passphrase unavailable"):
                    execute_live_pxe_restore({
                        "image_id": "golden", "repository_id": "nas-images",
                        "target": {"wwn": "0x5000c50012345678", "serial": None},
                    }, operation_log=log_dir / "operations.jsonl",
                       passphrase_provider=lambda: (_ for _ in ()).throw(
                           PXEAnswerClientError("passphrase unavailable")
                       ))
            restore.assert_not_called()
            with self.assertRaises(OSError):
                os.fstat(lease_fd)
            self.assertEqual(events, [("unmount", "nas-images")])


if __name__ == "__main__":
    unittest.main()

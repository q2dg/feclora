import os
import stat
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

from feclora.deployment.coordinator import ClientState, JobState
from feclora.deployment.service import DeploymentService, DeploymentServiceError, recover_stale_ipc_socket


class FakeCoordinator:
    def __init__(self, state=JobState.CREATED, clients=()):
        self.state = state
        self._clients = tuple(clients)

    def clients(self):
        return self._clients


class FakeControl:
    bound_address = ("192.0.2.10", 9443)
    listener_errors = []

    def __init__(self, coordinator):
        self.cancelled = False
        self.coordinator = coordinator

    def cancel(self):
        self.cancelled = True
        self.coordinator.state = JobState.CANCELLED

    def client_progress(self):
        return {}


class FakeThread:
    instances = []

    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


def make_service(transport="unicast", clients=()):
    service = DeploymentService.__new__(DeploymentService)
    service.job = SimpleNamespace(
        job_id="12345678-1234-4234-8234-123456789abc",
        operation="restore", image_id="image-1", transport=transport,
        authorized_clients=tuple(item.mac_address for item in clients),
        network_interface="enp1s0",
        multicast_group="239.10.10.10",
    )
    service.coordinator = FakeCoordinator(clients=clients)
    service.control = FakeControl(service.coordinator)
    service._worker = None
    service._worker_lock = threading.RLock()
    service._stop_event = threading.Event()
    service._arm_requested = False
    service._last_error = None
    service._run_job = lambda: None
    return service


def _fd_is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


class DeploymentServiceCommandTests(unittest.TestCase):
    def setUp(self):
        FakeThread.instances.clear()

    def test_status_includes_per_client_progress(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.RUNNING, detail=None)
        service = make_service(clients=(client,))
        progress = {
            client.mac_address: {
                "phase": "restore", "completed_bytes": 1024,
                "total_bytes": 4096, "bytes_per_second": 512.0,
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        }
        service.control.client_progress = mock.Mock(return_value=progress)
        status = service._status()
        self.assertEqual(status["clients"][0]["progress"]["completed_bytes"], 1024)
        service.control.client_progress.assert_called_once_with()

    def test_arm_requires_exact_job_specific_confirmation(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(clients=(client,))
        with mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            with self.assertRaisesRegex(DeploymentServiceError, "exact job-specific"):
                service._handle_ipc("arm", {
                    "job_id": service.job.job_id, "confirmation": "ARM wrong",
                })

    def test_clone_arm_requires_source_and_enrolled_peer_confirmation(self):
        mac = "02:00:00:00:00:01"
        client = SimpleNamespace(mac_address=mac, state=ClientState.READY, detail=None)
        service = make_service(clients=(client,))
        service.job.operation = "clone"
        service.job.source_device = "/dev/sda"
        service.config = SimpleNamespace(client_identity_to_mac={"URI:feclora-client": mac})
        expected = (
            "ARM " + service.job.job_id
            + " AND READ /dev/sda TO URI:feclora-client"
        )
        with self.assertRaisesRegex(DeploymentServiceError, "exact job-specific"):
            service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM " + service.job.job_id,
            })
        with mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            result = service._handle_ipc("arm", {
                "job_id": service.job.job_id, "confirmation": expected,
            })
        self.assertTrue(result["accepted"])
        self.assertTrue(service._arm_requested)

    def test_arm_requires_every_authorized_client_ready(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.CONNECTED, detail=None)
        service = make_service(clients=(client,))
        with self.assertRaisesRegex(DeploymentServiceError, "READY"):
            service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM " + service.job.job_id,
            })

    def test_arm_starts_one_worker_after_all_clients_are_ready(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(clients=(client,))
        with mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            result = service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM " + service.job.job_id,
            })
        self.assertTrue(result["accepted"])
        self.assertTrue(service._arm_requested)
        self.assertEqual(len(FakeThread.instances), 1)
        self.assertTrue(FakeThread.instances[0].started)

    def test_multicast_arm_requires_igmp_verification_phrase(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(transport="multicast", clients=(client,))
        with mock.patch(
            "feclora.deployment.service.inspect_multicast_interface",
            return_value=SimpleNamespace(route_interface="enp1s0"),
        ) as preflight, mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            result = service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM MULTICAST " + service.job.job_id + " IGMP-VERIFIED",
            })
        self.assertTrue(result["accepted"])
        preflight.assert_called_once_with("enp1s0", "239.10.10.10", role="sender")

    def test_multicast_requires_distinct_typed_confirmation(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(transport="multicast", clients=(client,))
        with self.assertRaisesRegex(DeploymentServiceError, "exact job-specific"):
            service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM " + service.job.job_id,
            })

    def test_arm_is_rejected_after_shutdown_begins(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(clients=(client,))
        service._stop_event = threading.Event()
        service._stop_event.set()
        with mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            with self.assertRaisesRegex(DeploymentServiceError, "shutdown has begun"):
                service._handle_ipc("arm", {
                    "job_id": service.job.job_id,
                    "confirmation": "ARM " + service.job.job_id,
                })
        self.assertEqual(FakeThread.instances, [])

    def test_cancel_is_available_only_before_arm(self):
        service = make_service()
        result = service._handle_ipc("cancel", {
            "job_id": service.job.job_id,
            "confirmation": "CANCEL " + service.job.job_id,
        })
        self.assertTrue(service.control.cancelled)
        self.assertEqual(result["job_state"], "cancelled")

    def test_cancel_rejects_running_job(self):
        service = make_service()
        service.coordinator.state = JobState.RUNNING
        with self.assertRaisesRegex(DeploymentServiceError, "only before arming"):
            service._handle_ipc("cancel", {
                "job_id": service.job.job_id,
                "confirmation": "CANCEL " + service.job.job_id,
            })

    def test_remote_repository_lease_is_held_until_service_shutdown_finishes(self):
        lease_fd = os.open(os.devnull, os.O_RDONLY)
        self.addCleanup(lambda: os.close(lease_fd) if _fd_is_open(lease_fd) else None)
        service = make_service()
        service.job.repository_id = "images"
        service.config = SimpleNamespace(
            bind_address="192.0.2.10", port=9443,
            server_minisign_public_key="public-key",
        )
        service._lock_fd = None
        service._pxe_state = None
        service.firewall = SimpleNamespace(on_change=None)
        service._firewall_changed = lambda _state: None
        service._write_firewall_state = lambda _state: None
        service.journal = mock.Mock()
        service._acquire_instance_lock = lambda: None
        service._stop_event = threading.Event()

        class Worker:
            joined = False

            def is_alive(self):
                return True

            def join(self):
                os.fstat(lease_fd)
                self.joined = True

        worker = Worker()
        service._worker = worker

        class IPC:
            def start(self):
                service._stop_event.set()

            def stop(self):
                pass

        service.ipc = IPC()

        class Control:
            def start(self, *_args, **_kwargs):
                pass

            def stop(self):
                os.fstat(lease_fd)
                if not worker.joined:
                    raise AssertionError("control sessions stopped before the active worker finished")

        service.control = Control()
        manager = mock.Mock()
        manager.acquire_usage_lock.return_value = lease_fd
        manager.resolve.return_value = "/mnt/feclora/images"

        with mock.patch(
            "feclora.storage.repository_manager.RemoteRepositoryManager",
            return_value=manager,
        ), mock.patch("feclora.deployment.service.verify_manifest_signature"), mock.patch(
            "feclora.deployment.service.recover_stale_runtime_artifacts",
        ):
            service.run()

        manager.acquire_usage_lock.assert_called_once_with("images")
        manager.resolve.assert_called_once_with("images", write=False)
        self.assertTrue(worker.joined)
        with self.assertRaises(OSError):
            os.fstat(lease_fd)


    def test_stale_private_root_socket_is_removed_after_lock_is_held(self):
        info = SimpleNamespace(
            st_mode=stat.S_IFSOCK | 0o600, st_uid=0, st_dev=12, st_ino=34,
        )
        with mock.patch("feclora.deployment.service.os.lstat", return_value=info), \
             mock.patch("feclora.deployment.service.os.open", return_value=99), \
             mock.patch("feclora.deployment.service.os.fsync"), \
             mock.patch("feclora.deployment.service.os.close"), \
             mock.patch("pathlib.Path.unlink") as unlink:
            recover_stale_ipc_socket(lock_held=True)
        unlink.assert_called_once()

    def test_stale_ipc_recovery_refuses_regular_files(self):
        info = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0, st_dev=12, st_ino=34,
        )
        with mock.patch("feclora.deployment.service.os.lstat", return_value=info):
            with self.assertRaisesRegex(DeploymentServiceError, "not a private root-owned Unix socket"):
                recover_stale_ipc_socket(lock_held=True)


if __name__ == "__main__":
    unittest.main()

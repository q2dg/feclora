import threading
import unittest
from unittest import mock
from types import SimpleNamespace

from feclora.deployment.coordinator import ClientState, JobState
from feclora.deployment.service import DeploymentService, DeploymentServiceError


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
    )
    service.coordinator = FakeCoordinator(clients=clients)
    service.control = FakeControl(service.coordinator)
    service._worker = None
    service._worker_lock = threading.RLock()
    service._arm_requested = False
    service._last_error = None
    service._run_job = lambda: None
    return service


class DeploymentServiceCommandTests(unittest.TestCase):
    def setUp(self):
        FakeThread.instances.clear()

    def test_arm_requires_exact_job_specific_confirmation(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(clients=(client,))
        with mock.patch("feclora.deployment.service.threading.Thread", FakeThread):
            with self.assertRaisesRegex(DeploymentServiceError, "exact job-specific"):
                service._handle_ipc("arm", {
                    "job_id": service.job.job_id, "confirmation": "ARM wrong",
                })

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

    def test_multicast_requires_distinct_typed_confirmation(self):
        client = SimpleNamespace(mac_address="02:00:00:00:00:01", state=ClientState.READY, detail=None)
        service = make_service(transport="multicast", clients=(client,))
        with self.assertRaisesRegex(DeploymentServiceError, "exact job-specific"):
            service._handle_ipc("arm", {
                "job_id": service.job.job_id,
                "confirmation": "ARM " + service.job.job_id,
            })

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


if __name__ == "__main__":
    unittest.main()

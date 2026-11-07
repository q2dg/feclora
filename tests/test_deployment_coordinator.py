import unittest
from datetime import datetime, timezone

from feclora.deployment.coordinator import (
    ClientState,
    CoordinatorError,
    DeploymentCoordinator,
    JobState,
)
from feclora.deployment.job import DeploymentJob


def make_job(**changes):
    payload = {
        "schema_version": 1,
        "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "operation": "restore",
        "image_id": "golden-image",
        "authorized_clients": [
            "52:54:00:12:34:56",
            "52:54:00:12:34:57",
        ],
        "network_interface": "enp1s0",
        "transport": "unicast",
        "multicast_group": None,
        "multicast_port": None,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
    }
    payload.update(changes)
    return DeploymentJob.from_dict(payload)


class DeploymentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = DeploymentCoordinator(make_job())

    def connect(self, mac="52:54:00:12:34:56"):
        self.coordinator.register_client(mac, authenticated=True)
        self.coordinator.mark_ready(mac)

    def test_rejects_unauthenticated_or_unauthorized_clients(self):
        with self.assertRaisesRegex(CoordinatorError, "not authenticated"):
            self.coordinator.register_client("52:54:00:12:34:56", authenticated=False)
        with self.assertRaisesRegex(CoordinatorError, "allowlist"):
            self.coordinator.register_client("52:54:00:12:34:99", authenticated=True)

    def test_requires_ready_client_before_manual_arm(self):
        with self.assertRaisesRegex(CoordinatorError, "condition"):
            self.coordinator.arm()
        self.connect()
        self.coordinator.arm()
        self.assertEqual(self.coordinator.state, JobState.ARMED)

    def test_expected_client_threshold(self):
        coordinator = DeploymentCoordinator(make_job(
            start_policy="expected_clients", expected_clients=2
        ))
        for mac in ("52:54:00:12:34:56", "52:54:00:12:34:57"):
            coordinator.register_client(mac, authenticated=True)
            coordinator.mark_ready(mac)
        self.assertTrue(coordinator.can_start())
        coordinator.arm()
        self.assertEqual(coordinator.state, JobState.ARMED)

    def test_deadline_policy_uses_injected_clock(self):
        coordinator = DeploymentCoordinator(
            make_job(
                start_policy="deadline",
                start_deadline="2030-01-01T12:00:00Z",
            ),
            clock=lambda: datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.connect_with(coordinator)
        self.assertTrue(coordinator.can_start())
        coordinator.arm()

    def connect_with(self, coordinator):
        mac = "52:54:00:12:34:56"
        coordinator.register_client(mac, authenticated=True)
        coordinator.mark_ready(mac)

    def test_cannot_arm_or_join_after_arm(self):
        self.connect()
        self.coordinator.arm()
        with self.assertRaisesRegex(CoordinatorError, "after the job is armed"):
            self.coordinator.register_client("52:54:00:12:34:57", authenticated=True)

    def test_tracks_success_and_failure_per_client(self):
        self.connect()
        self.coordinator.arm()
        self.coordinator.mark_running("52:54:00:12:34:56")
        result = self.coordinator.report_result(
            "52:54:00:12:34:56", success=True, detail="verified"
        )
        self.assertEqual(result.state, ClientState.SUCCEEDED)
        self.assertEqual(self.coordinator.state, JobState.COMPLETED)
        self.assertEqual(self.coordinator.summary()["succeeded"], 1)

    def test_any_failed_client_fails_the_job(self):
        self.connect()
        self.coordinator.arm()
        self.coordinator.mark_running("52:54:00:12:34:56")
        self.coordinator.report_result(
            "52:54:00:12:34:56", success=False, detail="write error"
        )
        self.assertEqual(self.coordinator.state, JobState.FAILED)

    def test_cancellation_is_terminal(self):
        self.coordinator.cancel()
        self.assertEqual(self.coordinator.state, JobState.CANCELLED)
        with self.assertRaisesRegex(CoordinatorError, "terminal"):
            self.coordinator.arm()

    def test_cannot_report_result_without_running(self):
        self.connect()
        with self.assertRaisesRegex(CoordinatorError, "running"):
            self.coordinator.report_result("52:54:00:12:34:56", success=True)


if __name__ == "__main__":
    unittest.main()

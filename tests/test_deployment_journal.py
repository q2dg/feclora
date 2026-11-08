import os
import tempfile
import unittest

from feclora.deployment.coordinator import (
    ClientState, CoordinatorError, DeploymentCoordinator, JobState,
)
from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
from feclora.deployment.job import DeploymentJob


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
MAC = "52:54:00:12:34:56"


def make_job():
    return DeploymentJob.from_dict({
        "schema_version": 1, "job_id": JOB_ID, "operation": "restore",
        "image_id": "golden-image", "authorized_clients": [MAC],
        "network_interface": "enp1s0", "transport": "unicast",
        "multicast_group": None, "multicast_port": None,
        "start_policy": "manual", "expected_clients": None, "start_deadline": None,
    })


class DeploymentJournalTests(unittest.TestCase):
    def test_journal_persists_and_verifies_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            journal({
                "timestamp": "2026-11-08T12:00:00+00:00",
                "job_id": JOB_ID, "event": "job_created", "job_state": "created",
            })
            journal({
                "timestamp": "2026-11-08T12:00:01+00:00",
                "job_id": JOB_ID, "event": "job_armed", "job_state": "armed",
            })
            reopened = DeploymentJournal.inspect(path)
            self.assertEqual(len(reopened.events), 2)
            self.assertEqual(reopened.latest_state()["event"], "job_armed")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_journal_rejects_tampered_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            journal({
                "timestamp": "2026-11-08T12:00:00+00:00",
                "job_id": JOB_ID, "event": "job_created", "job_state": "created",
            })
            with open(path, "rb") as stream:
                payload = stream.read()
            with open(path, "wb") as stream:
                stream.write(payload.replace(b"created", b"changed"))
            with self.assertRaisesRegex(DeploymentJournalError, "hash mismatch"):
                DeploymentJournal(path, JOB_ID)

    def test_journal_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "target")
            path = os.path.join(directory, "job.jsonl")
            with open(target, "w", encoding="ascii") as stream:
                stream.write("")
            os.symlink(target, path)
            with self.assertRaises(DeploymentJournalError):
                DeploymentJournal(path, JOB_ID)

    def test_coordinator_persists_every_transition_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(os.path.join(directory, "job.jsonl"), JOB_ID)
            coordinator = DeploymentCoordinator(make_job(), event_sink=journal)
            coordinator.register_client(MAC, authenticated=True)
            coordinator.mark_ready(MAC)
            coordinator.arm()
            coordinator.mark_running(MAC)
            coordinator.report_result(MAC, success=True, detail="verified")
            self.assertEqual(coordinator.state, JobState.COMPLETED)
            self.assertEqual(
                [event["event"] for event in journal.events],
                [
                    "job_created", "client_authenticated", "client_ready",
                    "job_armed", "client_running", "client_result",
                ],
            )
            self.assertEqual(journal.latest_state()["job_state"], "completed")

    def test_recovery_report_reconstructs_interrupted_job_without_resuming(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            coordinator = DeploymentCoordinator(make_job(), event_sink=journal)
            coordinator.register_client(MAC, authenticated=True)
            coordinator.mark_ready(MAC)
            coordinator.arm()
            coordinator.mark_running(MAC)
            report = DeploymentJournal.inspect(path).recovery_report()
            self.assertTrue(report["interrupted"])
            self.assertFalse(report["automatic_resume"])
            self.assertEqual(report["job_state"], "running")
            self.assertEqual(report["clients"][MAC]["state"], "running")
            self.assertEqual(report["job"]["job_id"], JOB_ID)
    def test_journal_failure_does_not_mutate_coordinator_state(self):
        def failing_sink(event):
            if event["event"] == "client_ready":
                raise OSError("disk full")
        coordinator = DeploymentCoordinator(make_job(), event_sink=failing_sink)
        coordinator.register_client(MAC, authenticated=True)
        with self.assertRaisesRegex(CoordinatorError, "could not persist"):
            coordinator.mark_ready(MAC)
        self.assertEqual(coordinator.clients()[0].state, ClientState.CONNECTED)
        self.assertEqual(coordinator.state, JobState.CREATED)


if __name__ == "__main__":
    unittest.main()

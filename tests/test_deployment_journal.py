import os
import tempfile
import threading
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

    def test_caller_cannot_mutate_event_after_append(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            payload = {
                "timestamp": "2026-11-08T12:00:00+00:00",
                "job_id": JOB_ID, "event": "job_created", "job_state": "created",
                "metadata": {"authorized_clients": [MAC]},
            }
            journal(payload)
            payload["metadata"]["authorized_clients"].clear()
            self.assertEqual(journal.events[0]["metadata"]["authorized_clients"], [MAC])
            reopened = DeploymentJournal.inspect(path)
            self.assertEqual(reopened.events[0]["metadata"]["authorized_clients"], [MAC])

    def test_returned_events_and_latest_state_cannot_mutate_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            journal({
                "timestamp": "2026-11-08T12:00:00+00:00",
                "job_id": JOB_ID, "event": "job_created", "job_state": "created",
                "job": {"authorized_clients": [MAC]},
            })
            exposed = journal.events
            exposed[0]["job"]["authorized_clients"].append("02:00:00:00:00:01")
            latest = journal.latest_state()
            latest["job"]["authorized_clients"].clear()
            reopened = DeploymentJournal.inspect(path)
            self.assertEqual(reopened.events[0]["job"]["authorized_clients"], [MAC])
            self.assertEqual(journal.events[0]["job"]["authorized_clients"], [MAC])

    def test_multiple_journal_instances_serialize_appends(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            first = DeploymentJournal(path, JOB_ID)
            second = DeploymentJournal(path, JOB_ID)
            first({
                "timestamp": "2026-11-08T12:00:00+00:00",
                "job_id": JOB_ID, "event": "job_created", "job_state": "created",
            })
            second({
                "timestamp": "2026-11-08T12:00:01+00:00",
                "job_id": JOB_ID, "event": "job_armed", "job_state": "armed",
            })
            first({
                "timestamp": "2026-11-08T12:00:02+00:00",
                "job_id": JOB_ID, "event": "job_running", "job_state": "running",
            })
            reopened = DeploymentJournal.inspect(path)
            self.assertEqual(
                [event["sequence"] for event in reopened.events],
                [1, 2, 3],
            )
            self.assertEqual(
                [event["event"] for event in reopened.events],
                ["job_created", "job_armed", "job_running"],
            )

    def test_concurrent_journal_instances_keep_one_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journals = [
                DeploymentJournal(path, JOB_ID),
                DeploymentJournal(path, JOB_ID),
            ]
            barrier = threading.Barrier(len(journals))
            errors = []

            def append_events(index, journal):
                try:
                    barrier.wait()
                    for event_number in range(10):
                        journal({
                            "timestamp": f"2026-11-08T12:00:{event_number:02d}+00:00",
                            "job_id": JOB_ID,
                            "event": f"writer_{index}",
                            "job_state": "created",
                        })
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=append_events, args=(index, journal))
                for index, journal in enumerate(journals)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            events = DeploymentJournal.inspect(path).events
            self.assertEqual(len(events), 20)
            self.assertEqual(
                [event["sequence"] for event in events],
                list(range(1, 21)),
            )

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

    def test_journal_rejects_truncated_final_record_without_newline(self):
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
                stream.write(payload[:-1])
            with self.assertRaisesRegex(DeploymentJournalError, "incomplete event record"):
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
    def test_recovery_report_retains_last_durable_client_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            coordinator = DeploymentCoordinator(make_job(), event_sink=journal)
            coordinator.register_client(MAC, authenticated=True)
            coordinator.mark_ready(MAC)
            coordinator.arm()
            coordinator.mark_running(MAC)
            journal({
                "timestamp": "2026-11-08T12:00:02+00:00",
                "job_id": JOB_ID, "event": "client_progress", "job_state": "running",
                "client_mac": MAC, "client_state": "running",
                "progress": {
                    "phase": "restore", "completed_bytes": 1048576,
                    "total_bytes": 4194304, "bytes_per_second": 512.0,
                    "updated_at": "2026-11-08T12:00:02+00:00",
                },
            })
            report = DeploymentJournal.inspect(path).recovery_report()
            self.assertTrue(report["interrupted"])
            self.assertFalse(report["automatic_resume"])
            self.assertEqual(report["progress"][MAC]["completed_bytes"], 1048576)

    def test_coordinator_rehydrates_interrupted_state_without_resuming(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            coordinator = DeploymentCoordinator(make_job(), event_sink=journal)
            coordinator.register_client(MAC, authenticated=True)
            coordinator.mark_ready(MAC)
            coordinator.arm()
            coordinator.mark_running(MAC)

            reopened = DeploymentJournal.inspect(path)
            recovered = DeploymentCoordinator.from_journal(make_job(), reopened)

            self.assertEqual(recovered.state, JobState.RUNNING)
            self.assertEqual(recovered.clients()[0].state, ClientState.RUNNING)
            self.assertEqual(len(reopened.events), 5)
            with self.assertRaisesRegex(CoordinatorError, "newly created"):
                recovered.arm()
            self.assertEqual(len(reopened.events), 5)

    def test_coordinator_rejects_journal_for_another_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            DeploymentCoordinator(make_job(), event_sink=journal)
            other_job = DeploymentJob.from_dict({
                **make_job().to_dict(),
                "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d480",
            })
            with self.assertRaisesRegex(CoordinatorError, "does not match"):
                DeploymentCoordinator.from_journal(other_job, journal)

    def test_operator_reconciliation_is_durable_and_never_resumes_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "job.jsonl")
            journal = DeploymentJournal(path, JOB_ID)
            coordinator = DeploymentCoordinator(make_job(), event_sink=journal)
            coordinator.register_client(MAC, authenticated=True)
            coordinator.mark_ready(MAC)
            coordinator.arm()
            coordinator.mark_running(MAC)
            with self.assertRaisesRegex(DeploymentJournalError, "confirmation"):
                journal.reconcile_after_operator_inspection("yes")
            report = journal.reconcile_after_operator_inspection(f"RECONCILE {JOB_ID}")
            self.assertFalse(report["interrupted"])
            self.assertTrue(report["operator_reconciled"])
            self.assertFalse(report["automatic_resume"])
            self.assertEqual(report["job_state"], "failed")
            reopened = DeploymentJournal.inspect(path).recovery_report()
            self.assertTrue(reopened["operator_reconciled"])
            self.assertEqual(reopened["last_event"], "operator_reconciled")

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

    def test_fresh_job_definition_is_not_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(os.path.join(directory, "job.jsonl"), JOB_ID)
            DeploymentCoordinator(make_job(), event_sink=journal)
            report = journal.recovery_report()
            self.assertFalse(report["interrupted"])
            self.assertEqual(report["event_count"], 1)

    def test_service_crash_before_client_connect_is_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(os.path.join(directory, "job.jsonl"), JOB_ID)
            DeploymentCoordinator(make_job(), event_sink=journal)
            journal({
                "timestamp": "2026-11-08T12:00:01+00:00",
                "job_id": JOB_ID, "event": "service_started", "job_state": "created",
            })
            self.assertTrue(journal.recovery_report()["interrupted"])

    def test_clean_unarmed_service_stop_is_restartable(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(os.path.join(directory, "job.jsonl"), JOB_ID)
            DeploymentCoordinator(make_job(), event_sink=journal)
            for event in ("service_started", "service_stopped"):
                journal({
                    "timestamp": "2026-11-08T12:00:01+00:00",
                    "job_id": JOB_ID, "event": event, "job_state": "created",
                })
            self.assertFalse(journal.recovery_report()["interrupted"])


if __name__ == "__main__":
    unittest.main()

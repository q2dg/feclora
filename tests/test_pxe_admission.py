import tempfile
import unittest
from pathlib import Path

from feclora.network.pxe_admission import PXEAdmission, PXEAdmissionError


class PXEAdmissionTests(unittest.TestCase):
    def test_unique_macs_consume_slots_once_and_retries_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "boot.ipxe").write_text("#!ipxe\\necho boot\\n", encoding="utf-8")
            admission = PXEAdmission(
                str(Path(tmp) / "state.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/", boot_script_path=str(Path(tmp) / "boot.ipxe"),
                max_clients=2, max_duration_seconds=None,
            )
            self.assertEqual(admission.admit("AA:BB:CC:DD:EE:01"), (True, "registered"))
            self.assertEqual(admission.admit("aa:bb:cc:dd:ee:01"), (True, "already registered"))
            self.assertEqual(admission.admit("aa:bb:cc:dd:ee:02"), (True, "registered"))
            self.assertEqual(admission.admit("aa:bb:cc:dd:ee:03"), (False, "PXE client limit has been reached"))
            self.assertEqual(admission.status()["clients_served"], 2)

    def test_time_limit_stops_even_registered_clients(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            admission = PXEAdmission(
                str(Path(tmp) / "state.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/", boot_script_path=str(Path(tmp) / "boot.ipxe"),
                max_clients=None, max_duration_seconds=60, clock=lambda: now[0],
            )
            self.assertTrue(admission.admit("aa:bb:cc:dd:ee:01")[0])
            self.assertTrue(admission.is_admitted("aa:bb:cc:dd:ee:01"))
            now[0] = 1060.0
            self.assertFalse(admission.admit("aa:bb:cc:dd:ee:01")[0])
            self.assertFalse(admission.status()["accepting"])

    def test_unlimited_admission_registers_macs_and_report_is_idempotent(self):
        import uuid
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            http_root = root / "http"
            job_id = "123e4567-e89b-12d3-a456-426614174000"
            answer = http_root / "answers" / job_id / "answer.json"
            answer.parent.mkdir(parents=True)
            answer.write_text("{}", encoding="utf-8")
            report_path = root / "state" / "remote-reports.jsonl"
            admission = PXEAdmission(
                str(root / "state" / "admission.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/",
                boot_script_path=str(root / "boot.ipxe"),
                max_clients=None, max_duration_seconds=None,
                http_root=str(http_root), report_log_path=str(report_path),
            )
            mac = "aa:bb:cc:dd:ee:01"
            self.assertTrue(admission.admit(mac)[0])
            event = {
                "event_id": str(uuid.uuid4()),
                "operation_id": str(uuid.uuid4()),
                "operation": "restore_disk",
                "timestamp": "2026-11-15T12:00:00Z",
                "status": "started",
                "target": "/dev/sda",
                "image_id": "fedora-workstation",
            }
            self.assertTrue(admission.record_report(job_id, mac, event))
            self.assertFalse(admission.record_report(job_id, mac, event))
            # Revoking the answer prevents new boots but must not discard the
            # terminal status of a restore that already reported its start.
            answer.parent.chmod(0o700)
            answer.unlink()
            progress = {
                **event, "event_id": str(uuid.uuid4()), "status": "progress",
                "bytes_done": 100, "bytes_total": 100,
            }
            self.assertTrue(admission.record_report(job_id, mac, progress))
            rows = [__import__("json").loads(line) for line in report_path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["client_mac"], mac)
            self.assertEqual(rows[0]["job_id"], job_id)
            self.assertEqual(rows[1]["status"], "progress")

    def test_report_journal_enforces_monotonic_progress_and_terminal_state(self):
        import json
        import uuid

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            http_root = root / "http"
            job_id = "123e4567-e89b-12d3-a456-426614174000"
            answer = http_root / "answers" / job_id / "answer.json"
            answer.parent.mkdir(parents=True)
            answer.write_text("{}", encoding="utf-8")
            admission = PXEAdmission(
                str(root / "state" / "admission.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/",
                boot_script_path=str(root / "boot.ipxe"),
                max_clients=None, max_duration_seconds=None,
                http_root=str(http_root),
                report_log_path=str(root / "state" / "remote-reports.jsonl"),
            )
            mac = "aa:bb:cc:dd:ee:01"
            self.assertTrue(admission.admit(mac)[0])
            operation_id = str(uuid.uuid4())

            def event(status, **fields):
                return {
                    "event_id": str(uuid.uuid4()),
                    "operation_id": operation_id,
                    "operation": "restore_disk",
                    "timestamp": "2026-11-15T12:00:00Z",
                    "status": status,
                    "target": "/dev/sda",
                    "image_id": "fedora-workstation",
                    **fields,
                }

            self.assertTrue(admission.record_report(job_id, mac, event("started")))
            self.assertTrue(admission.record_report(
                job_id, mac, event("progress", bytes_done=100, bytes_total=200),
            ))
            with self.assertRaisesRegex(PXEAdmissionError, "cannot move backwards"):
                admission.record_report(
                    job_id, mac, event("progress", bytes_done=90, bytes_total=200),
                )
            with self.assertRaisesRegex(PXEAdmissionError, "total cannot change"):
                admission.record_report(
                    job_id, mac, event("progress", bytes_done=110, bytes_total=300),
                )
            self.assertTrue(admission.record_report(job_id, mac, event("completed")))
            with self.assertRaisesRegex(Exception, "terminal report"):
                admission.record_report(
                    job_id, mac, event("progress", bytes_done=200, bytes_total=200),
                )
            rows = [json.loads(line) for line in
                    (root / "state" / "remote-reports.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in rows],
                             ["started", "progress", "completed"])

    def test_report_event_id_cannot_be_reused_for_different_payload(self):
        import uuid

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            http_root = root / "http"
            job_id = "123e4567-e89b-12d3-a456-426614174000"
            answer = http_root / "answers" / job_id / "answer.json"
            answer.parent.mkdir(parents=True)
            answer.write_text("{}", encoding="utf-8")
            admission = PXEAdmission(
                str(root / "state" / "admission.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/",
                boot_script_path=str(root / "boot.ipxe"),
                max_clients=None, max_duration_seconds=None,
                http_root=str(http_root),
                report_log_path=str(root / "state" / "remote-reports.jsonl"),
            )
            mac = "aa:bb:cc:dd:ee:01"
            self.assertTrue(admission.admit(mac)[0])
            operation_id = str(uuid.uuid4())
            report = {
                "event_id": str(uuid.uuid4()),
                "operation_id": operation_id,
                "operation": "restore_disk",
                "timestamp": "2026-11-15T12:00:00Z",
                "status": "started",
                "target": "/dev/sda",
                "image_id": "fedora-workstation",
            }
            self.assertTrue(admission.record_report(job_id, mac, report))
            self.assertFalse(admission.record_report(job_id, mac, report))
            changed = {**report, "target": "/dev/sdb"}
            with self.assertRaisesRegex(Exception, "reused for a different report"):
                admission.record_report(job_id, mac, changed)

    def test_state_survives_admission_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            kwargs = dict(
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/", boot_script_path=str(Path(tmp) / "boot.ipxe"),
                max_clients=1, max_duration_seconds=None,
            )
            (Path(tmp) / "boot.ipxe").write_text("#!ipxe\\necho boot\\n", encoding="utf-8")
            first = PXEAdmission(path, **kwargs)
            self.assertTrue(first.admit("aa:bb:cc:dd:ee:01")[0])
            second = PXEAdmission(path, **kwargs)
            self.assertFalse(second.admit("aa:bb:cc:dd:ee:02")[0])
            self.assertTrue(second.admit("aa:bb:cc:dd:ee:01")[0])

    def test_unlimited_profile_admits_any_valid_mac_without_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            admission = PXEAdmission(
                str(Path(tmp) / "state.json"),
                boot_url_prefix="http://192.0.2.1:8080/pxe/boot/", boot_script_path=str(Path(tmp) / "boot.ipxe"),
                max_clients=None, max_duration_seconds=None,
            )
            self.assertTrue(admission.admit("aa:bb:cc:dd:ee:01")[0])
            self.assertTrue(admission.admit("aa:bb:cc:dd:ee:02")[0])
            self.assertFalse(admission.is_admitted("aa:bb:cc:dd:ee:ff"))
            self.assertIsNone(admission.status()["clients_served"])
            self.assertFalse(admission.admit("not-a-mac")[0])


if __name__ == "__main__":
    unittest.main()

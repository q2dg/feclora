import tempfile
import unittest
from pathlib import Path

from feclora.network.pxe_admission import PXEAdmission, PXEAdmissionError


class PXEAdmissionTests(unittest.TestCase):
    def test_unique_macs_consume_slots_once_and_retries_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            admission = PXEAdmission(
                str(Path(tmp) / "state.json"),
                answer_boot_url="http://192.0.2.1:8080/unattended-answer-boot.ipxe",
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
                answer_boot_url="http://192.0.2.1:8080/unattended-answer-boot.ipxe",
                max_clients=None, max_duration_seconds=60, clock=lambda: now[0],
            )
            self.assertTrue(admission.admit("aa:bb:cc:dd:ee:01")[0])
            now[0] = 1060.0
            self.assertFalse(admission.admit("aa:bb:cc:dd:ee:01")[0])
            self.assertFalse(admission.status()["accepting"])

    def test_state_survives_admission_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            kwargs = dict(
                answer_boot_url="http://192.0.2.1:8080/unattended-answer-boot.ipxe",
                max_clients=1, max_duration_seconds=None,
            )
            first = PXEAdmission(path, **kwargs)
            self.assertTrue(first.admit("aa:bb:cc:dd:ee:01")[0])
            second = PXEAdmission(path, **kwargs)
            self.assertFalse(second.admit("aa:bb:cc:dd:ee:02")[0])
            self.assertTrue(second.admit("aa:bb:cc:dd:ee:01")[0])

    def test_invalid_mac_and_unbounded_profile_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PXEAdmissionError):
                PXEAdmission(
                    str(Path(tmp) / "state.json"),
                    answer_boot_url="http://192.0.2.1:8080/unattended-answer-boot.ipxe",
                    max_clients=None, max_duration_seconds=None,
                )
            admission = PXEAdmission(
                str(Path(tmp) / "state.json"),
                answer_boot_url="http://192.0.2.1:8080/unattended-answer-boot.ipxe",
                max_clients=2, max_duration_seconds=None,
            )
            self.assertFalse(admission.admit("not-a-mac")[0])


if __name__ == "__main__":
    unittest.main()

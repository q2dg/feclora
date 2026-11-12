import tempfile
import unittest
from pathlib import Path

from feclora.network.pxe_admission import PXEAdmission


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
            self.assertTrue(admission.is_admitted("aa:bb:cc:dd:ee:ff"))
            self.assertIsNone(admission.status()["clients_served"])
            self.assertFalse(admission.admit("not-a-mac")[0])


if __name__ == "__main__":
    unittest.main()

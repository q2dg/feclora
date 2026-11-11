import unittest
import tempfile
from pathlib import Path

from feclora.network.pxe_boot_request import (
    PXEBootRequestError,
    parse_pxe_boot_request,
)
from feclora.network.boot_tree import (
    LiveBootAssetError,
    render_ipxe_script,
    render_unattended_ipxe_script,
    publish_unattended_ipxe_script,
    revoke_unattended_ipxe_script,
)


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"


class PXEBootRequestTests(unittest.TestCase):
    def test_missing_mode_defaults_to_interactive(self):
        self.assertEqual(parse_pxe_boot_request("quiet ro").mode, "interactive")

    def test_interactive_mode_has_no_job_authorization_parameters(self):
        request = parse_pxe_boot_request("quiet feclora.pxe_mode=interactive")
        self.assertEqual(request.mode, "interactive")
        self.assertIsNone(request.job_id)

    def test_unattended_handoff_requires_canonical_job_and_server_endpoint(self):
        request = parse_pxe_boot_request(
            f"ro feclora.pxe_mode=unattended feclora.pxe_job_id={JOB_ID} "
            "feclora.pxe_server=192.0.2.10 feclora.pxe_control_port=9443"
        )
        self.assertEqual(request.mode, "unattended")
        self.assertEqual(request.job_id, JOB_ID)
        self.assertEqual(request.server_address, "192.0.2.10")
        self.assertEqual(request.control_port, 9443)

    def test_rejects_duplicate_or_incomplete_parameters(self):
        with self.assertRaisesRegex(PXEBootRequestError, "duplicate"):
            parse_pxe_boot_request(
                "feclora.pxe_mode=interactive feclora.pxe_mode=unattended"
            )
        with self.assertRaisesRegex(PXEBootRequestError, "requires job ID"):
            parse_pxe_boot_request("feclora.pxe_mode=unattended")

    def test_rejects_invalid_job_server_and_port(self):
        base = f"feclora.pxe_mode=unattended feclora.pxe_job_id={JOB_ID}"
        for suffix, message in (
            ("feclora.pxe_server=127.0.0.1 feclora.pxe_control_port=9443", "usable unicast"),
            ("feclora.pxe_server=192.0.2.10 feclora.pxe_control_port=22", "between 1024"),
            ("feclora.pxe_server=192.0.2.10 feclora.pxe_control_port=bad", "integer"),
        ):
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(PXEBootRequestError, message):
                    parse_pxe_boot_request(base + " " + suffix)

    def test_rejects_job_parameters_in_interactive_mode(self):
        with self.assertRaisesRegex(PXEBootRequestError, "must not carry"):
            parse_pxe_boot_request(
                f"feclora.pxe_mode=interactive feclora.pxe_job_id={JOB_ID}"
            )

    def test_normal_boot_script_offers_two_modes_but_does_not_authorize(self):
        script = render_ipxe_script("192.0.2.10", 8080)
        self.assertIn("item interactive", script)
        self.assertIn("item unattended", script)
        self.assertIn("feclora.pxe_mode=interactive", script)
        self.assertIn("unattended.ipxe", script)
        self.assertNotIn("feclora.pxe_job_id=", script)

    def test_job_bound_boot_script_contains_only_non_secret_handoff_data(self):
        script = render_unattended_ipxe_script("192.0.2.10", JOB_ID, 8080, 9443)
        self.assertIn(f"feclora.pxe_job_id={JOB_ID}", script)
        self.assertIn("feclora.pxe_mode=unattended", script)
        self.assertIn("feclora.pxe_server=192.0.2.10", script)
        self.assertIn("http://192.0.2.10:8080/live/vmlinuz", script)
        self.assertIn("feclora.pxe_control_port=9443", script)
        self.assertNotIn("PRIVATE KEY", script)
        self.assertNotIn("password", script.lower())

    def test_publishes_and_revokes_only_the_matching_job_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = publish_unattended_ipxe_script(tmp, "192.0.2.10", JOB_ID, 8080, 9443)
            published = Path(path)
            self.assertTrue(published.is_file())
            self.assertEqual(published.stat().st_mode & 0o777, 0o444)
            self.assertIn(f"feclora.pxe_job_id={JOB_ID}", published.read_text())
            # Idempotent publication of the same job is safe.
            self.assertEqual(
                publish_unattended_ipxe_script(tmp, "192.0.2.10", JOB_ID, 8080, 9443),
                path,
            )

            other_job = "f47ac10b-58cc-4372-a567-0e02b2c3d480"
            with self.assertRaisesRegex(LiveBootAssetError, "different unattended PXE job"):
                publish_unattended_ipxe_script(tmp, "192.0.2.10", other_job, 8080, 9443)
            with self.assertRaisesRegex(LiveBootAssetError, "different job"):
                revoke_unattended_ipxe_script(tmp, "192.0.2.10", other_job, 8080, 9443)
            self.assertTrue(published.exists())
            self.assertTrue(revoke_unattended_ipxe_script(tmp, "192.0.2.10", JOB_ID, 8080, 9443))
            self.assertFalse(published.exists())
            self.assertFalse(revoke_unattended_ipxe_script(tmp, "192.0.2.10", JOB_ID, 8080, 9443))

    def test_rejects_noncanonical_job_id_for_boot_script(self):
        with self.assertRaisesRegex(LiveBootAssetError, "canonical UUID"):
            render_unattended_ipxe_script(
                "192.0.2.10", JOB_ID.upper(), 9443
            )


if __name__ == "__main__":
    unittest.main()

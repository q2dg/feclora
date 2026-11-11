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
    render_unattended_answer_ipxe_script,
    publish_unattended_answer_ipxe_script,
    revoke_unattended_answer_ipxe_script,
    clear_stale_unattended_ipxe_script,
)


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
ANSWER_URL = f"http://192.0.2.10:8080/answers/{JOB_ID}/answer.json"
SIGNATURE_URL = f"http://192.0.2.10:8080/answers/{JOB_ID}/answer.minisig"


class PXEBootRequestTests(unittest.TestCase):
    def test_missing_mode_defaults_to_interactive(self):
        self.assertEqual(parse_pxe_boot_request("quiet ro").mode, "interactive")

    def test_interactive_mode_has_no_answer_authorization_parameters(self):
        request = parse_pxe_boot_request("quiet feclora.pxe_mode=interactive")
        self.assertEqual(request.mode, "interactive")
        self.assertIsNone(request.job_id)
        self.assertIsNone(request.answer_url)

    def test_unattended_answer_handoff_requires_job_and_both_urls(self):
        request = parse_pxe_boot_request(
            f"ro feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB_ID} "
            f"feclora.pxe_answer_url={ANSWER_URL} feclora.pxe_signature_url={SIGNATURE_URL}"
        )
        self.assertEqual(request.mode, "unattended-answer")
        self.assertEqual(request.job_id, JOB_ID)
        self.assertEqual(request.server_address, "192.0.2.10")
        self.assertEqual(request.http_port, 8080)
        self.assertEqual(request.answer_url, ANSWER_URL)
        self.assertEqual(request.signature_url, SIGNATURE_URL)

    def test_rejects_duplicate_or_incomplete_parameters(self):
        with self.assertRaisesRegex(PXEBootRequestError, "duplicate"):
            parse_pxe_boot_request(
                "feclora.pxe_mode=interactive feclora.pxe_mode=unattended-answer"
            )
        with self.assertRaisesRegex(PXEBootRequestError, "requires job ID"):
            parse_pxe_boot_request("feclora.pxe_mode=unattended-answer")

    def test_rejects_noncanonical_job_id(self):
        with self.assertRaisesRegex(PXEBootRequestError, "canonical UUID"):
            parse_pxe_boot_request(
                f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB_ID.upper()} "
                f"feclora.pxe_answer_url={ANSWER_URL} feclora.pxe_signature_url={SIGNATURE_URL}"
            )

    def test_rejects_loopback_and_malformed_answer_urls(self):
        bad_answer_urls = (
            f"http://127.0.0.1:8080/answers/{JOB_ID}/answer.json",
            f"http://user@192.0.2.10:8080/answers/{JOB_ID}/answer.json",
            f"http://192.0.2.10:8080/answers/{JOB_ID}/other.json",
            f"https://192.0.2.10:8080/answers/{JOB_ID}/answer.json",
        )
        for answer_url in bad_answer_urls:
            with self.subTest(answer_url=answer_url):
                with self.assertRaises(PXEBootRequestError):
                    parse_pxe_boot_request(
                        f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB_ID} "
                        f"feclora.pxe_answer_url={answer_url} feclora.pxe_signature_url={SIGNATURE_URL}"
                    )

    def test_rejects_signature_url_on_different_listener_or_path(self):
        for signature_url in (
            f"http://192.0.2.11:8080/answers/{JOB_ID}/answer.minisig",
            f"http://192.0.2.10:8081/answers/{JOB_ID}/answer.minisig",
            f"http://192.0.2.10:8080/answers/{JOB_ID}/wrong.minisig",
        ):
            with self.subTest(signature_url=signature_url):
                with self.assertRaises(PXEBootRequestError):
                    parse_pxe_boot_request(
                        f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB_ID} "
                        f"feclora.pxe_answer_url={ANSWER_URL} feclora.pxe_signature_url={signature_url}"
                    )

    def test_rejects_answer_parameters_in_interactive_mode(self):
        with self.assertRaisesRegex(PXEBootRequestError, "must not carry"):
            parse_pxe_boot_request(
                f"feclora.pxe_mode=interactive feclora.pxe_job_id={JOB_ID}"
            )

    def test_normal_boot_script_offers_interactive_and_answer_modes_only(self):
        script = render_ipxe_script("192.0.2.10", 8080)
        self.assertIn("item interactive", script)
        self.assertIn("item unattended", script)
        self.assertIn("unattended-answer.ipxe", script)
        self.assertIn("feclora.pxe_mode=interactive", script)
        self.assertNotIn("feclora.pxe_control_port=", script)

    def test_answer_boot_script_contains_only_job_and_signed_answer_urls(self):
        script = render_unattended_answer_ipxe_script(
            "192.0.2.10", JOB_ID, ANSWER_URL, SIGNATURE_URL, 8080,
        )
        self.assertIn(f"feclora.pxe_job_id={JOB_ID}", script)
        self.assertIn("feclora.pxe_mode=unattended-answer", script)
        self.assertIn(f"feclora.pxe_answer_url={ANSWER_URL}", script)
        self.assertIn(f"feclora.pxe_signature_url={SIGNATURE_URL}", script)
        self.assertIn("http://192.0.2.10:8080/live/vmlinuz", script)
        self.assertNotIn("feclora.pxe_control_port=", script)
        self.assertNotIn("client.key", script.lower())
        self.assertNotIn("PRIVATE KEY", script)

    def test_answer_boot_script_rejects_foreign_answer_urls(self):
        with self.assertRaisesRegex(LiveBootAssetError, "must match"):
            render_unattended_answer_ipxe_script(
                "192.0.2.10", JOB_ID,
                f"http://192.0.2.11:8080/answers/{JOB_ID}/answer.json",
                SIGNATURE_URL, 8080,
            )

    def test_publishes_and_revokes_only_the_matching_answer_job_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = publish_unattended_answer_ipxe_script(
                tmp, "192.0.2.10", JOB_ID, ANSWER_URL, SIGNATURE_URL, 8080,
            )
            published = Path(path)
            self.assertTrue(published.is_file())
            self.assertEqual(published.stat().st_mode & 0o777, 0o444)
            self.assertIn(f"feclora.pxe_job_id={JOB_ID}", published.read_text())
            self.assertEqual(
                publish_unattended_answer_ipxe_script(
                    tmp, "192.0.2.10", JOB_ID, ANSWER_URL, SIGNATURE_URL, 8080,
                ),
                path,
            )
            other_job = "f47ac10b-58cc-4372-a567-0e02b2c3d480"
            with self.assertRaisesRegex(LiveBootAssetError, "different unattended PXE answer job"):
                publish_unattended_answer_ipxe_script(
                    tmp, "192.0.2.10", other_job,
                    f"http://192.0.2.10:8080/answers/{other_job}/answer.json",
                    f"http://192.0.2.10:8080/answers/{other_job}/answer.minisig", 8080,
                )
            with self.assertRaisesRegex(LiveBootAssetError, "different job"):
                revoke_unattended_answer_ipxe_script(tmp, other_job)
            self.assertTrue(published.exists())
            self.assertTrue(revoke_unattended_answer_ipxe_script(tmp, JOB_ID))
            self.assertFalse(published.exists())
            self.assertFalse(revoke_unattended_answer_ipxe_script(tmp, JOB_ID))

    def test_new_pxe_session_clears_both_stale_handoff_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "unattended.ipxe"
            answer = Path(tmp) / "unattended-answer.ipxe"
            legacy.write_text("#!ipxe\\necho stale\\n", encoding="utf-8")
            answer.write_text("#!ipxe\\necho stale\\n", encoding="utf-8")
            self.assertTrue(clear_stale_unattended_ipxe_script(tmp))
            self.assertFalse(legacy.exists())
            self.assertFalse(answer.exists())
            self.assertFalse(clear_stale_unattended_ipxe_script(tmp))

    def test_new_pxe_session_refuses_symlinked_stale_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "unattended-answer.ipxe"
            stale.symlink_to("/etc/passwd")
            with self.assertRaisesRegex(LiveBootAssetError, "not a safe regular file"):
                clear_stale_unattended_ipxe_script(tmp)


if __name__ == "__main__":
    unittest.main()

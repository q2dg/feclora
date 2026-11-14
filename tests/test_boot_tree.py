import tempfile
import unittest
from pathlib import Path

from feclora.network.boot_tree import (
    LiveBootAssetError,
    render_ipxe_script,
    render_unattended_answer_ipxe_script,
    stage_live_boot_assets,
)


class LiveBootTreeTests(unittest.TestCase):
    def test_renders_http_live_boot_script(self):
        script = render_ipxe_script("192.0.2.10", 8080)
        self.assertIn("set live_base http://192.0.2.10:8080/live", script)
        self.assertIn("root=live:${live_base}/squashfs.img", script)
        self.assertIn("feclora.pxe_mode=interactive", script)
        self.assertIn("item unattended", script)
        self.assertIn("rd.neednet=1", script)
        self.assertIn("initrd ${live_base}/initrd.img", script)

    def test_unattended_handoff_passes_job_and_admitted_mac_to_live(self):
        job_id = "123e4567-e89b-12d3-a456-426614174000"
        answer_url = f"http://192.0.2.10:8080/answers/{job_id}/answer.json"
        script = render_unattended_answer_ipxe_script(
            "192.0.2.10", job_id, answer_url, 8080,
        )
        self.assertIn(f"feclora.pxe_job_id={job_id}", script)
        self.assertIn("feclora.pxe_client_mac=${net0/mac}", script)
        self.assertIn(f"feclora.pxe_answer_url={answer_url}", script)

    def test_stages_kernel_initramfs_squashfs_and_script_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "media"
            (live / "images" / "pxeboot").mkdir(parents=True)
            (live / "LiveOS").mkdir()
            (live / "images" / "pxeboot" / "vmlinuz").write_bytes(b"kernel")
            (live / "images" / "pxeboot" / "initrd.img").write_bytes(b"initrd")
            (live / "LiveOS" / "squashfs.img").write_bytes(b"squashfs")
            target = root / "http"
            staged = stage_live_boot_assets(str(live), str(target), address="192.0.2.10")
            self.assertEqual(set(staged), {"vmlinuz", "initrd.img", "squashfs.img", "boot.ipxe"})
            self.assertEqual((target / "live" / "squashfs.img").read_bytes(), b"squashfs")
            self.assertEqual((target / "boot.ipxe").stat().st_mode & 0o777, 0o444)
            # Staging is idempotent for identical source payloads.
            stage_live_boot_assets(str(live), str(target), address="192.0.2.10")

    def test_refuses_to_overwrite_different_existing_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "media"
            (live / "images" / "pxeboot").mkdir(parents=True)
            (live / "LiveOS").mkdir()
            (live / "images" / "pxeboot" / "vmlinuz").write_bytes(b"kernel")
            (live / "images" / "pxeboot" / "initrd.img").write_bytes(b"initrd")
            (live / "LiveOS" / "squashfs.img").write_bytes(b"squashfs")
            target = root / "http"
            (target / "live").mkdir(parents=True)
            (target / "live" / "vmlinuz").write_bytes(b"old")
            with self.assertRaises(LiveBootAssetError):
                stage_live_boot_assets(str(live), str(target), address="192.0.2.10")


if __name__ == "__main__":
    unittest.main()

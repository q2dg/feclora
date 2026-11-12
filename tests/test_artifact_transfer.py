import hashlib
import json
import os
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from feclora.deployment.artifact_transfer import (
    ImageTransferError, receive_image_set, send_image_set,
)


def make_image_set(directory):
    disk = b"disk"
    table = b"table"
    with open(os.path.join(directory, "disk.raw"), "wb") as stream:
        stream.write(disk)
    with open(os.path.join(directory, "table.txt"), "wb") as stream:
        stream.write(table)
    manifest = {
        "schema_version": 1,
        "image_id": "golden",
        "image_type": "disk",
        "source_size_bytes": len(disk),
        "logical_sector_size": 512,
        "partition_table": "none",
        "artifacts": [
            {
                "filename": "disk.raw", "role": "disk-image", "format": "raw",
                "compression": "none", "size_bytes": len(disk),
                "sha256": hashlib.sha256(disk).hexdigest(),
            },
            {
                "filename": "table.txt", "role": "partition-table", "format": "raw",
                "compression": "none", "size_bytes": len(table),
                "sha256": hashlib.sha256(table).hexdigest(),
            },
        ],
    }
    manifest_path = os.path.join(directory, "golden.manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)
    return manifest_path


class ImageTransferTests(unittest.TestCase):
    def test_image_set_transfers_and_publishes_manifest_last(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = make_image_set(source)
            left, right = socket.socketpair()
            errors = []
            send_progress = []
            receive_progress = []
            def sender():
                try:
                    send_image_set(
                        left, source, manifest_path, expected_image_id="golden",
                        progress_callback=lambda current, total: send_progress.append((current, total)),
                    )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    left.close()
            thread = threading.Thread(target=sender, daemon=True)
            thread.start()
            received_manifest = receive_image_set(
                right, target, expected_image_id="golden",
                progress_callback=lambda current, total: receive_progress.append((current, total)),
            )
            thread.join(5)
            right.close()
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors, str(errors))
            self.assertEqual(send_progress[0], (0, 9))
            self.assertEqual(send_progress[-1], (9, 9))
            self.assertEqual(receive_progress[0], (0, 9))
            self.assertEqual(receive_progress[-1], (9, 9))
            self.assertTrue(os.path.isfile(received_manifest))
            self.assertFalse(os.path.lexists(received_manifest + ".minisig"))
            with open(os.path.join(target, "disk.raw"), "rb") as stream:
                self.assertEqual(stream.read(), b"disk")
            with open(os.path.join(target, "table.txt"), "rb") as stream:
                self.assertEqual(stream.read(), b"table")
            self.assertFalse(any(name.startswith(".feclora-transfer-") for name in os.listdir(target)))


    def test_sender_rejects_artifact_digest_mismatch_before_network_write(self):
        with tempfile.TemporaryDirectory() as source:
            manifest_path = make_image_set(source)
            with open(os.path.join(source, "disk.raw"), "wb") as stream:
                stream.write(b"evil")
            fake = type("Sink", (), {"sendall": lambda self, data: None})()
            with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                with self.assertRaisesRegex(ImageTransferError, "SHA-256"):
                    send_image_set(
                        fake, source, manifest_path, expected_image_id="golden", trusted_public_key="/trusted/server.pub",
                    )

    def test_receiver_rejects_insufficient_staging_space_before_payload(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = make_image_set(source)
            left, right = socket.socketpair()
            def sender():
                send_image_set(
                    left, source, manifest_path, expected_image_id="golden",
                )
                left.close()
            thread = threading.Thread(target=sender, daemon=True)
            with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                thread.start()
                with patch("feclora.deployment.artifact_transfer.shutil.disk_usage", return_value=type("Usage", (), {"free": 1})()):
                    with self.assertRaisesRegex(ImageTransferError, "insufficient staging space"):
                        receive_image_set(
                            right, target, expected_image_id="golden",
                        )
            right.close()
            thread.join(5)


    def test_disconnect_during_payload_removes_staging_without_publishing(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = make_image_set(source)
            left, right = socket.socketpair()
            sender_errors = []

            class DisconnectAfterPartialPayload:
                def __init__(self, wrapped):
                    self.wrapped = wrapped
                    self.calls = 0

                def sendall(self, data):
                    self.calls += 1
                    if self.calls == 1:
                        self.wrapped.sendall(data)
                        return
                    self.wrapped.sendall(data[:2])
                    self.wrapped.shutdown(socket.SHUT_WR)
                    raise BrokenPipeError("simulated peer disconnect")

            def sender():
                try:
                    send_image_set(
                        DisconnectAfterPartialPayload(left), source, manifest_path,
                        expected_image_id="golden", trusted_public_key="/trusted/server.pub",
                    )
                except Exception as exc:
                    sender_errors.append(exc)
                finally:
                    left.close()

            with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                thread = threading.Thread(target=sender, daemon=True)
                thread.start()
                with self.assertRaisesRegex(ImageTransferError, "peer closed"):
                    receive_image_set(
                        right, target, expected_image_id="golden",
                    )
                thread.join(5)
            right.close()

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(sender_errors), 1)
            self.assertIsInstance(sender_errors[0], ImageTransferError)
            self.assertEqual(os.listdir(target), [])



    def test_publication_collision_removes_only_files_created_by_this_transfer(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = make_image_set(source)
            collision = os.path.join(target, "table.txt")
            with open(collision, "wb") as stream:
                stream.write(b"pre-existing")
            left, right = socket.socketpair()
            sender_errors = []

            def sender():
                try:
                    with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                        send_image_set(
                            left, source, manifest_path, expected_image_id="golden",
                        )
                except Exception as exc:
                    sender_errors.append(exc)
                finally:
                    left.close()

            with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                thread = threading.Thread(target=sender, daemon=True)
                thread.start()
                with self.assertRaisesRegex(ImageTransferError, "could not publish"):
                    receive_image_set(
                        right, target, expected_image_id="golden",
                    )
                thread.join(5)
            right.close()

            self.assertFalse(thread.is_alive())
            self.assertEqual(sender_errors, [])
            self.assertEqual(os.listdir(target), ["table.txt"])
            with open(collision, "rb") as stream:
                self.assertEqual(stream.read(), b"pre-existing")


    def test_receiver_rejects_wrong_job_image_id_without_publishing(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = make_image_set(source)
            left, right = socket.socketpair()
            errors = []
            def sender():
                try:
                    with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                        send_image_set(
                            left, source, manifest_path, expected_image_id="golden", trusted_public_key="/trusted/server.pub",
                        )
                except Exception as exc:
                    errors.append(exc)
                finally:
                    left.close()
            thread = threading.Thread(target=sender, daemon=True)
            thread.start()
            with self.assertRaisesRegex(ImageTransferError, "does not match"):
                receive_image_set(
                    right, target, expected_image_id="other",
                )
            right.close()
            thread.join(5)
            self.assertFalse(os.path.exists(os.path.join(target, "golden.manifest.json")))


if __name__ == "__main__":
    unittest.main()

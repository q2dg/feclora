import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from feclora.storage.partition_restore import PartitionRestoreCancelled, PartitionRestoreError, restore_partition
from unittest.mock import patch


class RecordingInput:
    def __init__(self):
        self.buffer = io.BytesIO()
    def write(self, data):
        return self.buffer.write(data)
    def close(self):
        pass
    def getvalue(self):
        return self.buffer.getvalue()


class FakeProcess:
    def __init__(self):
        self.returncode = 0
        self.stdin = RecordingInput()
        self.stderr = io.BytesIO(b"Progress: 25.0%\rProgress: 75.0%\r")
        self.argv = None
    def wait(self):
        return self.returncode
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15


class PartitionRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b"raw partition payload" * 20
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.temp.name, "partition.img.gz"), "wb") as stream:
            stream.write(self.stored)
        self.manifest = os.path.join(self.temp.name, "part.manifest.json")
        self.write_manifest("raw", None, len(self.payload))
        self.calls = []
        self.runner_calls = []
        self.stdin_data = None
        self.partclone_data = None
        self.active_process = None
    def write_manifest(self, image_format, filesystem, size):
        artifact = {
            "filename": "partition.img.gz", "role": "partition-image",
            "format": image_format, "compression": "gzip",
            "size_bytes": len(self.stored), "sha256": hashlib.sha256(self.stored).hexdigest(),
            "partition_id": "sda1",
        }
        if filesystem:
            artifact["filesystem"] = filesystem
        manifest = {
            "schema_version": 1, "image_id": "partition-test", "image_type": "partition",
            "source_size_bytes": size, "logical_sector_size": 512,
            "partition_table": "none", "artifacts": [artifact],
        }
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
    def runner(self, command, **kwargs):
        self.runner_calls.append((command, kwargs))
        if command[0] == "e2fsck":
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part 512 0\n")
    def restore(self, **kwargs):
        proc = FakeProcess()
        proc.stdout = io.BytesIO(self.payload)
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            if argv[0] == "dd":
                self.active_process = proc
            elif argv[0].startswith("partclone."):
                with open(argv[argv.index("-s") + 1], "rb") as image:
                    self.partclone_data = image.read()
            return proc
        result = restore_partition(
            self.manifest, self.temp.name, "/dev/sda1",
            confirmation="ERASE /dev/sda1",
            executables={"lsblk": "lsblk", "dd": "dd", "partclone.ext4": "partclone.ext4", "e2fsck": "e2fsck"},
            runner=self.runner, device_validator=lambda _path: True,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=factory, **kwargs,
        )
        if self.active_process is not None:
            self.stdin_data = self.active_process.stdin.getvalue()
        return result
    def write_luks2_manifest(self, *, scope="encrypted_container_bytes", source_layer="luks2_container", luks_uuid="12345678-1234-4234-8234-123456789abc"):
        self.write_manifest("raw", None, len(self.payload))
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        manifest["storage"] = {
            "schema_version": 1, "capture_scope": scope, "source_layer": source_layer,
            "luks_uuid": luks_uuid,
            "dependencies": [{
                "kind": "luks2_metadata", "identity": luks_uuid,
                "included_in_source_bytes": True,
            }],
        }
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)

    def test_luks2_container_restore_preserves_raw_bytes_and_verifies_header_uuid(self):
        self.write_luks2_manifest()
        luks_uuid = "12345678-1234-4234-8234-123456789abc"
        def runner(command, **kwargs):
            self.runner_calls.append((command, kwargs))
            if "luksUUID" in command:
                return SimpleNamespace(stdout=luks_uuid + "\n", stderr="", returncode=0)
            if "luksDump" in command:
                return SimpleNamespace(
                    stdout=json.dumps({"uuid": luks_uuid, "segments": {"0": {"encryption": "aes-xts-plain64"}}}),
                    stderr="", returncode=0,
                )
            return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part 512 0\n", stderr="", returncode=0)
        proc = FakeProcess()
        proc.stdout = io.BytesIO(self.payload)
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        result = restore_partition(
            self.manifest, self.temp.name, "/dev/sda1",
            confirmation="ERASE /dev/sda1",
            executables={"lsblk": "lsblk", "dd": "dd", "cryptsetup": "cryptsetup"},
            runner=runner, device_validator=lambda _path: True,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=factory,
        )
        self.assertEqual(result.storage["capture_scope"], "encrypted_container_bytes")
        self.assertEqual(proc.stdin.getvalue(), self.payload)
        self.assertTrue(any("luksUUID" in call[0][0] for call in self.runner_calls))
        self.assertTrue(any("luksDump" in call[0][0] for call in self.runner_calls))

    def test_luks2_container_restore_rejects_uuid_mismatch_after_write(self):
        self.write_luks2_manifest()
        proc = FakeProcess()
        proc.stdout = io.BytesIO(self.payload)
        def runner(command, **kwargs):
            if "luksUUID" in command:
                return SimpleNamespace(stdout="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n", stderr="", returncode=0)
            if "luksDump" in command:
                return SimpleNamespace(stdout=json.dumps({"uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "segments": {"0": {}}}), stderr="", returncode=0)
            return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part 512 0\n", stderr="", returncode=0)
        with self.assertRaisesRegex(PartitionRestoreError, "UUID or metadata"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "dd": "dd", "cryptsetup": "cryptsetup"},
                runner=runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda _argv, **_opts: proc,
            )

    def test_luks2_container_restore_requires_cryptsetup_before_writer(self):
        self.write_luks2_manifest()
        with self.assertRaisesRegex(PartitionRestoreError, "cryptsetup is required"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_luks2_container_restore_rejects_inconsistent_scope_and_layer(self):
        self.write_luks2_manifest(source_layer="active_crypt_mapping")
        with self.assertRaisesRegex(PartitionRestoreError, "byte scope and source layer"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_open_crypt_mapping_image_is_not_written_as_luks_container(self):
        self.write_luks2_manifest(scope="decrypted_mapping_bytes", source_layer="active_crypt_mapping")
        with self.assertRaisesRegex(PartitionRestoreError, "plaintext from an opened crypt mapping"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_luks2_manifest_requires_matching_header_dependency(self):
        self.write_luks2_manifest()
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        manifest["storage"]["dependencies"][0]["identity"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        with self.assertRaisesRegex(PartitionRestoreError, "matching header-included"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_age_encrypted_restore_requires_identity_before_writer(self):
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        manifest["artifacts"][0]["encryption"] = "age"
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        with self.assertRaisesRegex(PartitionRestoreError, "identity file is required"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_can_require_minisign_signature_before_writer(self):
        with self.assertRaisesRegex(PartitionRestoreError, "signature is required"):
            self.restore(require_signature=True)
        self.assertEqual(self.calls, [])

    def test_raw_restore_uses_dd_and_verified_decompressed_file(self):
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "dd")
        self.assertEqual(self.stdin_data, self.payload)
    def test_raw_restore_reports_progress(self):
        progress = []
        self.restore(progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
    def test_raw_restore_cancellation_stops_writer(self):
        proc = FakeProcess()
        class RunningProcess(FakeProcess):
            def poll(self):
                return -15 if self.returncode == -15 else None
        proc = RunningProcess()
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        with self.assertRaisesRegex(PartitionRestoreCancelled, "cancel"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "dd": "dd"},
                runner=self.runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
                progress_callback=lambda *_args: (_ for _ in ()).throw(PartitionRestoreCancelled("operator cancel")),
            )
        self.assertEqual(proc.returncode, -15)
    def test_filesystem_restore_map_has_a_checker_for_every_partclone_type(self):
        from feclora.storage.partition_restore import _PARTCLONE, _FILESYSTEM_CHECKS
        expected = {
            "ext2": "partclone.extfs", "ext3": "partclone.extfs",
            "ext4": "partclone.ext4", "xfs": "partclone.xfs",
            "btrfs": "partclone.btrfs", "f2fs": "partclone.f2fs",
            "ntfs": "partclone.ntfs", "ntfs3": "partclone.ntfs",
            "fat": "partclone.fat", "fat12": "partclone.fat",
            "fat16": "partclone.fat", "fat32": "partclone.fat",
            "vfat": "partclone.fat", "exfat": "partclone.exfat",
        }
        for filesystem, executable in expected.items():
            with self.subTest(filesystem=filesystem):
                self.assertEqual(_PARTCLONE[filesystem], executable)
                self.assertIn(filesystem, _FILESYSTEM_CHECKS)

    def test_partclone_restore_uses_filesystem_specific_executable(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "partclone.ext4")
        self.assertEqual(argv[1], "-r")
        self.assertIn("-s", argv)
        self.assertEqual(self.partclone_data, self.payload)
        self.assertTrue(any(call[0][0] == "e2fsck" and call[0][-1] == "/dev/sda1" for call in self.runner_calls))
        self.assertNotIn("pass_fds", options)

    def test_partclone_restore_fails_when_read_only_verification_fails(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        def failing_checker(command, **kwargs):
            self.runner_calls.append((command, kwargs))
            if command[0] == "e2fsck":
                return SimpleNamespace(stdout="", stderr="filesystem errors found", returncode=4)
            return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part 512 0\n")
        with self.assertRaisesRegex(PartitionRestoreError, "consistency check failed"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "partclone.ext4": "partclone.ext4", "e2fsck": "e2fsck"},
                runner=failing_checker, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *args, **kwargs: FakeProcess(),
            )

    @patch("feclora.storage.partition_restore._partclone_supports_json_status", return_value=True)
    def test_partclone_restore_prefers_native_json_block_progress(self, supports_json):
        self.write_manifest("partclone", "ext4", len(self.payload))
        progress = []
        status_paths = []
        proc = FakeProcess()
        def factory(argv, **opts):
            status_arg = next(arg for arg in argv if arg.startswith("--json-status="))
            status_path = status_arg.split("=", 1)[1]
            status_paths.append(status_path)
            with open(status_path, "w", encoding="utf-8") as stream:
                json.dump({
                    "schema_version": 1,
                    "partclone": {
                        "block_size": 4096,
                        "progress": {"copied_blocks": 5, "total_block": 10},
                    },
                }, stream)
            self.calls.append((argv, opts))
            return proc
        restore_partition(
            self.manifest, self.temp.name, "/dev/sda1",
            confirmation="ERASE /dev/sda1",
            executables={"lsblk": "lsblk", "partclone.ext4": "partclone.ext4", "e2fsck": "e2fsck"},
            runner=self.runner, device_validator=lambda _path: True,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=factory,
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertIn("--json-fresh=1", self.calls[0][0])
        self.assertIn((20480, 40960), progress)
        self.assertNotIn((10240, 40960), progress)
        self.assertFalse(os.path.exists(status_paths[0]))

    def test_partclone_restore_reports_progress_from_stderr(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        progress = []
        self.restore(progress_callback=lambda done, total: progress.append((done, total)))
        self.assertIn((len(self.payload) * 25 // 100, len(self.payload)), progress)
        self.assertIn((len(self.payload) * 75 // 100, len(self.payload)), progress)
        self.assertIn("-F", self.calls[0][0])
        self.assertIn("1", self.calls[0][0])

    def test_partclone_restore_cancellation_terminates_writer(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        class RunningProcess(FakeProcess):
            def poll(self):
                return -15 if self.returncode == -15 else None
        proc = RunningProcess()
        proc.stderr = io.BytesIO(b"Progress: 10%\r")
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        with self.assertRaisesRegex(PartitionRestoreCancelled, "cancel"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "partclone.ext4": "partclone.ext4", "e2fsck": "e2fsck"},
                runner=self.runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
                progress_callback=lambda *_args: (_ for _ in ()).throw(PartitionRestoreCancelled("operator cancel")),
            )
        self.assertEqual(proc.returncode, -15)
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(PartitionRestoreError, "confirmation"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1", confirmation="yes",
                executables={"lsblk": "lsblk"}, runner=self.runner,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_raw_restore_rejects_readback_mismatch(self):
        proc = FakeProcess()
        proc.stdout = io.BytesIO(b"different destination bytes")
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        with self.assertRaisesRegex(PartitionRestoreError, "read-back verification failed"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "dd": "dd"},
                runner=self.runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
            )

    def test_rejects_corrupt_artifact_before_starting_writer(self):
        with open(os.path.join(self.temp.name, "partition.img.gz"), "ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(PartitionRestoreError, "SHA-256"):
            self.restore()
        self.assertEqual(self.calls, [])
    def test_rejects_too_small_target(self):
        def small(command, **kwargs):
            return SimpleNamespace(stdout="1 part 512 0\n")
        with self.assertRaisesRegex(PartitionRestoreError, "smaller"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1", executables={"lsblk": "lsblk", "dd": "dd"},
                runner=small, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: self.fail("writer must not start"),
            )


    def test_signed_image_cannot_be_restored_without_trusted_key(self):
        with open(self.manifest + ".minisig", "wb") as signature:
            signature.write(b"unverified")
        with self.assertRaisesRegex(PartitionRestoreError, "trusted minisign public key"):
            self.restore()
        self.assertEqual(self.calls, [])


    def test_decompressed_partition_stages_outside_source_repository(self):
        from feclora.storage import partition_restore
        with tempfile.TemporaryDirectory() as local_stage:
            original = partition_restore._decompress_to_temp
            observed = {}

            def recording_decompress(source, compression, expected_size, directory, executables=None):
                observed["directory"] = directory
                return original(source, compression, expected_size, directory, executables)

            with patch("feclora.storage.partition_restore.tempfile.gettempdir", return_value=local_stage), patch(
                "feclora.storage.partition_restore._decompress_to_temp", side_effect=recording_decompress
            ):
                self.restore()
            self.assertEqual(observed["directory"], local_stage)
            self.assertEqual(os.listdir(local_stage), [])


if __name__ == "__main__":
    unittest.main()

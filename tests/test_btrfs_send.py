import hashlib
import lzma
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.image_security import ImageSecurityError

from feclora.storage.btrfs_send import (
    BtrfsSendError, _filesystem_info, _subvolume_info,
    capture_btrfs_subvolume, restore_btrfs_subvolume,
)


UUID = "11111111-1111-1111-1111-111111111111"


class BtrfsSendTests(unittest.TestCase):
    def test_subvolume_and_filesystem_metadata_parsing(self):
        def runner(argv, **kwargs):
            if argv[1:3] == ["subvolume", "show"]:
                return SimpleNamespace(stdout=(
                    "Name: root\nSubvolume ID: 256\nUUID: " + UUID
                    + "\nParent UUID: -\nReceived UUID: -\n"
                ))
            if argv[1:3] == ["property", "get"]:
                return SimpleNamespace(stdout="ro=true\n")
            return SimpleNamespace(stdout=(
                "Label: none  uuid: " + UUID + "\n"
                "Total devices 2 FS bytes used 4096\n"
            ))
        info = _subvolume_info(Path("/mnt/root"), "btrfs", runner)
        self.assertEqual(info["uuid"], UUID)
        self.assertTrue(info["readonly"])
        self.assertIsNone(info["parent_uuid"])
        self.assertEqual(_filesystem_info(Path("/mnt/root"), "btrfs", runner), (UUID, 2))

    def test_capture_publishes_stream_then_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "root"
            source.mkdir()
            repository = root / "repo"
            repository.mkdir()
            calls = []

            def runner(argv, **kwargs):
                calls.append(argv)
                if argv[1:3] == ["subvolume", "show"]:
                    name = Path(argv[-1]).name
                    return SimpleNamespace(stdout=(
                        f"Name: {name}\nSubvolume ID: 256\nUUID: {UUID}\n"
                        "Parent UUID: -\nReceived UUID: -\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=false\n")
                if argv[1:3] == ["subvolume", "list"]:
                    return SimpleNamespace(stdout="")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none  uuid: {UUID}\nTotal devices 2 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "snapshot", "-r"]:
                    Path(argv[-1]).mkdir()
                    return SimpleNamespace(stdout="")
                if argv[1] == "send":
                    kwargs["stdout"].write(b"fake-btrfs-send-stream")
                    return SimpleNamespace(stdout="", stderr=b"")
                if argv[1:3] == ["subvolume", "delete"]:
                    Path(argv[-1]).rmdir()
                    return SimpleNamespace(stdout="")
                raise AssertionError(argv)

            manifest = capture_btrfs_subvolume(
                source, "root-image", repository,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
            )
            stream = repository / manifest.stream_filename
            self.assertTrue(stream.is_file())
            self.assertTrue((repository / "root-image.manifest.json").is_file())
            self.assertEqual(manifest.subvolume_name, "root")
            self.assertEqual(manifest.device_count, 2)
            self.assertEqual(manifest.stream_sha256, hashlib.sha256(stream.read_bytes()).hexdigest())
            self.assertEqual(calls[-1][1:3], ["subvolume", "delete"])

    def test_restore_rejects_stream_digest_mismatch_before_receive(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repo = root / "repo"
            repo.mkdir()
            target = root / "target"
            target.mkdir()
            stream = repo / "image.btrfs"
            stream.write_bytes(b"corrupt")
            manifest = {
                "schema_version": 1, "image_id": "image",
                "filesystem_uuid": UUID, "subvolume_id": 256,
                "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
                "subvolume_name": "root", "device_count": 1,
                "send_mode": "full", "stream_parent_uuid": None,
                "stream_filename": "image.btrfs", "stream_size_bytes": 100,
                "stream_sha256": "a" * 64, "compression": "none",
            }
            manifest_path = repo / "image.manifest.json"
            import json
            manifest_path.write_text(json.dumps(manifest))
            calls = []

            def runner(argv, **kwargs):
                calls.append(argv)
                raise AssertionError("Btrfs must not be invoked for a corrupt stream")

            with self.assertRaisesRegex(BtrfsSendError, "SHA-256"):
                restore_btrfs_subvolume(
                    manifest_path, repo, target,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                )
            self.assertEqual(calls, [])
            self.assertEqual(list(target.iterdir()), [])

    def test_receive_exposes_subvolume_only_after_received_uuid_check(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repo = root / "repo"
            repo.mkdir()
            target = root / "target"
            target.mkdir()
            payload = b"valid-btrfs-send"
            (repo / "image.btrfs").write_bytes(payload)
            source_uuid = "22222222-2222-2222-2222-222222222222"
            import json
            manifest = {
                "schema_version": 1, "image_id": "image",
                "filesystem_uuid": UUID, "subvolume_id": 256,
                "subvolume_uuid": source_uuid, "subvolume_name": "root",
                "device_count": 1, "send_mode": "full",
                "stream_parent_uuid": None, "stream_filename": "image.btrfs",
                "stream_size_bytes": len(payload),
                "stream_sha256": hashlib.sha256(payload).hexdigest(),
                "compression": "none",
            }
            manifest_path = repo / "image.manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            def runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:2] == ["receive"]:
                    Path(argv[-1], "root").mkdir()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        "Name: root\nSubvolume ID: 256\nUUID: 33333333-3333-3333-3333-333333333333\n"
                        f"Parent UUID: -\nReceived UUID: {source_uuid}\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                raise AssertionError(argv)

            result = restore_btrfs_subvolume(
                manifest_path, repo, target,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
            )
            self.assertEqual(result, target / "root")
            self.assertTrue(result.is_dir())
            self.assertEqual(list(target.iterdir()), [result])

    def test_incremental_capture_rejects_unrelated_parent(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            parent = root / "parent"
            repository = root / "repo"
            source.mkdir()
            parent.mkdir()
            repository.mkdir()
            source_uuid = "22222222-2222-2222-2222-222222222222"
            parent_uuid = "33333333-3333-3333-3333-333333333333"

            def runner(argv, **kwargs):
                if argv[1:3] == ["subvolume", "show"]:
                    path = Path(argv[-1])
                    is_parent = path == parent
                    return SimpleNamespace(stdout=(
                        f"Name: {path.name}\nSubvolume ID: 256\n"
                        f"UUID: {parent_uuid if is_parent else source_uuid}\n"
                        f"Parent UUID: {'-' if is_parent else '44444444-4444-4444-4444-444444444444'}\n"
                        "Received UUID: -\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "list", "-o"]:
                    return SimpleNamespace(stdout="")
                raise AssertionError(argv)

            with self.assertRaisesRegex(BtrfsSendError, "directly derived"):
                capture_btrfs_subvolume(
                    source, "incremental", repository, parent_path=parent,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                )
            self.assertEqual(list(repository.iterdir()), [])

    def test_capture_rejects_nested_subvolumes_instead_of_omitting_them(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "root"
            source.mkdir()
            repository = root / "repo"
            repository.mkdir()

            def runner(argv, **kwargs):
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Name: root\nSubvolume ID: 256\nUUID: {UUID}\n"
                        "Parent UUID: -\nReceived UUID: -\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "list", "-o"]:
                    return SimpleNamespace(stdout="ID 257 gen 1 top level 256 path nested\n")
                raise AssertionError(argv)

            with self.assertRaisesRegex(BtrfsSendError, "nested Btrfs subvolumes"):
                capture_btrfs_subvolume(
                    source, "image", repository,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                )
            self.assertEqual(list(repository.iterdir()), [])

    def test_capture_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            actual = root / "actual"
            actual.mkdir()
            link = root / "link"
            link.symlink_to(actual, target_is_directory=True)
            repo = root / "repo"
            repo.mkdir()
            with self.assertRaisesRegex(BtrfsSendError, "symlink"):
                capture_btrfs_subvolume(
                    link, "image", repo,
                    executables={"btrfs": "/usr/bin/btrfs"},
                    runner=subprocess.run,
                )


    def test_gzip_capture_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "root"
            source.mkdir()
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            payload = b"btrfs-send-stream-payload" * 64
            received_payload = []

            def runner(argv, **kwargs):
                if argv[1:3] == ["subvolume", "show"]:
                    path = Path(argv[-1])
                    if path.name == "root":
                        return SimpleNamespace(stdout=(
                            f"Name: root\nSubvolume ID: 256\nUUID: {UUID}\n"
                            "Parent UUID: -\nReceived UUID: -\n"
                        ))
                    raise AssertionError(argv)
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "list", "-o"]:
                    return SimpleNamespace(stdout="")
                if argv[1] == "send":
                    kwargs["stdout"].write(payload)
                    return SimpleNamespace(stdout=b"", stderr=b"")
                if argv[1] == "receive":
                    received_payload.append(kwargs["stdin"].read())
                    Path(argv[-1], "root").mkdir()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                raise AssertionError(argv)

            manifest = capture_btrfs_subvolume(
                source, "gzip-image", repository,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                compression="gzip",
            )
            stored = repository / manifest.stream_filename
            self.assertTrue(manifest.stream_filename.endswith(".btrfs.gz"))
            self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), manifest.stream_sha256)
            self.assertEqual(manifest.stream_size_bytes, stored.stat().st_size)
            import gzip
            self.assertEqual(gzip.decompress(stored.read_bytes()), payload)

            # A received subvolume reports the source UUID as its received UUID.
            def restore_runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    received_payload.append(kwargs["stdin"].read())
                    Path(argv[-1], "root").mkdir()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        "Name: root\nSubvolume ID: 300\nUUID: 44444444-4444-4444-4444-444444444444\n"
                        f"Parent UUID: -\nReceived UUID: {UUID}\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                raise AssertionError(argv)

            result = restore_btrfs_subvolume(
                repository / "gzip-image.manifest.json", repository, target,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=restore_runner,
            )
            self.assertEqual(result, target / "root")
            self.assertEqual(received_payload, [payload])
            self.assertEqual(list(target.iterdir()), [result])


    def test_age_encrypted_gzip_capture_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "root"
            source.mkdir()
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            recipients = root / "recipients.txt"
            recipients.write_text("age1example\n", encoding="ascii")
            identity = root / "identity.txt"
            identity.write_text("AGE-SECRET-KEY-1EXAMPLE\n", encoding="ascii")
            payload = b"encrypted-btrfs-send-payload" * 32
            received_payload = []

            def runner(argv, **kwargs):
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Name: root\nSubvolume ID: 256\nUUID: {UUID}\n"
                        "Parent UUID: -\nReceived UUID: -\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "list", "-o"]:
                    return SimpleNamespace(stdout="")
                if argv[1] == "send":
                    kwargs["stdout"].write(payload)
                    return SimpleNamespace(stdout=b"", stderr=b"")
                raise AssertionError(argv)

            def fake_encrypt(path, artifact, recipients_file, *, age_executable=None):
                plaintext = Path(path)
                encrypted_name = plaintext.name + ".age"
                encrypted_bytes = b"age:" + plaintext.read_bytes()
                (plaintext.parent / encrypted_name).write_bytes(encrypted_bytes)
                plaintext.unlink()
                return replace(
                    artifact, filename=encrypted_name,
                    size_bytes=len(encrypted_bytes),
                    sha256=hashlib.sha256(encrypted_bytes).hexdigest(),
                    encryption="age",
                )

            with patch("feclora.storage.btrfs_send.encrypt_artifact", side_effect=fake_encrypt):
                manifest = capture_btrfs_subvolume(
                    source, "encrypted-image", repository,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                    compression="gzip", age_recipients_file=recipients,
                )

            self.assertEqual(manifest.encryption, "age")
            self.assertEqual(manifest.compression, "gzip")
            stored = repository / manifest.stream_filename
            stored_bytes = stored.read_bytes()
            self.assertEqual(hashlib.sha256(stored_bytes).hexdigest(), manifest.stream_sha256)
            self.assertEqual(len(stored_bytes), manifest.stream_size_bytes)
            self.assertTrue(stored_bytes.startswith(b"age:"))

            def fake_decrypt(encrypted_stream, identity_file, directory, *, age_executable=None):
                encrypted = encrypted_stream.read()
                if not encrypted.startswith(b"age:"):
                    raise ImageSecurityError("unexpected encrypted test payload")
                fd, path = tempfile.mkstemp(prefix=".decrypted-", dir=directory)
                with os.fdopen(fd, "wb") as output:
                    output.write(encrypted[4:])
                return path

            def restore_runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    received_payload.append(kwargs["stdin"].read())
                    Path(argv[-1], "root").mkdir()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        "Name: root\nSubvolume ID: 300\nUUID: 44444444-4444-4444-4444-444444444444\n"
                        f"Parent UUID: -\nReceived UUID: {UUID}\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                raise AssertionError(argv)

            with patch(
                "feclora.storage.btrfs_send.decrypt_artifact_stream_to_temp",
                side_effect=fake_decrypt,
            ):
                result = restore_btrfs_subvolume(
                    repository / "encrypted-image.manifest.json", repository, target,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=restore_runner,
                    age_identity_file=identity,
                )
            self.assertEqual(result, target / "root")
            self.assertEqual(received_payload, [payload])

    def test_age_decryption_failure_keeps_receive_staging_quarantined(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            identity = root / "identity.txt"
            identity.write_text("AGE-SECRET-KEY-1EXAMPLE\n", encoding="ascii")
            stored = b"not-authenticated"
            (repository / "image.btrfs.age").write_bytes(stored)
            import json
            manifest = {
                "schema_version": 1, "image_id": "image",
                "filesystem_uuid": UUID, "subvolume_id": 256,
                "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
                "subvolume_name": "root", "device_count": 1,
                "send_mode": "full", "stream_parent_uuid": None,
                "stream_filename": "image.btrfs.age",
                "stream_size_bytes": len(stored),
                "stream_sha256": hashlib.sha256(stored).hexdigest(),
                "compression": "none", "encryption": "age",
            }
            manifest_path = repository / "image.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receive_calls = []

            def runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    receive_calls.append(argv)
                raise AssertionError(argv)

            with patch(
                "feclora.storage.btrfs_send.decrypt_artifact_stream_to_temp",
                side_effect=ImageSecurityError("authentication failed"),
            ):
                with self.assertRaisesRegex(BtrfsSendError, "decode/restore failed"):
                    restore_btrfs_subvolume(
                        manifest_path, repository, target,
                        executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                        age_identity_file=identity,
                    )
            self.assertEqual(receive_calls, [])
            staging = list(target.glob(".feclora-receive-image-*"))
            self.assertEqual(len(staging), 1)
            self.assertEqual(list(staging[0].iterdir()), [])


    def test_xz_capture_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "root"
            source.mkdir()
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            payload = b"btrfs-xz-stream-payload" * 64
            received_payload = []

            def capture_runner(argv, **kwargs):
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Name: root\nSubvolume ID: 256\nUUID: {UUID}\n"
                        "Parent UUID: -\nReceived UUID: -\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1:4] == ["subvolume", "list", "-o"]:
                    return SimpleNamespace(stdout="")
                if argv[1] == "send":
                    kwargs["stdout"].write(payload)
                    return SimpleNamespace(stdout=b"", stderr=b"")
                raise AssertionError(argv)

            manifest = capture_btrfs_subvolume(
                source, "xz-image", repository,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=capture_runner,
                compression="xz",
            )
            stored = repository / manifest.stream_filename
            stored_bytes = stored.read_bytes()
            self.assertTrue(manifest.stream_filename.endswith(".btrfs.xz"))
            self.assertEqual(lzma.decompress(stored_bytes), payload)
            self.assertEqual(hashlib.sha256(stored_bytes).hexdigest(), manifest.stream_sha256)
            self.assertEqual(len(stored_bytes), manifest.stream_size_bytes)

            def restore_runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    received_payload.append(kwargs["stdin"].read())
                    Path(argv[-1], "root").mkdir()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                if argv[1:3] == ["subvolume", "show"]:
                    return SimpleNamespace(stdout=(
                        "Name: root\nSubvolume ID: 300\nUUID: 44444444-4444-4444-4444-444444444444\n"
                        f"Parent UUID: -\nReceived UUID: {UUID}\n"
                    ))
                if argv[1:3] == ["property", "get"]:
                    return SimpleNamespace(stdout="ro=true\n")
                raise AssertionError(argv)

            result = restore_btrfs_subvolume(
                repository / "xz-image.manifest.json", repository, target,
                executables={"btrfs": "/usr/bin/btrfs"}, runner=restore_runner,
            )
            self.assertEqual(result, target / "root")
            self.assertEqual(received_payload, [payload])

    def test_corrupt_gzip_stream_is_kept_in_quarantined_staging(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            stored = b"not a gzip stream"
            (repository / "image.btrfs.gz").write_bytes(stored)
            import json
            manifest = {
                "schema_version": 1, "image_id": "image",
                "filesystem_uuid": UUID, "subvolume_id": 256,
                "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
                "subvolume_name": "root", "device_count": 1,
                "send_mode": "full", "stream_parent_uuid": None,
                "stream_filename": "image.btrfs.gz",
                "stream_size_bytes": len(stored),
                "stream_sha256": hashlib.sha256(stored).hexdigest(),
                "compression": "gzip",
            }
            manifest_path = repository / "image.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receive_calls = []

            def runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    receive_calls.append(argv)
                    kwargs["stdin"].read()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                raise AssertionError(argv)

            with self.assertRaisesRegex(BtrfsSendError, "decode/restore failed"):
                restore_btrfs_subvolume(
                    manifest_path, repository, target,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                )
            self.assertEqual(len(receive_calls), 1)
            self.assertFalse((target / "root").exists())
            staging = list(target.glob(".feclora-receive-image-*"))
            self.assertEqual(len(staging), 1)
            self.assertEqual(list(staging[0].iterdir()), [])


    @unittest.skipUnless(shutil.which("zstd") and shutil.which("lz4"),
                         "zstd and lz4 executables are required")
    def test_external_codec_capture_and_restore_round_trips(self):
        for codec, suffix in (("zstd", ".zst"), ("lz4", ".lz4")):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                source = root / "root"
                source.mkdir()
                repository = root / "repo"
                repository.mkdir()
                target = root / "target"
                target.mkdir()
                payload = (f"btrfs-{codec}-stream-payload-".encode("ascii")) * 128
                received_payload = []
                executables = {
                    "btrfs": "/usr/bin/btrfs",
                    codec: shutil.which(codec),
                }

                def capture_runner(argv, **kwargs):
                    if argv[1:3] == ["subvolume", "show"]:
                        return SimpleNamespace(stdout=(
                            f"Name: root\nSubvolume ID: 256\nUUID: {UUID}\n"
                            "Parent UUID: -\nReceived UUID: -\n"
                        ))
                    if argv[1:3] == ["property", "get"]:
                        return SimpleNamespace(stdout="ro=true\n")
                    if argv[1:3] == ["filesystem", "show"]:
                        return SimpleNamespace(stdout=(
                            f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                        ))
                    if argv[1:4] == ["subvolume", "list", "-o"]:
                        return SimpleNamespace(stdout="")
                    if argv[1] == "send":
                        kwargs["stdout"].write(payload)
                        return SimpleNamespace(stdout=b"", stderr=b"")
                    raise AssertionError(argv)

                manifest = capture_btrfs_subvolume(
                    source, f"{codec}-image", repository,
                    executables=executables, runner=capture_runner,
                    compression=codec,
                )
                stored = repository / manifest.stream_filename
                stored_bytes = stored.read_bytes()
                self.assertTrue(manifest.stream_filename.endswith(".btrfs" + suffix))
                self.assertEqual(hashlib.sha256(stored_bytes).hexdigest(), manifest.stream_sha256)
                self.assertEqual(len(stored_bytes), manifest.stream_size_bytes)

                def restore_runner(argv, **kwargs):
                    if argv[1:3] == ["filesystem", "show"]:
                        return SimpleNamespace(stdout=(
                            f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                        ))
                    if argv[1] == "receive":
                        received_payload.append(kwargs["stdin"].read())
                        Path(argv[-1], "root").mkdir()
                        return SimpleNamespace(stdout=b"", stderr=b"")
                    if argv[1:3] == ["subvolume", "show"]:
                        return SimpleNamespace(stdout=(
                            "Name: root\nSubvolume ID: 300\nUUID: 44444444-4444-4444-4444-444444444444\n"
                            f"Parent UUID: -\nReceived UUID: {UUID}\n"
                        ))
                    if argv[1:3] == ["property", "get"]:
                        return SimpleNamespace(stdout="ro=true\n")
                    raise AssertionError(argv)

                result = restore_btrfs_subvolume(
                    repository / f"{codec}-image.manifest.json", repository, target,
                    executables=executables, runner=restore_runner,
                )
                self.assertEqual(result, target / "root")
                self.assertEqual(received_payload, [payload])


    @unittest.skipUnless(shutil.which("zstd") and shutil.which("lz4"),
                         "zstd and lz4 executables are required")
    def test_corrupt_external_codec_streams_are_quarantined(self):
        for codec, suffix in (("zstd", ".zst"), ("lz4", ".lz4")):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                repository = root / "repo"
                repository.mkdir()
                target = root / "target"
                target.mkdir()
                stored = b"not a valid external compressed stream"
                filename = "image.btrfs" + suffix
                (repository / filename).write_bytes(stored)
                import json
                manifest = {
                    "schema_version": 1, "image_id": "image",
                    "filesystem_uuid": UUID, "subvolume_id": 256,
                    "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
                    "subvolume_name": "root", "device_count": 1,
                    "send_mode": "full", "stream_parent_uuid": None,
                    "stream_filename": filename,
                    "stream_size_bytes": len(stored),
                    "stream_sha256": hashlib.sha256(stored).hexdigest(),
                    "compression": codec,
                }
                manifest_path = repository / "image.manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                receive_calls = []
                executables = {
                    "btrfs": "/usr/bin/btrfs",
                    codec: shutil.which(codec),
                }

                def runner(argv, **kwargs):
                    if argv[1:3] == ["filesystem", "show"]:
                        return SimpleNamespace(stdout=(
                            f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                        ))
                    if argv[1] == "receive":
                        receive_calls.append(argv)
                        kwargs["stdin"].read()
                        return SimpleNamespace(stdout=b"", stderr=b"")
                    raise AssertionError(argv)

                with self.assertRaisesRegex(BtrfsSendError, "decode/restore failed"):
                    restore_btrfs_subvolume(
                        manifest_path, repository, target,
                        executables=executables, runner=runner,
                    )
                self.assertEqual(len(receive_calls), 1)
                self.assertFalse((target / "root").exists())
                staging = list(target.glob(".feclora-receive-image-*"))
                self.assertEqual(len(staging), 1)
                self.assertEqual(list(staging[0].iterdir()), [])


    def test_corrupt_xz_stream_is_kept_in_quarantined_staging(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repository = root / "repo"
            repository.mkdir()
            target = root / "target"
            target.mkdir()
            stored = b"not an xz stream"
            (repository / "image.btrfs.xz").write_bytes(stored)
            import json
            manifest = {
                "schema_version": 1, "image_id": "image",
                "filesystem_uuid": UUID, "subvolume_id": 256,
                "subvolume_uuid": "22222222-2222-2222-2222-222222222222",
                "subvolume_name": "root", "device_count": 1,
                "send_mode": "full", "stream_parent_uuid": None,
                "stream_filename": "image.btrfs.xz",
                "stream_size_bytes": len(stored),
                "stream_sha256": hashlib.sha256(stored).hexdigest(),
                "compression": "xz",
            }
            manifest_path = repository / "image.manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receive_calls = []

            def runner(argv, **kwargs):
                if argv[1:3] == ["filesystem", "show"]:
                    return SimpleNamespace(stdout=(
                        f"Label: none uuid: {UUID}\nTotal devices 1 FS bytes used 4096\n"
                    ))
                if argv[1] == "receive":
                    receive_calls.append(argv)
                    kwargs["stdin"].read()
                    return SimpleNamespace(stdout=b"", stderr=b"")
                raise AssertionError(argv)

            with self.assertRaisesRegex(BtrfsSendError, "decode/restore failed"):
                restore_btrfs_subvolume(
                    manifest_path, repository, target,
                    executables={"btrfs": "/usr/bin/btrfs"}, runner=runner,
                )
            self.assertEqual(len(receive_calls), 1)
            self.assertFalse((target / "root").exists())
            staging = list(target.glob(".feclora-receive-image-*"))
            self.assertEqual(len(staging), 1)
            self.assertEqual(list(staging[0].iterdir()), [])


if __name__ == "__main__":
    unittest.main()

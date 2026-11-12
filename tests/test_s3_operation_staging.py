import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.webapi import WebAPIError, _operation_repository_context


class FakeObjectRepository:
    def __init__(self, read_only=False):
        self.config = SimpleNamespace(read_only=read_only)
        self.downloaded = []
        self.uploaded = []

    def download_image_set(self, image_id, destination):
        self.downloaded.append(image_id)
        (Path(destination) / f"{image_id}.manifest.json").write_text("{}")

    def upload_image_set(self, repository, image_id):
        self.uploaded.append((Path(repository), image_id))


class FakeManager:
    def __init__(self, repository):
        self.object_repository = repository

    def list(self):
        return [{"id": "s3archive"}]

    def repository(self, identifier, progress=None):
        if identifier != "s3archive":
            raise AssertionError(identifier)
        return self.object_repository


class S3OperationStagingTests(unittest.TestCase):
    def test_read_operation_downloads_to_private_temporary_directory(self):
        remote = FakeObjectRepository()
        manager = FakeManager(remote)
        with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=manager):
            with _operation_repository_context(
                {"repository_id": "s3archive"}, write=False, image_id="golden",
            ) as repository:
                self.assertTrue((repository / "golden.manifest.json").is_file())
                self.assertEqual(repository.stat().st_mode & 0o777, 0o700)
                temporary_path = repository
        self.assertFalse(temporary_path.exists())
        self.assertEqual(remote.downloaded, ["golden"])
        self.assertEqual(remote.uploaded, [])

    def test_capture_uploads_image_only_after_staging_context_succeeds(self):
        remote = FakeObjectRepository()
        manager = FakeManager(remote)
        with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=manager):
            with _operation_repository_context(
                {"repository_id": "s3archive"}, write=True, upload_image_id="captured",
            ) as repository:
                (repository / "captured.manifest.json").write_text("{}")
                staging_path = repository
        self.assertEqual(len(remote.uploaded), 1)
        self.assertEqual(remote.uploaded[0][1], "captured")
        self.assertFalse(staging_path.exists())

    def test_read_only_s3_repository_rejects_capture_before_staging(self):
        remote = FakeObjectRepository(read_only=True)
        manager = FakeManager(remote)
        with patch("feclora.storage.s3_repository_manager.S3RepositoryManager", return_value=manager):
            with self.assertRaisesRegex(WebAPIError, "read-only"):
                with _operation_repository_context(
                    {"repository_id": "s3archive"}, write=True, upload_image_id="captured",
                ):
                    self.fail("read-only S3 repository must not yield a writable staging directory")


if __name__ == "__main__":
    unittest.main()

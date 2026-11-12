import os
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.webapi import _operation_repository_context


class FakeRepositoryManager:
    def __init__(self):
        self.lease_fd = None
        self.lease_active = False

    def acquire_usage_lock(self, identifier):
        if identifier != "nas":
            raise AssertionError("unexpected repository identifier")
        self.lease_fd = os.open(os.devnull, os.O_RDONLY)
        self.lease_active = True
        return self.lease_fd

    def resolve(self, identifier, *, write=False):
        if not self.lease_active:
            raise AssertionError("repository resolved without an active usage lease")
        if identifier != "nas":
            raise AssertionError("unexpected repository identifier")
        return "/var/lib/feclora/repositories/nas"


class RemoteRepositoryOperationLeaseTests(unittest.TestCase):
    def test_local_image_operation_holds_shared_repository_lease_for_entire_context(self):
        manager = FakeRepositoryManager()
        with patch("feclora.webapi._remote_repository_manager", return_value=manager):
            with _operation_repository_context({"repository_id": "nas"}, write=True) as path:
                self.assertEqual(path, Path("/var/lib/feclora/repositories/nas"))
                self.assertTrue(manager.lease_active)
                os.fstat(manager.lease_fd)
        with self.assertRaises(OSError):
            os.fstat(manager.lease_fd)

    def test_repository_lease_is_released_when_image_engine_fails(self):
        manager = FakeRepositoryManager()
        with patch("feclora.webapi._remote_repository_manager", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "engine failed"):
                with _operation_repository_context({"repository_id": "nas"}, write=False):
                    raise RuntimeError("engine failed")
        self.assertFalse(manager.lease_active)
        with self.assertRaises(OSError):
            os.fstat(manager.lease_fd)


if __name__ == "__main__":
    unittest.main()

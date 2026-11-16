from __future__ import annotations

import os
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.client_service import (
    ClientDeploymentService,
    ClientJobServiceError,
)


JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"


class ClientDeploymentLockTests(unittest.TestCase):
    def setUp(self):
        self.service = ClientDeploymentService(JOB_ID)

    def prepare_directories(self):
        return (
            patch("feclora.deployment.client_service._ensure_directory"),
            patch("feclora.deployment.client_service._ensure_runtime_directory"),
        )

    def test_lock_open_is_close_on_exec(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
        with self.prepare_directories()[0], self.prepare_directories()[1], \
             patch("feclora.deployment.client_service.os.open", return_value=71) as open_lock, \
             patch("feclora.deployment.client_service.os.fstat", return_value=info), \
             patch("feclora.deployment.client_service.fcntl.flock"):
            self.service._acquire_lock()
        flags = open_lock.call_args.args[1]
        if hasattr(os, "O_CLOEXEC"):
            self.assertTrue(flags & os.O_CLOEXEC)
        self.assertEqual(self.service._lock_fd, 71)

    def test_unsafe_lock_file_closes_descriptor(self):
        info = SimpleNamespace(st_mode=stat.S_IFLNK, st_uid=0)
        with self.prepare_directories()[0], self.prepare_directories()[1], \
             patch("feclora.deployment.client_service.os.open", return_value=72), \
             patch("feclora.deployment.client_service.os.fstat", return_value=info), \
             patch("feclora.deployment.client_service.os.close") as close_fd:
            with self.assertRaisesRegex(ClientJobServiceError, "lock file is unsafe"):
                self.service._acquire_lock()
        close_fd.assert_called_once_with(72)
        self.assertIsNone(self.service._lock_fd)

    def test_hard_linked_lock_file_is_rejected_and_closed(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=2)
        with self.prepare_directories()[0], self.prepare_directories()[1], \
             patch("feclora.deployment.client_service.os.open", return_value=74), \
             patch("feclora.deployment.client_service.os.fstat", return_value=info), \
             patch("feclora.deployment.client_service.os.close") as close_fd:
            with self.assertRaisesRegex(ClientJobServiceError, "lock file is unsafe"):
                self.service._acquire_lock()
        close_fd.assert_called_once_with(74)
        self.assertIsNone(self.service._lock_fd)

    def test_busy_lock_closes_descriptor(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0)
        with self.prepare_directories()[0], self.prepare_directories()[1], \
             patch("feclora.deployment.client_service.os.open", return_value=73), \
             patch("feclora.deployment.client_service.os.fstat", return_value=info), \
             patch("feclora.deployment.client_service.fcntl.flock", side_effect=BlockingIOError), \
             patch("feclora.deployment.client_service.os.close") as close_fd:
            with self.assertRaisesRegex(ClientJobServiceError, "already owns this job"):
                self.service._acquire_lock()
        close_fd.assert_called_once_with(73)
        self.assertIsNone(self.service._lock_fd)


if __name__ == "__main__":
    unittest.main()

import subprocess
import unittest
from unittest.mock import Mock

from feclora.storage.process_control import stop_process


class ProcessControlTests(unittest.TestCase):
    def test_stops_and_reaps_process_after_graceful_termination(self):
        process = Mock()
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        stop_process(process)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)

    def test_kills_process_when_graceful_termination_times_out(self):
        process = Mock()
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [subprocess.TimeoutExpired("worker", 5), 0]
        stop_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)

    def test_does_not_signal_an_already_exited_process(self):
        process = Mock()
        process.poll.return_value = 0
        stop_process(process)
        process.terminate.assert_not_called()
        process.wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()

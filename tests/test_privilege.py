import unittest
from feclora.storage.privilege import PrivilegeError, privileged_argv


class PrivilegeTests(unittest.TestCase):
    def test_root_runs_command_directly(self):
        self.assertEqual(
            privileged_argv(["/usr/bin/dd", "if=/dev/sda"], effective_uid=lambda: 0),
            ["/usr/bin/dd", "if=/dev/sda"],
        )

    def test_unprivileged_runs_noninteractive_sudo(self):
        result = privileged_argv(
            ["/usr/bin/dd", "of=/dev/sdb"],
            effective_uid=lambda: 1000,
            which=lambda name: "/usr/bin/sudo" if name == "sudo" else None,
        )
        self.assertEqual(result, ["/usr/bin/sudo", "-n", "--", "/usr/bin/dd", "of=/dev/sdb"])

    def test_missing_sudo_fails_closed(self):
        with self.assertRaises(PrivilegeError):
            privileged_argv(["/usr/bin/dd"], effective_uid=lambda: 1000, which=lambda _name: None)


if __name__ == "__main__":
    unittest.main()

import subprocess
import unittest

from feclora.network.firewall import PXEFirewall, PXEFirewallError


class FirewallTests(unittest.TestCase):
    def test_opens_only_new_ports_in_selected_interface_zone(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if any(arg.startswith("--get-zone-of-interface=") for arg in argv):
                return subprocess.CompletedProcess(argv, 0, "work\n", "")
            if any(arg == "--query-port=69/udp" for arg in argv):
                return subprocess.CompletedProcess(argv, 0, "", "")
            if any(arg.startswith("--query-port=") for arg in argv):
                return subprocess.CompletedProcess(argv, 1, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=runner)
        firewall.open("enp1s0", ["67/udp", "69/udp", "4011/udp", "8080/tcp"])
        additions = [call for call in calls if any(arg.startswith("--add-port=") for arg in call)]
        self.assertEqual([call[-1].split("=", 1)[1] for call in additions], ["67/udp", "4011/udp", "8080/tcp"])
        firewall.close("enp1s0")
        removals = [call for call in calls if any(arg.startswith("--remove-port=") for arg in call)]
        self.assertEqual([call[-1].split("=", 1)[1] for call in removals], ["8080/tcp", "4011/udp", "67/udp"])

    def test_rolls_back_added_ports_after_failure(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if any(arg.startswith("--get-zone-of-interface=") for arg in argv):
                return subprocess.CompletedProcess(argv, 0, "work\n", "")
            if any(arg.startswith("--query-port=") for arg in argv):
                return subprocess.CompletedProcess(argv, 1, "", "")
            if any(arg == "--add-port=69/udp" for arg in argv):
                return subprocess.CompletedProcess(argv, 1, "", "denied")
            return subprocess.CompletedProcess(argv, 0, "", "")
        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=runner)
        with self.assertRaises(PXEFirewallError):
            firewall.open("enp1s0", ["67/udp", "69/udp"])
        self.assertTrue(any(any(arg == "--remove-port=67/udp" for arg in call) for call in calls))

    def test_rejects_invalid_port_and_interface(self):
        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=lambda *a, **k: None)
        with self.assertRaises(PXEFirewallError):
            firewall.open("any", ["67/udp"])
        with self.assertRaises(PXEFirewallError):
            firewall.open("enp1s0", ["99999/tcp"])


if __name__ == "__main__":
    unittest.main()

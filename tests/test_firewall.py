import subprocess
import unittest

from feclora.network.firewall import PXEFirewall, PXEFirewallError


class FirewallTests(unittest.TestCase):
    def test_uses_a_temporary_zone_bound_only_to_the_selected_interface(self):
        calls = []
        zones = {"work", "public"}
        current = {"enp1s0": "work"}
        def runner(argv, **kwargs):
            calls.append(argv)
            args = argv[1:]
            if args == ["--state"]:
                return subprocess.CompletedProcess(argv, 0, "running\n", "")
            if args and args[0].startswith("--get-zone-of-interface="):
                interface = args[0].split("=", 1)[1]
                return subprocess.CompletedProcess(argv, 0, current.get(interface, "public") + "\n", "")
            if args == ["--get-default-zone"]:
                return subprocess.CompletedProcess(argv, 0, "public\n", "")
            if args and args[0].startswith("--zone=work") and args[1] == "--list-interfaces":
                return subprocess.CompletedProcess(argv, 0, "enp1s0 enp2s0\n", "")
            if args and args[0].startswith("--new-zone="):
                zones.add(args[0].split("=", 1)[1])
                return subprocess.CompletedProcess(argv, 0, "", "")
            if len(args) > 1 and args[1].startswith("--add-interface="):
                current[args[1].split("=", 1)[1]] = args[0].split("=", 1)[1]
                return subprocess.CompletedProcess(argv, 0, "", "")
            if len(args) > 1 and args[1].startswith("--remove-interface="):
                current[args[1].split("=", 1)[1]] = "public"
                return subprocess.CompletedProcess(argv, 0, "", "")
            if len(args) > 1 and args[1] == "--add-service=tftp":
                return subprocess.CompletedProcess(argv, 0, "", "")
            if len(args) > 1 and args[1].startswith("--add-port="):
                return subprocess.CompletedProcess(argv, 0, "", "")
            if args and args[0].startswith("--zone=work") and args[1].startswith("--add-interface="):
                current[args[1].split("=", 1)[1]] = "work"
                return subprocess.CompletedProcess(argv, 0, "", "")
            if args == ["--get-zones"]:
                return subprocess.CompletedProcess(argv, 0, " ".join(sorted(zones)), "")
            if args and args[0].startswith("--delete-zone="):
                zones.discard(args[0].split("=", 1)[1])
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=runner)
        firewall.open("enp1s0", ["67/udp", "4011/udp", "8080/tcp"])
        temp_zone = current["enp1s0"]
        self.assertTrue(temp_zone.startswith("feclora-pxe-"))
        self.assertNotEqual(current["enp2s0"] if "enp2s0" in current else "work", temp_zone)
        self.assertTrue(any("--add-service=tftp" in call for call in calls))
        firewall.close("enp1s0")
        self.assertEqual(current["enp1s0"], "work")
        self.assertNotIn(temp_zone, zones)
        self.assertTrue(any("--zone=work" in call and "--add-interface=enp1s0" in call for call in calls))

    def test_rolls_back_temporary_zone_after_port_failure(self):
        calls = []
        zones = {"public"}
        current = {"enp1s0": "public"}
        def runner(argv, **kwargs):
            calls.append(argv)
            args = argv[1:]
            if args == ["--state"]:
                return subprocess.CompletedProcess(argv, 0, "running\n", "")
            if args and args[0].startswith("--get-zone-of-interface="):
                return subprocess.CompletedProcess(argv, 0, current["enp1s0"] + "\n", "")
            if args == ["--get-default-zone"]:
                return subprocess.CompletedProcess(argv, 0, "public\n", "")
            if args and args[0].startswith("--zone=public") and args[1] == "--list-interfaces":
                return subprocess.CompletedProcess(argv, 0, "enp2s0\n", "")
            if args and args[0].startswith("--new-zone="):
                zones.add(args[0].split("=", 1)[1])
                return subprocess.CompletedProcess(argv, 0, "", "")
            if args and args[1].startswith("--add-interface="):
                current["enp1s0"] = args[0].split("=", 1)[1]
                return subprocess.CompletedProcess(argv, 0, "", "")
            if args and args[1].startswith("--remove-interface="):
                current["enp1s0"] = "public"
                return subprocess.CompletedProcess(argv, 0, "", "")
            if args and args[1] == "--add-service=tftp":
                return subprocess.CompletedProcess(argv, 0, "", "")
            if len(args) > 1 and args[1] == "--add-port=4011/udp":
                return subprocess.CompletedProcess(argv, 1, "", "denied")
            if args == ["--get-zones"]:
                return subprocess.CompletedProcess(argv, 0, " ".join(sorted(zones)), "")
            if args and args[0].startswith("--delete-zone="):
                zones.discard(args[0].split("=", 1)[1])
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=runner)
        with self.assertRaises(PXEFirewallError):
            firewall.open("enp1s0", ["67/udp", "4011/udp"])
        self.assertEqual(current["enp1s0"], "public")
        self.assertEqual(zones, {"public"})

    def test_rejects_invalid_port_and_interface(self):
        firewall = PXEFirewall(executable="/usr/bin/firewall-cmd", runner=lambda *a, **k: None)
        with self.assertRaises(PXEFirewallError):
            firewall.open("any", ["67/udp"])
        with self.assertRaises(PXEFirewallError):
            firewall.open("enp1s0", ["99999/tcp"])


if __name__ == "__main__":
    unittest.main()

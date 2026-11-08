import json
import subprocess
import unittest

from feclora.storage.volume_topology import (
    VolumeTopologyError,
    _report_rows,
    collect_lvm_topology,
)


def report(name, rows):
    return json.dumps({"report": [{name: rows}]})


class LvmTopologyTests(unittest.TestCase):
    def test_parses_lvm_report_rows(self):
        rows = [{"pv_name": "/dev/sda2", "vg_name": "vg0"}]
        self.assertEqual(_report_rows(report("pvs", rows), "pvs"), rows)

    def test_rejects_invalid_report(self):
        with self.assertRaises(VolumeTopologyError):
            _report_rows('{"report":[]}', "lvs")

    def test_collects_all_three_read_only_reports(self):
        outputs = {
            "pvs": report("pvs", [{"pv_name": "/dev/sda2", "vg_name": "vg0"}]),
            "vgs": report("vgs", [{"vg_name": "vg0", "pv_count": "1"}]),
            "lvs": report("lvs", [{"lv_path": "/dev/vg0/root", "vg_name": "vg0"}]),
        }
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            name = argv[0].rsplit("/", 1)[-1]
            return subprocess.CompletedProcess(argv, 0, outputs[name], "")
        topology = collect_lvm_topology(
            which=lambda name: "/usr/sbin/" + name,
            runner=runner,
        )
        self.assertEqual(len(topology["pvs"]), 1)
        self.assertEqual(len(topology["vgs"]), 1)
        self.assertEqual(len(topology["lvs"]), 1)
        self.assertTrue(all("--readonly" in argv for argv in calls))
        self.assertTrue(all("--reportformat" in argv for argv in calls))

    def test_missing_tools_mark_topology_incomplete(self):
        topology = collect_lvm_topology(which=lambda _name: None)
        self.assertEqual(topology["status"], "incomplete")
        self.assertEqual(set(topology["missing"]), {"pvs", "vgs", "lvs"})


if __name__ == "__main__":
    unittest.main()

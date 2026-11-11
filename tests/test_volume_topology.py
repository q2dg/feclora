import json
import subprocess
import unittest
from unittest.mock import patch

from feclora.storage.volume_topology import (
    VolumeTopologyError,
    _report_rows,
    collect_lvm_topology,
    summarize_lvm_topology,
)


def report(name, rows):
    return json.dumps({"report": [{name: rows}]})


class LvmTopologyTests(unittest.TestCase):
    def test_parses_lvm_report_rows(self):
        rows = [{"pv_name": "/dev/sda2", "vg_name": "vg0"}]
        self.assertEqual(_report_rows(report("pv", rows), "pvs"), rows)

    def test_rejects_invalid_report(self):
        with self.assertRaises(VolumeTopologyError):
            _report_rows('{"report":[{"lv":"not-a-list"}]}', "lvs")

    def test_collects_all_three_read_only_reports(self):
        outputs = {
            "pvs": report("pv", [{"pv_name": "/dev/sda2", "vg_name": "vg0"}]),
            "vgs": report("vg", [{"vg_name": "vg0", "pv_count": "1"}]),
            "lvs": report("lv", [{"lv_path": "/dev/vg0/root", "vg_name": "vg0"}]),
        }
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            name = argv[0].rsplit("/", 1)[-1]
            return subprocess.CompletedProcess(argv, 0, outputs[name], "")
        topology = collect_lvm_topology(
            which=lambda name: "/usr/sbin/" + name,
            runner=runner,
            effective_uid=lambda: 0,
        )
        self.assertEqual(len(topology["pvs"]), 1)
        self.assertEqual(len(topology["vgs"]), 1)
        self.assertEqual(len(topology["lvs"]), 1)
        self.assertEqual(topology["volume_groups"][0]["name"], "vg0")
        self.assertTrue(all("--readonly" in argv for argv in calls))
        self.assertTrue(all("--reportformat" in argv for argv in calls))
        lvs_call = next(argv for argv in calls if argv[0].endswith("/lvs"))
        self.assertIn("--all", lvs_call)


    def test_summarizes_pv_membership_thin_volumes_and_degraded_vgs(self):
        raw = {
            "status": "available",
            "pvs": [
                {"pv_name": "/dev/sda2", "pv_uuid": "pv-a", "vg_name": "vg0",
                 "pv_size": "100000", "pv_free": "20000",
                 "pv_pe_count": "25", "pv_pe_alloc_count": "20", "pv_missing": ""},
            ],
            "vgs": [
                {"vg_name": "vg0", "vg_uuid": "vg-uuid", "pv_count": "2",
                 "lv_count": "2", "vg_extent_size": "4096",
                 "vg_extent_count": "25", "vg_free_count": "5",
                 "vg_missing_pv_count": "1"},
            ],
            "lvs": [
                {"lv_path": "/dev/vg0/data", "lv_name": "data", "vg_name": "vg0",
                 "lv_size": "80000", "segtype": "thin", "lv_layout": "thin",
                 "pool_lv": "pool0", "data_percent": "42.5",
                 "metadata_percent": "8.0", "devices": "/dev/sda2(0)"},
                {"lv_path": "/dev/vg0/snap", "lv_name": "snap", "vg_name": "vg0",
                 "origin": "data", "lv_role": "public,snapshot", "lv_size": "1000"},
                {"lv_path": "/dev/vg0/[pool_tdata]", "lv_name": "[pool_tdata]",
                 "vg_name": "vg0", "lv_role": "private,thin,pool", "lv_size": "1000"},
            ],
        }
        summary = summarize_lvm_topology(raw)
        vg = summary["volume_groups"][0]
        self.assertEqual(vg["status"], "degraded")
        self.assertEqual(vg["missing_pv_count"], 1)
        self.assertEqual(vg["pv_members"][0]["allocated_extents"], 20)
        self.assertTrue(vg["logical_volumes"][0]["thin_provisioned"])
        self.assertEqual(vg["logical_volumes"][0]["data_percent"], "42.5")
        self.assertTrue(vg["logical_volumes"][1]["snapshot"])
        self.assertTrue(vg["logical_volumes"][2]["hidden"])
        self.assertEqual(summary["lvs"], raw["lvs"])


    def test_missing_pv_attribute_marks_group_degraded_when_count_is_unknown(self):
        summary = summarize_lvm_topology({
            "status": "available",
            "pvs": [{"pv_name": "[unknown]", "vg_name": "vg0", "pv_missing": "missing"}],
            "vgs": [{"vg_name": "vg0", "vg_attr": "wz-pn-"}],
            "lvs": [],
        })
        vg = summary["volume_groups"][0]
        self.assertEqual(vg["status"], "degraded")
        self.assertEqual(vg["missing_pv_count"], 1)
        self.assertTrue(vg["pv_members"][0]["missing"])


    def test_pv_missing_rows_override_inconsistent_zero_vg_count(self):
        summary = summarize_lvm_topology({
            "status": "available",
            "pvs": [{"pv_name": "[unknown]", "vg_name": "vg0", "pv_missing": "missing"}],
            "vgs": [{"vg_name": "vg0", "vg_missing_pv_count": "0"}],
            "lvs": [],
        })
        self.assertEqual(summary["volume_groups"][0]["status"], "degraded")
        self.assertEqual(summary["volume_groups"][0]["missing_pv_count"], 1)

    def test_unknown_health_fields_are_not_reported_as_healthy(self):
        summary = summarize_lvm_topology({
            "status": "available",
            "pvs": [],
            "vgs": [{"vg_name": "vg0"}],
            "lvs": [],
        })
        self.assertEqual(summary["volume_groups"][0]["status"], "unknown")

    def test_vg_partial_flag_uses_the_documented_attribute_position(self):
        partial = summarize_lvm_topology({
            "status": "available", "pvs": [],
            "vgs": [{"vg_name": "partial", "vg_attr": "wz-pn-", "vg_missing_pv_count": "0"}],
            "lvs": [],
        })
        self.assertEqual(partial["volume_groups"][0]["status"], "degraded")

        # A p in the allocation-policy position is not the partial flag.
        healthy = summarize_lvm_topology({
            "status": "available", "pvs": [],
            "vgs": [{"vg_name": "healthy", "vg_attr": "wz--p-", "vg_missing_pv_count": "0"}],
            "lvs": [],
        })
        self.assertEqual(healthy["volume_groups"][0]["status"], "healthy")

    def test_vg_with_zero_missing_pvs_but_unknown_attributes_is_not_healthy(self):
        summary = summarize_lvm_topology({
            "status": "available", "pvs": [],
            "vgs": [{"vg_name": "vg0", "vg_missing_pv_count": "0"}],
            "lvs": [],
        })
        self.assertEqual(summary["volume_groups"][0]["status"], "unknown")

    def test_rejects_non_object_lvm_rows(self):
        with self.assertRaises(VolumeTopologyError):
            summarize_lvm_topology({"pvs": ["bad"], "vgs": [], "lvs": []})

    @patch("feclora.storage.volume_topology.shutil.which", return_value=None)
    def test_unprivileged_collection_requires_noninteractive_sudo(self, _which):
        topology = collect_lvm_topology(
            which=lambda name: "/usr/sbin/" + name,
            sudo=None,
            effective_uid=lambda: 1000,
        )
        self.assertEqual(topology["status"], "permission_required")

    def test_missing_tools_mark_topology_incomplete(self):
        topology = collect_lvm_topology(which=lambda _name: None, effective_uid=lambda: 0)
        self.assertEqual(topology["status"], "incomplete")
        self.assertEqual(set(topology["missing"]), {"pvs", "vgs", "lvs"})


if __name__ == "__main__":
    unittest.main()

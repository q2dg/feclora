from feclora.storage.volume_metadata import annotate_inventory, classify_volume


def test_classifies_lvm_physical_and_logical_volumes():
    assert classify_volume({"type": "part", "fstype": "LVM2_member"}) == ["lvm", "lvm_pv"]
    assert classify_volume({"type": "lvm", "fstype": "xfs"}) == ["lvm", "lvm_lv"]


def test_classifies_btrfs_without_claiming_lvm_or_stratis():
    assert classify_volume({"type": "part", "fstype": "btrfs"}) == ["btrfs"]


def test_classifies_stratis_mapper_conservatively():
    tags = classify_volume({"name": "/dev/mapper/stratis-pool-fs", "type": "dm", "fstype": "xfs"})
    assert tags == ["stratis", "stratis_filesystem"]


def test_does_not_misidentify_plain_xfs_as_stratis():
    assert classify_volume({"name": "/dev/sda1", "type": "part", "fstype": "xfs"}) == []


def test_annotates_nested_inventory_without_mutating_input():
    source = {"schema_version": 1, "devices": [{"name": "sda", "children": [
        {"name": "sda1", "type": "part", "fstype": "btrfs", "children": []}
    ]}]}
    result = annotate_inventory(source)
    assert result["devices"][0]["children"][0]["volume_features"] == ["btrfs"]
    assert "volume_features" not in source["devices"][0]

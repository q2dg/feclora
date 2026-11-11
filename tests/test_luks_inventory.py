import json
import subprocess

import pytest

from feclora.storage.luks_inventory import (
    LuksInventoryError, collect_luks_inventory, parse_luks_metadata,
)


def test_parses_luks2_metadata_without_returning_token_payload():
    payload = json.dumps({
        "uuid": "11111111-2222-3333-4444-555555555555",
        "config": {"json_size": "16384"},
        "keyslots": {"0": {"type": "luks2"}},
        "tokens": {"1": {"type": "systemd-tpm2", "secret": "never expose"}},
        "segments": {"0": {"type": "crypt", "encryption": "aes-xts-plain64", "sector_size": 4096}},
    })
    result = parse_luks_metadata(payload)
    assert result["version"] == 2
    assert result["keyslot_count"] == 1
    assert result["token_count"] == 1
    assert result["cipher"] == "aes-xts-plain64"
    assert result["sector_size"] == 4096
    assert "secret" not in str(result)


def test_collects_nested_luks2_devices():
    calls = []
    payload = json.dumps({"config": {}, "keyslots": {}, "tokens": {},
                          "segments": {"0": {"encryption": "aes-xts-plain64"}}})
    def runner(argv, **kwargs):
        calls.append(argv)
        output = "11111111-2222-3333-4444-555555555555\n" if "luksUUID" in argv else payload
        return subprocess.CompletedProcess(argv, 0, output, "")
    result = collect_luks_inventory(
        [{"path": "/dev/sda", "children": [
            {"path": "/dev/sda2", "filesystem": "crypto_LUKS", "children": []}
        ]}],
        which=lambda name: "/usr/sbin/cryptsetup" if name == "cryptsetup" else None,
        runner=runner, effective_uid=lambda: 0,
    )
    assert result["containers"][0]["device"] == "/dev/sda2"
    assert result["containers"][0]["version"] == 2
    assert len(calls) == 2


def test_no_luks_devices_needs_no_cryptsetup():
    assert collect_luks_inventory([], which=lambda _name: None)["containers"] == []


def test_missing_cryptsetup_is_reported():
    result = collect_luks_inventory(
        [{"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []}],
        which=lambda _name: None,
    )
    assert result["status"] == "unavailable"


def test_rejects_non_json_metadata_instead_of_falling_back_to_luks1():
    with pytest.raises(LuksInventoryError):
        parse_luks_metadata("LUKS header information\\nVersion: 1")

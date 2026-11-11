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
    result = parse_luks_metadata(payload, json_metadata=True)
    assert result["version"] == 2
    assert result["keyslot_count"] == 1
    assert result["token_count"] == 1
    assert "secret" not in str(result)


def test_parses_luks1_header():
    payload = """LUKS header information
Version: 1
Cipher name: aes
Cipher mode: xts-plain64
UUID: 11111111-2222-3333-4444-555555555555
Key Slot 0: ENABLED
Key Slot 1: DISABLED
"""
    result = parse_luks_metadata(payload, json_metadata=False)
    assert result["version"] == 1
    assert result["keyslot_count"] == 1


def test_collects_nested_luks_devices():
    calls = []
    payload = json.dumps({"uuid": "11111111-2222-3333-4444-555555555555",
                          "config": {}, "keyslots": {}, "tokens": {},
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
    assert len(calls) == 2
    assert any("luksUUID" in call for call in calls)


def test_no_luks_devices_needs_no_cryptsetup():
    assert collect_luks_inventory([], which=lambda _name: None)["containers"] == []


def test_missing_cryptsetup_is_reported():
    result = collect_luks_inventory(
        [{"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []}],
        which=lambda _name: None,
    )
    assert result["status"] == "unavailable"


def test_rejects_unrecognized_luks1_text():
    with pytest.raises(LuksInventoryError):
        parse_luks_metadata("not a LUKS header", json_metadata=False)


def test_collects_luks1_when_json_metadata_is_not_supported():
    uuid = "11111111-2222-3333-4444-555555555555"
    text_header = f"""LUKS header information
Version: 1
Cipher name: aes
Cipher mode: xts-plain64
UUID: {uuid}
Key Slot 0: ENABLED
"""
    def runner(argv, **kwargs):
        if "luksUUID" in argv:
            return subprocess.CompletedProcess(argv, 0, uuid + "\n", "")
        if "--dump-json-metadata" in argv:
            raise subprocess.CalledProcessError(1, argv, stderr="LUKS1 has no JSON metadata")
        return subprocess.CompletedProcess(argv, 0, text_header, "")
    result = collect_luks_inventory(
        [{"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []}],
        which=lambda name: "/usr/sbin/cryptsetup" if name == "cryptsetup" else None,
        runner=runner, effective_uid=lambda: 0,
    )
    assert result["containers"][0]["version"] == 1
    assert result["containers"][0]["uuid"] == uuid

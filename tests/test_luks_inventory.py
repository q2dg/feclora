import json
import subprocess
import unittest

from feclora.storage.luks_inventory import (
    LuksInventoryError, collect_luks_inventory, parse_luks_metadata,
)


class LuksInventoryTests(unittest.TestCase):
    def test_parses_luks2_metadata_without_returning_token_payload(self):
        payload = json.dumps({
            "uuid": "11111111-2222-3333-4444-555555555555",
            "config": {"json_size": "16384"},
            "keyslots": {"0": {"type": "luks2"}},
            "tokens": {"1": {"type": "systemd-tpm2", "secret": "never expose"}},
            "segments": {"0": {"type": "crypt", "encryption": "aes-xts-plain64", "sector_size": 4096}},
        })
        result = parse_luks_metadata(payload)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["keyslot_count"], 1)
        self.assertEqual(result["token_count"], 1)
        self.assertEqual(result["cipher"], "aes-xts-plain64")
        self.assertEqual(result["sector_size"], 4096)
        self.assertNotIn("secret", str(result))

    def test_collects_nested_luks2_devices(self):
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
        self.assertEqual(result["containers"][0]["device"], "/dev/sda2")
        self.assertEqual(result["containers"][0]["version"], 2)
        self.assertEqual(len(calls), 2)

    def test_luks1_container_does_not_hide_other_luks2_devices(self):
        payload = json.dumps({
            "uuid": "22222222-2222-3333-4444-555555555555",
            "config": {}, "keyslots": {}, "tokens": {},
            "segments": {"0": {"encryption": "aes-xts-plain64"}},
        })

        def runner(argv, **kwargs):
            device = argv[-1]
            if "luksUUID" in argv:
                value = (
                    "11111111-2222-3333-4444-555555555555"
                    if device == "/dev/sda1"
                    else "22222222-2222-3333-4444-555555555555"
                )
                return subprocess.CompletedProcess(argv, 0, value + "\n", "")
            if "--dump-json-metadata" in argv and device == "/dev/sda1":
                raise subprocess.CalledProcessError(1, argv, stderr="not a LUKS2 device")
            if "--dump-json-metadata" in argv:
                return subprocess.CompletedProcess(argv, 0, payload, "")
            return subprocess.CompletedProcess(argv, 0, "Version: 1\n", "")

        result = collect_luks_inventory(
            [{"path": "/dev/sda", "children": [
                {"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []},
                {"path": "/dev/sda2", "filesystem": "crypto_LUKS", "children": []},
            ]}],
            which=lambda name: "/usr/sbin/cryptsetup" if name == "cryptsetup" else None,
            runner=runner, effective_uid=lambda: 0,
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual([item["device"] for item in result["containers"]], ["/dev/sda2"])
        self.assertEqual(result["unsupported_containers"][0]["device"], "/dev/sda1")
        self.assertEqual(result["unsupported_containers"][0]["version"], 1)

    def test_no_luks_devices_needs_no_cryptsetup(self):
        self.assertEqual(
            collect_luks_inventory([], which=lambda _name: None)["containers"], []
        )

    def test_missing_cryptsetup_is_reported(self):
        result = collect_luks_inventory(
            [{"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []}],
            which=lambda _name: None,
        )
        self.assertEqual(result["status"], "unavailable")

    def test_rejects_non_json_metadata_instead_of_falling_back_to_luks1(self):
        with self.assertRaises(LuksInventoryError):
            parse_luks_metadata("LUKS header information\nVersion: 1")


    def test_rejects_luks2_metadata_without_uuid(self):
        payload = json.dumps({
            "config": {}, "keyslots": {}, "tokens": {},
            "segments": {"0": {"encryption": "aes-xts-plain64"}},
        })
        with self.assertRaisesRegex(LuksInventoryError, "canonical UUID"):
            parse_luks_metadata(payload)

    def test_rejects_invalid_luks2_sector_size(self):
        payload = json.dumps({
            "uuid": "11111111-2222-3333-4444-555555555555",
            "config": {}, "keyslots": {}, "tokens": {},
            "segments": {"0": {"encryption": "aes-xts-plain64", "sector_size": 1000}},
        })
        with self.assertRaisesRegex(LuksInventoryError, "sector size"):
            parse_luks_metadata(payload)

    def test_rejects_conflicting_luks2_segment_ciphers(self):
        payload = json.dumps({
            "uuid": "11111111-2222-3333-4444-555555555555",
            "config": {}, "keyslots": {}, "tokens": {},
            "segments": {
                "0": {"encryption": "aes-xts-plain64"},
                "1": {"encryption": "aes-cbc-essiv"},
            },
        })
        with self.assertRaisesRegex(LuksInventoryError, "conflicting"):
            parse_luks_metadata(payload)


    def test_collect_rejects_disagreeing_luks_uuid_sources(self):
        payload = json.dumps({
            "uuid": "22222222-3333-4444-5555-666666666666",
            "config": {}, "keyslots": {}, "tokens": {},
            "segments": {"0": {"encryption": "aes-xts-plain64"}},
        })

        def runner(argv, **kwargs):
            if "luksUUID" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, "11111111-2222-3333-4444-555555555555\n", ""
                )
            return subprocess.CompletedProcess(argv, 0, payload, "")

        result = collect_luks_inventory(
            [{"path": "/dev/sda1", "filesystem": "crypto_LUKS", "children": []}],
            which=lambda name: "/usr/sbin/cryptsetup" if name == "cryptsetup" else None,
            runner=runner, effective_uid=lambda: 0,
        )
        self.assertEqual(result["containers"], [])
        self.assertEqual(result["errors"][0]["reason"], "LUKS UUID sources disagree")


if __name__ == "__main__":
    unittest.main()

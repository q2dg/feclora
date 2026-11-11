"""Read-only LUKS1/LUKS2 metadata inventory; never reads or stores key material."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable


class LuksInventoryError(RuntimeError):
    """LUKS metadata could not be read or parsed safely."""


_VERSION = re.compile(r"^Version:\s*(\d+)\s*$", re.MULTILINE)
_UUID = re.compile(r"^UUID:\s*([0-9a-fA-F-]{36})\s*$", re.MULTILINE)
_CIPHER = re.compile(r"^Cipher name:\s*(\S+)\s*$", re.MULTILINE)
_MODE = re.compile(r"^Cipher mode:\s*(\S+)\s*$", re.MULTILINE)
_KEY_SLOT = re.compile(r"^Key Slot\s+\d+:\s+(ENABLED|DISABLED)\s*$", re.MULTILINE)


def _luks_devices(devices: list[dict[str, Any]]):
    for device in devices:
        if str(device.get("filesystem") or "").lower() == "crypto_luks":
            path = device.get("path") or device.get("name")
            if isinstance(path, str) and path.startswith("/dev/"):
                yield path
        yield from _luks_devices(device.get("children") or [])


def parse_luks_metadata(payload: str, *, json_metadata: bool) -> dict[str, Any]:
    """Return a minimal summary without exposing token or keyslot payloads."""
    if json_metadata:
        try:
            metadata = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LuksInventoryError("cryptsetup returned invalid LUKS2 JSON metadata") from exc
        if not isinstance(metadata, dict):
            raise LuksInventoryError("LUKS2 metadata must be a JSON object")
        segments = metadata.get("segments") if isinstance(metadata.get("segments"), dict) else {}
        keyslots = metadata.get("keyslots") if isinstance(metadata.get("keyslots"), dict) else {}
        tokens = metadata.get("tokens") if isinstance(metadata.get("tokens"), dict) else {}
        config = metadata.get("config") if isinstance(metadata.get("config"), dict) else {}
        return {
            "version": 2,
            "uuid": metadata.get("uuid"),
            "cipher": next((v.get("encryption") for v in segments.values() if isinstance(v, dict) and v.get("encryption")), None),
            "sector_size": next((v.get("sector_size") for v in segments.values() if isinstance(v, dict) and v.get("sector_size")), None),
            "keyslot_count": len(keyslots),
            "token_count": len(tokens),
            "segment_count": len(segments),
            "metadata_size": config.get("json_size"),
        }
    version, uuid = _VERSION.search(payload), _UUID.search(payload)
    if not version or not uuid or int(version.group(1)) != 1:
        raise LuksInventoryError("cryptsetup output is not a recognized LUKS1 header")
    slots = _KEY_SLOT.findall(payload)
    cipher, mode = _CIPHER.search(payload), _MODE.search(payload)
    return {
        "version": 1,
        "uuid": uuid.group(1),
        "cipher": cipher.group(1) if cipher else None,
        "cipher_mode": mode.group(1) if mode else None,
        "keyslot_count": sum(state == "ENABLED" for state in slots),
        "token_count": 0,
        "segment_count": 1,
    }


def collect_luks_inventory(
    devices: list[dict[str, Any]],
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    effective_uid: Callable[[], int] = os.geteuid,
    sudo: str | None = None,
) -> dict[str, Any]:
    """Inspect LUKS headers discovered by lsblk; do not activate or modify them."""
    paths = sorted(set(_luks_devices(devices)))
    if not paths:
        return {"status": "available", "containers": []}
    cryptsetup = which("cryptsetup")
    if cryptsetup is None:
        return {"status": "unavailable", "missing": ["cryptsetup"], "containers": []}
    prefix: list[str] = []
    if effective_uid() != 0:
        sudo_bin = sudo or shutil.which("sudo")
        if not sudo_bin:
            return {"status": "permission_required", "containers": []}
        prefix = [sudo_bin, "-n"]
    containers = []
    for path in paths:
        try:
            uuid_result = runner([*prefix, cryptsetup, "luksUUID", path],
                                 check=True, capture_output=True, text=True, timeout=20)
            luks_uuid = uuid_result.stdout.strip()
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", luks_uuid):
                raise LuksInventoryError(f"cryptsetup returned an invalid LUKS UUID for {path}")
            result = runner([*prefix, cryptsetup, "luksDump", "--dump-json-metadata", path],
                            check=True, capture_output=True, text=True, timeout=20)
            metadata = parse_luks_metadata(result.stdout, json_metadata=True)
        except subprocess.CalledProcessError:
            try:
                result = runner([*prefix, cryptsetup, "luksDump", path],
                                check=True, capture_output=True, text=True, timeout=20)
                metadata = parse_luks_metadata(result.stdout, json_metadata=False)
            except subprocess.TimeoutExpired as exc:
                raise LuksInventoryError(f"LUKS metadata inspection timed out for {path}") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "").strip()
                raise LuksInventoryError(detail or f"cannot inspect LUKS header on {path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LuksInventoryError(f"LUKS metadata inspection timed out for {path}") from exc
        metadata["uuid"] = luks_uuid
        containers.append({"device": path, **metadata})
    return {"status": "available", "containers": containers}

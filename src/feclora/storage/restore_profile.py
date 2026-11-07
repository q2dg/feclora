"""Validated, declarative restore profiles for repeatable local deployments.

Profiles describe choices; they never contain private key material and do not
bypass device safety checks performed by the restore engine.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RestoreProfileError(ValueError):
    """A restore profile is malformed, unauthorized, expired or mismatched."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RestoreProfileError(f"duplicate profile field: {key}")
        result[key] = value
    return result


def _text(value: Any, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise RestoreProfileError(f"{field} must be a non-empty string of at most {maximum} characters")
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise RestoreProfileError(f"{field} contains whitespace padding or control characters")
    return value


def _utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise RestoreProfileError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RestoreProfileError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RestoreProfileError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class RestoreTargetSelector:
    """Stable physical-device identity; /dev names are intentionally excluded."""

    wwn: str | None = None
    serial: str | None = None

    def __post_init__(self) -> None:
        if self.wwn is None and self.serial is None:
            raise RestoreProfileError("target selector requires a WWN, serial number, or both")
        if self.wwn is not None:
            _text(self.wwn, "target.wwn")
        if self.serial is not None:
            _text(self.serial, "target.serial")

    def matches(self, device: dict[str, Any]) -> bool:
        if not isinstance(device, dict):
            return False
        if self.wwn is not None:
            actual = device.get("wwn")
            if not isinstance(actual, str) or actual.strip().lower() != self.wwn.lower():
                return False
        if self.serial is not None:
            actual = device.get("serial")
            if not isinstance(actual, str) or actual.strip() != self.serial:
                return False
        return True

    def to_dict(self) -> dict[str, str | None]:
        return {"wwn": self.wwn, "serial": self.serial}


@dataclass(frozen=True)
class RestoreProfile:
    profile_id: str
    name: str
    image_manifest: str
    target: RestoreTargetSelector
    execution_mode: str = "interactive"
    layout_policy: str = "preserve"
    verify_after_restore: bool = True
    on_success: str = "none"
    expires_at: str | None = None
    single_use: bool = False
    schema_version: int = 1
    signature_verified: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        import uuid

        try:
            parsed = uuid.UUID(self.profile_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RestoreProfileError("profile_id must be a UUID") from exc
        if str(parsed) != self.profile_id:
            raise RestoreProfileError("profile_id must use canonical UUID notation")
        _text(self.name, "name", 80)
        _text(self.image_manifest, "image_manifest", 255)
        if (self.image_manifest in {".", ".."} or "/" in self.image_manifest
                or "\\" in self.image_manifest or not self.image_manifest.endswith(".json")):
            raise RestoreProfileError("image_manifest must be a JSON filename inside the configured repository")
        if self.execution_mode not in {"interactive", "confirm", "unattended"}:
            raise RestoreProfileError("execution_mode must be interactive, confirm or unattended")
        if self.layout_policy not in {"preserve", "proportional"}:
            raise RestoreProfileError("layout_policy must be preserve or proportional")
        if not isinstance(self.verify_after_restore, bool) or not self.verify_after_restore:
            raise RestoreProfileError("restore profiles must require post-write verification")
        if self.on_success not in {"none", "reboot", "poweroff"}:
            raise RestoreProfileError("on_success must be none, reboot or poweroff")
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise RestoreProfileError("unsupported restore profile schema version")
        if not isinstance(self.single_use, bool):
            raise RestoreProfileError("single_use must be boolean")
        if self.expires_at is not None:
            _utc_datetime(self.expires_at, "expires_at")
        if self.execution_mode == "unattended":
            if self.expires_at is None:
                raise RestoreProfileError("unattended profiles require an expiry timestamp")
            if not self.single_use:
                raise RestoreProfileError("unattended profiles must be single-use")
        if not isinstance(self.signature_verified, bool):
            raise RestoreProfileError("signature_verified is runtime-only boolean state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "name": self.name,
            "image_manifest": self.image_manifest,
            "target": self.target.to_dict(),
            "execution_mode": self.execution_mode,
            "layout_policy": self.layout_policy,
            "verify_after_restore": self.verify_after_restore,
            "on_success": self.on_success,
            "expires_at": self.expires_at,
            "single_use": self.single_use,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Any) -> "RestoreProfile":
        required = {
            "schema_version", "profile_id", "name", "image_manifest", "target",
            "execution_mode", "layout_policy", "verify_after_restore", "on_success",
            "expires_at", "single_use",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise RestoreProfileError("restore profile has missing or unknown fields")
        target = value["target"]
        if not isinstance(target, dict) or set(target) != {"wwn", "serial"}:
            raise RestoreProfileError("target selector must contain exactly wwn and serial")
        try:
            selector = RestoreTargetSelector(**target)
            fields = {key: item for key, item in value.items() if key != "target"}
            return cls(target=selector, **fields)
        except TypeError as exc:
            raise RestoreProfileError(f"invalid restore profile fields: {exc}") from exc

    @classmethod
    def from_json(cls, raw: str) -> "RestoreProfile":
        try:
            value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise RestoreProfileError(f"invalid restore profile JSON: {exc}") from exc
        return cls.from_dict(value)

    def authorize(
        self,
        device: dict[str, Any],
        *,
        now: datetime | None = None,
        already_consumed: bool = False,
    ) -> None:
        """Check target binding and unattended authorization immediately pre-write."""
        if not self.target.matches(device):
            raise RestoreProfileError("detected target WWN/serial does not match this restore profile")
        if self.execution_mode == "unattended":
            if not self.signature_verified:
                raise RestoreProfileError("unattended profile has not been verified with a trusted minisign key")
            current = now or datetime.now(timezone.utc)\n            if current.tzinfo is None or current.utcoffset() is None:\n                raise RestoreProfileError("authorization clock must be timezone-aware")\n            current = current.astimezone(timezone.utc)
            if _utc_datetime(self.expires_at, "expires_at") <= current:
                raise RestoreProfileError("unattended restore profile has expired")
            if already_consumed:
                raise RestoreProfileError("unattended restore profile has already been consumed")


def _regular_file(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RestoreProfileError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise RestoreProfileError(f"{label} must be a regular file, not a symlink or special file")


def load_restore_profile(
    path: str | os.PathLike[str],
    *,
    minisign_public_key: str | os.PathLike[str] | None = None,
    minisign_executable: str | None = None,
) -> RestoreProfile:
    """Load a profile; unattended profiles must have a trusted minisign signature."""
    profile_path = Path(path)
    _regular_file(profile_path, "restore profile")
    try:
        raw = profile_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RestoreProfileError(f"cannot read restore profile: {exc}") from exc
    profile = RestoreProfile.from_json(raw)
    if profile.execution_mode != "unattended":
        return profile
    if minisign_public_key is None:
        raise RestoreProfileError("unattended profile requires a configured trusted minisign public key")
    key_path = Path(minisign_public_key)
    signature_path = Path(str(profile_path) + ".minisig")
    _regular_file(key_path, "trusted minisign public key")
    _regular_file(signature_path, "restore profile signature")
    executable = minisign_executable or shutil.which("minisign")
    if not executable:
        raise RestoreProfileError("minisign is required to authorize unattended restore profiles")
    try:
        subprocess.run(
            [executable, "-Vm", str(profile_path), "-x", str(signature_path), "-p", str(key_path)],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RestoreProfileError(f"restore profile signature verification failed: {exc}") from exc
    object.__setattr__(profile, "signature_verified", True)\n    return profile

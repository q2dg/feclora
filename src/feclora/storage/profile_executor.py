"""Execute signed, single-use unattended whole-disk restore profiles."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from feclora.storage.disk_restore import restore_disk
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.operation_log import DEFAULT_LOG_PATH, operation_record
from feclora.storage.restore_profile import (
    RestoreProfile,
    RestoreProfileError,
    load_restore_profile,
)
from feclora.storage.inventory import collect_inventory

DEFAULT_PROFILE_DIRECTORY = Path("/home/feclora/profiles")
DEFAULT_CONSUMPTION_LEDGER = Path("/home/feclora/logs/consumed-restore-profiles.jsonl")
_MAX_LEDGER_BYTES = 8 * 1024 * 1024


def _consume_profile_once(profile_id: str, ledger_path: str | os.PathLike[str]) -> None:
    """Atomically consume a profile ID immediately before the first disk write."""
    destination = Path(ledger_path)
    directory = destination.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        dir_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            dir_info = os.fstat(dir_fd)
            if not stat.S_ISDIR(dir_info.st_mode) or dir_info.st_uid != os.geteuid():
                raise RestoreProfileError("profile consumption ledger directory has unsafe type or ownership")
            os.fchmod(dir_fd, 0o700)
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(destination.name, flags, 0o600, dir_fd=dir_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                    raise RestoreProfileError("profile consumption ledger has unsafe type or ownership")
                if info.st_size > _MAX_LEDGER_BYTES:
                    raise RestoreProfileError("profile consumption ledger exceeds its safety limit")
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.lseek(fd, 0, os.SEEK_SET)
                chunks = []
                remaining = _MAX_LEDGER_BYTES + 1
                while remaining:
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
                if len(raw) > _MAX_LEDGER_BYTES:
                    raise RestoreProfileError("profile consumption ledger exceeds its safety limit")
                consumed: set[str] = set()
                for line_number, line in enumerate(raw.splitlines(), 1):
                    try:
                        event = json.loads(line.decode("utf-8"))
                        value = event["profile_id"]
                    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                        raise RestoreProfileError(
                            f"profile consumption ledger is corrupt at line {line_number}"
                        ) from exc
                    if not isinstance(value, str):
                        raise RestoreProfileError(
                            f"profile consumption ledger has invalid profile ID at line {line_number}"
                        )
                    consumed.add(value)
                if profile_id in consumed:
                    raise RestoreProfileError("unattended restore profile has already been consumed")
                payload = (json.dumps({
                    "profile_id": profile_id,
                    "status": "consumed",
                }, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise RestoreProfileError("short write while consuming restore profile")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except RestoreProfileError:
        raise
    except OSError as exc:
        raise RestoreProfileError(f"cannot persist one-time profile authorization: {exc}") from exc


def _matching_target(profile: RestoreProfile, inventory: dict[str, Any]) -> dict[str, Any]:
    matches = [
        device for device in inventory.get("devices", [])
        if device.get("type") == "disk" and profile.target.matches(device)
    ]
    if len(matches) != 1:
        raise RestoreProfileError(
            f"stable target selector matched {len(matches)} disks; exactly one is required"
        )
    target = matches[0]
    path = target.get("path")
    if not isinstance(path, str) or not path.startswith("/dev/"):
        raise RestoreProfileError("matched target has no valid local block-device path")
    return target


def execute_unattended_restore_profile(
    profile_path: str | os.PathLike[str],
    *,
    profile_trusted_key: str | os.PathLike[str],
    image_trusted_key: str | os.PathLike[str],
    repository: str | os.PathLike[str] = "/home/feclora/images",
    age_identity_file: str | os.PathLike[str] | None = None,
    consumption_ledger: str | os.PathLike[str] = DEFAULT_CONSUMPTION_LEDGER,
    operation_log_path: str | os.PathLike[str] = DEFAULT_LOG_PATH,
    inventory: dict[str, Any] | None = None,
    restore_function: Any = restore_disk,
    command_runner: Any = subprocess.run,
) -> ImageManifest:
    """Run one signed profile; all destructive preflight remains in restore_disk."""
    profile = load_restore_profile(
        profile_path, minisign_public_key=profile_trusted_key,
    )
    if profile.execution_mode != "unattended":
        raise RestoreProfileError("profile execution mode is not unattended")
    if profile.layout_policy != "preserve":
        raise RestoreProfileError(
            "proportional layout execution is not yet available; choose preserve for this raw-disk executor"
        )
    if not profile.single_use or not profile.verify_after_restore:
        raise RestoreProfileError("unattended profile must be single-use and require read-back verification")
    current_inventory = inventory if inventory is not None else collect_inventory()
    target = _matching_target(profile, current_inventory)
    profile.authorize(target)
    repository_path = Path(repository)
    manifest_path = repository_path / profile.image_manifest
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise RestoreProfileError(f"cannot load profile image manifest: {exc}") from exc
    if manifest.image_type != "disk":
        raise RestoreProfileError("unattended profile executor currently supports whole-disk images only")
    if age_identity_file is None and any(item.encryption == "age" for item in manifest.artifacts):
        raise RestoreProfileError("this image requires an age identity supplied outside the profile")
    target_path = target["path"]

    def consume_before_write() -> None:
        _consume_profile_once(profile.profile_id, consumption_ledger)

    with operation_record(
        "unattended-restore-profile",
        target_path,
        image_id=profile.profile_id,
        log_path=operation_log_path,
    ):
        restored = restore_function(
            profile.image_manifest,
            repository_path,
            target_path,
            confirmation=f"ERASE {target_path}",
            age_identity_file=age_identity_file,
            minisign_public_key=image_trusted_key,
            require_signature=True,
            pre_write_callback=consume_before_write,
        )
    if profile.on_success in {"reboot", "poweroff"}:
        command_runner(["systemctl", profile.on_success], check=True, timeout=30)
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one signed, single-use feclora whole-disk restore profile."
    )
    parser.add_argument("--profile", required=True, help="Path to the signed restore profile JSON")
    parser.add_argument("--profile-trusted-key", required=True, help="Trusted minisign public key for the profile")
    parser.add_argument("--image-trusted-key", required=True, help="Trusted minisign public key for the image manifest")
    parser.add_argument("--repository", default="/home/feclora/images")
    parser.add_argument("--age-identity", help="Protected path to the age identity; never stored in the profile")
    args = parser.parse_args(argv)
    try:
        manifest = execute_unattended_restore_profile(
            args.profile,
            profile_trusted_key=args.profile_trusted_key,
            image_trusted_key=args.image_trusted_key,
            repository=args.repository,
            age_identity_file=args.age_identity,
        )
    except (RestoreProfileError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"feclora-restore-profile: {exc}", file=sys.stderr)
        return 1
    print(f"Verified restore completed: {manifest.image_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

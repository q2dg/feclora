"""Privileged, allowlisted Cockpit API for Feclora storage workflows.

Requests are one bounded JSON object on stdin. Long operations run in this
process and emit newline-delimited progress events followed by one result.
No shell, arbitrary argv, filesystem path outside the Feclora repository, or
untyped destructive operation is exposed.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import collect_inventory

REPOSITORY = Path("/var/lib/feclora/images")
MAX_REQUEST = 16 * 1024


class WebAPIError(RuntimeError):
    """A Cockpit API request was invalid or could not be fulfilled."""


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WebAPIError(f"duplicate request field: {key}")
        result[key] = value
    return result


def _repository(*, create: bool = False) -> Path:
    parent = REPOSITORY.parent
    if create:
        parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    try:
        parent_info = os.lstat(parent)
    except OSError as exc:
        raise WebAPIError("Feclora state directory is unavailable") from exc
    if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
            or parent_info.st_uid != 0 or parent_info.st_mode & 0o077):
        raise WebAPIError("Feclora state directory must be a private root-owned real directory")
    if create:
        REPOSITORY.mkdir(mode=0o700, exist_ok=True)
    try:
        info = os.lstat(REPOSITORY)
    except FileNotFoundError:
        return REPOSITORY
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise WebAPIError("Feclora image repository must be a private root-owned real directory")
    if create:
        os.chmod(REPOSITORY, 0o700)
    return REPOSITORY


def _image_manifest(image_id: str) -> Path:
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise WebAPIError("image identifier is invalid")
    path = _repository() / f"{image_id}.manifest.json"
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise WebAPIError("selected image manifest does not exist") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise WebAPIError("selected image manifest is not a root-owned regular file")
    return path


def _device(value: Any, field: str) -> str:
    if (not isinstance(value, str)
            or not re.fullmatch(r"/dev/[A-Za-z0-9_.!/+:-]{1,120}", value)
            or ".." in Path(value).parts
            or os.path.normpath(value) != value):
        raise WebAPIError(f"{field} must be a normalized /dev block-device path")
    return value


def _text(params: dict[str, Any], key: str, *, default: str | None = None,
          pattern: str | None = None, maximum: int = 128) -> str:
    value = params.get(key, default)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WebAPIError(f"{key} must be a non-empty string of at most {maximum} characters")
    if pattern and not re.fullmatch(pattern, value):
        raise WebAPIError(f"{key} contains unsupported characters")
    return value


def _progress(done: int, total: int | None) -> None:
    _emit({"event": "progress", "bytes_done": max(0, int(done)),
           "bytes_total": int(total) if total is not None else None})


def _security_material() -> dict[str, bool]:
    directory = Path("/etc/feclora/pki")
    files = {
        "age_encryption_available": directory / "age-recipients.txt",
        "age_decryption_available": directory / "server.age",
        "image_signing_available": directory / "server.minisign.key",
        "image_verification_available": directory / "server.pub",
    }
    result = {}
    for label, path in files.items():
        try:
            info = os.lstat(path)
            result[label] = (
                stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == 0
                and (label not in {"age_decryption_available", "image_signing_available"}
                     or not info.st_mode & 0o077)
            )
        except OSError:
            result[label] = False
    return result


def _initialize_security() -> dict[str, Any]:
    from feclora.deployment.managed_pki import initialize_server_pki

    before = _security_material()
    created = not all(before.values())
    pki = Path("/etc/feclora/pki")
    initialize_server_pki(pki)
    age_identity = pki / "server.age"
    age_recipients = pki / "age-recipients.txt"
    if age_identity.exists() != age_recipients.exists():
        raise WebAPIError("partial age identity exists; refusing to regenerate trust material")
    if not age_identity.exists():
        generated = subprocess.run(
            ["/usr/bin/age-keygen", "-o", str(age_identity)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=60,
        )
        if generated.returncode != 0:
            raise WebAPIError("age-keygen failed while creating the local image identity")
        public = subprocess.run(
            ["/usr/bin/age-keygen", "-y", str(age_identity)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
        recipient = public.stdout.strip()
        if public.returncode != 0 or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
            raise WebAPIError("age-keygen did not return a valid recipient")
        fd = os.open(age_recipients, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(recipient + "\\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(age_identity, 0o600)
    signing_secret = pki / "server.minisign.key"
    signing_public = pki / "server.pub"
    if signing_secret.exists() != signing_public.exists():
        raise WebAPIError("partial minisign keypair exists; refusing to regenerate trust material")
    if not signing_secret.exists():
        generated = subprocess.run(
            ["/usr/bin/minisign", "-G", "-s", str(signing_secret), "-p", str(signing_public), "-W"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=60,
        )
        if generated.returncode != 0:
            raise WebAPIError("minisign failed while creating the local image-signing key")
        os.chmod(signing_secret, 0o600)
        os.chmod(signing_public, 0o644)
    return {"created": created, **_security_material()}


def _images() -> list[dict[str, Any]]:
    path = _repository()
    if not path.exists():
        return []
    items = []
    for manifest_path in sorted(path.glob("*.manifest.json")):
        try:
            info = os.lstat(manifest_path)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
                continue
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError):
            continue
        items.append({
            "image_id": manifest.image_id,
            "image_type": manifest.image_type,
            "source_size_bytes": manifest.source_size_bytes,
            "logical_sector_size": manifest.logical_sector_size,
            "signed": os.path.isfile(str(manifest_path) + ".minisig"),
            "encrypted": bool(manifest.artifacts) and all(
                artifact.encryption == "age" for artifact in manifest.artifacts
            ),
            "artifact_count": len(manifest.artifacts),
        })
    return items


def _operations() -> list[dict[str, Any]]:
    path = Path("/var/lib/feclora/operations.jsonl")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise WebAPIError("operation journal must be a private root-owned regular file")
    if info.st_size > 2 * 1024 * 1024:
        raise WebAPIError("operation journal exceeds the Cockpit read limit")
    records = []
    for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _service_state() -> dict[str, str]:
    services = {}
    for service in ("cockpit.socket", "feclora-dnsmasq.service", "feclora-caddy.service"):
        try:
            result = subprocess.run(
                ["/usr/bin/systemctl", "is-active", service],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=3,
            )
            services[service] = result.stdout.strip() or "inactive"
        except (OSError, subprocess.SubprocessError):
            services[service] = "unknown"
    return services


def _execute_operation(action: str, params: dict[str, Any], operation_id: str) -> dict[str, Any]:
    allowed = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "sign"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "sign"},
        "restore_disk": {"image_id", "target", "confirmation"},
        "restore_partition": {"image_id", "target", "confirmation"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
    }
    if action not in allowed or set(params) != allowed[action]:
        raise WebAPIError("operation parameters do not match the selected operation")
    started = time.monotonic()
    _emit({"event": "started", "operation_id": operation_id, "operation": action})
    if action == "capture_disk":
        from feclora.storage.disk_capture import capture_disk
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|zstd|lz4)")
        encrypt, sign = params["encrypt"], params["sign"]
        if not isinstance(encrypt, bool) or not isinstance(sign, bool):
            raise WebAPIError("encrypt and sign must be boolean values")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling age encryption")
        if sign and not security["image_signing_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling image signatures")
        pki = Path("/etc/feclora/pki")
        manifest = capture_disk(
            source, image_id, _repository(create=True), compression=compression,
            progress_callback=_progress,
            age_recipients_file=pki / "age-recipients.txt" if encrypt else None,
            minisign_secret_key=pki / "server.minisign.key" if sign else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "capture_partition":
        from feclora.storage.partition_image_capture import capture_partition_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        partition_id = _text(params, "partition_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|zstd|lz4)")
        encrypt, sign = params["encrypt"], params["sign"]
        if not isinstance(encrypt, bool) or not isinstance(sign, bool):
            raise WebAPIError("encrypt and sign must be boolean values")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling age encryption")
        if sign and not security["image_signing_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling image signatures")
        pki = Path("/etc/feclora/pki")
        manifest = capture_partition_image(
            source, image_id, partition_id, _repository(create=True),
            compression=compression, progress_callback=_progress,
            age_recipients_file=pki / "age-recipients.txt" if encrypt else None,
            minisign_secret_key=pki / "server.minisign.key" if sign else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action in {"restore_disk", "restore_partition"}:
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        target = _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        manifest_path = _image_manifest(image_id)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        expected_type = "disk" if action == "restore_disk" else "partition"
        if manifest.image_type != expected_type:
            raise WebAPIError(f"selected image is not a {expected_type} image")
        security = _security_material()
        signed = os.path.isfile(str(manifest_path) + ".minisig")
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        if signed and not security["image_verification_available"]:
            raise WebAPIError("signed image requires the trusted Feclora minisign public key")
        if encrypted and not security["age_decryption_available"]:
            raise WebAPIError("age-encrypted image requires the local Feclora age identity")
        pki = Path("/etc/feclora/pki")
        if action == "restore_disk":
            from feclora.storage.disk_restore import restore_disk
            restore_disk(
                manifest_path, _repository(), target, confirmation=expected,
                progress_callback=_progress,
                age_identity_file=pki / "server.age" if encrypted else None,
                minisign_public_key=pki / "server.pub" if signed else None,
                require_signature=signed,
            )
        else:
            from feclora.storage.partition_restore import restore_partition
            restore_partition(
                manifest_path, _repository(), target, confirmation=expected,
                progress_callback=_progress,
                age_identity_file=pki / "server.age" if encrypted else None,
                minisign_public_key=pki / "server.pub" if signed else None,
                require_signature=signed,
            )
        result = {"image_id": image_id, "target": target, "verified": True}
    elif action == "clone_disk":
        from feclora.storage.disk_clone import clone_disk
        source, target = _device(params["source"], "source"), _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        copied = clone_disk(source, target, confirmation=expected,
                            progress_callback=lambda done, message: _emit(
                                {"event": "progress", "bytes_done": int(done),
                                 "bytes_total": None, "message": str(message)[:256]}))
        result = {"source": source, "target": target, "bytes_copied": copied}
    else:
        from feclora.storage.partition_clone import clone_partition
        source, target = _device(params["source"], "source"), _device(params["target"], "target")
        expected = f"ERASE {target} FROM {source}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        copied = clone_partition(source, target, confirmation=expected, progress_callback=_progress)
        result = {"source": source, "target": target, "bytes_copied": copied}
    return {"operation_id": operation_id, "elapsed_seconds": round(time.monotonic() - started, 2),
            **result}


def _run_operation(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "sign"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "sign"},
        "restore_disk": {"image_id", "target", "confirmation"},
        "restore_partition": {"image_id", "target", "confirmation"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
    }
    if action not in operation_fields or set(params) != operation_fields[action]:
        raise WebAPIError("operation parameters do not match the selected operation")
    from feclora.storage.operation_log import operation_record

    target = params.get("target") or params.get("source") or "unspecified"
    image_id = params.get("image_id")
    with operation_record(
        action, str(target), image_id=image_id,
        log_path="/var/lib/feclora/operations.jsonl",
    ) as operation_id:
        return _execute_operation(action, params, operation_id)


def dispatch(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) - {"action", "params"} or "action" not in request:
        raise WebAPIError("request must contain an action and optional params object")
    action = request["action"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise WebAPIError("params must be a JSON object")
    if action == "status":
        if params:
            raise WebAPIError("status does not accept parameters")
        return {
            "hostname": socket.gethostname(), "platform": platform.platform(),
            "python": platform.python_version(),
            "server_configured": os.path.isfile("/etc/feclora/deployment-server.json"),
            "client_configured": os.path.isfile("/etc/feclora/deployment-client.json"),
            "services": _service_state(),
            "security": _security_material(),
        }
    if action == "inventory":
        if params:
            raise WebAPIError("inventory does not accept parameters")
        return collect_inventory()
    if action == "images":
        if params:
            raise WebAPIError("images does not accept parameters")
        return {"images": _images()}
    if action == "operations":
        if params:
            raise WebAPIError("operations does not accept parameters")
        return {"operations": _operations()}
    if action == "initialize_security":
        if params:
            raise WebAPIError("initialize_security does not accept parameters")
        return _initialize_security()
    if action == "journals":
        if params:
            raise WebAPIError("journals does not accept parameters")
        from feclora.deployment.journal import DeploymentJournal
        directory = Path("/var/lib/feclora/deployments")
        reports = []
        if directory.exists():
            info = os.lstat(directory)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                raise WebAPIError("deployment journal directory is unsafe")
            for journal_path in sorted(directory.glob("*.jsonl")):
                report = DeploymentJournal.inspect(journal_path).recovery_report()
                reports.append({"job_id": report["job_id"], "job_state": report["job_state"],
                                "interrupted": report["interrupted"], "event_count": report["event_count"],
                                "clients": {mac: item["state"] for mac, item in report["clients"].items()}})
        return {"journals": reports}
    if action in {"capture_disk", "capture_partition", "restore_disk", "restore_partition",
                  "clone_disk", "clone_partition"}:
        return _run_operation(action, params)
    raise WebAPIError("unsupported Cockpit API action")


def main() -> int:
    if os.geteuid() != 0:
        _emit({"ok": False, "error": "Feclora Cockpit API requires authorized root execution"})
        return 1
    if len(sys.argv) != 2:
        _emit({"ok": False, "error": "one API command is required"})
        return 2
    try:
        raw = sys.stdin.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise WebAPIError("request exceeds the size limit")
        request = json.loads(raw or "{}", object_pairs_hook=_reject_duplicates)
        if not isinstance(request, dict) or request.get("action") != sys.argv[1]:
            raise WebAPIError("request action does not match the authorized command")
        response = {"ok": True, "data": dispatch(request)}
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)[:512]})
        return 1
    _emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

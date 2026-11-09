"""Privileged, allowlisted Cockpit API for Feclora storage workflows.

Requests are one bounded JSON object on stdin. Long operations run in this
process and emit newline-delimited progress events followed by one result.
No shell, arbitrary argv, filesystem path outside the Feclora repository, or
untyped destructive operation is exposed.
"""
from __future__ import annotations

import json
from dataclasses import replace
import ipaddress
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import sys
import time
from contextlib import contextmanager
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


def _image_manifest(image_id: str, repository: Path | None = None) -> Path:
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise WebAPIError("image identifier is invalid")
    path = (repository or _repository()) / f"{image_id}.manifest.json"
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise WebAPIError("selected image manifest does not exist") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise WebAPIError("selected image manifest is not a root-owned regular file")
    return path


def _operation_repository(params: dict[str, Any], *, write: bool, create_local: bool = False) -> Path:
    """Resolve a local or explicitly selected, identity-verified image repository."""
    repository_id = params.get("repository_id")
    if repository_id is None:
        return _repository(create=create_local)
    if (not isinstance(repository_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", repository_id)):
        raise WebAPIError("repository_id is invalid")
    try:
        return Path(_remote_repository_manager().resolve(repository_id, write=write))
    except Exception as exc:
        raise WebAPIError(f"selected image repository is not safely available: {exc}") from exc


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
    from feclora.storage.operation_log import record_progress

    bytes_done = max(0, int(done))
    bytes_total = int(total) if total is not None else None
    record_progress(bytes_done, bytes_total)
    _emit({"event": "progress", "bytes_done": bytes_done,
           "bytes_total": bytes_total})


def _clone_disk_progress(done: int, message: str) -> None:
    from feclora.storage.operation_log import record_progress

    bytes_done = max(0, int(done))
    record_progress(bytes_done, None)
    _emit({
        "event": "progress", "bytes_done": bytes_done,
        "bytes_total": None, "message": str(message)[:256],
    })


def _client_runtime_config() -> Any | None:
    path = Path("/etc/feclora/deployment-client.json")
    if not path.exists():
        return None
    from feclora.deployment.runtime_config import load_client_runtime_config
    return load_client_runtime_config(str(path))


def _capture_material() -> tuple[Path | None, Path | None]:
    pki = Path("/etc/feclora/pki")
    client = _client_runtime_config()
    recipients = Path(client.age_recipients_file) if client and client.age_recipients_file else pki / "age-recipients.txt"
    signing = Path(client.local_minisign_secret_key) if client and client.local_minisign_secret_key else pki / "server.minisign.key"
    return recipients, signing


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
    client = _client_runtime_config()
    if client:
        result["age_encryption_available"] = result["age_encryption_available"] or bool(client.age_recipients_file)
        result["age_decryption_available"] = result["age_decryption_available"] or bool(client.age_identity_file)
        result["image_signing_available"] = result["image_signing_available"] or bool(client.local_minisign_secret_key)
        result["image_verification_available"] = result["image_verification_available"] or bool(client.trusted_server_public_key)
    return result


def _renew_server_certificate(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"confirmation"} or params.get("confirmation") != "RENEW SERVER CERTIFICATE":
        raise WebAPIError("explicit confirmation required: RENEW SERVER CERTIFICATE")
    config_path = "/etc/feclora/deployment-server.json"
    try:
        from feclora.deployment.runtime_config import load_server_runtime_config
        config = load_server_runtime_config(config_path)
    except Exception as exc:
        raise WebAPIError(f"managed Server identity is unavailable: {exc}") from exc
    if os.path.realpath(config.certificate_file) != "/etc/feclora/pki/server.crt" or os.path.realpath(
        config.private_key_file
    ) != "/etc/feclora/pki/server.key" or os.path.realpath(config.ca_file) != "/etc/feclora/pki/ca.crt":
        raise WebAPIError("Server PKI paths differ from the managed renewal locations; refusing to replace an untracked certificate")
    if config.local_identity != "URI:feclora-server":
        raise WebAPIError("Server runtime identity is not the managed Feclora Server identity")
    try:
        active = subprocess.run(
            ["/usr/bin/systemctl", "list-units", "--type=service", "--state=running",
             "--no-legend", "feclora-deployment@*.service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WebAPIError(f"cannot establish whether a deployment service is active: {exc}") from exc
    if active.returncode != 0:
        raise WebAPIError("cannot establish whether a deployment service is active; Server certificate renewal is blocked")
    if active.stdout.strip():
        raise WebAPIError("stop all active deployment jobs before renewing the Server TLS certificate")
    try:
        from feclora.deployment.managed_pki import renew_server_certificate, certificate_expiry_days
        renewed = renew_server_certificate("/etc/feclora/pki")
        days = certificate_expiry_days(renewed["certificate_file"])
    except Exception as exc:
        raise WebAPIError(f"Server TLS certificate renewal failed: {exc}") from exc
    return {
        "renewed": True, "identity": config.local_identity,
        "certificate_file": renewed["certificate_file"],
        "ca_fingerprint": renewed["ca_fingerprint"], "expiry_days": days,
        "ca_expiry_days": renewed["ca_expiry_days"],
        "message": "Server TLS certificate renewed with the existing CA and private key. The CA, Server identity, Client trust and image-signing keys were not changed.",
    }



def _rotate_server_keypair(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"confirmation"} or params.get("confirmation") != "ROTATE SERVER TLS KEYPAIR":
        raise WebAPIError("explicit confirmation required: ROTATE SERVER TLS KEYPAIR")
    try:
        from feclora.deployment.runtime_config import load_server_runtime_config
        config = load_server_runtime_config("/etc/feclora/deployment-server.json")
    except Exception as exc:
        raise WebAPIError(f"managed Server identity is unavailable: {exc}") from exc
    if (os.path.realpath(config.certificate_file) != "/etc/feclora/pki/server.crt"
            or os.path.realpath(config.private_key_file) != "/etc/feclora/pki/server.key"
            or os.path.realpath(config.ca_file) != "/etc/feclora/pki/ca.crt"
            or config.local_identity != "URI:feclora-server"):
        raise WebAPIError("Server PKI paths or identity differ from the managed rotation locations")
    try:
        active = subprocess.run(
            ["/usr/bin/systemctl", "list-units", "--type=service", "--state=running",
             "--no-legend", "feclora-deployment@*.service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WebAPIError(f"cannot establish whether a deployment service is active: {exc}") from exc
    if active.returncode != 0:
        raise WebAPIError("cannot establish whether a deployment service is active; Server key rotation is blocked")
    if active.stdout.strip():
        raise WebAPIError("stop all active deployment jobs before rotating the Server TLS keypair")
    try:
        from feclora.deployment.managed_pki import rotate_server_keypair, certificate_expiry_days
        rotated = rotate_server_keypair("/etc/feclora/pki")
        days = certificate_expiry_days(rotated["certificate_file"])
    except Exception as exc:
        raise WebAPIError(f"Server TLS keypair rotation failed: {exc}") from exc
    return {
        "rotated": True, "identity": config.local_identity,
        "certificate_file": rotated["certificate_file"],
        "private_key_file": rotated["private_key_file"],
        "ca_fingerprint": rotated["ca_fingerprint"], "key_rotated": rotated["key_rotated"],
        "expiry_days": days, "ca_expiry_days": rotated["ca_expiry_days"],
        "message": "Server TLS keypair rotated under the existing CA. Enrolled Clients retain CA trust and Server identity; the Server certificate and private key have both changed.",
    }

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
            stream.write(recipient + "\n")
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


def _images(repository_id: str | None = None) -> list[dict[str, Any]]:
    path = _operation_repository({"repository_id": repository_id}, write=False) if repository_id else _repository()
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


def _inspect_image_layout(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) not in ({"image_id"}, {"image_id", "repository_id"}):
        raise WebAPIError("inspect_image_layout requires image_id and optional repository_id")
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    repository = _operation_repository(params, write=False)
    manifest_path = _image_manifest(image_id, repository)
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WebAPIError(f"cannot read selected image manifest: {exc}") from exc
    if manifest.image_id != image_id:
        raise WebAPIError("selected image manifest identifier does not match its repository name")
    if manifest.image_type != "disk":
        raise WebAPIError("layout inspection requires a whole-disk image")
    signed = os.path.isfile(str(manifest_path) + ".minisig")
    if signed:
        from feclora.storage.image_security import verify_manifest_signature
        security = _security_material()
        pki = Path("/etc/feclora/pki")
        trusted_keys = [pki / "server.pub"] if security["image_verification_available"] else []
        client_config = _client_runtime_config()
        if client_config and client_config.trusted_server_public_key:
            trusted_keys.insert(0, Path(client_config.trusted_server_public_key))
        verified = False
        for candidate in dict.fromkeys(trusted_keys):
            try:
                verify_manifest_signature(manifest_path, candidate)
                verified = True
                break
            except Exception:
                continue
        if not verified:
            raise WebAPIError("signed disk image does not verify against any locally trusted Feclora signing key")
    disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disk_artifacts) != 1 or disk_artifacts[0].format != "raw":
        raise WebAPIError("whole-disk image must contain exactly one raw disk-image artifact")
    table_artifacts = [item for item in manifest.artifacts if item.role == "partition-table"]
    if len(table_artifacts) != 1 or table_artifacts[0].format != "raw":
        raise WebAPIError("whole-disk image must contain exactly one raw partition-table artifact")
    table_artifact = table_artifacts[0]
    if table_artifact.encryption != "none" or table_artifact.compression != "none":
        raise WebAPIError("partition-table metadata must be stored unencrypted and uncompressed")
    from feclora.storage.disk_restore import DiskRestoreError, _open_artifact, _verify_stored_artifact
    from feclora.storage.partition_range import PartitionRangeError, parse_sfdisk_dump, partition_ranges
    try:
        with _open_artifact(str(_repository()), table_artifact) as stream:
            _verify_stored_artifact(stream, table_artifact)
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise WebAPIError("partition-table metadata exceeds 1 MiB")
        table = parse_sfdisk_dump(
            raw.decode("utf-8"), image_size_bytes=manifest.source_size_bytes,
            default_sector_size=manifest.logical_sector_size,
        )
        ranges = partition_ranges(
            table, image_size_bytes=manifest.source_size_bytes,
            sector_size=manifest.logical_sector_size,
        )
    except (DiskRestoreError, OSError, UnicodeError, PartitionRangeError) as exc:
        raise WebAPIError(f"partition-table verification or parsing failed: {exc}") from exc
    raw_parts = table["partitiontable"]["partitions"]
    partitions = []
    for item, part in zip(ranges, raw_parts):
        # Device nodes are unique in the parsed table; UUIDs/labels can be duplicated or ambiguous.
        selector = item.node
        partitions.append({
            "selector": selector, "node": item.node,
            "uuid": part.get("uuid"), "name": part.get("name"),
            "start_sector": item.start_sector, "sector_count": item.sector_count,
            "offset_bytes": item.offset_bytes, "size_bytes": item.length_bytes,
        })
    return {
        "image_id": image_id, "source_size_bytes": manifest.source_size_bytes,
        "logical_sector_size": manifest.logical_sector_size, "signed": signed,
        "partitions": partitions,
        "message": "Manifest and partition-table metadata verified. The full disk data artifact is verified again during extraction.",
    }


def _verify_image(params: dict[str, Any]) -> dict[str, Any]:
    """Read-only, end-to-end verification of every stored image artifact."""
    if set(params) not in ({"image_id"}, {"image_id", "repository_id"}):
        raise WebAPIError("verify_image requires image_id and optional repository_id")
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    repository = _operation_repository(params, write=False)
    manifest_path = _image_manifest(image_id, repository)
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WebAPIError(f"cannot read selected image manifest: {exc}") from exc
    if manifest.image_id != image_id:
        raise WebAPIError("selected image manifest identifier does not match its repository name")

    from feclora.storage.image_security import verify_manifest_signature
    signed = os.path.isfile(str(manifest_path) + ".minisig")
    trusted_keys: list[Path] = []
    security = _security_material()
    pki = Path("/etc/feclora/pki")
    if security["image_verification_available"]:
        trusted_keys.append(pki / "server.pub")
    client_config = _client_runtime_config()
    if client_config and client_config.trusted_server_public_key:
        trusted_keys.insert(0, Path(client_config.trusted_server_public_key))
    signature_status = "unsigned"
    if signed:
        verified_key = None
        for candidate in dict.fromkeys(trusted_keys):
            try:
                verify_manifest_signature(manifest_path, candidate)
                verified_key = candidate
                break
            except Exception:
                continue
        if verified_key is None:
            raise WebAPIError("manifest signature is present but does not verify against any locally trusted signing key")
        signature_status = "verified"

    encrypted = any(item.encryption == "age" for item in manifest.artifacts)
    identities: list[Path] = []
    if security["age_decryption_available"]:
        identities.append(pki / "server.age")
    if client_config and client_config.age_identity_file:
        identities.append(Path(client_config.age_identity_file))
    if encrypted and not identities:
        raise WebAPIError("image contains age-encrypted artifacts but no local age identity is available")

    from feclora.storage.disk_restore import (
        DiskRestoreError, _decoded_stream, _verified_artifact_stream,
    )
    artifact_reports = []
    total_decoded = 0
    for artifact in manifest.artifacts:
        identity_context = tempfile.TemporaryDirectory(prefix="feclora-verify-identities-") if (
            artifact.encryption == "age" and len(identities) > 1
        ) else None
        try:
            if identity_context:
                identity_file = Path(identity_context.name) / "identities.txt"
                identity_file.write_text(
                    "\n".join(item.read_text(encoding="ascii").strip() for item in identities) + "\n",
                    encoding="ascii",
                )
                os.chmod(identity_file, 0o600)
            else:
                identity_file = identities[0] if artifact.encryption == "age" else None
            decoded_bytes = 0
            with _verified_artifact_stream(
                str(_repository()), artifact, identity_file, "/usr/bin/age",
            ) as verified_stream:
                decoded_stream = _decoded_stream(verified_stream, artifact.compression)
                try:
                    while True:
                        chunk = decoded_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        decoded_bytes += len(chunk)
                    if hasattr(decoded_stream, "finish"):
                        decoded_stream.finish()
                finally:
                    if decoded_stream is not verified_stream:
                        decoded_stream.close()
            if artifact.role == "disk-image" and decoded_bytes != manifest.source_size_bytes:
                raise WebAPIError(
                    f"decoded disk artifact size mismatch: expected {manifest.source_size_bytes}, got {decoded_bytes}"
                )
            total_decoded += decoded_bytes
            artifact_reports.append({
                "filename": artifact.filename, "role": artifact.role,
                "stored_bytes": artifact.size_bytes, "decoded_bytes": decoded_bytes,
                "sha256": artifact.sha256, "stored_digest": "verified",
                "age_authentication": "verified" if artifact.encryption == "age" else "not encrypted",
                "decompression": "verified" if artifact.compression != "none" else "not compressed",
                "format": artifact.format,
            })
        except Exception as exc:
            raise WebAPIError(f"artifact verification failed for {artifact.filename}: {exc}") from exc
        finally:
            if identity_context:
                identity_context.cleanup()
    return {
        "image_id": image_id, "image_type": manifest.image_type,
        "manifest": "valid", "signature": signature_status,
        "artifact_count": len(artifact_reports), "total_decoded_bytes": total_decoded,
        "artifacts": artifact_reports,
        "verified": True,
        "message": "All stored artifact digests, age authentication and compression streams were verified. This is a read-only check; unsigned images remain unsigned.",
    }


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
    from feclora.storage.operation_log import reconcile_interrupted
    return reconcile_interrupted(records)


def _certificate_status() -> list[dict[str, Any]]:
    from feclora.deployment.managed_pki import certificate_expiry_days
    from feclora.deployment.runtime_config import (
        load_client_runtime_config, load_server_runtime_config,
    )
    results = []
    for role, path, loader in (
        ("Server", "/etc/feclora/deployment-server.json", load_server_runtime_config),
        ("Client", "/etc/feclora/deployment-client.json", load_client_runtime_config),
    ):
        if not os.path.isfile(path):
            continue
        try:
            config = loader(path)
            days = certificate_expiry_days(config.certificate_file)
            ca_days = certificate_expiry_days(config.ca_file)
            identity = config.local_identity
            results.append({
                "role": role, "identity": identity, "expiry_days": days,
                "status": "expired" if days < 0 else "expiring" if days <= 30 else "valid",
                "ca_expiry_days": ca_days,
                "ca_status": "expired" if ca_days < 0 else "expiring" if ca_days <= 30 else "valid",
            })
        except Exception as exc:
            results.append({
                "role": role, "identity": None, "expiry_days": None,
                "status": "error", "detail": str(exc)[:256],
            })
    return results


def _service_state() -> dict[str, str]:
    services = {}
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "cockpit.socket"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=3,
        )
        services["cockpit.socket"] = result.stdout.strip() or "inactive"
    except (OSError, subprocess.SubprocessError):
        services["cockpit.socket"] = "unknown"
    for label, pattern in (
        ("PXE dnsmasq", "feclora-dnsmasq-*.service"),
        ("PXE Caddy", "feclora-caddy-*.service"),
    ):
        try:
            result = subprocess.run(
                ["/usr/bin/systemctl", "list-units", "--type=service", "--state=running",
                 "--no-legend", pattern],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=3,
            )
            services[label] = "active" if result.returncode == 0 and result.stdout.strip() else "inactive"
        except (OSError, subprocess.SubprocessError):
            services[label] = "unknown"
    return services


def _network_interfaces() -> list[dict[str, Any]]:
    from feclora.network.interface_discovery import (
        detect_existing_dhcp_server, parse_interface_addresses,
    )

    executable = shutil.which("ip")
    if not executable:
        raise WebAPIError("iproute is required for network interface discovery")
    try:
        result = subprocess.run(
            [executable, "-j", "-4", "address", "show"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=True, timeout=10,
        )
        rows = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise WebAPIError(f"cannot inspect network interfaces: {exc}") from exc
    if not isinstance(rows, list):
        raise WebAPIError("ip returned an invalid interface inventory")
    interfaces = []
    dhcp_cache: dict[str, str | None] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("ifname")
        if not isinstance(name, str):
            continue
        try:
            addresses = parse_interface_addresses(json.dumps([row]), name)
        except Exception:
            continue
        if name not in dhcp_cache:
            dhcp_cache[name] = detect_existing_dhcp_server(name)
        for address in addresses:
            interfaces.append({
                "interface": address.interface,
                "address": address.address,
                "prefix_length": address.prefix_length,
                "dhcp_server": dhcp_cache[name],
                "binding": f"{address.interface}|{address.address}|{address.prefix_length}",
            })
    return interfaces


def _bootstrap_server(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"interface", "address", "prefix_length"}:
        raise WebAPIError("bootstrap_server requires interface, address and prefix_length")
    interface = _text(params, "interface", pattern=r"[A-Za-z0-9_.:-]{1,15}", maximum=15)
    address = _text(params, "address", maximum=45)
    prefix = params["prefix_length"]
    if isinstance(prefix, bool) or not isinstance(prefix, int) or not 1 <= prefix <= 30:
        raise WebAPIError("prefix_length must be an integer between 1 and 30")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise WebAPIError("Server address must be a valid IPv4 address") from exc
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback:
        raise WebAPIError("Server address must be a concrete unicast IPv4 address")

    from feclora.network.interface_discovery import (
        discover_interface_addresses, validate_selected_address,
    )
    from feclora.deployment.bootstrap import ensure_server_deployment_config
    from feclora.deployment.runtime_config import load_server_runtime_config

    try:
        discovered = discover_interface_addresses(interface)
        validate_selected_address(interface, str(parsed), prefix, discovered)
        created = ensure_server_deployment_config(str(parsed))
        config = load_server_runtime_config("/etc/feclora/deployment-server.json")
    except Exception as exc:
        raise WebAPIError(f"Server identity initialization failed: {exc}") from exc
    return {
        "created": created,
        "configured": True,
        "bind_address": config.bind_address,
        "port": config.port,
        "server_identity": config.local_identity,
        "enrolled_clients": len(config.client_identity_to_mac),
        "message": (
            "Server identity and managed trust material initialized."
            if created else
            "An existing Server configuration was validated and left unchanged."
        ),
    }


def _validate_pxe_profile(params: dict[str, Any]) -> dict[str, Any]:
    required = {
        "interface", "address", "prefix_length", "mode", "pool_start",
        "pool_end", "lease_time", "gateway", "dns_server", "http_port",
        "authoritative_confirmed",
    }
    if set(params) != required:
        raise WebAPIError("validate_pxe_profile requires the complete PXE profile field set")
    interface = _text(params, "interface", pattern=r"[A-Za-z0-9_.:-]{1,15}", maximum=15)
    address = _text(params, "address", maximum=45)
    mode = _text(params, "mode", pattern=r"(?:proxy|isolated)", maximum=16)
    prefix = params["prefix_length"]
    port = params["http_port"]
    authoritative = params["authoritative_confirmed"]
    if isinstance(prefix, bool) or not isinstance(prefix, int) or not 1 <= prefix <= 30:
        raise WebAPIError("prefix_length must be an integer between 1 and 30")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise WebAPIError("http_port must be an integer between 1 and 65535")
    if not isinstance(authoritative, bool):
        raise WebAPIError("authoritative_confirmed must be boolean")
    optional = {}
    for key in ("pool_start", "pool_end", "gateway", "dns_server"):
        value = params[key]
        if value is not None and (not isinstance(value, str) or not value or len(value) > 45):
            raise WebAPIError(f"{key} must be an IPv4 address or null")
        optional[key] = value
    lease = _text(params, "lease_time", pattern=r"[1-9][0-9]*(?:s|m|h|d|w)", maximum=16)

    from feclora.network.pxe_config import PXENetworkConfig
    from feclora.network.pxe_preflight import validate_pxe_configuration
    from feclora.network.interface_discovery import detect_existing_dhcp_server

    config = PXENetworkConfig(
        interface=interface, address=address, prefix_length=prefix, mode=mode,
        tftp_root="/srv/feclora/tftp",
        bios_boot_file="undionly.kpxe",
        uefi_boot_file="ipxe-snponly-x86_64.efi",
        http_root="/srv/feclora/http",
        http_port=port, pool_start=optional["pool_start"],
        pool_end=optional["pool_end"], lease_time=lease,
        gateway=optional["gateway"], dns_server=optional["dns_server"],
        authoritative_confirmed=authoritative,
    )
    try:
        config.validated()
        validate_pxe_configuration(config)
        dhcp_server = detect_existing_dhcp_server(interface)
    except Exception as exc:
        raise WebAPIError(f"PXE preflight failed: {exc}") from exc
    warnings = []
    if dhcp_server:
        warnings.append(
            f"NetworkManager reports DHCP server {dhcp_server} on this interface. "
            "Use ProxyDHCP unless the network is a deliberately isolated Feclora DHCP segment."
        )
        if mode == "isolated":
            raise WebAPIError(
                "An existing DHCP server is reported on this interface; isolated authoritative DHCP is blocked. "
                "Use ProxyDHCP or move Feclora to a verified isolated network."
            )
    elif mode == "isolated":
        warnings.append(
            "No DHCP server was reported by the current NetworkManager lease. "
            "This does not prove the segment is isolated; verify the VLAN and DHCP topology before activation."
        )
    return {
        "valid": True,
        "interface": interface,
        "address": address,
        "prefix_length": prefix,
        "subnet": str(config.network),
        "mode": mode,
        "pool_start": config.pool_start,
        "pool_end": config.pool_end,
        "http_url": f"http://{address}:{port}/boot.ipxe",
        "dhcp_server": dhcp_server,
        "warnings": warnings,
        "services_started": False,
        "message": "PXE configuration passed static and daemon preflight. No network services or firewall rules were changed.",
    }



def _pxe_service_manager() -> Any:
    from feclora.network.pxe_service import PXEServiceManager
    return PXEServiceManager()


def _active_deployment_service_status() -> dict[str, Any] | None:
    from feclora.deployment.local_control import LocalControlError, local_control_request
    try:
        return local_control_request("/run/feclora/deployment.sock", "status")
    except (FileNotFoundError, ConnectionRefusedError):
        return None
    except (OSError, LocalControlError) as exc:
        raise WebAPIError(f"cannot verify active deployment service ownership: {exc}") from exc


def _start_pxe_services(params: dict[str, Any]) -> dict[str, Any]:
    _validate_pxe_profile(params)
    from feclora.network.pxe_config import PXENetworkConfig
    config = PXENetworkConfig(
        interface=params["interface"], address=params["address"],
        prefix_length=params["prefix_length"], mode=params["mode"],
        tftp_root="/srv/feclora/tftp", bios_boot_file="undionly.kpxe",
        uefi_boot_file="ipxe-snponly-x86_64.efi", http_root="/srv/feclora/http",
        http_port=params["http_port"], pool_start=params["pool_start"],
        pool_end=params["pool_end"], lease_time=params["lease_time"],
        gateway=params["gateway"], dns_server=params["dns_server"],
        authoritative_confirmed=params["authoritative_confirmed"],
    )
    active_service = _active_deployment_service_status()
    if active_service and active_service.get("network_interface") == config.interface:
        raise WebAPIError("stop the active deployment service before activating PXE on the same interface")
    try:
        manager = _pxe_service_manager()
        manager.start(config)
        status = manager.status()
    except Exception as exc:
        raise WebAPIError(f"PXE service activation failed: {exc}") from exc
    return {
        "active": status["active"], "interface": status["interface"],
        "services": status["services"],
        "message": "PXE services started with a temporary interface-scoped firewall zone. They are not enabled at boot.",
    }


def _stop_pxe_services() -> dict[str, Any]:
    manager = _pxe_service_manager()
    try:
        current = manager.status()
        active_service = _active_deployment_service_status()
        if (current.get("active") and active_service
                and current.get("interface") == active_service.get("network_interface")):
            raise WebAPIError("stop the deployment service before stopping PXE on the same interface")
        manager.stop()
        status = manager.status()
    except Exception as exc:
        raise WebAPIError(f"PXE service shutdown failed: {exc}") from exc
    return {
        "active": status["active"], "interface": status["interface"],
        "services": status["services"],
        "message": "PXE services stopped and the interface's previous firewalld zone restored."
        if not status["configured"] else
        "PXE shutdown is incomplete; inspect service and firewall state before continuing.",
    }





def _prepare_client_request(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import prepare_client_request
    try:
        return prepare_client_request(params)
    except Exception as exc:
        raise WebAPIError(f"Client enrollment request preparation failed: {exc}") from exc


def _complete_client_enrollment(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import complete_client_enrollment
    try:
        return complete_client_enrollment(params)
    except Exception as exc:
        raise WebAPIError(f"Client enrollment completion failed: {exc}") from exc


def _prepare_client_renewal(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import prepare_client_renewal
    try:
        return prepare_client_renewal(params)
    except Exception as exc:
        raise WebAPIError(f"Client renewal request preparation failed: {exc}") from exc


def _complete_client_renewal(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import complete_client_renewal
    try:
        return complete_client_renewal(params)
    except Exception as exc:
        raise WebAPIError(f"Client renewal installation failed: {exc}") from exc


def _inspect_client_csr(params: dict[str, Any]) -> dict[str, str]:
    from feclora.deployment.cockpit_enrollment import inspect_client_request
    try:
        return inspect_client_request(params)
    except Exception as exc:
        raise WebAPIError(f"Client CSR inspection failed: {exc}") from exc


def _approve_client_csr(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_enrollment import approve_client_csr
    try:
        return approve_client_csr(params)
    except Exception as exc:
        raise WebAPIError(f"Client CSR approval failed: {exc}") from exc


def _execute_operation(action: str, params: dict[str, Any], operation_id: str) -> dict[str, Any]:
    allowed = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "sign", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "sign", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in allowed or (set(params) != allowed[action] and set(params) != allowed[action] - {"repository_id"}):
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
        recipients_file, signing_key = _capture_material()
        manifest = capture_disk(
            source, image_id, _operation_repository(params, write=True, create_local=True), compression=compression,
            progress_callback=_progress,
            age_recipients_file=recipients_file if encrypt else None,
            minisign_secret_key=signing_key if sign else None,
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
        recipients_file, signing_key = _capture_material()
        manifest = capture_partition_image(
            source, image_id, partition_id, _operation_repository(params, write=True, create_local=True),
            compression=compression, progress_callback=_progress,
            age_recipients_file=recipients_file if encrypt else None,
            minisign_secret_key=signing_key if sign else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "extract_partition_image":
        from feclora.storage.disk_image_partition import extract_partition_image
        from feclora.storage.image_security import verify_manifest_signature
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        selector = _text(params, "selector", maximum=256)
        repository = _operation_repository(params, write=True)
        manifest_path = _image_manifest(image_id, repository)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.image_id != image_id:
            raise WebAPIError("selected image manifest identifier does not match its repository name")
        if manifest.image_type != "disk":
            raise WebAPIError("partition extraction requires a whole-disk image")
        signed = os.path.isfile(str(manifest_path) + ".minisig")
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        security = _security_material()
        pki = Path("/etc/feclora/pki")
        identity_paths: list[Path] = []
        trusted_keys: list[Path] = []
        if security["age_decryption_available"]:
            identity_paths.append(pki / "server.age")
        if security["image_verification_available"]:
            trusted_keys.append(pki / "server.pub")
        client_config = _client_runtime_config()
        if client_config:
            if client_config.age_identity_file:
                identity_paths.append(Path(client_config.age_identity_file))
            if client_config.trusted_server_public_key:
                trusted_keys.insert(0, Path(client_config.trusted_server_public_key))
        if encrypted and not identity_paths:
            raise WebAPIError("age-encrypted disk image requires an enrolled Client or local Feclora age identity")
        trusted_key = None
        if signed:
            for candidate in dict.fromkeys(trusted_keys):
                try:
                    verify_manifest_signature(manifest_path, candidate)
                    trusted_key = candidate
                    break
                except Exception:
                    continue
            if trusted_key is None:
                raise WebAPIError("signed disk image does not verify against any locally trusted Feclora signing key")
        recipients_file, signing_key = _capture_material()
        if encrypted and not security["age_encryption_available"]:
            raise WebAPIError("extracting an age-encrypted disk image requires an available age recipient inventory for the new partition image")
        if not security["image_signing_available"]:
            signing_key = None
        if signed and signing_key is None:
            raise WebAPIError("extracting a signed disk image requires a local signing key to sign the resulting partition image")
        identity_context = tempfile.TemporaryDirectory(prefix="feclora-age-identities-") if encrypted and len(identity_paths) > 1 else None
        try:
            if identity_context:
                identity_file = Path(identity_context.name) / "identities.txt"
                identity_file.write_text(
                    "\n".join(path.read_text(encoding="ascii").strip() for path in identity_paths) + "\n",
                    encoding="ascii",
                )
                os.chmod(identity_file, 0o600)
            else:
                identity_file = identity_paths[0] if encrypted else None
            extracted, extracted_manifest = extract_partition_image(
                manifest_path, repository, selector,
                age_identity_file=identity_file,
                minisign_public_key=trusted_key,
                require_signature=signed,
                minisign_secret_key=signing_key,
                age_recipients_file=recipients_file if encrypted else None,
                progress_callback=_progress,
            )
        except Exception as exc:
            raise WebAPIError(f"partition extraction failed: {exc}") from exc
        finally:
            if identity_context:
                identity_context.cleanup()
        result = {
            "source_image_id": image_id, "image_id": extracted.image_id,
            "image_type": extracted.image_type, "manifest": extracted_manifest,
            "signed": signing_key is not None,
            "encrypted": any(item.encryption == "age" for item in extracted.artifacts),
        }
    elif action in {"restore_disk", "restore_partition"}:
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        target = _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        repository = _operation_repository(params, write=False)
        manifest_path = _image_manifest(image_id, repository)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        expected_type = "disk" if action == "restore_disk" else "partition"
        if manifest.image_type != expected_type:
            raise WebAPIError(f"selected image is not a {expected_type} image")
        from feclora.storage.image_security import verify_manifest_signature
        security = _security_material()
        signed = os.path.isfile(str(manifest_path) + ".minisig")
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        pki = Path("/etc/feclora/pki")
        identity_paths: list[Path] = []
        if security["age_decryption_available"]:
            identity_paths.append(pki / "server.age")
        trusted_keys: list[Path] = []
        if security["image_verification_available"]:
            trusted_keys.append(pki / "server.pub")
        client_config = _client_runtime_config()
        if client_config:
            if client_config.age_identity_file:
                identity_paths.append(Path(client_config.age_identity_file))
            trusted_keys.insert(0, Path(client_config.trusted_server_public_key))
        if encrypted and not identity_paths:
            raise WebAPIError("age-encrypted image requires an enrolled Client or local Feclora age identity")
        trusted_key = None
        if signed:
            for candidate in dict.fromkeys(trusted_keys):
                try:
                    verify_manifest_signature(manifest_path, candidate)
                    trusted_key = candidate
                    break
                except Exception:
                    continue
            if trusted_key is None:
                raise WebAPIError("signed image does not verify against any locally trusted Feclora signing key")
        identity_context = tempfile.TemporaryDirectory(prefix="feclora-age-identities-") if encrypted and len(identity_paths) > 1 else None
        try:
            if identity_context:
                identity_file = Path(identity_context.name) / "identities.txt"
                contents = []
                for identity_path in identity_paths:
                    contents.append(identity_path.read_text(encoding="ascii").strip())
                identity_file.write_text("\n".join(contents) + "\n", encoding="ascii")
                os.chmod(identity_file, 0o600)
            else:
                identity_file = identity_paths[0] if encrypted else None
            if action == "restore_disk":
                from feclora.storage.disk_restore import restore_disk
                restore_disk(
                    manifest_path, repository, target, confirmation=expected,
                    progress_callback=_progress, age_identity_file=identity_file,
                    minisign_public_key=trusted_key, require_signature=signed,
                )
            else:
                from feclora.storage.partition_restore import restore_partition
                restore_partition(
                    manifest_path, repository, target, confirmation=expected,
                    progress_callback=_progress, age_identity_file=identity_file,
                    minisign_public_key=trusted_key, require_signature=signed,
                )
        finally:
            if identity_context:
                identity_context.cleanup()
        result = {"image_id": image_id, "target": target, "verified": True}
    elif action == "clone_disk":
        from feclora.storage.disk_clone import clone_disk
        source, target = _device(params["source"], "source"), _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        copied = clone_disk(
            source, target, confirmation=expected,
            progress_callback=_clone_disk_progress,
        )
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


@contextmanager
def _storage_operation_lock():
    runtime_directory = Path("/run/feclora")
    try:
        runtime_directory.mkdir(mode=0o755, parents=True, exist_ok=True)
        directory_info = os.lstat(runtime_directory)
        if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                or directory_info.st_uid != 0 or directory_info.st_mode & 0o022):
            raise WebAPIError("deployment runtime directory is unsafe")
        fd = os.open(
            runtime_directory / "deployment.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            os.close(fd)
            raise WebAPIError("deployment operation lock file is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise WebAPIError("another Server, Client or local storage operation is active on this host") from exc
        try:
            from feclora.deployment.service import recover_stale_runtime_artifacts
            recover_stale_runtime_artifacts(lock_held=True)
        except Exception:
            os.close(fd)
            raise
    except WebAPIError:
        raise
    except OSError as exc:
        raise WebAPIError(f"cannot acquire host-wide storage operation lock: {exc}") from exc
    try:
        yield
    finally:
        os.close(fd)


def _local_operation_store():
    from feclora.storage.local_operations import LocalOperationStore
    return LocalOperationStore("/var/lib/feclora/local-operations")


def _submit_local_operation(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation", "operation_params"}:
        raise WebAPIError("submit_local_operation requires operation and operation_params")
    operation, operation_params = params["operation"], params["operation_params"]
    if not isinstance(operation, str) or not isinstance(operation_params, dict):
        raise WebAPIError("operation must be a string and operation_params must be an object")
    try:
        store = _local_operation_store()
        operation_id = store.submit(operation, operation_params)
    except Exception as exc:
        raise WebAPIError(f"cannot persist local operation: {exc}") from exc
    unit = f"feclora-local-operation@{operation_id}.service"
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", "--no-block", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            store.append(operation_id, "failed", {"error": f"cannot start worker: {str(exc)[:256]}"})
        except Exception:
            pass
        raise WebAPIError(f"local operation was persisted but its worker could not be started: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "systemd rejected the operation").strip()[:384]
        try:
            store.append(operation_id, "failed", {"error": message})
        except Exception:
            pass
        raise WebAPIError(f"local operation was persisted but its worker could not be started: {message}")
    return {"operation_id": operation_id, "state": "queued", "unit": unit}


def _local_operation_status(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id"} or not isinstance(params["operation_id"], str):
        raise WebAPIError("local_operation_status requires one operation_id")
    try:
        return _local_operation_store().status(params["operation_id"])
    except Exception as exc:
        raise WebAPIError(f"cannot read local operation status: {exc}") from exc


def _local_operations(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) - {"limit"}:
        raise WebAPIError("local_operations accepts only an optional limit")
    limit = params.get("limit", 100)
    try:
        return {"operations": _local_operation_store().list(limit=limit)}
    except Exception as exc:
        raise WebAPIError(f"cannot read local operation history: {exc}") from exc


def _run_operation(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "sign", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "sign", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in operation_fields or (set(params) != operation_fields[action] and set(params) != operation_fields[action] - {"repository_id"}):
        raise WebAPIError("operation parameters do not match the selected operation")
    with _storage_operation_lock():
        return _run_operation_locked(action, params)


def _run_operation_locked(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "sign", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "sign", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in operation_fields or (
        set(params) != operation_fields[action]
        and set(params) != operation_fields[action] - {"repository_id"}
    ):
        raise WebAPIError("operation parameters do not match the selected operation")
    from feclora.storage.operation_log import operation_record

    target = params.get("target") or params.get("source") or params.get("image_id") or "unspecified"
    image_id = params.get("image_id")
    with operation_record(
        action, str(target), image_id=image_id,
        log_path="/var/lib/feclora/operations.jsonl",
    ) as operation_id:
        return _execute_operation(action, params, operation_id)


def _deployment_journal_directory(*, create: bool = False) -> Path:
    directory = Path("/var/lib/feclora/deployments")
    if create:
        directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    try:
        info = os.lstat(directory)
    except OSError as exc:
        raise WebAPIError("deployment journal directory is unavailable") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise WebAPIError("deployment journal directory must be a private root-owned real directory")
    return directory


def _inspect_remote_job(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"host", "job_id"}:
        raise WebAPIError("remote job inspection requires exactly host and job_id")
    host = params["host"]
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    from feclora.deployment.runtime_config import load_client_runtime_config
    from feclora.deployment.control import DeploymentControlError, inspect_deployment_job
    from feclora.network.remote_clone_protocol import create_mutual_tls_context
    try:
        config = load_client_runtime_config("/etc/feclora/deployment-client.json")
    except Exception as exc:
        raise WebAPIError(f"Client deployment identity is not configured: {exc}") from exc
    if host == "":
        host = config.host
    if (not isinstance(host, str) or not host or len(host) > 253
            or any(ord(char) < 33 for char in host)):
        raise WebAPIError("Server host must be a hostname or address without whitespace")
    try:
        context = create_mutual_tls_context(
            "client", ca_file=config.ca_file,
            certificate_file=config.certificate_file,
            private_key_file=config.private_key_file,
        )
        job = inspect_deployment_job(
            host, config.port, context,
            local_identity=config.local_identity,
            expected_server_identity=config.server_identity,
            mac_address=config.mac_address,
            job_id=job_id,
        )
    except (DeploymentControlError, OSError, ValueError) as exc:
        raise WebAPIError(f"could not inspect authenticated Server job: {exc}") from exc
    if job.operation == "save" and job.target_type != "disk":
        raise WebAPIError("Client-side capture currently supports whole-disk jobs only")
    if job.operation == "save" and not config.local_minisign_secret_key:
        raise WebAPIError("this Client has no enrolled image-signing key and cannot capture images")
    if job.transport == "multicast" and (not config.age_identity_file or not config.age_recipients_file):
        raise WebAPIError("multicast restore requires this Client's enrolled age identity and recipient inventory")
    return {
        "host": host,
        "port": config.port,
        "client_identity": config.local_identity,
        "client_mac": config.mac_address,
        "server_identity": config.server_identity,
        "job": job.to_dict(),
    }


def _client_job_directory() -> Path:
    directory = Path("/var/lib/feclora/client-jobs")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(directory)
    except OSError as exc:
        raise WebAPIError(f"cannot prepare private Client job directory: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise WebAPIError("Client job directory must be a private root-owned real directory")
    return directory


def _client_job_paths(job_id: str) -> tuple[Path, Path]:
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    directory = _client_job_directory()
    return directory / f"{job_id}.request.json", directory / f"{job_id}.status.json"


def _write_client_job_request(path: Path, value: dict[str, Any]) -> None:
    if os.path.lexists(path):
        raise WebAPIError("a Client job request already exists for this UUID")
    fd, temporary = tempfile.mkstemp(prefix=".client-request-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise WebAPIError("a Client job request already exists for this UUID") from exc
        os.unlink(temporary)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_client_job_status(job_id: str) -> dict[str, Any]:
    _request_path, status_path = _client_job_paths(job_id)
    try:
        info = os.lstat(status_path)
    except FileNotFoundError as exc:
        raise WebAPIError("Client job service has not published a status record yet") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 16384):
        raise WebAPIError("Client job status file is unsafe")
    try:
        fd = os.open(status_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0
                    or opened.st_mode & 0o077
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise WebAPIError("Client job status file changed during inspection")
            value = json.loads(os.read(fd, 16385).decode("utf-8"))
        finally:
            os.close(fd)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WebAPIError(f"cannot read Client job status: {exc}") from exc
    if (not isinstance(value, dict) or value.get("job_id") != job_id
            or value.get("schema_version") != 1
            or value.get("phase") not in {"connecting", "ready", "running", "completed", "failed", "cancelled", "interrupted"}
            or not isinstance(value.get("detail", ""), str)):
        raise WebAPIError("Client job status has an invalid schema or does not match the requested UUID")
    return value


def _start_client_job(params: dict[str, Any]) -> dict[str, Any]:
    required = {"host", "job_id", "device_path", "confirmation", "compression"}
    allowed = {
        frozenset(required),
        frozenset(required | {"network_interface"}),
        frozenset(required | {"network_interface", "igmp_confirmed"}),
    }
    if frozenset(params) not in allowed:
        raise WebAPIError("start_client_job requires host, job_id, device_path, confirmation, compression and optional multicast acknowledgements")
    inspection = _inspect_remote_job({"host": params["host"], "job_id": params["job_id"]})
    job = inspection["job"]
    network_interface = params.get("network_interface")
    igmp_confirmed = params.get("igmp_confirmed", False)
    multicast_preflight = None
    if job["transport"] == "multicast":
        if igmp_confirmed is not True:
            raise WebAPIError("explicitly confirm IGMP snooping and an active querier on the deployment VLAN")
        if job["operation"] != "restore":
            raise WebAPIError("multicast Client execution supports restore jobs only")
        if not isinstance(network_interface, str) or network_interface not in {
            name for _index, name in socket.if_nameindex()
        }:
            raise WebAPIError("select a local multicast receive interface")
        from feclora.network.multicast_preflight import inspect_multicast_interface
        try:
            multicast_preflight = inspect_multicast_interface(
                network_interface, job["multicast_group"], role="receiver",
            )
        except Exception as exc:
            raise WebAPIError(f"multicast receive interface preflight failed: {exc}") from exc
    elif network_interface is not None or igmp_confirmed is not False:
        raise WebAPIError("multicast interface and IGMP acknowledgement are only valid for multicast Client jobs")
    device_path = params["device_path"]
    confirmation = params["confirmation"]
    compression = params["compression"]
    if (not isinstance(device_path, str) or not device_path.startswith("/dev/")
            or len(device_path) > 256 or os.path.normpath(device_path) != device_path):
        raise WebAPIError("selected local target path is invalid")
    if not isinstance(confirmation, str) or len(confirmation) > 512:
        raise WebAPIError("local target confirmation is invalid")
    if not isinstance(compression, str) or compression not in {"none", "gzip", "xz"}:
        raise WebAPIError("compression must be none, gzip or xz")
    expected_confirmation = (
        f"ERASE {device_path} FROM {inspection['server_identity']}"
        if job["operation"] == "restore"
        else f"READ {device_path} TO {inspection['server_identity']}"
    )
    if confirmation != expected_confirmation:
        raise WebAPIError("local typed confirmation does not match the selected device and authenticated Server")
    from feclora.storage.inventory import collect_inventory
    inventory = collect_inventory()
    expected_type = "disk" if job["target_type"] == "disk" else "part"
    matches = []

    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            if item.get("path") == device_path and item.get("type") == expected_type:
                matches.append(item)
            children = item.get("children")
            if isinstance(children, list):
                visit(children)

    visit(inventory.get("devices", []))
    if len(matches) != 1:
        raise WebAPIError("selected target is not uniquely present in the current local block-device inventory")
    try:
        device_info = os.lstat(device_path)
    except OSError as exc:
        raise WebAPIError(f"cannot inspect selected local target: {exc}") from exc
    if not stat.S_ISBLK(device_info.st_mode):
        raise WebAPIError("selected local target is no longer a block device")
    if job["operation"] == "save" and job["target_type"] != "disk":
        raise WebAPIError("Client capture currently supports whole-disk jobs only")
    request_path, status_path = _client_job_paths(params["job_id"])
    if os.path.lexists(status_path):
        raise WebAPIError("a status record already exists for this job; interrupted Client jobs are never restarted")
    _write_client_job_request(request_path, {
        "schema_version": 1, "job_id": params["job_id"], "host": inspection["host"],
        "device_path": device_path, "confirmation": confirmation,
        "compression": compression, "network_interface": network_interface,
        "igmp_confirmed": igmp_confirmed,
    })
    unit = "feclora-client@" + params["job_id"] + ".service"
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            request_path.unlink()
        except OSError:
            pass
        raise WebAPIError(f"could not start persistent Client service: {exc}") from exc
    if result.returncode != 0:
        try:
            request_path.unlink()
        except OSError:
            pass
        detail = (result.stderr or result.stdout or "").strip()
        raise WebAPIError(f"Client service did not start: {detail or result.returncode}")
    deadline = time.monotonic() + 10
    last_error = None
    while time.monotonic() < deadline:
        try:
            status = _client_job_status({"job_id": params["job_id"]})
            if multicast_preflight is not None:
                status["multicast_preflight"] = {
                    "interface": multicast_preflight.interface,
                    "ipv4_address": multicast_preflight.ipv4_address,
                    "warnings": list(multicast_preflight.warnings),
                }
            return status
        except WebAPIError as exc:
            last_error = exc
            time.sleep(0.1)
    try:
        active_check = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
        if active_check.returncode != 0 and request_path.exists():
            request_path.unlink()
    except (OSError, subprocess.SubprocessError):
        pass
    raise WebAPIError(f"Client service started but did not publish status: {last_error}")


def _client_job_status(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id"}:
        raise WebAPIError("client_job_status requires exactly job_id")
    job_id = params["job_id"]
    _request_path, _status_path = _client_job_paths(job_id)
    status = _read_client_job_status(job_id)
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", "feclora-client@" + job_id + ".service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
        active = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        active = False
    status["unit_active"] = active
    status["interrupted"] = not active and status.get("phase") not in {"completed", "failed", "cancelled", "interrupted"}
    return status


def _deployment_service_job_id(params: dict[str, Any]) -> str:
    if set(params) != {"job_id"}:
        raise WebAPIError("deployment service action requires exactly job_id")
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    return job_id


def _deployment_service_unit(job_id: str) -> str:
    return "feclora-deployment@" + job_id + ".service"


def _deployment_service_status(job_id: str) -> dict[str, Any]:
    from feclora.deployment.local_control import LocalControlError, local_control_request
    try:
        status = local_control_request("/run/feclora/deployment.sock", "status")
    except (OSError, LocalControlError) as exc:
        raise WebAPIError(f"deployment service IPC is unavailable: {exc}") from exc
    if status.get("job_id") != job_id:
        raise WebAPIError("the active deployment service belongs to a different job")
    return status


def _start_deployment_service(params: dict[str, Any]) -> dict[str, Any]:
    job_id = _deployment_service_job_id(params)
    active_service = _active_deployment_service_status()
    if active_service is not None:
        if active_service.get("job_id") != job_id:
            raise WebAPIError("another deployment job already owns the Server control service")
        return active_service
    from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
    journal_path = _deployment_journal_directory() / f"{job_id}.jsonl"
    try:
        report = DeploymentJournal.inspect(journal_path).recovery_report()
    except (OSError, DeploymentJournalError) as exc:
        raise WebAPIError(f"cannot inspect the requested deployment job journal: {exc}") from exc
    if report.get("job_id") != job_id:
        raise WebAPIError("deployment journal UUID does not match the requested job")
    if report.get("job_state") != "created" or report.get("interrupted"):
        raise WebAPIError("only a fresh, unstarted deployment job can be started from Cockpit")
    unit = _deployment_service_unit(job_id)
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WebAPIError(f"could not start persistent deployment service: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise WebAPIError(f"deployment service did not start: {detail or result.returncode}")
    deadline = time.monotonic() + 10
    last_error = None
    while time.monotonic() < deadline:
        try:
            return _deployment_service_status(job_id)
        except WebAPIError as exc:
            last_error = exc
            time.sleep(0.1)
    raise WebAPIError(f"deployment service started but its local control socket did not become ready: {last_error}")


def _stop_deployment_service(params: dict[str, Any]) -> dict[str, Any]:
    job_id = _deployment_service_job_id(params)
    status = _deployment_service_status(job_id)
    clients = status.get("clients", [])
    if status.get("worker_active") or status.get("job_state") == "running" or any(
        isinstance(client, dict) and client.get("state") == "running" for client in clients
    ):
        raise WebAPIError("cannot stop the service while a deployment worker may be performing storage I/O")
    if status.get("job_state") == "created" and clients:
        raise WebAPIError("cancel the unarmed job before stopping its service while Clients are connected")
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "stop", _deployment_service_unit(job_id)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WebAPIError(f"could not stop persistent deployment service: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise WebAPIError(f"deployment service did not stop cleanly: {detail or result.returncode}")
    return {"job_id": job_id, "stopped": True,
            "message": "Deployment control service stopped. No interrupted job was resumed."}


def _deployment_service_command(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id", "confirmation"}:
        raise WebAPIError(f"{action} requires exactly job_id and confirmation")
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    confirmation = params["confirmation"]
    if not isinstance(confirmation, str) or len(confirmation) > 512:
        raise WebAPIError("operator confirmation is invalid")
    from feclora.deployment.local_control import LocalControlError, local_control_request
    try:
        return local_control_request(
            "/run/feclora/deployment.sock", "arm" if action == "arm_deployment_job" else "cancel",
            {"job_id": job_id, "confirmation": confirmation},
        )
    except (OSError, LocalControlError) as exc:
        raise WebAPIError(f"deployment service rejected the command: {exc}") from exc


def _deployment_jobs() -> list[dict[str, Any]]:
    from feclora.deployment.journal import DeploymentJournal
    if not os.path.lexists("/var/lib/feclora/deployments"):
        return []
    active_service = None
    try:
        from feclora.deployment.local_control import LocalControlError, local_control_request
        active_service = local_control_request("/run/feclora/deployment.sock", "status")
    except (OSError, LocalControlError):
        active_service = None
    directory = _deployment_journal_directory()
    jobs = []
    for path in sorted(directory.glob("*.jsonl")):
        report = DeploymentJournal.inspect(path).recovery_report()
        job = report["job"]
        service_active = bool(active_service and active_service.get("job_id") == report["job_id"])
        jobs.append({
            "job_id": report["job_id"],
            "operation": job["operation"],
            "image_id": job["image_id"],
            "source_device": job.get("source_device"),
            "target_type": job.get("target_type", "disk"),
            "transport": job["transport"],
            "job_state": report["job_state"],
            "interrupted": report["interrupted"] and not service_active,
            "service_active": service_active,
            "clients": report["clients"],
            "progress": report["progress"],
            "authorized_clients": job["authorized_clients"],
            "event_count": report["event_count"],
            "last_event": report["last_event"],
        })
    return jobs



def _reconcile_deployment_job(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id", "confirmation"}:
        raise WebAPIError("reconcile_deployment_job requires exactly job_id and confirmation")
    job_id = params["job_id"]
    confirmation = params["confirmation"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    if not isinstance(confirmation, str) or len(confirmation) > 96:
        raise WebAPIError("operator reconciliation confirmation is invalid")
    from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
    try:
        from feclora.deployment.local_control import LocalControlError, local_control_request
        active_service = local_control_request("/run/feclora/deployment.sock", "status")
    except (OSError, LocalControlError):
        active_service = None
    if active_service and active_service.get("job_id") == job_id:
        raise WebAPIError("stop the active deployment service before reconciling its journal")

    directory = _deployment_journal_directory()
    journal_path = directory / f"{job_id}.jsonl"
    if not os.path.lexists(journal_path):
        raise WebAPIError("deployment job journal does not exist")
    try:
        journal = DeploymentJournal.inspect(journal_path)
        if journal.job_id != job_id:
            raise WebAPIError("deployment journal UUID does not match the requested job")
        report = journal.reconcile_after_operator_inspection(confirmation)
    except DeploymentJournalError as exc:
        raise WebAPIError(str(exc)) from exc
    return {
        "job_id": job_id,
        "job_state": report["job_state"],
        "interrupted": report["interrupted"],
        "operator_reconciled": report["operator_reconciled"],
        "message": "Interrupted job closed for audit. No operation was resumed or performed on storage.",
    }


def _create_deployment_job(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job"} or not isinstance(params["job"], dict):
        raise WebAPIError("create_deployment_job requires exactly one job object")
    from feclora.deployment.job import DeploymentJob, JobValidationError
    from feclora.deployment.journal import DeploymentJournal
    from feclora.deployment.runtime_config import load_server_runtime_config, RuntimeConfigError

    try:
        job = DeploymentJob.from_dict(params["job"])
    except JobValidationError as exc:
        raise WebAPIError(str(exc)) from exc
    if job.operation == "save" and job.target_type != "disk":
        raise WebAPIError("Client-side capture currently supports whole-disk jobs only")
    if job.transport == "unicast" and len(job.authorized_clients) != 1:
        raise WebAPIError("persistent unicast deployment supports exactly one Client per job")
    if job.transport == "multicast" and len(job.authorized_clients) < 2:
        raise WebAPIError("multicast restore requires at least two authorized Clients")
    config_path = "/etc/feclora/deployment-server.json"
    try:
        config = load_server_runtime_config(config_path)
    except RuntimeConfigError as exc:
        raise WebAPIError(f"configure the Feclora Server before creating jobs: {exc}") from exc
    if not set(job.authorized_clients).issubset(set(config.client_identity_to_mac.values())):
        raise WebAPIError("every job Client must already be enrolled on this Server")
    if job.network_interface not in {name for _, name in socket.if_nameindex()}:
        raise WebAPIError("selected network interface does not exist")
    if job.transport == "multicast" and job.operation != "restore":
        raise WebAPIError("network capture currently supports unicast only")
    if job.operation == "save":
        if job.image_id in {item["image_id"] for item in _images()}:
            raise WebAPIError("capture image identifier already exists")
        missing_keys = set(job.authorized_clients) - set(config.client_minisign_public_keys)
        if missing_keys:
            raise WebAPIError("every Client in a capture job must have an enrolled minisign public key")
    elif job.operation == "clone":
        source = _device(job.source_device, "source_device")
        inventory = collect_inventory()
        matches = [
            item for item in inventory.get("devices", [])
            if item.get("path") == source and item.get("type") == "disk"
        ]
        if len(matches) != 1:
            raise WebAPIError("clone source must be one whole disk in the current block-device inventory")
        if matches[0].get("read_only") is not True:
            raise WebAPIError("clone source disk must already be marked read-only")
        from feclora.storage.source_safety import check_capture_source_safe, SourceSafetyError
        try:
            check_capture_source_safe(source)
        except (SourceSafetyError, OSError) as exc:
            raise WebAPIError(f"clone source disk is unsafe or in use: {exc}") from exc
    else:
        image_repository = (
            _operation_repository({"repository_id": job.repository_id}, write=False)
            if job.repository_id else Path(config.repository)
        )
        manifest_path = _image_manifest(job.image_id, image_repository)
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
            expected_type = "disk" if job.target_type == "disk" else "partition"
            if manifest.image_type != expected_type:
                raise WebAPIError(f"selected image is not a {expected_type} image")
            if job.transport == "multicast" and (
                not manifest.artifacts or any(item.encryption != "age" for item in manifest.artifacts)
            ):
                raise WebAPIError("multicast restore requires every image artifact to be age-encrypted")
            from feclora.storage.image_security import verify_manifest_signature
            verify_manifest_signature(manifest_path, config.server_minisign_public_key)
            if job.transport == "multicast":
                job = replace(
                    job,
                    staging_required_bytes=sum(item.size_bytes for item in manifest.artifacts),
                )
        except WebAPIError:
            raise
        except Exception as exc:
            raise WebAPIError(f"restore image must have a valid Server signature: {exc}") from exc
        if any(item.encryption == "age" for item in manifest.artifacts):
            pki = Path("/etc/feclora/pki")
            recipients_directory = pki / "age-recipients"
            try:
                pki_info = os.lstat(pki)
                directory_info = os.lstat(recipients_directory)
            except OSError as exc:
                raise WebAPIError("Server age-recipient registry is unavailable") from exc
            if (not stat.S_ISDIR(pki_info.st_mode) or stat.S_ISLNK(pki_info.st_mode)
                    or pki_info.st_uid != 0 or pki_info.st_mode & 0o077
                    or not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                    or directory_info.st_uid != 0 or directory_info.st_mode & 0o077):
                raise WebAPIError("Server age-recipient registry directories are unsafe")
            for mac in job.authorized_clients:
                identity = next(
                    identity for identity, enrolled_mac in config.client_identity_to_mac.items()
                    if enrolled_mac == mac
                )
                client_id = identity.removeprefix("URI:feclora-client-")
                mapping = recipients_directory / f"{client_id}.txt"
                try:
                    info = os.lstat(mapping)
                    recipient = mapping.read_text(encoding="ascii").strip()
                except OSError as exc:
                    raise WebAPIError(f"Client {mac} has no registered age recipient") from exc
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                        or info.st_mode & 0o077 or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient)):
                    raise WebAPIError(f"Client {mac} age recipient mapping is unsafe")
    directory = _deployment_journal_directory(create=True)
    journal_path = directory / f"{job.job_id}.jsonl"
    if os.path.lexists(journal_path):
        raise WebAPIError("deployment job UUID already exists")
    try:
        journal = DeploymentJournal(journal_path, job.job_id)
        from feclora.deployment.coordinator import DeploymentCoordinator
        coordinator = DeploymentCoordinator(job, event_sink=journal)
    except Exception as exc:
        try:
            if journal_path.exists() and journal_path.stat().st_size == 0:
                journal_path.unlink()
        except OSError:
            pass
        raise WebAPIError(f"could not persist deployment job: {exc}") from exc
    return {
        "job_id": job.job_id,
        "job_state": coordinator.state.value,
        "authorized_clients": list(job.authorized_clients),
        "journal": str(journal_path),
        "started": False,
        "message": "Job definition persisted. No Client was contacted and no storage operation was started.",
    }



def _server_trusted_clients() -> dict[str, Any]:
    """Return enrolled Client identities without exposing key material."""
    from feclora.deployment.runtime_config import load_server_runtime_config
    config_path = "/etc/feclora/deployment-server.json"
    if not os.path.isfile(config_path):
        return {"clients": []}
    try:
        config = load_server_runtime_config(config_path)
    except Exception as exc:
        raise WebAPIError(f"cannot read Server trust configuration: {exc}") from exc
    return {"clients": [
        {"identity": identity, "mac_address": mac,
         "image_capture": mac in config.client_minisign_public_keys}
        for identity, mac in sorted(config.client_identity_to_mac.items())
    ]}


def _export_server_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_enrollment import export_server_age_recipients
    try:
        return export_server_age_recipients(params)
    except Exception as exc:
        raise WebAPIError(f"age recipient export failed: {exc}") from exc


def _export_server_ca_backup(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_enrollment import export_server_ca_backup
    try:
        return export_server_ca_backup(params)
    except Exception as exc:
        raise WebAPIError(f"encrypted CA backup export failed: {exc}") from exc


def _inspect_server_ca_backup(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_enrollment import inspect_server_ca_backup
    try:
        return inspect_server_ca_backup(params)
    except Exception as exc:
        raise WebAPIError(f"CA backup inspection failed: {exc}") from exc


def _refresh_client_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import refresh_client_age_recipients
    try:
        return refresh_client_age_recipients(params)
    except Exception as exc:
        raise WebAPIError(f"Client age recipient refresh failed: {exc}") from exc


def _revoke_server_client(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"identity", "confirmation"}:
        raise WebAPIError("Client revocation requires exactly identity and confirmation")
    identity, confirmation = params["identity"], params["confirmation"]
    if not isinstance(identity, str) or not identity.startswith("URI:feclora-client-"):
        raise WebAPIError("Client identity is invalid")
    if not isinstance(confirmation, str) or confirmation != f"REVOKE {identity}":
        raise WebAPIError("revocation confirmation does not match")
    from feclora.deployment.enrollment import revoke_client_certificate
    from feclora.deployment.cockpit_enrollment import remove_client_certificate_pin
    try:
        mac = revoke_client_certificate(
            "/etc/feclora/deployment-server.json", identity,
            confirmation=confirmation,
        )
        pin_removed = remove_client_certificate_pin(identity)
    except Exception as exc:
        raise WebAPIError(f"Client revocation failed: {exc}") from exc
    return {"identity": identity, "mac_address": mac, "revoked": True, "certificate_pin_removed": pin_removed}




def _remote_repository_manager():
    from feclora.storage.repository_manager import RemoteRepositoryManager
    return RemoteRepositoryManager()


def _remote_repository_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    manager = _remote_repository_manager()
    try:
        if action == "remote_repositories":
            if params:
                raise WebAPIError("remote_repositories does not accept parameters")
            return {"repositories": manager.list()}
        if action == "add_remote_repository":
            required = {
                "id", "provider", "host", "remote_path", "username",
                "credential_file", "identity_file", "known_hosts_file",
                "port", "read_only", "rclone_remote",
            }
            if set(params) != required:
                raise WebAPIError("remote repository definition has missing or unknown fields")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            definition = {key: params[key] for key in required - {"id"}}
            for key in ("provider", "host", "remote_path"):
                _text(definition, key, maximum=512)
            for key in ("username", "credential_file", "identity_file", "known_hosts_file", "rclone_remote"):
                if definition[key] is not None and (
                    not isinstance(definition[key], str) or not definition[key]
                    or len(definition[key]) > 512
                ):
                    raise WebAPIError(f"{key} must be null or a non-empty path/value")
            if definition["port"] is not None and (
                isinstance(definition["port"], bool) or not isinstance(definition["port"], int)
                or not 1 <= definition["port"] <= 65535
            ):
                raise WebAPIError("port must be null or an integer between 1 and 65535")
            if not isinstance(definition["read_only"], bool):
                raise WebAPIError("read_only must be boolean")
            return manager.add(identifier, definition)
        if action in {"mount_remote_repository", "unmount_remote_repository", "remove_remote_repository"}:
            if set(params) != {"id"}:
                raise WebAPIError(f"{action} requires exactly id")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            if action == "mount_remote_repository":
                return manager.mount(identifier)
            if action == "unmount_remote_repository":
                return manager.unmount(identifier)
            return manager.remove(identifier)
    except WebAPIError:
        raise
    except Exception as exc:
        raise WebAPIError(f"remote repository operation failed: {exc}") from exc
    raise WebAPIError("unsupported remote repository action")

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
            "certificate_status": _certificate_status(),
        }
    if action in {"remote_repositories", "add_remote_repository", "mount_remote_repository", "unmount_remote_repository", "remove_remote_repository"}:
        return _remote_repository_action(action, params)
    if action == "server_trusted_clients":
        if params:
            raise WebAPIError("server_trusted_clients does not accept parameters")
        return _server_trusted_clients()
    if action == "revoke_server_client":
        return _revoke_server_client(params)
    if action == "export_server_age_recipients":
        return _export_server_age_recipients(params)
    if action == "export_server_ca_backup":
        return _export_server_ca_backup(params)
    if action == "inspect_server_ca_backup":
        return _inspect_server_ca_backup(params)
    if action == "refresh_client_age_recipients":
        return _refresh_client_age_recipients(params)
    if action == "network_interfaces":
        if params:
            raise WebAPIError("network_interfaces does not accept parameters")
        return {"interfaces": _network_interfaces()}
    if action == "bootstrap_server":
        return _bootstrap_server(params)
    if action == "renew_server_certificate":
        return _renew_server_certificate(params)
    if action == "rotate_server_keypair":
        return _rotate_server_keypair(params)
    if action == "prepare_client_request":
        return _prepare_client_request(params)
    if action == "complete_client_enrollment":
        return _complete_client_enrollment(params)
    if action == "prepare_client_renewal":
        return _prepare_client_renewal(params)
    if action == "complete_client_renewal":
        return _complete_client_renewal(params)
    if action == "inspect_client_csr":
        return _inspect_client_csr(params)
    if action == "approve_client_csr":
        return _approve_client_csr(params)
    if action == "validate_pxe_profile":
        return _validate_pxe_profile(params)
    if action == "start_pxe_services":
        return _start_pxe_services(params)
    if action == "stop_pxe_services":
        if params:
            raise WebAPIError("stop_pxe_services does not accept parameters")
        return _stop_pxe_services()
    if action == "pxe_service_status":
        if params:
            raise WebAPIError("pxe_service_status does not accept parameters")
        return _pxe_service_manager().status()
    if action == "inventory":
        if params:
            raise WebAPIError("inventory does not accept parameters")
        return collect_inventory()
    if action == "images":
        if params:
            raise WebAPIError("images does not accept parameters")
        return {"images": _images()}
    if action == "repository_images":
        if set(params) != {"repository_id"}:
            raise WebAPIError("repository_images requires repository_id")
        return {"images": _images(_text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}"))}
    if action == "inspect_image_layout":
        return _inspect_image_layout(params)
    if action == "verify_image":
        return _verify_image(params)
    if action == "operations":
        if params:
            raise WebAPIError("operations does not accept parameters")
        return {"operations": _operations()}
    if action == "initialize_security":
        if params:
            raise WebAPIError("initialize_security does not accept parameters")
        return _initialize_security()
    if action == "deployment_jobs":
        if params:
            raise WebAPIError("deployment_jobs does not accept parameters")
        return {"jobs": _deployment_jobs()}
    if action == "inspect_remote_job":
        return _inspect_remote_job(params)
    if action == "start_client_job":
        return _start_client_job(params)
    if action == "client_job_status":
        return _client_job_status(params)
    if action == "create_deployment_job":
        return _create_deployment_job(params)
    if action == "reconcile_deployment_job":
        return _reconcile_deployment_job(params)
    if action == "start_deployment_service":
        return _start_deployment_service(params)
    if action == "deployment_service_status":
        return _deployment_service_status(_deployment_service_job_id(params))
    if action == "stop_deployment_service":
        return _stop_deployment_service(params)
    if action in {"arm_deployment_job", "cancel_deployment_job"}:
        return _deployment_service_command(action, params)
    if action == "journals":
        if params:
            raise WebAPIError("journals does not accept parameters")
        reports = _deployment_jobs()
        return {"journals": [
            {"job_id": item["job_id"], "job_state": item["job_state"],
             "interrupted": item["interrupted"], "event_count": item["event_count"],
             "clients": {mac: state["state"] for mac, state in item["clients"].items()},
             "progress": item["progress"]}
            for item in reports
        ]}
    if action == "submit_local_operation":
        return _submit_local_operation(params)
    if action == "local_operation_status":
        return _local_operation_status(params)
    if action == "local_operations":
        return _local_operations(params)
    if action in {"capture_disk", "capture_partition", "restore_disk", "restore_partition",
                  "clone_disk", "clone_partition", "extract_partition_image"}:
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

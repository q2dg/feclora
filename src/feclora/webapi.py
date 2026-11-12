"""Privileged, allowlisted Cockpit API for Feclora storage workflows.

Requests are one bounded JSON object on stdin. Long operations run in this
process and emit newline-delimited progress events followed by one result.
No shell, arbitrary argv, filesystem path outside the Feclora repository, or
untyped destructive operation is exposed.
"""
from __future__ import annotations

import json
import base64
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
from typing import Any, Callable

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import collect_inventory

REPOSITORY = Path("/var/lib/feclora/images")
MAX_REQUEST = 128 * 1024


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


def _find_inventory_device(inventory: dict[str, Any], path: str, expected_type: str) -> list[dict[str, Any]]:
    """Find a device at any depth in lsblk's nested disk/partition tree."""
    matches: list[dict[str, Any]] = []

    def visit(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("path") == path and item.get("type") == expected_type:
                matches.append(item)
            visit(item.get("children"))

    visit(inventory.get("devices"))
    return matches


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


def _clone_disk_progress(done: int, total: int, message: str) -> None:
    from feclora.storage.operation_log import record_progress

    bytes_done = max(0, int(done))
    bytes_total = max(0, int(total))
    record_progress(bytes_done, bytes_total)
    _emit({
        "event": "progress", "bytes_done": bytes_done,
        "bytes_total": bytes_total, "message": str(message)[:256],
    })


def _client_runtime_config() -> Any | None:
    path = Path("/etc/feclora/deployment-client.json")
    if not path.exists():
        return None
    from feclora.deployment.runtime_config import load_client_runtime_config
    return load_client_runtime_config(str(path))


def _capture_material() -> Path | None:
    pki = Path("/etc/feclora/pki")
    client = _client_runtime_config()
    recipients = Path(client.age_recipients_file) if client and client.age_recipients_file else pki / "age-recipients.txt"
    return recipients


def _security_material() -> dict[str, bool]:
    directory = Path("/etc/feclora/pki")
    files = {
        "age_encryption_available": directory / "age-recipients.txt",
        "age_decryption_available": directory / "server.age",
    }
    result = {"age_executable_available": bool(shutil.which("age"))}
    for label, path in files.items():
        try:
            info = os.lstat(path)
            result[label] = (
                stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == 0
                and (label != "age_decryption_available" or not info.st_mode & 0o077)
            )
        except OSError:
            result[label] = False
    client = _client_runtime_config()
    if client:
        result["age_encryption_available"] = result["age_encryption_available"] or bool(client.age_recipients_file)
        result["age_decryption_available"] = result["age_decryption_available"] or bool(client.age_identity_file)
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
        "message": "Server TLS certificate renewed with the existing CA and private key. The CA, Server identity and Client trust were not changed.",
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


def _publish_generated_keypair(staged_paths: tuple[Path, ...], final_paths: tuple[Path, ...]) -> None:
    """Publish an optional keypair without leaving half of it on failure."""
    if not staged_paths or len(staged_paths) != len(final_paths):
        raise WebAPIError("generated image-security keypair is incomplete")
    parent = final_paths[0].parent
    if any(path.parent != parent for path in final_paths):
        raise WebAPIError("generated image-security keypair must share one destination directory")
    directory_fd = None
    published: list[str] = []
    try:
        directory_fd = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise WebAPIError("Feclora PKI directory is unsafe for image-security key publication")
        for staged, final in zip(staged_paths, final_paths):
            staged_fd = os.open(staged, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                staged_info = os.fstat(staged_fd)
                if not stat.S_ISREG(staged_info.st_mode) or staged_info.st_size <= 0:
                    raise WebAPIError("generated image-security key must be a non-empty regular non-symlink file")
                os.fsync(staged_fd)
            finally:
                os.close(staged_fd)
            os.link(staged, final.name, dst_dir_fd=directory_fd, follow_symlinks=False)
            published.append(final.name)
        os.fsync(directory_fd)
    except Exception as exc:
        if directory_fd is not None:
            for name in reversed(published):
                try:
                    os.unlink(name, dir_fd=directory_fd)
                except OSError:
                    pass
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
        if isinstance(exc, WebAPIError):
            raise
        raise WebAPIError(f"could not atomically publish optional image-security keys: {exc}") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)



def _initialize_security() -> dict[str, Any]:
    """Initialize TLS identity and optional age encryption material.

    Age encryption is optional and must never prevent TLS bootstrap or ordinary imaging.
    """
    from feclora.deployment.managed_pki import initialize_server_pki

    pki = Path("/etc/feclora/pki")
    tls_paths = (pki / "ca.key", pki / "ca.crt", pki / "server.key", pki / "server.crt")
    tls_created = not all(path.exists() for path in tls_paths)
    initialize_server_pki(pki)
    created = tls_created

    age_identity = pki / "server.age"
    age_recipients = pki / "age-recipients.txt"
    if os.path.lexists(age_identity) != os.path.lexists(age_recipients):
        raise WebAPIError("partial age identity exists; refusing to regenerate trust material")
    age_keygen = shutil.which("age-keygen")
    if not os.path.lexists(age_identity) and age_keygen:
        with tempfile.TemporaryDirectory(prefix=".feclora-age-keys-", dir=pki) as staging:
            staged_identity = Path(staging) / "server.age"
            staged_recipients = Path(staging) / "age-recipients.txt"
            generated = subprocess.run(
                [age_keygen, "-o", str(staged_identity)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=60,
            )
            if generated.returncode != 0 or not staged_identity.is_file():
                raise WebAPIError("age-keygen failed while creating the optional local image identity")
            public = subprocess.run(
                [age_keygen, "-y", str(staged_identity)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=30,
            )
            recipient = public.stdout.strip()
            if public.returncode != 0 or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
                raise WebAPIError("age-keygen did not return a valid recipient")
            fd = os.open(staged_recipients, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(recipient + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(staged_identity, 0o600)
            _publish_generated_keypair(
                (staged_identity, staged_recipients), (age_identity, age_recipients),
            )
            created = True

    security = _security_material()
    unavailable = []
    if not age_keygen:
        unavailable.append("age-keygen")
    message = "TLS identity is ready."
    if unavailable:
        message += " Optional age encryption unavailable because this tool is not installed: " + ", ".join(unavailable) + ". Ordinary imaging remains available."
    return {"created": created, **security, "message": message}



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
        with _open_artifact(str(repository), table_artifact) as stream:
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
        "logical_sector_size": manifest.logical_sector_size,
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

    encrypted = any(item.encryption == "age" for item in manifest.artifacts)
    security = _security_material()
    pki = Path("/etc/feclora/pki")
    client_config = _client_runtime_config()
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
                str(repository), artifact, identity_file, shutil.which("age"),
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
            if (
                artifact.role == "disk-image"
                or (artifact.role == "partition-image" and artifact.format == "raw")
            ) and decoded_bytes != manifest.source_size_bytes:
                label = "disk" if artifact.role == "disk-image" else "raw partition"
                raise WebAPIError(
                    f"decoded {label} artifact size mismatch: expected {manifest.source_size_bytes}, got {decoded_bytes}"
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
        "manifest": "valid",
        "artifact_count": len(artifact_reports), "total_decoded_bytes": total_decoded,
        "artifacts": artifact_reports,
        "verified": True,
        "message": "All stored artifact SHA-256 digests, age authentication and compression streams were verified. This is a read-only check.",
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
    from feclora.deployment.runtime_config import load_server_runtime_config
    path = "/etc/feclora/deployment-server.json"
    if not os.path.isfile(path):
        return []
    try:
        config = load_server_runtime_config(path)
        days = certificate_expiry_days(config.certificate_file)
        ca_days = certificate_expiry_days(config.ca_file)
        return [{
            "role": "Server", "identity": config.local_identity,
            "expiry_days": days,
            "status": "expired" if days < 0 else "expiring" if days <= 30 else "valid",
            "ca_expiry_days": ca_days,
            "ca_status": "expired" if ca_days < 0 else "expiring" if ca_days <= 30 else "valid",
        }]
    except Exception as exc:
        return [{"role": "Server", "identity": None, "expiry_days": None,
                 "status": "error", "detail": str(exc)[:256]}]



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


def _apply_network_profile(params: dict[str, Any]) -> dict[str, Any]:
    required = {"uuid", "interface", "method", "address", "prefix_length", "gateway", "dns"}
    if not required.issubset(params) or set(params) - required - {"rollback_timeout"}:
        raise WebAPIError("apply_network_profile requires uuid, interface, method, address, prefix_length, gateway and dns")
    timeout = params.get("rollback_timeout", 120)
    from feclora.network.profile_apply import NetworkApplyError, apply_ipv4_profile
    try:
        return apply_ipv4_profile(
            uuid=params["uuid"], interface=params["interface"],
            method=params["method"], address=params["address"],
            prefix_length=params["prefix_length"], gateway=params["gateway"],
            dns=params["dns"], rollback_timeout=timeout,
        )
    except NetworkApplyError as exc:
        raise WebAPIError(str(exc)) from exc


def _network_connection_profiles() -> list[dict[str, Any]]:
    from feclora.network.connection_profiles import (
        NetworkProfileError, list_connection_profiles,
    )
    try:
        return list_connection_profiles()
    except NetworkProfileError as exc:
        raise WebAPIError(str(exc)) from exc


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
        "authoritative_confirmed", "max_clients", "max_duration_seconds",
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
    max_clients = params["max_clients"]
    max_duration_seconds = params["max_duration_seconds"]
    if max_clients is not None and (isinstance(max_clients, bool) or not isinstance(max_clients, int) or not 1 <= max_clients <= 4096):
        raise WebAPIError("max_clients must be an integer from 1 to 4096 or null")
    if max_duration_seconds is not None and (isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, int) or not 60 <= max_duration_seconds <= 604800):
        raise WebAPIError("max_duration_seconds must be an integer from 60 to 604800 or null")
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
        max_clients=max_clients, max_duration_seconds=max_duration_seconds,
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
        "max_clients": config.max_clients,
        "max_duration_seconds": config.max_duration_seconds,
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
        max_clients=params["max_clients"], max_duration_seconds=params["max_duration_seconds"],
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






def _publish_pxe_answer(params: dict[str, Any]) -> dict[str, Any]:
    required = {"job_id", "answer_base64"}
    if set(params) != required:
        raise WebAPIError("publish_pxe_answer requires job_id and answer_base64")
    job_id = _text(params, "job_id", maximum=36)
    answer_text = _text(params, "answer_base64", maximum=90_000)
    try:
        raw_answer = base64.b64decode(answer_text, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise WebAPIError("answer must be valid base64 data") from exc
    from feclora.network.pxe_answer import parse_pxe_answer, PXEAnswerError
    try:
        answer = parse_pxe_answer(raw_answer)
    except PXEAnswerError as exc:
        raise WebAPIError(f"PXE answer validation failed: {exc}") from exc
    manager = _pxe_service_manager()
    status = manager.status()
    if status.get("active") is not True or not status.get("interface"):
        raise WebAPIError("start and verify the PXE services before publishing an unattended answer")
    config_file = Path("/run/feclora/pxe/Caddyfile")
    try:
        info = os.lstat(config_file)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_size > 8192:
            raise WebAPIError("active Caddy configuration is not a safe root-owned regular file")
        caddy_config = config_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise WebAPIError("active Caddy configuration is unavailable") from exc
    match = re.match(r'^http://([0-9.]+):([0-9]+) \{\n    root \* "(/srv/feclora/http)"\n', caddy_config)
    if not match:
        raise WebAPIError("active Caddy configuration does not use the expected Feclora HTTP document root")
    address, port_text, http_root = match.groups()
    try:
        port = int(port_text)
        parsed_address = ipaddress.ip_address(address)
    except ValueError as exc:
        raise WebAPIError("active Caddy listener address is invalid") from exc
    if parsed_address.version != 4 or not any(
        item["interface"] == status["interface"] and item["address"] == address
        for item in _network_interfaces()
    ):
        raise WebAPIError("active Caddy address is no longer assigned to the PXE interface")
    from feclora.network.pxe_answer_store import publish_pxe_answer, revoke_pxe_answer
    from feclora.network.boot_tree import (
        publish_unattended_answer_ipxe_script, revoke_unattended_answer_ipxe_script,
    )

    answer_published = False
    try:
        published = publish_pxe_answer(
            http_root, job_id, raw_answer, address=address, http_port=port,
        )
        answer_published = True
        publish_unattended_answer_ipxe_script(
            http_root, address, job_id,
            published["answer_url"], port,
        )
    except Exception as exc:
        if answer_published:
            try:
                revoke_unattended_answer_ipxe_script(http_root, job_id)
            except Exception:
                pass
            try:
                revoke_pxe_answer(http_root, job_id)
            except Exception:
                pass
        raise WebAPIError(f"PXE answer/boot publication failed: {exc}") from exc
    return {
        "job_id": job_id,
        "answer_url": published["answer_url"],
        "boot_script_url": f"http://{address}:{port}/unattended-answer.ipxe",
        "message": "Answer validated and published over HTTP with an identity-free iPXE handoff. Live downloads and validates the JSON; NFS-backed whole-disk restore is connected, while other providers and physical acceptance remain pending.",
    }



def _pxe_age_passphrase_status(params: dict[str, Any]) -> dict[str, Any]:
    if params:
        raise WebAPIError("pxe_age_passphrase_status does not accept parameters")
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="ascii")
    except OSError as exc:
        raise WebAPIError("cannot verify PXE Live boot mode") from exc
    if "feclora.pxe_mode=unattended-answer" not in cmdline.split():
        return {"available": False, "waiting": False, "submitted": False}
    directory = Path("/run/feclora/pxe")
    marker = directory / "age-passphrase-needed"
    try:
        root_info = os.lstat(directory)
        if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
                or root_info.st_uid != 0 or root_info.st_mode & 0o077):
            raise WebAPIError("PXE Live runtime directory is not secure")
        marker_info = os.lstat(marker)
    except FileNotFoundError:
        return {"available": True, "waiting": False, "submitted": False}
    if (not stat.S_ISREG(marker_info.st_mode) or stat.S_ISLNK(marker_info.st_mode)
            or marker_info.st_uid != 0 or marker_info.st_mode & 0o077):
        raise WebAPIError("PXE age passphrase request marker is unsafe")
    try:
        os.lstat(directory / "age-passphrase")
        submitted = True
    except FileNotFoundError:
        submitted = False
    return {"available": True, "waiting": not submitted, "submitted": submitted}


def _provide_pxe_age_passphrase(params: dict[str, Any]) -> dict[str, Any]:
    """Submit a one-shot symmetric age passphrase to the local PXE Live worker."""
    if set(params) != {"passphrase"}:
        raise WebAPIError("provide_pxe_age_passphrase requires exactly passphrase")
    passphrase = params.get("passphrase")
    if (not isinstance(passphrase, str) or not passphrase
            or len(passphrase.encode("utf-8")) > 1024
            or any(char in passphrase for char in "\r\n\x00")):
        raise WebAPIError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="ascii")
    except OSError as exc:
        raise WebAPIError("cannot verify PXE Live boot mode") from exc
    if "feclora.pxe_mode=unattended-answer" not in cmdline.split():
        raise WebAPIError("age passphrases can only be submitted on an unattended PXE Live client")
    directory = Path("/run/feclora/pxe")
    marker = directory / "age-passphrase-needed"
    temporary = None
    try:
        info = os.lstat(directory)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o077):
            raise WebAPIError("PXE Live runtime directory is not secure")
        marker_info = os.lstat(marker)
        if (not stat.S_ISREG(marker_info.st_mode) or stat.S_ISLNK(marker_info.st_mode)
                or marker_info.st_uid != 0 or marker_info.st_mode & 0o077):
            raise WebAPIError("PXE Live worker is not waiting for an age passphrase")
        secret = directory / "age-passphrase"
        fd, temporary = tempfile.mkstemp(prefix=".age-passphrase-", dir=directory)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(passphrase)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, secret, follow_symlinks=False)
        os.unlink(temporary)
        temporary = None
        return {"submitted": True, "message": "Passphrase delivered once to the waiting PXE restore worker."}
    except FileExistsError as exc:
        raise WebAPIError("an age passphrase is already pending; wait for the restore worker") from exc
    except FileNotFoundError as exc:
        raise WebAPIError("the PXE restore worker is not currently waiting for an age passphrase") from exc
    except WebAPIError:
        raise
    except OSError as exc:
        raise WebAPIError(f"cannot submit age passphrase to PXE Live: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _revoke_pxe_answer(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id"}:
        raise WebAPIError("revoke_pxe_answer requires exactly job_id")
    job_id = _text(params, "job_id", maximum=36)
    from feclora.network.pxe_answer_store import revoke_pxe_answer
    from feclora.network.boot_tree import revoke_unattended_answer_ipxe_script
    try:
        revoke_unattended_answer_ipxe_script("/srv/feclora/http", job_id)
        revoked = revoke_pxe_answer("/srv/feclora/http", job_id)
    except Exception as exc:
        raise WebAPIError(f"PXE answer revocation failed: {exc}") from exc
    return {
        "job_id": job_id,
        "revoked": revoked,
        "message": "PXE answer revoked from the Caddy document root."
        if revoked else "No published PXE answer existed for this job.",
    }



def _execute_operation(action: str, params: dict[str, Any], operation_id: str) -> dict[str, Any]:
    allowed = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id", "encrypt_passphrase", "age_passphrase"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id"},
        "capture_logical_volume": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in allowed:
        raise WebAPIError("operation parameters do not match the selected operation")
    allowed_params = allowed[action]
    if action.startswith("restore_"):
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if action == "capture_disk":
        accepted_params = accepted_params + tuple(item - {"age_passphrase"} for item in accepted_params)
        accepted_params = accepted_params + tuple(
            item - {"age_passphrase", "encrypt_passphrase"} for item in accepted_params
        )
    if set(params) not in accepted_params:
        raise WebAPIError("operation parameters do not match the selected operation")
    started = time.monotonic()
    _emit({"event": "started", "operation_id": operation_id, "operation": action})
    if action == "capture_disk":
        from feclora.storage.disk_capture import capture_disk
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise WebAPIError("encrypt must be a boolean value")
        symmetric = params.get("encrypt_passphrase", False)
        if not isinstance(symmetric, bool) or (symmetric and not encrypt):
            raise WebAPIError("encrypt_passphrase must be boolean and requires encrypt=true")
        security = _security_material()
        if encrypt and symmetric:
            import shutil
            if not shutil.which("age"):
                raise WebAPIError("age executable is required for passphrase encryption")
        elif encrypt and not security["age_encryption_available"]:
            raise WebAPIError("initialize Feclora age recipient keys before enabling recipient encryption")
        recipients_file = _capture_material()
        passphrase = params.get("age_passphrase")
        if symmetric and not isinstance(passphrase, str):
            raise WebAPIError("the one-shot capture passphrase was not delivered to the worker")
        if not symmetric and passphrase is not None:
            raise WebAPIError("unexpected passphrase for recipient-based encryption")
        manifest = capture_disk(
            source, image_id, _operation_repository(params, write=True, create_local=True), compression=compression,
            progress_callback=_progress,
            age_recipients_file=recipients_file if encrypt and not symmetric else None,
            age_passphrase=passphrase if symmetric else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "capture_partition":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.partition_image_capture import capture_partition_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        partition_id = _text(params, "partition_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise WebAPIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        manifest = capture_partition_image(
            source, image_id, partition_id, _operation_repository(params, write=True, create_local=True),
            compression=compression, progress_callback=_progress, inventory=inventory,
            age_recipients_file=recipients_file if encrypt else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "capture_logical_volume":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.logical_volume_image_capture import capture_logical_volume_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise WebAPIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise WebAPIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        manifest = capture_logical_volume_image(
            source, image_id, _operation_repository(params, write=True, create_local=True),
            inventory, compression=compression, progress_callback=_progress,
            age_recipients_file=recipients_file if encrypt else None,
        )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "extract_partition_image":
        from feclora.storage.disk_image_partition import extract_partition_image
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        selector = _text(params, "selector", maximum=256)
        repository = _operation_repository(params, write=False)
        manifest_path = _image_manifest(image_id, repository)
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise WebAPIError(f"cannot read selected disk image manifest: {exc}") from exc
        if manifest.image_id != image_id or manifest.image_type != "disk":
            raise WebAPIError("partition extraction requires the selected disk image manifest")
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        security = _security_material()
        pki = Path("/etc/feclora/pki")
        identity_paths: list[Path] = []
        if security["age_decryption_available"]:
            identity_paths.append(pki / "server.age")
        client_config = _client_runtime_config()
        if client_config and client_config.age_identity_file:
            identity_paths.append(Path(client_config.age_identity_file))
        if encrypted and not identity_paths:
            raise WebAPIError("age-encrypted disk image requires an enrolled Client or local Feclora age identity")
        recipients_file = _capture_material()
        if encrypted and not security["age_encryption_available"]:
            raise WebAPIError("extracting an age-encrypted disk image requires an available age recipient inventory for the new partition image")
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
            "encrypted": any(item.encryption == "age" for item in extracted.artifacts),
        }
    elif action in {"restore_disk", "restore_partition", "restore_logical_volume"}:
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        target = _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise WebAPIError(f"explicit confirmation required: {expected}")
        repository = _operation_repository(params, write=False)
        manifest_path = _image_manifest(image_id, repository)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        expected_type = {"restore_disk": "disk", "restore_partition": "partition", "restore_logical_volume": "logical_volume"}[action]
        if manifest.image_type != expected_type:
            raise WebAPIError(f"selected image is not a {expected_type} image")
        security = _security_material()
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        pki = Path("/etc/feclora/pki")
        identity_paths: list[Path] = []
        if security["age_decryption_available"]:
            identity_paths.append(pki / "server.age")
        client_config = _client_runtime_config()
        if client_config and client_config.age_identity_file:
            identity_paths.append(Path(client_config.age_identity_file))
        if encrypted and not identity_paths:
            raise WebAPIError("age-encrypted image requires an enrolled Client or local Feclora age identity")
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
                )
            elif action == "restore_partition":
                from feclora.storage.partition_restore import restore_partition
                restore_partition(
                    manifest_path, repository, target, confirmation=expected,
                    progress_callback=_progress, age_identity_file=identity_file,
                )
            else:
                from feclora.storage.inventory import collect_inventory
                from feclora.storage.logical_volume_restore import restore_logical_volume
                restore_logical_volume(
                    manifest_path, repository, target, confirmation=expected,
                    inventory_provider=collect_inventory,
                    progress_callback=_progress, age_identity_file=identity_file,
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
        from uuid import uuid4
        from feclora.storage.local_operations import validate_definition
        validate_definition({
            "schema_version": 1, "operation_id": str(uuid4()),
            "action": operation, "params": operation_params,
        })
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


def _provide_capture_passphrase(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id", "passphrase"}:
        raise WebAPIError("provide_capture_passphrase requires operation_id and passphrase")
    operation_id = params["operation_id"]
    if not isinstance(operation_id, str):
        raise WebAPIError("operation_id must be a UUID")
    try:
        store = _local_operation_store()
        definition = store.definition(operation_id)
        report = store.status(operation_id)
        if (definition["action"] != "capture_disk"
                or not definition["params"].get("encrypt_passphrase")
                or report["state"] not in {"queued", "preflight", "running"}):
            raise WebAPIError("operation is not awaiting a passphrase-encrypted disk capture")
        from feclora.storage.capture_passphrase import provide
        provide(operation_id, params["passphrase"])
        return {"operation_id": operation_id, "provided": True}
    except WebAPIError:
        raise
    except Exception as exc:
        raise WebAPIError(f"cannot deliver one-shot capture passphrase: {exc}") from exc


def _cancel_local_operation(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id"} or not isinstance(params["operation_id"], str):
        raise WebAPIError("cancel_local_operation requires one operation_id")
    try:
        store = _local_operation_store()
        operation_id = params["operation_id"]
        report = store.status(operation_id)
        state = report["state"]
        if state == "cancelled":
            return {"operation_id": operation_id, "state": state, "requested": False}
        if state in {"completed", "failed", "interrupted", "verifying"}:
            raise WebAPIError(f"operation in state {state} cannot be cancelled")
        if state == "queued":
            try:
                store.append(operation_id, "cancelled", {
                    "reason": "cancelled before the worker started",
                    "destination_may_be_partial": False,
                })
                return {"operation_id": operation_id, "state": "cancelled", "requested": True}
            except Exception:
                # The worker may have advanced to preflight between status and
                # append. Re-read under the journal's own transition lock.
                report = store.status(operation_id)
                state = report["state"]
                if state == "cancelled":
                    return {"operation_id": operation_id, "state": state, "requested": False}
        if state not in {"preflight", "running"}:
            raise WebAPIError(f"operation in state {state} cannot be cancelled")
        unit = f"feclora-local-operation@{operation_id}.service"
        result = subprocess.run(
            ["/usr/bin/systemctl", "stop", "--no-block", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=10,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "systemd rejected the cancellation request").strip()[:384]
            raise WebAPIError(f"cannot request operation cancellation: {message}")
        return {"operation_id": operation_id, "state": state, "requested": True}
    except WebAPIError:
        raise
    except Exception as exc:
        raise WebAPIError(f"cannot cancel local operation: {exc}") from exc


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
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in operation_fields:
        raise WebAPIError("operation parameters do not match the selected operation")
    allowed_params = operation_fields[action]
    if action.startswith("restore_"):
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if set(params) not in accepted_params:
        raise WebAPIError("operation parameters do not match the selected operation")
    with _storage_operation_lock():
        return _run_operation_locked(action, params)


def _run_operation_locked(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
    }
    if action not in operation_fields:
        raise WebAPIError("operation parameters do not match the selected operation")
    allowed_params = operation_fields[action]
    if action.startswith("restore_"):
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if set(params) not in accepted_params:
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
    allowed = ({"host", "job_id"}, {"host", "job_id", "network_interface", "source_address"})
    if set(params) not in allowed:
        raise WebAPIError("remote job inspection requires host/job_id and an optional local interface/source address pair")
    network_interface = params.get("network_interface")
    source_address = params.get("source_address")
    if (network_interface is None) != (source_address is None):
        raise WebAPIError("network_interface and source_address must be supplied together")
    if network_interface is not None:
        from feclora.network.interface_discovery import discover_interface_addresses
        try:
            discovered = discover_interface_addresses(network_interface)
            matches = [item for item in discovered if item.address == source_address]
            if len(matches) != 1:
                raise WebAPIError("selected source address is not assigned to the selected Client interface")
        except WebAPIError:
            raise
        except Exception as exc:
            raise WebAPIError(f"cannot validate selected Client interface/address: {exc}") from exc
    host = params["host"]
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise WebAPIError("job_id must be a canonical UUID")
    from feclora.deployment.runtime_config import load_client_runtime_config
    from feclora.deployment.control import DeploymentControlError, inspect_deployment_job
    from feclora.network.remote_clone_protocol import create_tls_context
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
        context = create_tls_context("client", ca_file=config.ca_file)
        job = inspect_deployment_job(
            host, config.port, context,
            expected_server_identity=config.server_identity,
            mac_address=config.mac_address,
            job_id=job_id, source_address=source_address,
            network_interface=network_interface,
        )
    except (DeploymentControlError, OSError, ValueError) as exc:
        raise WebAPIError(f"could not inspect Server job: {exc}") from exc
    if job.operation == "save" and job.target_type != "disk":
        raise WebAPIError("Client-side capture currently supports whole-disk jobs only")
    return {
        "host": host,
        "port": config.port,
        "client_mac": config.mac_address,
        "client_network_interface": network_interface,
        "client_source_address": source_address,
        "server_identity": config.server_identity,
        "image_security": {
            "age_encryption_available": bool(
                config.age_recipients_file and os.path.isfile(config.age_recipients_file)
                and shutil.which("age")
            ),
        },
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
    optional = {"network_interface", "source_address", "igmp_confirmed", "image_encrypt"}
    if not required.issubset(params) or set(params) - required - optional:
        raise WebAPIError("start_client_job requires host, job_id, device_path, confirmation and compression, with optional network and per-image security choices")
    image_encrypt = params.get("image_encrypt", False)
    if not isinstance(image_encrypt, bool):
        raise WebAPIError("per-image encryption choice must be boolean")
    network_interface = params.get("network_interface")
    source_address = params.get("source_address")
    if source_address is not None and network_interface is None:
        raise WebAPIError("source_address requires a selected network_interface")
    inspection_params = {"host": params["host"], "job_id": params["job_id"]}
    if network_interface is not None and source_address is not None:
        inspection_params.update(network_interface=network_interface, source_address=source_address)
    inspection = _inspect_remote_job(inspection_params)
    job = inspection["job"]
    if job["operation"] != "save" and image_encrypt:
        raise WebAPIError("per-image encryption choice is valid only for Client save jobs")
    if image_encrypt:
        from feclora.deployment.runtime_config import load_client_runtime_config
        config = load_client_runtime_config("/etc/feclora/deployment-client.json")
        if not config.age_recipients_file or not os.path.isfile(config.age_recipients_file) or not shutil.which("age"):
            raise WebAPIError("age encryption was selected but this Client has no usable age recipient inventory or age executable")
    igmp_confirmed = params.get("igmp_confirmed", False)
    multicast_preflight = None
    if job["transport"] == "unicast" and (network_interface is None or source_address is None):
        raise WebAPIError("unicast Client jobs require a selected interface and source IPv4 address")
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
    elif igmp_confirmed is not False:
        raise WebAPIError("IGMP acknowledgement is only valid for multicast Client jobs")
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
        f"ERASE {device_path}"
        if job["operation"] == "restore"
        else f"READ {device_path}"
    )
    if confirmation != expected_confirmation:
        raise WebAPIError("local typed confirmation does not match the selected device")
    from feclora.storage.inventory import collect_inventory
    inventory = collect_inventory()
    matches = []
    if job["target_type"] == "logical_volume":
        topology = inventory.get("volume_topology", {})
        if topology.get("status") != "available":
            raise WebAPIError("local LVM topology is unavailable")
        devices = []

        def visit(items: list[dict[str, Any]]) -> None:
            for item in items:
                if isinstance(item, dict):
                    devices.append(item)
                    children = item.get("children")
                    if isinstance(children, list):
                        visit(children)

        visit(inventory.get("devices", []))
        all_lvs = [
            lv for group in topology.get("volume_groups", [])
            for lv in group.get("logical_volumes", [])
            if isinstance(lv, dict) and lv.get("major_minor")
        ]
        identity_counts = {}
        for lv in all_lvs:
            identity_counts[lv["major_minor"]] = identity_counts.get(lv["major_minor"], 0) + 1
        for group in topology.get("volume_groups", []):
            if group.get("status") != "healthy":
                continue
            for lv in group.get("logical_volumes", []):
                if (not isinstance(lv, dict) or lv.get("path") != device_path
                        or lv.get("segment_type") not in {"linear", "thin"}
                        or lv.get("snapshot") or lv.get("hidden")
                        or lv.get("health") not in (None, "", "-", "ok", "healthy")
                        or not lv.get("major_minor")
                        or identity_counts.get(lv["major_minor"]) != 1):
                    continue
                backing = [item for item in devices if item.get("major_minor") == lv["major_minor"]]
                if len(backing) == 1 and backing[0].get("type") == "lvm":
                    matches.append(lv)
    else:
        expected_type = "disk" if job["target_type"] == "disk" else "part"

        def visit_devices(items: list[dict[str, Any]]) -> None:
            for item in items:
                if item.get("path") == device_path and item.get("type") == expected_type:
                    matches.append(item)
                children = item.get("children")
                if isinstance(children, list):
                    visit_devices(children)

        visit_devices(inventory.get("devices", []))
    if len(matches) != 1:
        raise WebAPIError("selected target is not uniquely present in the current local block-device inventory")
    try:
        device_info = os.stat(device_path)
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
        "source_address": source_address, "igmp_confirmed": igmp_confirmed,
        "image_encrypt": image_encrypt,
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
        result = local_control_request(
            "/run/feclora/deployment.sock", "arm" if action == "arm_deployment_job" else "cancel",
            {"job_id": job_id, "confirmation": confirmation},
        )
    except (OSError, LocalControlError) as exc:
        raise WebAPIError(f"deployment service rejected the command: {exc}") from exc
    if action == "cancel_deployment_job" and isinstance(result, dict) and result.get("accepted") is True:
        # A cancelled deployment must no longer expose its destructive PXE answer.
        try:
            from feclora.network.pxe_answer_store import revoke_pxe_answer
            revoked = revoke_pxe_answer("/srv/feclora/http", job_id)
        except Exception as exc:
            raise WebAPIError(
                f"deployment cancellation was accepted, but its PXE answer could not be revoked: {exc}"
            ) from exc
        result["pxe_answer_revoked"] = revoked
    return result


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
    if job.network_interface not in {name for _, name in socket.if_nameindex()}:
        raise WebAPIError("selected network interface does not exist")
    if job.transport == "multicast" and job.operation != "restore":
        raise WebAPIError("network capture currently supports unicast only")
    if job.operation == "save":
        if job.image_id in {item["image_id"] for item in _images()}:
            raise WebAPIError("capture image identifier already exists")
    elif job.operation == "clone":
        source = _device(job.source_device, "source_device")
        inventory = collect_inventory()
        expected_source_type = "disk" if job.target_type == "disk" else "part"
        matches = _find_inventory_device(inventory, source, expected_source_type)
        if len(matches) != 1:
            label = "whole disk" if job.target_type == "disk" else "partition"
            raise WebAPIError(f"clone source must be one {label} in the current block-device inventory")
        if matches[0].get("read_only") is not True:
            raise WebAPIError(f"clone source {job.target_type} must already be marked read-only")
        from feclora.storage.source_safety import check_capture_source_safe, SourceSafetyError
        try:
            check_capture_source_safe(source)
        except (SourceSafetyError, OSError) as exc:
            raise WebAPIError(f"clone source {job.target_type} is unsafe or in use: {exc}") from exc
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
            if job.transport == "multicast":
                job = replace(
                    job,
                    staging_required_bytes=sum(item.size_bytes for item in manifest.artifacts),
                )
        except WebAPIError:
            raise
        except Exception as exc:
            raise WebAPIError(f"restore image manifest is invalid: {exc}") from exc
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
                mapping = recipients_directory / f"{mac.replace(':', '')}.txt"
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



def _export_server_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_enrollment import export_server_age_recipients
    try:
        return export_server_age_recipients(params)
    except Exception as exc:
        raise WebAPIError(f"age recipient export failed: {exc}") from exc


def _refresh_client_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.cockpit_client import refresh_client_age_recipients
    try:
        return refresh_client_age_recipients(params)
    except Exception as exc:
        raise WebAPIError(f"Client age recipient refresh failed: {exc}") from exc


def _remote_repository_manager():
    from feclora.storage.repository_manager import RemoteRepositoryManager
    return RemoteRepositoryManager()


def _remote_repository_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        if action == "put_systemd_credential":
            if set(params) != {"id", "kind", "source_file", "replace"}:
                raise WebAPIError("put_systemd_credential requires id, kind, source_file and replace")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            kind = _text(params, "kind", pattern=r"ssh-key|known-hosts|smb|s3", maximum=16)
            source_file = _text(params, "source_file", maximum=512)
            if not isinstance(params["replace"], bool):
                raise WebAPIError("replace must be boolean")
            from feclora.storage.credential_cli import read_source_file
            from feclora.storage.systemd_credential_store import SystemdCredentialStore
            content = read_source_file(source_file)
            return {"credential": SystemdCredentialStore().put(
                identifier, kind, content, replace=params["replace"],
            )}
        if action == "remove_systemd_credential":
            if set(params) != {"id", "kind"}:
                raise WebAPIError("remove_systemd_credential requires id and kind")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            kind = _text(params, "kind", pattern=r"ssh-key|known-hosts|smb|s3", maximum=16)
            from feclora.storage.systemd_credential_store import SystemdCredentialStore
            store = SystemdCredentialStore()
            if _remote_repository_manager().credential_is_referenced(str(store._path(identifier, kind))):
                raise WebAPIError("credential is still referenced by a saved repository; update or remove that repository first")
            if kind == "s3":
                from feclora.storage.s3_repository_manager import S3RepositoryManager
                if S3RepositoryManager().credential_is_referenced(identifier):
                    raise WebAPIError("credential is still referenced by a saved S3 repository; update or remove that repository first")
            store.remove(identifier, kind)
            return {"removed": True, "id": identifier, "kind": kind}
        if action == "systemd_credentials":
            if params:
                raise WebAPIError("systemd_credentials does not accept parameters")
            from feclora.storage.systemd_credential_store import SystemdCredentialStore
            try:
                return {"credentials": SystemdCredentialStore().list()}
            except Exception as exc:
                raise WebAPIError(f"encrypted credential inventory failed: {exc}") from exc
        if action == "s3_repositories":
            if params:
                raise WebAPIError("s3_repositories does not accept parameters")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            return {"repositories": S3RepositoryManager().list()}
        if action in {"add_s3_repository", "update_s3_repository"}:
            required = {"id", "endpoint_url", "region", "bucket", "prefix", "credential_id", "read_only"}
            if set(params) != required:
                raise WebAPIError("S3 repository definition has missing or unknown fields")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            definition = {key: params[key] for key in required - {"id"}}
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            manager = S3RepositoryManager()
            return manager.add(identifier, definition) if action == "add_s3_repository" else manager.update(identifier, definition)
        if action == "check_s3_repository":
            if set(params) != {"id"}:
                raise WebAPIError("check_s3_repository requires exactly id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            return S3RepositoryManager().check(_text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48))
        if action == "remove_s3_repository":
            if set(params) != {"id"}:
                raise WebAPIError("remove_s3_repository requires exactly id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            return S3RepositoryManager().remove(_text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48))
        if action == "s3_repository_images":
            if set(params) != {"repository_id"}:
                raise WebAPIError("s3_repository_images requires repository_id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            identifier = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            return {"images": S3RepositoryManager().repository(identifier).list_images()}
        if action == "remote_credentials":
            if params:
                raise WebAPIError("remote_credentials does not accept parameters")
            from feclora.storage.credential_store import CredentialStore
            try:
                return {"credentials": CredentialStore().list()}
            except Exception as exc:
                raise WebAPIError(f"remote credential inventory failed: {exc}") from exc
        if action == "remote_repositories":
            if params:
                raise WebAPIError("remote_repositories does not accept parameters")
            return {"repositories": _remote_repository_manager().list()}
        if action in {"add_remote_repository", "update_remote_repository"}:
            required = {
                "id", "provider", "host", "remote_path", "username",
                "credential_file", "identity_file", "known_hosts_file",
                "port", "read_only",
            }
            if set(params) != required:
                raise WebAPIError("remote repository definition has missing or unknown fields")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            definition = {key: params[key] for key in required - {"id"}}
            for key in ("provider", "host", "remote_path"):
                _text(definition, key, maximum=512)
            for key in ("username", "credential_file", "identity_file", "known_hosts_file"):
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
            manager = _remote_repository_manager()
            return manager.add(identifier, definition) if action == "add_remote_repository" else manager.update(identifier, definition)
        if action == "check_remote_repository":
            if set(params) != {"id"}:
                raise WebAPIError("check_remote_repository requires exactly id")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            return _remote_repository_manager().check(identifier)
        if action in {"mount_remote_repository", "unmount_remote_repository", "remove_remote_repository"}:
            if set(params) != {"id"}:
                raise WebAPIError(f"{action} requires exactly id")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            if action == "mount_remote_repository":
                return _remote_repository_manager().mount(identifier)
            if action == "unmount_remote_repository":
                return _remote_repository_manager().unmount(identifier)
            return _remote_repository_manager().remove(identifier)
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
    if action in {"remote_credentials", "systemd_credentials", "put_systemd_credential", "remove_systemd_credential"}:
        return _remote_repository_action(action, params)
    if action in {"remote_repositories", "add_remote_repository", "update_remote_repository", "check_remote_repository", "mount_remote_repository", "unmount_remote_repository", "remove_remote_repository"}:
        return _remote_repository_action(action, params)
    if action in {"s3_repositories", "add_s3_repository", "update_s3_repository", "check_s3_repository", "remove_s3_repository", "s3_repository_images"}:
        return _remote_repository_action(action, params)
    if action == "export_server_age_recipients":
        return _export_server_age_recipients(params)
    if action == "refresh_client_age_recipients":
        return _refresh_client_age_recipients(params)
    if action == "apply_network_profile":
        return _apply_network_profile(params)
    if action == "network_connection_profiles":
        if params:
            raise WebAPIError("network_connection_profiles does not accept parameters")
        return {"profiles": _network_connection_profiles()}
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
    if action == "validate_pxe_profile":
        return _validate_pxe_profile(params)
    if action == "start_pxe_services":
        return _start_pxe_services(params)
    if action == "stop_pxe_services":
        if params:
            raise WebAPIError("stop_pxe_services does not accept parameters")
        return _stop_pxe_services()
    if action == "publish_pxe_answer":
        return _publish_pxe_answer(params)
    if action == "revoke_pxe_answer":
        return _revoke_pxe_answer(params)
    if action == "provide_pxe_age_passphrase":
        return _provide_pxe_age_passphrase(params)
    if action == "pxe_age_passphrase_status":
        return _pxe_age_passphrase_status(params)
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
    if action == "provide_capture_passphrase":
        return _provide_capture_passphrase(params)
    if action == "submit_local_operation":
        return _submit_local_operation(params)
    if action == "local_operation_status":
        return _local_operation_status(params)
    if action == "cancel_local_operation":
        return _cancel_local_operation(params)
    if action == "local_operations":
        return _local_operations(params)
    if action in {"capture_disk", "capture_partition", "restore_disk", "restore_partition", "restore_logical_volume",
                  "clone_disk", "clone_partition", "extract_partition_image"}:
        return _submit_local_operation({"operation": action, "operation_params": params})
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

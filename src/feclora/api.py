"""Privileged, allowlisted API for Feclora terminal workflows.

Requests are one bounded JSON object on stdin. Long operations run in this
process and emit newline-delimited progress events followed by one result.
No shell, arbitrary argv, filesystem path outside the Feclora repository, or
untyped destructive operation is exposed.
"""
from __future__ import annotations

import json
import hashlib
import base64
from dataclasses import replace
import fcntl
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
MAX_REQUEST = 128 * 1024


class APIError(RuntimeError):
    """An API request was invalid or could not be fulfilled."""


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise APIError(f"duplicate request field: {key}")
        result[key] = value
    return result


def _repository(*, create: bool = False) -> Path:
    parent = REPOSITORY.parent
    if create:
        parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    try:
        parent_info = os.lstat(parent)
    except OSError as exc:
        raise APIError("Feclora state directory is unavailable") from exc
    if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
            or parent_info.st_uid != 0 or parent_info.st_mode & 0o077):
        raise APIError("Feclora state directory must be a private root-owned real directory")
    if create:
        REPOSITORY.mkdir(mode=0o700, exist_ok=True)
    try:
        info = os.lstat(REPOSITORY)
    except FileNotFoundError:
        return REPOSITORY
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise APIError("Feclora image repository must be a private root-owned real directory")
    if create:
        os.chmod(REPOSITORY, 0o700)
    return REPOSITORY


def _image_manifest(image_id: str, repository: Path | None = None) -> Path:
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise APIError("image identifier is invalid")
    path = (repository or _repository()) / f"{image_id}.manifest.json"
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise APIError("selected image manifest does not exist") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise APIError("selected image manifest is not a root-owned regular file")
    return path


def _repository_id(params: dict[str, Any]) -> str | None:
    """Return a validated repository ID, or None for the local repository."""
    repository_id = params.get("repository_id")
    if repository_id is None:
        return None
    if (not isinstance(repository_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", repository_id)):
        raise APIError("repository_id is invalid")
    return repository_id


def _operation_repository(params: dict[str, Any], *, write: bool, create_local: bool = False) -> Path:
    """Resolve a local or explicitly selected, identity-verified image repository."""
    repository_id = _repository_id(params)
    if repository_id is None:
        return _repository(create=create_local)
    try:
        return Path(_remote_repository_manager().resolve(repository_id, write=write))
    except Exception as exc:
        raise APIError(f"selected image repository is not safely available: {exc}") from exc


@contextmanager
def _operation_repository_context(
    params: dict[str, Any], *, write: bool, create_local: bool = False,
    image_id: str | None = None, upload_image_id: str | None = None,
    upload_new_images: bool = False,
):
    """Resolve a filesystem repository or stage S3 objects in a private work directory."""
    repository_id = _repository_id(params)
    if repository_id is None:
        yield _operation_repository(params, write=write, create_local=create_local)
        return
    from feclora.storage.s3_repository_manager import S3RepositoryManager
    manager = S3RepositoryManager()
    s3_definition = next((item for item in manager.list() if item["id"] == repository_id), None)
    if s3_definition is None:
        manager = _remote_repository_manager()
        lease_fd = None
        try:
            lease_fd = manager.acquire_usage_lock(repository_id)
            repository = Path(manager.resolve(repository_id, write=write))
        except Exception as exc:
            if lease_fd is not None:
                os.close(lease_fd)
            raise APIError(f"selected image repository is not safely available: {exc}") from exc
        try:
            yield repository
        finally:
            os.close(lease_fd)
        return
    try:
        s3_usage_fd = manager.acquire_usage_lock(repository_id)
    except Exception as exc:
        raise APIError(f"selected S3 repository is not safely available: {exc}") from exc
    try:
        object_repository = manager.repository(repository_id, progress=_progress)
        if write and object_repository.config.read_only:
            raise APIError("S3 repository is configured read-only")
        with tempfile.TemporaryDirectory(prefix="feclora-s3-operation-") as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            if image_id is not None:
                object_repository.download_image_set(image_id, root)
            original_ids = {
                item.name[:-len(".manifest.json")]
                for item in root.glob("*.manifest.json") if item.is_file()
            }
            yield root
            if write:
                if upload_image_id is not None:
                    object_repository.upload_image_set(root, upload_image_id)
                elif upload_new_images:
                    new_ids = sorted(
                        item.name[:-len(".manifest.json")]
                        for item in root.glob("*.manifest.json")
                        if item.is_file() and item.name[:-len(".manifest.json")] not in original_ids
                    )
                    if not new_ids:
                        raise APIError("S3 operation produced no new image manifest to publish")
                    for new_id in new_ids:
                        object_repository.upload_image_set(root, new_id)
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"S3 object repository operation failed: {exc}") from exc
    finally:
        os.close(s3_usage_fd)


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
        raise APIError(f"{field} must be a normalized /dev block-device path")
    return value


def _text(params: dict[str, Any], key: str, *, default: str | None = None,
          pattern: str | None = None, maximum: int = 128) -> str:
    value = params.get(key, default)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise APIError(f"{key} must be a non-empty string of at most {maximum} characters")
    if pattern and not re.fullmatch(pattern, value):
        raise APIError(f"{key} contains unsupported characters")
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


def _assert_no_active_deployment_jobs(operation: str) -> None:
    """Fail closed unless no Feclora deployment worker is running."""
    try:
        active = subprocess.run(
            ["/usr/bin/systemctl", "list-units", "--type=service", "--state=running",
             "--no-legend", "feclora-deployment@*.service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError(f"cannot establish whether a deployment service is active: {exc}") from exc
    if active.returncode != 0:
        raise APIError(
            f"cannot establish whether a deployment service is active; {operation} is blocked"
        )
    if active.stdout.strip():
        raise APIError(f"stop all active deployment jobs before {operation}")


def _renew_server_certificate(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"confirmation"} or params.get("confirmation") != "RENEW SERVER CERTIFICATE":
        raise APIError("explicit confirmation required: RENEW SERVER CERTIFICATE")
    config_path = "/etc/feclora/deployment-server.json"
    try:
        from feclora.deployment.runtime_config import load_server_runtime_config
        config = load_server_runtime_config(config_path)
    except Exception as exc:
        raise APIError(f"managed Server identity is unavailable: {exc}") from exc
    if os.path.realpath(config.certificate_file) != "/etc/feclora/pki/server.crt" or os.path.realpath(
        config.private_key_file
    ) != "/etc/feclora/pki/server.key" or os.path.realpath(config.ca_file) != "/etc/feclora/pki/ca.crt":
        raise APIError("Server PKI paths differ from the managed renewal locations; refusing to replace an untracked certificate")
    if config.local_identity != "URI:feclora-server":
        raise APIError("Server runtime identity is not the managed Feclora Server identity")
    _assert_no_active_deployment_jobs("renewing the Server TLS certificate")
    try:
        from feclora.deployment.managed_pki import renew_server_certificate, certificate_expiry_days
        renewed = renew_server_certificate("/etc/feclora/pki")
        days = certificate_expiry_days(renewed["certificate_file"])
    except Exception as exc:
        raise APIError(f"Server TLS certificate renewal failed: {exc}") from exc
    return {
        "renewed": True, "identity": config.local_identity,
        "certificate_file": renewed["certificate_file"],
        "ca_fingerprint": renewed["ca_fingerprint"], "expiry_days": days,
        "ca_expiry_days": renewed["ca_expiry_days"],
        "message": "Server TLS certificate renewed with the existing CA and private key. The CA and Server identity were not changed.",
    }



def _rotate_server_keypair(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"confirmation"} or params.get("confirmation") != "ROTATE SERVER TLS KEYPAIR":
        raise APIError("explicit confirmation required: ROTATE SERVER TLS KEYPAIR")
    try:
        from feclora.deployment.runtime_config import load_server_runtime_config
        config = load_server_runtime_config("/etc/feclora/deployment-server.json")
    except Exception as exc:
        raise APIError(f"managed Server identity is unavailable: {exc}") from exc
    if (os.path.realpath(config.certificate_file) != "/etc/feclora/pki/server.crt"
            or os.path.realpath(config.private_key_file) != "/etc/feclora/pki/server.key"
            or os.path.realpath(config.ca_file) != "/etc/feclora/pki/ca.crt"
            or config.local_identity != "URI:feclora-server"):
        raise APIError("Server PKI paths or identity differ from the managed rotation locations")
    _assert_no_active_deployment_jobs("rotating the Server TLS keypair")
    try:
        from feclora.deployment.managed_pki import rotate_server_keypair, certificate_expiry_days
        rotated = rotate_server_keypair("/etc/feclora/pki")
        days = certificate_expiry_days(rotated["certificate_file"])
    except Exception as exc:
        raise APIError(f"Server TLS keypair rotation failed: {exc}") from exc
    return {
        "rotated": True, "identity": config.local_identity,
        "certificate_file": rotated["certificate_file"],
        "private_key_file": rotated["private_key_file"],
        "ca_fingerprint": rotated["ca_fingerprint"], "key_rotated": rotated["key_rotated"],
        "expiry_days": days, "ca_expiry_days": rotated["ca_expiry_days"],
        "message": "Server TLS keypair rotated under the existing CA. Clients continue to verify the Server using the configured CA and Server identity; the Server certificate and private key have both changed.",
    }


def _publish_generated_keypair(staged_paths: tuple[Path, ...], final_paths: tuple[Path, ...]) -> None:
    """Publish an optional keypair without leaving half of it on failure."""
    if not staged_paths or len(staged_paths) != len(final_paths):
        raise APIError("generated image-security keypair is incomplete")
    parent = final_paths[0].parent
    if any(path.parent != parent for path in final_paths):
        raise APIError("generated image-security keypair must share one destination directory")
    directory_fd = None
    published: list[str] = []
    try:
        directory_fd = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise APIError("Feclora PKI directory is unsafe for image-security key publication")
        for staged, final in zip(staged_paths, final_paths):
            staged_fd = os.open(staged, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                staged_info = os.fstat(staged_fd)
                if not stat.S_ISREG(staged_info.st_mode) or staged_info.st_size <= 0:
                    raise APIError("generated image-security key must be a non-empty regular non-symlink file")
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
        if isinstance(exc, APIError):
            raise
        raise APIError(f"could not atomically publish optional image-security keys: {exc}") from exc
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
        raise APIError("partial age identity exists; refusing to regenerate trust material")
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
                raise APIError("age-keygen failed while creating the optional local image identity")
            public = subprocess.run(
                [age_keygen, "-y", str(staged_identity)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=30,
            )
            recipient = public.stdout.strip()
            if public.returncode != 0 or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
                raise APIError("age-keygen did not return a valid recipient")
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



def _filesystem_images(
    path: Path, *, missing_ok: bool = False,
) -> list[dict[str, Any]]:
    """Read committed image manifests and verified QCOW2 P2V sidecars."""
    try:
        with os.scandir(path) as entries:
            names = sorted(entry.name for entry in entries)
    except FileNotFoundError:
        if missing_ok:
            return []
        raise
    items = []
    for name in names:
        if not name.endswith(".manifest.json"):
            continue
        manifest_path = path / name
        info = os.lstat(manifest_path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            continue
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeError, ManifestValidationError):
            continue
        items.append({
            "image_id": manifest.image_id, "image_type": manifest.image_type,
            "image_format": next((artifact.format for artifact in manifest.artifacts
                                  if artifact.role in {"disk-image", "partition-image", "logical-volume-image"}), None),
            "source_size_bytes": manifest.source_size_bytes,
            "logical_sector_size": manifest.logical_sector_size,
            "encrypted": bool(manifest.artifacts) and all(
                artifact.encryption == "age" for artifact in manifest.artifacts
            ), "artifact_count": len(manifest.artifacts),
        })
    for name in names:
        if not name.endswith(".p2v.json"):
            continue
        metadata_path = path / name
        try:
            info = os.lstat(metadata_path)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            image_id = name[:-len(".p2v.json")]
            qcow2_path = path / f"{image_id}.qcow2"
            qcow2_info = os.lstat(qcow2_path)
            if (metadata.get("schema_version") != 1 or metadata.get("image_id") != image_id
                    or metadata.get("format") != "qcow2" or metadata.get("verified") is not True
                    or not stat.S_ISREG(qcow2_info.st_mode) or qcow2_info.st_uid != os.geteuid()
                    or qcow2_info.st_size != metadata.get("file_size_bytes")):
                continue
            digest = hashlib.sha256()
            with qcow2_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != metadata.get("qcow2_sha256"):
                continue
            items.append({
                "image_id": image_id, "image_type": "virtual_disk", "format": "qcow2",
                "source_size_bytes": metadata.get("virtual_size_bytes"),
                "logical_sector_size": metadata.get("logical_sector_size"),
                "importable": (not isinstance(metadata.get("logical_sector_size"), bool)
                               and metadata.get("logical_sector_size") in {512, 4096}),
                "artifact_bytes": metadata.get("file_size_bytes"), "artifact_count": 1,
                "encrypted": False, "verified": True,
            })
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return items


def _export_p2v_from_s3(params: dict[str, Any]) -> dict[str, Any]:
    """Export one committed S3 QCOW2 to a filesystem repository, sidecar last."""
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    source_id = _text(params, "source_repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}")
    destination_id = params.get("destination_repository_id")
    if destination_id is not None and (
        not isinstance(destination_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", destination_id)
    ):
        raise APIError("destination_repository_id is invalid")
    from feclora.storage.s3_repository_manager import S3RepositoryManager
    s3_manager = S3RepositoryManager()
    if not any(item["id"] == source_id for item in s3_manager.list()):
        raise APIError("source_repository_id must identify a configured S3 object repository")
    source_lease = destination_lease = None
    try:
        source_lease = s3_manager.acquire_usage_lock(source_id)
        source = s3_manager.repository(source_id, progress=_progress)
        with tempfile.TemporaryDirectory(prefix="feclora-p2v-export-") as temporary:
            staging = Path(temporary)
            os.chmod(staging, 0o700)
            source.download_p2v(image_id, staging)
            qcow2 = staging / f"{image_id}.qcow2"
            sidecar = staging / f"{image_id}.p2v.json"
            if destination_id is None:
                destination = _repository(create=True)
            else:
                manager = _remote_repository_manager()
                destination_lease = manager.acquire_usage_lock(destination_id)
                destination = Path(manager.resolve(destination_id, write=True))
            directory_info = os.lstat(destination)
            if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                    or (destination_id is None and directory_info.st_uid != os.geteuid())):
                raise APIError("P2V export destination must be a real, safely resolved directory")
            target_qcow2 = destination / f"{image_id}.qcow2"
            target_sidecar = destination / f"{image_id}.p2v.json"
            if os.path.lexists(target_qcow2) or os.path.lexists(target_sidecar):
                raise APIError("P2V export refuses to overwrite an existing destination object")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            if (metadata.get("schema_version") != 1 or metadata.get("image_id") != image_id
                    or metadata.get("format") != "qcow2" or metadata.get("verified") is not True):
                raise APIError("verified S3 P2V metadata failed local export validation")

            def stage_in_destination(source_path: Path) -> tuple[Path, int, str]:
                fd, temporary_name = tempfile.mkstemp(prefix=".feclora-p2v-export-", dir=destination)
                temporary_path = Path(temporary_name)
                digest = hashlib.sha256()
                total = 0
                try:
                    os.fchmod(fd, 0o600)
                    with source_path.open("rb") as source_stream, os.fdopen(fd, "wb") as output:
                        fd = -1
                        for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                            output.write(chunk)
                            digest.update(chunk)
                            total += len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    return temporary_path, total, digest.hexdigest()
                except Exception:
                    if fd >= 0:
                        os.close(fd)
                    temporary_path.unlink(missing_ok=True)
                    raise

            staged_qcow2, copied_size, copied_digest = stage_in_destination(qcow2)
            staged_sidecar = None
            published_qcow2 = False
            published_sidecar = False
            try:
                if (copied_size != metadata.get("file_size_bytes")
                        or copied_digest != metadata.get("qcow2_sha256")):
                    raise APIError("staged P2V QCOW2 failed size or SHA-256 verification")
                staged_sidecar, sidecar_size, sidecar_digest = stage_in_destination(sidecar)
                original_sidecar_digest = hashlib.sha256(sidecar.read_bytes()).hexdigest()
                if sidecar_size != sidecar.stat().st_size or sidecar_digest != original_sidecar_digest:
                    raise APIError("staged P2V metadata sidecar failed integrity verification")
                os.link(staged_qcow2, target_qcow2, follow_symlinks=False)
                published_qcow2 = True
                # Metadata is the commit marker and is always published last.
                os.link(staged_sidecar, target_sidecar, follow_symlinks=False)
                published_sidecar = True
                directory_fd = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                       | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                if published_sidecar:
                    try:
                        os.unlink(target_sidecar)
                    except OSError:
                        pass
                if published_qcow2:
                    try:
                        os.unlink(target_qcow2)
                    except OSError:
                        pass
                raise
            finally:
                staged_qcow2.unlink(missing_ok=True)
                if staged_sidecar is not None:
                    staged_sidecar.unlink(missing_ok=True)
            return {
                "image_id": image_id, "source_repository_id": source_id,
                "destination_repository_id": destination_id, "output_path": str(target_qcow2),
                "format": "qcow2", "verified": True, "metadata_committed": True,
            }
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"P2V S3 export failed safely: {exc}") from exc
    finally:
        if destination_lease is not None:
            os.close(destination_lease)
        if source_lease is not None:
            os.close(source_lease)


def _images(repository_id: str | None = None) -> list[dict[str, Any]]:
    if repository_id is None:
        return _filesystem_images(_repository(), missing_ok=True)
    from feclora.storage.s3_repository_manager import S3RepositoryManager
    manager = S3RepositoryManager()
    if any(item["id"] == repository_id for item in manager.list()):
        lease_fd = None
        try:
            lease_fd = manager.acquire_usage_lock(repository_id)
            return manager.repository(repository_id).list_images()
        except Exception as exc:
            raise APIError(f"S3 image inventory failed: {exc}") from exc
        finally:
            if lease_fd is not None:
                os.close(lease_fd)

    manager = _remote_repository_manager()
    lease_fd = None
    try:
        lease_fd = manager.acquire_usage_lock(repository_id)
        path = Path(manager.resolve(repository_id, write=False))
        return _filesystem_images(path)
    except Exception as exc:
        raise APIError(f"remote image inventory failed: {exc}") from exc
    finally:
        if lease_fd is not None:
            os.close(lease_fd)


def _inspect_image_layout(params: dict[str, Any]) -> dict[str, Any]:
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    with _operation_repository_context(params, write=False, image_id=image_id) as repository:
        return _inspect_image_layout_from_repository(params, repository)


def _inspect_image_layout_from_repository(params: dict[str, Any], repository: Path) -> dict[str, Any]:
    if set(params) not in ({"image_id"}, {"image_id", "repository_id"}):
        raise APIError("inspect_image_layout requires image_id and optional repository_id")
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    manifest_path = _image_manifest(image_id, repository)
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise APIError(f"cannot read selected image manifest: {exc}") from exc
    if manifest.image_id != image_id:
        raise APIError("selected image manifest identifier does not match its repository name")
    if manifest.image_type != "disk":
        raise APIError("layout inspection requires a whole-disk image")
    disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disk_artifacts) != 1 or disk_artifacts[0].format not in {"raw", "qcow2"}:
        raise APIError("whole-disk image must contain exactly one raw or QCOW2 disk-image artifact")
    table_artifacts = [item for item in manifest.artifacts if item.role == "partition-table"]
    if len(table_artifacts) != 1 or table_artifacts[0].format != "raw":
        raise APIError("whole-disk image must contain exactly one raw partition-table artifact")
    table_artifact = table_artifacts[0]
    if table_artifact.encryption != "none" or table_artifact.compression != "none":
        raise APIError("partition-table metadata must be stored unencrypted and uncompressed")
    from feclora.storage.disk_restore import DiskRestoreError, _open_artifact, _verify_stored_artifact
    from feclora.storage.partition_range import PartitionRangeError, parse_sfdisk_dump, partition_ranges
    try:
        with _open_artifact(str(repository), table_artifact) as stream:
            _verify_stored_artifact(stream, table_artifact)
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise APIError("partition-table metadata exceeds 1 MiB")
        table = parse_sfdisk_dump(
            raw.decode("utf-8"), image_size_bytes=manifest.source_size_bytes,
            default_sector_size=manifest.logical_sector_size,
        )
        ranges = partition_ranges(
            table, image_size_bytes=manifest.source_size_bytes,
            sector_size=manifest.logical_sector_size,
        )
    except (DiskRestoreError, OSError, UnicodeError, PartitionRangeError) as exc:
        raise APIError(f"partition-table verification or parsing failed: {exc}") from exc
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



def _browse_image(params: dict[str, Any]) -> dict[str, Any]:
    required = {"image_id", "partition_index", "path"}
    optional = {"repository_id", "download", "session_id"}
    if not required.issubset(params) or set(params) - required - optional:
        raise APIError("browse_image requires image_id, partition_index and path, with optional repository_id, download and session_id")
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    partition_index = params.get("partition_index")
    if isinstance(partition_index, bool) or not isinstance(partition_index, int) or not 1 <= partition_index <= 256:
        raise APIError("partition_index must be an integer between 1 and 256")
    guest_path = params.get("path")
    if not isinstance(guest_path, str) or len(guest_path) > 4096 or "\x00" in guest_path:
        raise APIError("path must be a string of at most 4096 characters")
    session_id = params.get("session_id")
    if session_id is not None and (
        not isinstance(session_id, str)
        or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", session_id)
    ):
        raise APIError("session_id must be a canonical UUID")
    download = params.get("download", False)
    if not isinstance(download, bool):
        raise APIError("download must be boolean")
    with _operation_repository_context(params, write=False, image_id=image_id) as repository:
        manifest_path = _image_manifest(image_id, repository)
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise APIError(f"cannot read selected disk image manifest: {exc}") from exc
        if manifest.image_id != image_id or manifest.image_type != "disk":
            raise APIError("image browsing requires the selected whole-disk image")
        verified_layout = _inspect_image_layout_from_repository({"image_id": image_id}, repository)
        if partition_index > len(verified_layout["partitions"]):
            raise APIError("selected partition index is not present in the verified partition table")
        partition_selector = verified_layout["partitions"][partition_index - 1]["selector"]
        encrypted = any(item.role == "disk-image" and item.encryption == "age" for item in manifest.artifacts)
        identity_paths: list[Path] = []
        pki = Path("/etc/feclora/pki")
        security = _security_material()
        if security["age_decryption_available"]:
            identity_paths.append(pki / "server.age")
        client_config = _client_runtime_config()
        if client_config and client_config.age_identity_file:
            identity_paths.append(Path(client_config.age_identity_file))
        if encrypted and not identity_paths:
            raise APIError("age-encrypted image requires a configured age identity")
        identity_context = tempfile.TemporaryDirectory(prefix="feclora-image-browser-identities-") if encrypted and len(identity_paths) > 1 else None
        try:
            if identity_context:
                identity_file = Path(identity_context.name) / "identities.txt"
                identity_file.write_text(
                    "\n".join(item.read_text(encoding="ascii").strip() for item in identity_paths) + "\n",
                    encoding="ascii",
                )
                os.chmod(identity_file, 0o600)
            else:
                identity_file = identity_paths[0] if encrypted else None
            from feclora.storage.image_browser import ImageBrowserError, browse_image
            try:
                return browse_image(
                    manifest_path, repository, partition_index, guest_path,
                    download=download,
                    expected_partition_count=len(verified_layout["partitions"]),
                    expected_partition_selector=partition_selector,
                    age_identity_file=identity_file,
                    session_id=session_id,
                )
            except ImageBrowserError as exc:
                raise APIError(str(exc)) from exc
        finally:
            if identity_context:
                identity_context.cleanup()


def _verify_image(params: dict[str, Any]) -> dict[str, Any]:
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    with _operation_repository_context(params, write=False, image_id=image_id) as repository:
        return _verify_image_from_repository(params, repository)


def _verify_image_from_repository(params: dict[str, Any], repository: Path) -> dict[str, Any]:
    """Read-only, end-to-end verification of every stored image artifact."""
    if set(params) not in ({"image_id"}, {"image_id", "repository_id"}):
        raise APIError("verify_image requires image_id and optional repository_id")
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    manifest_path = _image_manifest(image_id, repository)
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise APIError(f"cannot read selected image manifest: {exc}") from exc
    if manifest.image_id != image_id:
        raise APIError("selected image manifest identifier does not match its repository name")

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
        raise APIError("image contains age-encrypted artifacts but no local age identity is available")

    from feclora.storage.disk_restore import (
        _decoded_stream, _verified_artifact_stream,
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
            if artifact.format == "qcow2":
                qemu_img = shutil.which("qemu-img")
                if not qemu_img or artifact.role != "disk-image":
                    raise APIError("qemu-img is required to verify a QCOW2 whole-disk artifact")
                with tempfile.TemporaryDirectory(prefix="feclora-verify-qcow2-") as temporary:
                    staged = Path(temporary) / "image.qcow2"
                    with _verified_artifact_stream(
                        str(repository), artifact, identity_file, shutil.which("age"),
                    ) as verified_stream, staged.open("xb") as output:
                        shutil.copyfileobj(verified_stream, output, 1024 * 1024)
                    info_result = subprocess.run(
                        [qemu_img, "info", "--output=json", str(staged)],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        check=False, timeout=60,
                    )
                    if info_result.returncode != 0:
                        raise APIError("qemu-img info could not inspect the QCOW2 artifact")
                    try:
                        info = json.loads(info_result.stdout)
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise APIError("qemu-img returned invalid QCOW2 metadata") from exc
                    format_specific = info.get("format-specific") if isinstance(info, dict) else None
                    format_data = format_specific.get("data", {}) if isinstance(format_specific, dict) else {}
                    external_data_file = info.get("data-file") if isinstance(info, dict) else None
                    if isinstance(format_data, dict):
                        external_data_file = external_data_file or format_data.get("data-file")
                    if (not isinstance(info, dict) or info.get("format") != "qcow2"
                            or isinstance(info.get("virtual-size"), bool)
                            or not isinstance(info.get("virtual-size"), int)
                            or info.get("virtual-size") != manifest.source_size_bytes
                            or info.get("backing-filename") or info.get("full-backing-filename")
                            or external_data_file or info.get("encrypted") is True
                            or (isinstance(format_data, dict) and format_data.get("encrypted") is True)):
                        raise APIError("QCOW2 dependencies or virtual capacity disagree with the manifest")
                    check = subprocess.run(
                        [qemu_img, "check", "-f", "qcow2", str(staged)],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        check=False, timeout=24 * 60 * 60,
                    )
                    if check.returncode != 0:
                        raise APIError("qemu-img check rejected the QCOW2 artifact")
                decoded_bytes = manifest.source_size_bytes
            else:
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
                raise APIError(
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
            raise APIError(f"artifact verification failed for {artifact.filename}: {exc}") from exc
        finally:
            if identity_context:
                identity_context.cleanup()
    return {
        "image_id": image_id, "image_type": manifest.image_type,
        "manifest": "valid",
        "artifact_count": len(artifact_reports), "total_decoded_bytes": total_decoded,
        "artifacts": artifact_reports,
        "verified": True,
        "message": "All stored artifact SHA-256 digests, age authentication, compression streams and QCOW2 structures were verified. This is a read-only check.",
    }


def _operations() -> list[dict[str, Any]]:
    path = Path("/var/lib/feclora/operations.jsonl")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise APIError("operation journal must be a private root-owned regular file")
    if info.st_size > 2 * 1024 * 1024:
        raise APIError("operation journal exceeds the API read limit")
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
            ["/usr/bin/systemctl", "is-active", "feclora-tui.service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=3,
        )
        services["Textual interface"] = result.stdout.strip() or "inactive"
    except (OSError, subprocess.SubprocessError):
        services["Textual interface"] = "unknown"
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
        raise APIError("apply_network_profile requires uuid, interface, method, address, prefix_length, gateway and dns")
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
        raise APIError(str(exc)) from exc


def _network_connection_profiles() -> list[dict[str, Any]]:
    from feclora.network.connection_profiles import (
        NetworkProfileError, list_connection_profiles,
    )
    try:
        return list_connection_profiles()
    except NetworkProfileError as exc:
        raise APIError(str(exc)) from exc


def _network_interfaces() -> list[dict[str, Any]]:
    from feclora.network.interface_discovery import (
        detect_existing_dhcp_server, parse_interface_addresses,
    )

    executable = shutil.which("ip")
    if not executable:
        raise APIError("iproute is required for network interface discovery")
    try:
        result = subprocess.run(
            [executable, "-j", "-4", "address", "show"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=True, timeout=10,
        )
        rows = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise APIError(f"cannot inspect network interfaces: {exc}") from exc
    if not isinstance(rows, list):
        raise APIError("ip returned an invalid interface inventory")
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
        raise APIError("bootstrap_server requires interface, address and prefix_length")
    interface = _text(params, "interface", pattern=r"[A-Za-z0-9_.:-]{1,15}", maximum=15)
    address = _text(params, "address", maximum=45)
    prefix = params["prefix_length"]
    if isinstance(prefix, bool) or not isinstance(prefix, int) or not 1 <= prefix <= 30:
        raise APIError("prefix_length must be an integer between 1 and 30")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise APIError("Server address must be a valid IPv4 address") from exc
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback:
        raise APIError("Server address must be a concrete unicast IPv4 address")

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
        raise APIError(f"Server identity initialization failed: {exc}") from exc
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
        raise APIError("validate_pxe_profile requires the complete PXE profile field set")
    interface = _text(params, "interface", pattern=r"[A-Za-z0-9_.:-]{1,15}", maximum=15)
    address = _text(params, "address", maximum=45)
    mode = _text(params, "mode", pattern=r"(?:proxy|isolated)", maximum=16)
    prefix = params["prefix_length"]
    port = params["http_port"]
    authoritative = params["authoritative_confirmed"]
    if isinstance(prefix, bool) or not isinstance(prefix, int) or not 1 <= prefix <= 30:
        raise APIError("prefix_length must be an integer between 1 and 30")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise APIError("http_port must be an integer between 1 and 65535")
    if not isinstance(authoritative, bool):
        raise APIError("authoritative_confirmed must be boolean")
    max_clients = params["max_clients"]
    max_duration_seconds = params["max_duration_seconds"]
    if max_clients is not None and (isinstance(max_clients, bool) or not isinstance(max_clients, int) or not 1 <= max_clients <= 4096):
        raise APIError("max_clients must be an integer from 1 to 4096 or null")
    if max_duration_seconds is not None and (isinstance(max_duration_seconds, bool) or not isinstance(max_duration_seconds, int) or not 60 <= max_duration_seconds <= 604800):
        raise APIError("max_duration_seconds must be an integer from 60 to 604800 or null")
    optional = {}
    for key in ("pool_start", "pool_end", "gateway", "dns_server"):
        value = params[key]
        if value is not None and (not isinstance(value, str) or not value or len(value) > 45):
            raise APIError(f"{key} must be an IPv4 address or null")
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
        raise APIError(f"PXE preflight failed: {exc}") from exc
    warnings = []
    if dhcp_server:
        warnings.append(
            f"NetworkManager reports DHCP server {dhcp_server} on this interface. "
            "Use ProxyDHCP unless the network is a deliberately isolated Feclora DHCP segment."
        )
        if mode == "isolated":
            raise APIError(
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
        raise APIError(f"cannot verify active deployment service ownership: {exc}") from exc


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
        raise APIError("stop the active deployment service before activating PXE on the same interface")
    try:
        manager = _pxe_service_manager()
        manager.start(config)
        status = manager.status()
    except Exception as exc:
        raise APIError(f"PXE service activation failed: {exc}") from exc
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
            raise APIError("stop the deployment service before stopping PXE on the same interface")
        manager.stop()
        status = manager.status()
    except Exception as exc:
        raise APIError(f"PXE service shutdown failed: {exc}") from exc
    return {
        "active": status["active"], "interface": status["interface"],
        "services": status["services"],
        "message": "PXE services stopped and the interface's previous firewalld zone restored."
        if not status["configured"] else
        "PXE shutdown is incomplete; inspect service and firewall state before continuing.",
    }






def _read_pxe_answer_source(params: dict[str, Any]) -> bytes:
    """Read a bounded answer document from upload, HTTP(S), or a managed repository."""
    from urllib.parse import urlsplit
    from urllib.request import HTTPRedirectHandler, Request, build_opener
    from feclora.network.pxe_answer import MAX_ANSWER_BYTES

    source = params.get("source")
    if source == "upload":
        if set(params) != {"job_id", "source", "answer_base64"}:
            raise APIError("upload source requires job_id, source and answer_base64")
        encoded = _text(params, "answer_base64", maximum=90_000)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise APIError("answer must be valid base64 data") from exc
    elif source == "url":
        if set(params) != {"job_id", "source", "url"}:
            raise APIError("URL source requires job_id, source and url")
        url = _text(params, "url", maximum=4096)
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or any(ord(char) < 32 for char in url)):
            raise APIError("answer URL must be an HTTP or HTTPS URL without embedded credentials or a fragment")
        class _NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        request = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Feclora-PXE-Answer/1",
        })
        try:
            opener = build_opener(_NoRedirect)
            with opener.open(request, timeout=10.0) as response:
                if response.status != 200:
                    raise APIError(f"answer server returned HTTP {response.status}")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > MAX_ANSWER_BYTES):
                    raise APIError("remote answer exceeds the 64 KiB size limit")
                raw = response.read(MAX_ANSWER_BYTES + 1)
        except APIError:
            raise
        except Exception as exc:
            raise APIError(f"cannot download answer from the supplied HTTP(S) URL: {exc}") from exc
    elif source in {"repository", "scp"}:
        if set(params) != {"job_id", "source", "repository_id", "source_path"}:
            raise APIError("repository/SCP source requires job_id, source, repository_id and source_path")
        repository_id = _repository_id(params)
        if repository_id is None:
            raise APIError("repository_id is invalid")
        source_path = _text(params, "source_path", maximum=1024)
        parts = source_path.split("/")
        if (source_path.startswith("/") or "\\" in source_path or "\x00" in source_path
                or any(part in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.@+=-]{1,128}", part)
                       for part in parts)):
            raise APIError("repository answer path must be a safe relative path")
        try:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            s3_manager = S3RepositoryManager()
            s3_entries = {item["id"] for item in s3_manager.list()}
            if source == "repository" and repository_id in s3_entries:
                lease_fd = s3_manager.acquire_usage_lock(repository_id)
                try:
                    raw = s3_manager.repository(repository_id).download_small_object(
                        source_path, max_bytes=MAX_ANSWER_BYTES,
                    )
                finally:
                    os.close(lease_fd)
            elif source == "scp":
                manager = _remote_repository_manager()
                lease_fd = manager.acquire_usage_lock(repository_id)
                try:
                    definition = manager._load().get(repository_id)
                    if not isinstance(definition, dict) or definition.get("provider") != "sshfs":
                        raise APIError("SCP source requires an existing SSHFS repository definition")
                    from feclora.storage.repository_manager import _repository
                    repo = _repository(repository_id, definition)
                    from feclora.storage.systemd_credential_store import SystemdCredentialStore
                    credential_store = SystemdCredentialStore()

                    def read_ssh_material(path_value: str, kind: str, *, private: bool) -> bytes:
                        credential_path = Path(path_value)
                        prefix = "feclora-"
                        suffix = f"-{kind}.cred"
                        if (credential_path.parent == credential_store.root
                                and credential_path.name.startswith(prefix)
                                and credential_path.name.endswith(suffix)):
                            identifier = credential_path.name[len(prefix):-len(suffix)]
                            return credential_store.read(identifier, kind)
                        fd = os.open(credential_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                        try:
                            info = os.fstat(fd)
                            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                                    or info.st_mode & (0o077 if private else 0o022)
                                    or info.st_size > 1024 * 1024):
                                raise APIError("SSH credential file is unsafe")
                            return os.read(fd, 1024 * 1024 + 1)
                        finally:
                            os.close(fd)

                    scp = shutil.which("scp")
                    if not scp:
                        raise APIError("OpenSSH scp is required for this source")
                    key_bytes = read_ssh_material(repo.identity_file, "ssh-key", private=True)
                    known_hosts_bytes = read_ssh_material(repo.known_hosts_file, "known-hosts", private=False)
                    with tempfile.TemporaryDirectory(prefix="feclora-pxe-scp-") as temporary:
                        temporary_root = Path(temporary)
                        key_path = temporary_root / "identity"
                        known_hosts_path = temporary_root / "known_hosts"
                        output_path = temporary_root / "answer.json"
                        key_path.write_bytes(key_bytes)
                        known_hosts_path.write_bytes(known_hosts_bytes)
                        os.chmod(key_path, 0o600)
                        os.chmod(known_hosts_path, 0o600)
                        remote_file = f"{repo.remote_path.rstrip('/')}/{source_path}"
                        command = [
                            scp, "-q", "-B", "-O", "-oBatchMode=yes",
                            "-oStrictHostKeyChecking=yes",
                            f"-oUserKnownHostsFile={known_hosts_path}",
                            "-oIdentitiesOnly=yes", "-oConnectTimeout=10",
                            "-i", str(key_path), "-P", str(repo.port or 22),
                            f"{repo.username}@{repo.host}:{remote_file}",
                            str(output_path),
                        ]
                        result = subprocess.run(
                            command, stdin=subprocess.DEVNULL, capture_output=True,
                            check=False, timeout=20,
                        )
                        if result.returncode != 0:
                            detail = result.stderr.decode("utf-8", errors="replace")[:512]
                            raise APIError(f"SCP answer download failed: {detail or 'remote copy failed'}")
                        info = output_path.lstat()
                        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_ANSWER_BYTES:
                            raise APIError("SCP answer must be a regular file between 1 byte and 64 KiB")
                        raw = output_path.read_bytes()
                finally:
                    os.close(lease_fd)
            else:
                manager = _remote_repository_manager()
                lease_fd = manager.acquire_usage_lock(repository_id)
                try:
                    root = Path(manager.resolve(repository_id))
                    directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                           | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        for component in parts[:-1]:
                            next_fd = os.open(
                                component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd,
                            )
                            os.close(directory_fd)
                            directory_fd = next_fd
                        file_fd = os.open(
                            parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=directory_fd,
                        )
                        try:
                            info = os.fstat(file_fd)
                            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_ANSWER_BYTES:
                                raise APIError("repository answer must be a regular file between 1 byte and 64 KiB")
                            chunks = []
                            remaining = MAX_ANSWER_BYTES + 1
                            while remaining:
                                chunk = os.read(file_fd, min(remaining, 8192))
                                if not chunk:
                                    break
                                chunks.append(chunk)
                                remaining -= len(chunk)
                            raw = b"".join(chunks)
                        finally:
                            os.close(file_fd)
                    finally:
                        os.close(directory_fd)
                finally:
                    os.close(lease_fd)
        except APIError:
            raise
        except Exception as exc:
            raise APIError(f"cannot read answer from the selected managed repository: {exc}") from exc
    else:
        raise APIError("source must be upload, url or repository")
    if not 1 <= len(raw) <= MAX_ANSWER_BYTES:
        raise APIError("answer file must be between 1 byte and 64 KiB")
    return raw



def _import_deployment_job(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch and validate a shared DeploymentJob document from a remote source."""
    if not isinstance(params, dict) or "source" not in params:
        raise APIError("import_deployment_job requires a source")
    source = params.get("source")
    if source not in {"upload", "url", "repository", "scp"}:
        raise APIError("DeploymentJob import supports upload, HTTP(S), repository or SCP sources")
    # Reuse the same bounded, redirect-free, credential-safe readers as PXE
    # publication. The synthetic UUID is only an internal reader parameter;
    # the actual UUID is parsed and validated from the document itself.
    reader_params = {"job_id": "00000000-0000-4000-8000-000000000000", **params}
    raw = _read_pxe_answer_source(reader_params)
    from feclora.deployment.job import DeploymentJob, JobValidationError
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        job = DeploymentJob.from_dict(document)
    except (UnicodeDecodeError, json.JSONDecodeError, JobValidationError, APIError) as exc:
        raise APIError(f"DeploymentJob import validation failed: {exc}") from exc
    return {"job": job.to_dict(), "message": "DeploymentJob downloaded and validated. Review all fields before creating the job."}

def _publish_pxe_answer(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict) or "job_id" not in params or "source" not in params:
        raise APIError("publish_pxe_answer requires job_id and source")
    job_id = _text(params, "job_id", maximum=36)
    raw_answer = _read_pxe_answer_source(params)
    from feclora.network.pxe_answer import parse_pxe_answer, PXEAnswerError
    try:
        validated_answer = parse_pxe_answer(raw_answer)
    except PXEAnswerError as exc:
        raise APIError(f"PXE answer validation failed: {exc}") from exc
    manager = _pxe_service_manager()
    status = manager.status()
    if status.get("active") is not True or not status.get("interface"):
        raise APIError("start and verify the PXE services before publishing an unattended answer")
    config_file = Path("/run/feclora/pxe/Caddyfile")
    try:
        info = os.lstat(config_file)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_size > 8192:
            raise APIError("active Caddy configuration is not a safe root-owned regular file")
        caddy_config = config_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise APIError("active Caddy configuration is unavailable") from exc
    match = re.match(r'^http://([0-9.]+):([0-9]+) \{\n    root \* "(/srv/feclora/http)"\n', caddy_config)
    if not match:
        raise APIError("active Caddy configuration does not use the expected Feclora HTTP document root")
    address, port_text, http_root = match.groups()
    try:
        port = int(port_text)
        parsed_address = ipaddress.ip_address(address)
    except ValueError as exc:
        raise APIError("active Caddy listener address is invalid") from exc
    if parsed_address.version != 4 or not any(
        item["interface"] == status["interface"] and item["address"] == address
        for item in _network_interfaces()
    ):
        raise APIError("active Caddy address is no longer assigned to the PXE interface")
    if validated_answer.get("start_policy") == "automatic":
        from feclora.deployment.runtime_config import load_server_runtime_config
        try:
            server_config = load_server_runtime_config("/etc/feclora/deployment-server.json")
        except Exception as exc:
            raise APIError(f"cannot load Server control endpoint configuration: {exc}") from exc
        if server_config.bind_address != address:
            raise APIError(
                "shared PXE deployment requires the authenticated Server control listener "
                "to use the same address as the PXE answer service"
            )
    if validated_answer.get("start_policy") == "automatic":
        if validated_answer.get("job_id") != job_id:
            raise APIError("published job_id must match the UUID inside the shared DeploymentJob JSON")
        # A shared answer is also the canonical Server job definition. Persist
        # it once and start the existing authenticated control service before
        # publishing the answer that Clients will consume.
        from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
        journal_path = _deployment_journal_directory(create=True) / f"{job_id}.jsonl"
        if journal_path.exists():
            try:
                report = DeploymentJournal.inspect(journal_path).recovery_report()
            except (OSError, DeploymentJournalError) as exc:
                raise APIError(f"cannot inspect existing shared deployment job: {exc}") from exc
            stored = report.get("job")
            incoming = dict(validated_answer)
            stored_compare = dict(stored) if isinstance(stored, dict) else {}
            incoming_compare = dict(incoming)
            stored_compare.pop("staging_required_bytes", None)
            incoming_compare.pop("staging_required_bytes", None)
            if stored_compare != incoming_compare:
                raise APIError("published shared answer does not match the existing Server DeploymentJob")
            if report.get("job_state") != "created" or report.get("interrupted"):
                raise APIError("shared DeploymentJob is not fresh and cannot be started for unattended clients")
        else:
            _create_deployment_job({"job": validated_answer})
        _start_deployment_service({"job_id": job_id})
        try:
            report = DeploymentJournal.inspect(journal_path).recovery_report()
            validated_answer = report["job"]
            raw_answer = (json.dumps(
                validated_answer, sort_keys=True, separators=(",", ":"),
            ) + "\n").encode("utf-8")
        except Exception as exc:
            raise APIError(f"cannot reload canonical shared DeploymentJob for publication: {exc}") from exc
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
        if validated_answer.get("boot_method") == "pxe":
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
        raise APIError(f"PXE answer/boot publication failed: {exc}") from exc
    return {
        "job_id": job_id,
        "answer_url": published["answer_url"],
        **({
            "boot_script_url": f"http://{address}:{port}/unattended-answer.ipxe",
        } if validated_answer.get("boot_method") == "pxe" else {}),
        "message": "One shared answer validated and published over HTTP for every authorized Live Client. PXE boot-script publication is optional and depends on boot_method.",
    }



def _pxe_age_passphrase_status(params: dict[str, Any]) -> dict[str, Any]:
    if params:
        raise APIError("pxe_age_passphrase_status does not accept parameters")
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="ascii")
    except OSError as exc:
        raise APIError("cannot verify PXE Live boot mode") from exc
    if "feclora.pxe_mode=unattended-answer" not in cmdline.split():
        return {"available": False, "waiting": False, "submitted": False}
    directory = Path("/run/feclora/pxe")
    marker = directory / "age-passphrase-needed"
    try:
        root_info = os.lstat(directory)
        if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
                or root_info.st_uid != 0 or root_info.st_mode & 0o077):
            raise APIError("PXE Live runtime directory is not secure")
        marker_info = os.lstat(marker)
    except FileNotFoundError:
        return {"available": True, "waiting": False, "submitted": False}
    if (not stat.S_ISREG(marker_info.st_mode) or stat.S_ISLNK(marker_info.st_mode)
            or marker_info.st_uid != 0 or marker_info.st_mode & 0o077):
        raise APIError("PXE age passphrase request marker is unsafe")
    try:
        os.lstat(directory / "age-passphrase")
        submitted = True
    except FileNotFoundError:
        submitted = False
    return {"available": True, "waiting": not submitted, "submitted": submitted}


def _provide_pxe_age_passphrase(params: dict[str, Any]) -> dict[str, Any]:
    """Submit a one-shot symmetric age passphrase to the local PXE Live worker."""
    if set(params) != {"passphrase"}:
        raise APIError("provide_pxe_age_passphrase requires exactly passphrase")
    passphrase = params.get("passphrase")
    if (not isinstance(passphrase, str) or not passphrase
            or len(passphrase.encode("utf-8")) > 1024
            or any(char in passphrase for char in "\r\n\x00")):
        raise APIError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="ascii")
    except OSError as exc:
        raise APIError("cannot verify PXE Live boot mode") from exc
    if "feclora.pxe_mode=unattended-answer" not in cmdline.split():
        raise APIError("age passphrases can only be submitted on an unattended PXE Live client")
    directory = Path("/run/feclora/pxe")
    marker = directory / "age-passphrase-needed"
    temporary = None
    try:
        info = os.lstat(directory)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o077):
            raise APIError("PXE Live runtime directory is not secure")
        marker_info = os.lstat(marker)
        if (not stat.S_ISREG(marker_info.st_mode) or stat.S_ISLNK(marker_info.st_mode)
                or marker_info.st_uid != 0 or marker_info.st_mode & 0o077):
            raise APIError("PXE Live worker is not waiting for an age passphrase")
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
        raise APIError("an age passphrase is already pending; wait for the restore worker") from exc
    except FileNotFoundError as exc:
        raise APIError("the PXE restore worker is not currently waiting for an age passphrase") from exc
    except APIError:
        raise
    except OSError as exc:
        raise APIError(f"cannot submit age passphrase to PXE Live: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _revoke_pxe_answer(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id"}:
        raise APIError("revoke_pxe_answer requires exactly job_id")
    job_id = _text(params, "job_id", maximum=36)
    from feclora.network.pxe_answer_store import revoke_pxe_answer
    from feclora.network.boot_tree import revoke_unattended_answer_ipxe_script
    try:
        revoke_unattended_answer_ipxe_script("/srv/feclora/http", job_id)
        revoked = revoke_pxe_answer("/srv/feclora/http", job_id)
    except Exception as exc:
        raise APIError(f"PXE answer revocation failed: {exc}") from exc
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
        "recover_disk": {"source", "image_id", "retry_passes", "resume", "repository_id"},
        "finalize_recovery": {"job_id", "repository_id"},
        "capture_stratis_filesystem": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_proportional_disk": {"image_id", "source", "target", "source_major_minor", "target_major_minor", "confirmation", "repository_id"},
        "execute_restore_profile": {"profile_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "restore_stratis_filesystem": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
        "capture_p2v": {"source", "image_id", "repository_id"},
        "import_p2v": {"source_image_id", "image_id", "repository_id"},
        "export_p2v_s3": {"image_id", "source_repository_id", "destination_repository_id"},
        "build_recovery_iso": {"base_iso_path", "image_id", "target_wwn", "target_serial", "confirm_build", "repository_id"},
        "build_deployment_bundle": {"base_iso_path", "image_id", "deployment_job", "bundle_name", "repository_id"},
    }
    if action not in allowed:
        raise APIError("operation parameters do not match the selected operation")
    allowed_params = allowed[action]
    if action == "export_p2v_s3":
        accepted_params = (allowed_params, allowed_params - {"destination_repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if action == "capture_disk":
        accepted_params = accepted_params + tuple(item - {"age_passphrase"} for item in accepted_params)
        accepted_params = accepted_params + tuple(
            item - {"age_passphrase", "encrypt_passphrase"} for item in accepted_params
        )
    if set(params) not in accepted_params:
        raise APIError("operation parameters do not match the selected operation")
    started = time.monotonic()
    _emit({"event": "started", "operation_id": operation_id, "operation": action})
    if action == "build_deployment_bundle":
        from feclora.deployment.job import DeploymentJob, JobValidationError
        from feclora.storage.deployment_bundle import build_deployment_bundle
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        bundle_name = _text(params, "bundle_name", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        base_iso = params.get("base_iso_path")
        if (not isinstance(base_iso, str) or not os.path.isabs(base_iso)
                or os.path.normpath(base_iso) != base_iso or len(base_iso) > 4096
                or not base_iso.lower().endswith(".iso")):
            raise APIError("base_iso_path must be an absolute path to a Live .iso file")
        try:
            job = DeploymentJob.from_dict(params.get("deployment_job"))
        except JobValidationError as exc:
            raise APIError(f"deployment_job is invalid: {exc}") from exc
        repository_id = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}")
        if (job.operation != "restore" or job.image_id != image_id
                or job.repository_id != repository_id or job.start_policy != "automatic"):
            raise APIError("deployment_job must be an automatic restore for the selected image and repository")
        from feclora.storage.s3_repository_manager import S3RepositoryManager
        if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
            raise APIError("deployment bundles require a writable filesystem repository; S3 object storage is not supported")
        params = dict(params)
        params["repository_id"] = repository_id
        with _operation_repository_context(params, write=True, image_id=image_id) as repository:
            manifest_path = _image_manifest(image_id, repository)
            with tempfile.TemporaryDirectory(prefix="feclora-bundle-answer-") as temporary:
                os.chmod(temporary, 0o700)
                answer_path = Path(temporary) / "answer.json"
                fd = os.open(answer_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(job.to_json())
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                output_path = repository / bundle_name
                result = build_deployment_bundle(
                    base_iso, str(repository), str(manifest_path), str(answer_path),
                    str(output_path),
                )
        result["output_directory"] = str(output_path)
    elif action == "build_recovery_iso":
        from feclora.storage.recovery_iso import build_recovery_iso
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        base_iso = params.get("base_iso_path")
        if (not isinstance(base_iso, str) or not os.path.isabs(base_iso)
                or os.path.normpath(base_iso) != base_iso or len(base_iso) > 4096
                or not base_iso.lower().endswith(".iso")):
            raise APIError("base_iso_path must be an absolute path to a Live .iso file")
        if params.get("confirm_build") != f"BUILD {image_id}":
            raise APIError("recovery ISO build confirmation does not match the selected image")
        target_wwn = params.get("target_wwn")
        target_serial = params.get("target_serial")
        if target_wwn is not None and (not isinstance(target_wwn, str) or not target_wwn or len(target_wwn) > 128):
            raise APIError("target_wwn is invalid")
        if target_serial is not None and (not isinstance(target_serial, str) or not target_serial or len(target_serial) > 128):
            raise APIError("target_serial is invalid")
        if target_wwn is None and target_serial is None:
            raise APIError("recovery ISO requires a target WWN and/or serial selector")
        repository_id = params.get("repository_id")
        if repository_id is not None:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
                raise APIError("recovery ISO output requires a writable filesystem repository; S3 object storage is not supported")
        repository = _operation_repository(params, write=True, create_local=True)
        manifest_path = _image_manifest(image_id, repository)
        output_path = repository / f"{image_id}.recovery.iso"
        if os.path.lexists(output_path):
            raise APIError("recovery ISO output already exists; choose another image identifier or move the existing file")
        answer = {
            "schema_version": 1, "operation": "restore", "image_id": image_id,
            "target": {"wwn": target_wwn, "serial": target_serial},
            "confirm_destructive": True, "start": True,
        }
        temporary_directory = tempfile.mkdtemp(prefix=".feclora-recovery-answer-", dir=repository)
        os.chmod(temporary_directory, 0o700)
        answer_path = Path(temporary_directory) / "answer.json"
        try:
            fd = os.open(answer_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(answer, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            result = build_recovery_iso(
                base_iso, str(repository), str(manifest_path), str(answer_path),
                str(output_path),
            )
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)
        result["output_path"] = str(output_path)
    elif action == "capture_disk":
        from feclora.storage.disk_capture import capture_disk
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        image_format = params.get("image_format", "raw")
        if not isinstance(image_format, str) or image_format not in {"raw", "qcow2"}:
            raise APIError("whole-disk image_format must be raw or qcow2")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise APIError("encrypt must be a boolean value")
        symmetric = params.get("encrypt_passphrase", False)
        if not isinstance(symmetric, bool) or (symmetric and not encrypt):
            raise APIError("encrypt_passphrase must be boolean and requires encrypt=true")
        if image_format == "qcow2" and (compression != "none" or encrypt or symmetric):
            raise APIError("QCOW2 images cannot use separate compression or age encryption")
        security = _security_material()
        if encrypt and symmetric:
            if not shutil.which("age"):
                raise APIError("age executable is required for passphrase encryption")
        elif encrypt and not security["age_encryption_available"]:
            raise APIError("initialize Feclora age recipient keys before enabling recipient encryption")
        recipients_file = _capture_material()
        passphrase = params.get("age_passphrase")
        if symmetric and not isinstance(passphrase, str):
            raise APIError("the one-shot capture passphrase was not delivered to the worker")
        if not symmetric and passphrase is not None:
            raise APIError("unexpected passphrase for recipient-based encryption")
        with _operation_repository_context(
            params, write=True, create_local=True, upload_image_id=image_id,
        ) as repository:
            if image_format == "qcow2":
                from feclora.storage.qcow2_disk_capture import capture_qcow2_disk
                manifest = capture_qcow2_disk(source, image_id, repository)
            else:
                manifest = capture_disk(
                    source, image_id, repository, compression=compression,
                    progress_callback=_progress,
                    age_recipients_file=recipients_file if encrypt and not symmetric else None,
                    age_passphrase=passphrase if symmetric else None,
                )
        result = {
            "image_id": manifest.image_id, "image_type": manifest.image_type,
            "image_format": next(item.format for item in manifest.artifacts if item.role == "disk-image"),
        }
    elif action == "recover_disk":
        from feclora.storage.ddrescue_recovery import recover_block_device, DdrescueRecoveryError
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        retry_passes = params.get("retry_passes", 3)
        resume = params.get("resume", False)
        if isinstance(retry_passes, bool) or not isinstance(retry_passes, int) or not 0 <= retry_passes <= 10:
            raise APIError("retry_passes must be an integer between 0 and 10")
        if not isinstance(resume, bool):
            raise APIError("resume must be a boolean")
        inventory = collect_inventory()
        matches = [
            item for item in inventory.get("devices", [])
            if isinstance(item, dict) and item.get("path") == source and item.get("type") == "disk"
        ]
        if len(matches) != 1:
            raise APIError("recovery source must identify exactly one inventoried whole disk")
        device = matches[0]
        size = device.get("size_bytes")
        major_minor = device.get("major_minor")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise APIError("recovery source size is unknown")
        if not isinstance(major_minor, str) or not re.fullmatch(r"[0-9]+:[0-9]+", major_minor):
            raise APIError("recovery source has no stable kernel device identity")
        wwn, serial = device.get("wwn"), device.get("serial")
        if isinstance(wwn, str) and re.fullmatch(r"[A-Za-z0-9_.:+/-]{1,240}", wwn):
            identity = f"wwn:{wwn}"
        elif isinstance(serial, str) and re.fullmatch(r"[A-Za-z0-9_.:+/-]{1,240}", serial):
            identity = f"serial:{serial}"
        else:
            identity = f"major_minor:{major_minor}"
        lsblk = shutil.which("lsblk")
        if not lsblk:
            raise APIError("lsblk is required to record recovery disk geometry")
        try:
            geometry_result = subprocess.run(
                [lsblk, "--json", "--bytes", "--nodeps", "--output", "SIZE,LOG-SEC,PTTYPE,MAJ:MIN", source],
                check=True, capture_output=True, text=True, timeout=10,
            )
            geometry_devices = json.loads(geometry_result.stdout).get("blockdevices", [])
            if len(geometry_devices) != 1 or not isinstance(geometry_devices[0], dict):
                raise ValueError("lsblk did not return exactly one source disk")
            geometry_device = geometry_devices[0]
            geometry_size = geometry_device.get("size")
            geometry_major_minor = geometry_device.get("maj:min")
            sector_size = geometry_device.get("log-sec")
            pttype = str(geometry_device.get("pttype") or "").lower()
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise APIError(f"cannot record recovery disk geometry: {exc}") from exc
        if (isinstance(geometry_size, bool) or not isinstance(geometry_size, int)
                or geometry_size != size or geometry_major_minor != major_minor):
            raise APIError("recovery source geometry or kernel identity changed during preflight")
        if isinstance(sector_size, bool) or not isinstance(sector_size, int) or sector_size not in {512, 4096}:
            raise APIError("recovery source logical sector size is unavailable or unsupported")
        partition_table = {"gpt": "gpt", "dos": "mbr", "mbr": "mbr", "": "none"}.get(pttype, "unknown")
        repository_id = params.get("repository_id")
        if repository_id is not None:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
                raise APIError("ddrescue recovery requires a writable filesystem repository; S3 is not supported")
        with _operation_repository_context(
            {"repository_id": repository_id}, write=True, create_local=True,
        ) as repository:
            try:
                recovered = recover_block_device(
                    source, image_id, repository, source_size_bytes=size,
                    source_identity=identity, logical_sector_size=sector_size,
                    partition_table=partition_table,
                    retry_passes=retry_passes, resume=resume,
                    progress_callback=_progress,
                )
            except DdrescueRecoveryError as exc:
                raise APIError(f"disk recovery failed: {exc}") from exc
        if recovered.state != "completed":
            remaining = (
                recovered.summary.non_tried_bytes + recovered.summary.non_trimmed_bytes
                + recovered.summary.non_scraped_bytes + recovered.summary.bad_sector_bytes
            )
            raise APIError(
                f"recovery is {recovered.state}; {remaining} bytes remain unresolved, "
                f"and the partial image/mapfile were retained at {recovered.mapfile_path}; "
                "select resume to continue this job"
            )
        result = {
            "job_id": recovered.job_id, "state": recovered.state,
            "source_size_bytes": size, "rescued_bytes": recovered.summary.rescued_bytes,
            "non_tried_bytes": recovered.summary.non_tried_bytes,
            "non_trimmed_bytes": recovered.summary.non_trimmed_bytes,
            "non_scraped_bytes": recovered.summary.non_scraped_bytes,
            "bad_sector_bytes": recovered.summary.bad_sector_bytes,
            "mapfile": recovered.mapfile_path, "recovery_image": recovered.image_path,
        }
    elif action == "finalize_recovery":
        from feclora.storage.recovery_finalize import finalize_recovery_job, RecoveryFinalizeError
        job_id = _text(params, "job_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        repository_id = params.get("repository_id")
        if repository_id is not None:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
                raise APIError("recovery finalization requires a writable filesystem repository; S3 is not supported")
        with _operation_repository_context(
            {"repository_id": repository_id}, write=True, create_local=True,
        ) as repository:
            try:
                manifest = finalize_recovery_job(job_id, repository)
            except RecoveryFinalizeError as exc:
                raise APIError(f"recovery finalization failed: {exc}") from exc
        result = {
            "job_id": job_id, "image_id": manifest.image_id,
            "image_type": manifest.image_type, "artifact_count": len(manifest.artifacts),
            "finalized": True,
        }
    elif action == "capture_partition":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.partition_image_capture import capture_partition_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        partition_id = _text(params, "partition_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise APIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise APIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        with _operation_repository_context(
            params, write=True, create_local=True, upload_image_id=image_id,
        ) as repository:
            manifest = capture_partition_image(
                source, image_id, partition_id, repository,
                compression=compression, progress_callback=_progress, inventory=inventory,
                age_recipients_file=recipients_file if encrypt else None,
            )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "capture_stratis_filesystem":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.stratis_filesystem_image_capture import capture_stratis_filesystem_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise APIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise APIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        with _operation_repository_context(
            params, write=True, create_local=True, upload_image_id=image_id,
        ) as repository:
            manifest = capture_stratis_filesystem_image(
                source, image_id, repository, inventory,
                compression=compression, progress_callback=_progress,
                age_recipients_file=recipients_file if encrypt else None,
            )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "capture_stratis_filesystem":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.stratis_filesystem_image_capture import capture_stratis_filesystem_image
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        compression = _text(params, "compression", pattern=r"(?:none|gzip|xz|zstd|lz4)")
        encrypt = params["encrypt"]
        if not isinstance(encrypt, bool):
            raise APIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise APIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        with _operation_repository_context(
            params, write=True, create_local=True, upload_image_id=image_id,
        ) as repository:
            manifest = capture_stratis_filesystem_image(
                source, image_id, repository, inventory,
                compression=compression, progress_callback=_progress,
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
            raise APIError("encrypt must be a boolean value")
        security = _security_material()
        if encrypt and not security["age_encryption_available"]:
            raise APIError("initialize Feclora security keys before enabling age encryption")
        recipients_file = _capture_material()
        inventory = collect_inventory()
        with _operation_repository_context(
            params, write=True, create_local=True, upload_image_id=image_id,
        ) as repository:
            manifest = capture_logical_volume_image(
                source, image_id, repository,
                inventory, compression=compression, progress_callback=_progress,
                age_recipients_file=recipients_file if encrypt else None,
            )
        result = {"image_id": manifest.image_id, "image_type": manifest.image_type}
    elif action == "export_p2v_s3":
        result = _export_p2v_from_s3(params)
    elif action == "import_p2v":
        from feclora.storage.p2v_import import import_p2v_qcow2
        source_image_id = _text(params, "source_image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        repository_id = params.get("repository_id")
        if repository_id is not None:
            repository_id = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
                raise APIError("P2V import requires a filesystem repository; S3 is not supported")
        with _operation_repository_context(
            {"repository_id": repository_id}, write=True, image_id=source_image_id,
        ) as repository:
            manifest = import_p2v_qcow2(repository, source_image_id, image_id)
        result = {
            "image_id": manifest.image_id, "image_type": manifest.image_type,
            "artifact_count": len(manifest.artifacts), "verified": True,
            "repository_path": str(repository),
        }
    elif action == "capture_p2v":
        from feclora.storage.p2v import convert_block_device_to_qcow2
        source = _device(params["source"], "source")
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        repository_id = params.get("repository_id")
        from feclora.storage.s3_repository_manager import S3RepositoryManager
        s3_manager = S3RepositoryManager()
        is_s3 = repository_id is not None and any(item["id"] == repository_id for item in s3_manager.list())
        s3_lease = None
        temporary_context = None
        if is_s3:
            try:
                s3_lease = s3_manager.acquire_usage_lock(repository_id)
                s3_repository = s3_manager.repository(repository_id, progress=_progress)
                if s3_repository.config.read_only:
                    raise APIError("S3 repository is configured read-only")
            except Exception as exc:
                if s3_lease is not None:
                    os.close(s3_lease)
                raise APIError(f"selected S3 repository is not safely available: {exc}") from exc
            temporary_context = tempfile.TemporaryDirectory(prefix="feclora-p2v-s3-")
            repository = Path(temporary_context.name)
            os.chmod(repository, 0o700)
        else:
            repository = _operation_repository(params, write=True, create_local=True)
        output_path = repository / f"{image_id}.qcow2"
        metadata_path = repository / f"{image_id}.p2v.json"
        if os.path.lexists(output_path) or os.path.lexists(metadata_path):
            if temporary_context:
                temporary_context.cleanup()
            if s3_lease is not None:
                os.close(s3_lease)
            raise APIError("P2V image identifier already exists in the selected repository")
        temporary_directory = tempfile.mkdtemp(prefix=".feclora-p2v-publish-", dir=repository)
        os.chmod(temporary_directory, 0o700)
        staged_output = Path(temporary_directory) / f"{image_id}.qcow2"
        try:
            converted = convert_block_device_to_qcow2(source, staged_output)
            digest = hashlib.sha256()
            with staged_output.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            metadata = {
                "schema_version": 1, "image_id": image_id, "format": "qcow2",
                "source_device": source, "virtual_size_bytes": converted["virtual_size_bytes"],
                "logical_sector_size": converted["logical_sector_size"],
                "file_size_bytes": converted["file_size_bytes"], "qcow2_sha256": digest.hexdigest(),
                "verified": True,
                "bootability_note": "QCOW2 conversion preserves disk sectors and partition metadata; guest boot may require driver or initramfs changes.",
            }
            metadata_tmp = Path(temporary_directory) / f"{image_id}.p2v.json"
            with metadata_tmp.open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if is_s3:
                s3_result = s3_repository.publish_p2v(image_id, staged_output, metadata_tmp)
                result = {
                    "image_id": image_id, "repository_id": repository_id, "format": "qcow2",
                    "virtual_size_bytes": converted["virtual_size_bytes"],
                    "file_size_bytes": converted["file_size_bytes"], "sha256": digest.hexdigest(),
                    "verified": bool(s3_result.get("committed")),
                }
            else:
                from feclora.storage.image_publication import publish_image_set
                publish_image_set(
                    repository, temporary_directory,
                    [output_path.name, metadata_path.name],
                )
                result = {
                    "image_id": image_id, "output_path": str(output_path),
                    "virtual_size_bytes": converted["virtual_size_bytes"],
                    "file_size_bytes": converted["file_size_bytes"], "sha256": digest.hexdigest(),
                    "verified": True,
                }
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            if temporary_context:
                temporary_context.cleanup()
            if s3_lease is not None:
                os.close(s3_lease)
    elif action == "extract_partition_image":
        from feclora.storage.disk_image_partition import extract_partition_image
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        selector = _text(params, "selector", maximum=256)
        with _operation_repository_context(
            params, write=True, image_id=image_id, upload_new_images=True,
        ) as repository:
            manifest_path = _image_manifest(image_id, repository)
            try:
                manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise APIError(f"cannot read selected disk image manifest: {exc}") from exc
            if manifest.image_id != image_id or manifest.image_type != "disk":
                raise APIError("partition extraction requires the selected disk image manifest")
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
                raise APIError("age-encrypted disk image requires a configured Client age recipient or local Feclora age identity")
            recipients_file = _capture_material()
            if encrypted and not security["age_encryption_available"]:
                raise APIError("extracting an age-encrypted disk image requires an available age recipient inventory for the new partition image")
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
                raise APIError(f"partition extraction failed: {exc}") from exc
            finally:
                if identity_context:
                    identity_context.cleanup()
            result = {
                "source_image_id": image_id, "image_id": extracted.image_id,
                "image_type": extracted.image_type, "manifest": extracted_manifest,
                "encrypted": any(item.encryption == "age" for item in extracted.artifacts),
            }
    elif action == "execute_restore_profile":
        result = _execute_restore_profile_operation(params)
    elif action == "restore_proportional_disk":
        from feclora.storage.inventory import collect_inventory
        from feclora.storage.proportional_restore_workflow import (
            ProportionalRestoreWorkflowError, require_distinct_block_devices,
            prepare_from_offline_source_disk,
        )
        from feclora.storage.proportional_staging import stage_verified_raw_disk_image
        from feclora.storage.staged_proportional_restore import restore_staged_proportional_image
        from feclora.storage.source_safety import check_capture_source_safe
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        source = _device(params["source"], "source")
        target = _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise APIError(f"explicit confirmation required: {expected}")
        inventory = collect_inventory()
        source_matches = _find_inventory_device(inventory, source, "disk")
        target_matches = _find_inventory_device(inventory, target, "disk")
        if len(source_matches) != 1 or len(target_matches) != 1:
            raise APIError("source and destination must each identify exactly one inventoried whole disk")
        source_disk, target_disk = source_matches[0], target_matches[0]
        try:
            source_identity, target_identity = require_distinct_block_devices(
                source, target,
                source_major_minor=params["source_major_minor"],
                target_major_minor=params["target_major_minor"],
            )
        except ProportionalRestoreWorkflowError as exc:
            raise APIError(str(exc)) from exc
        if source_disk.get("major_minor") != params["source_major_minor"] or target_disk.get("major_minor") != params["target_major_minor"]:
            raise APIError("storage inventory changed since source and destination selection")
        if target_disk.get("read_only"):
            raise APIError("proportional restore destination is read-only")
        source_size = source_disk.get("size_bytes")
        target_size = target_disk.get("size_bytes")
        if (isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0
                or isinstance(target_size, bool) or not isinstance(target_size, int) or target_size <= 0
                or target_size >= source_size):
            raise APIError("proportional restore requires valid capacities and a destination smaller than the source")
        if source_disk.get("logical_sector_size") != target_disk.get("logical_sector_size"):
            raise APIError("source and destination logical sector sizes must match")
        check_capture_source_safe(source)
        check_capture_source_safe(target)
        with _operation_repository_context(params, write=False, image_id=image_id) as repository:
            manifest_path = _image_manifest(image_id, repository)
            try:
                manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise APIError(f"cannot read selected disk image manifest: {exc}") from exc
            if manifest.image_id != image_id or manifest.image_type != "disk":
                raise APIError("proportional restore requires the selected whole-disk image")
            if not any(item.role == "disk-image" and item.format == "raw" for item in manifest.artifacts):
                raise APIError("proportional restore requires a RAW whole-disk artifact")
            if manifest.logical_sector_size != source_disk.get("logical_sector_size"):
                raise APIError("image logical sector size differs from the selected source disk")
            if manifest.source_size_bytes != source_disk.get("size_bytes"):
                raise APIError("selected source disk capacity differs from the verified image")
            encrypted = any(item.encryption == "age" for item in manifest.artifacts)
            identity_paths = []
            server_identity = Path("/etc/feclora/pki/server.age")
            if server_identity.is_file():
                identity_paths.append(server_identity)
            client_config = _client_runtime_config()
            if client_config and client_config.age_identity_file:
                identity_paths.append(Path(client_config.age_identity_file))
            if encrypted and not identity_paths:
                raise APIError("age-encrypted image requires a configured Client or local age identity")
            identity_context = tempfile.TemporaryDirectory(prefix="feclora-proportional-identities-") if encrypted and len(identity_paths) > 1 else None
            try:
                if identity_context:
                    identity_file = Path(identity_context.name) / "identities.txt"
                    identity_file.write_text("\n".join(path.read_text(encoding="ascii").strip() for path in identity_paths) + "\n", encoding="ascii")
                    os.chmod(identity_file, 0o600)
                else:
                    identity_file = identity_paths[0] if encrypted else None
                with stage_verified_raw_disk_image(
                    manifest, repository, staging_root="/var/tmp",
                    age_identity_file=identity_file,
                ) as staged:
                    plans = []
                    def capture_plan(value):
                        plans.extend(value)
                        _emit({"event": "progress", "phase": "preflight",
                               "message": "Filesystem minimum sizes and proportional GPT layout validated",
                               "bytes_done": 0, "bytes_total": staged.size_bytes})
                    prepared = prepare_from_offline_source_disk(
                        staged, source_disk, target_size_bytes=target_disk["size_bytes"],
                        sector_size=manifest.logical_sector_size,
                        plan_callback=capture_plan,
                    )
                    def revalidate_source():
                        latest = collect_inventory()
                        found = _find_inventory_device(latest, source, "disk")
                        if len(found) != 1 or found[0].get("major_minor") != params["source_major_minor"]:
                            raise APIError("source disk identity changed before proportional restore write")
                        if os.stat(source).st_rdev != source_identity:
                            raise APIError("source physical device changed before proportional restore write")
                        check_capture_source_safe(source)
                    digest = restore_staged_proportional_image(
                        prepared, target, sector_size=manifest.logical_sector_size,
                        expected_device_identity=target_identity,
                        confirmation=expected, pre_write_callback=revalidate_source,
                        cancellation_requested=lambda: False,
                    )
            finally:
                if identity_context:
                    identity_context.cleanup()
        result = {
            "image_id": image_id, "source": source, "target": target,
            "source_size_bytes": manifest.source_size_bytes,
            "restored_size_bytes": target_disk["size_bytes"],
            "filesystem_plan": [
                {"node": getattr(item, "node", None),
                 "partuuid": getattr(item, "partuuid", None),
                 "start_sector": getattr(item, "start_sector", None),
                 "size_sectors": getattr(item, "size_sectors", None),
                 "minimum_size_bytes": getattr(item, "minimum_size_bytes", None)}
                for item in plans
            ],
            "sha256": digest, "verified": True,
        }
    elif action in {"restore_disk", "restore_partition", "restore_logical_volume", "restore_stratis_filesystem"}:
        image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
        target = _device(params["target"], "target")
        expected = f"ERASE {target}"
        if params["confirmation"] != expected:
            raise APIError(f"explicit confirmation required: {expected}")
        with _operation_repository_context(params, write=False, image_id=image_id) as repository:
            manifest_path = _image_manifest(image_id, repository)
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
            expected_type = {"restore_disk": "disk", "restore_partition": "partition", "restore_logical_volume": "logical_volume", "restore_stratis_filesystem": "stratis_filesystem"}[action]
            if manifest.image_type != expected_type:
                raise APIError(f"selected image is not a {expected_type} image")
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
                raise APIError("age-encrypted image requires a configured Client age recipient or local Feclora age identity")
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
                elif action == "restore_logical_volume":
                    from feclora.storage.inventory import collect_inventory
                    from feclora.storage.logical_volume_restore import restore_logical_volume
                    restore_logical_volume(
                        manifest_path, repository, target, confirmation=expected,
                        inventory_provider=collect_inventory,
                        progress_callback=_progress, age_identity_file=identity_file,
                    )
                else:
                    from feclora.storage.inventory import collect_inventory
                    from feclora.storage.stratis_filesystem_restore import restore_stratis_filesystem_image
                    restore_stratis_filesystem_image(
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
            raise APIError(f"explicit confirmation required: {expected}")
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
            raise APIError(f"explicit confirmation required: {expected}")
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
            raise APIError("deployment runtime directory is unsafe")
        fd = os.open(
            runtime_directory / "deployment.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            os.close(fd)
            raise APIError("deployment operation lock file is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise APIError("another Server, Client or local storage operation is active on this host") from exc
        try:
            from feclora.deployment.service import recover_stale_runtime_artifacts
            recover_stale_runtime_artifacts(lock_held=True)
        except Exception:
            os.close(fd)
            raise
    except APIError:
        raise
    except OSError as exc:
        raise APIError(f"cannot acquire host-wide storage operation lock: {exc}") from exc
    try:
        yield
    finally:
        os.close(fd)


def _local_operation_store():
    from feclora.storage.local_operations import LocalOperationStore
    return LocalOperationStore("/var/lib/feclora/local-operations")


def _submit_local_operation(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation", "operation_params"}:
        raise APIError("submit_local_operation requires operation and operation_params")
    operation, operation_params = params["operation"], params["operation_params"]
    if not isinstance(operation, str) or not isinstance(operation_params, dict):
        raise APIError("operation must be a string and operation_params must be an object")
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
        raise APIError(f"cannot persist local operation: {exc}") from exc
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
        raise APIError(f"local operation was persisted but its worker could not be started: {exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "systemd rejected the operation").strip()[:384]
        try:
            store.append(operation_id, "failed", {"error": message})
        except Exception:
            pass
        raise APIError(f"local operation was persisted but its worker could not be started: {message}")
    return {"operation_id": operation_id, "state": "queued", "unit": unit}


def _provide_capture_passphrase(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id", "passphrase"}:
        raise APIError("provide_capture_passphrase requires operation_id and passphrase")
    operation_id = params["operation_id"]
    if not isinstance(operation_id, str):
        raise APIError("operation_id must be a UUID")
    try:
        store = _local_operation_store()
        definition = store.definition(operation_id)
        report = store.status(operation_id)
        if (definition["action"] != "capture_disk"
                or not definition["params"].get("encrypt_passphrase")
                or report["state"] not in {"queued", "preflight", "running"}):
            raise APIError("operation is not awaiting a passphrase-encrypted disk capture")
        from feclora.storage.capture_passphrase import provide
        provide(operation_id, params["passphrase"])
        return {"operation_id": operation_id, "provided": True}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"cannot deliver one-shot capture passphrase: {exc}") from exc


def _cancel_local_operation(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id"} or not isinstance(params["operation_id"], str):
        raise APIError("cancel_local_operation requires one operation_id")
    try:
        store = _local_operation_store()
        operation_id = params["operation_id"]
        report = store.status(operation_id)
        state = report["state"]
        if state == "cancelled":
            return {"operation_id": operation_id, "state": state, "requested": False}
        if state in {"completed", "failed", "interrupted", "verifying"}:
            raise APIError(f"operation in state {state} cannot be cancelled")
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
            raise APIError(f"operation in state {state} cannot be cancelled")
        unit = f"feclora-local-operation@{operation_id}.service"
        result = subprocess.run(
            ["/usr/bin/systemctl", "stop", "--no-block", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=10,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "systemd rejected the cancellation request").strip()[:384]
            raise APIError(f"cannot request operation cancellation: {message}")
        return {"operation_id": operation_id, "state": state, "requested": True}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"cannot cancel local operation: {exc}") from exc


def _local_operation_status(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation_id"} or not isinstance(params["operation_id"], str):
        raise APIError("local_operation_status requires one operation_id")
    try:
        return _local_operation_store().status(params["operation_id"])
    except Exception as exc:
        raise APIError(f"cannot read local operation status: {exc}") from exc


_PXE_OPERATION_LOG_PATH = Path("/var/lib/feclora/pxe/operations.jsonl")


def _pxe_local_operations(limit: int) -> list[dict[str, Any]]:
    path = _PXE_OPERATION_LOG_PATH
    fd = None
    try:
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise APIError(f"cannot safely open PXE operation journal: {exc}") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077):
            raise APIError("PXE operation journal must be a private service-owned regular file")
        if info.st_size > 2 * 1024 * 1024:
            raise APIError("PXE operation journal exceeds the API read limit")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = None
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw.encode("utf-8")) > 2 * 1024 * 1024:
            raise APIError("PXE operation journal exceeds the API read limit")
    finally:
        if fd is not None:
            os.close(fd)
    records = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("operation") == "restore_disk":
            records.append(event)
    from feclora.storage.operation_log import reconcile_interrupted
    records = reconcile_interrupted(records)
    grouped: dict[str, dict[str, Any]] = {}
    state_map = {
        "started": "running", "progress": "running", "completed": "completed",
        "failed": "failed", "cancelled": "cancelled", "interrupted": "interrupted",
    }
    for event in records:
        operation_id = event.get("operation_id")
        state = state_map.get(event.get("status"))
        if not isinstance(operation_id, str) or state is None:
            continue
        details = {
            key: value for key, value in event.items()
            if key not in {
                "operation_id", "operation", "timestamp", "status",
                "pid", "boot_id", "process_start_ticks",
            }
        }
        if isinstance(event.get("recovery_note"), str):
            details["reason"] = event["recovery_note"][:512]
        item = grouped.setdefault(operation_id, {
            "operation_id": operation_id,
            "action": "pxe_restore_disk",
            "state": state,
            "cancellable": False,
            "events": [],
        })
        if not (event.get("status") == "progress" and item["state"] == "interrupted"):
            item["state"] = state
        item["events"].append({
            "state": "progress" if event.get("status") == "progress" else state,
            "timestamp": event.get("timestamp"),
            "details": details,
        })
    result = list(grouped.values())
    result.sort(
        key=lambda item: str(item["events"][-1].get("timestamp") or ""),
        reverse=True,
    )
    return result[:limit]


def _pxe_remote_operations(limit: int) -> list[dict[str, Any]]:
    """Read bounded, client-asserted PXE reports received by the Server."""
    path = Path("/var/lib/feclora/pxe/remote-reports.jsonl")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise APIError(f"cannot safely open PXE remote report journal: {exc}") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o077 or info.st_size > 8 * 1024 * 1024):
            raise APIError("PXE remote report journal is unsafe or exceeds 8 MiB")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = None
            raw = stream.read(8 * 1024 * 1024 + 1)
    finally:
        if fd is not None:
            os.close(fd)
    grouped: dict[str, dict[str, Any]] = {}
    states = {
        "started": "running", "progress": "running", "completed": "completed",
        "failed": "failed", "cancelled": "cancelled",
    }
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (not isinstance(event, dict) or event.get("operation") != "restore_disk"
                or event.get("status") not in states
                or not isinstance(event.get("operation_id"), str)
                or not isinstance(event.get("client_mac"), str)
                or not isinstance(event.get("job_id"), str)):
            continue
        operation_id = event["operation_id"] + "@" + event["client_mac"]
        state = states[event["status"]]
        details = {
            key: value for key, value in event.items()
            if key not in {"event_id", "operation_id", "operation", "timestamp",
                           "status", "received_at", "pid", "boot_id",
                           "process_start_ticks"}
        }
        item = grouped.setdefault(operation_id, {
            "operation_id": operation_id,
            "action": "pxe_remote_restore_disk",
            "state": state,
            "cancellable": False,
            "events": [],
        })
        item["state"] = state
        item["events"].append({
            "state": "progress" if event["status"] == "progress" else state,
            "timestamp": event.get("timestamp"),
            "details": details,
        })
    result = list(grouped.values())
    result.sort(
        key=lambda item: str(item["events"][-1].get("timestamp") or ""),
        reverse=True,
    )
    return result[:limit]


def _local_operations(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) - {"limit"}:
        raise APIError("local_operations accepts only an optional limit")
    limit = params.get("limit", 100)
    try:
        local_operations, inspection_errors = _local_operation_store().list_with_errors(limit=limit)
        operations = list(local_operations)
        operations.extend(_pxe_local_operations(limit))
        operations.extend(_pxe_remote_operations(limit))
        operations.sort(
            key=lambda item: str(
                (item.get("events") or [{}])[-1].get("timestamp") or ""
            ),
            reverse=True,
        )
        return {"operations": operations[:limit], "inspection_errors": inspection_errors}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"cannot read local operation history: {exc}") from exc


def _run_operation(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id"},
        "recover_disk": {"source", "image_id", "retry_passes", "resume", "repository_id"},
        "finalize_recovery": {"job_id", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
        "export_p2v_s3": {"image_id", "source_repository_id", "destination_repository_id"},
    }
    if action not in operation_fields:
        raise APIError("operation parameters do not match the selected operation")
    allowed_params = operation_fields[action]
    if action == "export_p2v_s3":
        accepted_params = (allowed_params, allowed_params - {"destination_repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if set(params) not in accepted_params:
        raise APIError("operation parameters do not match the selected operation")
    with _storage_operation_lock():
        return _run_operation_locked(action, params)


def _run_operation_locked(action: str, params: dict[str, Any]) -> dict[str, Any]:
    operation_fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id"},
        "recover_disk": {"source", "image_id", "retry_passes", "resume", "repository_id"},
        "finalize_recovery": {"job_id", "repository_id"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
        "export_p2v_s3": {"image_id", "source_repository_id", "destination_repository_id"},
    }
    if action not in operation_fields:
        raise APIError("operation parameters do not match the selected operation")
    allowed_params = operation_fields[action]
    if action == "export_p2v_s3":
        accepted_params = (allowed_params, allowed_params - {"destination_repository_id"})
    else:
        accepted_params = (allowed_params, allowed_params - {"repository_id"})
    if set(params) not in accepted_params:
        raise APIError("operation parameters do not match the selected operation")
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
        raise APIError("deployment journal directory is unavailable") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise APIError("deployment journal directory must be a private root-owned real directory")
    return directory


def _inspect_remote_job(params: dict[str, Any]) -> dict[str, Any]:
    allowed = ({"host", "job_id"}, {"host", "job_id", "network_interface", "source_address"})
    if set(params) not in allowed:
        raise APIError("remote job inspection requires host/job_id and an optional local interface/source address pair")
    network_interface = params.get("network_interface")
    source_address = params.get("source_address")
    if (network_interface is None) != (source_address is None):
        raise APIError("network_interface and source_address must be supplied together")
    if network_interface is not None:
        from feclora.network.interface_discovery import discover_interface_addresses
        try:
            discovered = discover_interface_addresses(network_interface)
            matches = [item for item in discovered if item.address == source_address]
            if len(matches) != 1:
                raise APIError("selected source address is not assigned to the selected Client interface")
        except APIError:
            raise
        except Exception as exc:
            raise APIError(f"cannot validate selected Client interface/address: {exc}") from exc
    host = params["host"]
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise APIError("job_id must be a canonical UUID")
    from feclora.deployment.runtime_config import load_client_runtime_config
    from feclora.deployment.control import DeploymentControlError, inspect_deployment_job
    from feclora.network.remote_clone_protocol import create_tls_context
    try:
        config = load_client_runtime_config("/etc/feclora/deployment-client.json")
    except Exception as exc:
        raise APIError(f"Client deployment identity is not configured: {exc}") from exc
    if host == "":
        host = config.host
    if (not isinstance(host, str) or not host or len(host) > 253
            or any(ord(char) < 33 for char in host)):
        raise APIError("Server host must be a hostname or address without whitespace")
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
        raise APIError(f"could not inspect Server job: {exc}") from exc
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
        raise APIError(f"cannot prepare private Client job directory: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise APIError("Client job directory must be a private root-owned real directory")
    return directory


def _client_job_paths(job_id: str) -> tuple[Path, Path]:
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise APIError("job_id must be a canonical UUID")
    directory = _client_job_directory()
    return directory / f"{job_id}.request.json", directory / f"{job_id}.status.json"


def _write_client_job_request(path: Path, value: dict[str, Any]) -> None:
    if os.path.lexists(path):
        raise APIError("a Client job request already exists for this UUID")
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
            raise APIError("a Client job request already exists for this UUID") from exc
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
        raise APIError("Client job service has not published a status record yet") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 16384):
        raise APIError("Client job status file is unsafe")
    try:
        fd = os.open(status_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0
                    or opened.st_mode & 0o077
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise APIError("Client job status file changed during inspection")
            value = json.loads(os.read(fd, 16385).decode("utf-8"))
        finally:
            os.close(fd)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise APIError(f"cannot read Client job status: {exc}") from exc
    if (not isinstance(value, dict) or value.get("job_id") != job_id
            or value.get("schema_version") != 1
            or value.get("phase") not in {"connecting", "ready", "running", "completed", "failed", "cancelled", "interrupted"}
            or not isinstance(value.get("detail", ""), str)):
        raise APIError("Client job status has an invalid schema or does not match the requested UUID")
    return value


def _start_client_job(params: dict[str, Any]) -> dict[str, Any]:
    required = {"host", "job_id", "device_path", "confirmation", "compression"}
    optional = {"network_interface", "source_address", "igmp_confirmed", "image_encrypt"}
    if not required.issubset(params) or set(params) - required - optional:
        raise APIError("start_client_job requires host, job_id, device_path, confirmation and compression, with optional network and per-image security choices")
    image_encrypt = params.get("image_encrypt", False)
    if not isinstance(image_encrypt, bool):
        raise APIError("per-image encryption choice must be boolean")
    network_interface = params.get("network_interface")
    source_address = params.get("source_address")
    if source_address is not None and network_interface is None:
        raise APIError("source_address requires a selected network_interface")
    inspection_params = {"host": params["host"], "job_id": params["job_id"]}
    if network_interface is not None and source_address is not None:
        inspection_params.update(network_interface=network_interface, source_address=source_address)
    inspection = _inspect_remote_job(inspection_params)
    job = inspection["job"]
    if job["operation"] != "save" and image_encrypt:
        raise APIError("per-image encryption choice is valid only for Client save jobs")
    if image_encrypt:
        from feclora.deployment.runtime_config import load_client_runtime_config
        config = load_client_runtime_config("/etc/feclora/deployment-client.json")
        if not config.age_recipients_file or not os.path.isfile(config.age_recipients_file) or not shutil.which("age"):
            raise APIError("age encryption was selected but this Client has no usable age recipient inventory or age executable")
    igmp_confirmed = params.get("igmp_confirmed", False)
    multicast_preflight = None
    if job["transport"] == "unicast" and (network_interface is None or source_address is None):
        raise APIError("unicast Client jobs require a selected interface and source IPv4 address")
    if job["transport"] == "multicast":
        if igmp_confirmed is not True:
            raise APIError("explicitly confirm IGMP snooping and an active querier on the deployment VLAN")
        if job["operation"] != "restore":
            raise APIError("multicast Client execution supports restore jobs only")
        if not isinstance(network_interface, str) or network_interface not in {
            name for _index, name in socket.if_nameindex()
        }:
            raise APIError("select a local multicast receive interface")
        from feclora.network.multicast_preflight import inspect_multicast_interface
        try:
            multicast_preflight = inspect_multicast_interface(
                network_interface, job["multicast_group"], role="receiver",
            )
        except Exception as exc:
            raise APIError(f"multicast receive interface preflight failed: {exc}") from exc
    elif igmp_confirmed is not False:
        raise APIError("IGMP acknowledgement is only valid for multicast Client jobs")
    device_path = params["device_path"]
    confirmation = params["confirmation"]
    compression = params["compression"]
    if (not isinstance(device_path, str) or not device_path.startswith("/dev/")
            or len(device_path) > 256 or os.path.normpath(device_path) != device_path):
        raise APIError("selected local target path is invalid")
    if not isinstance(confirmation, str) or len(confirmation) > 512:
        raise APIError("local target confirmation is invalid")
    if not isinstance(compression, str) or compression not in {"none", "gzip", "xz"}:
        raise APIError("compression must be none, gzip or xz")
    expected_confirmation = (
        f"ERASE {device_path}"
        if job["operation"] == "restore"
        else f"READ {device_path}"
    )
    if confirmation != expected_confirmation:
        raise APIError("local typed confirmation does not match the selected device")
    from feclora.storage.inventory import collect_inventory
    inventory = collect_inventory()
    matches = []
    if job["target_type"] == "logical_volume":
        topology = inventory.get("volume_topology", {})
        if topology.get("status") != "available":
            raise APIError("local LVM topology is unavailable")
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
        raise APIError("selected target is not uniquely present in the current local block-device inventory")
    try:
        device_info = os.stat(device_path)
    except OSError as exc:
        raise APIError(f"cannot inspect selected local target: {exc}") from exc
    if not stat.S_ISBLK(device_info.st_mode):
        raise APIError("selected local target is no longer a block device")
    request_path, status_path = _client_job_paths(params["job_id"])
    if os.path.lexists(status_path):
        raise APIError("a status record already exists for this job; interrupted Client jobs are never restarted")
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
        raise APIError(f"could not start persistent Client service: {exc}") from exc
    if result.returncode != 0:
        try:
            request_path.unlink()
        except OSError:
            pass
        detail = (result.stderr or result.stdout or "").strip()
        raise APIError(f"Client service did not start: {detail or result.returncode}")
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
        except APIError as exc:
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
    raise APIError(f"Client service started but did not publish status: {last_error}")


def _client_job_status(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id"}:
        raise APIError("client_job_status requires exactly job_id")
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
        raise APIError("deployment service action requires exactly job_id")
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise APIError("job_id must be a canonical UUID")
    return job_id


def _deployment_service_unit(job_id: str) -> str:
    return "feclora-deployment@" + job_id + ".service"


def _deployment_service_status(job_id: str) -> dict[str, Any]:
    from feclora.deployment.local_control import LocalControlError, local_control_request
    try:
        status = local_control_request("/run/feclora/deployment.sock", "status")
    except (OSError, LocalControlError) as exc:
        raise APIError(f"deployment service IPC is unavailable: {exc}") from exc
    if status.get("job_id") != job_id:
        raise APIError("the active deployment service belongs to a different job")
    return status


def _start_deployment_service(params: dict[str, Any]) -> dict[str, Any]:
    job_id = _deployment_service_job_id(params)
    active_service = _active_deployment_service_status()
    if active_service is not None:
        if active_service.get("job_id") != job_id:
            raise APIError("another deployment job already owns the Server control service")
        return active_service
    from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
    journal_path = _deployment_journal_directory() / f"{job_id}.jsonl"
    try:
        report = DeploymentJournal.inspect(journal_path).recovery_report()
    except (OSError, DeploymentJournalError) as exc:
        raise APIError(f"cannot inspect the requested deployment job journal: {exc}") from exc
    if report.get("job_id") != job_id:
        raise APIError("deployment journal UUID does not match the requested job")
    if report.get("job_state") != "created" or report.get("interrupted"):
        raise APIError("only a fresh, unstarted deployment job can be started from the interface")
    unit = _deployment_service_unit(job_id)
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "start", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError(f"could not start persistent deployment service: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise APIError(f"deployment service did not start: {detail or result.returncode}")
    deadline = time.monotonic() + 10
    last_error = None
    while time.monotonic() < deadline:
        try:
            return _deployment_service_status(job_id)
        except APIError as exc:
            last_error = exc
            time.sleep(0.1)
    raise APIError(f"deployment service started but its local control socket did not become ready: {last_error}")


def _stop_deployment_service(params: dict[str, Any]) -> dict[str, Any]:
    job_id = _deployment_service_job_id(params)
    status = _deployment_service_status(job_id)
    clients = status.get("clients", [])
    if status.get("worker_active") or status.get("job_state") == "running" or any(
        isinstance(client, dict) and client.get("state") == "running" for client in clients
    ):
        raise APIError("cannot stop the service while a deployment worker may be performing storage I/O")
    if status.get("job_state") == "created" and clients:
        raise APIError("cancel the unarmed job before stopping its service while Clients are connected")
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "stop", _deployment_service_unit(job_id)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError(f"could not stop persistent deployment service: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise APIError(f"deployment service did not stop cleanly: {detail or result.returncode}")
    return {"job_id": job_id, "stopped": True,
            "message": "Deployment control service stopped. No interrupted job was resumed."}


def _deployment_service_command(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job_id", "confirmation"}:
        raise APIError(f"{action} requires exactly job_id and confirmation")
    job_id = params["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise APIError("job_id must be a canonical UUID")
    confirmation = params["confirmation"]
    if not isinstance(confirmation, str) or len(confirmation) > 512:
        raise APIError("operator confirmation is invalid")
    from feclora.deployment.local_control import LocalControlError, local_control_request
    try:
        result = local_control_request(
            "/run/feclora/deployment.sock", "arm" if action == "arm_deployment_job" else "cancel",
            {"job_id": job_id, "confirmation": confirmation},
        )
    except (OSError, LocalControlError) as exc:
        raise APIError(f"deployment service rejected the command: {exc}") from exc
    if action == "cancel_deployment_job" and isinstance(result, dict) and result.get("accepted") is True:
        # A cancelled deployment must no longer expose its destructive PXE answer.
        try:
            from feclora.network.pxe_answer_store import revoke_pxe_answer
            revoked = revoke_pxe_answer("/srv/feclora/http", job_id)
        except Exception as exc:
            raise APIError(
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



def _deployment_unit_is_active(job_id: str) -> bool:
    """Fail closed while the job's systemd unit is active or transitioning."""
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value",
             _deployment_service_unit(job_id)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError(f"cannot establish deployment service state: {exc}") from exc
    if result.returncode != 0:
        raise APIError("cannot establish deployment service state; journal reconciliation is blocked")
    state = result.stdout.strip()
    if state in {"active", "activating", "deactivating", "reloading"}:
        return True
    if state in {"inactive", "failed"}:
        return False
    raise APIError(
        f"deployment service has an unknown systemd state ({state or 'empty'}); "
        "journal reconciliation is blocked"
    )


def _reconcile_deployment_job(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.journal import DeploymentJournal, DeploymentJournalError
    if set(params) != {"job_id", "confirmation"}:
        raise APIError("reconcile_deployment_job requires exactly job_id and confirmation")
    job_id = params["job_id"]
    confirmation = params["confirmation"]
    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ):
        raise APIError("job_id must be a canonical UUID")
    if not isinstance(confirmation, str) or len(confirmation) > 96:
        raise APIError("operator reconciliation confirmation is invalid")
    if _deployment_unit_is_active(job_id):
        raise APIError("stop the active deployment service before reconciling its journal")

    directory = _deployment_journal_directory()
    journal_path = directory / f"{job_id}.jsonl"
    if not os.path.lexists(journal_path):
        raise APIError("deployment job journal does not exist")
    try:
        journal = DeploymentJournal.inspect(journal_path)
        if journal.job_id != job_id:
            raise APIError("deployment journal UUID does not match the requested job")
        report = journal.reconcile_after_operator_inspection(confirmation)
    except DeploymentJournalError as exc:
        raise APIError(str(exc)) from exc
    return {
        "job_id": job_id,
        "job_state": report["job_state"],
        "interrupted": report["interrupted"],
        "operator_reconciled": report["operator_reconciled"],
        "message": "Interrupted job closed for audit. No operation was resumed or performed on storage.",
    }


def _create_deployment_job(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"job"} or not isinstance(params["job"], dict):
        raise APIError("create_deployment_job requires exactly one job object")
    from feclora.deployment.job import DeploymentJob, JobValidationError
    from feclora.deployment.journal import DeploymentJournal
    from feclora.deployment.runtime_config import load_server_runtime_config, RuntimeConfigError

    try:
        job = DeploymentJob.from_dict(params["job"])
    except JobValidationError as exc:
        raise APIError(str(exc)) from exc
    if job.transport == "unicast" and len(job.authorized_clients) != 1 and job.operation != "clone":
        raise APIError("persistent unicast save/restore supports exactly one Client per job; clone supports multi-Client fan-out")
    if job.transport == "multicast" and len(job.authorized_clients) < 2:
        raise APIError("multicast restore requires at least two authorized Clients")
    config_path = "/etc/feclora/deployment-server.json"
    try:
        config = load_server_runtime_config(config_path)
    except RuntimeConfigError as exc:
        raise APIError(f"configure the Feclora Server before creating jobs: {exc}") from exc
    if job.boot_method == "pxe" and job.network_interface == "auto":
        # PXE Live retains DHCP on each Client; the Server interface is resolved
        # from its configured bind address by DeploymentService.
        pass
    elif job.network_interface not in {name for _, name in socket.if_nameindex()}:
        raise APIError("selected network interface does not exist")
    if job.transport == "multicast" and job.operation not in {"restore", "clone"}:
        raise APIError("multicast transport supports restore or whole-disk physical clone only")
    if job.operation == "save":
        if job.repository_id is None:
            existing_ids = {item["image_id"] for item in _images()}
        else:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            s3_manager = S3RepositoryManager()
            definition = next((item for item in s3_manager.list() if item["id"] == job.repository_id), None)
            if definition is None:
                raise APIError("selected S3 repository does not exist")
            if definition["read_only"]:
                raise APIError("selected S3 repository is read-only and cannot receive Client captures")
            try:
                existing_ids = {item["image_id"] for item in s3_manager.repository(job.repository_id).list_images()}
            except Exception as exc:
                raise APIError(f"cannot inspect selected S3 repository: {exc}") from exc
        if job.image_id in existing_ids:
            raise APIError("capture image identifier already exists in the selected repository")
    elif job.operation == "clone":
        source = _device(job.source_device, "source_device")
        inventory = collect_inventory()
        expected_source_type = "disk" if job.target_type == "disk" else "part"
        matches = _find_inventory_device(inventory, source, expected_source_type)
        if len(matches) != 1:
            label = "whole disk" if job.target_type == "disk" else "partition"
            raise APIError(f"clone source must be one {label} in the current block-device inventory")
        if matches[0].get("read_only") is not True:
            raise APIError(f"clone source {job.target_type} must already be marked read-only")
        from feclora.storage.source_safety import check_capture_source_safe, SourceSafetyError
        try:
            check_capture_source_safe(source)
        except (SourceSafetyError, OSError) as exc:
            raise APIError(f"clone source {job.target_type} is unsafe or in use: {exc}") from exc
        if job.transport == "multicast":
            try:
                from feclora.network.physical_multicast import build_physical_device_record
                source_identity = build_physical_device_record(matches[0])
                job = replace(
                    job,
                    source_identity_json=json.dumps(
                        source_identity, sort_keys=True, separators=(",", ":"), allow_nan=False,
                    ),
                )
            except Exception as exc:
                raise APIError(
                    f"physical multicast source lacks a complete stable kernel identity: {exc}"
                ) from exc
    else:
        remote_image = None
        manifest = None
        if job.repository_id is not None:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            s3_manager = S3RepositoryManager()
            s3_definition = next(
                (item for item in s3_manager.list() if item["id"] == job.repository_id), None,
            )
            if s3_definition is not None:
                try:
                    remote_image = next(
                        (item for item in s3_manager.repository(job.repository_id).list_images()
                         if item["image_id"] == job.image_id), None,
                    )
                    if remote_image is None:
                        raise APIError("selected image is not available in the S3 repository")
                    expected_type = "disk" if job.target_type == "disk" else "partition"
                    if remote_image["image_type"] != expected_type:
                        raise APIError(f"selected image is not a {expected_type} image")
                    if job.transport == "multicast":
                        job = replace(job, staging_required_bytes=remote_image["artifact_bytes"])
                except APIError:
                    raise
                except Exception as exc:
                    raise APIError(f"cannot validate S3 restore image: {exc}") from exc
            elif job.operation == "save":
                raise APIError("Client capture destination must be an S3 object repository")
            else:
                try:
                    image_repository = Path(_remote_repository_manager().resolve(
                        job.repository_id, write=False,
                    ))
                except Exception as exc:
                    raise APIError(f"selected image repository is not mounted and verified: {exc}") from exc
                manifest_path = _image_manifest(job.image_id, image_repository)
        else:
            image_repository = Path(config.repository)
            manifest_path = _image_manifest(job.image_id, image_repository)
        if remote_image is None:
            try:
                manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
                expected_type = "disk" if job.target_type == "disk" else "partition"
                if manifest.image_type != expected_type:
                    raise APIError(f"selected image is not a {expected_type} image")
                if job.transport == "multicast":
                    job = replace(
                        job,
                        staging_required_bytes=sum(item.size_bytes for item in manifest.artifacts),
                    )
            except APIError:
                raise
            except Exception as exc:
                raise APIError(f"restore image manifest is invalid: {exc}") from exc
        image_is_encrypted = (
            remote_image["encrypted"] if remote_image is not None
            else any(item.encryption == "age" for item in manifest.artifacts)
        )
        if image_is_encrypted:
            pki = Path("/etc/feclora/pki")
            recipients_directory = pki / "age-recipients"
            try:
                pki_info = os.lstat(pki)
                directory_info = os.lstat(recipients_directory)
            except OSError as exc:
                raise APIError("Server age-recipient registry is unavailable") from exc
            if (not stat.S_ISDIR(pki_info.st_mode) or stat.S_ISLNK(pki_info.st_mode)
                    or pki_info.st_uid != 0 or pki_info.st_mode & 0o077
                    or not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                    or directory_info.st_uid != 0 or directory_info.st_mode & 0o077):
                raise APIError("Server age-recipient registry directories are unsafe")
            for mac in job.authorized_clients:
                mapping = recipients_directory / f"{mac.replace(':', '')}.txt"
                try:
                    info = os.lstat(mapping)
                    recipient = mapping.read_text(encoding="ascii").strip()
                except OSError as exc:
                    raise APIError(f"Client {mac} has no registered age recipient") from exc
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                        or info.st_mode & 0o077 or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient)):
                    raise APIError(f"Client {mac} age recipient mapping is unsafe")
    directory = _deployment_journal_directory(create=True)
    journal_path = directory / f"{job.job_id}.jsonl"
    if os.path.lexists(journal_path):
        raise APIError("deployment job UUID already exists")
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
        raise APIError(f"could not persist deployment job: {exc}") from exc
    return {
        "job_id": job.job_id,
        "job_state": coordinator.state.value,
        "authorized_clients": list(job.authorized_clients),
        "journal": str(journal_path),
        "started": False,
        "message": "Job definition persisted. No Client was contacted and no storage operation was started.",
    }



def _export_server_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.recipient_inventory_export import export_server_age_recipients
    try:
        return export_server_age_recipients(params)
    except Exception as exc:
        raise APIError(f"age recipient export failed: {exc}") from exc


def _refresh_client_age_recipients(params: dict[str, Any]) -> dict[str, Any]:
    from feclora.deployment.recipient_inventory_refresh import refresh_client_age_recipients
    try:
        return refresh_client_age_recipients(params)
    except Exception as exc:
        raise APIError(f"Client age recipient refresh failed: {exc}") from exc


def _remote_repository_manager():
    from feclora.storage.repository_manager import RemoteRepositoryManager
    return RemoteRepositoryManager()


def _remote_repository_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        if action == "put_systemd_credential":
            if set(params) != {"id", "kind", "source_file", "replace"}:
                raise APIError("put_systemd_credential requires id, kind, source_file and replace")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            kind = _text(params, "kind", maximum=16)
            from feclora.storage.systemd_credential_store import CREDENTIAL_KINDS, SystemdCredentialStore
            if kind not in CREDENTIAL_KINDS:
                raise APIError("unsupported credential kind")
            source_file = _text(params, "source_file", maximum=512)
            if not isinstance(params["replace"], bool):
                raise APIError("replace must be boolean")
            from feclora.storage.credential_source import read_source_file
            content = read_source_file(source_file)
            return {"credential": SystemdCredentialStore().put(
                identifier, kind, content, replace=params["replace"],
            )}
        if action == "remove_systemd_credential":
            if set(params) != {"id", "kind"}:
                raise APIError("remove_systemd_credential requires id and kind")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            kind = _text(params, "kind", maximum=16)
            from feclora.storage.systemd_credential_store import CREDENTIAL_KINDS, SystemdCredentialStore
            if kind not in CREDENTIAL_KINDS:
                raise APIError("unsupported credential kind")
            store = SystemdCredentialStore()
            if _remote_repository_manager().credential_is_referenced(str(store._path(identifier, kind))):
                raise APIError("credential is still referenced by a saved repository; update or remove that repository first")
            if kind == "s3":
                from feclora.storage.s3_repository_manager import S3RepositoryManager
                if S3RepositoryManager().credential_is_referenced(identifier):
                    raise APIError("credential is still referenced by a saved S3 repository; update or remove that repository first")
            store.remove(identifier, kind)
            return {"removed": True, "id": identifier, "kind": kind}
        if action == "systemd_credentials":
            if params:
                raise APIError("systemd_credentials does not accept parameters")
            from feclora.storage.systemd_credential_store import SystemdCredentialStore
            try:
                return {"credentials": SystemdCredentialStore().list()}
            except Exception as exc:
                raise APIError(f"encrypted credential inventory failed: {exc}") from exc
        if action == "s3_repositories":
            if params:
                raise APIError("s3_repositories does not accept parameters")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            return {"repositories": S3RepositoryManager().list()}
        if action in {"add_s3_repository", "update_s3_repository"}:
            required = {"id", "endpoint_url", "region", "bucket", "prefix", "credential_id", "read_only"}
            if set(params) != required:
                raise APIError("S3 repository definition has missing or unknown fields")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            definition = {key: params[key] for key in required - {"id"}}
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == identifier for item in _remote_repository_manager().list()):
                raise APIError("repository ID is already used by a filesystem repository")
            manager = S3RepositoryManager()
            if action == "add_s3_repository":
                return manager.add(identifier, definition)
            with _storage_operation_lock():
                return manager.update(identifier, definition)
        if action == "check_s3_repository":
            if set(params) != {"id"}:
                raise APIError("check_s3_repository requires exactly id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            return S3RepositoryManager().check(_text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48))
        if action == "remove_s3_repository":
            if set(params) != {"id"}:
                raise APIError("remove_s3_repository requires exactly id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            with _storage_operation_lock():
                return S3RepositoryManager().remove(identifier)
        if action == "s3_repository_images":
            if set(params) != {"repository_id"}:
                raise APIError("s3_repository_images requires repository_id")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            identifier = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            return {"images": S3RepositoryManager().repository(identifier).list_images()}
        if action == "remote_repositories":
            if params:
                raise APIError("remote_repositories does not accept parameters")
            return {"repositories": _remote_repository_manager().list()}
        if action in {"add_remote_repository", "update_remote_repository"}:
            required = {
                "id", "provider", "host", "remote_path", "username",
                "credential_file", "identity_file", "known_hosts_file",
                "port", "read_only",
            }
            if set(params) != required:
                raise APIError("remote repository definition has missing or unknown fields")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            definition = {key: params[key] for key in required - {"id"}}
            for key in ("provider", "host", "remote_path"):
                _text(definition, key, maximum=512)
            for key in ("username", "credential_file", "identity_file", "known_hosts_file"):
                if definition[key] is not None and (
                    not isinstance(definition[key], str) or not definition[key]
                    or len(definition[key]) > 512
                ):
                    raise APIError(f"{key} must be null or a non-empty path/value")
            if definition["port"] is not None and (
                isinstance(definition["port"], bool) or not isinstance(definition["port"], int)
                or not 1 <= definition["port"] <= 65535
            ):
                raise APIError("port must be null or an integer between 1 and 65535")
            if not isinstance(definition["read_only"], bool):
                raise APIError("read_only must be boolean")
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == identifier for item in S3RepositoryManager().list()):
                raise APIError("repository ID is already used by an S3 object repository")
            manager = _remote_repository_manager()
            return manager.add(identifier, definition) if action == "add_remote_repository" else manager.update(identifier, definition)
        if action == "check_remote_repository":
            if set(params) != {"id"}:
                raise APIError("check_remote_repository requires exactly id")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            return _remote_repository_manager().check(identifier)
        if action in {"mount_remote_repository", "unmount_remote_repository", "remove_remote_repository"}:
            if set(params) != {"id"}:
                raise APIError(f"{action} requires exactly id")
            identifier = _text(params, "id", pattern=r"[a-z0-9][a-z0-9-]{0,47}", maximum=48)
            if action == "mount_remote_repository":
                return _remote_repository_manager().mount(identifier)
            if action == "unmount_remote_repository":
                return _remote_repository_manager().unmount(identifier)
            return _remote_repository_manager().remove(identifier)
    except APIError:
        raise
    except Exception as exc:
        raise APIError(f"remote repository operation failed: {exc}") from exc
    raise APIError("unsupported remote repository action")


def _persistent_repository(repository: Path) -> None:
    try:
        info = os.lstat(repository)
    except OSError as exc:
        raise APIError("selected profile repository is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise APIError("restore profiles require a real mounted filesystem repository")
    findmnt = shutil.which("findmnt")
    if not findmnt:
        raise APIError("findmnt is required to verify persistent restore-profile storage")
    try:
        result = subprocess.run(
            [findmnt, "--noheadings", "--output", "FSTYPE,TARGET", "--target", str(repository)],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError(f"cannot verify persistent profile storage: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) < 2:
        raise APIError("findmnt did not identify the restore-profile filesystem")
    filesystem, mountpoint = fields[0].lower(), fields[-1]
    if filesystem in {"overlay", "tmpfs", "ramfs", "rootfs", "squashfs", "devtmpfs"} or mountpoint == "/":
        raise APIError("restore profiles require a dedicated persistent mounted filesystem, not the Live root")


def _restore_profile_directory(repository: Path, *, create: bool = False) -> Path:
    _persistent_repository(repository)
    state = repository / ".feclora"
    directory = state / "restore-profiles"
    if create:
        for path in (state, directory):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
    for path in (state, directory):
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            if not create:
                return directory
            raise APIError("persistent restore-profile directory is unavailable")
        except OSError as exc:
            raise APIError("cannot inspect persistent restore-profile directory") from exc
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o077):
            raise APIError("restore-profile directories must be root-owned and mode 0700")
    return directory


def _profile_repository(params: dict[str, Any], *, write: bool) -> Path:
    if set(params) != {"repository_id"}:
        raise APIError("restore profile action requires a mounted filesystem repository_id")
    repository_id = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}")
    from feclora.storage.s3_repository_manager import S3RepositoryManager
    if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
        raise APIError("restore profiles require persistent mounted filesystem storage; S3 is not supported")
    repository = _operation_repository({"repository_id": repository_id}, write=write)
    _persistent_repository(repository)
    return repository


def _restore_profiles(params: dict[str, Any]) -> dict[str, Any]:
    if not params:
        return {"profiles": [], "storage_available": False}
    repository = _profile_repository(params, write=False)
    directory = _restore_profile_directory(repository)
    profiles = []
    from feclora.storage.restore_profile import load_restore_profile
    inventory = collect_inventory()
    consumed_ids: set[str] = set()
    ledger = repository / ".feclora" / "restore-audit" / "consumed-profiles.jsonl"
    try:
        ledger_info = os.lstat(ledger)
    except FileNotFoundError:
        ledger_info = None
    except OSError as exc:
        raise APIError(f"cannot inspect restore profile consumption ledger: {exc}") from exc
    if ledger_info is not None:
        if (not stat.S_ISREG(ledger_info.st_mode) or stat.S_ISLNK(ledger_info.st_mode)
                or ledger_info.st_uid != 0 or ledger_info.st_mode & 0o077
                or ledger_info.st_size > 8 * 1024 * 1024):
            raise APIError("restore profile consumption ledger has unsafe type, permissions or size")
        try:
            for line_number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
                event = json.loads(line, object_pairs_hook=_reject_duplicates)
                if not isinstance(event, dict) or event.get("status") != "consumed" or not isinstance(event.get("profile_id"), str):
                    raise APIError(f"restore profile consumption ledger is invalid at line {line_number}")
                consumed_ids.add(event["profile_id"])
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise APIError(f"restore profile consumption ledger is corrupt: {exc}") from exc
    for path in sorted(directory.glob("*.json")):
        try:
            profile = load_restore_profile(path)
        except Exception as exc:
            raise APIError(f"restore profile {path.name} is invalid: {exc}") from exc
        matches = [
            device for device in inventory.get("devices", [])
            if isinstance(device, dict) and device.get("type") == "disk" and profile.target.matches(device)
        ]
        profiles.append({
            "profile_id": profile.profile_id, "name": profile.name,
            "image_manifest": profile.image_manifest, "execution_mode": profile.execution_mode,
            "layout_policy": profile.layout_policy, "target": profile.target.to_dict(),
            "target_path": matches[0].get("path") if len(matches) == 1 else None,
            "expires_at": profile.expires_at, "single_use": profile.single_use,
            "consumed": profile.profile_id in consumed_ids,
        })
    return {"profiles": profiles, "storage_available": True}


def _create_restore_profile(params: dict[str, Any]) -> dict[str, Any]:
    required = {"name", "image_id", "target_wwn", "target_serial", "expires_at", "repository_id"}
    if set(params) != required:
        raise APIError("create_restore_profile requires name, image_id, target identity, expiry and repository_id")
    name = _text(params, "name", maximum=80)
    image_id = _text(params, "image_id", pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    wwn, serial = params.get("target_wwn"), params.get("target_serial")
    if wwn is not None and (not isinstance(wwn, str) or not wwn or len(wwn) > 256):
        raise APIError("target_wwn must be a non-empty string or null")
    if serial is not None and (not isinstance(serial, str) or not serial or len(serial) > 256):
        raise APIError("target_serial must be a non-empty string or null")
    if wwn is None and serial is None:
        raise APIError("restore profile requires a WWN and/or serial-number binding")
    expires_at = _text(params, "expires_at", maximum=64)
    from datetime import datetime, timezone
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise APIError("expires_at must be a timezone-aware ISO-8601 timestamp") from exc
    if expiry.tzinfo is None or expiry.utcoffset() is None or expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise APIError("restore profile expiry must be a future timezone-aware timestamp")
    from feclora.storage.restore_profile import (
        RestoreProfile, RestoreTargetSelector, RestoreProfileError, save_unattended_restore_profile,
    )
    import uuid
    try:
        repository = _profile_repository({"repository_id": params["repository_id"]}, write=True)
        selector = RestoreTargetSelector(wwn=wwn, serial=serial)
        profile = RestoreProfile(
            profile_id=str(uuid.uuid4()), name=name,
            image_manifest=f"{image_id}.manifest.json", target=selector,
            execution_mode="unattended", layout_policy="preserve",
            verify_after_restore=True, on_success="none",
            expires_at=expires_at, single_use=True,
        )
        manifest_path = _image_manifest(image_id, repository)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.image_id != image_id or manifest.image_type != "disk":
            raise APIError("restore profiles currently require a matching whole-disk image")
        disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
        if len(disk_artifacts) != 1 or disk_artifacts[0].format != "raw":
            raise APIError("restore profiles require exactly one RAW whole-disk artifact")
        if any(item.encryption == "age" for item in manifest.artifacts):
            if not _security_material().get("age_decryption_available"):
                raise APIError("age-encrypted image requires a separately provisioned Server or Client age identity")
        inventory = collect_inventory()
        matches = [
            device for device in inventory.get("devices", [])
            if isinstance(device, dict) and device.get("type") == "disk" and selector.matches(device)
        ]
        if len(matches) != 1:
            raise APIError("stable target selector must match exactly one detected whole disk")
        target = matches[0]
        if target.get("read_only"):
            raise APIError("restore profile target disk is read-only")
        from feclora.storage.source_safety import check_capture_source_safe
        try:
            check_capture_source_safe(target.get("path"))
        except Exception as exc:
            raise APIError(f"restore profile target must be offline and unused: {exc}") from exc
        target_size = target.get("size_bytes")
        if isinstance(target_size, bool) or not isinstance(target_size, int) or target_size < manifest.source_size_bytes:
            raise APIError("restore profile target capacity is unknown or smaller than the source image; proportional restore is a separate workflow")
        if target.get("logical_sector_size") != manifest.logical_sector_size:
            raise APIError("restore profile target logical sector size differs from the image")
        pending = [target]
        while pending:
            item = pending.pop()
            if item.get("mountpoints"):
                raise APIError("restore profile target disk or one of its partitions is mounted or in use")
            children = item.get("children")
            if isinstance(children, list):
                pending.extend(child for child in children if isinstance(child, dict))
        path = _restore_profile_directory(repository, create=True) / f"{profile.profile_id}.json"
        saved = save_unattended_restore_profile(profile, path)
    except APIError:
        raise
    except (RestoreProfileError, ManifestValidationError, OSError, ValueError) as exc:
        raise APIError(f"could not create restore profile: {exc}") from exc
    return {
        "profile_id": profile.profile_id, "name": profile.name,
        "path": str(saved), "image_id": image_id, "repository_id": params["repository_id"],
        "target": selector.to_dict(), "execution_mode": "unattended",
        "single_use": True, "layout_policy": "preserve",
        "message": "Profile saved on persistent storage. It is not armed or executed automatically.",
    }




def _execute_restore_profile_operation(params: dict[str, Any]) -> dict[str, Any]:
    required = {"profile_id", "target", "confirmation", "repository_id"}
    if set(params) != required:
        raise APIError("execute_restore_profile requires profile_id, target, confirmation and repository_id")
    import uuid
    try:
        profile_id = str(uuid.UUID(params["profile_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError("profile_id must be a canonical UUID") from exc
    if profile_id != params["profile_id"]:
        raise APIError("profile_id must be a canonical UUID")
    target_path = _device(params["target"], "target")
    if params["confirmation"] != f"ERASE {target_path}":
        raise APIError(f"explicit confirmation required: ERASE {target_path}")
    repository_id = _text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}")
    from feclora.storage.s3_repository_manager import S3RepositoryManager
    if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
        raise APIError("unattended restore profiles require persistent mounted filesystem storage; S3 is not supported")
    with _operation_repository_context({"repository_id": repository_id}, write=True) as repository:
        _persistent_repository(repository)
        profile_path = _restore_profile_directory(repository) / f"{profile_id}.json"
        from feclora.storage.restore_profile import load_restore_profile, RestoreProfileError
        try:
            profile = load_restore_profile(profile_path)
        except RestoreProfileError as exc:
            raise APIError(f"selected restore profile is unavailable or invalid: {exc}") from exc
        if profile.profile_id != profile_id:
            raise APIError("restore profile identifier does not match its filename")
        inventory = collect_inventory()
        matches = [
            item for item in inventory.get("devices", [])
            if isinstance(item, dict) and item.get("type") == "disk" and profile.target.matches(item)
        ]
        if len(matches) != 1 or matches[0].get("path") != target_path:
            raise APIError("selected target path does not uniquely match the profile WWN/serial authorization")
        audit = repository / ".feclora" / "restore-audit"
        try:
            audit.mkdir(mode=0o700)
        except FileExistsError:
            pass
        audit_info = os.lstat(audit)
        if (not stat.S_ISDIR(audit_info.st_mode) or stat.S_ISLNK(audit_info.st_mode)
                or audit_info.st_uid != 0 or audit_info.st_mode & 0o077):
            raise APIError("restore profile audit directory must be root-owned and mode 0700")
        client_config = _client_runtime_config()
        identity_paths = []
        server_identity = Path("/etc/feclora/pki/server.age")
        try:
            server_info = os.lstat(server_identity)
            if stat.S_ISREG(server_info.st_mode) and not stat.S_ISLNK(server_info.st_mode) and server_info.st_uid == 0 and not server_info.st_mode & 0o077:
                identity_paths.append(server_identity)
        except OSError:
            pass
        if client_config and client_config.age_identity_file:
            identity_paths.append(Path(client_config.age_identity_file))
        manifest_path = _image_manifest(profile.image_manifest[:-len(".manifest.json")], repository)
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        encrypted = any(item.encryption == "age" for item in manifest.artifacts)
        if encrypted and not identity_paths:
            raise APIError("age-encrypted profile image requires a separately provisioned age identity")
        from feclora.storage.profile_executor import execute_unattended_restore_profile
        identity_context = tempfile.TemporaryDirectory(prefix="feclora-profile-identities-") if encrypted and len(identity_paths) > 1 else None
        try:
            if identity_context:
                identity_file = Path(identity_context.name) / "identities.txt"
                identity_file.write_text("\n".join(path.read_text(encoding="ascii").strip() for path in identity_paths) + "\n", encoding="ascii")
                os.chmod(identity_file, 0o600)
            else:
                identity_file = identity_paths[0] if identity_paths else None
            restored = execute_unattended_restore_profile(
                profile_path,
                consumption_ledger=audit / "consumed-profiles.jsonl",
                operation_log_path=audit / "operations.jsonl",
                repository=repository,
                age_identity_file=identity_file,
                progress_callback=_progress,
                expected_target_path=target_path,
            )
        except Exception as exc:
            raise APIError(f"unattended restore profile execution failed: {exc}") from exc
        finally:
            if identity_context:
                identity_context.cleanup()
    return {
        "profile_id": profile_id, "image_id": restored.image_id,
        "target": target_path, "verified": True,
        "message": "Single-use restore profile executed and destination read-back verification completed.",
    }


def dispatch(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) - {"action", "params"} or "action" not in request:
        raise APIError("request must contain an action and optional params object")
    action = request["action"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise APIError("params must be a JSON object")
    if action == "open_root_terminal":
        if params:
            raise APIError("open_root_terminal does not accept parameters")
        try:
            result = subprocess.run(
                ["/usr/bin/systemctl", "start", "--no-block", "feclora-root-terminal.service"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise APIError("cannot request the local root terminal") from exc
        if result.returncode != 0:
            raise APIError("systemd rejected the local root terminal request")
        return {"requested": True}
    if action == "get_keyboard_layout":
        if params:
            raise APIError("get_keyboard_layout does not accept parameters")
        from feclora.system_preferences import get_keyboard_layout, KeyboardLayoutError
        try:
            return get_keyboard_layout()
        except KeyboardLayoutError as exc:
            raise APIError(str(exc)) from exc
    if action == "set_keyboard_layout":
        from feclora.system_preferences import set_keyboard_layout, KeyboardLayoutError
        try:
            return set_keyboard_layout(params)
        except KeyboardLayoutError as exc:
            raise APIError(str(exc)) from exc
    if action == "check_capture_filesystem":
        if set(params) != {"source", "filesystem"}:
            raise APIError("check_capture_filesystem requires exactly source and filesystem")
        source = _device(params["source"], "source")
        filesystem = _text(params, "filesystem", pattern=r"(?:ext2|ext3|ext4|ntfs|ntfs3|xfs)")
        from feclora.storage.filesystem_probe import (
            FilesystemProbeError, probe_ext_minimum_size, probe_ntfs_minimum_size,
            check_xfs_read_only,
        )
        try:
            if filesystem in {"ext2", "ext3", "ext4"}:
                minimum_bytes = probe_ext_minimum_size(source, filesystem_type=filesystem)
                checker = "e2fsck -f -n"
            elif filesystem in {"ntfs", "ntfs3"}:
                minimum_bytes = probe_ntfs_minimum_size(source, filesystem_type=filesystem)
                checker = "ntfsresize --info"
            else:
                minimum_bytes = check_xfs_read_only(source, filesystem_type=filesystem)
                checker = "xfs_repair -n"
        except FilesystemProbeError as exc:
            raise APIError(f"read-only pre-capture check failed: {exc}") from exc
        result = {
            "source": source, "filesystem": filesystem, "checked": True,
            "read_only": True, "checker": checker,
            "limitations": (
                "This is a non-destructive offline consistency and geometry probe, "
                "not a repair and not a guarantee that capture data is application-consistent."
            ),
        }
        if filesystem == "xfs":
            result["checked_size_bytes"] = minimum_bytes
        else:
            result["minimum_size_bytes"] = minimum_bytes
        return result
    if action == "status":
        if params:
            raise APIError("status does not accept parameters")
        return {
            "hostname": socket.gethostname(), "platform": platform.platform(),
            "python": platform.python_version(),
            "server_configured": os.path.isfile("/etc/feclora/deployment-server.json"),
            "client_configured": os.path.isfile("/etc/feclora/deployment-client.json"),
            "services": _service_state(),
            "security": _security_material(),
            "certificate_status": _certificate_status(),
        }
    if action in {"systemd_credentials", "put_systemd_credential", "remove_systemd_credential"}:
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
            raise APIError("network_connection_profiles does not accept parameters")
        return {"profiles": _network_connection_profiles()}
    if action == "network_interfaces":
        if params:
            raise APIError("network_interfaces does not accept parameters")
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
            raise APIError("stop_pxe_services does not accept parameters")
        return _stop_pxe_services()
    if action == "import_deployment_job":
        return _import_deployment_job(params)
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
            raise APIError("pxe_service_status does not accept parameters")
        return _pxe_service_manager().status()
    if action == "inventory":
        if params:
            raise APIError("inventory does not accept parameters")
        return collect_inventory()
    if action == "restore_profiles":
        return _restore_profiles(params)
    if action == "create_restore_profile":
        return _create_restore_profile(params)
    if action == "images":
        if params:
            raise APIError("images does not accept parameters")
        return {"images": _images()}
    if action == "recovery_jobs":
        if set(params) not in (set(), {"repository_id"}):
            raise APIError("recovery_jobs accepts only an optional repository_id")
        repository_id = _repository_id(params)
        if repository_id is not None:
            from feclora.storage.s3_repository_manager import S3RepositoryManager
            if any(item["id"] == repository_id for item in S3RepositoryManager().list()):
                raise APIError("ddrescue recovery jobs require a filesystem repository; S3 is not supported")
        from feclora.storage.ddrescue_recovery import list_recovery_jobs, DdrescueRecoveryError
        try:
            with _operation_repository_context(
                {"repository_id": repository_id}, write=False,
            ) as repository:
                return {"jobs": list_recovery_jobs(repository)}
        except DdrescueRecoveryError as exc:
            raise APIError(f"cannot list ddrescue recovery jobs: {exc}") from exc
    if action == "repository_images":
        if set(params) != {"repository_id"}:
            raise APIError("repository_images requires repository_id")
        return {"images": _images(_text(params, "repository_id", pattern=r"[a-z0-9][a-z0-9-]{0,47}"))}
    if action == "inspect_image_layout":
        return _inspect_image_layout(params)
    if action == "browse_image":
        return _browse_image(params)
    if action == "verify_image":
        return _verify_image(params)
    if action == "operations":
        if params:
            raise APIError("operations does not accept parameters")
        return {"operations": _operations()}
    if action == "initialize_security":
        if params:
            raise APIError("initialize_security does not accept parameters")
        return _initialize_security()
    if action == "deployment_jobs":
        if params:
            raise APIError("deployment_jobs does not accept parameters")
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
            raise APIError("journals does not accept parameters")
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
    if action in {"capture_disk", "capture_partition", "capture_logical_volume", "capture_p2v", "import_p2v", "export_p2v_s3", "restore_disk", "restore_partition", "restore_logical_volume",
                  "clone_disk", "clone_partition", "extract_partition_image", "build_recovery_iso", "build_deployment_bundle", "restore_proportional_disk", "execute_restore_profile"}:
        return _submit_local_operation({"operation": action, "operation_params": params})
    raise APIError("unsupported API action")


def main() -> int:
    if os.geteuid() != 0:
        _emit({"ok": False, "error": "Feclora API requires authorized root execution"})
        return 1
    if len(sys.argv) != 2:
        _emit({"ok": False, "error": "one API command is required"})
        return 2
    try:
        raw = sys.stdin.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise APIError("request exceeds the size limit")
        request = json.loads(raw or "{}", object_pairs_hook=_reject_duplicates)
        if not isinstance(request, dict) or request.get("action") != sys.argv[1]:
            raise APIError("request action does not match the authorized command")
        response = {"ok": True, "data": dispatch(request)}
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)[:512]})
        return 1
    _emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

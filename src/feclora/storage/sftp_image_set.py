"""Publish complete, signed image sets to an SFTP repository.

The detached signature is uploaded last and acts as the publication marker:
consumers must reject a set unless both manifest and signature are present and
the signature verifies against an independently trusted minisign public key.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Callable

from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, verify_manifest_signature
from .sftp_transfer import SFTPTransferError
from .sftp_transfer_service import run_sftp_transfer


class SFTPImageSetError(RuntimeError):
    """An image set could not be safely published to SFTP."""


def _regular_file(path: str | os.PathLike[str], label: str) -> str:
    value = os.path.abspath(os.fspath(path))
    try:
        info = os.lstat(value)
    except OSError as exc:
        raise SFTPImageSetError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SFTPImageSetError(f"{label} must be a regular non-symlink file")
    return value


def _digest(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def publish_image_set(
    *,
    manifest_path: str | os.PathLike[str],
    signature_path: str | os.PathLike[str],
    public_key: str | os.PathLike[str],
    artifact_directory: str | os.PathLike[str],
    remote_directory: str,
    host: str,
    username: str,
    identity_credential: str,
    known_hosts_credential: str,
    port: int = 22,
    transfer: Callable[..., dict[str, Any]] = run_sftp_transfer,
    manager: Any = None,
) -> dict[str, Any]:
    """Validate and publish artifacts, manifest, then signature.

    Existing remote files are never overwritten by the SFTP primitive. A
    failed publication can leave unreferenced artifacts behind, but cannot
    produce a successfully signed, partially uploaded set.
    """
    manifest_file = _regular_file(manifest_path, "image manifest")
    signature_file = _regular_file(signature_path, "manifest signature")
    key_file = _regular_file(public_key, "trusted minisign public key")
    root = os.path.abspath(os.fspath(artifact_directory))
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise SFTPImageSetError("artifact directory is unavailable") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise SFTPImageSetError("artifact directory must be a real directory")

    try:
        manifest = ImageManifest.from_json(Path(manifest_file).read_text(encoding="utf-8"))
        verify_manifest_signature(manifest_file, key_file, signature_path=signature_file)
    except (OSError, UnicodeError, ManifestValidationError, ImageSecurityError) as exc:
        raise SFTPImageSetError(f"manifest validation or signature verification failed: {exc}") from exc

    files: list[tuple[str, str]] = []
    for artifact in manifest.artifacts:
        local = os.path.join(root, artifact.filename)
        local = _regular_file(local, f"artifact {artifact.filename}")
        size, digest = _digest(local)
        if size != artifact.size_bytes or digest != artifact.sha256:
            raise SFTPImageSetError(f"artifact {artifact.filename} does not match the signed manifest")
        files.append((local, artifact.filename))

    _, manifest_digest = _digest(manifest_file)
    _, signature_digest = _digest(signature_file)
    prefix = remote_directory.rstrip("/")
    if not prefix.startswith("/") or any(part in {".", ".."} for part in prefix.split("/")):
        raise SFTPImageSetError("remote image-set directory must be an absolute normalized path")

    def upload(local_path: str, filename: str) -> None:
        transfer(
            identity_credential=identity_credential,
            known_hosts_credential=known_hosts_credential,
            operation="upload", host=host, username=username,
            remote_path=f"{prefix}/{filename}", local_path=local_path,
            port=port, manager=manager,
        )

    try:
        for local, filename in files:
            upload(local, filename)
        upload(manifest_file, "manifest.json")
        upload(signature_file, "manifest.json.minisig")
    except (SFTPTransferError, RuntimeError, OSError) as exc:
        raise SFTPImageSetError(f"SFTP image-set publication failed: {exc}") from exc

    return {
        "image_id": manifest.image_id,
        "image_type": manifest.image_type,
        "artifact_count": len(files),
        "manifest_sha256": manifest_digest,
        "signature_sha256": signature_digest,
        "published": True,
        "publication_marker": "manifest.json.minisig",
    }

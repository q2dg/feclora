"""Fetch and verify complete signed image sets from an SFTP repository.

Untrusted manifest metadata is downloaded only into a private staging
directory. Its detached signature is verified against an independently
trusted key before any artifact is fetched. Artifacts are then checked against
the signed size and SHA-256 values and the complete directory is atomically
published without replacing an existing image.
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable

from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, verify_manifest_signature
from .sftp_transfer import SFTPTransferError
from .sftp_transfer_service import run_sftp_transfer


class SFTPImageSetError(RuntimeError):
    """An image set could not be safely published to or fetched from SFTP."""


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


def _remote_directory(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9._/-]{0,1024}", value)
            or value.startswith("//") or posixpath.normpath(value) != value
            or any(part in {".", ".."} for part in value.split("/"))):
        raise SFTPImageSetError("remote image-set directory must be an absolute normalized path")
    return value.rstrip("/") or "/"


def _validate_manifest_filenames(manifest: ImageManifest) -> None:
    reserved = {"manifest.json", "manifest.json.minisig"}
    if any(item.filename in reserved for item in manifest.artifacts):
        raise SFTPImageSetError("manifest artifact filename collides with reserved metadata")


def fetch_image_set(
    *,
    remote_directory: str,
    destination_root: str | os.PathLike[str],
    public_key: str | os.PathLike[str],
    host: str,
    username: str,
    identity_credential: str,
    known_hosts_credential: str,
    port: int = 22,
    transfer: Callable[..., dict[str, Any]] = run_sftp_transfer,
    manager: Any = None,
) -> dict[str, Any]:
    """Fetch metadata, authenticate it, fetch artifacts and publish atomically."""
    remote = _remote_directory(remote_directory)
    key_file = _regular_file(public_key, "trusted minisign public key")
    root = os.path.abspath(os.fspath(destination_root))
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise SFTPImageSetError("image destination root is unavailable") from exc
    if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
            or Path(root).resolve(strict=True) != Path(root)):
        raise SFTPImageSetError("image destination root must be a real directory without symlinked path components")

    # mkdtemp creates mode 0700; avoid a post-creation chmod failure leaking
    # a staging directory before the cleanup guard is established.
    staging = tempfile.mkdtemp(prefix=".feclora-sftp-incoming-", dir=root)

    def download(filename: str, expected_sha256: str | None) -> dict[str, Any]:
        return transfer(
            identity_credential=identity_credential,
            known_hosts_credential=known_hosts_credential,
            operation="download", host=host, username=username,
            remote_path=f"{remote}/{filename}" if remote != "/" else f"/{filename}",
            local_path=os.path.join(staging, filename), port=port,
            expected_sha256=expected_sha256,
            allow_unverified_metadata=expected_sha256 is None,
            manager=manager,
        )

    try:
        # These two files are untrusted until minisign verification succeeds.
        download("manifest.json", None)
        download("manifest.json.minisig", None)
        manifest_path = os.path.join(staging, "manifest.json")
        signature_path = manifest_path + ".minisig"
        if os.path.getsize(manifest_path) > 1024 * 1024:
            raise SFTPImageSetError("remote manifest exceeds the 1 MiB size limit")
        if os.path.getsize(signature_path) > 64 * 1024:
            raise SFTPImageSetError("remote minisign signature exceeds the 64 KiB size limit")
        try:
            manifest = ImageManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
            verify_manifest_signature(manifest_path, key_file, signature_path=signature_path)
        except (OSError, UnicodeError, ManifestValidationError, ImageSecurityError) as exc:
            raise SFTPImageSetError(f"remote manifest signature or schema validation failed: {exc}") from exc
        _validate_manifest_filenames(manifest)

        for artifact in manifest.artifacts:
            result = download(artifact.filename, artifact.sha256)
            local = os.path.join(staging, artifact.filename)
            size, digest = _digest(local)
            if size != artifact.size_bytes or digest != artifact.sha256:
                raise SFTPImageSetError(f"downloaded artifact {artifact.filename} does not match signed manifest")
            if result.get("verified") is not True:
                raise SFTPImageSetError(f"downloaded artifact {artifact.filename} was not digest-verified by the SFTP service")

        # Existing Feclora repositories are flat: artifacts plus
        # <image_id>.manifest.json and its adjacent .minisig. Publish the
        # artifacts first, the signature next, and the manifest last so the
        # manifest remains the visible commit marker expected by _images().
        published: list[str] = []
        manifest_name = f"{manifest.image_id}.manifest.json"
        signature_name = manifest_name + ".minisig"
        try:
            for artifact in manifest.artifacts:
                source = os.path.join(staging, artifact.filename)
                target = os.path.join(root, artifact.filename)
                os.link(source, target, follow_symlinks=False)
                published.append(target)
            signature_target = os.path.join(root, signature_name)
            os.link(signature_path, signature_target, follow_symlinks=False)
            published.append(signature_target)
            manifest_target = os.path.join(root, manifest_name)
            os.link(manifest_path, manifest_target, follow_symlinks=False)
            published.append(manifest_target)
            directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as exc:
            for target in reversed(published):
                try:
                    os.unlink(target)
                except OSError:
                    pass
            raise SFTPImageSetError(
                "an image artifact or manifest already exists; refusing to overwrite it"
            ) from exc
        except OSError:
            for target in reversed(published):
                try:
                    os.unlink(target)
                except OSError:
                    pass
            raise
        final_path = os.path.join(root, manifest_name)
        return {
            "image_id": manifest.image_id,
            "image_type": manifest.image_type,
            "artifact_count": len(manifest.artifacts),
            "repository_path": final_path,
            "signature_verified": True,
            "artifacts_verified": True,
            "published": True,
        }
    except (SFTPTransferError, OSError) as exc:
        raise SFTPImageSetError(f"SFTP image-set retrieval failed: {exc}") from exc
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)


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
    _validate_manifest_filenames(manifest)

    files: list[tuple[str, str]] = []
    for artifact in manifest.artifacts:
        local = _regular_file(os.path.join(root, artifact.filename), f"artifact {artifact.filename}")
        size, digest = _digest(local)
        if size != artifact.size_bytes or digest != artifact.sha256:
            raise SFTPImageSetError(f"artifact {artifact.filename} does not match the signed manifest")
        files.append((local, artifact.filename))

    _, manifest_digest = _digest(manifest_file)
    _, signature_digest = _digest(signature_file)
    prefix = _remote_directory(remote_directory)

    def upload(local_path: str, filename: str) -> None:
        transfer(
            identity_credential=identity_credential,
            known_hosts_credential=known_hosts_credential,
            operation="upload", host=host, username=username,
            remote_path=f"{prefix}/{filename}" if prefix != "/" else f"/{filename}",
            local_path=local_path, port=port, manager=manager,
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

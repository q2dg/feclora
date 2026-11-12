"""Fetch and publish SHA-256-verified image sets over authenticated SFTP."""
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
from .image_publication import ImagePublicationError, publish_image_set as publish_local_image_set
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
    # The native local repository is flat and uses these names as reserved
    # image-set commit markers. An artifact must never occupy another image's
    # marker namespace, even when the remote SFTP directory itself is separate.
    reserved = re.compile(
        r"(?:manifest\.json(?:\.minisig)?|"
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.manifest\.json(?:\.minisig)?)"
    )
    if any(reserved.fullmatch(item.filename) for item in manifest.artifacts):
        raise SFTPImageSetError("manifest artifact filename collides with reserved repository metadata")


def inspect_remote_image_set(
    *,
    remote_directory: str,
    host: str,
    username: str,
    identity_credential: str,
    known_hosts_credential: str,
    port: int = 22,
    transfer: Callable[..., dict[str, Any]] = run_sftp_transfer,
    manager: Any = None,
) -> dict[str, Any]:
    """Download and validate metadata for one remote image set."""
    remote = _remote_directory(remote_directory)
    with tempfile.TemporaryDirectory(prefix="feclora-sftp-inspect-") as staging:
        os.chmod(staging, 0o700)
        for filename in ("manifest.json",):
            result = transfer(
                identity_credential=identity_credential,
                known_hosts_credential=known_hosts_credential,
                operation="download", host=host, username=username,
                remote_path=f"{remote}/{filename}" if remote != "/" else f"/{filename}",
                local_path=os.path.join(staging, filename), port=port,
                expected_sha256=None, allow_unverified_metadata=True,
                manager=manager,
            )
            if result.get("verified") is not False:
                raise SFTPImageSetError("remote metadata transfer must remain explicitly unverified until manifest validation")
        manifest_path = os.path.join(staging, "manifest.json")
        if os.path.getsize(manifest_path) > 1024 * 1024:
            raise SFTPImageSetError("remote manifest exceeds the 1 MiB size limit")
        try:
            manifest = ImageManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError) as exc:
            raise SFTPImageSetError(f"remote manifest schema validation failed: {exc}") from exc
        _validate_manifest_filenames(manifest)
        return {
            "image_id": manifest.image_id,
            "image_type": manifest.image_type,
            "source_size_bytes": manifest.source_size_bytes,
            "logical_sector_size": manifest.logical_sector_size,
            "artifact_count": len(manifest.artifacts),
            "artifacts": [
                {"filename": item.filename, "role": item.role,
                 "size_bytes": item.size_bytes, "sha256": item.sha256,
                 "compression": item.compression, "encryption": item.encryption}
                for item in manifest.artifacts
            ],
            "manifest_sha256": _digest(manifest_path)[1],
        }


def fetch_image_set(
    *,
    remote_directory: str,
    destination_root: str | os.PathLike[str],
    host: str,
    username: str,
    identity_credential: str,
    known_hosts_credential: str,
    port: int = 22,
    expected_image_id: str | None = None,
    expected_manifest_sha256: str | None = None,
    transfer: Callable[..., dict[str, Any]] = run_sftp_transfer,
    manager: Any = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> dict[str, Any]:
    """Fetch and import a SHA-256-verified image set without overwriting files."""
    remote = _remote_directory(remote_directory)
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
        # The manifest is received over pinned-host-key SFTP.
        download("manifest.json", None)
        manifest_path = os.path.join(staging, "manifest.json")
        if os.path.getsize(manifest_path) > 1024 * 1024:
            raise SFTPImageSetError("remote manifest exceeds the 1 MiB size limit")
        try:
            manifest = ImageManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError) as exc:
            raise SFTPImageSetError(f"remote manifest schema validation failed: {exc}") from exc
        _validate_manifest_filenames(manifest)
        if expected_image_id is not None and manifest.image_id != expected_image_id:
            raise SFTPImageSetError("authenticated remote image ID does not match the selected image")
        if expected_manifest_sha256 is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
                raise SFTPImageSetError("expected manifest SHA-256 is invalid")
            if _digest(manifest_path)[1] != expected_manifest_sha256:
                raise SFTPImageSetError("authenticated remote manifest changed after inspection")

        bytes_total = sum(item.size_bytes for item in manifest.artifacts)
        bytes_done = 0
        if progress_callback is not None:
            progress_callback(bytes_done, bytes_total)
        for artifact in manifest.artifacts:
            result = download(artifact.filename, artifact.sha256)
            local = os.path.join(staging, artifact.filename)
            size, digest = _digest(local)
            if size != artifact.size_bytes or digest != artifact.sha256:
                raise SFTPImageSetError(f"downloaded artifact {artifact.filename} does not match manifest")
            if result.get("verified") is not True:
                raise SFTPImageSetError(f"downloaded artifact {artifact.filename} was not digest-verified by the SFTP service")
            bytes_done += size
            if progress_callback is not None:
                progress_callback(bytes_done, bytes_total)

        # Existing Feclora repositories are flat. Reuse the shared dirfd-pinned
        # publisher so rollback cannot unlink a concurrent replacement. The
        # native manifest remains the final commit marker.
        manifest_name = f"{manifest.image_id}.manifest.json"
        publication_names = [item.filename for item in manifest.artifacts]
        # SFTP metadata is downloaded under protocol-standard names. Rename
        # it inside the private staging directory to Feclora's native names
        # before handing the complete set to the shared publisher.
        staged_manifest = os.path.join(staging, "manifest.json")
        os.rename(staged_manifest, os.path.join(staging, manifest_name))
        publication_names.append(manifest_name)
        try:
            publish_local_image_set(root, staging, publication_names)
        except (FileExistsError, ImagePublicationError) as exc:
            raise SFTPImageSetError(
                "an image artifact or manifest already exists, or safe publication failed; refusing to overwrite it"
            ) from exc
        final_path = os.path.join(root, manifest_name)
        return {
            "image_id": manifest.image_id,
            "image_type": manifest.image_type,
            "artifact_count": len(manifest.artifacts),
            "repository_path": final_path,
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
    artifact_directory: str | os.PathLike[str],
    remote_directory: str,
    host: str,
    username: str,
    identity_credential: str,
    known_hosts_credential: str,
    port: int = 22,
    transfer: Callable[..., dict[str, Any]] = run_sftp_transfer,
    manager: Any = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> dict[str, Any]:
    """Validate and publish artifacts, then the manifest commit marker.

    Existing remote files are never overwritten. Failed publication may
    leave unreferenced artifacts, but never publishes the manifest early.
    """
    manifest_file = _regular_file(manifest_path, "image manifest")
    root = os.path.abspath(os.fspath(artifact_directory))
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise SFTPImageSetError("artifact directory is unavailable") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise SFTPImageSetError("artifact directory must be a real directory")

    try:
        manifest = ImageManifest.from_json(Path(manifest_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise SFTPImageSetError(f"manifest validation failed: {exc}") from exc
    _validate_manifest_filenames(manifest)

    files: list[tuple[str, str, int]] = []
    for artifact in manifest.artifacts:
        local = _regular_file(os.path.join(root, artifact.filename), f"artifact {artifact.filename}")
        size, digest = _digest(local)
        if size != artifact.size_bytes or digest != artifact.sha256:
            raise SFTPImageSetError(f"artifact {artifact.filename} does not match the manifest")
        files.append((local, artifact.filename, size))

    manifest_size, manifest_digest = _digest(manifest_file)
    prefix = _remote_directory(remote_directory)

    def upload(local_path: str, filename: str) -> None:
        transfer(
            identity_credential=identity_credential,
            known_hosts_credential=known_hosts_credential,
            operation="upload", host=host, username=username,
            remote_path=f"{prefix}/{filename}" if prefix != "/" else f"/{filename}",
            local_path=local_path, port=port, manager=manager,
        )

    bytes_total = sum(size for _local, _filename, size in files)
    bytes_total += manifest_size
    bytes_done = 0
    if progress_callback is not None:
        progress_callback(bytes_done, bytes_total)
    try:
        for local, filename, size in files:
            upload(local, filename)
            bytes_done += size
            if progress_callback is not None:
                progress_callback(bytes_done, bytes_total)
        # Manifest is the final visibility/commit marker.
        upload(manifest_file, "manifest.json")
        bytes_done += manifest_size
        if progress_callback is not None:
            progress_callback(bytes_done, bytes_total)
    except (SFTPTransferError, RuntimeError, OSError) as exc:
        raise SFTPImageSetError(f"SFTP image-set publication failed: {exc}") from exc

    return {
        "image_id": manifest.image_id,
        "image_type": manifest.image_type,
        "artifact_count": len(files),
        "manifest_sha256": manifest_digest,
        "published": True,
        "publication_marker": "manifest.json",
    }

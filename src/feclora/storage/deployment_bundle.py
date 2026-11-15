"""Atomically assemble a generic Live ISO, Feclora disk image and one shared answer.

This coordinator consumes already-built/selected inputs. It does not build an ISO,
capture a disk, import P2V QCOW2 or publish repository credentials.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.deployment.job import DeploymentJob, JobValidationError
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError


class DeploymentBundleError(ValueError):
    """Bundle inputs are inconsistent or publication failed."""


_MAX_ANSWER_BYTES = 64 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing any existing path."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise DeploymentBundleError("atomic no-replace directory publication is unavailable") from exc
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), str(destination))
        if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise DeploymentBundleError("filesystem/kernel does not support atomic no-replace directory publication")
        raise OSError(error, os.strerror(error), str(destination))


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise DeploymentBundleError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise DeploymentBundleError(f"{label} must be a regular non-symlink file")
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DeploymentBundleError(f"cannot read {path.name}: {exc}") from exc
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentBundleError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _run_xorriso(iso: Path, xorriso: str, runner: Callable[..., Any]) -> str:
    executable = shutil.which(xorriso) if "/" not in xorriso else xorriso
    if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        raise DeploymentBundleError("xorriso executable is not available")
    try:
        result = runner(
            [executable, "-indev", str(iso), "-report_el_torito", "plain"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeploymentBundleError(f"could not inspect Live ISO: {exc}") from exc
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise DeploymentBundleError("xorriso could not inspect Live ISO" + (f": {detail[:512]}" if detail else ""))
    report = (getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")
    if "El Torito" not in report and "El-Torito" not in report and "boot catalog" not in report.lower():
        raise DeploymentBundleError("selected Live ISO does not report an El Torito boot catalog")
    return executable


def _copy_verified(source: Path, destination: Path, expected_size: int, expected_digest: str) -> dict[str, Any]:
    info = _regular_file(source, source.name)
    if info.st_size != expected_size:
        raise DeploymentBundleError(f"size mismatch for {source.name}")
    digest = _sha256(source)
    if digest != expected_digest:
        raise DeploymentBundleError(f"SHA-256 mismatch for {source.name}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    if destination.stat().st_size != expected_size or _sha256(destination) != expected_digest:
        raise DeploymentBundleError(f"copied file failed integrity verification: {source.name}")
    return {"path": str(destination.relative_to(destination.parents[1])), "size_bytes": expected_size, "sha256": digest}


def build_deployment_bundle(
    base_iso: str,
    image_directory: str,
    manifest_path: str,
    answer_path: str,
    output_directory: str,
    *,
    source_revision: str | None = None,
    xorriso: str = "/usr/bin/xorriso",
    runner: Callable[..., Any] = subprocess.run,
    free_bytes: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Build a versioned bundle from existing inputs and publish it atomically.

    The shared answer is parsed as one schema-v1 DeploymentJob and serialized
    canonically exactly once. Every authorized Client receives this same file;
    its MAC-specific target selection remains inside target_bindings.
    """
    iso = Path(base_iso)
    image_dir = Path(image_directory)
    manifest_file = Path(manifest_path)
    answer_file = Path(answer_path)
    output = Path(output_directory)
    if not all(path.is_absolute() for path in (iso, image_dir, output)):
        raise DeploymentBundleError("Live ISO, image directory and output directory must be absolute")
    iso_info = _regular_file(iso, "Live ISO")
    try:
        image_info = os.lstat(image_dir)
        parent_info = os.lstat(output.parent)
    except OSError as exc:
        raise DeploymentBundleError(f"cannot inspect bundle directories: {exc}") from exc
    if (not stat.S_ISDIR(image_info.st_mode) or stat.S_ISLNK(image_info.st_mode)
            or not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)):
        raise DeploymentBundleError("image directory and output parent must be real directories")
    if output.name in {"", ".", ".."} or os.path.lexists(output):
        raise DeploymentBundleError("bundle output already exists or has an invalid name")

    manifest_info = _regular_file(manifest_file, "image manifest")
    if not 0 < manifest_info.st_size <= _MAX_MANIFEST_BYTES:
        raise DeploymentBundleError("image manifest must be non-empty and at most 1 MiB")
    try:
        manifest = ImageManifest.from_json(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise DeploymentBundleError(f"image manifest is invalid: {exc}") from exc
    if manifest.image_type != "disk":
        raise DeploymentBundleError("shared unattended restore bundle currently requires a whole-disk image manifest")

    answer_info = _regular_file(answer_file, "shared DeploymentJob answer")
    if not 0 < answer_info.st_size <= _MAX_ANSWER_BYTES:
        raise DeploymentBundleError("shared answer must be non-empty and at most 64 KiB")
    try:
        answer_value = json.loads(answer_file.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        job = DeploymentJob.from_dict(answer_value)
    except (OSError, UnicodeError, json.JSONDecodeError, JobValidationError) as exc:
        raise DeploymentBundleError(f"shared answer is invalid: {exc}") from exc
    if (job.operation != "restore" or job.target_type != "disk"
            or job.start_policy != "automatic" or job.image_id != manifest.image_id
            or job.repository_id is None or not job.confirm_destructive
            or len(job.target_bindings) != len(job.authorized_clients)):
        raise DeploymentBundleError("answer must be an automatic, destructive-confirmed whole-disk restore for this image with a repository and one target binding per Client")
    if job.transport == "multicast" and len(job.authorized_clients) < 2:
        raise DeploymentBundleError("multicast bundle requires at least two authorized Clients")
    canonical_answer = (job.to_json() + "\n").encode("utf-8")

    if source_revision is not None and (
        not isinstance(source_revision, str) or len(source_revision) not in {40, 64}
        or any(char not in "0123456789abcdefABCDEF" for char in source_revision)
    ):
        raise DeploymentBundleError("source_revision must be a full Git commit SHA")

    artifacts: list[tuple[Path, Any]] = []
    payload_bytes = iso_info.st_size + len(canonical_answer) + manifest_info.st_size
    for artifact in manifest.artifacts:
        source = image_dir / artifact.filename
        info = _regular_file(source, f"image artifact {artifact.filename}")
        if info.st_size != artifact.size_bytes or _sha256(source) != artifact.sha256:
            raise DeploymentBundleError(f"image artifact size or SHA-256 mismatch: {artifact.filename}")
        artifacts.append((source, artifact))
        payload_bytes += info.st_size

    if free_bytes is None:
        free_bytes = lambda directory: shutil.disk_usage(directory).free
    required = payload_bytes + max(16 * 1024 * 1024, payload_bytes // 100)
    try:
        available = free_bytes(str(output.parent))
    except OSError as exc:
        raise DeploymentBundleError(f"cannot check bundle output capacity: {exc}") from exc
    if available < required:
        raise DeploymentBundleError(f"insufficient bundle capacity: need {required} bytes, have {available}")

    _run_xorriso(iso, xorriso, runner)

    # A sibling O_EXCL lock serializes cooperating publishers and prevents a
    # concurrent run from replacing a completed bundle.
    lock_path = output.parent / (f".{output.name}.publish.lock")
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError as exc:
        raise DeploymentBundleError("another bundle publication is in progress") from exc
    staging: Path | None = None
    try:
        with os.fdopen(lock_fd, "w", encoding="ascii") as lock:
            lock.write(f"{os.getpid()}\n")
            lock.flush()
            os.fsync(lock.fileno())
        if os.path.lexists(output):
            raise DeploymentBundleError("bundle output already exists")
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
        os.chmod(staging, 0o700)
        (staging / "images").mkdir(mode=0o700)
        files: dict[str, dict[str, Any]] = {}

        def copy_entry(source: Path, relative: str, size: int, digest: str) -> None:
            destination = staging / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            entry = _copy_verified(source, destination, size, digest)
            entry["path"] = relative
            files[relative] = entry

        copy_entry(iso, "feclora-live.iso", iso_info.st_size, _sha256(iso))
        manifest_bytes = (json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        manifest_destination = staging / "image-manifest.json"
        manifest_destination.write_bytes(manifest_bytes)
        os.chmod(manifest_destination, 0o600)
        with manifest_destination.open("rb") as stream:
            os.fsync(stream.fileno())
        files["image-manifest.json"] = {
            "path": "image-manifest.json", "size_bytes": len(manifest_bytes),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
        for source, artifact in artifacts:
            copy_entry(source, f"images/{artifact.filename}", artifact.size_bytes, artifact.sha256)

        answer_destination = staging / "answer.json"
        fd = os.open(answer_destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_answer)
            stream.flush()
            os.fsync(stream.fileno())
        files["answer.json"] = {
            "path": "answer.json", "size_bytes": len(canonical_answer),
            "sha256": hashlib.sha256(canonical_answer).hexdigest(),
        }
        bundle_manifest = {
            "schema_version": 1,
            "bundle_id": job.job_id,
            "job_id": job.job_id,
            "image_id": manifest.image_id,
            "repository_id": job.repository_id,
            "boot_method": job.boot_method,
            "transport": job.transport,
            "authorized_clients": list(job.authorized_clients),
            "source_revision": source_revision,
            "files": files,
        }
        bundle_manifest_bytes = (json.dumps(bundle_manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        bundle_path = staging / "bundle-manifest.json"
        bundle_path.write_bytes(bundle_manifest_bytes)
        os.chmod(bundle_path, 0o600)
        with bundle_path.open("rb") as stream:
            os.fsync(stream.fileno())
        for directory in (staging / "images", staging):
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        _rename_noreplace(staging, output)
        staging = None
        parent_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return {
            "bundle_id": job.job_id, "output_directory": str(output),
            "image_id": manifest.image_id, "job_id": job.job_id,
            "client_count": len(job.authorized_clients), "transport": job.transport,
            "file_count": len(files), "bundle_manifest": str(output / "bundle-manifest.json"),
            "published": True,
        }
    except FileExistsError as exc:
        raise DeploymentBundleError("bundle output already exists") from exc
    except OSError as exc:
        raise DeploymentBundleError(f"bundle publication failed: {exc}") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass

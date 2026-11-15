#!/usr/bin/env python3
"""Build a coordinated Live ISO + Feclora image + one shared answer bundle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from feclora.deployment.job import DeploymentJob, JobValidationError
from feclora.storage.deployment_bundle import build_deployment_bundle
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError


class BundleWorkflowError(RuntimeError):
    """The coordinated artifact workflow could not complete safely."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BundleWorkflowError(f"duplicate answer field: {key}")
        result[key] = value
    return result


def create_bundle(
    *,
    fedora_iso: str,
    repository: str,
    repository_id: str,
    image_id: str,
    answer_file: str,
    output_directory: str,
    capture_source: str | None = None,
    releasever: str = "45",
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Build the generic Live ISO, optionally capture a disk, then bundle once."""
    repo = Path(repository)
    output = Path(output_directory)
    installer = Path(fedora_iso)
    answer_source = Path(answer_file)
    for path, label in ((repo, "image repository"), (installer, "Fedora installer ISO"),
                        (answer_source, "shared answer file")):
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise BundleWorkflowError(f"{label} is unavailable: {exc}") from exc
        if path == repo:
            import stat
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise BundleWorkflowError("image repository must be a real directory")
        else:
            import stat
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise BundleWorkflowError(f"{label} must be a regular file")
    if not output.is_absolute() or not output.parent.is_dir() or output.parent.is_symlink():
        raise BundleWorkflowError("bundle output must have an existing real parent directory")
    if output.exists() or output.is_symlink():
        raise BundleWorkflowError("bundle output already exists")
    if not re_identifier(repository_id) or not re_identifier(image_id):
        raise BundleWorkflowError("repository_id or image_id is invalid")

    try:
        answer_value = json.loads(answer_source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        job = DeploymentJob.from_dict(answer_value)
    except (OSError, UnicodeError, json.JSONDecodeError, JobValidationError) as exc:
        raise BundleWorkflowError(f"shared DeploymentJob answer is invalid: {exc}") from exc
    if (job.operation != "restore" or job.target_type != "disk"
            or job.start_policy != "automatic" or job.repository_id != repository_id
            or job.image_id != image_id or not job.confirm_destructive):
        raise BundleWorkflowError("shared answer must be an automatic whole-disk restore for this repository and image")

    if capture_source is not None:
        from feclora.storage.disk_capture import capture_disk
        try:
            capture_disk(capture_source, image_id, repo, compression="none")
        except Exception as exc:
            raise BundleWorkflowError(f"whole-disk capture failed: {exc}") from exc

    manifest_path = repo / f"{image_id}.manifest.json"
    try:
        manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise BundleWorkflowError(f"selected image manifest is unavailable or invalid: {exc}") from exc
    if manifest.image_id != image_id or manifest.image_type != "disk":
        raise BundleWorkflowError("selected image must be a Feclora whole-disk image with the requested ID")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".feclora-bundle-iso-", dir=output.parent) as temporary:
        iso_output = Path(temporary)
        environment = os.environ.copy()
        environment.update({
            "FEDORA_INSTALL_ISO": str(installer.resolve()),
            "FECLORA_RESULT_DIR": str(iso_output),
            "FECLORA_RELEASEVER": releasever,
        })
        try:
            result = runner(
                ["bash", str(ROOT / "build" / "build-iso.sh")],
                cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL,
                check=False, timeout=24 * 60 * 60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BundleWorkflowError(f"Live ISO build could not run: {exc}") from exc
        if result.returncode != 0:
            raise BundleWorkflowError(f"Live ISO build failed with exit status {result.returncode}")
        live_iso = iso_output / "feclora-live.iso"
        try:
            import stat
            iso_info = os.lstat(live_iso)
        except OSError as exc:
            raise BundleWorkflowError("Live ISO build did not produce feclora-live.iso") from exc
        if not stat.S_ISREG(iso_info.st_mode) or stat.S_ISLNK(iso_info.st_mode) or iso_info.st_size <= 0:
            raise BundleWorkflowError("Live ISO build output is not a non-empty regular file")

        with tempfile.TemporaryDirectory(prefix="feclora-bundle-answer-", dir=output.parent) as answer_tmp:
            answer_path = Path(answer_tmp) / "answer.json"
            fd = os.open(answer_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(job.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            try:
                result = build_deployment_bundle(
                    str(live_iso), str(repo), str(manifest_path), str(answer_path), str(output),
                )
            except Exception as exc:
                raise BundleWorkflowError(f"coordinated bundle publication failed: {exc}") from exc
    return {
        **result,
        "bundle_directory": str(output),
        "image_id": image_id,
        "repository_id": repository_id,
        "iso_built": True,
        "image_captured": capture_source is not None,
        "shared_answer_job_id": job.job_id,
    }


def re_identifier(value: str) -> bool:
    import re
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fedora-iso", required=True, help="Fedora DVD installer ISO used to build Feclora Live")
    parser.add_argument("--repository", required=True, help="Existing mounted filesystem image repository")
    parser.add_argument("--repository-id", required=True, help="Managed Feclora repository ID used in the shared answer")
    parser.add_argument("--image-id", required=True, help="Existing Feclora disk image ID, or ID to create with --capture-source")
    parser.add_argument("--answer-file", required=True, help="One shared schema-v1 automatic DeploymentJob JSON")
    parser.add_argument("--output", required=True, help="New bundle directory; it must not already exist")
    parser.add_argument("--capture-source", help="Optional offline source block device to capture before building the bundle")
    parser.add_argument("--releasever", default="45", help="Fedora release version (default: 45)")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as root on a Fedora x86_64 build host with KVM and ISO build dependencies")
    try:
        result = create_bundle(
            fedora_iso=args.fedora_iso, repository=args.repository,
            repository_id=args.repository_id, image_id=args.image_id,
            answer_file=args.answer_file, output_directory=args.output,
            capture_source=args.capture_source, releasever=args.releasever,
        )
    except BundleWorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

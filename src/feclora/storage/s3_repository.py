"""S3-compatible object repository primitives.

This module deliberately exposes object operations rather than a FUSE mount.
Image artifacts are immutable objects; the validated manifest is the commit
marker and is always uploaded after its payload objects.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .image_manifest import ImageManifest


class S3RepositoryError(RuntimeError):
    """An S3 object repository operation failed safely."""


_IMAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_ACCESS_KEY = re.compile(r"^[A-Za-z0-9/+=_-]{8,128}$")
_PREFIX_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=-]{0,127}$")
_OBJECT_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=-]{0,254}$")
_CHUNK = 1024 * 1024
_DEFAULT_PART_SIZE = 64 * 1024 * 1024
_MULTIPART_THRESHOLD = 64 * 1024 * 1024


@dataclass(frozen=True)
class S3RepositoryConfig:
    endpoint_url: str | None
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    secret_access_key: str
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.endpoint_url is not None:
            from urllib.parse import urlsplit
            parsed = urlsplit(self.endpoint_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment):
                raise S3RepositoryError("S3 endpoint must be an HTTPS URL without user info, query or fragment")
        if not isinstance(self.region, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", self.region):
            raise S3RepositoryError("S3 region is invalid")
        if (not isinstance(self.bucket, str) or not _BUCKET.fullmatch(self.bucket)
                or ".." in self.bucket or ".-" in self.bucket or "-." in self.bucket
                or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", self.bucket)):
            raise S3RepositoryError("S3 bucket name is invalid")
        if not isinstance(self.prefix, str) or len(self.prefix) > 512:
            raise S3RepositoryError("S3 prefix is invalid")
        normalized_prefix = self.prefix.strip("/")
        components = normalized_prefix.split("/") if normalized_prefix else []
        if any(not _PREFIX_COMPONENT.fullmatch(item) for item in components):
            raise S3RepositoryError("S3 prefix contains an unsafe path component")
        if not isinstance(self.access_key_id, str) or not _ACCESS_KEY.fullmatch(self.access_key_id):
            raise S3RepositoryError("S3 access key ID is invalid")
        if (not isinstance(self.secret_access_key, str)
                or not 8 <= len(self.secret_access_key) <= 256
                or any(ord(char) < 33 or ord(char) > 126 for char in self.secret_access_key)):
            raise S3RepositoryError("S3 secret access key is invalid")
        if not isinstance(self.read_only, bool):
            raise S3RepositoryError("S3 read_only must be boolean")


class S3ObjectRepository:
    """S3 image-set transfer with immutable keys and manifest-last commits."""

    def __init__(
        self,
        config: S3RepositoryConfig,
        *,
        client: Any | None = None,
        part_size: int = _DEFAULT_PART_SIZE,
        multipart_threshold: int = _MULTIPART_THRESHOLD,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        if part_size < 5 * 1024 * 1024 or part_size > 5 * 1024 * 1024 * 1024:
            raise S3RepositoryError("multipart part size must be between 5 MiB and 5 GiB")
        if multipart_threshold < part_size:
            raise S3RepositoryError("multipart threshold must be at least one part")
        self.config = config
        self.part_size = part_size
        self.multipart_threshold = multipart_threshold
        self.progress = progress
        if client is None:
            try:
                import boto3
                from botocore.config import Config
                client = boto3.client(
                    "s3",
                    endpoint_url=config.endpoint_url,
                    region_name=config.region,
                    aws_access_key_id=config.access_key_id,
                    aws_secret_access_key=config.secret_access_key,
                    verify=True,
                    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
                )
            except Exception as exc:
                raise S3RepositoryError(f"cannot initialize the S3 client: {exc}") from exc
        self.client = client
        self.prefix = config.prefix.strip("/")

    def _key(self, name: str) -> str:
        if (not isinstance(name, str) or not name or name.startswith("/")
                or name.endswith("/") or "\\" in name or "\x00" in name):
            raise S3RepositoryError("object key is unsafe")
        components = name.split("/")
        if any(not _OBJECT_COMPONENT.fullmatch(item) for item in components):
            raise S3RepositoryError("object key contains an unsafe path component")
        return f"{self.prefix}/{name}" if self.prefix else name

    def _manifest_key(self, image_id: str) -> str:
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise S3RepositoryError("image identifier is invalid")
        return self._key(f"{image_id}.manifest.json")

    def _artifact_key(self, image_id: str, filename: str) -> str:
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise S3RepositoryError("image identifier is invalid")
        return self._key(f"{image_id}/{filename}")

    def _report(self, done: int, total: int) -> None:
        if self.progress is not None:
            self.progress(done, total)

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            return self.client.head_object(Bucket=self.config.bucket, Key=key)
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", ""))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return None
            raise S3RepositoryError(f"cannot inspect S3 object {key}: {exc}") from exc

    def _exists(self, key: str) -> bool:
        return self._head(key) is not None

    def _put_file(self, path: Path, key: str, expected_sha256: str, expected_size: int) -> None:
        existing = self._head(key)
        if existing is not None:
            metadata = existing.get("Metadata", {})
            if (existing.get("ContentLength") == expected_size
                    and metadata.get("sha256") == expected_sha256):
                return
            raise S3RepositoryError(f"refusing to overwrite a different existing S3 object: {key}")
        if path.stat().st_size != expected_size:
            raise S3RepositoryError(f"local artifact size changed before upload: {path.name}")
        if expected_size < self.multipart_threshold:
            with path.open("rb") as source:
                try:
                    self.client.put_object(
                        Bucket=self.config.bucket, Key=key, Body=source,
                        ContentLength=expected_size,
                        Metadata={"sha256": expected_sha256},
                        IfNoneMatch="*",
                    )
                except Exception as exc:
                    raise S3RepositoryError(f"cannot upload S3 object {key}: {exc}") from exc
            return

        upload_id = None
        completed = False
        parts = []
        try:
            response = self.client.create_multipart_upload(
                Bucket=self.config.bucket, Key=key,
                Metadata={"sha256": expected_sha256},
            )
            upload_id = response["UploadId"]
            with path.open("rb") as source:
                number = 1
                while True:
                    chunk = source.read(self.part_size)
                    if not chunk:
                        break
                    result = self.client.upload_part(
                        Bucket=self.config.bucket, Key=key, UploadId=upload_id,
                        PartNumber=number, Body=chunk,
                    )
                    parts.append({"PartNumber": number, "ETag": result["ETag"]})
                    number += 1
            # Conditional completion is required to preserve immutable keys.
            self.client.complete_multipart_upload(
                Bucket=self.config.bucket, Key=key, UploadId=upload_id,
                MultipartUpload={"Parts": parts}, IfNoneMatch="*",
            )
            completed = True
        except Exception as exc:
            raise S3RepositoryError(f"multipart upload failed for {key}: {exc}") from exc
        finally:
            if upload_id is not None and not completed:
                try:
                    self.client.abort_multipart_upload(
                        Bucket=self.config.bucket, Key=key, UploadId=upload_id,
                    )
                except Exception:
                    pass

    @staticmethod
    def _digest(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while True:
                chunk = source.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def upload_image_set(self, repository: str | os.PathLike[str], image_id: str) -> dict[str, Any]:
        """Upload every payload first and publish its manifest as the commit marker."""
        if self.config.read_only:
            raise S3RepositoryError("S3 repository is configured read-only")
        root = Path(repository)
        manifest_path = root / f"{image_id}.manifest.json"
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise S3RepositoryError(f"local image manifest is invalid or unavailable: {exc}") from exc
        if manifest.image_id != image_id:
            raise S3RepositoryError("manifest image identifier does not match its filename")
        manifest_key = self._manifest_key(image_id)
        if self._exists(manifest_key):
            raise S3RepositoryError("refusing to overwrite an existing committed image")

        total = sum(item.size_bytes for item in manifest.artifacts)
        completed = 0
        for artifact in manifest.artifacts:
            path = root / artifact.filename
            try:
                size, digest = self._digest(path)
            except OSError as exc:
                raise S3RepositoryError(f"image artifact is unavailable: {artifact.filename}") from exc
            if size != artifact.size_bytes or digest != artifact.sha256:
                raise S3RepositoryError(f"image artifact failed local integrity verification: {artifact.filename}")
            self._put_file(path, self._artifact_key(image_id, artifact.filename), digest, size)
            completed += size
            self._report(completed, total)

        manifest_bytes = manifest_path.read_bytes()
        try:
            self.client.put_object(
                Bucket=self.config.bucket, Key=manifest_key, Body=manifest_bytes,
                ContentLength=len(manifest_bytes), ContentType="application/json",
                IfNoneMatch="*",
            )
        except Exception as exc:
            raise S3RepositoryError(f"image payloads uploaded but manifest commit failed: {exc}") from exc
        return {"image_id": image_id, "artifact_count": len(manifest.artifacts), "committed": True}

    def list_images(self) -> list[dict[str, Any]]:
        """Return only images whose manifest object exists and validates."""
        prefix = f"{self.prefix}/" if self.prefix else ""
        paginator = self.client.get_paginator("list_objects_v2")
        result = []
        try:
            pages = paginator.paginate(Bucket=self.config.bucket, Prefix=prefix)
            for page in pages:
                for item in page.get("Contents", []):
                    key = item.get("Key", "")
                    filename = key.rsplit("/", 1)[-1]
                    if not filename.endswith(".manifest.json"):
                        continue
                    try:
                        body = self.client.get_object(Bucket=self.config.bucket, Key=key)["Body"]
                        try:
                            manifest = ImageManifest.from_json(body.read().decode("utf-8"))
                        finally:
                            body.close()
                    except Exception as exc:
                        raise S3RepositoryError(f"cannot read S3 manifest {key}: {exc}") from exc
                    if filename != f"{manifest.image_id}.manifest.json":
                        continue
                    complete = True
                    for artifact in manifest.artifacts:
                        head = self._head(self._artifact_key(manifest.image_id, artifact.filename))
                        if head is None:
                            complete = False
                            break
                        if (head.get("ContentLength") != artifact.size_bytes
                                or head.get("Metadata", {}).get("sha256") != artifact.sha256):
                            complete = False
                            break
                    if not complete:
                        continue
                    result.append({
                        "image_id": manifest.image_id,
                        "image_type": manifest.image_type,
                        "source_size_bytes": manifest.source_size_bytes,
                        "logical_sector_size": manifest.logical_sector_size,
                        "encrypted": bool(manifest.artifacts) and all(
                            artifact.encryption == "age" for artifact in manifest.artifacts
                        ),
                        "artifact_count": len(manifest.artifacts),
                    })
        except Exception as exc:
            if isinstance(exc, S3RepositoryError):
                raise
            raise S3RepositoryError(f"S3 image inventory failed: {exc}") from exc
        return sorted(result, key=lambda item: item["image_id"])

    def download_image_set(
        self, image_id: str, destination: str | os.PathLike[str],
    ) -> Path:
        """Download and verify a committed image set into a private local directory."""
        root = Path(destination)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        manifest_key = self._manifest_key(image_id)
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=manifest_key)
            manifest_bytes = response["Body"].read()
            response["Body"].close()
            manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise S3RepositoryError(f"committed image manifest is unavailable or invalid: {exc}") from exc
        if manifest.image_id != image_id:
            raise S3RepositoryError("remote manifest image identifier does not match its object key")

        for artifact in manifest.artifacts:
            final_path = root / artifact.filename
            if final_path.exists():
                size, digest = self._digest(final_path)
                if size == artifact.size_bytes and digest == artifact.sha256:
                    continue
                raise S3RepositoryError(f"local destination already contains a different artifact: {artifact.filename}")
            temporary = root / f".{artifact.filename}.{secrets.token_hex(8)}.part"
            digest = hashlib.sha256()
            size = 0
            try:
                response = self.client.get_object(
                    Bucket=self.config.bucket, Key=self._artifact_key(image_id, artifact.filename),
                )
                with temporary.open("xb") as output:
                    body = response["Body"]
                    try:
                        while True:
                            chunk = body.read(_CHUNK)
                            if not chunk:
                                break
                            output.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    finally:
                        body.close()
                    output.flush()
                    os.fsync(output.fileno())
                if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                    raise S3RepositoryError(f"downloaded artifact failed integrity verification: {artifact.filename}")
                os.link(temporary, final_path, follow_symlinks=False)
            except S3RepositoryError:
                raise
            except Exception as exc:
                raise S3RepositoryError(f"cannot download artifact {artifact.filename}: {exc}") from exc
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

        manifest_path = root / f"{image_id}.manifest.json"
        try:
            with manifest_path.open("xb") as output:
                output.write(manifest_bytes)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            existing = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
            if existing.image_id != image_id:
                raise S3RepositoryError("local manifest destination contains a different image")
        return manifest_path

"""Validated, versioned metadata for a feclora disk/partition image set.

The manifest describes files and source geometry. It is not an instruction to
write a target device and performs no filesystem or block-device I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class ManifestValidationError(ValueError):
    """Raised when an image manifest is malformed or unsafe."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_PARTITION_ID_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
_ARTIFACT_ROLES = {"disk-image", "disk-metadata", "partition-table", "boot-area", "partition-image", "logical-volume-image"}
_ARTIFACT_FORMATS = {"raw", "partclone"}
_COMPRESSIONS = {"none", "gzip", "zstd", "xz", "lz4"}


_STORAGE_SCOPES = {
    "whole_disk_bytes", "partition_bytes", "logical_volume_bytes",
    "encrypted_container_bytes", "decrypted_mapping_bytes",
}
_STORAGE_LAYERS = {
    "block_device", "luks2_container", "active_crypt_mapping",
    "lvm_logical_volume", "btrfs_filesystem", "btrfs_subvolume",
}
_STORAGE_DEPENDENCIES = {
    "luks2_metadata", "lvm_pv_metadata", "lvm_vg_members",
    "lvm_volume_group", "btrfs_filesystem", "btrfs_subvolume",
}


def _validate_storage_metadata(value: Any, image_type: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestValidationError("storage metadata must be a JSON object")
    allowed = {
        "schema_version", "capture_scope", "source_layer", "luks_uuid",
        "lvm_vg_name", "lvm_lv_name", "lvm_lv_uuid", "btrfs_uuid",
        "btrfs_subvolume_id", "btrfs_subvolume_uuid", "btrfs_parent_uuid",
        "btrfs_received_uuid", "dependencies",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ManifestValidationError(f"Unknown storage metadata fields: {', '.join(sorted(unknown))}")
    if value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        raise ManifestValidationError("Unsupported storage metadata schema_version")
    scope = value.get("capture_scope")
    if scope not in _STORAGE_SCOPES:
        raise ManifestValidationError("Unsupported storage capture_scope")
    layer = value.get("source_layer")
    if layer not in _STORAGE_LAYERS:
        raise ManifestValidationError("Unsupported storage source_layer")
    if image_type == "disk" and scope != "whole_disk_bytes":
        raise ManifestValidationError("Disk image storage scope must be whole_disk_bytes")
    if image_type == "partition" and scope not in {"partition_bytes", "encrypted_container_bytes"}:
        raise ManifestValidationError("Partition image has an incompatible storage scope")
    if image_type == "logical_volume" and scope not in {
        "logical_volume_bytes", "encrypted_container_bytes", "decrypted_mapping_bytes"
    }:
        raise ManifestValidationError("Logical-volume image has an incompatible storage scope")
    result = dict(value)
    for key in allowed - {"schema_version", "capture_scope", "source_layer", "dependencies"}:
        item = value.get(key)
        if item is not None and (
            not isinstance(item, str) or not item or len(item) > 256
            or any(ord(ch) < 32 for ch in item)
        ):
            raise ManifestValidationError(f"storage.{key} must be a short non-empty string")
    if "btrfs_subvolume_id" in value:
        subvolume_id = value["btrfs_subvolume_id"]
        if isinstance(subvolume_id, bool) or not isinstance(subvolume_id, int) or subvolume_id < 0:
            raise ManifestValidationError("storage.btrfs_subvolume_id must be a non-negative integer")
    dependencies = value.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ManifestValidationError("storage.dependencies must be a list")
    normalized = []
    for dependency in dependencies:
        if not isinstance(dependency, dict) or set(dependency) != {"kind", "identity", "included_in_source_bytes"}:
            raise ManifestValidationError("Each storage dependency requires kind, identity and included_in_source_bytes")
        if dependency["kind"] not in _STORAGE_DEPENDENCIES:
            raise ManifestValidationError("Unsupported storage dependency kind")
        identity = dependency["identity"]
        included = dependency["included_in_source_bytes"]
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise ManifestValidationError("Storage dependency identity must be a short non-empty string")
        if not isinstance(included, bool):
            raise ManifestValidationError("Storage dependency included_in_source_bytes must be boolean")
        normalized.append(dict(dependency))
    result["dependencies"] = normalized
    return result


@dataclass(frozen=True)
class ImageArtifact:
    """One file belonging to an image set."""

    filename: str
    role: str
    format: str
    compression: str
    size_bytes: int
    sha256: str
    partition_id: str | None = None
    filesystem: str | None = None
    encryption: str = "none"
    compression_level: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ImageArtifact":
        if not isinstance(value, dict):
            raise ManifestValidationError("Each artifact must be a JSON object")
        allowed = {
            "filename", "role", "format", "compression", "size_bytes",
            "sha256", "partition_id", "filesystem", "encryption", "compression_level",
        }
        unknown = set(value) - allowed
        missing = allowed - set(value) - {"partition_id", "filesystem", "encryption", "compression_level"}
        if unknown:
            raise ManifestValidationError(f"Unknown artifact fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ManifestValidationError(f"Missing artifact fields: {', '.join(sorted(missing))}")

        filename = value.get("filename")
        if not isinstance(filename, str) or not _FILENAME_RE.fullmatch(filename):
            raise ManifestValidationError("Artifact filename must be a safe basename")
        if filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise ManifestValidationError("Artifact filename must not contain path components")

        role = value.get("role")
        if not isinstance(role, str) or role not in _ARTIFACT_ROLES:
            raise ManifestValidationError("Unsupported artifact role")
        image_format = value.get("format")
        if not isinstance(image_format, str) or image_format not in _ARTIFACT_FORMATS:
            raise ManifestValidationError("Artifact format must be raw or partclone")
        compression = value.get("compression")
        if not isinstance(compression, str) or compression not in _COMPRESSIONS:
            raise ManifestValidationError("Unsupported artifact compression")

        size = value.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ManifestValidationError("Artifact size_bytes must be a positive integer")
        digest = value.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ManifestValidationError("Artifact sha256 must be 64 lowercase hexadecimal characters")

        partition_id = value.get("partition_id")
        filesystem = value.get("filesystem")
        encryption = value.get("encryption", "none")
        if not isinstance(encryption, str) or encryption not in {"none", "age"}:
            raise ManifestValidationError("Artifact encryption must be none or age")
        compression_level = value.get("compression_level")
        if compression == "none" and compression_level is not None:
            raise ManifestValidationError("Uncompressed artifacts must not specify compression_level")
        if compression_level is not None and (
            isinstance(compression_level, bool) or not isinstance(compression_level, int)
            or (compression == "gzip" and not 1 <= compression_level <= 9)
            or (compression == "xz" and not 0 <= compression_level <= 9)
            or (compression == "zstd" and not 1 <= compression_level <= 19)
            or (compression == "lz4" and not 1 <= compression_level <= 12)
            or compression not in {"gzip", "xz", "zstd", "lz4"}
        ):
            raise ManifestValidationError("gzip 1-9; xz 0-9; zstd 1-19; lz4 1-12")
        supported_filesystems = {"btrfs", "ext2", "ext3", "ext4", "exfat", "fat", "fat12", "fat16", "fat32", "vfat", "f2fs", "ntfs", "ntfs3", "xfs"}
        if filesystem is not None and (not isinstance(filesystem, str) or filesystem not in supported_filesystems):
            raise ManifestValidationError("Unsupported artifact filesystem")
        if role == "partition-image":
            if not isinstance(partition_id, str) or not _PARTITION_ID_RE.fullmatch(partition_id):
                raise ManifestValidationError("partition-image artifacts require a valid partition_id")
        elif partition_id is not None:
            raise ManifestValidationError("partition_id is only valid for partition-image artifacts")

        if image_format == "partclone" and role not in {"partition-image", "logical-volume-image"}:
            raise ManifestValidationError("Partclone format is only valid for partition or logical-volume image artifacts")
        if role not in {"partition-image", "logical-volume-image"} and filesystem is not None:
            raise ManifestValidationError("filesystem is only valid for partition or logical-volume image artifacts")
        return cls(filename, role, image_format, compression, size, digest, partition_id, filesystem, encryption, compression_level)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "filename": self.filename,
            "role": self.role,
            "format": self.format,
            "compression": self.compression,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.partition_id is not None:
            result["partition_id"] = self.partition_id
        if self.filesystem is not None:
            result["filesystem"] = self.filesystem
        if self.encryption != "none":
            result["encryption"] = self.encryption
        if self.compression_level is not None:
            result["compression_level"] = self.compression_level
        return result


@dataclass(frozen=True)
class ImageManifest:
    """Immutable manifest for a whole-disk or partition image set."""

    image_id: str
    image_type: str
    source_size_bytes: int
    logical_sector_size: int
    partition_table: str
    artifacts: tuple[ImageArtifact, ...]
    storage: dict[str, Any] | None = None
    schema_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ImageManifest":
        if not isinstance(value, dict):
            raise ManifestValidationError("Manifest must be a JSON object")
        allowed = {
            "schema_version", "image_id", "image_type", "source_size_bytes",
            "logical_sector_size", "partition_table", "artifacts", "storage",
        }
        unknown = set(value) - allowed
        missing = allowed - set(value)
        if unknown:
            raise ManifestValidationError(f"Unknown manifest fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ManifestValidationError(f"Missing manifest fields: {', '.join(sorted(missing))}")

        version = value.get("schema_version")
        if isinstance(version, bool) or version != 1:
            raise ManifestValidationError("Unsupported manifest schema_version")

        image_id = value.get("image_id")
        if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
            raise ManifestValidationError("image_id must be a simple identifier")

        image_type = value.get("image_type")
        if not isinstance(image_type, str) or image_type not in {"disk", "partition", "logical_volume"}:
            raise ManifestValidationError("image_type must be disk, partition or logical_volume")

        source_size = value.get("source_size_bytes")
        if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0:
            raise ManifestValidationError("source_size_bytes must be a positive integer")

        sector_size = value.get("logical_sector_size")
        if isinstance(sector_size, bool) or not isinstance(sector_size, int) or sector_size not in {512, 4096}:
            raise ManifestValidationError("logical_sector_size must be 512 or 4096")

        table = value.get("partition_table")
        if not isinstance(table, str) or table not in {"gpt", "mbr", "none", "unknown"}:
            raise ManifestValidationError("partition_table must be gpt, mbr, none, or unknown")
        if image_type == "partition" and table != "none":
            raise ManifestValidationError("Partition images must use partition_table='none'")

        raw_artifacts = value.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise ManifestValidationError("artifacts must be a non-empty list")
        artifacts = tuple(ImageArtifact.from_dict(item) for item in raw_artifacts)
        filenames = [item.filename for item in artifacts]
        if len(set(filenames)) != len(filenames):
            raise ManifestValidationError("Artifact filenames must be unique")

        roles = [item.role for item in artifacts]
        if image_type == "disk" and "partition-table" not in roles:
            raise ManifestValidationError("Disk image requires a partition-table artifact")
        if image_type == "disk" and not ({"disk-image", "partition-image"} & set(roles)):
            raise ManifestValidationError("Disk image requires at least one data artifact")
        if image_type == "partition" and "partition-image" not in roles:
            raise ManifestValidationError("Partition image requires a partition-image artifact")
        if image_type == "logical_volume" and roles.count("logical-volume-image") != 1:
            raise ManifestValidationError("Logical-volume image requires exactly one logical-volume-image artifact")
        if "disk-image" in roles and any(
            item.role == "disk-image" and item.format != "raw" for item in artifacts
        ):
            raise ManifestValidationError("Whole-disk artifacts must use raw format")
        if image_type in {"partition", "logical_volume"} and any(
            role in {"partition-table", "disk-metadata", "boot-area"} for role in roles
        ):
            raise ManifestValidationError("Partition/logical-volume images cannot contain whole-disk metadata artifacts")

        storage = value.get("storage")
        if storage is not None:
            storage = _validate_storage_metadata(storage, image_type)

        return cls(
            image_id=image_id,
            image_type=image_type,
            source_size_bytes=source_size,
            logical_sector_size=sector_size,
            partition_table=table,
            artifacts=artifacts,
            storage=storage,
            schema_version=1,
        )

    @classmethod
    def from_json(cls, document: str) -> "ImageManifest":
        try:
            value = json.loads(document)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ManifestValidationError("Manifest is not valid JSON") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "image_id": self.image_id,
            "image_type": self.image_type,
            "source_size_bytes": self.source_size_bytes,
            "logical_sector_size": self.logical_sector_size,
            "partition_table": self.partition_table,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            **({"storage": self.storage} if self.storage is not None else {}),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

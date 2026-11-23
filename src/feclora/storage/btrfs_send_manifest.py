"""Strict manifest contract for Btrfs send-stream image sets.

This format is deliberately separate from block-image manifests: a send stream
is a subvolume replication artifact, not a disk or filesystem byte image.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class BtrfsSendManifestError(ValueError):
    """A Btrfs send manifest is malformed or unsafe."""


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_IMAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPRESSIONS = {"none", "gzip", "xz", "zstd", "lz4"}


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise BtrfsSendManifestError(f"{field} must be a valid UUID")
    return value.lower()


@dataclass(frozen=True)
class BtrfsSendManifest:
    """Validated provenance and integrity metadata for one send stream."""

    image_id: str
    filesystem_uuid: str
    subvolume_id: int
    subvolume_uuid: str
    device_count: int
    send_mode: str
    stream_parent_uuid: str | None
    stream_filename: str
    stream_size_bytes: int
    stream_sha256: str
    compression: str
    parent_uuid: str | None = None
    received_uuid: str | None = None
    schema_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BtrfsSendManifest":
        if not isinstance(value, dict):
            raise BtrfsSendManifestError("manifest must be a JSON object")
        required = {
            "schema_version", "image_id", "filesystem_uuid", "subvolume_id",
            "subvolume_uuid", "device_count", "send_mode", "stream_parent_uuid",
            "stream_filename", "stream_size_bytes", "stream_sha256", "compression",
        }
        optional = {"parent_uuid", "received_uuid"}
        if set(value) - required - optional or required - set(value):
            raise BtrfsSendManifestError("manifest fields do not match the Btrfs send schema")
        version = value["schema_version"]
        if isinstance(version, bool) or version != 1:
            raise BtrfsSendManifestError("unsupported Btrfs send manifest schema_version")
        image_id = value["image_id"]
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise BtrfsSendManifestError("image_id is invalid")
        subvolume_id = value["subvolume_id"]
        if isinstance(subvolume_id, bool) or not isinstance(subvolume_id, int) or subvolume_id < 256:
            raise BtrfsSendManifestError("subvolume_id must be an integer >= 256")
        device_count = value["device_count"]
        if isinstance(device_count, bool) or not isinstance(device_count, int) or not 1 <= device_count <= 256:
            raise BtrfsSendManifestError("device_count must be an integer between 1 and 256")
        mode = value["send_mode"]
        if mode not in {"full", "incremental"}:
            raise BtrfsSendManifestError("send_mode must be full or incremental")
        parent = value["stream_parent_uuid"]
        if mode == "incremental":
            parent = _uuid(parent, "stream_parent_uuid")
        elif parent is not None:
            raise BtrfsSendManifestError("full send streams must not specify stream_parent_uuid")
        filename = value["stream_filename"]
        if not isinstance(filename, str) or not _FILENAME.fullmatch(filename) or filename in {".", ".."}:
            raise BtrfsSendManifestError("stream_filename must be a safe basename")
        size = value["stream_size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise BtrfsSendManifestError("stream_size_bytes must be a positive integer")
        digest = value["stream_sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise BtrfsSendManifestError("stream_sha256 must be 64 lowercase hexadecimal characters")
        compression = value["compression"]
        if compression not in _COMPRESSIONS:
            raise BtrfsSendManifestError("unsupported stream compression")
        normalized = {
            "schema_version": 1,
            "image_id": image_id,
            "filesystem_uuid": _uuid(value["filesystem_uuid"], "filesystem_uuid"),
            "subvolume_id": subvolume_id,
            "subvolume_uuid": _uuid(value["subvolume_uuid"], "subvolume_uuid"),
            "device_count": device_count,
            "send_mode": mode,
            "stream_parent_uuid": parent,
            "stream_filename": filename,
            "stream_size_bytes": size,
            "stream_sha256": digest,
            "compression": compression,
            "parent_uuid": _uuid(value["parent_uuid"], "parent_uuid") if value.get("parent_uuid") is not None else None,
            "received_uuid": _uuid(value["received_uuid"], "received_uuid") if value.get("received_uuid") is not None else None,
        }
        return cls(**normalized)

    @classmethod
    def from_json(cls, document: str) -> "BtrfsSendManifest":
        try:
            value = json.loads(document)
        except (TypeError, json.JSONDecodeError) as exc:
            raise BtrfsSendManifestError("manifest is not valid JSON") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "image_id": self.image_id,
            "filesystem_uuid": self.filesystem_uuid,
            "subvolume_id": self.subvolume_id,
            "subvolume_uuid": self.subvolume_uuid,
            "device_count": self.device_count,
            "send_mode": self.send_mode,
            "stream_parent_uuid": self.stream_parent_uuid,
            "stream_filename": self.stream_filename,
            "stream_size_bytes": self.stream_size_bytes,
            "stream_sha256": self.stream_sha256,
            "compression": self.compression,
        }
        if self.parent_uuid is not None:
            result["parent_uuid"] = self.parent_uuid
        if self.received_uuid is not None:
            result["received_uuid"] = self.received_uuid
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

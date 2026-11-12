"""Validate declarative PXE answer documents.

Answer documents are data, not executable scripts. They deliberately contain
no client certificate, private key, password, or local /dev path. Credentials
for remote repositories are referenced separately by an opaque local ID.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit


class PXEAnswerError(ValueError):
    """An uploaded or downloaded PXE answer document is invalid."""


MAX_ANSWER_BYTES = 64 * 1024
IMAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CREDENTIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
WWN_RE = re.compile(r"^[A-Za-z0-9_.:-]{4,128}$")
SERIAL_RE = re.compile(r"^[A-Za-z0-9_.:+/-]{1,128}$")
REPOSITORY_SCHEMES = {
    "sshfs", "sftp", "smb", "cifs", "nfs", "webdav", "webdavs",
    "http", "https", "bittorrent", "magnet",
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PXEAnswerError(f"duplicate answer field: {key}")
        result[key] = value
    return result


def _repository_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise PXEAnswerError("repository_url must be a URL under 2048 characters")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise PXEAnswerError("repository_url contains whitespace or control characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PXEAnswerError("repository_url is malformed") from exc
    if parsed.scheme.lower() not in REPOSITORY_SCHEMES:
        raise PXEAnswerError("repository_url scheme is not supported")
    if parsed.username is not None or parsed.password is not None:
        raise PXEAnswerError("repository_url must not embed usernames or passwords")
    if parsed.scheme.lower() == "magnet":
        if not value.startswith("magnet:?") or "xt=urn:btih:" not in value:
            raise PXEAnswerError("magnet repository URL must identify a BitTorrent info hash")
    elif not parsed.hostname:
        raise PXEAnswerError("repository_url must contain a host")
    if port is not None and not 1 <= port <= 65535:
        raise PXEAnswerError("repository_url port is invalid")
    if parsed.fragment:
        raise PXEAnswerError("repository_url must not contain a fragment")
    return value


def validate_pxe_answer(value: object) -> dict[str, object]:
    """Validate the version-1 unattended whole-disk restore answer."""
    if not isinstance(value, dict):
        raise PXEAnswerError("PXE answer document must be a JSON object")
    required = {
        "schema_version", "operation", "image_id", "repository_url",
        "target", "confirm_destructive", "start",
    }
    optional = {"credential_ref", "description"}
    if not required.issubset(value) or set(value) - required - optional:
        raise PXEAnswerError("PXE answer document has missing or unknown fields")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise PXEAnswerError("unsupported PXE answer schema_version")
    if value["operation"] != "restore":
        raise PXEAnswerError("PXE answer currently supports restore only")
    image_id = value["image_id"]
    if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
        raise PXEAnswerError("image_id is invalid")
    repository_url = _repository_url(value["repository_url"])
    target = value["target"]
    if not isinstance(target, dict) or set(target) != {"wwn", "serial"}:
        raise PXEAnswerError("target must contain exactly wwn and serial selectors")
    wwn, serial = target["wwn"], target["serial"]
    if wwn is not None and (not isinstance(wwn, str) or not WWN_RE.fullmatch(wwn)):
        raise PXEAnswerError("target.wwn is invalid")
    if serial is not None and (not isinstance(serial, str) or not SERIAL_RE.fullmatch(serial)):
        raise PXEAnswerError("target.serial is invalid")
    if wwn is None and serial is None:
        raise PXEAnswerError("target requires a WWN and/or serial selector")
    if value["confirm_destructive"] is not True or value["start"] is not True:
        raise PXEAnswerError("unattended restore requires explicit confirm_destructive and start flags")
    credential_ref = value.get("credential_ref")
    if credential_ref is not None and (
        not isinstance(credential_ref, str) or not CREDENTIAL_ID_RE.fullmatch(credential_ref)
    ):
        raise PXEAnswerError("credential_ref must be a valid local credential identifier")
    description = value.get("description")
    if description is not None and (
        not isinstance(description, str) or len(description) > 256
        or any(ord(char) < 32 for char in description)
    ):
        raise PXEAnswerError("description must be text under 257 characters")
    return {
        "schema_version": 1,
        "operation": "restore",
        "image_id": image_id,
        "repository_url": repository_url,
        "target": {"wwn": wwn, "serial": serial},
        "confirm_destructive": True,
        "start": True,
        **({"credential_ref": credential_ref} if credential_ref is not None else {}),
        **({"description": description} if description is not None else {}),
    }


def parse_pxe_answer(raw: bytes | str) -> dict[str, object]:
    """Parse bounded UTF-8 JSON, rejecting duplicate keys and non-object roots."""
    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PXEAnswerError("PXE answer is not valid UTF-8") from exc
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise PXEAnswerError("PXE answer must be bytes or text")
    if not encoded or len(encoded) > MAX_ANSWER_BYTES:
        raise PXEAnswerError("PXE answer must be non-empty and at most 64 KiB")
    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_object)
    except PXEAnswerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PXEAnswerError(f"PXE answer is not valid UTF-8 JSON: {exc}") from exc
    return validate_pxe_answer(value)

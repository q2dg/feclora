"""Validated deployment-job contract shared by feclora Server and Client modes.

This module validates configuration only. It performs no networking, storage I/O,
service activation, or destructive operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import re
from typing import Any
from uuid import UUID


class JobValidationError(ValueError):
    """Raised when a deployment job is malformed or unsafe."""


_MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_IMAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_JOB_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_ALLOWED_FIELDS = {
    "schema_version",
    "job_id",
    "operation",
    "image_id",
    "target_type",
    "authorized_clients",
    "network_interface",
    "transport",
    "multicast_group",
    "multicast_port",
    "start_policy",
    "expected_clients",
    "start_deadline",
    "staging_required_bytes",
}


@dataclass(frozen=True)
class DeploymentJob:
    """Immutable, validated job description; never an authorization credential."""

    job_id: str
    operation: str
    image_id: str
    authorized_clients: tuple[str, ...]
    network_interface: str
    transport: str
    multicast_group: str | None
    multicast_port: int | None
    start_policy: str
    expected_clients: int | None
    start_deadline: str | None
    target_type: str = "disk"
    schema_version: int = 1
    staging_required_bytes: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeploymentJob":
        if not isinstance(payload, dict):
            raise JobValidationError("Job document must be a JSON object")
        unknown = set(payload) - _ALLOWED_FIELDS
        missing = _ALLOWED_FIELDS - set(payload) - {
            "multicast_group", "multicast_port", "expected_clients", "start_deadline", "target_type", "staging_required_bytes"
        }
        if unknown:
            raise JobValidationError(f"Unknown job fields: {', '.join(sorted(unknown))}")
        if missing:
            raise JobValidationError(f"Missing job fields: {', '.join(sorted(missing))}")

        if isinstance(payload.get("schema_version"), bool) or payload.get("schema_version") != 1:
            raise JobValidationError("Unsupported deployment job schema_version")

        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
            raise JobValidationError("job_id must be a UUID")
        try:
            job_id = str(UUID(job_id))
        except ValueError as exc:
            raise JobValidationError("job_id must be a valid UUID") from exc

        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in {"save", "restore"}:
            raise JobValidationError("operation must be 'save' or 'restore'")

        image_id = payload.get("image_id")
        if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
            raise JobValidationError("image_id must be a simple identifier, not a path")
        target_type = payload.get("target_type", "disk")
        if not isinstance(target_type, str) or target_type not in {"disk", "partition"}:
            raise JobValidationError("target_type must be disk or partition")
        if operation == "save" and target_type != "disk":
            raise JobValidationError("network save currently supports whole disks only")

        clients = payload.get("authorized_clients")
        if not isinstance(clients, list) or not clients:
            raise JobValidationError("authorized_clients must be a non-empty list of MAC addresses")
        normalized_clients: list[str] = []
        for mac in clients:
            if not isinstance(mac, str) or not _MAC_RE.fullmatch(mac):
                raise JobValidationError(f"Invalid client MAC address: {mac!r}")
            normalized = mac.lower()
            first_octet = int(normalized.split(":", 1)[0], 16)
            if first_octet & 1 or normalized == "00:00:00:00:00:00":
                raise JobValidationError(f"Client MAC must be a unicast hardware address: {mac!r}")
            if normalized in normalized_clients:
                raise JobValidationError(f"Duplicate authorized client: {normalized}")
            normalized_clients.append(normalized)

        interface = payload.get("network_interface")
        if not isinstance(interface, str) or not _INTERFACE_RE.fullmatch(interface):
            raise JobValidationError("network_interface must be a valid Linux interface name")

        transport = payload.get("transport")
        if not isinstance(transport, str) or transport not in {"unicast", "multicast"}:
            raise JobValidationError("transport must be 'unicast' or 'multicast'")

        group = payload.get("multicast_group")
        port = payload.get("multicast_port")
        if transport == "multicast":
            if not isinstance(group, str):
                raise JobValidationError("multicast_group must be an IPv4 multicast address")
            try:
                address = ipaddress.ip_address(group)
            except ValueError as exc:
                raise JobValidationError("multicast_group must be an IPv4 multicast address") from exc
            if address.version != 4 or address not in ipaddress.ip_network("239.0.0.0/8"):
                raise JobValidationError("multicast_group must be in administratively scoped 239.0.0.0/8")
            if (isinstance(port, bool) or not isinstance(port, int)
                    or not 1024 <= port <= 65534 or port % 2):
                raise JobValidationError("multicast_port must be an even UDPcast portbase between 1024 and 65534")
        elif group is not None or port is not None:
            raise JobValidationError("multicast_group/port are only valid for multicast transport")

        staging_required_bytes = payload.get("staging_required_bytes")
        if staging_required_bytes is not None and (
            isinstance(staging_required_bytes, bool)
            or not isinstance(staging_required_bytes, int)
            or not 0 <= staging_required_bytes <= (1 << 63) - 1
        ):
            raise JobValidationError("staging_required_bytes must be a non-negative 63-bit integer")
        if transport != "multicast" and staging_required_bytes is not None:
            raise JobValidationError("staging_required_bytes is only valid for multicast restore jobs")

        policy = payload.get("start_policy")
        if not isinstance(policy, str) or policy not in {"manual", "expected_clients", "deadline"}:
            raise JobValidationError("start_policy must be manual, expected_clients, or deadline")

        expected = payload.get("expected_clients")
        deadline = payload.get("start_deadline")
        if policy == "expected_clients":
            if isinstance(expected, bool) or not isinstance(expected, int) or not 1 <= expected <= len(normalized_clients):
                raise JobValidationError("expected_clients must be between 1 and the authorized client count")
            if deadline is not None:
                raise JobValidationError("start_deadline is only valid with deadline policy")
        elif policy == "deadline":
            if not isinstance(deadline, str):
                raise JobValidationError("start_deadline is required for deadline policy")
            try:
                parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            except ValueError as exc:
                raise JobValidationError("start_deadline must be an ISO-8601 timestamp") from exc
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise JobValidationError("start_deadline must include a UTC timezone")
            if expected is not None:
                raise JobValidationError("expected_clients is only valid with expected_clients policy")
            deadline = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        elif expected is not None or deadline is not None:
            raise JobValidationError("expected_clients/deadline conflict with manual start policy")

        return cls(
            job_id=job_id,
            operation=operation,
            image_id=image_id,
            authorized_clients=tuple(normalized_clients),
            network_interface=interface,
            transport=transport,
            multicast_group=str(group) if group is not None else None,
            multicast_port=port,
            start_policy=policy,
            expected_clients=expected,
            start_deadline=deadline,
            target_type=target_type,
            staging_required_bytes=staging_required_bytes,
        )

    @classmethod
    def from_json(cls, document: str) -> "DeploymentJob":
        try:
            payload = json.loads(document)
        except (TypeError, json.JSONDecodeError) as exc:
            raise JobValidationError("Job document is not valid JSON") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical schema-v1 representation."""
        document = {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "operation": self.operation,
            "image_id": self.image_id,
            "target_type": self.target_type,
            "authorized_clients": list(self.authorized_clients),
            "network_interface": self.network_interface,
            "transport": self.transport,
            "multicast_group": self.multicast_group,
            "multicast_port": self.multicast_port,
            "start_policy": self.start_policy,
            "expected_clients": self.expected_clients,
            "start_deadline": self.start_deadline,
        }
        # Keep pre-capacity schema-v1 journals byte-for-byte reconstructible.
        if self.staging_required_bytes is not None:
            document["staging_required_bytes"] = self.staging_required_bytes
        return document

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def authorizes_client(self, mac_address: str) -> bool:
        """Check membership only; this is not cryptographic authentication."""
        if not isinstance(mac_address, str) or not _MAC_RE.fullmatch(mac_address):
            return False
        return mac_address.lower() in self.authorized_clients

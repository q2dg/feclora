"""Validated deployment-job contract shared by feclora Server and Client modes.

This module validates configuration only. It performs no networking, storage I/O,
service activation, or destructive operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import os
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
    "source_device",
    "repository_id",
    "target_bindings",
}


@dataclass(frozen=True)
class DeploymentJob:
    """Immutable, validated job description; never an authorization credential."""

    job_id: str
    operation: str
    image_id: str | None
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
    source_device: str | None = None
    repository_id: str | None = None
    target_bindings: tuple[tuple[str, str | None, str | None], ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeploymentJob":
        if not isinstance(payload, dict):
            raise JobValidationError("Job document must be a JSON object")
        unknown = set(payload) - _ALLOWED_FIELDS
        missing = _ALLOWED_FIELDS - set(payload) - {
            "multicast_group", "multicast_port", "expected_clients", "start_deadline", "target_type", "staging_required_bytes", "source_device", "repository_id", "target_bindings"
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
        if not isinstance(operation, str) or operation not in {"save", "restore", "clone"}:
            raise JobValidationError("operation must be 'save', 'restore', or 'clone'")

        image_id = payload.get("image_id")
        if operation == "clone":
            if image_id is not None:
                raise JobValidationError("clone jobs must not reference an image_id")
        elif not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
            raise JobValidationError("image_id must be a simple identifier, not a path")

        repository_id = payload.get("repository_id")
        if repository_id is not None:
            if (operation != "restore" or not isinstance(repository_id, str)
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", repository_id)):
                raise JobValidationError("repository_id is valid only for restore jobs and must be a simple repository ID")
        source_device = payload.get("source_device")
        if operation == "clone":
            if (not isinstance(source_device, str)
                    or not re.fullmatch(r"/dev/[A-Za-z0-9_.!/+:-]{1,120}", source_device)
                    or ".." in source_device.split("/") or "//" in source_device
                    or any(ord(char) < 32 for char in source_device)
                    or os.path.normpath(source_device) != source_device):
                raise JobValidationError("clone source_device must be a normalized absolute /dev path")
        elif source_device is not None:
            raise JobValidationError("source_device is only valid for clone jobs")
        target_type = payload.get("target_type", "disk")
        if not isinstance(target_type, str) or target_type not in {"disk", "partition"}:
            raise JobValidationError("target_type must be disk or partition")
        if operation in {"save", "clone"} and target_type != "disk":
            raise JobValidationError("network save and clone currently support whole disks only")
        if operation == "clone" and (
            payload.get("transport") != "unicast" or payload.get("start_policy") != "manual"
        ):
            raise JobValidationError("clone jobs require unicast transport and manual start policy")

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

        raw_bindings = payload.get("target_bindings", {})
        if not isinstance(raw_bindings, dict) or len(raw_bindings) > len(normalized_clients):
            raise JobValidationError("target_bindings must map authorized Client MACs to stable WWN/serial selectors")
        bindings: list[tuple[str, str | None, str | None]] = []
        seen_binding_macs: set[str] = set()
        for raw_mac, selector in raw_bindings.items():
            if not isinstance(raw_mac, str) or not _MAC_RE.fullmatch(raw_mac):
                raise JobValidationError("target_bindings contains an invalid Client MAC")
            mac = raw_mac.lower()
            if mac not in normalized_clients or mac in seen_binding_macs:
                raise JobValidationError("target_bindings may reference each authorized Client only once")
            if not isinstance(selector, dict) or set(selector) != {"wwn", "serial"}:
                raise JobValidationError("each target binding must contain exactly wwn and serial")
            wwn, serial = selector["wwn"], selector["serial"]
            if wwn is None and serial is None:
                raise JobValidationError("each target binding requires a WWN, serial number, or both")
            for value, label in ((wwn, "WWN"), (serial, "serial")):
                if value is not None and (
                    not isinstance(value, str) or not value or len(value) > 256
                    or value != value.strip() or any(ord(char) < 32 for char in value)
                ):
                    raise JobValidationError(f"target binding {label} must be non-empty text without control characters")
            bindings.append((mac, wwn, serial))
            seen_binding_macs.add(mac)

        if bindings and seen_binding_macs != set(normalized_clients):
            raise JobValidationError("stable target bindings must cover every authorized Client in the job")
        if bindings and (operation != "restore" or target_type != "disk"):
            raise JobValidationError("stable WWN/serial target bindings currently require whole-disk restore jobs")

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
            source_device=source_device,
            repository_id=repository_id,
            target_bindings=tuple(sorted(bindings)),
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
        if self.source_device is not None:
            document["source_device"] = self.source_device
        if self.repository_id is not None:
            document["repository_id"] = self.repository_id
        if self.target_bindings:
            document["target_bindings"] = {
                mac: {"wwn": wwn, "serial": serial}
                for mac, wwn, serial in self.target_bindings
            }
        return document

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def authorizes_client(self, mac_address: str) -> bool:
        """Check membership only; this is not cryptographic authentication."""
        if not isinstance(mac_address, str) or not _MAC_RE.fullmatch(mac_address):
            return False
        return mac_address.lower() in self.authorized_clients

    def authorizes_target(self, mac_address: str, device: dict[str, Any]) -> bool:
        """Enforce an optional per-Client physical target binding.

        Jobs without a binding retain interactive target approval. A configured
        binding requires every supplied hardware identifier to match; transient
        /dev names are never used as identity.
        """
        if not isinstance(mac_address, str) or not self.authorizes_client(mac_address):
            return False
        selector = next(
            ((wwn, serial) for mac, wwn, serial in self.target_bindings
             if mac == mac_address.lower()),
            None,
        )
        if selector is None:
            return True
        if not isinstance(device, dict):
            return False
        wwn, serial = selector
        if wwn is not None:
            actual_wwn = device.get("wwn")
            if not isinstance(actual_wwn, str) or actual_wwn.strip().lower() != wwn.lower():
                return False
        if serial is not None:
            actual_serial = device.get("serial")
            if not isinstance(actual_serial, str) or actual_serial.strip() != serial:
                return False
        return True

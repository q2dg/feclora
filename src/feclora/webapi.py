"""Narrow, read-only Cockpit API for Feclora status and inventory.

The command accepts one bounded JSON request on stdin and returns one JSON
response. It deliberately exposes no shell, arbitrary argv, or destructive
storage/deployment operation.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import collect_inventory


class WebAPIError(RuntimeError):
    """A Cockpit API request was invalid or could not be fulfilled."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WebAPIError(f"duplicate request field: {key}")
        result[key] = value
    return result


def _images(repository: str = "/var/lib/feclora/images") -> list[dict[str, Any]]:
    path = Path(repository)
    if not path.exists():
        return []
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise WebAPIError("image repository is not a root-owned real directory")
    items = []
    for manifest_path in sorted(path.glob("*.manifest.json")):
        try:
            manifest = ImageManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError):
            continue
        items.append({
            "image_id": manifest.image_id,
            "image_type": manifest.image_type,
            "source_size_bytes": manifest.source_size_bytes,
            "signed": os.path.isfile(str(manifest_path) + ".minisig"),
            "encrypted": bool(manifest.artifacts) and all(
                artifact.encryption == "age" for artifact in manifest.artifacts
            ),
            "artifact_count": len(manifest.artifacts),
        })
    return items


def _service_state() -> dict[str, str]:
    services = {}
    for service in ("cockpit.socket", "feclora-dnsmasq.service", "feclora-caddy.service"):
        try:
            result = subprocess.run(
                ["/usr/bin/systemctl", "is-active", service],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=3,
            )
            services[service] = result.stdout.strip() or "inactive"
        except (OSError, subprocess.SubprocessError):
            services[service] = "unknown"
    return services


def dispatch(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) != {"action"}:
        raise WebAPIError("request must contain exactly one action field")
    action = request["action"]
    if action == "status":
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "server_configured": os.path.isfile("/etc/feclora/deployment-server.json"),
            "client_configured": os.path.isfile("/etc/feclora/deployment-client.json"),
            "services": _service_state(),
        }
    if action == "inventory":
        return collect_inventory()
    if action == "images":
        return {"images": _images()}
    if action == "journals":
        from feclora.deployment.journal import DeploymentJournal
        directory = Path("/var/lib/feclora/deployments")
        reports = []
        if directory.exists():
            info = os.lstat(directory)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                raise WebAPIError("deployment journal directory is unsafe")
            for journal_path in sorted(directory.glob("*.jsonl")):
                report = DeploymentJournal.inspect(journal_path).recovery_report()
                reports.append({
                    "job_id": report["job_id"],
                    "job_state": report["job_state"],
                    "interrupted": report["interrupted"],
                    "event_count": report["event_count"],
                    "clients": {
                        mac: item["state"] for mac, item in report["clients"].items()
                    },
                })
        return {"journals": reports}
    raise WebAPIError("unsupported Cockpit API action")


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "Feclora Cockpit API requires authorized root execution"}))
        return 1
    payload = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(payload) > 64 * 1024:
        print(json.dumps({"error": "request exceeds 64 KiB"}))
        return 2
    try:
        request = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        response = {"ok": True, "data": dispatch(request)}
    except (UnicodeError, json.JSONDecodeError, WebAPIError, Exception) as exc:
        response = {"ok": False, "error": str(exc)[:512]}
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Execute SFTP transfers inside a systemd encrypted-credential context.

The web/API process passes only encrypted blob paths to systemd-run. The
plaintext SSH key and known_hosts are materialized by systemd in the transient
service's private CREDENTIALS_DIRECTORY and are never placed in argv or env.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from feclora.storage.repository_manager import RemoteRepositoryManager, RepositoryManagerError
from feclora.storage.sftp_transfer import SFTPTransferError, upload_file, download_file


def credential_bindings(
    identity_credential: str, known_hosts_credential: str, *,
    manager: RemoteRepositoryManager | None = None,
) -> list[tuple[str, str]]:
    """Resolve exactly one encrypted ssh-key and known-hosts reference."""
    store_manager = manager or RemoteRepositoryManager()
    try:
        inventory = store_manager._load()
        from feclora.storage.systemd_credential_store import SystemdCredentialStore
        store = SystemdCredentialStore(
            store_manager.credential_root,
            effective_uid=store_manager.effective_uid,
            owner_uid=store_manager.owner_uid,
        )
        credentials = store.list()
    except Exception as exc:
        raise RepositoryManagerError(f"SFTP encrypted credential inventory is unavailable: {exc}") from exc
    by_path = {item["path"]: item for item in credentials}
    expected = ((identity_credential, "ssh-key"), (known_hosts_credential, "known-hosts"))
    bindings = []
    for path, kind in expected:
        item = by_path.get(path)
        if item is None or item["kind"] != kind:
            raise RepositoryManagerError(f"SFTP requires a registered encrypted {kind} credential")
        bindings.append((item["name"], item["path"]))
    return bindings


def build_systemd_transfer_argv(
    *, systemd_run: str, python: str, unit: str,
    bindings: list[tuple[str, str]], operation: str,
    host: str, username: str, remote_path: str, local_path: str,
    port: int = 22, expected_sha256: str | None = None,
) -> list[str]:
    """Build a transient service invocation; no plaintext secret is included."""
    if operation not in {"upload", "download"}:
        raise RepositoryManagerError("SFTP operation must be upload or download")
    if not unit.startswith("feclora-sftp-") or not unit.endswith(".service"):
        raise RepositoryManagerError("SFTP transient unit name is invalid")
    if len(bindings) != 2 or {name for name, _ in bindings} != {
        "feclora-" + Path(bindings[0][1]).stem.removesuffix("-ssh-key") + "-ssh-key",
        "feclora-" + Path(bindings[1][1]).stem.removesuffix("-known-hosts") + "-known-hosts",
    }:
        # The store validates names and kinds; this guard only rejects malformed
        # or duplicated binding lists before constructing systemd properties.
        if len({name for name, _ in bindings}) != 2:
            raise RepositoryManagerError("SFTP requires distinct key and known_hosts credentials")
    command = [
        systemd_run, f"--unit={unit}", "--wait", "--pipe", "--collect",
        "--property=User=root", "--property=Group=root",
        "--property=UMask=0077", "--property=NoNewPrivileges=yes",
    ]
    for name, path in bindings:
        command.append(f"--property=LoadCredentialEncrypted={name}:{path}")
    command.extend([
        "--setenv=PYTHONPATH=/usr/share/feclora/python", "--",
        python, "-m", "feclora.storage.sftp_transfer_service", operation,
        "--host", host, "--username", username, "--remote-path", remote_path,
        "--local-path", local_path, "--port", str(port),
    ])
    if expected_sha256 is not None:
        command.extend(["--expected-sha256", expected_sha256])
    return command


def _credential_path(name: str) -> str:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not directory or not os.path.isabs(directory):
        raise SFTPTransferError("systemd credential directory is unavailable")
    path = Path(directory) / name
    if not path.is_file() or path.is_symlink():
        raise SFTPTransferError("required SFTP service credential is unavailable")
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feclora-sftp-transfer")
    parser.add_argument("operation", choices=("upload", "download"))
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--local-path", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    try:
        directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if not directory:
            raise SFTPTransferError("SFTP transfer must run with systemd credentials")
        # Credential names are fixed by the registered store reference IDs
        # passed as environment-free service arguments by the unit wrapper.
        identity = os.environ.get("FECLORA_SFTP_IDENTITY_NAME", "")
        known_hosts = os.environ.get("FECLORA_SFTP_KNOWN_HOSTS_NAME", "")
        if not identity or not known_hosts or identity == known_hosts:
            raise SFTPTransferError("SFTP credential references are missing")
        key = _credential_path(identity)
        hosts = _credential_path(known_hosts)
        common = dict(
            host=args.host, username=args.username, identity_file=key,
            known_hosts_file=hosts, port=args.port,
        )
        if args.operation == "upload":
            upload_file(args.local_path, args.remote_path, **common)
        else:
            if not args.expected_sha256:
                raise SFTPTransferError("download requires the manifest SHA-256")
            download_file(
                args.remote_path, args.local_path,
                expected_sha256=args.expected_sha256, **common,
            )
        return 0
    except (OSError, SFTPTransferError) as exc:
        print(f"feclora-sftp-transfer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

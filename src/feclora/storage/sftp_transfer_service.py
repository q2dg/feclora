"""Execute SFTP transfers inside a systemd encrypted-credential context.

The web/API process passes only encrypted blob paths to systemd-run. The
plaintext SSH key and known_hosts are materialized by systemd in the transient
service's private CREDENTIALS_DIRECTORY and are never placed in argv or env.
"""
from __future__ import annotations

import argparse
import os
import re
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
    allow_unverified_metadata: bool = False,
) -> list[str]:
    """Build a transient service invocation; no plaintext secret is included."""
    if operation not in {"upload", "download"}:
        raise RepositoryManagerError("SFTP operation must be upload or download")
    if allow_unverified_metadata and (operation != "download" or expected_sha256 is not None):
        raise RepositoryManagerError("unverified metadata mode is only valid for digest-free downloads")
    if not isinstance(unit, str) or not re.fullmatch(r"feclora-sftp-[a-f0-9]{32}\.service", unit):
        raise RepositoryManagerError("SFTP transient unit name is invalid")
    if len(bindings) != 2:
        raise RepositoryManagerError("SFTP requires exactly two encrypted credentials")
    key_binding = next((item for item in bindings if item[0].endswith("-ssh-key")), None)
    hosts_binding = next((item for item in bindings if item[0].endswith("-known-hosts")), None)
    if key_binding is None or hosts_binding is None or key_binding == hosts_binding:
        raise RepositoryManagerError("SFTP requires distinct ssh-key and known-hosts credentials")
    for name, path in bindings:
        if (not re.fullmatch(r"feclora-[a-z0-9][a-z0-9-]{0,47}-(?:ssh-key|known-hosts)", name)
                or not os.path.isabs(path) or ":" in path or "\\n" in path
                or Path(path).name != name + ".cred"):
            raise RepositoryManagerError("SFTP encrypted credential binding is invalid")
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
        "--identity-credential-name", key_binding[0],
        "--known-hosts-credential-name", hosts_binding[0],
    ])
    if expected_sha256 is not None:
        command.extend(["--expected-sha256", expected_sha256])
    if allow_unverified_metadata:
        command.append("--allow-unverified-metadata")
    return command


def run_sftp_transfer(
    *, identity_credential: str, known_hosts_credential: str,
    operation: str, host: str, username: str, remote_path: str,
    local_path: str, port: int = 22, expected_sha256: str | None = None,
    allow_unverified_metadata: bool = False,
    manager: RemoteRepositoryManager | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Run one SFTP transfer in a synchronous transient systemd service."""
    store_manager = manager or RemoteRepositoryManager()
    bindings = credential_bindings(
        identity_credential, known_hosts_credential, manager=store_manager,
    )
    systemd_run = store_manager.which("systemd-run")
    python = store_manager.which("python3")
    if not systemd_run or not python:
        raise RepositoryManagerError("systemd-run and python3 are required for encrypted SFTP transfers")
    import uuid
    unit = f"feclora-sftp-{uuid.uuid4().hex}.service"
    command = build_systemd_transfer_argv(
        systemd_run=systemd_run, python=python, unit=unit, bindings=bindings,
        operation=operation, host=host, username=username,
        remote_path=remote_path, local_path=local_path, port=port,
        expected_sha256=expected_sha256,
        allow_unverified_metadata=allow_unverified_metadata,
    )
    try:
        result = runner(
            command, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, check=False, timeout=86430,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepositoryManagerError(f"SFTP transient service could not complete: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[:512]
        raise RepositoryManagerError("SFTP transfer failed" + (f": {detail}" if detail else ""))
    return {"operation": operation, "remote_path": remote_path, "completed": True}


def _credential_path(name: str) -> str:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not directory or not os.path.isabs(directory):
        raise SFTPTransferError("systemd credential directory is unavailable")
    path = Path(directory) / name
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise SFTPTransferError("required SFTP service credential is unavailable") from exc
    try:
        import stat
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise SFTPTransferError("systemd SFTP credential has unsafe ownership or permissions")
    finally:
        os.close(fd)
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feclora-sftp-transfer")
    parser.add_argument("operation", choices=("upload", "download"))
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--local-path", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--identity-credential-name", required=True)
    parser.add_argument("--known-hosts-credential-name", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--allow-unverified-metadata", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if not directory:
            raise SFTPTransferError("SFTP transfer must run with systemd credentials")
        # Credential names are fixed by the registered store reference IDs
        # passed as environment-free service arguments by the unit wrapper.
        identity = args.identity_credential_name
        known_hosts = args.known_hosts_credential_name
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
            if args.allow_unverified_metadata:
                from pathlib import PurePosixPath
                if (args.expected_sha256 is not None
                        or PurePosixPath(args.remote_path).name not in {"manifest.json", "manifest.json.minisig"}
                        or PurePosixPath(args.local_path).name not in {"manifest.json", "manifest.json.minisig"}):
                    raise SFTPTransferError("unverified download is restricted to manifest metadata files")
            elif not args.expected_sha256:
                raise SFTPTransferError("download requires a manifest SHA-256")
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

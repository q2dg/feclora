"""Provision encrypted systemd credentials from protected local source files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from feclora.storage.credential_cli import read_source_file
from feclora.storage.credential_store import CredentialStoreError
from feclora.storage.systemd_credential_store import (
    DEFAULT_ROOT, SystemdCredentialStore, SystemdCredentialStoreError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feclora-systemd-credential")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("put", help="Encrypt a protected local credential file")
    put.add_argument("--id", required=True)
    put.add_argument("--kind", required=True, choices=("ssh-key", "known-hosts", "smb"))
    put.add_argument("--source", required=True, help="Root-owned private source file")
    put.add_argument("--replace", action="store_true")
    remove = commands.add_parser("remove", help="Remove an encrypted credential")
    remove.add_argument("--id", required=True)
    remove.add_argument("--kind", required=True, choices=("ssh-key", "known-hosts", "smb", "rclone"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SystemdCredentialStore(args.root)
    try:
        if args.command == "put":
            source = read_source_file(args.source)
            reference = store.put(args.id, args.kind, source, replace=args.replace)
            print(reference["path"])
        else:
            store.remove(args.id, args.kind)
            print("Encrypted credential removed.")
        return 0
    except (CredentialStoreError, SystemdCredentialStoreError) as exc:
        print(f"feclora-systemd-credential: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

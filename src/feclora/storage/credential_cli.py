"""Local root-only CLI for importing and removing repository credentials."""
from __future__ import annotations
import argparse
import os
import stat
import sys
from pathlib import Path
from feclora.storage.credential_store import CredentialStore, CredentialStoreError, DEFAULT_ROOT


def read_source_file(path: str, *, owner_uid: int = 0) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CredentialStoreError("source file is unavailable or is a symlink") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid
                or info.st_mode & 0o077 or info.st_nlink != 1
                or info.st_size < 1 or info.st_size > 1024 * 1024):
            raise CredentialStoreError("source must be a root-owned private regular file (1 byte to 1 MiB)")
        chunks, remaining = [], 1024 * 1024 + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if not content or len(content) > 1024 * 1024 or b"\x00" in content:
            raise CredentialStoreError("source file content is invalid or too large")
        return content
    finally:
        os.close(fd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feclora-credential")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("put", help="Import a protected local credential file")
    put.add_argument("--id", required=True)
    put.add_argument("--kind", required=True, choices=("ssh-key", "known-hosts", "smb"))
    put.add_argument("--source", required=True, help="Root-owned private source file")
    put.add_argument("--replace", action="store_true")
    remove = commands.add_parser("remove", help="Remove a stored credential")
    remove.add_argument("--id", required=True)
    remove.add_argument("--kind", required=True, choices=("ssh-key", "known-hosts", "smb", "rclone"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = CredentialStore(args.root)
    try:
        if args.command == "put":
            print(store.put(args.id, args.kind, read_source_file(args.source), replace=args.replace))
        else:
            store.remove(args.id, args.kind)
            print("Credential removed.")
        return 0
    except CredentialStoreError as exc:
        print(f"feclora-credential: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

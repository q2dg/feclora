"""Run a repository mount inside a systemd service credential context."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from feclora.storage.repository_manager import (
    RemoteRepositoryManager, RepositoryManagerError, _repository,
)


def build_mount_argv(repo, bindings: list[tuple[str, str]], credential_directory: str) -> list[str]:
    """Build a provider command with encrypted blob paths replaced by service credentials."""
    if not credential_directory or not os.path.isabs(credential_directory):
        raise RepositoryManagerError("systemd credential directory is unavailable")
    names = {path: name for name, path in bindings}
    argv = repo.mount_argv()
    for index, value in enumerate(argv):
        name = names.get(value)
        if name is not None:
            argv[index] = str(Path(credential_directory) / name)
    if repo.provider == "sshfs":
        argv.insert(1, "-f")
    elif repo.provider == "s3":
        argv = [
            value for value in argv
            if value not in {"--daemon", "--daemon-wait", "60s"}
        ]
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feclora-repository-mount")
    parser.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        manager = RemoteRepositoryManager()
        entries = manager._load()
        if args.id not in entries:
            raise RepositoryManagerError("unknown repository ID")
        repo = _repository(args.id, entries[args.id])
        bindings = manager._encrypted_credential_bindings(repo)
        if not bindings:
            raise RepositoryManagerError("repository has no registered encrypted credentials")
        command = build_mount_argv(
            repo, bindings, os.environ.get("CREDENTIALS_DIRECTORY", ""),
        )
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, check=False,
        )
        return result.returncode
    except (OSError, subprocess.SubprocessError, RepositoryManagerError) as exc:
        print(f"feclora-repository-mount: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

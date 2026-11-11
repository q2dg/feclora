"""Pinned-host-key SFTP file transfer adapter.

This is deliberately separate from SSHFS: it transfers individual files over
OpenSSH SFTP and does not expose a mountpoint or pretend to be a filesystem.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class SFTPTransferError(RuntimeError):
    """A secure SFTP transfer could not be completed."""


_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REMOTE = re.compile(r"^/[A-Za-z0-9._/-]{1,1024}$")


def _credential(path: str, *, private: bool) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise SFTPTransferError("SFTP credential path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SFTPTransferError("SFTP credential is unavailable or is a symlink") from exc
    try:
        info = os.fstat(fd)
        unsafe = info.st_mode & (0o077 if private else 0o022)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or unsafe or info.st_nlink != 1):
            mode = "0600 or stricter" if private else "not group/other-writable"
            raise SFTPTransferError(f"SFTP credential must be root-owned, regular, {mode}, and unlinked")
    finally:
        os.close(fd)
    return path


def _remote_path(value: str) -> str:
    if not isinstance(value, str) or value.startswith("//") or not _REMOTE.fullmatch(value):
        raise SFTPTransferError("remote SFTP path must be absolute and contain only safe path characters")
    path = PurePosixPath(value)
    if ".." in path.parts or str(path) != value:
        raise SFTPTransferError("remote SFTP path must be normalized and must not traverse parent directories")
    return value


def _batch_quote(value: str) -> str:
    if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n\x00"):
        raise SFTPTransferError("SFTP batch path contains an unsupported control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_sftp_argv(
    *, host: str, username: str, identity_file: str, known_hosts_file: str,
    port: int = 22, executable: str = "sftp",
) -> list[str]:
    """Build a non-interactive OpenSSH SFTP command with pinned host keys."""
    if not isinstance(host, str) or not _HOST.fullmatch(host):
        raise SFTPTransferError("SFTP host is invalid")
    if not isinstance(username, str) or not _USER.fullmatch(username):
        raise SFTPTransferError("SFTP username is invalid")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SFTPTransferError("SFTP port must be between 1 and 65535")
    key = _credential(identity_file, private=True)
    known_hosts = _credential(known_hosts_file, private=False)
    return [
        executable, "-F", "/dev/null", "-b", "-", "-P", str(port),
        "-oBatchMode=yes", "-oIdentitiesOnly=yes", "-oPubkeyAuthentication=yes",
        "-oPasswordAuthentication=no", "-oKbdInteractiveAuthentication=no",
        "-oPreferredAuthentications=publickey", "-oStrictHostKeyChecking=yes",
        "-oGlobalKnownHostsFile=/dev/null", f"-oUserKnownHostsFile={known_hosts}", f"-oIdentityFile={key}",
        "-oConnectTimeout=15", "-oServerAliveInterval=15",
        "-oServerAliveCountMax=3", "-oClearAllForwardings=yes",
        f"{username}@{host}",
    ]


def _run_batch_result(
    argv: list[str], commands: list[str], *, runner: Callable[..., Any],
    timeout: int,
) -> Any:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise SFTPTransferError("SFTP timeout must be between 1 and 86400 seconds")
    try:
        result = runner(
            argv, input="\n".join(commands) + "\n",
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SFTPTransferError(f"SFTP process could not complete: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or "").strip().replace("\n", " ")[:512]
        raise SFTPTransferError(f"SFTP operation failed (exit {result.returncode}): {detail}")
    return result


def _run_batch(
    argv: list[str], commands: list[str], *, runner: Callable[..., Any],
    timeout: int,
) -> None:
    _run_batch_result(argv, commands, runner=runner, timeout=timeout)


def list_image_manifests(
    remote_directory: str, *, host: str, username: str,
    identity_file: str, known_hosts_file: str, port: int = 22,
    timeout: int = 120, runner: Callable[..., Any] = subprocess.run,
) -> list[str]:
    """List only Feclora image-manifest filenames in a pinned SFTP directory.

    The server's listing is untrusted input. Return only the fixed Feclora
    manifest marker or normalized image-id manifest basenames; never interpret
    entries as paths or commands.
    """
    if (not isinstance(remote_directory, str) or not _REMOTE.fullmatch(remote_directory)
            or remote_directory.startswith("//")
            or ".." in PurePosixPath(remote_directory).parts
            or str(PurePosixPath(remote_directory)) != remote_directory):
        raise SFTPTransferError("remote SFTP directory must be absolute and normalized")
    argv = build_sftp_argv(
        host=host, username=username, identity_file=identity_file,
        known_hosts_file=known_hosts_file, port=port,
    )
    result = _run_batch_result(
        argv, [f"ls -1 {_batch_quote(remote_directory)}"],
        runner=runner, timeout=timeout,
    )
    entries = set((result.stdout or "").splitlines())
    manifests = {
        name for name in entries
        if name == "manifest.json"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.manifest\.json", name)
    }
    # A manifest is the inventory/commit marker only when its detached
    # signature is also present. Publishers upload the manifest first and the
    # signature last, so concurrent readers must hide the in-progress window.
    return sorted(
        name for name in manifests
        if name + ".minisig" in entries
    )


def _local_regular(path: str | os.PathLike[str]) -> tuple[str, int, str, tuple[int, int, int, int, int]]:
    """Hash a regular file and capture metadata that detects replacement or mutation."""
    local = os.path.abspath(os.fspath(path))
    try:
        fd = os.open(local, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SFTPTransferError("local SFTP transfer source must be a regular file")
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        identity = lambda info: (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
        if identity(before) != identity(after) or size != after.st_size:
            raise SFTPTransferError("local SFTP transfer source changed while it was being hashed")
        return local, size, digest.hexdigest(), identity(after)
    except OSError as exc:
        raise SFTPTransferError(f"cannot safely read local transfer file: {exc}") from exc


def upload_file(
    local_path: str | os.PathLike[str], remote_path: str, *,
    host: str, username: str, identity_file: str, known_hosts_file: str,
    port: int = 22, timeout: int = 86400, runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Upload one regular file to a new remote name using a staged hard link that fails if the destination exists.

    SFTP v3 has no portable remote SHA-256 operation. The local source is
    hashed before transfer; remote publication creates a hard link only after put succeeds; the
    server must support the OpenSSH hard-link extension. Callers must still verify the published artifact via Feclora's
    signed manifest when it is later consumed.
    """
    local, size, digest, source_identity = _local_regular(local_path)
    target = _remote_path(remote_path)
    parent, name = target.rsplit("/", 1)
    if not name:
        raise SFTPTransferError("remote SFTP destination must name a file")
    staged = f"{parent}/.{name}.feclora-{secrets.token_hex(12)}.partial"
    argv = build_sftp_argv(
        host=host, username=username, identity_file=identity_file,
        known_hosts_file=known_hosts_file, port=port,
    )
    try:
        _run_batch(argv, [f"put {_batch_quote(local)} {_batch_quote(staged)}"],
                   runner=runner, timeout=timeout)
        # OpenSSH reopens the local pathname after our initial hash. Re-hash
        # and compare inode/timestamps before publishing the remote hard link,
        # so a replaced or modified source cannot be published under a stale
        # digest. A failed check leaves only a removable staging name.
        _local_after, size_after, digest_after, identity_after = _local_regular(local_path)
        if (size_after, digest_after, identity_after) != (size, digest, source_identity):
            raise SFTPTransferError("local SFTP transfer source changed during upload")
        _run_batch(argv, [f"ln {_batch_quote(staged)} {_batch_quote(target)}"],
                   runner=runner, timeout=timeout)
    except SFTPTransferError:
        try:
            _run_batch(argv, [f"rm {_batch_quote(staged)}"], runner=runner, timeout=min(timeout, 30))
        except SFTPTransferError:
            pass
        raise
    staging_removed = True
    try:
        _run_batch(argv, [f"rm {_batch_quote(staged)}"], runner=runner, timeout=min(timeout, 30))
    except SFTPTransferError:
        # The final hard link is already published. A leftover hidden staging
        # name is harmless and must not turn a successful publication into a
        # reported failure that would make retries collide with the final name.
        staging_removed = False
    return {"remote_path": target, "size_bytes": size, "sha256": digest,
            "published": True, "staging_removed": staging_removed}


def download_file(
    remote_path: str, local_path: str | os.PathLike[str], *,
    expected_sha256: str | None, host: str, username: str, identity_file: str,
    known_hosts_file: str, port: int = 22, timeout: int = 86400,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Download privately; when supplied, require the expected SHA-256 before publication.

Only callers handling untrusted manifest/signature metadata may omit the
expected digest; they must authenticate that metadata before trusting it.
"""
    target = _remote_path(remote_path)
    if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise SFTPTransferError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    destination = Path(os.path.abspath(os.fspath(local_path)))
    if destination.exists() or destination.is_symlink():
        raise SFTPTransferError("local SFTP destination already exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = os.lstat(destination.parent)
    if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
            or parent_info.st_mode & 0o077):
        raise SFTPTransferError("local SFTP destination parent must be a private real directory")
    try:
        if destination.parent.resolve(strict=True) != destination.parent:
            raise SFTPTransferError("local SFTP destination path must not traverse symlinked directories")
    except OSError as exc:
        raise SFTPTransferError("local SFTP destination parent is unavailable") from exc
    temporary = destination.parent / f".{destination.name}.feclora-{secrets.token_hex(12)}.partial"
    argv = build_sftp_argv(
        host=host, username=username, identity_file=identity_file,
        known_hosts_file=known_hosts_file, port=port,
    )
    try:
        _run_batch(argv, [f"get {_batch_quote(target)} {_batch_quote(str(temporary))}"],
                   runner=runner, timeout=timeout)
        fd = os.open(temporary, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SFTPTransferError("downloaded SFTP artifact is not a regular file")
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise SFTPTransferError("downloaded SFTP artifact SHA-256 does not match its signed manifest")
        os.link(temporary, destination, follow_symlinks=False)
        os.unlink(temporary)
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {"local_path": str(destination), "size_bytes": size, "sha256": digest.hexdigest(), "verified": expected_sha256 is not None}
    except (OSError, SFTPTransferError) as exc:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        if isinstance(exc, SFTPTransferError):
            raise
        raise SFTPTransferError(f"could not publish downloaded SFTP artifact: {exc}") from exc

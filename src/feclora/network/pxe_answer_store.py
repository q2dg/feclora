"""Publish validated, job-scoped PXE JSON answers into the Caddy document root."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from feclora.network.pxe_answer import PXEAnswerError, parse_pxe_answer


class PXEAnswerStoreError(RuntimeError):
    """A PXE answer could not be safely published or revoked."""


def _safe_root(path: str | os.PathLike[str]) -> Path:
    root = Path(path)
    try:
        info = root.lstat()
    except OSError as exc:
        raise PXEAnswerStoreError(f"PXE HTTP root is unavailable: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_mode & 0o005 != 0o005):
        raise PXEAnswerStoreError(
            "PXE HTTP root must be a real directory owned by the publisher and not group/other-writable"
        )
    return root


def _job_id(value: str) -> str:
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PXEAnswerStoreError("PXE answer job ID must be a UUID") from exc
    if canonical != value:
        raise PXEAnswerStoreError("PXE answer job ID must use canonical UUID notation")
    return canonical


def publish_pxe_answer(
    http_root: str | os.PathLike[str],
    job_id: str,
    raw_answer: bytes,
    *,
    address: str,
    http_port: int = 8080,
) -> dict[str, str]:
    """Atomically publish a validated JSON answer for retrieval over HTTP."""
    canonical_job_id = _job_id(job_id)
    root = _safe_root(http_root)
    try:
        parsed_address = ipaddress.ip_address(address)
    except ValueError as exc:
        raise PXEAnswerStoreError("PXE answer URL address must be an IP address") from exc
    if parsed_address.version != 4 or parsed_address.is_unspecified or parsed_address.is_loopback or parsed_address.is_multicast:
        raise PXEAnswerStoreError("PXE answer URL address must be usable unicast IPv4")
    if isinstance(http_port, bool) or not isinstance(http_port, int) or not 1 <= http_port <= 65535:
        raise PXEAnswerStoreError("PXE answer HTTP port is invalid")
    try:
        answer = parse_pxe_answer(raw_answer)
    except PXEAnswerError as exc:
        raise PXEAnswerStoreError(f"PXE answer validation failed: {exc}") from exc
    if "expires_at" in answer:
        raise PXEAnswerStoreError("PXE answer expiry is assigned by the Server, not the uploaded document")
    answer["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_answer = (json.dumps(answer, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    answers = root / "answers"
    answers.mkdir(mode=0o755, exist_ok=True)
    info = answers.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_mode & 0o005 != 0o005):
        raise PXEAnswerStoreError("PXE answers directory is unsafe")
    destination = answers / canonical_job_id
    if os.path.lexists(destination):
        raise PXEAnswerStoreError("an answer document is already published for this job")

    temporary = Path(tempfile.mkdtemp(prefix=".answer-", dir=answers))
    try:
        answer_path = temporary / "answer.json"
        fd = os.open(answer_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o444)
        with os.fdopen(fd, "wb") as output:
            output.write(raw_answer)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(answer_path, 0o444)
        os.chmod(temporary, 0o555)
        os.rename(temporary, destination)
        directory_fd = os.open(answers, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise PXEAnswerStoreError("another answer document was published concurrently") from exc
    except OSError as exc:
        raise PXEAnswerStoreError(f"cannot atomically publish PXE answer: {exc}") from exc
    finally:
        if temporary.exists():
            os.chmod(temporary, 0o700)
            shutil.rmtree(temporary, ignore_errors=True)

    base = f"http://{parsed_address}:{http_port}/answers/{canonical_job_id}"
    return {"answer_url": base + "/answer.json", "directory": str(destination)}

def clear_stale_pxe_answers(http_root: str | os.PathLike[str]) -> int:
    """Remove all safely published answer directories before a new PXE session."""
    root = _safe_root(http_root)
    answers = root / "answers"
    try:
        info = answers.lstat()
    except FileNotFoundError:
        return 0
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_mode & 0o005 != 0o005):
        raise PXEAnswerStoreError("PXE answers directory is unsafe")
    removed = 0
    for destination in answers.iterdir():
        canonical_job_id = _job_id(destination.name)
        directory_info = destination.lstat()
        if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid()):
            raise PXEAnswerStoreError("PXE answer job path is not a safe directory")
        if {item.name for item in destination.iterdir()} != {"answer.json"}:
            raise PXEAnswerStoreError(f"PXE answer {canonical_job_id} contains unexpected or missing files")
        for name in ("answer.json",):
            item = destination / name
            item_info = item.lstat()
            if (not stat.S_ISREG(item_info.st_mode) or stat.S_ISLNK(item_info.st_mode)
                    or item_info.st_uid != os.geteuid()):
                raise PXEAnswerStoreError(f"PXE answer {canonical_job_id} contains an unsafe file")
        os.chmod(destination, 0o700)
        for item in destination.iterdir():
            os.chmod(item, 0o600)
        shutil.rmtree(destination)
        removed += 1
    if removed:
        directory_fd = os.open(answers, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return removed



def revoke_pxe_answer(http_root: str | os.PathLike[str], job_id: str) -> bool:
    """Revoke only the selected job's answer directory, refusing unsafe contents."""
    canonical_job_id = _job_id(job_id)
    root = _safe_root(http_root)
    answers = root / "answers"
    try:
        info = answers.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_mode & 0o005 != 0o005):
        raise PXEAnswerStoreError("PXE answers directory is unsafe")
    destination = answers / canonical_job_id
    try:
        directory_info = destination.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
            or directory_info.st_uid != os.geteuid()):
        raise PXEAnswerStoreError("PXE answer job path is not a safe directory")
    for name in ("answer.json",):
        item = destination / name
        try:
            item_info = item.lstat()
        except FileNotFoundError:
            raise PXEAnswerStoreError("PXE answer publication is incomplete; refusing recursive removal")
        if not stat.S_ISREG(item_info.st_mode) or stat.S_ISLNK(item_info.st_mode) or item_info.st_uid != os.geteuid():
            raise PXEAnswerStoreError("PXE answer publication contains an unsafe file")
    if {item.name for item in destination.iterdir()} != {"answer.json"}:
        raise PXEAnswerStoreError("PXE answer publication contains unexpected files")
    os.chmod(destination, 0o700)
    for item in destination.iterdir():
        os.chmod(item, 0o600)
    shutil.rmtree(destination)
    directory_fd = os.open(answers, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return True

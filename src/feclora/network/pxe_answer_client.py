"""Fetch and validate the shared HTTP PXE answer in the Fedora Live session.

This first Live-side stage deliberately performs no disk writes. It retrieves
only the bounded declarative JSON, validates its schema, and stores it in a
root-only runtime directory for the restore coordinator.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from feclora.network.pxe_answer import MAX_ANSWER_BYTES, parse_pxe_answer
from feclora.network.pxe_boot_request import (
    PXEBootRequestError,
    parse_pxe_boot_request,
)


class PXEAnswerClientError(RuntimeError):
    """The Live client could not safely retrieve its PXE answer."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _download_answer(url: str, *, timeout: float = 15.0) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Feclora-PXE/1"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise PXEAnswerClientError(f"PXE answer server returned HTTP {response.status}")
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "application/octet-stream"}:
                raise PXEAnswerClientError("PXE answer server returned an unexpected content type")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > MAX_ANSWER_BYTES:
                        raise PXEAnswerClientError("PXE answer exceeds the 64 KiB size limit")
                except ValueError as exc:
                    raise PXEAnswerClientError("PXE answer server returned an invalid Content-Length") from exc
            chunks = bytearray()
            while len(chunks) <= MAX_ANSWER_BYTES:
                chunk = response.read(min(8192, MAX_ANSWER_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if not chunks or len(chunks) > MAX_ANSWER_BYTES:
                raise PXEAnswerClientError("PXE answer must be non-empty and at most 64 KiB")
            return bytes(chunks)
    except PXEAnswerClientError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise PXEAnswerClientError(f"cannot download PXE answer over HTTP: {exc}") from exc


def _publish_runtime_answer(raw: bytes, destination: str | os.PathLike[str]) -> Path:
    target = Path(destination)
    parent = target.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_info = os.lstat(parent)
        if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
                or parent_info.st_uid != 0 or parent_info.st_mode & 0o077):
            raise PXEAnswerClientError("PXE runtime answer directory must be root-owned and mode 0700")
        if os.path.lexists(target):
            info = os.lstat(target)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                raise PXEAnswerClientError("existing PXE runtime answer path is unsafe")
        fd, temporary = tempfile.mkstemp(prefix=".answer-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    except PXEAnswerClientError:
        raise
    except OSError as exc:
        raise PXEAnswerClientError(f"cannot safely store PXE answer in Live runtime: {exc}") from exc
    return target


def fetch_live_pxe_answer(
    command_line: str | None = None,
    *,
    destination: str | os.PathLike[str] = "/run/feclora/pxe/answer.json",
    downloader: Any = _download_answer,
) -> dict[str, Any] | None:
    """Fetch/validate the unattended answer; interactive PXE boots are a no-op."""
    if command_line is None:
        try:
            command_line = Path("/proc/cmdline").read_text(encoding="ascii")
        except OSError as exc:
            raise PXEAnswerClientError(f"cannot read Live kernel command line: {exc}") from exc
    try:
        request = parse_pxe_boot_request(command_line)
    except PXEBootRequestError as exc:
        raise PXEAnswerClientError(f"invalid PXE boot handoff: {exc}") from exc
    if request.mode == "interactive":
        return None
    if not request.answer_url:
        raise PXEAnswerClientError("unattended PXE boot has no answer URL")
    raw = downloader(request.answer_url)
    answer = parse_pxe_answer(raw)
    _publish_runtime_answer(raw, destination)
    return answer


def main() -> int:
    try:
        answer = fetch_live_pxe_answer()
    except (PXEAnswerClientError, ValueError, OSError) as exc:
        print(f"feclora-pxe-answer: {exc}", file=sys.stderr)
        return 1
    if answer is None:
        return 0
    print(
        "PXE answer downloaded and validated "
        f"(image_id={answer['image_id']}); restore execution is not enabled by this stage."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

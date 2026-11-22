"""Unprivileged Textual-to-root API client."""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

SUDO = "/usr/bin/sudo"
API_HELPER = "/usr/libexec/feclora/feclora-api"
MAX_REQUEST = 128 * 1024
MAX_RESPONSE_LINE = 32 * 1024 * 1024
MAX_ERROR_OUTPUT = 16 * 1024


class TUIAPIError(RuntimeError):
    """The privileged Feclora API could not complete a request."""


async def _read_limited(reader: asyncio.StreamReader, limit: int) -> bytes:
    collected = bytearray()
    while chunk := await reader.read(4096):
        remaining = limit - len(collected)
        if remaining > 0:
            collected.extend(chunk[:remaining])
    return bytes(collected)


def _request_bytes(action: str, params: dict[str, Any]) -> bytes:
    if not isinstance(action, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
        raise TUIAPIError("invalid Feclora API action")
    if not isinstance(params, dict):
        raise TUIAPIError("Feclora API parameters must be an object")
    try:
        payload = json.dumps(
            {"action": action, "params": params},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise TUIAPIError("Feclora API parameters are not JSON serializable") from exc
    if len(payload) > MAX_REQUEST:
        raise TUIAPIError("Feclora API request exceeds the size limit")
    return payload


async def call_feclora(
    action: str,
    params: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """Call one allowlisted action through sudo and stream progress events."""
    payload = _request_bytes(action, {} if params is None else params)
    try:
        process = await asyncio.create_subprocess_exec(
            SUDO,
            "-n",
            API_HELPER,
            action,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_RESPONSE_LINE,
        )
    except OSError as exc:
        raise TUIAPIError("cannot start the privileged Feclora API helper") from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_task = asyncio.create_task(_read_limited(process.stderr, MAX_ERROR_OUTPUT))
    result: dict[str, Any] | None = None
    try:
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
        while line := await process.stdout.readline():
            if len(line) > MAX_RESPONSE_LINE:
                raise TUIAPIError("Feclora API response exceeds the size limit")
            try:
                message = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TUIAPIError("Feclora API returned invalid JSON") from exc
            if not isinstance(message, dict):
                raise TUIAPIError("Feclora API returned an invalid response")
            if message.get("event"):
                if on_event is not None:
                    on_event(message)
            else:
                result = message
        return_code = await process.wait()
        stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        if return_code != 0:
            detail = result.get("error") if result else None
            raise TUIAPIError(detail or stderr or f"Feclora API exited with status {return_code}")
        if result is None or result.get("ok") is not True or "data" not in result:
            detail = result.get("error") if result else None
            raise TUIAPIError(detail or "Feclora API did not return a result")
        return result["data"]
    except BaseException:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
        raise

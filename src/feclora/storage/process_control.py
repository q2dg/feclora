"""Bounded shutdown helpers for storage subprocesses."""
from __future__ import annotations

import subprocess
from typing import Any


def stop_process(process: Any, *, grace_seconds: float = 5.0) -> None:
    """Terminate a child, wait briefly, then kill and reap it if necessary."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
        return
    except TypeError:
        # Small test doubles and older process adapters may not accept timeout.
        process.wait()
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
    except TypeError:
        process.wait()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("storage child process did not exit after SIGKILL") from exc

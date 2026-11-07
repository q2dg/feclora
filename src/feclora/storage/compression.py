"""Bounded streaming adapters for system zstd and lz4 command-line tools."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Any


class CompressionError(RuntimeError):
    """An external compression process is unavailable or failed."""


def executable_for(compression: str, executables: dict[str, str | None] | None = None) -> str:
    name = {"zstd": "zstd", "lz4": "lz4"}.get(compression)
    if name is None:
        raise CompressionError(f"no external codec for {compression!r}")
    available = executables or {}
    executable = available.get(name) or shutil.which(name)
    if not executable:
        raise CompressionError(f"{name} is required for {compression} compression")
    return executable


class ExternalDecompressionStream:
    """Read a codec's stdout while it consumes the supplied stream on stdin."""

    def __init__(self, source: Any, compression: str, executables: dict[str, str | None] | None = None):
        executable = executable_for(compression, executables)
        self._stderr = tempfile.TemporaryFile(mode="w+b")
        args = [executable, "-q", "-d", "-c"]
        try:
            self._process = subprocess.Popen(
                args, stdin=source, stdout=subprocess.PIPE, stderr=self._stderr,
                close_fds=True,
            )
        except OSError as exc:
            self._stderr.close()
            raise CompressionError(f"could not start {compression} decompressor: {exc}") from exc
        if self._process.stdout is None:
            self._process.terminate()
            self._process.wait()
            self._stderr.close()
            raise CompressionError(f"{compression} decompressor did not provide output")

    def read(self, size: int = -1) -> bytes:
        return self._process.stdout.read(size)

    def finish(self) -> None:
        if self._process.stdout is not None:
            self._process.stdout.close()
            self._process.stdout = None
        result = self._process.wait()
        self._stderr.seek(0)
        detail = self._stderr.read(8192).decode("utf-8", errors="replace").strip()
        self._stderr.close()
        if result != 0:
            raise CompressionError(
                f"decompressor exited with status {result}" + (f": {detail}" if detail else "")
            )

    def close(self) -> None:
        if self._process.stdout is not None:
            self._process.stdout.close()
            self._process.stdout = None
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        if not self._stderr.closed:
            self._stderr.close()

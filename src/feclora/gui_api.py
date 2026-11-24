"""Thread-safe bridge between CustomTkinter and Feclora's async privileged API.

Tk owns the main thread. API subprocesses run in a small worker pool and
communicate back through a queue; worker threads never call Tk methods.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from typing import Any, Callable

from feclora.tui_api import TUIAPIError, call_feclora

Callback = Callable[..., None]


class TkAPIClient:
    """Dispatch allowlisted API calls without blocking the Tk event loop."""

    def __init__(
        self,
        root: Any,
        *,
        poll_interval_ms: int = 40,
        max_workers: int = 2,
    ) -> None:
        if poll_interval_ms < 1:
            raise ValueError("poll_interval_ms must be positive")
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._root = root
        self._poll_interval_ms = poll_interval_ms
        self._queue: Queue[tuple[Callback | None, tuple[Any, ...]]] = Queue()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="feclora-api",
        )
        self._closed = False
        self._poll_id: Any = self._root.after(self._poll_interval_ms, self._drain)

    def submit(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        on_success: Callback | None = None,
        on_event: Callback | None = None,
        on_error: Callback | None = None,
    ) -> Future[Any]:
        """Run an API request and deliver callbacks on Tk's main thread."""
        if self._closed:
            raise RuntimeError("TkAPIClient is closed")

        def run() -> Any:
            try:
                result = asyncio.run(
                    call_feclora(
                        action,
                        params,
                        on_event=(
                            (lambda event: self._queue.put((on_event, (event,))))
                            if on_event is not None
                            else None
                        ),
                    )
                )
            except Exception as exc:
                if on_error is not None:
                    self._queue.put((on_error, (exc,)))
                else:
                    self._queue.put((None, ()))
                raise
            else:
                if on_success is not None:
                    self._queue.put((on_success, (result,)))
                return result

        return self._executor.submit(run)

    def _drain(self) -> None:
        if self._closed:
            return
        while True:
            try:
                callback, args = self._queue.get_nowait()
            except Empty:
                break
            if callback is not None:
                callback(*args)
        if not self._closed:
            self._poll_id = self._root.after(self._poll_interval_ms, self._drain)

    def close(self) -> None:
        """Stop polling and prevent new work; in-flight subprocesses may finish."""
        if self._closed:
            return
        self._closed = True
        try:
            self._root.after_cancel(self._poll_id)
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["TkAPIClient", "TUIAPIError"]

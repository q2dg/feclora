"""Thread-safe bridge from the GTK main loop to Feclora's privileged API."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from feclora.tui_api import call_feclora

Callback = Callable[..., None]
Dispatcher = Callable[[Callable[[], bool]], Any]


class GtkAPIClient:
    """Run API subprocesses in workers and marshal callbacks onto GLib."""

    def __init__(self, *, max_workers: int = 2, dispatch: Dispatcher | None = None) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if dispatch is None:
            from gi.repository import GLib
            dispatch = GLib.idle_add
        self._dispatch = dispatch
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="feclora-api")
        self._closed = False

    def submit(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        on_success: Callback | None = None,
        on_event: Callback | None = None,
        on_error: Callback | None = None,
    ) -> Future[Any]:
        if self._closed:
            raise RuntimeError("GtkAPIClient is closed")

        def deliver(callback: Callback, value: Any) -> None:
            def invoke() -> bool:
                if not self._closed:
                    callback(value)
                return False
            self._dispatch(invoke)

        def run() -> Any:
            try:
                result = asyncio.run(
                    call_feclora(
                        action,
                        params,
                        on_event=(lambda event: deliver(on_event, event)) if on_event else None,
                    )
                )
            except Exception as exc:
                if on_error:
                    deliver(on_error, exc)
                raise
            if on_success:
                deliver(on_success, result)
            return result

        return self._executor.submit(run)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["GtkAPIClient"]

"""Small TLS socket helpers for remote disk-clone endpoints."""
from __future__ import annotations

import socket
import ssl
import time
from typing import Any, Callable

from .remote_clone_protocol import RemoteCloneCancelled, verify_peer_identity


def connect_mutual_tls(
    context: ssl.SSLContext,
    host: str,
    port: int,
    *,
    expected_peer_identity: str,
    timeout: float = 15.0,
    io_timeout: float = 120.0,
    cancel_check: Callable[[], bool] | None = None,
    connect_poll_interval: float = 0.25,
) -> ssl.SSLSocket:
    """Connect to a TLS server, polling cancellation during the TCP connect phase."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
            or isinstance(connect_poll_interval, bool)
            or not isinstance(connect_poll_interval, (int, float))
            or not 0.05 <= connect_poll_interval <= 5.0):
        raise ValueError("connection timeout and polling interval must be positive and bounded")
    deadline = time.monotonic() + timeout
    raw = None
    while raw is None:
        if cancel_check is not None and cancel_check():
            raise RemoteCloneCancelled("remote clone cancelled while connecting to receiver")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("timed out connecting to remote clone receiver")
        try:
            raw = socket.create_connection(
                (host, port), timeout=min(float(connect_poll_interval), remaining),
            )
        except socket.timeout:
            continue
    try:
        wrapped = context.wrap_socket(raw, server_hostname=host)
        wrapped.settimeout(io_timeout)
        verify_peer_identity(wrapped, expected_peer_identity)
        return wrapped
    except Exception:
        raw.close()
        raise


def accept_mutual_tls(
    context: ssl.SSLContext,
    accepted_socket: socket.socket,
    *,
    expected_peer_identity: str,
    io_timeout: float = 120.0,
) -> ssl.SSLSocket:
    """Complete server-side mTLS on an accepted socket and verify the client identity."""
    try:
        accepted_socket.settimeout(io_timeout)
        wrapped = context.wrap_socket(accepted_socket, server_side=True)
        wrapped.settimeout(io_timeout)
        verify_peer_identity(wrapped, expected_peer_identity)
        return wrapped
    except Exception:
        accepted_socket.close()
        raise

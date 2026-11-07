"""Small TLS socket helpers for remote disk-clone endpoints."""
from __future__ import annotations

import socket
import ssl
from typing import Any

from .remote_clone_protocol import verify_peer_identity


def connect_mutual_tls(
    context: ssl.SSLContext,
    host: str,
    port: int,
    *,
    expected_peer_identity: str,
    timeout: float = 15.0,
    io_timeout: float = 120.0,
) -> ssl.SSLSocket:
    """Connect to a TLS server, require its client certificate, and pin its exact identity."""
    raw = socket.create_connection((host, port), timeout=timeout)
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

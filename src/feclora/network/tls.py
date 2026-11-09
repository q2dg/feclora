"""Small TLS socket helpers for remote disk-clone endpoints."""
from __future__ import annotations

import socket
import ssl
import subprocess
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
    source_address: str | None = None,
    network_interface: str | None = None,
) -> ssl.SSLSocket:
    """Connect to a TLS server, polling cancellation during the TCP connect phase."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
            or isinstance(connect_poll_interval, bool)
            or not isinstance(connect_poll_interval, (int, float))
            or not 0.05 <= connect_poll_interval <= 5.0):
        raise ValueError("connection timeout and polling interval must be positive and bounded")
    if source_address is not None:
        try:
            parsed_source = socket.inet_pton(socket.AF_INET, source_address)
        except OSError as exc:
            raise ValueError("source_address must be a valid IPv4 address") from exc
    else:
        parsed_source = None
    if network_interface is not None:
        if (not isinstance(network_interface, str)
                or not __import__("re").fullmatch(r"[A-Za-z0-9_.:-]{1,15}", network_interface)
                or source_address is None):
            raise ValueError("network_interface requires a valid selected interface and source_address")
    deadline = time.monotonic() + timeout
    raw = None
    while raw is None:
        if cancel_check is not None and cancel_check():
            raise RemoteCloneCancelled("remote clone cancelled while connecting to receiver")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("timed out connecting to remote clone receiver")
        if network_interface is not None:
            try:
                destinations = sorted({item[4][0] for item in socket.getaddrinfo(
                    host, port, socket.AF_INET, socket.SOCK_STREAM
                )})
                if not destinations:
                    raise OSError("Server hostname has no IPv4 addresses")
                for destination in destinations:
                    route = subprocess.run(
                        ["/usr/sbin/ip", "-4", "route", "get", destination,
                         "from", source_address],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                        check=False, timeout=3,
                    )
                    if route.returncode != 0:
                        raise OSError("cannot resolve route to Server through selected Client interface")
                    fields = route.stdout.split()
                    if ("dev" not in fields or fields[fields.index("dev") + 1] != network_interface
                            or "src" not in fields or fields[fields.index("src") + 1] != source_address):
                        raise OSError(
                            f"kernel route to {destination} does not use selected interface "
                            f"{network_interface} and source address {source_address}"
                        )
            except (OSError, subprocess.SubprocessError, IndexError) as exc:
                raise OSError(f"selected Client network route is unavailable: {exc}") from exc
        try:
            raw = socket.create_connection(
                (host, port), timeout=min(float(connect_poll_interval), remaining),
                source_address=(source_address, 0) if parsed_source is not None else None,
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

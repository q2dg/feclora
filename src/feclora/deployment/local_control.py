"""Root-only Unix-socket IPC primitives for the Feclora deployment service."""
from __future__ import annotations

import json
import os
import socket
import stat
import struct
import threading
from pathlib import Path
from typing import Any, Callable

MAX_FRAME = 16 * 1024
_ALLOWED_ACTIONS = {"status", "arm", "cancel"}


class LocalControlError(RuntimeError):
    """Local deployment IPC failed or violated its security policy."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LocalControlError(f"duplicate IPC field: {key}")
        result[key] = value
    return result


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise LocalControlError("IPC peer closed the connection")
        data.extend(chunk)
    return bytes(data)


def _receive(connection: socket.socket) -> dict[str, Any]:
    size = struct.unpack("!I", _recv_exact(connection, 4))[0]
    if not 1 <= size <= MAX_FRAME:
        raise LocalControlError("invalid IPC frame length")
    try:
        request = json.loads(
            _recv_exact(connection, size).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LocalControlError(f"invalid IPC JSON: {exc}") from exc
    if not isinstance(request, dict) or set(request) != {"action", "params"}:
        raise LocalControlError("IPC request must contain exactly action and params")
    if request["action"] not in _ALLOWED_ACTIONS or not isinstance(request["params"], dict):
        raise LocalControlError("unsupported IPC action or invalid parameters")
    if request["action"] == "status" and request["params"]:
        raise LocalControlError("status does not accept parameters")
    if request["action"] in {"arm", "cancel"} and set(request["params"]) != {"job_id", "confirmation"}:
        raise LocalControlError("arm and cancel require exactly job_id and confirmation")
    return request


def _send(connection: socket.socket, response: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise LocalControlError(f"IPC response is not serializable: {exc}") from exc
    if not encoded or len(encoded) > MAX_FRAME:
        raise LocalControlError("IPC response exceeds the frame limit")
    connection.sendall(struct.pack("!I", len(encoded)) + encoded)


class LocalControlServer:
    """Single-request, root-peer-only Unix socket server.

    The caller owns command semantics and must still validate job identity,
    current state and the typed operator confirmation before any transition.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        handler: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        allowed_uid: int = 0,
    ) -> None:
        if not callable(handler):
            raise LocalControlError("IPC handler must be callable")
        if not isinstance(allowed_uid, int) or isinstance(allowed_uid, bool) or allowed_uid < 0:
            raise LocalControlError("invalid IPC peer UID")
        self.path = os.path.abspath(os.fspath(path))
        if len(self.path.encode()) >= 104:
            raise LocalControlError("Unix socket path is too long")
        self.handler = handler
        self.allowed_uid = allowed_uid
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._socket_identity: tuple[int, int] | None = None

    def start(self) -> None:
        if self._listener is not None:
            raise LocalControlError("IPC listener is already running")
        parent = os.path.dirname(self.path)
        info = os.lstat(parent)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o022):
            raise LocalControlError("IPC parent must be a root-owned non-writable directory")
        try:
            os.lstat(self.path)
        except FileNotFoundError:
            pass
        else:
            raise LocalControlError("IPC socket path already exists; refusing to replace it")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound_identity = None
        try:
            listener.bind(self.path)
            info = os.lstat(self.path)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise LocalControlError("bound IPC path is not an owned Unix socket")
            bound_identity = (info.st_dev, info.st_ino)
            os.chmod(self.path, 0o600)
            listener.listen(8)
            listener.settimeout(0.5)
        except Exception:
            listener.close()
            if bound_identity is not None:
                try:
                    info = os.lstat(self.path)
                    if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == bound_identity:
                        os.unlink(self.path)
                except OSError:
                    pass
            raise
        self._socket_identity = bound_identity
        self._listener = listener
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="feclora-local-control", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    continue
                break
            with connection:
                connection.settimeout(5)
                try:
                    if not hasattr(socket, "SO_PEERCRED"):
                        raise LocalControlError("platform does not support Unix peer credentials")
                    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _pid, uid, _gid = struct.unpack("3i", credentials)
                    if uid != self.allowed_uid:
                        raise LocalControlError("IPC peer UID is not authorized")
                    request = _receive(connection)
                    result = self.handler(request["action"], request["params"])
                    if not isinstance(result, dict):
                        raise LocalControlError("IPC handler returned an invalid response")
                    _send(connection, {"ok": True, "data": result})
                except Exception as exc:
                    try:
                        _send(connection, {"ok": False, "error": str(exc)[:512]})
                    except (OSError, LocalControlError):
                        pass

    def stop(self) -> None:
        self._stop.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        try:
            info = os.lstat(self.path)
            if (stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid()
                    and self._socket_identity == (info.st_dev, info.st_ino)):
                os.unlink(self.path)
        except FileNotFoundError:
            pass
        finally:
            self._socket_identity = None


def local_control_request(
    path: str | os.PathLike[str],
    action: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 5,
) -> dict[str, Any]:
    """Send one allowlisted command to the root-owned local service."""
    if not isinstance(action, str) or action not in _ALLOWED_ACTIONS or not isinstance(params or {}, dict):
        raise LocalControlError("unsupported IPC action or invalid parameters")
    normalized_params = params or {}
    if action == "status" and normalized_params:
        raise LocalControlError("status does not accept parameters")
    if action in {"arm", "cancel"} and set(normalized_params) != {"job_id", "confirmation"}:
        raise LocalControlError("arm and cancel require exactly job_id and confirmation")
    request = {"action": action, "params": normalized_params}
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(encoded) > MAX_FRAME:
        raise LocalControlError("IPC request exceeds the frame limit")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(os.fspath(path))
        connection.sendall(struct.pack("!I", len(encoded)) + encoded)
        size = struct.unpack("!I", _recv_exact(connection, 4))[0]
        if not 1 <= size <= MAX_FRAME:
            raise LocalControlError("invalid IPC response frame length")
        try:
            response = json.loads(_recv_exact(connection, size).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LocalControlError(f"invalid IPC response: {exc}") from exc
    if (not isinstance(response, dict)
            or (response.get("ok") is not True and response.get("ok") is not False)):
        raise LocalControlError("invalid IPC response structure")
    if response["ok"] is True:
        if set(response) != {"ok", "data"} or not isinstance(response["data"], dict):
            raise LocalControlError("local service returned invalid data")
        return response["data"]
    if set(response) != {"ok", "error"} or not isinstance(response["error"], str):
        raise LocalControlError("local service returned an invalid error response")
    raise LocalControlError(response["error"])

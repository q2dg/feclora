"""In-memory deployment session coordinator.

This is control-plane state only. It does not open network sockets, authenticate
clients, start storage commands, or persist state across process restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Callable

from feclora.deployment.job import DeploymentJob


class CoordinatorError(RuntimeError):
    """Raised for an invalid deployment state transition."""


class JobState(str, Enum):
    CREATED = "created"
    ARMED = "armed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClientState(str, Enum):
    CONNECTED = "connected"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DISCONNECTED = "disconnected"


_TERMINAL_CLIENT_STATES = {
    ClientState.SUCCEEDED,
    ClientState.FAILED,
    ClientState.DISCONNECTED,
}


@dataclass(frozen=True)
class ClientRecord:
    mac_address: str
    state: ClientState
    detail: str | None = None


class DeploymentCoordinator:
    """Thread-safe state machine for one deployment job."""

    def __init__(
        self,
        job: DeploymentJob,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.job = job
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._state = JobState.CREATED
        self._clients: dict[str, ClientRecord] = {}

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    def clients(self) -> tuple[ClientRecord, ...]:
        with self._lock:
            return tuple(self._clients[key] for key in sorted(self._clients))

    def register_client(self, mac_address: str, *, authenticated: bool) -> ClientRecord:
        """Register a peer only after an external transport authenticates it.

        The boolean is an integration boundary, not authentication itself.
        Callers must not set it based only on a MAC address.
        """
        with self._lock:
            if authenticated is not True:
                raise CoordinatorError("Client control channel is not authenticated")
            if not self.job.authorizes_client(mac_address):
                raise CoordinatorError("Client is not in the job allowlist")
            if self._state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                raise CoordinatorError("Cannot join a terminal deployment job")
            mac = mac_address.lower()
            existing = self._clients.get(mac)
            if existing and existing.state not in _TERMINAL_CLIENT_STATES:
                raise CoordinatorError("Client is already registered")
            if self._state in {JobState.ARMED, JobState.RUNNING}:
                raise CoordinatorError("Cannot add clients after the job is armed")
            record = ClientRecord(mac, ClientState.CONNECTED)
            self._clients[mac] = record
            return record

    def mark_ready(self, mac_address: str) -> ClientRecord:
        with self._lock:
            record = self._require_client(mac_address)
            if self._state is not JobState.CREATED:
                raise CoordinatorError("Clients can become ready only before the job is armed")
            if record.state is not ClientState.CONNECTED:
                raise CoordinatorError("Only a connected client can become ready")
            updated = ClientRecord(record.mac_address, ClientState.READY)
            self._clients[record.mac_address] = updated
            return updated

    def can_start(self, *, now: datetime | None = None) -> bool:
        with self._lock:
            if self._state is not JobState.CREATED:
                return False
            ready = self._ready_count()
            if ready == 0:
                return False
            if self.job.start_policy == "manual":
                return True
            if self.job.start_policy == "expected_clients":
                return ready >= int(self.job.expected_clients or 0)
            current = now or self._clock()
            if current.tzinfo is None or current.utcoffset() is None:
                raise CoordinatorError("Clock must return a timezone-aware datetime")
            deadline = datetime.fromisoformat(
                str(self.job.start_deadline).replace("Z", "+00:00")
            )
            return current.astimezone(timezone.utc) >= deadline

    def arm(self, *, now: datetime | None = None) -> None:
        """Explicitly arm the job after its configured start condition is met."""
        with self._lock:
            if self._state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                raise CoordinatorError("A terminal deployment job cannot be armed")
            if self._state is not JobState.CREATED:
                raise CoordinatorError("Only a newly created job can be armed")
            if not self.can_start(now=now):
                raise CoordinatorError("Deployment start condition has not been met")
            self._state = JobState.ARMED

    def mark_running(self, mac_address: str) -> ClientRecord:
        with self._lock:
            if self._state not in {JobState.ARMED, JobState.RUNNING}:
                raise CoordinatorError("Job must be armed before a client can run")
            record = self._require_client(mac_address)
            if record.state is not ClientState.READY:
                raise CoordinatorError("Only a ready client can start")
            updated = ClientRecord(record.mac_address, ClientState.RUNNING)
            self._clients[record.mac_address] = updated
            self._state = JobState.RUNNING
            return updated

    def report_result(
        self,
        mac_address: str,
        *,
        success: bool,
        detail: str | None = None,
    ) -> ClientRecord:
        with self._lock:
            record = self._require_client(mac_address)
            if record.state is not ClientState.RUNNING:
                raise CoordinatorError("Only a running client can report a result")
            updated = ClientRecord(
                record.mac_address,
                ClientState.SUCCEEDED if success else ClientState.FAILED,
                detail,
            )
            self._clients[record.mac_address] = updated
            states = [client.state for client in self._clients.values()]
            if all(state in _TERMINAL_CLIENT_STATES for state in states):
                self._state = (
                    JobState.COMPLETED
                    if all(state is ClientState.SUCCEEDED for state in states)
                    else JobState.FAILED
                )
            return updated

    def disconnect_client(self, mac_address: str, detail: str | None = None) -> ClientRecord:
        with self._lock:
            record = self._require_client(mac_address)
            if record.state in _TERMINAL_CLIENT_STATES:
                raise CoordinatorError("Client is already in a terminal state")
            updated = ClientRecord(record.mac_address, ClientState.DISCONNECTED, detail)
            self._clients[record.mac_address] = updated
            if self._state in {JobState.ARMED, JobState.RUNNING} and all(
                client.state in _TERMINAL_CLIENT_STATES for client in self._clients.values()
            ):
                self._state = JobState.FAILED
            return updated

    def cancel(self) -> None:
        with self._lock:
            if self._state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                raise CoordinatorError("Deployment job is already terminal")
            self._state = JobState.CANCELLED

    def summary(self) -> dict[str, int | str]:
        with self._lock:
            counts = {state.value: 0 for state in ClientState}
            for record in self._clients.values():
                counts[record.state.value] += 1
            return {"job_state": self._state.value, "clients_total": len(self._clients), **counts}

    def _ready_count(self) -> int:
        return sum(record.state is ClientState.READY for record in self._clients.values())

    def _require_client(self, mac_address: str) -> ClientRecord:
        if not isinstance(mac_address, str):
            raise CoordinatorError("Invalid client MAC address")
        record = self._clients.get(mac_address.lower())
        if record is None:
            raise CoordinatorError("Client is not registered")
        return record

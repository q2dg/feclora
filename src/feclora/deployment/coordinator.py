"""Thread-safe deployment state machine with optional durable event sink."""
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
    """Thread-safe state machine for one deployment job.

    When event_sink is configured, every transition is persisted before the
    in-memory state is changed. A persistence failure therefore fails closed.
    """

    def __init__(
        self,
        job: DeploymentJob,
        *,
        clock: Callable[[], datetime] | None = None,
        event_sink: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.job = job
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._state = JobState.CREATED
        self._clients: dict[str, ClientRecord] = {}
        self._event_sink = event_sink
        self._record_event(
            "job_created", job_state=JobState.CREATED, job_document=self.job.to_dict(),
        )

    @classmethod
    def from_journal(cls, job: DeploymentJob, journal: object) -> "DeploymentCoordinator":
        """Rebuild audit state from a verified journal without restoring sessions.

        In-flight jobs remain in their recorded state and cannot be armed again.
        The caller must reconcile an interrupted job after inspecting every
        Client and destination; this method never reconnects peers or resumes I/O.
        """
        if not isinstance(job, DeploymentJob):
            raise CoordinatorError("journal recovery requires a validated deployment job")
        report_method = getattr(journal, "recovery_report", None)
        if not callable(report_method):
            raise CoordinatorError("journal recovery requires a verified deployment journal")
        try:
            report = report_method()
        except Exception as exc:
            raise CoordinatorError(f"could not inspect deployment journal: {exc}") from exc
        if report.get("job_id") != job.job_id or report.get("job") != job.to_dict():
            raise CoordinatorError("deployment journal does not match the supplied job definition")
        try:
            state = JobState(report["job_state"])
            clients = {
                mac: ClientRecord(
                    mac,
                    ClientState(record["state"]),
                    record.get("detail"),
                )
                for mac, record in report["clients"].items()
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinatorError(f"deployment journal contains invalid coordinator state: {exc}") from exc
        if any(not job.authorizes_client(mac) for mac in clients):
            raise CoordinatorError("deployment journal contains a Client outside the job allowlist")
        coordinator = cls.__new__(cls)
        coordinator.job = job
        coordinator._clock = lambda: datetime.now(timezone.utc)
        coordinator._lock = RLock()
        coordinator._state = state
        coordinator._clients = clients
        coordinator._event_sink = journal
        return coordinator

    def _record_event(
        self,
        event: str,
        *,
        job_state: JobState | None = None,
        client: ClientRecord | None = None,
        detail: str | None = None,
        job_document: dict[str, object] | None = None,
    ) -> None:
        if self._event_sink is None:
            return
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise CoordinatorError("Clock must return a timezone-aware datetime")
        payload: dict[str, object] = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "job_id": self.job.job_id,
            "event": event,
            "job_state": (job_state or self._state).value,
        }
        if client is not None:
            payload["client_mac"] = client.mac_address
            payload["client_state"] = client.state.value
        if detail is not None:
            payload["detail"] = detail[:512]
        if job_document is not None:
            payload["job"] = job_document
        try:
            self._event_sink(payload)
        except Exception as exc:
            raise CoordinatorError(f"could not persist deployment state: {exc}") from exc

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    def clients(self) -> tuple[ClientRecord, ...]:
        with self._lock:
            return tuple(self._clients[key] for key in sorted(self._clients))

    def register_client(self, mac_address: str) -> ClientRecord:
        """Register a connected peer selected by the deployment job."""
        with self._lock:
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
            self._record_event("client_connected", client=record)
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
            self._record_event("client_ready", client=updated)
            self._clients[record.mac_address] = updated
            return updated

    def can_start(self, *, now: datetime | None = None) -> bool:
        with self._lock:
            if self._state is not JobState.CREATED:
                return False
            ready = self._ready_count()
            if ready == 0:
                return False
            # A physical clone is a cohort operation: no Client may start
            # writing until every explicitly selected Client has completed
            # local target approval and reached READY. A threshold or deadline
            # must never weaken this all-clients barrier.
            if self.job.operation == "clone":
                selected = {mac.lower() for mac in self.job.authorized_clients}
                ready_clients = {
                    mac for mac, record in self._clients.items()
                    if record.state is ClientState.READY
                }
                if ready_clients != selected:
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
            self._record_event("job_armed", job_state=JobState.ARMED)
            self._state = JobState.ARMED

    def mark_running(self, mac_address: str) -> ClientRecord:
        with self._lock:
            if self._state not in {JobState.ARMED, JobState.RUNNING}:
                raise CoordinatorError("Job must be armed before a client can run")
            record = self._require_client(mac_address)
            if record.state is not ClientState.READY:
                raise CoordinatorError("Only a ready client can start")
            updated = ClientRecord(record.mac_address, ClientState.RUNNING)
            self._record_event("client_running", client=updated, job_state=JobState.RUNNING)
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
            states = [
                updated.state if item.mac_address == record.mac_address else item.state
                for item in self._clients.values()
            ]
            next_state = self._state
            if all(state in _TERMINAL_CLIENT_STATES for state in states):
                next_state = (
                    JobState.COMPLETED
                    if all(state is ClientState.SUCCEEDED for state in states)
                    else JobState.FAILED
                )
            self._record_event("client_result", client=updated, detail=detail, job_state=next_state)
            self._clients[record.mac_address] = updated
            self._state = next_state
            return updated

    def disconnect_client(self, mac_address: str, detail: str | None = None) -> ClientRecord:
        with self._lock:
            record = self._require_client(mac_address)
            if record.state in _TERMINAL_CLIENT_STATES:
                raise CoordinatorError("Client is already in a terminal state")
            updated = ClientRecord(record.mac_address, ClientState.DISCONNECTED, detail)
            next_state = self._state
            future_states = [
                updated.state if item.mac_address == record.mac_address else item.state
                for item in self._clients.values()
            ]
            if self._state in {JobState.ARMED, JobState.RUNNING} and all(
                state in _TERMINAL_CLIENT_STATES for state in future_states
            ):
                next_state = JobState.FAILED
            self._record_event("client_disconnected", client=updated, detail=detail, job_state=next_state)
            self._clients[record.mac_address] = updated
            self._state = next_state
            return updated

    def cancel(self) -> None:
        with self._lock:
            if self._state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                raise CoordinatorError("Deployment job is already terminal")
            self._record_event("job_cancelled", job_state=JobState.CANCELLED)
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

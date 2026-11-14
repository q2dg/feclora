import hashlib
import io
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from feclora.deployment.control import (
    DeploymentControlError,
    DeploymentControlServer,
    LocalTargetApproval,
    inspect_deployment_job,
    join_deployment,
    receive_control_message,
    send_control_message,
)
from feclora.deployment.coordinator import DeploymentCoordinator, JobState
from feclora.deployment.job import DeploymentJob
from feclora.network.remote_clone_protocol import create_tls_context
from feclora.network.udpcast import UDPcastConfig
from feclora.deployment.coordinator import ClientState


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
MAC = "52:54:00:12:34:56"


def make_job(**changes):
    payload = {
        "schema_version": 1, "job_id": JOB_ID, "operation": "restore",
        "image_id": "golden-image", "authorized_clients": [MAC],
        "network_interface": "enp1s0", "transport": "unicast",
        "multicast_group": None, "multicast_port": None,
        "start_policy": "manual", "expected_clients": None, "start_deadline": None,
    }
    payload.update(changes)
    return DeploymentJob.from_dict(payload)


def frame(message):
    encoded = json.dumps(message, separators=(",", ":")).encode("ascii")
    return struct.pack("!I", len(encoded)) + encoded


class FakeSocket:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()
        self.timeout = None
        self.closed = False

    def recv(self, count):
        result = bytes(self.incoming[:count])
        del self.incoming[:count]
        return result

    def sendall(self, data):
        self.outgoing.extend(data)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class ListenerShutdownRaceTests(unittest.TestCase):
    def test_ready_client_is_not_registered_after_shutdown_begins(self):
        tls_socket = FakeSocket()
        job = SimpleNamespace(job_id=JOB_ID, operation="restore", authorizes_client=lambda mac: mac == MAC, to_dict=lambda: {})
        coordinator = Mock()
        coordinator.job = job

        def mark_ready(_mac):
            server._stop_event.set()

        coordinator.mark_ready.side_effect = mark_ready
        server = object.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server._sessions = {}
        server._target_devices = {}
        server.tls_context = SimpleNamespace(wrap_socket=lambda accepted, server_side: tls_socket)
        server.local_identity = "URI:feclora-server"
        server.coordinator = coordinator
        listener = SimpleNamespace(accept=lambda: (FakeSocket(), ("192.0.2.20", 40000)))
        messages = [
            {"type": "hello", "job_id": JOB_ID, "mac_address": MAC},
            {"type": "ready", "job_id": JOB_ID, "target_description": "approved target",
             "locally_authorized": True},
        ]
        with patch("feclora.deployment.control.receive_control_message", side_effect=messages), \
             patch("feclora.deployment.control.send_control_message"):
            with self.assertRaisesRegex(DeploymentControlError, "stopped during Client admission"):
                server.accept_ready_client(listener)
        self.assertTrue(tls_socket.closed)
        self.assertEqual(server._sessions, {})
        self.assertEqual(server._pending_sockets, set())
        coordinator.disconnect_client.assert_called_once()

    def test_tls_socket_created_during_shutdown_is_not_readded_as_pending(self):
        accepted = FakeSocket()
        tls_socket = FakeSocket()
        server = object.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server._pending_sockets.add(accepted)
        def wrap_socket(_accepted, server_side):
            self.assertTrue(server_side)
            server._stop_event.set()
            return tls_socket
        server.tls_context = SimpleNamespace(wrap_socket=wrap_socket)
        listener = SimpleNamespace(accept=lambda: (accepted, ("192.0.2.20", 40000)))
        self.assertIsNone(server.accept_ready_client(listener))
        self.assertTrue(tls_socket.closed)
        self.assertNotIn(accepted, server._pending_sockets)
        self.assertNotIn(tls_socket, server._pending_sockets)

    def test_socket_accepted_after_shutdown_begins_is_closed_immediately(self):
        fake = FakeSocket()
        server = object.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server._stop_event.set()
        listener = SimpleNamespace(accept=lambda: (fake, ("192.0.2.20", 40000)))
        self.assertIsNone(server.accept_ready_client(listener))
        self.assertTrue(fake.closed)
        self.assertEqual(server._pending_sockets, set())


class ListenerErrorTests(unittest.TestCase):
    def test_listener_error_history_is_bounded_and_truncated(self):
        server = object.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server.listener_errors = []
        for index in range(100):
            server._record_listener_error(f"listener error {index}")
        self.assertEqual(len(server.listener_errors), 64)
        self.assertEqual(server.listener_errors[0], "listener error 36")
        self.assertEqual(server.listener_errors[-1], "listener error 99")
        server._record_listener_error("x" * 600)
        self.assertEqual(len(server.listener_errors[-1]), 512)


class ClientProgressTests(unittest.TestCase):
    def test_progress_frame_is_validated_and_exposed_with_throughput(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        first = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 1024, "total_bytes": 4096,
        }
        with patch("feclora.deployment.control.time.monotonic", side_effect=[10.0, 12.0]):
            server._record_client_progress(MAC, first)
            server._record_client_progress(MAC, {**first, "completed_bytes": 2048})
        progress = server.client_progress()[MAC]
        self.assertEqual(progress["completed_bytes"], 2048)
        self.assertEqual(progress["total_bytes"], 4096)
        self.assertEqual(progress["bytes_per_second"], 512.0)
        self.assertNotIn("monotonic", progress)

    def test_progress_persists_initial_and_bounded_byte_checkpoints(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        server._last_persisted_progress = {}
        server._progress_event_sink = Mock()
        frame = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 1024, "total_bytes": 4 * 1024 * 1024,
        }
        with patch("feclora.deployment.control.time.monotonic", side_effect=[10.0, 11.0, 12.0]):
            server._record_client_progress(MAC, frame)
            server._record_client_progress(MAC, {**frame, "completed_bytes": 2048})
            server._record_client_progress(MAC, {**frame, "completed_bytes": 1024 * 1024 + 1024})
        self.assertEqual(server._progress_event_sink.call_count, 2)
        saved = server._progress_event_sink.call_args_list[-1].args[0]
        self.assertEqual(saved["event"], "client_progress")
        self.assertEqual(saved["client_mac"], MAC)
        self.assertEqual(saved["progress"]["completed_bytes"], 1024 * 1024 + 1024)

    def test_progress_is_not_published_in_memory_when_journal_write_fails(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        server._last_persisted_progress = {}
        server._progress_event_sink = Mock(side_effect=OSError("disk full"))
        frame = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 1024, "total_bytes": 4096,
        }
        with self.assertRaisesRegex(DeploymentControlError, "could not persist"):
            server._record_client_progress(MAC, frame)
        self.assertEqual(server.client_progress(), {})
        self.assertEqual(server._last_persisted_progress, {})

    def test_progress_is_rejected_after_client_reaches_terminal_state(self):
        server = object.__new__(DeploymentControlServer)
        coordinator = DeploymentCoordinator(make_job())
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        coordinator.arm()
        coordinator.mark_running(MAC)
        coordinator.report_result(MAC, success=True)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._progress = {}
        frame = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 4096, "total_bytes": 4096,
        }
        with self.assertRaisesRegex(DeploymentControlError, "running Client session"):
            server._record_client_progress(MAC, frame)
        self.assertEqual(server.client_progress(), {})

    def test_progress_counter_cannot_move_backwards_within_phase(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        frame = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 2048, "total_bytes": 4096,
        }
        with patch("feclora.deployment.control.time.monotonic", side_effect=[10.0, 11.0]):
            server._record_client_progress(MAC, frame)
            with self.assertRaisesRegex(DeploymentControlError, "moved backwards"):
                server._record_client_progress(MAC, {**frame, "completed_bytes": 1024})
        self.assertEqual(server.client_progress()[MAC]["completed_bytes"], 2048)

    def test_transfer_progress_is_a_distinct_phase_with_independent_throughput(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        restore = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 5000, "total_bytes": 10000,
        }
        transfer = {**restore, "phase": "transfer", "completed_bytes": 100, "total_bytes": 1000}
        with patch("feclora.deployment.control.time.monotonic", side_effect=[10.0, 11.0, 13.0]):
            server._record_client_progress(MAC, restore)
            server._record_client_progress(MAC, transfer)
            server._record_client_progress(MAC, {**transfer, "completed_bytes": 200})
        progress = server.client_progress()[MAC]
        self.assertEqual(progress["phase"], "transfer")
        self.assertEqual(progress["completed_bytes"], 200)
        self.assertEqual(progress["bytes_per_second"], 50.0)

    def test_progress_rejects_wrong_job_and_invalid_counters(self):
        server = object.__new__(DeploymentControlServer)
        server.coordinator = DeploymentCoordinator(make_job())
        server.coordinator.register_client(MAC)
        server.coordinator.mark_ready(MAC)
        server.coordinator.arm()
        server.coordinator.mark_running(MAC)
        server._lock = threading.RLock()
        server._progress = {}
        valid = {
            "type": "progress", "job_id": JOB_ID, "phase": "restore",
            "completed_bytes": 1024, "total_bytes": 4096,
        }
        with self.assertRaisesRegex(DeploymentControlError, "another deployment job"):
            server._record_client_progress(MAC, {**valid, "job_id": "00000000-0000-4000-8000-000000000000"})
        with self.assertRaisesRegex(DeploymentControlError, "byte counters"):
            server._record_client_progress(MAC, {**valid, "completed_bytes": True})


class TransferFailureTests(unittest.TestCase):
    def test_physical_clone_start_carries_server_digest_metadata(self):
        mac2 = "52:54:00:12:34:57"
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sda",
            transport="multicast", multicast_group="239.10.10.10",
            multicast_port=5000, authorized_clients=[MAC, mac2],
        )
        coordinator = DeploymentCoordinator(job)
        for mac in (MAC, mac2):
            coordinator.register_client(mac)
            coordinator.mark_ready(mac)
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: FakeSocket(), mac2: FakeSocket()}
        messages = []
        metadata = {"expected_bytes": 8192, "sha256": "a" * 64}
        with patch("feclora.deployment.control.send_control_message",
                   side_effect=lambda sock, payload: messages.append(dict(payload))):
            self.assertEqual(set(server.arm_and_start(physical_stream=metadata)), {MAC, mac2})
        starts = [item for item in messages if item.get("type") == "start"]
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(item["physical_stream"] == metadata for item in starts))


    def test_physical_multicast_server_waits_for_every_receiver_before_sending(self):
        mac2 = "52:54:00:12:34:57"
        identity = {
            "path": "/dev/sda", "major_minor": "8:0", "sysfs_path": "/sys/devices/sda",
            "wwn": "wwn-source", "serial": "source-serial", "size_bytes": 4096,
            "logical_sector_size": 512, "physical_sector_size": 4096,
            "read_only": True, "mountpoints": [], "holders": [],
            "backs_system": False, "busy": False,
        }
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sda",
            transport="multicast", multicast_group="239.10.10.10",
            multicast_port=5000, authorized_clients=[MAC, mac2],
            source_identity=identity,
        )
        coordinator = DeploymentCoordinator(job)
        for mac in (MAC, mac2):
            coordinator.register_client(mac)
            coordinator.mark_ready(mac)
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: FakeSocket(), mac2: FakeSocket()}
        server._target_identities = {
            MAC: {**identity, "path": "/dev/sdb", "major_minor": "8:16",
                  "sysfs_path": "/sys/devices/sdb", "wwn": "wwn-target-1",
                  "serial": "target-serial-1", "read_only": False, "size_bytes": 8192},
            mac2: {**identity, "path": "/dev/sdc", "major_minor": "8:32",
                   "sysfs_path": "/sys/devices/sdc", "wwn": "wwn-target-2",
                   "serial": "target-serial-2", "read_only": False, "size_bytes": 8192},
        }
        server.firewall = Mock()
        config = UDPcastConfig("enp1s0", "239.10.10.10", "239.10.10.11", portbase=5000, min_receivers=2)
        payload = b"x" * 4096
        events = []
        def ready_ack(sock, *, expected_type):
            events.append("all-client-ready")
            return {"type": "physical_ready", "job_id": JOB_ID, "ready": True, "detail": "ready"}
        with patch("feclora.storage.inventory.collect_inventory", return_value={"devices": [{"path": "/dev/sda", "type": "disk", "children": []}]}), \
             patch("feclora.network.physical_multicast.build_physical_device_record", return_value=identity), \
             patch("feclora.network.physical_multicast.validate_physical_multicast_cohort"), \
             patch("feclora.network.physical_multicast.open_approved_block_device", return_value=44), \
             patch("feclora.deployment.control.os.pread", return_value=payload), \
             patch("feclora.deployment.control.os.dup", return_value=45), \
             patch("feclora.deployment.control.os.fdopen", return_value=io.BytesIO(payload)), \
             patch.object(server, "arm_and_start", return_value=(MAC, mac2)), \
             patch("feclora.deployment.control.receive_control_message", side_effect=ready_ack), \
             patch("feclora.network.udpcast.send_physical_multicast_stream",
                   side_effect=lambda *args, **kwargs: events.append("stream-sent") or {"sha256": hashlib.sha256(payload).hexdigest()}), \
             patch.object(server, "collect_results", return_value={MAC: "verified", mac2: "verified"}), \
             patch("feclora.deployment.control.os.close"):
            result = server.run_physical_multicast_clone_job(udpcast_config=config)
        self.assertEqual(result, {MAC: "verified", mac2: "verified"})
        self.assertEqual(events, ["all-client-ready", "all-client-ready", "stream-sent"])

    def test_restore_transfer_timeout_is_reported_failed_and_closes_session(self):
        coordinator = DeploymentCoordinator(make_job())
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        tls_socket = FakeSocket()
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: tls_socket}
        server._progress = {}
        server._last_persisted_progress = {}
        server._progress_event_sink = None

        with patch("feclora.deployment.control.send_control_message"), \
             patch("feclora.deployment.control.send_image_set", side_effect=TimeoutError("transfer timed out")):
            self.assertEqual(server.arm_and_start(), (MAC,))
            with self.assertRaisesRegex(DeploymentControlError, "restore image transfer failed: transfer timed out"):
                server.send_restore_image(
                    MAC, "/repository", "/repository/golden-image.manifest.json",
                )

        self.assertTrue(tls_socket.closed)
        self.assertEqual(server.collect_results(), {MAC: "failed"})
        self.assertEqual(coordinator.state, JobState.FAILED)


    def test_save_transfer_timeout_is_reported_failed_and_closes_session(self):
        coordinator = DeploymentCoordinator(make_job(operation="save"))
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        tls_socket = FakeSocket()
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: tls_socket}
        server._progress = {}
        server._last_persisted_progress = {}
        server._progress_event_sink = None

        with patch("feclora.deployment.control.send_control_message"), \
             patch("feclora.deployment.control.receive_control_message", side_effect=TimeoutError("transfer timed out")):
            self.assertEqual(server.arm_and_start(), (MAC,))
            with self.assertRaisesRegex(DeploymentControlError, "saved image transfer failed: transfer timed out"):
                server.receive_saved_image(
                    MAC, "/repository",
                )

        self.assertTrue(tls_socket.closed)
        self.assertEqual(server.collect_results(), {MAC: "failed"})
        self.assertEqual(coordinator.state, JobState.FAILED)



class TLSContextTests(unittest.TestCase):
    def test_server_accepts_context_without_client_certificates(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        server = DeploymentControlServer(
            DeploymentCoordinator(make_job()), context,
            local_identity="URI:feclora-server",
        )
        self.assertIs(server.tls_context, context)


    def test_firewall_cleanup_failure_preserves_recovery_state_and_releases_callback(self):
        class Firewall:
            def is_open(self, interface):
                return False

            def open(self, interface, ports, include_tftp=False):
                pass

            def export_state(self, interface):
                return {"zone": "feclora-pxe-12345678", "restore_zone": "public",
                        "ports": ["9443/tcp"]}

            def close(self, interface):
                raise RuntimeError("firewalld unavailable")

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        firewall = Firewall()
        callbacks = []
        server = DeploymentControlServer(
            DeploymentCoordinator(make_job()), context,
            local_identity="URI:feclora-server",
            firewall=firewall, interface="enp1s0",
        )
        server.start("127.0.0.1", 0, firewall_state_callback=callbacks.append)
        self.assertTrue(callbacks[0]["opened_by_service"])
        with self.assertRaisesRegex(DeploymentControlError, "firewall cleanup failed"):
            server.stop()
        self.assertEqual(len(callbacks), 1)
        self.assertIsNone(server._firewall_state_callback)
        self.assertTrue(server._firewall_opened)

    def test_listener_persists_and_clears_firewall_ownership_callback(self):
        class Firewall:
            def __init__(self):
                self.opened = False

            def is_open(self, interface):
                return self.opened

            def open(self, interface, ports, include_tftp=False):
                self.opened = True

            def export_state(self, interface):
                return {"zone": "feclora-pxe-12345678", "restore_zone": "public",
                        "ports": ["9443/tcp"]}

            def close(self, interface):
                self.opened = False

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        firewall = Firewall()
        callbacks = []
        server = DeploymentControlServer(
            DeploymentCoordinator(make_job()), context,
            local_identity="URI:feclora-server",
            firewall=firewall, interface="enp1s0",
        )
        try:
            server.start("127.0.0.1", 0, firewall_state_callback=callbacks.append)
            self.assertTrue(callbacks[0]["opened_by_service"])
            self.assertEqual(callbacks[0]["interface"], "enp1s0")
        finally:
            server.stop()
        self.assertEqual(callbacks[-1], None)
        self.assertFalse(firewall.opened)


class ControlFramingTests(unittest.TestCase):
    def test_round_trip_fragmented_socket(self):
        left, right = socket.socketpair()
        try:
            send_control_message(left, {
                "type": "hello", "job_id": JOB_ID, "mac_address": MAC,
            })
            message = receive_control_message(right, expected_type="hello")
            self.assertEqual(message["job_id"], JOB_ID)
            self.assertEqual(message["mac_address"], MAC)
        finally:
            left.close()
            right.close()

    def test_rejects_unknown_message_type(self):
        with self.assertRaisesRegex(DeploymentControlError, "message type"):
            send_control_message(FakeSocket(), {"type": "shell", "command": "id"})

    def test_rejects_oversized_frame(self):
        fake = FakeSocket(struct.pack("!I", 16 * 1024 + 1))
        with self.assertRaisesRegex(DeploymentControlError, "frame length"):
            receive_control_message(fake)

    def test_rejects_duplicate_json_keys(self):
        payload = b'{"type":"hello","type":"result"}'
        fake = FakeSocket(struct.pack("!I", len(payload)) + payload)
        with self.assertRaisesRegex(DeploymentControlError, "duplicate"):
            receive_control_message(fake)

    def test_inspect_deployment_job_does_not_send_client_ready(self):
        job = make_job()
        fake = FakeSocket(frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            inspected = inspect_deployment_job(
                "192.0.2.10", 9443, context,
                                expected_server_identity="URI:feclora-server",
                mac_address=MAC, job_id=JOB_ID,
            )
        self.assertEqual(inspected.job_id, JOB_ID)
        outgoing = FakeSocket(fake.outgoing)
        request = receive_control_message(outgoing)
        self.assertEqual(request["type"], "inspect")
        self.assertEqual(request["job_id"], JOB_ID)

    def test_server_inspection_does_not_register_or_mark_client_ready(self):
        job = make_job()
        coordinator = DeploymentCoordinator(job)
        fake = FakeSocket()
        listener = SimpleNamespace(accept=lambda: (fake, ("192.0.2.20", 40000)))
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.tls_context = SimpleNamespace(wrap_socket=lambda accepted, server_side: accepted)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server._sessions = {}
        server.local_identity = "URI:feclora-server"
        server.coordinator = coordinator
        with patch("feclora.deployment.control.receive_control_message", return_value={
            "type": "inspect", "job_id": JOB_ID, "mac_address": MAC,
        }), patch("feclora.deployment.control.send_control_message") as send:
            result = server.accept_ready_client(listener)
        self.assertIsNone(result)
        self.assertEqual(coordinator.clients(), ())
        self.assertTrue(fake.closed)
        send.assert_called_once()



class ClientJoinTests(unittest.TestCase):
    def test_client_requires_job_offer_and_explicit_local_target_approval(self):
        job = make_job()
        incoming = frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }) + frame({
            "type": "start", "job_id": JOB_ID,
            "operation": "restore", "image_id": "golden-image",
        })
        fake = FakeSocket(incoming)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            received, success, detail = join_deployment(
                "192.0.2.10", 9443, context,
                                expected_server_identity="URI:feclora-server",
                mac_address=MAC, job_id=JOB_ID,
                prepare_local_target=lambda offered: LocalTargetApproval(
                    "/dev/vda", "Samsung SSD 1 TB", "ERASE /dev/vda",
                ),
                execute_job=lambda offered, tls, approval: (True, "restore verified"),
            )
        self.assertEqual(received.job_id, JOB_ID)
        self.assertTrue(success)
        self.assertEqual(detail, "restore verified")
        outgoing = FakeSocket(bytes(fake.outgoing))
        hello = receive_control_message(outgoing, expected_type="hello")
        ready = receive_control_message(outgoing, expected_type="ready")
        self.assertNotIn("certificate_identity", hello)
        result = receive_control_message(outgoing, expected_type="result")
        self.assertTrue(ready["locally_authorized"])
        self.assertNotIn("/dev/", ready["target_description"])
        self.assertTrue(result["success"])

    def test_client_keeps_selected_device_path_local(self):
        job = make_job()
        fake = FakeSocket(frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }) + frame({
            "type": "start", "job_id": JOB_ID,
            "operation": "restore", "image_id": "golden-image",
        }))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        approval = LocalTargetApproval(
            "/dev/vda", "Virtual disk 1",
            "ERASE /dev/vda",
        )
        observed = []
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            join_deployment(
                "192.0.2.10", 9443, context,
                                expected_server_identity="URI:feclora-server",
                mac_address=MAC, job_id=JOB_ID,
                prepare_local_target=lambda offered: approval,
                execute_job=lambda offered, tls, local: (
                    observed.append(local.device_path) or True, "simulated",
                ),
            )
        self.assertEqual(observed, ["/dev/vda"])
        outgoing = FakeSocket(bytes(fake.outgoing))
        hello = receive_control_message(outgoing, expected_type="hello")
        ready = receive_control_message(outgoing, expected_type="ready")
        result = receive_control_message(outgoing, expected_type="result")
        self.assertNotIn("certificate_identity", hello)
        self.assertNotIn("/dev/vda", json.dumps(ready))
        self.assertTrue(result["success"])

    def test_clone_client_sends_locally_approved_target_binding(self):
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sda",
        )
        fake = FakeSocket(frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }) + frame({
            "type": "start", "job_id": JOB_ID,
            "operation": "clone", "image_id": None,
        }))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        approval = LocalTargetApproval(
            "/dev/vdb", "Destination disk",
            "ERASE /dev/vdb",
        )
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            join_deployment(
                "192.0.2.10", 9443, context,
                                expected_server_identity="URI:feclora-server",
                mac_address=MAC, job_id=JOB_ID,
                prepare_local_target=lambda offered: approval,
                execute_job=lambda offered, tls, local: (True, "clone verified"),
            )
        outgoing = FakeSocket(bytes(fake.outgoing))
        receive_control_message(outgoing, expected_type="hello")
        ready = receive_control_message(outgoing, expected_type="ready")
        self.assertEqual(ready["target_device"], "/dev/vdb")
        self.assertTrue(ready["locally_authorized"])
        result = receive_control_message(outgoing, expected_type="result")
        self.assertTrue(result["success"])

    def test_client_rejects_wrong_typed_confirmation_before_ready(self):
        job = make_job()
        fake = FakeSocket(frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            with self.assertRaisesRegex(DeploymentControlError, "typed target confirmation"):
                join_deployment(
                    "192.0.2.10", 9443, context,
                                        expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: LocalTargetApproval(
                        "/dev/vda", "Virtual disk 1", "ERASE /dev/vdb",
                    ),
                    execute_job=lambda offered, tls, approval: (True, "unexpected"),
                )

    def test_client_refuses_unarmed_or_mismatched_start(self):
        job = make_job()
        fake = FakeSocket(frame({
            "type": "job", "job": job.to_dict(),
            "server_identity": "URI:feclora-server",
        }) + frame({
            "type": "start", "job_id": "wrong",
            "operation": "restore", "image_id": "golden-image",
        }))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        with patch("feclora.deployment.control.connect_tls", return_value=fake):
            with self.assertRaisesRegex(DeploymentControlError, "did not arm"):
                join_deployment(
                    "192.0.2.10", 9443, context,
                                        expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: LocalTargetApproval(
                        "/dev/vda", "Local virtual disk",
                        "ERASE /dev/vda",
                    ),
                    execute_job=lambda offered, tls, approval: (True, "unexpected"),
                )


class CoordinatorControlTests(unittest.TestCase):
    def _server(self, job):
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        coordinator.arm()
        coordinator.mark_running(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        return coordinator, server, fake

    def test_remote_clone_job_binds_ready_target_and_uses_existing_tls_session(self):
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sda",
        )
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        server._target_devices[MAC] = "/dev/vdb"
        header = object()
        with patch("feclora.deployment.control.build_remote_clone_header", return_value=header) as build, \
             patch("feclora.deployment.control.send_remote_disk") as send, \
             patch.object(server, "arm_and_start", return_value=(MAC,)), \
             patch.object(server, "collect_results", return_value={MAC: "succeeded"}):
            result = server.run_remote_clone_job()
        self.assertEqual(result, {MAC: "succeeded"})
        build.assert_called_once_with(
            "/dev/sda", "/dev/vdb", device_type="disk",
        )
        send.assert_called_once()
        self.assertIs(send.call_args.args[0], fake)
        self.assertIs(send.call_args.args[1], header)
        self.assertEqual(send.call_args.kwargs["source_path"], "/dev/sda")
        self.assertEqual(
            send.call_args.kwargs["confirmation"],
            "READ /dev/sda",
        )

    def test_partition_clone_builds_partition_bound_session_header(self):
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sda1",
            target_type="partition",
        )
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        server._target_devices[MAC] = "/dev/vdb1"
        header = object()
        with patch("feclora.deployment.control.build_remote_clone_header", return_value=header) as build, \
             patch("feclora.deployment.control.send_remote_disk") as send, \
             patch.object(server, "arm_and_start", return_value=(MAC,)), \
             patch.object(server, "collect_results", return_value={MAC: "succeeded"}):
            self.assertEqual(server.run_remote_clone_job(), {MAC: "succeeded"})
        build.assert_called_once_with(
            "/dev/sda1", "/dev/vdb1", device_type="partition",
        )
        send.assert_called_once()

    def test_restore_server_sends_job_bound_transfer_offer_before_image(self):
        coordinator, server, fake = self._server(make_job(image_id="golden"))
        with patch("feclora.deployment.control.send_image_set", return_value="manifest") as send:
            result = server.send_restore_image(
                MAC, "/images", "golden.manifest.json",
            )
        self.assertEqual(result, "manifest")
        offer = receive_control_message(FakeSocket(bytes(fake.outgoing)), expected_type="transfer_offer")
        self.assertEqual(offer["job_id"], JOB_ID)
        self.assertEqual(offer["image_id"], "golden")
        self.assertEqual(send.call_args.kwargs["expected_image_id"], "golden")

    def test_restore_transfer_progress_is_persisted_by_server_without_tls_frames(self):
        coordinator, server, _fake = self._server(make_job(image_id="golden"))
        server._progress_event_sink = Mock()
        server._last_persisted_progress = {}
        def transfer(_socket, _repository, _manifest, *, expected_image_id, progress_callback):
            self.assertEqual(expected_image_id, "golden")
            progress_callback(0, 8192)
            progress_callback(4096, 8192)
            progress_callback(8192, 8192)
            return "manifest"
        with patch("feclora.deployment.control.send_image_set", side_effect=transfer) as send:
            result = server.send_restore_image(MAC, "/images", "golden.manifest.json")
        self.assertEqual(result, "manifest")
        self.assertIn("progress_callback", send.call_args.kwargs)
        progress = server.client_progress()[MAC]
        self.assertEqual(progress["phase"], "transfer")
        self.assertEqual(progress["completed_bytes"], 8192)
        self.assertEqual(progress["total_bytes"], 8192)
        saved = server._progress_event_sink.call_args_list[-1].args[0]
        self.assertEqual(saved["progress"]["phase"], "transfer")
        self.assertEqual(saved["progress"]["completed_bytes"], 8192)

    def test_save_server_receives_job_bound_transfer_and_publishes(self):
        coordinator, server, fake = self._server(make_job(operation="save", image_id="golden"))
        fake.incoming.extend(frame({
            "type": "transfer_ready", "job_id": JOB_ID, "image_id": "golden",
        }))
        with patch("feclora.deployment.control.receive_image_set", return_value="/repo/golden.manifest.json") as receive:
            path = server.receive_saved_image(
                MAC, "/repo",
            )
        self.assertEqual(path, "/repo/golden.manifest.json")
        self.assertEqual(receive.call_args.kwargs["expected_image_id"], "golden")
        self.assertEqual(receive.call_args.kwargs["expected_image_type"], "disk")

    def test_save_server_requires_logical_volume_manifest_for_lv_job(self):
        coordinator, server, fake = self._server(make_job(
            operation="save", image_id="golden", target_type="logical_volume",
        ))
        fake.incoming.extend(frame({
            "type": "transfer_ready", "job_id": JOB_ID, "image_id": "golden",
        }))
        with patch("feclora.deployment.control.receive_image_set", return_value="/repo/golden.manifest.json") as receive:
            path = server.receive_saved_image(MAC, "/repo")
        self.assertEqual(path, "/repo/golden.manifest.json")
        self.assertEqual(receive.call_args.kwargs["expected_image_type"], "logical_volume")

    def test_save_server_commits_destination_before_returning_transfer_success(self):
        coordinator, server, fake = self._server(make_job(operation="save", image_id="golden"))
        fake.incoming.extend(frame({
            "type": "transfer_ready", "job_id": JOB_ID, "image_id": "golden",
        }))
        committed = []
        with patch("feclora.deployment.control.receive_image_set", return_value="/repo/golden.manifest.json"):
            path = server.receive_saved_image(MAC, "/repo", on_received=committed.append)
        self.assertEqual(path, "/repo/golden.manifest.json")
        self.assertEqual(committed, [path])
        self.assertEqual(coordinator.state, JobState.RUNNING)

    def test_save_server_marks_job_failed_when_destination_commit_fails(self):
        coordinator, server, fake = self._server(make_job(operation="save", image_id="golden"))
        fake.incoming.extend(frame({
            "type": "transfer_ready", "job_id": JOB_ID, "image_id": "golden",
        }))
        def reject_commit(_path):
            raise RuntimeError("S3 commit failed")
        with patch("feclora.deployment.control.receive_image_set", return_value="/repo/golden.manifest.json"):
            with self.assertRaisesRegex(DeploymentControlError, "destination repository"):
                server.receive_saved_image(MAC, "/repo", on_received=reject_commit)
        self.assertEqual(coordinator.state, JobState.FAILED)

    def test_save_server_records_client_failure_before_transfer(self):
        coordinator, server, fake = self._server(make_job(operation="save"))
        fake.incoming.extend(frame({
            "type": "result", "job_id": JOB_ID, "success": False,
            "detail": "capture rejected locally",
        }))
        self.assertEqual(
            server.receive_saved_image(MAC, "/repo"),
            "",
        )
        self.assertEqual(coordinator.state, JobState.FAILED)
        self.assertEqual(server.collect_results(), {MAC: "failed"})

    def test_control_listener_scopes_port_and_restores_firewall(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        firewall = Mock()
        firewall.is_open.return_value = False
        server = DeploymentControlServer(
            DeploymentCoordinator(make_job()), context,
            local_identity="URI:feclora-server",
            firewall=firewall, interface="enp1s0",
        )
        _host, port = server.start("127.0.0.1", 0)
        firewall.open.assert_called_once_with(
            "enp1s0", [f"{port}/tcp"], include_tftp=False,
        )
        server.stop()
        firewall.close.assert_called_once_with("enp1s0")

    def test_control_listener_adds_only_its_port_to_existing_pxe_zone(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        firewall = unittest.mock.Mock()
        firewall.is_open.return_value = True
        firewall.add_ports.side_effect = lambda interface, ports: tuple(ports)
        server = DeploymentControlServer(
            DeploymentCoordinator(make_job()), context,
            local_identity="URI:feclora-server",
            firewall=firewall, interface="enp1s0",
        )
        _host, port = server.start("127.0.0.1", 0)
        firewall.add_ports.assert_called_once_with("enp1s0", [f"{port}/tcp"])
        server.stop()
        firewall.remove_ports.assert_called_once_with("enp1s0", (f"{port}/tcp",))
        firewall.close.assert_not_called()

    def test_single_client_restore_orchestrator_arms_then_sends_and_collects(self):
        coordinator, server, fake = self._server_ready(make_job(image_id="golden"))
        with patch.object(server, "send_restore_image") as send, \
             patch.object(server, "collect_results", return_value={MAC: "succeeded"}) as collect:
            result = server.run_one_client_job(
                "/images", manifest_path="golden.manifest.json",
            )
        self.assertEqual(result, {MAC: "succeeded"})
        send.assert_called_once_with(
            MAC, "/images", "golden.manifest.json",
        )
        collect.assert_called_once()

    def _server_ready(self, job):
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        return coordinator, server, fake

    def test_server_arms_and_tracks_selected_ready_client(self):
        coordinator = DeploymentCoordinator(make_job())
        coordinator.register_client(MAC)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        self.assertEqual(server.arm_and_start(), (MAC,))
        self.assertEqual(coordinator.state, JobState.RUNNING)
        outgoing = FakeSocket(bytes(fake.outgoing))
        start = receive_control_message(outgoing, expected_type="start")
        self.assertEqual(start["job_id"], JOB_ID)
        self.assertEqual(start["operation"], "restore")



@unittest.skipUnless(shutil.which("openssl"), "openssl is required for loopback TLS integration")
class ServerAuthenticatedTLSControlIntegrationTests(unittest.TestCase):
    def _certificate(self, directory, name, san, ca_key, ca_cert):
        key = os.path.join(directory, name + ".key")
        csr = os.path.join(directory, name + ".csr")
        cert = os.path.join(directory, name + ".crt")
        subprocess.run([
            "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", key, "-out", csr, "-subj", f"/CN={name}",
        ], check=True, capture_output=True)
        ext = os.path.join(directory, name + ".ext")
        with open(ext, "w", encoding="ascii") as stream:
            stream.write(f"subjectAltName={san}\nextendedKeyUsage={'serverAuth' if name == 'server' else 'clientAuth'}\n")
        subprocess.run([
            "openssl", "x509", "-req", "-in", csr, "-CA", ca_cert,
            "-CAkey", ca_key, "-CAcreateserial", "-out", cert, "-days", "1",
            "-extfile", ext,
        ], check=True, capture_output=True)
        return cert, key

    def test_mtls_session_transfers_image_set_before_client_result(self):
        with tempfile.TemporaryDirectory() as directory:
            ca_key = os.path.join(directory, "ca.key")
            ca_cert = os.path.join(directory, "ca.crt")
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", ca_key, "-out", ca_cert, "-subj", "/CN=Feclora Test CA",
                "-days", "1",
            ], check=True, capture_output=True)
            server_cert, server_key = self._certificate(
                directory, "server", "URI:feclora-server", ca_key, ca_cert,
            )
            client_cert, client_key = self._certificate(
                directory, "client", "URI:feclora-client", ca_key, ca_cert,
            )
            server_context = create_tls_context(
                "server", certificate_file=server_cert, private_key_file=server_key,
            )
            client_context = create_tls_context(
                "client", ca_file=ca_cert,
            )
            source = os.path.join(directory, "source")
            destination = os.path.join(directory, "destination")
            os.mkdir(source)
            os.mkdir(destination)
            disk = b"disk"
            table = b"table"
            with open(os.path.join(source, "disk.raw"), "wb") as stream:
                stream.write(disk)
            with open(os.path.join(source, "table.txt"), "wb") as stream:
                stream.write(table)
            manifest = {
                "schema_version": 1, "image_id": "golden-image",
                "image_type": "disk", "source_size_bytes": len(disk),
                "logical_sector_size": 512, "partition_table": "none",
                "artifacts": [
                    {"filename": "disk.raw", "role": "disk-image", "format": "raw",
                     "compression": "none", "size_bytes": len(disk),
                     "sha256": hashlib.sha256(disk).hexdigest()},
                    {"filename": "table.txt", "role": "partition-table", "format": "raw",
                     "compression": "none", "size_bytes": len(table),
                     "sha256": hashlib.sha256(table).hexdigest()},
                ],
            }
            manifest_path = os.path.join(source, "golden-image.manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream)

            job = make_job()
            coordinator = DeploymentCoordinator(job)
            server = DeploymentControlServer(
                coordinator, server_context, local_identity="URI:feclora-server",
            )
            host, port = server.start("127.0.0.1", 0)
            client_result = []
            approval = LocalTargetApproval(
                "/dev/vda", "Disposable VM disk",
                "ERASE /dev/vda",
            )
            def client():
                client_result.append(join_deployment(
                    host, port, client_context,
                    expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: approval,
                    execute_job=lambda offered, tls, local: self._receive_test_image(
                        tls, destination, offered,
                    ),
                ))
            client_thread = threading.Thread(target=client, daemon=True)
            try:
                client_thread.start()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    records = coordinator.clients()
                    if records and records[0].state.value == "ready":
                        break
                    time.sleep(0.01)
                self.assertEqual(coordinator.clients()[0].state.value, "ready")
                server.arm_and_start()
                server.send_restore_image(
                    MAC, source, manifest_path,
                )
                client_thread.join(5)
                self.assertFalse(client_thread.is_alive())
                results = server.collect_results(timeout=5)
                self.assertEqual(results, {MAC: "succeeded"})
                self.assertTrue(client_result[0][1])
                with open(os.path.join(destination, "disk.raw"), "rb") as stream:
                    self.assertEqual(stream.read(), disk)
                with open(os.path.join(destination, "table.txt"), "rb") as stream:
                    self.assertEqual(stream.read(), table)
                self.assertEqual(coordinator.state, JobState.COMPLETED)
            finally:
                server.stop()

    @staticmethod
    def _receive_test_image(tls, destination, job):
        from feclora.deployment.artifact_transfer import receive_image_set
        offer = receive_control_message(tls, expected_type="transfer_offer")
        if offer.get("job_id") != job.job_id or offer.get("image_id") != job.image_id:
            raise DeploymentControlError("transfer offer mismatch")
        receive_image_set(
            tls, destination, expected_image_id=job.image_id,
        )
        return True, "image received and verified"

    def test_tls13_client_server_job_ready_arm_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            ca_key = os.path.join(directory, "ca.key")
            ca_cert = os.path.join(directory, "ca.crt")
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", ca_key, "-out", ca_cert, "-subj", "/CN=Feclora Test CA",
                "-days", "1",
            ], check=True, capture_output=True)
            server_cert, server_key = self._certificate(
                directory, "server", "URI:feclora-server", ca_key, ca_cert,
            )
            client_cert, client_key = self._certificate(
                directory, "client", "URI:feclora-client", ca_key, ca_cert,
            )
            server_context = create_tls_context(
                "server", certificate_file=server_cert, private_key_file=server_key,
            )
            client_context = create_tls_context(
                "client", ca_file=ca_cert,
            )
            coordinator = DeploymentCoordinator(make_job())
            server = DeploymentControlServer(
                coordinator, server_context, local_identity="URI:feclora-server",
            )
            _address, port = server.start("127.0.0.1", 0)
            client_result = []
            client_errors = []

            def run_client():
                try:
                    client_result.append(join_deployment(
                        "127.0.0.1", port, client_context,
                                                expected_server_identity="URI:feclora-server",
                        mac_address=MAC, job_id=JOB_ID,
                        prepare_local_target=lambda job: LocalTargetApproval(
                            "/dev/vda", "Virtual disk 1", "ERASE /dev/vda",
                        ),
                        execute_job=lambda job, tls, approval: (True, "simulated protected operation verified"),
                        timeout=10,
                    ))
                except Exception as exc:
                    client_errors.append(exc)

            client_thread = threading.Thread(target=run_client, daemon=True)
            client_thread.start()
            deadline = time.monotonic() + 12
            try:
                while time.monotonic() < deadline:
                    clients = coordinator.clients()
                    if clients and clients[0].state.value == "ready":
                        break
                    if client_errors:
                        self.fail(str(client_errors))
                    time.sleep(0.05)
                self.assertTrue(coordinator.clients(), "client did not connect")
                self.assertEqual(coordinator.clients()[0].state.value, "ready")
                self.assertEqual(server.arm_and_start(), (MAC,))
                client_thread.join(15)
                self.assertFalse(client_thread.is_alive(), "client did not finish after START")
                self.assertFalse(client_errors, str(client_errors))
                results = server.collect_results(timeout=10)
                self.assertEqual(results[MAC], "succeeded")
                self.assertEqual(coordinator.state, JobState.COMPLETED)
                self.assertEqual(len(client_result), 1)
            finally:
                server.stop()


    def test_mtls_client_save_transfers_image_and_reports_result(self):
        with tempfile.TemporaryDirectory() as directory:
            ca_key = os.path.join(directory, "ca.key")
            ca_cert = os.path.join(directory, "ca.crt")
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", ca_key, "-out", ca_cert, "-subj", "/CN=Feclora Test CA",
                "-days", "1",
            ], check=True, capture_output=True)
            server_cert, server_key = self._certificate(
                directory, "server", "URI:feclora-server", ca_key, ca_cert,
            )
            client_cert, client_key = self._certificate(
                directory, "client", "URI:feclora-client", ca_key, ca_cert,
            )
            server_context = create_tls_context(
                "server", certificate_file=server_cert, private_key_file=server_key,
            )
            client_context = create_tls_context(
                "client", ca_file=ca_cert,
            )
            source = os.path.join(directory, "client-image")
            destination = os.path.join(directory, "server-repository")
            os.mkdir(source)
            os.mkdir(destination)
            disk = b"client disk image"
            table = b"client partition table"
            with open(os.path.join(source, "disk.raw"), "wb") as stream:
                stream.write(disk)
            with open(os.path.join(source, "table.txt"), "wb") as stream:
                stream.write(table)
            manifest = {
                "schema_version": 1, "image_id": "golden-image",
                "image_type": "disk", "source_size_bytes": len(disk),
                "logical_sector_size": 512, "partition_table": "none",
                "artifacts": [
                    {"filename": "disk.raw", "role": "disk-image", "format": "raw",
                     "compression": "none", "size_bytes": len(disk),
                     "sha256": hashlib.sha256(disk).hexdigest()},
                    {"filename": "table.txt", "role": "partition-table", "format": "raw",
                     "compression": "none", "size_bytes": len(table),
                     "sha256": hashlib.sha256(table).hexdigest()},
                ],
            }
            manifest_path = os.path.join(source, "golden-image.manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream)

            coordinator = DeploymentCoordinator(make_job(operation="save"))
            server = DeploymentControlServer(
                coordinator, server_context, local_identity="URI:feclora-server",
            )
            host, port = server.start("127.0.0.1", 0)
            client_errors = []
            def execute_save(job, tls, approval):
                from feclora.deployment.artifact_transfer import send_image_set
                send_control_message(tls, {
                    "type": "transfer_ready", "job_id": job.job_id,
                    "image_id": job.image_id,
                })
                send_image_set(
                    tls, source, manifest_path, expected_image_id=job.image_id,
                )
                return True, "capture and transfer complete"

            def run_client():
                try:
                    join_deployment(
                        host, port, client_context,
                                                expected_server_identity="URI:feclora-server",
                        mac_address=MAC, job_id=JOB_ID,
                        prepare_local_target=lambda job: LocalTargetApproval(
                            "/dev/vda", "Disposable VM disk",
                            "READ /dev/vda",
                        ),
                        execute_job=execute_save, timeout=15,
                    )
                except Exception as exc:
                    client_errors.append(exc)

            client_thread = threading.Thread(target=run_client, daemon=True)
            try:
                client_thread.start()
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    clients = coordinator.clients()
                    if clients and clients[0].state.value == "ready":
                        break
                    if client_errors:
                        self.fail(str(client_errors))
                    time.sleep(0.05)
                self.assertTrue(coordinator.clients(), "save Client did not connect")
                self.assertEqual(coordinator.clients()[0].state.value, "ready")
                results = server.run_one_client_job(
                        destination,
                )
                client_thread.join(10)
                self.assertFalse(client_thread.is_alive(), "save Client did not report its result")
                self.assertFalse(client_errors, str(client_errors))
                self.assertEqual(results, {MAC: "succeeded"})
                self.assertEqual(coordinator.state, JobState.COMPLETED)
                for filename, expected in (("disk.raw", disk), ("table.txt", table)):
                    with open(os.path.join(destination, filename), "rb") as stream:
                        self.assertEqual(stream.read(), expected)
                self.assertTrue(os.path.isfile(os.path.join(destination, "golden-image.manifest.json")))
            finally:
                server.stop()


class MulticastControlTests(unittest.TestCase):
    def test_server_arms_all_ready_clients_and_multicasts_each_artifact(self):
        mac2 = "52:54:00:12:34:57"
        job = make_job(
            transport="multicast",
            authorized_clients=[MAC, mac2],
            multicast_group="239.10.10.1",
            multicast_port=9000,
        )
        coordinator = Mock()
        coordinator.job = job
        coordinator.clients.return_value = [
            SimpleNamespace(mac_address=MAC, state=ClientState.READY),
            SimpleNamespace(mac_address=mac2, state=ClientState.READY),
        ]
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: Mock(), mac2: Mock()}
        server.firewall = Mock()
        config = UDPcastConfig(
            "enp1s0", "239.10.10.1", "239.10.10.2",
            portbase=9000, min_receivers=2,
        )
        manifest = SimpleNamespace(
            image_id="golden-image", image_type="disk",
            artifacts=(SimpleNamespace(filename="image.raw", encryption="age"),),
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = os.path.join(directory, "golden-image.manifest.json")
            with open(manifest_path, "wb") as stream:
                stream.write(b"{}")
            with open(os.path.join(directory, "image.raw"), "wb") as stream:
                stream.write(b"payload")
            with (
                patch("feclora.deployment.control.ImageManifest.from_json", return_value=manifest),
                patch("feclora.deployment.control.verify_artifact_file"),
                patch("feclora.deployment.control.send_control_message") as send,
                patch("feclora.deployment.control.send_multicast_artifact") as multicast_send,
                patch.object(server, "arm_and_start", return_value=(MAC, mac2)),
                patch.object(server, "collect_results", return_value={MAC: "succeeded", mac2: "succeeded"}),
            ):
                results = server.run_multicast_restore_job(
                    directory, manifest_path,
                    udpcast_config=config,
                )
        self.assertEqual(results, {MAC: "succeeded", mac2: "succeeded"})
        self.assertEqual(send.call_count, 2)
        multicast_send.assert_called_once()
        self.assertEqual(multicast_send.call_args.args[0], coordinator)
        self.assertEqual(multicast_send.call_args.kwargs["firewall"], server.firewall)

    def test_server_rejects_multicast_job_until_every_selected_client_is_ready(self):
        mac2 = "52:54:00:12:34:57"
        job = make_job(
            transport="multicast",
            authorized_clients=[MAC, mac2],
            multicast_group="239.10.10.1",
            multicast_port=9000,
        )
        coordinator = Mock()
        coordinator.job = job
        coordinator.clients.return_value = [
            SimpleNamespace(mac_address=MAC, state=ClientState.READY),
        ]
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: Mock()}
        server.firewall = Mock()
        config = UDPcastConfig(
            "enp1s0", "239.10.10.1", "239.10.10.2",
            portbase=9000, min_receivers=2,
        )
        with self.assertRaisesRegex(DeploymentControlError, "at least 2 READY Client"):
            server.run_multicast_restore_job(
                "/repo", "/repo/image.manifest.json",
                udpcast_config=config,
            )


class MultiClientRemoteCloneTests(unittest.TestCase):
    def test_remote_clone_streams_to_each_ready_client_with_independent_target(self):
        mac2 = "52:54:00:12:34:57"
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sdz",
            target_type="disk", authorized_clients=[MAC, mac2],
        )
        clients = [
            SimpleNamespace(mac_address=MAC, state=ClientState.READY),
            SimpleNamespace(mac_address=mac2, state=ClientState.READY),
        ]
        coordinator = Mock()
        coordinator.job = job
        coordinator.clients.return_value = clients
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        socket_a, socket_b = Mock(), Mock()
        server._sessions = {MAC: socket_a, mac2: socket_b}
        server._target_devices = {MAC: "/dev/vda", mac2: "/dev/vdb"}
        server._progress = {}
        server._record_transfer_failure = Mock()

        with (
            patch("feclora.deployment.control.build_remote_clone_header",
                  side_effect=lambda source, target, device_type: (source, target, device_type)) as build_header,
            patch("feclora.deployment.control.send_remote_disk") as send_disk,
            patch.object(server, "arm_and_start", return_value=(MAC, mac2)) as arm,
            patch.object(server, "collect_results", return_value={MAC: "succeeded", mac2: "succeeded"}) as collect,
        ):
            result = server.run_remote_clone_job(operation_log_path="/tmp/operations.jsonl")

        self.assertEqual(result, {MAC: "succeeded", mac2: "succeeded"})
        arm.assert_called_once_with()
        self.assertEqual(build_header.call_count, 2)
        self.assertEqual(send_disk.call_count, 2)
        calls = {call.args[0]: call for call in send_disk.call_args_list}
        self.assertEqual(set(calls), {socket_a, socket_b})
        self.assertEqual(calls[socket_a].args[1], ("/dev/sdz", "/dev/vda", "disk"))
        self.assertEqual(calls[socket_b].args[1], ("/dev/sdz", "/dev/vdb", "disk"))
        for call in calls.values():
            self.assertEqual(call.kwargs["source_path"], "/dev/sdz")
            self.assertEqual(call.kwargs["confirmation"], "READ /dev/sdz")
            self.assertEqual(call.kwargs["operation_log_path"], "/tmp/operations.jsonl")
        collect.assert_called_once_with(timeout=86400)
        server._record_transfer_failure.assert_not_called()

    def test_remote_clone_rejects_below_threshold_before_arming(self):
        mac2 = "52:54:00:12:34:57"
        job = make_job(
            operation="clone", image_id=None, source_device="/dev/sdz",
            target_type="disk", authorized_clients=[MAC, mac2],
        )
        coordinator = Mock()
        coordinator.job = job
        coordinator.clients.return_value = [
            SimpleNamespace(mac_address=MAC, state=ClientState.READY),
        ]
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server.coordinator = coordinator
        server._lock = threading.RLock()
        server._sessions = {MAC: Mock()}
        server._target_devices = {MAC: "/dev/vda"}
        with patch.object(server, "arm_and_start") as arm:
            with self.assertRaisesRegex(DeploymentControlError, "at least 2 READY Client"):
                server.run_remote_clone_job()
        arm.assert_not_called()


if __name__ == "__main__":
    unittest.main()

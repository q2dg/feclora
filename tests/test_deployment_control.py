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

from feclora.deployment.control import (
    DeploymentControlError,
    DeploymentControlServer,
    LocalTargetApproval,
    join_deployment,
    receive_control_message,
    send_control_message,
)
from feclora.deployment.coordinator import DeploymentCoordinator, JobState
from feclora.deployment.job import DeploymentJob
from feclora.network.remote_clone_protocol import create_mutual_tls_context


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


class TLSContextTests(unittest.TestCase):
    def test_server_rejects_context_without_mandatory_peer_certificates(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        with self.assertRaisesRegex(DeploymentControlError, "TLS 1.3"):
            DeploymentControlServer(
                DeploymentCoordinator(make_job()), context,
                local_identity="URI:feclora-server",
                client_identity_to_mac={"URI:feclora-client": MAC},
            )


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
        with patch("feclora.deployment.control.connect_mutual_tls", return_value=fake):
            received, success, detail = join_deployment(
                "192.0.2.10", 9443, context,
                local_identity="URI:feclora-client",
                expected_server_identity="URI:feclora-server",
                mac_address=MAC, job_id=JOB_ID,
                prepare_local_target=lambda offered: LocalTargetApproval(
                    "/dev/vda", "Samsung SSD 1 TB", "ERASE /dev/vda FROM URI:feclora-server",
                ),
                execute_job=lambda offered, tls, approval: (True, "restore verified"),
            )
        self.assertEqual(received.job_id, JOB_ID)
        self.assertTrue(success)
        self.assertEqual(detail, "restore verified")
        outgoing = FakeSocket(bytes(fake.outgoing))
        ready = receive_control_message(outgoing, expected_type="ready")
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
            "ERASE /dev/vda FROM URI:feclora-server",
        )
        observed = []
        with patch("feclora.deployment.control.connect_mutual_tls", return_value=fake):
            join_deployment(
                "192.0.2.10", 9443, context,
                local_identity="URI:feclora-client",
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
        self.assertEqual(hello["certificate_identity"], "URI:feclora-client")
        self.assertNotIn("/dev/vda", json.dumps(ready))
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
        with patch("feclora.deployment.control.connect_mutual_tls", return_value=fake):
            with self.assertRaisesRegex(DeploymentControlError, "typed target confirmation"):
                join_deployment(
                    "192.0.2.10", 9443, context,
                    local_identity="URI:feclora-client",
                    expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: LocalTargetApproval(
                        "/dev/vda", "Virtual disk 1", "ERASE /dev/vdb FROM URI:feclora-server",
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
        with patch("feclora.deployment.control.connect_mutual_tls", return_value=fake):
            with self.assertRaisesRegex(DeploymentControlError, "did not arm"):
                join_deployment(
                    "192.0.2.10", 9443, context,
                    local_identity="URI:feclora-client",
                    expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: LocalTargetApproval(
                        "/dev/vda", "Local virtual disk",
                        "ERASE /dev/vda FROM URI:feclora-server",
                    ),
                    execute_job=lambda offered, tls, approval: (True, "unexpected"),
                )


class CoordinatorControlTests(unittest.TestCase):
    def _server(self, job):
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC, authenticated=True)
        coordinator.mark_ready(MAC)
        coordinator.arm()
        coordinator.mark_running(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
            client_identity_to_mac={"URI:feclora-client": MAC},
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        return coordinator, server, fake

    def test_restore_server_sends_job_bound_transfer_offer_before_image(self):
        coordinator, server, fake = self._server(make_job(image_id="golden"))
        with patch("feclora.deployment.control.send_image_set", return_value="manifest") as send:
            result = server.send_restore_image(
                MAC, "/images", "golden.manifest.json",
                trusted_public_key="/trusted/server.pub",
            )
        self.assertEqual(result, "manifest")
        offer = receive_control_message(FakeSocket(bytes(fake.outgoing)), expected_type="transfer_offer")
        self.assertEqual(offer["job_id"], JOB_ID)
        self.assertEqual(offer["image_id"], "golden")
        self.assertEqual(send.call_args.kwargs["expected_image_id"], "golden")

    def test_save_server_receives_job_bound_transfer_and_publishes(self):
        coordinator, server, fake = self._server(make_job(operation="save", image_id="golden"))
        fake.incoming.extend(frame({
            "type": "transfer_ready", "job_id": JOB_ID, "image_id": "golden",
        }))
        with patch("feclora.deployment.control.receive_image_set", return_value="/repo/golden.manifest.json") as receive:
            path = server.receive_saved_image(
                MAC, "/repo", trusted_public_key="/trusted/client.pub",
            )
        self.assertEqual(path, "/repo/golden.manifest.json")
        self.assertEqual(receive.call_args.kwargs["expected_image_id"], "golden")

    def test_save_server_records_client_failure_before_transfer(self):
        coordinator, server, fake = self._server(make_job(operation="save"))
        fake.incoming.extend(frame({
            "type": "result", "job_id": JOB_ID, "success": False,
            "detail": "capture rejected locally",
        }))
        self.assertEqual(
            server.receive_saved_image(MAC, "/repo", trusted_public_key="/trusted/client.pub"),
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
            client_identity_to_mac={"URI:feclora-client": MAC},
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
            client_identity_to_mac={"URI:feclora-client": MAC},
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
                trusted_public_key="/trusted/server.pub",
            )
        self.assertEqual(result, {MAC: "succeeded"})
        send.assert_called_once_with(
            MAC, "/images", "golden.manifest.json",
            trusted_public_key="/trusted/server.pub",
        )
        collect.assert_called_once()

    def _server_ready(self, job):
        coordinator = DeploymentCoordinator(job)
        coordinator.register_client(MAC, authenticated=True)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
            client_identity_to_mac={"URI:feclora-client": MAC},
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        return coordinator, server, fake

    def test_server_arms_and_tracks_authenticated_ready_client(self):
        coordinator = DeploymentCoordinator(make_job())
        coordinator.register_client(MAC, authenticated=True)
        coordinator.mark_ready(MAC)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        server = DeploymentControlServer(
            coordinator, context, local_identity="URI:feclora-server",
            client_identity_to_mac={"URI:feclora-client": MAC},
        )
        fake = FakeSocket()
        server._sessions[MAC] = fake
        self.assertEqual(server.arm_and_start(), (MAC,))
        self.assertEqual(coordinator.state, JobState.RUNNING)
        outgoing = FakeSocket(bytes(fake.outgoing))
        start = receive_control_message(outgoing, expected_type="start")
        self.assertEqual(start["job_id"], JOB_ID)
        self.assertEqual(start["operation"], "restore")



@unittest.skipUnless(shutil.which("openssl"), "openssl is required for loopback mTLS integration")
class MutualTLSControlIntegrationTests(unittest.TestCase):
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

    def test_mtls_session_transfers_signed_image_set_before_client_result(self):
        with tempfile.TemporaryDirectory() as directory:
            ca_key, ca_cert = self._certificate(directory, "ca", "URI:feclora-test-ca", ca=True)
            server_key, server_cert = self._certificate(
                directory, "server", "URI:feclora-server", ca_cert=ca_cert, ca_key=ca_key,
            )
            client_key, client_cert = self._certificate(
                directory, "client", "URI:feclora-client", ca_cert=ca_cert, ca_key=ca_key,
            )
            server_context = create_mutual_tls_context(
                "server", ca_file=ca_cert, certificate_file=server_cert,
                private_key_file=server_key,
            )
            client_context = create_mutual_tls_context(
                "client", ca_file=ca_cert, certificate_file=client_cert,
                private_key_file=client_key,
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
            with open(manifest_path + ".minisig", "wb") as stream:
                stream.write(b"test signature")

            job = make_job()
            coordinator = DeploymentCoordinator(job)
            server = DeploymentControlServer(
                coordinator, server_context, local_identity="URI:feclora-server",
                client_identity_to_mac={"URI:feclora-client": MAC},
            )
            host, port = server.start()
            accepted = []
            accept_thread = threading.Thread(
                target=lambda: accepted.append(server.accept_ready_client(server._listener)),
                daemon=True,
            )
            client_result = []
            approval = LocalTargetApproval(
                "/dev/vda", "Disposable VM disk",
                "ERASE /dev/vda FROM URI:feclora-server",
            )
            def client():
                client_result.append(join_deployment(
                    host, port, client_context,
                    local_identity="URI:feclora-client",
                    expected_server_identity="URI:feclora-server",
                    mac_address=MAC, job_id=JOB_ID,
                    prepare_local_target=lambda offered: approval,
                    execute_job=lambda offered, tls, local: self._receive_test_image(
                        tls, destination, offered,
                    ),
                ))
            client_thread = threading.Thread(target=client, daemon=True)
            try:
                with patch("feclora.deployment.artifact_transfer.verify_manifest_signature"):
                    accept_thread.start()
                    client_thread.start()
                    accept_thread.join(5)
                    self.assertFalse(accept_thread.is_alive())
                    server.arm_and_start()
                    server.send_restore_image(
                        MAC, source, manifest_path,
                        trusted_public_key="/trusted/server.pub",
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
            trusted_public_key="/trusted/server.pub",
        )
        return True, "signed image received and verified"

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
            server_context = create_mutual_tls_context(
                "server", ca_file=ca_cert,
                certificate_file=server_cert, private_key_file=server_key,
            )
            client_context = create_mutual_tls_context(
                "client", ca_file=ca_cert,
                certificate_file=client_cert, private_key_file=client_key,
            )
            coordinator = DeploymentCoordinator(make_job())
            server = DeploymentControlServer(
                coordinator, server_context, local_identity="URI:feclora-server",
                client_identity_to_mac={"URI:feclora-client": MAC},
            )
            _address, port = server.start("127.0.0.1", 0)
            client_result = []
            client_errors = []

            def run_client():
                try:
                    client_result.append(join_deployment(
                        "127.0.0.1", port, client_context,
                        local_identity="URI:feclora-client",
                        expected_server_identity="URI:feclora-server",
                        mac_address=MAC, job_id=JOB_ID,
                        prepare_local_target=lambda job: LocalTargetApproval(
                            "/dev/vda", "Virtual disk 1", "ERASE /dev/vda FROM URI:feclora-server",
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


if __name__ == "__main__":
    unittest.main()

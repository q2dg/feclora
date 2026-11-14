import hashlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import Mock, patch

from feclora.network.udpcast import (
    UDPcastConfig, UDPcastError, build_receiver_argv, build_sender_argv,
    build_physical_stream_sender_argv, build_physical_stream_receiver_argv,
    feed_physical_stream_to_sender, verify_received_physical_stream,
    send_physical_multicast_stream, receive_physical_multicast_stream,
    discard_staged_multicast_artifact, multicast_firewall_scope,
    receive_multicast_artifact_to_staging, send_multicast_artifact, verify_artifact_file,
)
from feclora.storage.image_manifest import ImageArtifact
from feclora.deployment.coordinator import ClientState, JobState


class UDPcastConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = UDPcastConfig(
            "enp1s0", "239.10.10.1", "239.10.10.2",
            portbase=9000, ttl=1, max_bitrate="100m", fec="8x8/128",
        )

    def test_builds_shell_free_sender_and_receiver_argv(self):
        sender = build_sender_argv("/usr/bin/udp-sender", "/images/disk.img", self.config)
        receiver = build_receiver_argv("/usr/bin/udp-receiver", "/tmp/staged", self.config)
        self.assertIn("--mcast-data-address", sender)
        self.assertIn("239.10.10.1", sender)
        self.assertIn("--fec", sender)
        self.assertNotIn("--autostart", sender)
        self.assertIn("/tmp/staged", receiver)
        self.assertNotIn("/dev/sda", receiver)

    def test_physical_stream_commands_use_pipes_without_file_or_device_paths(self):
        sender = build_physical_stream_sender_argv("/usr/bin/udp-sender", self.config)
        receiver = build_physical_stream_receiver_argv("/usr/bin/udp-receiver", self.config)
        self.assertNotIn("--file", sender)
        self.assertNotIn("--file", receiver)
        self.assertNotIn("/dev/", " ".join(sender + receiver))
        self.assertIn("--min-receivers", sender)
        self.assertIn("239.10.10.1", sender)
        self.assertIn("239.10.10.2", receiver)

    def test_physical_stream_sender_handles_short_writes_and_hashes_exact_bytes(self):
        payload = b"direct-block-stream" * 500
        class ShortWriter:
            def __init__(self):
                self.data = bytearray()
                self.closed = False
            def write(self, view):
                count = min(71, len(view))
                self.data.extend(view[:count])
                return count
            def close(self):
                self.closed = True
        writer = ShortWriter()
        result = feed_physical_stream_to_sender(
            io.BytesIO(payload), writer, len(payload), chunk_size=4096,
        )
        self.assertEqual(bytes(writer.data), payload)
        self.assertTrue(writer.closed)
        self.assertEqual(result["bytes_sent"], len(payload))
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())

    def test_physical_stream_receiver_writes_and_verifies_server_digest(self):
        payload = b"direct-block-stream" * 100
        stored = bytearray()
        offset = 0
        def write(view):
            count = min(97, len(view))
            stored.extend(view[:count])
            return count
        def readback(count):
            nonlocal offset
            data = bytes(stored[offset:offset + count])
            offset += len(data)
            return data
        result = verify_received_physical_stream(
            io.BytesIO(payload), write, lambda: None, readback,
            expected_bytes=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest(),
            chunk_size=4096,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["bytes_written"], len(payload))

    def test_physical_stream_receiver_rejects_server_digest_mismatch(self):
        payload = b"source-digest"
        with self.assertRaisesRegex(UDPcastError, "Server source digest"):
            verify_received_physical_stream(
                io.BytesIO(payload), lambda view: len(view), lambda: None,
                lambda count: payload[:count], expected_bytes=len(payload),
                expected_sha256="0" * 64, chunk_size=4096,
            )

    def test_rejects_non_multicast_group_and_invalid_port(self):
        with self.assertRaises(UDPcastError):
            UDPcastConfig("enp1s0", "192.0.2.1", "239.10.10.2")
        with self.assertRaises(UDPcastError):
            UDPcastConfig("enp1s0", "239.10.10.1", "239.10.10.2", portbase=9001)

    def test_rejects_same_rendezvous_and_data_group(self):
        with self.assertRaises(UDPcastError):
            UDPcastConfig("enp1s0", "239.10.10.1", "239.10.10.1")

    def test_rejects_shell_metacharacters_in_bitrate(self):
        with self.assertRaises(UDPcastError):
            UDPcastConfig("enp1s0", "239.10.10.1", "239.10.10.2", max_bitrate="100m; touch /tmp/pwn")
        with self.assertRaisesRegex(UDPcastError, "10 Gbit/s"):
            UDPcastConfig("enp1s0", "239.10.10.1", "239.10.10.2", max_bitrate="11g")

    def test_verifies_exact_artifact_size_and_digest(self):
        payload = b"feclora multicast image"
        artifact = ImageArtifact(
            "disk.img", "disk-image", "raw", "none",
            len(payload), hashlib.sha256(payload).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "disk.img")
            with open(path, "wb") as stream:
                stream.write(payload)
            verify_artifact_file(path, artifact)
            with open(path, "ab") as stream:
                stream.write(b"x")
            with self.assertRaisesRegex(UDPcastError, "size"):
                verify_artifact_file(path, artifact)

    def test_sender_accepts_authenticated_clients_already_running(self):
        job = SimpleNamespace(
            transport="multicast", network_interface="enp1s0",
            multicast_group="239.10.10.1", multicast_port=9000,
            image_id="golden-image",
        )
        coordinator = Mock()
        coordinator.job = job
        coordinator.state = JobState.RUNNING
        coordinator.clients.return_value = [
            SimpleNamespace(state=ClientState.RUNNING),
            SimpleNamespace(state=ClientState.RUNNING),
        ]
        manifest = SimpleNamespace(
            image_id="golden-image",
            artifacts=[SimpleNamespace(filename="disk.img")],
        )
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "disk.img")
            manifest_path = os.path.join(directory, "image.manifest.json")
            for path in (source, manifest_path):
                with open(path, "wb") as stream:
                    stream.write(b"x")
            with (
                patch("feclora.network.udpcast._load_manifest", return_value=manifest),
                patch("feclora.network.udpcast.verify_artifact_file"),
                patch("feclora.network.udpcast.shutil.which", return_value="/usr/bin/udp-sender"),
                patch("feclora.network.udpcast.multicast_firewall_scope", return_value=nullcontext()),
                patch("feclora.network.udpcast._run_process") as run,
            ):
                send_multicast_artifact(
                    coordinator, source, manifest_path, self.config, firewall=Mock(),
                )
            run.assert_called_once()

    def test_staging_preflight_rejects_insufficient_space(self):
        artifact = ImageArtifact(
            "disk.img", "disk-image", "raw", "none", 1024,
            hashlib.sha256(b"x" * 1024).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            firewall = Mock()
            with patch("feclora.network.udpcast.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(UDPcastError, "Insufficient free space"):
                    receive_multicast_artifact_to_staging(directory, artifact, self.config, firewall=firewall)

    def test_staging_receives_only_to_private_file_and_checks_size(self):
        artifact = ImageArtifact(
            "disk.img", "disk-image", "raw", "none", 3,
            hashlib.sha256(b"abc").hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            def fake_process(argv, **kwargs):
                target = argv[argv.index("--file") + 1]
                with open(target, "wb") as stream:
                    stream.write(b"abc")
                return Mock(returncode=0, poll=Mock(return_value=0))
            firewall = Mock()
            firewall.is_open.return_value = False
            path = receive_multicast_artifact_to_staging(
                directory, artifact, self.config, firewall=firewall,
                udp_receiver="/usr/bin/udp-receiver", runner_popen=fake_process,
            )
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"abc")
            discard_staged_multicast_artifact(path)
            self.assertEqual(os.listdir(directory), [])

    def test_firewall_scope_opens_exact_two_udp_ports_and_closes(self):
        firewall = Mock()
        firewall.is_open.return_value = False
        with multicast_firewall_scope(firewall, "enp1s0", 9000):
            firewall.open.assert_called_once_with("enp1s0", ["9000/udp", "9001/udp"], include_tftp=False)
        firewall.add_protocols.assert_called_once_with("enp1s0", ["igmp"])
        firewall.close.assert_called_once_with("enp1s0")

    def test_firewall_scope_closes_after_transfer_exception(self):
        firewall = Mock()
        firewall.is_open.return_value = False
        with self.assertRaisesRegex(RuntimeError, "transfer failed"):
            with multicast_firewall_scope(firewall, "enp1s0", 9000):
                raise RuntimeError("transfer failed")
        firewall.close.assert_called_once_with("enp1s0")

    def test_existing_pxe_zone_gets_only_temporary_udpcast_ports(self):
        firewall = Mock()
        firewall.is_open.return_value = True
        firewall.add_ports.return_value = ("9000/udp", "9001/udp")
        firewall.add_protocols.return_value = ("igmp",)
        with multicast_firewall_scope(firewall, "enp1s0", 9000):
            firewall.add_ports.assert_called_once_with("enp1s0", ["9000/udp", "9001/udp"])
            firewall.open.assert_not_called()
        firewall.add_protocols.assert_called_once_with("enp1s0", ["igmp"])
        firewall.remove_protocols.assert_called_once_with("enp1s0", ("igmp",))
        firewall.remove_ports.assert_called_once_with(
            "enp1s0", ("9000/udp", "9001/udp"),
        )
        firewall.close.assert_not_called()

    def test_staging_rejects_short_file_and_removes_it(self):
        artifact = ImageArtifact(
            "disk.img", "disk-image", "raw", "none", 3,
            hashlib.sha256(b"abc").hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            def fake_process(argv, **kwargs):
                target = argv[argv.index("--file") + 1]
                open(target, "wb").close()
                return Mock(returncode=0, poll=Mock(return_value=0))
            with self.assertRaisesRegex(UDPcastError, "size"):
                firewall = Mock()
                firewall.is_open.return_value = False
                receive_multicast_artifact_to_staging(
                    directory, artifact, self.config, firewall=firewall,
                    udp_receiver="/usr/bin/udp-receiver", runner_popen=fake_process,
                )
            self.assertEqual(os.listdir(directory), [])


class PhysicalMulticastProcessTests(unittest.TestCase):
    def setUp(self):
        self.config = UDPcastConfig("enp1s0", "239.10.10.1", "239.10.10.2")
        self.firewall = Mock()
        self.firewall.is_open.return_value = False

    def test_sender_uses_pipe_and_hashes_exact_source_without_file_arguments(self):
        payload = b"approved physical source"
        class Process:
            returncode = 0
            def __init__(self, **kwargs):
                self.stdin = io.BytesIO()
            def wait(self, **kwargs):
                return self.returncode
        calls = []
        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return Process(**kwargs)
        result = send_physical_multicast_stream(
            io.BytesIO(payload), len(payload), self.config,
            udp_sender="/usr/bin/udp-sender", runner_popen=popen,
            firewall=self.firewall,
        )
        argv, kwargs = calls[0]
        self.assertEqual(kwargs["stdin"], __import__("subprocess").PIPE)
        self.assertNotIn("--file", argv)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["bytes_sent"], len(payload))

    def test_receiver_writes_directly_and_verifies_readback(self):
        payload = b"multicast-to-block-device"
        class Process:
            returncode = 0
            def __init__(self, **kwargs):
                self.stdout = io.BytesIO(payload)
            def wait(self, **kwargs):
                return self.returncode
        stored = bytearray()
        def write(view):
            stored.extend(view)
            return len(view)
        def readback(count):
            start = len(readback.data)
            chunk = bytes(stored[start:start + count])
            readback.data.extend(chunk)
            return chunk
        readback.data = bytearray()
        result = receive_physical_multicast_stream(
            write, lambda: None, readback,
            expected_bytes=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            config=self.config, udp_receiver="/usr/bin/udp-receiver",
            runner_popen=lambda argv, **kwargs: Process(**kwargs),
            firewall=self.firewall,
        )
        self.assertEqual(bytes(stored), payload)
        self.assertTrue(result["verified"])

    def test_receiver_rejects_stream_digest_mismatch(self):
        payload = b"received bytes"
        class Process:
            returncode = 0
            def __init__(self, **kwargs):
                self.stdout = io.BytesIO(payload)
            def wait(self, **kwargs):
                return self.returncode
            def poll(self):
                return self.returncode
        with self.assertRaisesRegex(UDPcastError, "SHA-256"):
            receive_physical_multicast_stream(
                lambda view: len(view), lambda: None, lambda count: payload[:count],
                expected_bytes=len(payload), expected_sha256="0" * 64,
                config=self.config, udp_receiver="/usr/bin/udp-receiver",
                runner_popen=lambda argv, **kwargs: Process(**kwargs),
                firewall=self.firewall,
            )


if __name__ == "__main__":
    unittest.main()

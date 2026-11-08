import hashlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feclora.deployment.job import DeploymentJob
from feclora.deployment.coordinator import DeploymentCoordinator, JobState
from feclora.network.udpcast import (
    UDPcastConfig, UDPcastError, build_receiver_argv, build_sender_argv,
    receive_multicast_artifact_to_staging, verify_artifact_file,
)
from feclora.storage.image_manifest import ImageArtifact


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

    def test_staging_preflight_rejects_insufficient_space(self):
        artifact = ImageArtifact(
            "disk.img", "disk-image", "raw", "none", 1024,
            hashlib.sha256(b"x" * 1024).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch("feclora.network.udpcast.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(UDPcastError, "Insufficient free space"):
                    receive_multicast_artifact_to_staging(directory, artifact, self.config)

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
            path = receive_multicast_artifact_to_staging(
                directory, artifact, self.config,
                udp_receiver="/usr/bin/udp-receiver", runner_popen=fake_process,
            )
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"abc")

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
                receive_multicast_artifact_to_staging(
                    directory, artifact, self.config,
                    udp_receiver="/usr/bin/udp-receiver", runner_popen=fake_process,
                )
            self.assertEqual(os.listdir(directory), [])


if __name__ == "__main__":
    unittest.main()

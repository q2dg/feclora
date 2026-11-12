import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.image_publication import (
    ImagePublicationError, publish_image_set,
)


class ImagePublicationTests(unittest.TestCase):
    def test_rejects_path_separators_and_nul_in_publication_names(self):
        with tempfile.TemporaryDirectory() as repository:
            stage = os.path.join(repository, ".stage")
            os.mkdir(stage)
            for name in ("nested/payload.img", "nested\\payload.img", "payload\x00.img"):
                with self.subTest(name=repr(name)):
                    with self.assertRaises(ImagePublicationError):
                        publish_image_set(repository, stage, [name])

    def test_publishes_manifest_last_and_preserves_payload(self):
        with tempfile.TemporaryDirectory() as repository:
            stage = os.path.join(repository, ".stage")
            os.mkdir(stage)
            with open(os.path.join(stage, "payload.img"), "wb") as stream:
                stream.write(b"image")
            with open(os.path.join(stage, "manifest.json"), "wb") as stream:
                stream.write(b"manifest")

            real_link = os.link
            observed = []

            def observe_publication(src, dst, *args, **kwargs):
                observed.append(os.path.basename(os.fspath(dst)))
                if os.path.basename(os.fspath(dst)) == "manifest.json":
                    self.assertTrue(os.path.isfile(os.path.join(repository, "payload.img")))
                    self.assertFalse(os.path.exists(os.path.join(repository, "manifest.json")))
                return real_link(src, dst, *args, **kwargs)

            with patch("feclora.storage.image_publication.os.link", side_effect=observe_publication):
                publish_image_set(repository, stage, ["payload.img", "manifest.json"])
            self.assertEqual(observed, ["payload.img", "manifest.json"])

            with open(os.path.join(repository, "payload.img"), "rb") as stream:
                self.assertEqual(stream.read(), b"image")
            with open(os.path.join(repository, "manifest.json"), "rb") as stream:
                self.assertEqual(stream.read(), b"manifest")

    def test_collision_rolls_back_only_links_created_by_this_attempt(self):
        with tempfile.TemporaryDirectory() as repository:
            stage = os.path.join(repository, ".stage")
            os.mkdir(stage)
            for name in ("first.img", "taken.img", "manifest.json"):
                with open(os.path.join(stage, name), "wb") as stream:
                    stream.write(name.encode())
            with open(os.path.join(repository, "taken.img"), "wb") as stream:
                stream.write(b"pre-existing")

            with self.assertRaises(FileExistsError):
                publish_image_set(repository, stage, ["first.img", "taken.img", "manifest.json"])

            self.assertFalse(os.path.lexists(os.path.join(repository, "first.img")))
            with open(os.path.join(repository, "taken.img"), "rb") as stream:
                self.assertEqual(stream.read(), b"pre-existing")
            self.assertFalse(os.path.lexists(os.path.join(repository, "manifest.json")))

    def test_rollback_does_not_unlink_a_concurrent_replacement(self):
        with tempfile.TemporaryDirectory() as repository:
            stage = os.path.join(repository, ".stage")
            os.mkdir(stage)
            for name in ("first.img", "fail.img"):
                with open(os.path.join(stage, name), "wb") as stream:
                    stream.write(("staged-" + name).encode())
            real_link = os.link
            calls = 0

            def replace_then_fail(src, dst, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_link(src, dst, *args, **kwargs)
                os.unlink(os.path.join(repository, "first.img"))
                with open(os.path.join(repository, "first.img"), "wb") as stream:
                    stream.write(b"concurrent replacement")
                raise OSError("simulated publication failure")

            with patch("feclora.storage.image_publication.os.link", side_effect=replace_then_fail):
                with self.assertRaises(ImagePublicationError):
                    publish_image_set(repository, stage, ["first.img", "fail.img"])

            with open(os.path.join(repository, "first.img"), "rb") as stream:
                self.assertEqual(stream.read(), b"concurrent replacement")

    def test_concurrent_publishers_cannot_mix_image_sets(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        with tempfile.TemporaryDirectory() as repository:
            stages = [os.path.join(repository, f".stage-{index}") for index in range(2)]
            payloads = [b"publisher-zero", b"publisher-one"]
            for stage, payload in zip(stages, payloads):
                os.mkdir(stage)
                with open(os.path.join(stage, "payload.img"), "wb") as stream:
                    stream.write(payload)
                with open(os.path.join(stage, "manifest.json"), "wb") as stream:
                    stream.write(b"manifest-for-" + payload)

            barrier = Barrier(2)

            def publish(stage):
                barrier.wait(timeout=5)
                try:
                    publish_image_set(repository, stage, ["payload.img", "manifest.json"])
                    return "published"
                except FileExistsError:
                    return "collision"

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(publish, stages))

            self.assertCountEqual(outcomes, ["published", "collision"])
            with open(os.path.join(repository, "payload.img"), "rb") as stream:
                winning_payload = stream.read()
            with open(os.path.join(repository, "manifest.json"), "rb") as stream:
                winning_manifest = stream.read()
            self.assertIn(winning_payload, payloads)
            self.assertEqual(winning_manifest, b"manifest-for-" + winning_payload)

    def test_rejects_stage_directory_outside_repository(self):
        with tempfile.TemporaryDirectory() as repository, tempfile.TemporaryDirectory() as other:
            with open(os.path.join(other, "payload.img"), "wb") as stream:
                stream.write(b"image")
            with self.assertRaises(ImagePublicationError):
                publish_image_set(repository, other, ["payload.img"])


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from feclora.webapi import WebAPIError, dispatch


class WebAPITests(unittest.TestCase):
    def test_rejects_unknown_or_extra_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "exactly one"):
            dispatch({"action": "status", "command": "id"})
        with self.assertRaisesRegex(WebAPIError, "unsupported"):
            dispatch({"action": "shell"})

    def test_inventory_action_returns_only_inventory(self):
        with patch("feclora.webapi.collect_inventory", return_value={"devices": []}) as inventory:
            self.assertEqual(dispatch({"action": "inventory"}), {"devices": []})
        inventory.assert_called_once_with()

    def test_images_action_uses_manifest_inventory(self):
        with patch("feclora.webapi._images", return_value=[{"image_id": "base"}]):
            self.assertEqual(dispatch({"action": "images"}), {"images": [{"image_id": "base"}]})


if __name__ == "__main__":
    unittest.main()

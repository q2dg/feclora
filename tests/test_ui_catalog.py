import unittest

from feclora.ui_catalog import (
    KEYBOARD_LAYOUTS,
    LANGUAGES,
    MESSAGES,
    OPERATIONS,
    PAGES,
    PAGE_MESSAGE_KEYS,
)


class UICatalogTests(unittest.TestCase):
    def test_language_catalog_is_complete_and_unique(self):
        codes = [code for _label, code in LANGUAGES]
        self.assertEqual(len(codes), 25)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(set(codes).issubset(MESSAGES))

    def test_navigation_catalog_has_a_message_key_for_every_page(self):
        page_ids = {page_id for page_id, _label in PAGES}
        self.assertEqual(page_ids, set(PAGE_MESSAGE_KEYS))
        self.assertTrue(all(key for key in PAGE_MESSAGE_KEYS.values()))

    def test_operator_choices_are_unique(self):
        operation_ids = [operation_id for _label, operation_id in OPERATIONS]
        keyboard_ids = [layout_id for _label, layout_id in KEYBOARD_LAYOUTS]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(len(keyboard_ids), len(set(keyboard_ids)))


if __name__ == "__main__":
    unittest.main()

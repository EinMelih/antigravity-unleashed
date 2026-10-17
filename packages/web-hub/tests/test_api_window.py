import json
import tempfile
import unittest
from pathlib import Path

from src import api_window


class ApiWindowPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "scratch" / "api_window_visibility.json"

    def test_default_is_hidden_when_file_missing(self):
        self.assertFalse(api_window.read_visible(self.path))

    def test_corrupt_file_falls_back_to_hidden(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertFalse(api_window.read_visible(self.path))

    def test_preference_roundtrip_is_persisted(self):
        api_window.write_visible(True, self.path)
        self.assertTrue(api_window.read_visible(self.path))
        self.assertTrue(json.loads(self.path.read_text(encoding="utf-8"))["visible"])
        api_window.write_visible(False, self.path)
        self.assertFalse(api_window.read_visible(self.path))

    def test_apply_without_pids_changes_nothing(self):
        self.assertEqual(0, api_window.apply_visibility(set(), False))


if __name__ == "__main__":
    unittest.main()

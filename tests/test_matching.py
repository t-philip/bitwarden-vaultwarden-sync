"""Tests for item name + folder matching logic used during attachment restore."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.restore import _get_folder_name
from bwsync.export import _safe_name


class TestGetFolderName:
    def _vault(self, folders: list) -> dict:
        return {"folders": [{"id": str(i), "name": n} for i, n in enumerate(folders)]}

    def test_no_folder_id_returns_none(self):
        vault = self._vault(["Personal"])
        assert _get_folder_name(vault, "no-folder") is None

    def test_none_folder_id_returns_none(self):
        vault = self._vault(["Personal"])
        assert _get_folder_name(vault, None) is None

    def test_matching_id_returns_name(self):
        vault = {"folders": [{"id": "abc-123", "name": "Personal"}]}
        assert _get_folder_name(vault, "abc-123") == "Personal"

    def test_missing_id_returns_none(self):
        vault = {"folders": [{"id": "abc-123", "name": "Personal"}]}
        assert _get_folder_name(vault, "xyz-999") is None

    def test_empty_folders_list(self):
        assert _get_folder_name({"folders": []}, "abc-123") is None


class TestSafeName:
    def test_alphanumeric_unchanged(self):
        assert _safe_name("MyFolder") == "MyFolder"

    def test_slash_replaced(self):
        result = _safe_name("My/Folder")
        assert "/" not in result

    def test_empty_string_returns_placeholder(self):
        assert _safe_name("") == "_"

    def test_long_name_truncated_to_64(self):
        assert len(_safe_name("a" * 100)) <= 64

    def test_angle_brackets_replaced(self):
        result = _safe_name("Item: <test>")
        assert "<" not in result
        assert ">" not in result

    def test_allowed_chars_preserved(self):
        name = "My Item (2024) - backup.zip"
        result = _safe_name(name)
        assert result == name

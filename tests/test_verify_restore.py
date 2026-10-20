"""Tests for the post-restore verification pass.

Before this existed the run reported what was *sent* to the destination. These
cover reading it back and confirming what actually arrived.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.audit import verify_restore


def _export(tmp_path, items, folders=None):
    vault = {"folders": folders or [], "items": items}
    json_path = tmp_path / "vault.json"
    json_path.write_text(json.dumps(vault), encoding="utf-8")
    return SimpleNamespace(json_path=json_path, item_count=len(items))


def _dst_session(items, folders=None):
    responses = {
        ("list", "folders"): folders or [],
        ("list", "items"): items,
    }
    return SimpleNamespace(run_json=lambda *args: responses[tuple(args)])


class TestVerifyPasses:
    def test_identical_vaults_verify_ok(self, tmp_path):
        items = [{"name": "GitHub", "folderId": None}, {"name": "AWS", "folderId": None}]
        result = verify_restore(_export(tmp_path, items), _dst_session(items))
        assert result.ok
        assert result.missing == []
        assert result.extra == []
        assert result.dst_count == 2

    def test_empty_vaults_verify_ok(self, tmp_path):
        result = verify_restore(_export(tmp_path, []), _dst_session([]))
        assert result.ok

    def test_folders_resolved_on_both_sides(self, tmp_path):
        """Folder IDs differ between servers; matching is by folder *name*."""
        export = _export(
            tmp_path,
            [{"name": "Test Data Item", "folderId": "src-f1"}],
            folders=[{"id": "src-f1", "name": "Test Data Folder A"}],
        )
        dst = _dst_session(
            [{"name": "Test Data Item", "folderId": "dst-f9"}],
            folders=[{"id": "dst-f9", "name": "Test Data Folder A"}],
        )
        assert verify_restore(export, dst).ok


class TestVerifyDetectsProblems:
    def test_missing_item_detected(self, tmp_path):
        """The failure this whole pass exists to catch: import exited zero but
        did not place everything."""
        export = _export(tmp_path, [
            {"name": "GitHub", "folderId": None},
            {"name": "AWS", "folderId": None},
        ])
        dst = _dst_session([{"name": "GitHub", "folderId": None}])

        result = verify_restore(export, dst)

        assert not result.ok
        assert result.missing == [("AWS", "")]
        assert result.extra == []

    def test_extra_item_detected(self, tmp_path):
        export = _export(tmp_path, [{"name": "GitHub", "folderId": None}])
        dst = _dst_session([
            {"name": "GitHub", "folderId": None},
            {"name": "Leftover", "folderId": None},
        ])

        result = verify_restore(export, dst)

        assert not result.ok
        assert result.extra == [("Leftover", "")]
        assert result.missing == []

    def test_wrong_folder_counts_as_both_missing_and_extra(self, tmp_path):
        """An item restored into the wrong folder is not the same item."""
        export = _export(
            tmp_path,
            [{"name": "Test Data Item", "folderId": "f1"}],
            folders=[{"id": "f1", "name": "Test Data Folder A"}],
        )
        dst = _dst_session(
            [{"name": "Test Data Item", "folderId": "f2"}],
            folders=[{"id": "f2", "name": "Test Data Folder B"}],
        )

        result = verify_restore(export, dst)

        assert not result.ok
        assert result.missing == [("Test Data Item", "Test Data Folder A")]
        assert result.extra == [("Test Data Item", "Test Data Folder B")]

    def test_everything_missing_when_destination_empty(self, tmp_path):
        export = _export(tmp_path, [{"name": "GitHub", "folderId": None}])
        result = verify_restore(export, _dst_session([]))
        assert not result.ok
        assert result.missing == [("GitHub", "")]

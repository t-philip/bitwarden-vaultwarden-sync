"""Tests for destination-only audit rename tolerance."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.audit import audit_vaults, load_last_synced_keys, save_last_synced_keys


def _export(tmp_path, items, folders=None):
    """Build a fake ExportResult — audit_vaults only reads .json_path and .item_count."""
    vault = {
        "folders": folders or [],
        "items": items,
    }
    json_path = tmp_path / "vault.json"
    json_path.write_text(json.dumps(vault), encoding="utf-8")
    return SimpleNamespace(json_path=json_path, item_count=len(items))


def _dst_session(items, folders=None):
    """Fake BwSession — audit_vaults only calls run_json('list', 'folders'/'items')."""
    responses = {
        ("list", "folders"): folders or [],
        ("list", "items"): items,
    }
    return SimpleNamespace(run_json=lambda *args: responses[tuple(args)])


class TestAuditNoTolerance:
    """Baseline behaviour must be unchanged when last_synced_keys is empty (default)."""

    def test_no_dst_only_when_vaults_match(self, tmp_path):
        items = [{"name": "GitHub", "folderId": None}]
        export = _export(tmp_path, items)
        dst = _dst_session(items)
        audit = audit_vaults(export, dst)
        assert audit.dst_only == []
        assert audit.tolerated_renames == []

    def test_dst_only_item_aborts_by_default(self, tmp_path):
        export = _export(tmp_path, [{"name": "GitHub", "folderId": None}])
        dst = _dst_session([
            {"name": "GitHub", "folderId": None},
            {"name": "OldService", "folderId": None},
        ])
        audit = audit_vaults(export, dst)
        assert audit.dst_only == [("OldService", "")]
        assert audit.tolerated_renames == []
        assert audit.has_dst_only is True


class TestAuditRenameTolerance:
    """A dst-only item matching the last successful sync's key set is tolerated."""

    def test_renamed_item_tolerated_not_aborted(self, tmp_path):
        # Source renamed "OldName" -> "NewName" since the last sync.
        export = _export(tmp_path, [{"name": "NewName", "folderId": None}])
        dst = _dst_session([{"name": "OldName", "folderId": None}])
        last_synced = frozenset({("OldName", "")})

        audit = audit_vaults(export, dst, last_synced_keys=last_synced)

        assert audit.dst_only == []
        assert audit.tolerated_renames == [("OldName", "")]
        assert audit.has_dst_only is False

    def test_genuine_orphan_still_aborts_even_with_other_tolerated_keys(self, tmp_path):
        # "OldName" is an explained rename; "RandomVaultwardenItem" was never
        # part of any sync this tool performed -- must still abort.
        export = _export(tmp_path, [{"name": "NewName", "folderId": None}])
        dst = _dst_session([
            {"name": "OldName", "folderId": None},
            {"name": "RandomVaultwardenItem", "folderId": None},
        ])
        last_synced = frozenset({("OldName", "")})

        audit = audit_vaults(export, dst, last_synced_keys=last_synced)

        assert audit.dst_only == [("RandomVaultwardenItem", "")]
        assert audit.tolerated_renames == [("OldName", "")]
        assert audit.has_dst_only is True

    def test_folder_disambiguates_same_name_different_folder(self, tmp_path):
        # Same item name in a different folder is NOT the same key -- tolerance
        # must not blur across folders.
        export = _export(tmp_path, [{"name": "Login", "folderId": None}])
        dst = _dst_session([{"name": "Login", "folderId": "f1"}], folders=[{"id": "f1", "name": "Work"}])
        last_synced = frozenset({("Login", "")})  # only the no-folder version was ever synced

        audit = audit_vaults(export, dst, last_synced_keys=last_synced)

        assert audit.dst_only == [("Login", "Work")]
        assert audit.tolerated_renames == []

    def test_src_keys_exposed_for_persistence(self, tmp_path):
        export = _export(tmp_path, [{"name": "GitHub", "folderId": None}, {"name": "AWS", "folderId": None}])
        dst = _dst_session([])
        audit = audit_vaults(export, dst)
        assert audit.src_keys == frozenset({("GitHub", ""), ("AWS", "")})


class TestStatePersistence:
    def test_load_missing_file_returns_empty_set(self, tmp_path):
        assert load_last_synced_keys(tmp_path / "does_not_exist.json") == frozenset()

    def test_load_corrupt_file_returns_empty_set(self, tmp_path):
        state_path = tmp_path / "last_synced_keys.json"
        state_path.write_text("{not valid json", encoding="utf-8")
        assert load_last_synced_keys(state_path) == frozenset()

    def test_save_then_load_roundtrip(self, tmp_path):
        state_path = tmp_path / "sub" / "last_synced_keys.json"
        keys = frozenset({("GitHub", ""), ("Login", "Work")})
        save_last_synced_keys(state_path, keys)
        assert load_last_synced_keys(state_path) == keys

    def test_save_creates_parent_dir(self, tmp_path):
        state_path = tmp_path / "does" / "not" / "exist" / "last_synced_keys.json"
        save_last_synced_keys(state_path, frozenset({("A", "")}))
        assert state_path.exists()

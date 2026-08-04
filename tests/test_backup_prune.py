"""Tests for backup retention pruning.

Covers the naive/aware datetime boundary: the timestamp parsed out of a backup
filename has no tzinfo, so the cutoff must be naive too or the comparison raises
TypeError at runtime — on a path that only executes once a backup is old enough
to prune, which is exactly the kind of failure that hides for a week.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.backup import prune_backups


class _Cfg:
    def __init__(self, backup_dir: Path, retention_days: int):
        self.backup_dir = backup_dir
        self.backup_retention_days = retention_days


def _make_backup(backup_dir: Path, days_ago: int) -> Path:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"vault-{ts}.json.gpg"
    path.write_bytes(b"encrypted")
    return path


class TestPruneBackups:
    def test_old_backup_removed(self, tmp_path):
        old = _make_backup(tmp_path, days_ago=30)
        prune_backups(_Cfg(tmp_path, 7))
        assert not old.exists()

    def test_recent_backup_kept(self, tmp_path):
        recent = _make_backup(tmp_path, days_ago=2)
        prune_backups(_Cfg(tmp_path, 7))
        assert recent.exists()

    def test_no_typeerror_on_aware_naive_comparison(self, tmp_path):
        """Regression guard: this raised TypeError if the cutoff kept its tzinfo."""
        _make_backup(tmp_path, days_ago=30)
        _make_backup(tmp_path, days_ago=1)
        prune_backups(_Cfg(tmp_path, 7))  # must not raise

    def test_unrelated_files_untouched(self, tmp_path):
        keep = tmp_path / "readme.txt"
        keep.write_text("not a backup", encoding="utf-8")
        odd = tmp_path / "vault-not-a-timestamp.json.gpg"
        odd.write_bytes(b"x")

        prune_backups(_Cfg(tmp_path, 1))

        assert keep.exists()
        assert odd.exists()

    def test_mixed_ages(self, tmp_path):
        old_a = _make_backup(tmp_path, days_ago=90)
        old_b = _make_backup(tmp_path, days_ago=8)
        new = _make_backup(tmp_path, days_ago=1)

        prune_backups(_Cfg(tmp_path, 7))

        assert not old_a.exists()
        assert not old_b.exists()
        assert new.exists()

    def test_empty_dir_is_a_noop(self, tmp_path):
        prune_backups(_Cfg(tmp_path, 7))  # must not raise

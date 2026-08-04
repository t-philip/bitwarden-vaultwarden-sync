import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import BwSession
    from .export import ExportResult

log = logging.getLogger("bwsync")

Key = Tuple[str, str]  # (item_name, folder_name)


@dataclass
class AuditResult:
    src_count: int
    dst_count: int
    src_keys: FrozenSet[Key] = field(default_factory=frozenset)
    dst_only: List[Key] = field(default_factory=list)             # genuinely unexpected — abort-worthy
    tolerated_renames: List[Key] = field(default_factory=list)    # explained by AT-125 rename tolerance

    @property
    def has_dst_only(self) -> bool:
        return bool(self.dst_only)


def load_last_synced_keys(state_path: Path) -> FrozenSet[Key]:
    """Keys (item_name, folder_name) restored to the destination during the
    last successful sync. Missing/unreadable file → empty set, which makes
    audit_vaults() behave exactly as it did before AT-125 (any current
    dst-only item aborts) — the safe default for a first run or a corrupted
    state file."""
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        return frozenset((name, folder) for name, folder in raw)
    except Exception:
        return frozenset()


def save_last_synced_keys(state_path: Path, keys: FrozenSet[Key]) -> None:
    """Persist this run's restored item keys for the next run's audit. Called
    only after a real (non-dry-run) wipe+restore succeeds — dst is guaranteed
    to equal src at that point, which is the whole basis for the tolerance
    check next time."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(sorted(list(k) for k in keys), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass
class VerifyResult:
    """Outcome of the post-restore comparison (see verify_restore)."""
    src_count: int
    dst_count: int
    missing: List[Key] = field(default_factory=list)   # in source, absent from destination
    extra: List[Key] = field(default_factory=list)     # in destination, absent from source

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


def verify_restore(export: "ExportResult", dst_session: "BwSession") -> VerifyResult:
    """Re-read the destination after a restore and confirm it matches the source.

    Everything before this point reports what was *sent*. `bw import` exiting zero
    is not evidence that the destination now holds the data — this reads it back and
    compares by the same (item_name, folder_name) key the pre-wipe audit uses.

    Non-fatal by design: the wipe and restore have already happened, so a mismatch
    is something the operator must see, not something aborting can undo. It is
    surfaced loudly and reflected in the exit code rather than raising.
    """
    vault_data = json.loads(export.json_path.read_text(encoding="utf-8"))
    src_folder_map = {f["id"]: f["name"] for f in vault_data.get("folders", [])}

    src_keys: set = set()
    for item in vault_data.get("items", []):
        folder_id = item.get("folderId")
        folder_name = src_folder_map.get(folder_id, "") if folder_id else ""
        src_keys.add((item.get("name", ""), folder_name))

    dst_folders = dst_session.run_json("list", "folders")
    dst_folder_map = {f["id"]: f["name"] for f in dst_folders}

    dst_items = dst_session.run_json("list", "items")
    dst_keys: set = set()
    for item in dst_items:
        folder_id = item.get("folderId")
        folder_name = dst_folder_map.get(folder_id, "") if folder_id else ""
        dst_keys.add((item.get("name", ""), folder_name))

    return VerifyResult(
        src_count=len(src_keys),
        dst_count=len(dst_items),
        missing=sorted(src_keys - dst_keys),
        extra=sorted(dst_keys - src_keys),
    )


def audit_vaults(
    export: "ExportResult",
    dst_session: "BwSession",
    last_synced_keys: FrozenSet[Key] = frozenset(),
) -> AuditResult:
    """Compare source export against live destination vault.

    Matching is by (item_name, folder_name) — IDs are always different between
    Bitwarden.com and Vaultwarden even after a successful sync.

    AT-125 rename tolerance: a destination-only item is only treated as a
    genuine, abort-worthy orphan if it was NOT part of the last successful
    sync's restored set. Vaultwarden is wiped-and-restored from source on
    every run, so its only expected content immediately before this run is
    exactly what the last successful sync put there. A dst-only item that
    WAS part of that set is explained by a rename/deletion at the true
    source since then (AT-123's failure mode) — safe to let the upcoming
    wipe remove it, no manual cleanup needed. A dst-only item that was never
    part of any run we performed is a real anomaly (something added to
    Vaultwarden out-of-band, bypassing the sync entirely) and still aborts.

    This does not weaken the guard for genuinely foreign items: tolerance
    requires positive proof (presence in last_synced_keys) that *this tool*
    put that exact key there last time, never an assumption.
    """
    vault_data = json.loads(export.json_path.read_text(encoding="utf-8"))
    src_folder_map = {f["id"]: f["name"] for f in vault_data.get("folders", [])}

    src_keys: set = set()
    for item in vault_data.get("items", []):
        name = item.get("name", "")
        folder_id = item.get("folderId")
        folder_name = src_folder_map.get(folder_id, "") if folder_id else ""
        src_keys.add((name, folder_name))

    dst_folders = dst_session.run_json("list", "folders")
    dst_folder_map = {f["id"]: f["name"] for f in dst_folders}

    dst_items_raw = dst_session.run_json("list", "items")
    dst_count = len(dst_items_raw)

    dst_only: List[Key] = []
    tolerated_renames: List[Key] = []
    for item in dst_items_raw:
        name = item.get("name", "")
        folder_id = item.get("folderId")
        folder_name = dst_folder_map.get(folder_id, "") if folder_id else ""
        key = (name, folder_name)
        if key not in src_keys:
            if key in last_synced_keys:
                tolerated_renames.append(key)
            else:
                dst_only.append(key)

    return AuditResult(
        src_count=export.item_count,
        dst_count=dst_count,
        src_keys=frozenset(src_keys),
        dst_only=dst_only,
        tolerated_renames=tolerated_renames,
    )

import json
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import BwSession
    from .export import ExportResult

log = logging.getLogger("bwsync")


@dataclass
class AuditResult:
    src_count: int
    dst_count: int
    dst_only: List[Tuple[str, str]] = field(default_factory=list)  # (name, folder_name)

    @property
    def has_dst_only(self) -> bool:
        return bool(self.dst_only)


def audit_vaults(export: "ExportResult", dst_session: "BwSession") -> AuditResult:
    """Compare source export against live destination vault.

    Matching is by (item_name, folder_name) — IDs are always different between
    Bitwarden.com and Vaultwarden even after a successful sync.
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

    dst_only: List[Tuple[str, str]] = []
    for item in dst_items_raw:
        name = item.get("name", "")
        folder_id = item.get("folderId")
        folder_name = dst_folder_map.get(folder_id, "") if folder_id else ""
        if (name, folder_name) not in src_keys:
            dst_only.append((name, folder_name))

    return AuditResult(src_count=export.item_count, dst_count=dst_count, dst_only=dst_only)

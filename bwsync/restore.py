import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .session import BwSession
    from .export import ExportResult

log = logging.getLogger("bwsync")


@dataclass
class RestoreResult:
    items_restored: int = 0
    items_expected: int = 0
    attachments_restored: int = 0
    attachment_failures: List[str] = field(default_factory=list)

    @property
    def item_count_matches(self) -> bool:
        """Whether the destination confirmed as many items as the source sent."""
        return self.items_restored == self.items_expected


def restore_vault(
    session: "BwSession",
    export: "ExportResult",
    cfg: "Config",
) -> RestoreResult:
    result = RestoreResult(items_expected=export.item_count)

    # Import vault JSON (restores items + folders)
    session.run("import", "bitwardenjson", str(export.json_path))

    # Sync local cache so newly imported items are visible. This has to happen
    # before the count below as well as before attachment matching — without it
    # the CLI answers from a cache that predates the import.
    session.run("sync")

    # Count what the destination actually holds rather than assuming the import
    # placed everything that was sent. `bw import` can exit zero having restored
    # fewer items than the file contained, and reporting export.item_count here
    # would render that partial success indistinguishable from a full one.
    result.items_restored = len(session.run_json("list", "items"))

    if not export.attachments:
        return result

    # Build lookup: (item_name, folder_id_in_new_vault) → item_id
    vault_data = json.loads(export.json_path.read_text(encoding="utf-8"))
    folders = session.run_json("list", "folders")
    folder_name_to_id = {f["name"]: f["id"] for f in folders}

    items = session.run_json("list", "items")
    item_lookup: dict = {}
    for item in items:
        key = (item["name"], item.get("folderId"))
        if key not in item_lookup:
            item_lookup[key] = item["id"]

    # Re-upload each attachment
    for att in export.attachments:
        folder_name = _get_folder_name(vault_data, att.folder_id)
        new_folder_id = folder_name_to_id.get(folder_name) if folder_name else None
        item_id = item_lookup.get((att.item_name, new_folder_id))

        if not item_id:
            msg = (
                f"No match for attachment {att.attachment_name!r} — "
                f"item {att.item_name!r} not found in folder {folder_name!r}"
            )
            log.warning(msg)
            result.attachment_failures.append(msg)
            continue

        try:
            session.run(
                "create", "attachment",
                "--file", str(att.local_path),
                "--itemid", item_id,
            )
            result.attachments_restored += 1
            log.debug(
                "Uploaded: %s → %s (folder: %s)",
                att.attachment_name, att.item_name, folder_name,
            )
        except Exception as exc:
            msg = f"Upload failed for {att.attachment_name!r} on {att.item_name!r}: {exc}"
            log.warning(msg)
            result.attachment_failures.append(msg)

    return result


def _get_folder_name(vault_data: dict, folder_id: Optional[str]) -> Optional[str]:
    if not folder_id or folder_id == "no-folder":
        return None
    for folder in vault_data.get("folders", []):
        if folder["id"] == folder_id:
            return folder["name"]
    return None

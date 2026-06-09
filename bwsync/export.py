import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import BwSession

log = logging.getLogger("bwsync")


@dataclass
class AttachmentInfo:
    item_id: str
    item_name: str
    folder_id: str        # original source folder ID, or "no-folder"
    attachment_id: str
    attachment_name: str
    local_path: Path


@dataclass
class ExportResult:
    json_path: Path
    attachments: List[AttachmentInfo]
    item_count: int

    @property
    def attachment_count(self) -> int:
        return len(self.attachments)


def export_vault(session: "BwSession", export_dir: Path) -> ExportResult:
    export_dir.mkdir(parents=True, exist_ok=True)
    json_path = export_dir / "vault.json"

    session.run("export", "--format", "json", "--output", str(json_path))

    vault_data = json.loads(json_path.read_text(encoding="utf-8"))
    item_count = len(vault_data.get("items", []))

    # Build folder map: id → name
    folders_raw = session.run_json("list", "folders")
    folder_map = {f["id"]: f["name"] for f in folders_raw}

    # Find personal items with attachments (skip org items — see README limitations)
    items = session.run_json("list", "items")
    attachments: List[AttachmentInfo] = []
    att_dir = export_dir / "attachments"
    att_dir.mkdir(exist_ok=True)

    for item in items:
        if item.get("organizationId"):
            continue
        if not item.get("attachments"):
            continue

        item_id = item["id"]
        item_name = item["name"]
        folder_id = item.get("folderId") or "no-folder"
        folder_name = folder_map.get(folder_id, "no-folder")

        item_dir = att_dir / _safe_name(folder_name) / _safe_name(item_name)
        item_dir.mkdir(parents=True, exist_ok=True)

        for att in item["attachments"]:
            att_id = att["id"]
            att_name = att["fileName"]
            out_path = item_dir / att_name

            log.debug(
                "Downloading: %s / %s / %s",
                folder_name, item_name, att_name,
            )
            session.run(
                "get", "attachment", att_id,
                "--itemid", item_id,
                "--output", str(out_path),
            )

            attachments.append(AttachmentInfo(
                item_id=item_id,
                item_name=item_name,
                folder_id=folder_id,
                attachment_id=att_id,
                attachment_name=att_name,
                local_path=out_path,
            ))

    return ExportResult(json_path=json_path, attachments=attachments, item_count=item_count)


def _safe_name(name: str) -> str:
    """Sanitise a vault name for use as a filesystem path component."""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.()")
    result = "".join(c if c in allowed else "_" for c in name)
    return result[:64].strip() or "_"

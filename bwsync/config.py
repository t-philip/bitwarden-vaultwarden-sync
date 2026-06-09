import os
from dataclasses import dataclass
from pathlib import Path


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ValueError(f"Required environment variable {key!r} is not set")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass
class Config:
    # Source
    bw_source_url: str
    bw_source_email: str
    bw_source_client_id: str
    bw_source_client_secret: str
    bw_source_password: str

    # Destination
    bw_dest_url: str
    bw_dest_email: str
    bw_dest_client_id: str
    bw_dest_client_secret: str
    bw_dest_password: str

    # Wipe
    vw_wipe_method: str  # "cli" or "api"

    # Backup
    backup_enabled: bool
    backup_dir: Path
    backup_gpg_passphrase: str
    backup_retention_days: int

    # Notifications
    telegram_bot_token: str
    telegram_chat_id: str

    # Runtime
    temp_dir: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        wipe_method = _optional("VW_WIPE_METHOD", "cli").lower()
        if wipe_method not in ("cli", "api"):
            raise ValueError("VW_WIPE_METHOD must be 'cli' or 'api'")

        backup_enabled = _optional("BACKUP_ENABLED", "true").lower() in ("true", "1", "yes")

        return cls(
            bw_source_url=_optional("BW_SOURCE_URL", "https://vault.bitwarden.com"),
            bw_source_email=_require("BW_SOURCE_EMAIL"),
            bw_source_client_id=_require("BW_SOURCE_CLIENT_ID"),
            bw_source_client_secret=_require("BW_SOURCE_CLIENT_SECRET"),
            bw_source_password=_require("BW_SOURCE_PASSWORD"),

            bw_dest_url=_require("BW_DEST_URL"),
            bw_dest_email=_require("BW_DEST_EMAIL"),
            bw_dest_client_id=_require("BW_DEST_CLIENT_ID"),
            bw_dest_client_secret=_require("BW_DEST_CLIENT_SECRET"),
            bw_dest_password=_require("BW_DEST_PASSWORD"),

            vw_wipe_method=wipe_method,

            backup_enabled=backup_enabled,
            backup_dir=Path(_optional("BACKUP_DIR", "/var/backups/bw-sync")),
            backup_gpg_passphrase=_optional("BACKUP_GPG_PASSPHRASE"),
            backup_retention_days=int(_optional("BACKUP_RETENTION_DAYS", "7")),

            telegram_bot_token=_optional("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_optional("TELEGRAM_CHAT_ID"),

            temp_dir=Path(_optional("TEMP_DIR", "/dev/shm/bw-sync")),
            log_level=_optional("LOG_LEVEL", "INFO").upper(),
        )

    def validate(self) -> None:
        if self.backup_enabled and not self.backup_gpg_passphrase:
            raise ValueError(
                "BACKUP_GPG_PASSPHRASE is required when BACKUP_ENABLED=true. "
                "Set BACKUP_ENABLED=false to skip backups (not recommended)."
            )
        if self.vw_wipe_method == "api" and not self.bw_dest_email:
            raise ValueError("BW_DEST_EMAIL is required when VW_WIPE_METHOD=api")

import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("bwsync")


def create_backup(json_path: Path, cfg: "Config") -> Path:
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = cfg.backup_dir / f"vault-{timestamp}.json.gpg"

    result = subprocess.run(
        [
            "gpg", "--batch", "--yes",
            "--symmetric",
            "--cipher-algo", "AES256",
            "--passphrase", cfg.backup_gpg_passphrase,
            "--output", str(out_path),
            str(json_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GPG backup failed: {result.stderr.strip()}")

    log.debug("Backup written: %s", out_path.name)
    return out_path


def prune_backups(cfg: "Config") -> None:
    # Naive UTC: the timestamp parsed back out of the filename has no tzinfo, so the
    # cutoff must be naive too or the comparison raises TypeError.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=cfg.backup_retention_days)
    pruned = 0
    for f in cfg.backup_dir.glob("vault-*.json.gpg"):
        try:
            # Filename: vault-YYYYMMDD-HHMMSS.json.gpg
            ts_str = f.name.removeprefix("vault-").removesuffix(".json.gpg")
            ts = datetime.strptime(ts_str, "%Y%m%d-%H%M%S")
            if ts < cutoff:
                f.unlink()
                pruned += 1
                log.debug("Pruned old backup: %s", f.name)
        except (ValueError, OSError):
            pass

    if pruned:
        log.info("Pruned %d old backup(s) (retention: %d days).", pruned, cfg.backup_retention_days)

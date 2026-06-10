#!/usr/bin/env python3
"""bitwarden-vaultwarden-sync — entry point."""

import argparse
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from bwsync.config import Config
from bwsync.log import setup_logging
from bwsync.session import BwSession
from bwsync.audit import audit_vaults
from bwsync.export import export_vault
from bwsync.wipe import wipe_vault
from bwsync.restore import restore_vault
from bwsync.backup import create_backup, prune_backups
from bwsync.notify import Notifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync a Bitwarden.com vault to a self-hosted Vaultwarden instance.\n\n"
            "WARNING: this tool performs a full wipe of the destination vault before\n"
            "restoring. Always verify your backup before the first live run."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Export + backup only. Skips wipe and restore. "
            "Use this to verify credentials and measure vault size before the first live run."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        metavar="PATH",
        help="Path to .env file (default: .env in the current directory).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(env_path)
    elif args.env_file != ".env":
        print(f"Error: env file not found: {env_path}", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = Config.from_env()
        cfg.validate()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    log = setup_logging(cfg.log_level)
    notifier = Notifier(cfg)

    if args.dry_run:
        log.info("--- DRY RUN — wipe and restore will be skipped ---")

    tmp = cfg.temp_dir
    tmp.mkdir(parents=True, exist_ok=True)

    src = BwSession(
        server_url=cfg.bw_source_url,
        client_id=cfg.bw_source_client_id,
        client_secret=cfg.bw_source_client_secret,
        master_password=cfg.bw_source_password,
        config_dir=tmp / "src-appdata",
        label="source",
    )
    dst = BwSession(
        server_url=cfg.bw_dest_url,
        client_id=cfg.bw_dest_client_id,
        client_secret=cfg.bw_dest_client_secret,
        master_password=cfg.bw_dest_password,
        config_dir=tmp / "dst-appdata",
        label="destination",
    )

    try:
        log.info("Logging in to source (%s)…", cfg.bw_source_url)
        src.login()
        src.unlock()

        log.info("Logging in to destination (%s)…", cfg.bw_dest_url)
        dst.login()
        dst.unlock()

        log.info("Exporting source vault…")
        export = export_vault(src, tmp / "export")
        log.info("Exported %d item(s), %d attachment(s).", export.item_count, export.attachment_count)

        if cfg.backup_enabled:
            log.info("Creating encrypted backup…")
            backup_path = create_backup(export.json_path, cfg)
            log.info("Backup: %s", backup_path)
            prune_backups(cfg)

        log.info("Auditing destination vault…")
        audit = audit_vaults(export, dst)
        log.info(
            "Source: %d item(s) | Destination: %d item(s) before sync.",
            audit.src_count,
            audit.dst_count,
        )

        if audit.has_dst_only:
            log.warning(
                "%d item(s) found in Vaultwarden that are not in Bitwarden.com:",
                len(audit.dst_only),
            )
            for name, folder in audit.dst_only:
                label = f"{name!r} ({folder})" if folder else f"{name!r} (no folder)"
                log.warning("  • %s", label)
            if not args.dry_run:
                notifier.send_dst_only_abort(audit.dst_only)
                log.error(
                    "Sync aborted — delete the above item(s) from Vaultwarden manually, "
                    "then re-run the sync."
                )
                sys.exit(1)
        else:
            log.info("No destination-only items found.")

        if args.dry_run:
            log.info(
                "Dry run complete. Would wipe destination and restore "
                "%d item(s), %d attachment(s). No changes made.",
                export.item_count,
                export.attachment_count,
            )
            return

        log.info("Wiping destination vault (method: %s)…", cfg.vw_wipe_method)
        wipe_vault(dst, cfg)

        log.info("Restoring vault…")
        result = restore_vault(dst, export, cfg)

        log.info(
            "Sync complete — %d item(s), %d/%d attachment(s) restored. "
            "Vaultwarden: %d → %d item(s).",
            result.items_restored,
            result.attachments_restored,
            export.attachment_count,
            audit.dst_count,
            result.items_restored,
        )

        if result.attachment_failures:
            log.warning("%d attachment(s) could not be restored:", len(result.attachment_failures))
            for msg in result.attachment_failures:
                log.warning("  %s", msg)

        notifier.send_success(result.items_restored, result.attachments_restored, audit.dst_count)

    except Exception as exc:
        log.error("Sync failed: %s", exc, exc_info=(cfg.log_level == "DEBUG"))
        notifier.send_failure(str(exc))
        sys.exit(1)

    finally:
        src.logout()
        dst.logout()
        # Wipe temp dir — contains plaintext vault data
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    main()

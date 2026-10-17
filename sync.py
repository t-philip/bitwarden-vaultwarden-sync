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
from bwsync.audit import (
    audit_vaults,
    verify_restore,
    load_last_synced_keys,
    save_last_synced_keys,
)
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

    # appdata_dir is separate from tmp and persists on disk across runs. It
    # holds only the bw CLI's own device_id + last-used server URL — logout()
    # clears any account/vault state from it every run (see BwSession.login).
    # Wiping it (as it used to live under tmp) reset the CLI's device
    # identity on every sync, so Bitwarden.com treated each nightly run as a
    # brand-new device login and emailed a "new device" security alert daily.
    cfg.appdata_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    src = BwSession(
        server_url=cfg.bw_source_url,
        client_id=cfg.bw_source_client_id,
        client_secret=cfg.bw_source_client_secret,
        master_password=cfg.bw_source_password,
        config_dir=cfg.appdata_dir / "src-appdata",
        label="source",
    )
    dst = BwSession(
        server_url=cfg.bw_dest_url,
        client_id=cfg.bw_dest_client_id,
        client_secret=cfg.bw_dest_client_secret,
        master_password=cfg.bw_dest_password,
        config_dir=cfg.appdata_dir / "dst-appdata",
        label="destination",
        ca_bundle=cfg.bw_dest_ca_bundle,
        tls_verify=cfg.bw_dest_tls_verify,
    )

    if cfg.bw_dest_ca_bundle is not None:
        log.info("Destination TLS: trusting CA bundle %s", cfg.bw_dest_ca_bundle)
    elif not cfg.bw_dest_tls_verify:
        log.warning(
            "Destination TLS verification is DISABLED (BW_DEST_TLS_VERIFY=false). "
            "Prefer BW_DEST_CA_BUNDLE, which keeps verification on."
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
        # last_synced_keys.json records what the last successful sync
        # actually restored, so a dst-only item that matches it (renamed or
        # deleted at the true source since then) doesn't force a manual abort —
        # see audit_vaults()'s docstring for the full reasoning.
        state_path = cfg.appdata_dir / "last_synced_keys.json"
        last_synced_keys = load_last_synced_keys(state_path)
        audit = audit_vaults(export, dst, last_synced_keys=last_synced_keys)
        log.info(
            "Source: %d item(s) | Destination: %d item(s) before sync.",
            audit.src_count,
            audit.dst_count,
        )

        if audit.tolerated_renames:
            log.info(
                "%d destination item(s) explained by a rename/deletion at the source "
                "since the last sync — will be replaced by the wipe, no action needed:",
                len(audit.tolerated_renames),
            )
            for name, folder in audit.tolerated_renames:
                label = f"{name!r} ({folder})" if folder else f"{name!r} (no folder)"
                log.info("  • %s", label)

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

        # Read the destination back and confirm it matches the source. Everything
        # above this point reports what was sent; only this reports what arrived.
        log.info("Verifying restored vault…")
        verify = verify_restore(export, dst)

        # dst now equals src exactly (that's what the wipe+restore just
        # did) — persist this run's source keys so the next run's audit can
        # tell a real rename/deletion apart from a genuine out-of-band orphan.
        # Only persisted when verification agrees: recording a key set the
        # destination does not actually hold would let the next run's rename
        # tolerance excuse a genuinely missing item.
        if verify.ok:
            save_last_synced_keys(state_path, audit.src_keys)
        else:
            log.warning(
                "Verification mismatch — not updating %s. The next run will treat "
                "every destination-only item as abort-worthy, which is the safe "
                "default.",
                state_path.name,
            )

        log.info(
            "Sync complete — %d item(s), %d/%d attachment(s) restored. "
            "Vaultwarden: %d → %d item(s).",
            result.items_restored,
            result.attachments_restored,
            export.attachment_count,
            audit.dst_count,
            result.items_restored,
        )

        if not result.item_count_matches:
            log.warning(
                "Item count mismatch — source exported %d item(s) but the "
                "destination reports %d.",
                result.items_expected,
                result.items_restored,
            )

        if result.attachment_failures:
            log.warning("%d attachment(s) could not be restored:", len(result.attachment_failures))
            for msg in result.attachment_failures:
                log.warning("  %s", msg)

        if not verify.ok:
            if verify.missing:
                log.error(
                    "%d item(s) present in Bitwarden.com are MISSING from Vaultwarden "
                    "after the restore:",
                    len(verify.missing),
                )
                for name, folder in verify.missing:
                    log.error("  • %r (%s)", name, folder or "no folder")
            if verify.extra:
                log.error(
                    "%d unexpected item(s) present in Vaultwarden after the restore:",
                    len(verify.extra),
                )
                for name, folder in verify.extra:
                    log.error("  • %r (%s)", name, folder or "no folder")

            notifier.send_verify_failure(verify.missing, verify.extra)
            log.error(
                "Restore verification FAILED. The destination does not match the "
                "source — re-run the sync and investigate if it recurs."
            )
            sys.exit(1)

        log.info("Verification passed — destination matches source (%d items).", verify.dst_count)

    except Exception as exc:
        log.error("Sync failed: %s", exc, exc_info=(cfg.log_level == "DEBUG"))
        notifier.send_failure(str(exc))
        sys.exit(1)

    finally:
        src.logout()
        dst.logout()
        # Wipe temp dir — contains the decrypted vault export.
        # The exception is suppressed so cleanup can never mask the real error that
        # brought us here, but it must never be silent: a failure here means
        # plaintext vault data is still on the filesystem, which is exactly the
        # thing the tmpfs staging design exists to prevent.
        try:
            shutil.rmtree(tmp)
        except Exception as exc:
            log.warning(
                "Could not remove temp directory %s: %s — it may still contain a "
                "DECRYPTED copy of your vault. Remove it manually.",
                tmp, exc,
            )
        else:
            if tmp.exists():
                log.warning(
                    "Temp directory %s still exists after cleanup — check it for "
                    "plaintext vault data.", tmp,
                )


if __name__ == "__main__":
    main()

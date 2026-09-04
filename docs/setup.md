# Setup Guide

## Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.9+ | `python --version` |
| Bitwarden CLI (`bw`) | 2024.x | [Install guide](https://bitwarden.com/help/cli/) |
| GPG | Any | Only needed if `BACKUP_ENABLED=true` |
| tmpfs mount | — | `/dev/shm` on most Linux systems |

Install the Bitwarden CLI on Linux:
```bash
# Via npm
npm install -g @bitwarden/cli

# Or download the binary directly from:
# https://bitwarden.com/help/cli/#download-and-install
```

## Step 1 — Get API keys from Bitwarden

Bitwarden's US and EU clouds are separate, non-mergeable accounts — log in at the
one your account actually lives in:

- US cloud: [vault.bitwarden.com](https://vault.bitwarden.com) — leave
  `BW_SOURCE_URL` unset (defaults to this).
- EU cloud: [vault.bitwarden.eu](https://vault.bitwarden.eu) — set
  `BW_SOURCE_URL=https://vault.bitwarden.eu`.

1. Log in at the URL for your region
2. Go to **Account Settings → Security → API Key**
3. Click **View API Key** (requires master password)
4. Note your `client_id` and `client_secret`

These become `BW_SOURCE_CLIENT_ID` and `BW_SOURCE_CLIENT_SECRET` in your `.env`.
`BW_SOURCE_EMAIL` must be the login email for that same account — if you have
previously migrated an account from one region to the other, this may not be the
email you expect.

## Step 2 — Get API keys from Vaultwarden

1. Log in to your Vaultwarden instance
2. Go to **Account Settings → Security → API Key**
3. Note your `client_id` and `client_secret`

These become `BW_DEST_CLIENT_ID` and `BW_DEST_CLIENT_SECRET` in your `.env`.

## Step 3 — Configure .env

```bash
cp .env.example .env
# Edit .env with your values
```

Key decisions:

**`VW_WIPE_METHOD`**
- `cli` (default) — deletes items one by one via the `bw` CLI. Works with any
  Vaultwarden KDF setting (PBKDF2 or Argon2). Slower for vaults with hundreds of items.
- `api` — single HTTP call to `/api/ciphers/purge`. Near-instant regardless of vault size.
  Requires your Vaultwarden to use PBKDF2 KDF (the default). If you have switched to
  Argon2 in Vaultwarden settings, use `cli` instead.

**`TEMP_DIR`**
Set this to a tmpfs path so vault data is never written to persistent storage.
`/dev/shm` is tmpfs on most Linux systems. The directory is wiped automatically
at the end of every run (success or failure).

**`BACKUP_ENABLED`**
Strongly recommended. Each run writes a GPG-encrypted copy of the source export to
`BACKUP_DIR` before touching the destination. Backups older than `BACKUP_RETENTION_DAYS`
are pruned automatically.

## Step 4 — Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

## Step 5 — Test with dry run

Before your first live sync, run with `--dry-run`. This authenticates to both vaults,
exports the source, creates a backup, and reports what it *would* restore — without
touching the destination.

```bash
python sync.py --dry-run
```

Expected output:
```
2026-06-10 12:00:00  INFO      --- DRY RUN — wipe and restore will be skipped ---
2026-06-10 12:00:02  INFO      Logging in to source (https://vault.bitwarden.com)…
2026-06-10 12:00:04  INFO      Logging in to destination (https://vault.example.com)…
2026-06-10 12:00:06  INFO      Exporting source vault…
2026-06-10 12:00:10  INFO      Exported 142 item(s), 3 attachment(s).
2026-06-10 12:00:11  INFO      Backup: /var/backups/bw-sync/vault-20260610-120010.json.gpg
2026-06-10 12:00:11  INFO      Dry run complete. Would wipe destination and restore 142 item(s), 3 attachment(s). No changes made.
```

## Step 6 — First live run

```bash
python sync.py
```

## Known limitations

- **Organisation items are not synced.** Only personal vault items are exported and
  restored. Items belonging to a Bitwarden/Vaultwarden organisation are skipped.
- **Attachment matching requires unique item names per folder.** If two items in the
  same folder share an identical name, attachment re-upload may target the wrong item.
  This is reported as a warning, not a failure.
- **`api` wipe method requires PBKDF2 KDF.** If your Vaultwarden account uses Argon2
  (set in Vaultwarden security settings), use `VW_WIPE_METHOD=cli` instead.
- **Two-factor authentication.** The script uses API key authentication which bypasses
  2FA. This is the intended Bitwarden mechanism for automated access.

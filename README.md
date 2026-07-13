# bitwarden-vaultwarden-sync

Sync your [Bitwarden.com](https://bitwarden.com) vault to a self-hosted
[Vaultwarden](https://github.com/dani-garcia/vaultwarden) instance — including
attachments — with encrypted backups and optional Telegram failure alerts.

---

> **Destructive operation warning**
>
> This tool performs a **complete wipe** of your Vaultwarden vault before restoring.
> A GPG-encrypted backup is created automatically before any changes are made, but
> **you are solely responsible for verifying the backup** before running in production.
>
> Always use `--dry-run` first to confirm credentials and vault size.

> This project is not affiliated with, endorsed by, or supported by
> [Bitwarden, Inc.](https://bitwarden.com) or the
> [Vaultwarden](https://github.com/dani-garcia/vaultwarden) project.

---

## Features

- Full vault export from Bitwarden.com (or any hosted Bitwarden-compatible server)
- Attachment download and re-upload, matched by item name + folder
- GPG-symmetric encrypted backup before each sync, with configurable retention
- Two wipe methods: `cli` (universal) or `api` (fast, single HTTP call)
- `--dry-run` mode to verify credentials and measure vault size without touching the destination
- Optional Telegram alert on failure
- Vault data (export + backup staging) lives in tmpfs (`/dev/shm`), wiped after every run
- Stable `bw` CLI device identity persisted on disk — see [Device identity](#device-identity) below
- No heavy dependencies: only `python-dotenv` and `requests`

## Requirements

- Python 3.9+
- [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`)
- GPG (if `BACKUP_ENABLED=true`)

## Quick start

```bash
git clone https://github.com/t-philip/bitwarden-vaultwarden-sync.git
cd bitwarden-vaultwarden-sync

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — see docs/setup.md for a full walkthrough

# Verify credentials and vault size — no changes made
python sync.py --dry-run

# Live sync
python sync.py
```

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and
fill in your values. The full reference is in the example file and in
[docs/setup.md](docs/setup.md).

| Variable | Required | Default | Description |
|---|---|---|---|
| `BW_SOURCE_URL` | | `https://vault.bitwarden.com` | Source server URL |
| `BW_SOURCE_EMAIL` | Yes | | Source account email |
| `BW_SOURCE_CLIENT_ID` | Yes | | Source API key client ID |
| `BW_SOURCE_CLIENT_SECRET` | Yes | | Source API key client secret |
| `BW_SOURCE_PASSWORD` | Yes | | Source master password |
| `BW_DEST_URL` | Yes | | Vaultwarden URL |
| `BW_DEST_EMAIL` | Yes | | Destination account email |
| `BW_DEST_CLIENT_ID` | Yes | | Destination API key client ID |
| `BW_DEST_CLIENT_SECRET` | Yes | | Destination API key client secret |
| `BW_DEST_PASSWORD` | Yes | | Destination master password |
| `VW_WIPE_METHOD` | | `cli` | `cli` or `api` (see below) |
| `BACKUP_ENABLED` | | `true` | Enable GPG backup before each sync |
| `BACKUP_DIR` | | `/var/backups/bw-sync` | Backup output directory |
| `BACKUP_GPG_PASSPHRASE` | If backup enabled | | Passphrase for GPG encryption |
| `BACKUP_RETENTION_DAYS` | | `7` | Days to retain old backups |
| `TELEGRAM_BOT_TOKEN` | | | Telegram bot token (alerts off if blank) |
| `TELEGRAM_CHAT_ID` | | | Telegram chat ID |
| `TEMP_DIR` | | `/dev/shm/bw-sync` | Temp directory for plaintext export/backup staging (use tmpfs) |
| `APPDATA_DIR` | | `/var/lib/bw-vw-sync` | Persistent on-disk directory for the `bw` CLI's device identity (see below) |
| `LOG_LEVEL` | | `INFO` | `DEBUG`, `INFO`, `WARNING` |

## Wipe methods

**`VW_WIPE_METHOD=cli`** (default)

Deletes every item in the destination vault one by one using the `bw` CLI. Works with
any KDF setting (PBKDF2 or Argon2). The right choice for most users.

**`VW_WIPE_METHOD=api`**

Issues a single `POST /api/ciphers/purge` request. Completes instantly regardless of
vault size. Requires your Vaultwarden account to use the PBKDF2 KDF (the Vaultwarden
default). If you have switched to Argon2, use `cli` instead.

## Device identity

Each run authenticates to both vaults via `bw login --apikey` under an isolated
`BITWARDENCLI_APPDATA_DIR` per vault (`APPDATA_DIR/src-appdata`,
`APPDATA_DIR/dst-appdata`). That directory is where the `bw` CLI persists its
device identifier — a random ID that Bitwarden.com uses to recognize a login
as coming from an already-known device rather than a new one.

`APPDATA_DIR` lives outside `TEMP_DIR` and is **not** wiped between runs, so
the device ID stays stable and Bitwarden.com stops sending a "new device
logged in" email on every scheduled sync. `logout()` runs at the end of every
sync (success or failure) and clears the account/session state from this
directory, so nothing vault-related persists in it between runs — only the
CLI's own device ID and last-configured server URL remain.

## Dry run

```bash
python sync.py --dry-run
```

Authenticates to both vaults, exports the source, writes an encrypted backup, and
reports what would be restored — without making any changes to the destination.

## Scheduling

See [docs/scheduling.md](docs/scheduling.md) for systemd timer and cron examples.

## Known limitations

- Organisation items are not synced (personal vault only)
- Attachment matching requires unique item names within each folder
- `api` wipe method requires PBKDF2 KDF on the destination

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

## Author

Built by [T. Philip](https://github.com/t-philip).  
Uses the [Bitwarden CLI](https://github.com/bitwarden/clients) under the hood.  
Tested against Vaultwarden 1.32+.

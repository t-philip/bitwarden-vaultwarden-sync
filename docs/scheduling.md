# Scheduling

## systemd timer (Linux — recommended)

Create two files:

**`/etc/systemd/system/bw-vw-sync.service`**
```ini
[Unit]
Description=Bitwarden to Vaultwarden sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=bwsync
WorkingDirectory=/opt/bitwarden-vaultwarden-sync
ExecStart=/opt/bitwarden-vaultwarden-sync/.venv/bin/python sync.py --env-file /etc/bw-vw-sync/.env
StandardOutput=journal
StandardError=journal
# tmpfs for vault data — adjust if your system uses a different path
PrivateTmp=yes
```

**`/etc/systemd/system/bw-vw-sync.timer`**
```ini
[Unit]
Description=Run Bitwarden → Vaultwarden sync daily

[Timer]
# Runs daily at 02:00 UTC — adjust to suit your schedule
OnCalendar=*-*-* 02:00:00 UTC
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
systemctl daemon-reload
systemctl enable --now bw-vw-sync.timer

# Check status
systemctl status bw-vw-sync.timer
journalctl -u bw-vw-sync.service -f
```

## cron (Linux / macOS)

```bash
crontab -e
```

Add:
```cron
# Bitwarden → Vaultwarden sync — daily at 02:00 UTC
0 2 * * * cd /opt/bitwarden-vaultwarden-sync && .venv/bin/python sync.py >> /var/log/bw-vw-sync.log 2>&1
```

## Security note

The `.env` file contains master passwords and API keys. Set restrictive permissions:

```bash
chmod 600 /etc/bw-vw-sync/.env
chown bwsync:bwsync /etc/bw-vw-sync/.env
```

If using a dedicated service user, ensure only that user can read the `.env` file.

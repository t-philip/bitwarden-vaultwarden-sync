import logging
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("bwsync")


class Notifier:
    def __init__(self, cfg: "Config"):
        self._token = cfg.telegram_bot_token
        self._chat_id = cfg.telegram_chat_id

    @property
    def _enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def send_failure(self, message: str) -> None:
        if not self._enabled:
            return
        self._send(f"*bitwarden-vaultwarden-sync failed*\n\n```\n{message}\n```")

    def send_success(self, items: int, attachments: int) -> None:
        if not self._enabled:
            return
        self._send(
            f"*bitwarden-vaultwarden-sync completed*\n"
            f"{items} item(s), {attachments} attachment(s) synced."
        )

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as exc:
            log.warning("Telegram notification failed: %s", exc)

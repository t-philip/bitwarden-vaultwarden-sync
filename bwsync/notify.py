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

    def send_dst_only_abort(self, dst_only: list) -> None:
        if not self._enabled:
            return
        lines = "\n".join(
            f"  • {name}" + (f" ({folder})" if folder else " (no folder)")
            for name, folder in dst_only
        )
        self._send(
            f"*bitwarden-vaultwarden-sync aborted*\n\n"
            f"{len(dst_only)} item(s) found in Vaultwarden that are not in Bitwarden.com.\n"
            f"Delete them manually from Vaultwarden, then re-run the sync.\n\n"
            f"```\n{lines}\n```"
        )

    def send_verify_failure(self, missing: list, extra: list) -> None:
        """Alert that the destination did not match the source after a restore.

        Distinct from send_failure: the sync ran to completion without raising, so
        without this the run would look successful while leaving the destination
        incomplete.
        """
        if not self._enabled:
            return

        def _fmt(pairs: list) -> str:
            return "\n".join(
                f"  • {name}" + (f" ({folder})" if folder else " (no folder)")
                for name, folder in pairs
            )

        sections = []
        if missing:
            sections.append(f"MISSING from Vaultwarden ({len(missing)}):\n{_fmt(missing)}")
        if extra:
            sections.append(f"UNEXPECTED in Vaultwarden ({len(extra)}):\n{_fmt(extra)}")

        self._send(
            "*bitwarden-vaultwarden-sync — restore verification FAILED*\n\n"
            "The wipe and restore completed, but the destination does not match "
            "the source.\n\n"
            "```\n" + "\n\n".join(sections) + "\n```"
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

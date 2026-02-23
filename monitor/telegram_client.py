"""
Telegram API client and messaging functions.
"""

from __future__ import annotations

import sys
import requests

from .models import Announcement, Config
from .utils import debug_print


class TelegramClient:
    """Simple Telegram client using HTTPS Bot API."""

    def __init__(self, bot_token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML", disable_web_page_preview: bool = False) -> None:
        """
        Send a Telegram message.

        Raises an exception if the send fails, so the caller knows to retry.
        """
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        try:
            resp = requests.post(url, data=payload, timeout=15)
            if not resp.ok:
                raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to send Telegram message: {exc}")


def send_public_announcement(telegram: TelegramClient, cfg: Config, ann: Announcement, target_url: str) -> None:
    """Send a formatted announcement message to the public channel."""
    lines = [
        "📢 <b>New College Announcement Detected</b>",
        "",
        f"{ann.text}",
        "",
        f"🔗 <a href=\"{target_url}\">College website</a>",
    ]
    if ann.pdf_url:
        lines.append(f"📄 <a href=\"{ann.pdf_url}\">PDF link</a>")
    text = "\n".join(lines)
    telegram.send_message(cfg.telegram_channel_id, text, parse_mode="HTML", disable_web_page_preview=False)


def send_private_error(telegram: TelegramClient, cfg: Config, message: str) -> bool:
    """
    Send an error alert to the owner only.
    
    Returns True if sent successfully, False if it failed.
    """
    text = f"⚠️ <b>Monitoring error</b>\n\n<code>{message}</code>"
    try:
        telegram.send_message(cfg.telegram_owner_chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
        return True
    except Exception as exc:
        print(f"[telegram] Failed to send error alert: {exc}", file=sys.stderr)
        return False

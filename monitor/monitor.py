"""
Main monitoring script.

Responsibilities:
- Load configuration from environment variables.
- Fetch and parse the target webpage.
- Detect relevant announcements using fuzzy matching.
- Update JSON state file (used by the static status page).
- Send Telegram alerts (public announcement + private errors).

This module is designed to be:
- Runnable locally for testing.
- Runnable in GitHub Actions on a daily schedule.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def _format_dt(dt: datetime) -> str:
    """Format a datetime as ISO string."""
    return dt.strftime(ISO_FORMAT)


def _parse_dt(raw: str) -> Optional[datetime]:
    """Parse ISO datetime string; return None on failure."""
    try:
        return datetime.strptime(raw, ISO_FORMAT)
    except Exception:
        return None


@dataclass
class Announcement:
    """Represents a detected announcement."""

    id: str
    text: str
    pdf_url: Optional[str]
    first_detected: str  # ISO string


@dataclass
class MonitorState:
    """
    JSON-serialisable state consumed by the static webpage.

    This file is the only shared contract between the monitor script and the
    GitHub Pages status site.
    """

    monitoring_enabled: bool = True
    last_run_time: Optional[str] = None
    last_run_status: Optional[str] = None  # "success" | "failure"
    last_error_message: Optional[str] = None
    last_announcement: Optional[Announcement] = None
    error_signature: Optional[str] = None
    error_last_alert_time: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        data: Dict[str, Any] = asdict(self)
        if self.last_announcement:
            data["last_announcement"] = asdict(self.last_announcement)
        return data

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "MonitorState":
        ann_raw = raw.get("last_announcement")
        announcement: Optional[Announcement] = None
        if isinstance(ann_raw, dict):
            announcement = Announcement(
                id=str(ann_raw.get("id", "")),
                text=str(ann_raw.get("text", "")),
                pdf_url=ann_raw.get("pdf_url"),
                first_detected=str(ann_raw.get("first_detected", "")),
            )

        return cls(
            monitoring_enabled=bool(raw.get("monitoring_enabled", True)),
            last_run_time=raw.get("last_run_time"),
            last_run_status=raw.get("last_run_status"),
            last_error_message=raw.get("last_error_message"),
            last_announcement=announcement,
            error_signature=raw.get("error_signature"),
            error_last_alert_time=raw.get("error_last_alert_time"),
        )


def load_state(path: str) -> MonitorState:
    """
    Load state from JSON file.

    If the file is missing or invalid, return a default state so that the
    monitor can still proceed and the webpage can handle missing data.
    """
    if not os.path.exists(path):
        return MonitorState()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return MonitorState()
        return MonitorState.from_json(raw)
    except Exception:
        # Corrupt or invalid state; start from a clean slate but do not crash.
        return MonitorState()


def save_state(path: str, state: MonitorState) -> None:
    """Persist state atomically to JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state.to_json(), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


@dataclass
class Config:
    """
    Configuration loaded from environment variables.

    All sensitive values (bot token, chat IDs) are expected to be provided via
    environment variables or GitHub Secrets, never committed to the repo.
    """

    target_url: str
    match_keywords: str
    similarity_threshold: float
    telegram_bot_token: str
    telegram_channel_id: str
    telegram_owner_chat_id: str
    state_file: str
    monitoring_enabled: bool
    error_throttle_minutes: int = 60


def load_config() -> Config:
    """Read configuration from environment variables with sensible defaults."""
    try:
        similarity_threshold = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))
    except ValueError:
        similarity_threshold = 0.6

    state_file = os.getenv("STATE_FILE", os.path.join(os.path.dirname(__file__), "..", "state", "state.json"))
    state_file = os.path.abspath(state_file)

    monitoring_enabled_env = os.getenv("MONITORING_ENABLED", "true").lower()
    monitoring_enabled = monitoring_enabled_env not in {"0", "false", "no", "off"}

    error_throttle_minutes_env = os.getenv("ERROR_THROTTLE_MINUTES", "60")
    try:
        error_throttle_minutes = int(error_throttle_minutes_env)
    except ValueError:
        error_throttle_minutes = 60

    cfg = Config(
        target_url=os.environ["TARGET_URL"],
        match_keywords=os.environ["MATCH_KEYWORDS"],
        similarity_threshold=similarity_threshold,
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_channel_id=os.environ["TELEGRAM_CHANNEL_ID"],
        telegram_owner_chat_id=os.environ["TELEGRAM_OWNER_CHAT_ID"],
        state_file=state_file,
        monitoring_enabled=monitoring_enabled,
        error_throttle_minutes=error_throttle_minutes,
    )
    return cfg


class TelegramClient:
    """Simple Telegram client using HTTPS Bot API."""

    def __init__(self, bot_token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML", disable_web_page_preview: bool = False) -> None:
        """
        Send a Telegram message.

        Errors are logged to stderr but do not crash the monitor.
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
                print(f"[telegram] Failed to send message: {resp.status_code} {resp.text}", file=sys.stderr)
        except Exception as exc:
            print(f"[telegram] Exception while sending message: {exc}", file=sys.stderr)


def fetch_page(url: str) -> str:
    """Fetch target page and return HTML text."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_announcements(html: str) -> list[Dict[str, Any]]:
    """
    Extract candidate announcement blocks from the HTML.

    This implementation is intentionally conservative and generic so it can be
    adapted to different college websites later by adjusting the parsing logic.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Heuristic: look for list items and table rows as announcements.
    candidates: list[Dict[str, Any]] = []

    for li in soup.find_all("li"):
        text = " ".join(li.get_text(strip=True).split())
        if not text:
            continue
        link = li.find("a")
        pdf_url = None
        if link and link.get("href"):
            href = link["href"].strip()
            if href.lower().endswith(".pdf"):
                pdf_url = href
        candidates.append({"text": text, "pdf_url": pdf_url})

    # Fallback: also inspect anchor tags if list-based parsing yields nothing.
    if not candidates:
        for a in soup.find_all("a"):
            text = " ".join(a.get_text(strip=True).split())
            if not text:
                continue
            href = a.get("href", "").strip()
            pdf_url = href if href.lower().endswith(".pdf") else None
            candidates.append({"text": text, "pdf_url": pdf_url})

    return candidates


def fuzzy_matches(text: str, keywords: str, threshold: float) -> bool:
    """
    Check if any keyword fuzzy-matches the given text above the threshold.

    Keywords are comma-separated; we perform case-insensitive similarity using
    difflib.SequenceMatcher.
    """
    text_norm = text.lower()
    for raw_kw in keywords.split(","):
        kw = raw_kw.strip().lower()
        if not kw:
            continue
        ratio = SequenceMatcher(None, text_norm, kw).ratio()
        if ratio >= threshold:
            return True
    return False


def detect_announcement(candidates: list[Dict[str, Any]], cfg: Config) -> Optional[Announcement]:
    """
    Return the first candidate that matches the fuzzy keyword criteria.

    The 'id' for de-duplication is based on the text (and PDF URL if present).
    """
    now_iso = _format_dt(_now())
    for cand in candidates:
        text = cand.get("text") or ""
        pdf_url = cand.get("pdf_url")
        if not text:
            continue
        if fuzzy_matches(text, cfg.match_keywords, cfg.similarity_threshold):
            ann_id = text
            if pdf_url:
                ann_id = f"{text}|{pdf_url}"
            return Announcement(
                id=ann_id,
                text=text,
                pdf_url=pdf_url,
                first_detected=now_iso,
            )
    return None


def should_send_error_alert(state: MonitorState, signature: str, cfg: Config) -> bool:
    """
    Decide whether to send a new error alert to the owner.

    We throttle on both time and signature to avoid spamming on repeated failures.
    """
    if state.error_signature != signature or not state.error_last_alert_time:
        return True

    last_time = _parse_dt(state.error_last_alert_time)
    if not last_time:
        return True

    delta = _now() - last_time
    return delta >= timedelta(minutes=cfg.error_throttle_minutes)


def update_for_error(state: MonitorState, error_message: str, cfg: Config) -> MonitorState:
    """Update state for a failure and return it."""
    state.last_run_time = _format_dt(_now())
    state.last_run_status = "failure"
    state.last_error_message = error_message
    state.monitoring_enabled = cfg.monitoring_enabled
    return state


def update_for_success(state: MonitorState, announcement: Optional[Announcement], cfg: Config) -> MonitorState:
    """Update state for a successful run and return it."""
    state.last_run_time = _format_dt(_now())
    state.last_run_status = "success"
    state.last_error_message = None
    state.error_signature = None
    state.error_last_alert_time = None
    state.monitoring_enabled = cfg.monitoring_enabled

    if announcement:
        if state.last_announcement and state.last_announcement.id == announcement.id:
            # Preserve original first_detected date.
            announcement.first_detected = state.last_announcement.first_detected
        state.last_announcement = announcement

    return state


def send_public_announcement(telegram: TelegramClient, cfg: Config, ann: Announcement, target_url: str) -> None:
    """Send a formatted announcement message to the public channel."""
    lines = [
        "📢 <b>New College Announcement Detected</b>",
        "",
        f"{ann.text}",
        "",
        f"🔗 <a href=\"{target_url}\">Source page</a>",
    ]
    if ann.pdf_url:
        lines.append(f"📄 <a href=\"{ann.pdf_url}\">PDF link</a>")
    text = "\n".join(lines)
    telegram.send_message(cfg.telegram_channel_id, text, parse_mode="HTML", disable_web_page_preview=False)


def send_private_error(telegram: TelegramClient, cfg: Config, message: str) -> None:
    """Send an error alert to the owner only."""
    text = f"⚠️ <b>Monitoring error</b>\n\n<code>{message}</code>"
    telegram.send_message(cfg.telegram_owner_chat_id, text, parse_mode="HTML", disable_web_page_preview=True)


def run_monitor() -> int:
    """
    Execute one monitoring run.

    Returns an exit code suitable for use in CI systems.
    """
    try:
        cfg = load_config()
    except KeyError as exc:
        print(f"[monitor] Missing required environment variable: {exc}", file=sys.stderr)
        return 1

    state = load_state(cfg.state_file)
    telegram = TelegramClient(cfg.telegram_bot_token)

    if not cfg.monitoring_enabled:
        # Still update state so the webpage reflects OFF status.
        state.monitoring_enabled = False
        state.last_run_time = _format_dt(_now())
        save_state(cfg.state_file, state)
        print("[monitor] Monitoring disabled via configuration.")
        return 0

    try:
        html = fetch_page(cfg.target_url)
        candidates = extract_announcements(html)
        announcement = detect_announcement(candidates, cfg)

        is_new = False
        if announcement:
            if not state.last_announcement or state.last_announcement.id != announcement.id:
                is_new = True

        # Update state and send public alert if needed.
        state = update_for_success(state, announcement, cfg)
        save_state(cfg.state_file, state)

        if announcement and is_new:
            send_public_announcement(telegram, cfg, announcement, cfg.target_url)

        print("[monitor] Run completed successfully.")
        return 0

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        print(f"[monitor] Error during run: {error_message}", file=sys.stderr)
        signature = type(exc).__name__
        state = update_for_error(state, error_message, cfg)

        if should_send_error_alert(state, signature, cfg):
            send_private_error(telegram, cfg, error_message)
            state.error_signature = signature
            state.error_last_alert_time = _format_dt(_now())

        save_state(cfg.state_file, state)
        return 1


def main() -> None:
    """CLI entrypoint."""
    sys.exit(run_monitor())


if __name__ == "__main__":
    main()


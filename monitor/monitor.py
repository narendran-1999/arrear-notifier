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

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

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
from dotenv import load_dotenv
import urllib3


# ---------------------------------------------------------------------------
# Core, non-secret configuration
# ---------------------------------------------------------------------------

# College website URL to monitor for announcements.
DEFAULT_TARGET_URL = "https://www.psgtech.edu/"

# Comma-separated keywords used for fuzzy matching against announcement text.
DEFAULT_MATCH_KEYWORDS = "time limit exceeded, reappearance"

# Similarity threshold in the range [0, 1]. Higher = stricter match.
DEFAULT_SIMILARITY_THRESHOLD = 0.8

# Minimum minutes between repeated error alerts with the same signature.
DEFAULT_ERROR_THROTTLE_MINUTES = 60

# Note: Monitoring on/off is controlled via MONITORING_ENABLED environment
# variable (set via GitHub Secrets). There is no constant here to avoid confusion.

# ISO format for datetime strings
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


# ---------------------------------------------------------------------------
# Environment and SSL setup
# ---------------------------------------------------------------------------

# Suppress SSL warnings for sites with weak DH keys (common on older college websites).
# Browsers accept these, but Python's SSL library is stricter.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env file (for local testing).
# This looks for monitor/.env relative to this file's location.
# In production (GitHub Actions), environment variables are set directly.
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)

# Enable verbose logs by setting DEBUG=1 (or true/yes/on).
_DEBUG_ENV = os.getenv("DEBUG", "").strip().lower()
DEBUG = _DEBUG_ENV in {"1", "true", "yes", "on"}


def _debug(message: str) -> None:
    """Print debug messages only when DEBUG is enabled."""
    if DEBUG:
        print(message)


# ---------------------------------------------------------------------------
# Functions to handle datetime strings
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Data classes - Announcement & MonitorState
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Use JSON to load & save state
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Configuration for one run of the monitor
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """
    Configuration for one run of the monitor.

    Only Telegram-related values are read from environment variables / GitHub
    Secrets. All other tunables are module-level constants above so they are
    visible in version control and easy to tweak.
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
    """
    Build a Config object using module-level defaults for non-secret values
    and environment variables only for Telegram credentials.

    STATE_FILE and MONITORING_ENABLED can be overridden via environment if needed
    (useful for toggling monitoring via GitHub Secrets without code changes).
    """
    # Allow overriding the state file path from CI or local runs if needed.
    state_file_default = os.path.join(os.path.dirname(__file__), "..", "state", "state.json")
    state_file = os.getenv("STATE_FILE", state_file_default)
    state_file = os.path.abspath(state_file)

    # Monitoring on/off is controlled exclusively via MONITORING_ENABLED environment
    # variable. Defaults to True if not set (for local testing convenience), but in
    # production this should always be set via GitHub Secrets.
    monitoring_enabled_env = os.getenv("MONITORING_ENABLED")
    if monitoring_enabled_env is not None:
        monitoring_enabled = monitoring_enabled_env.lower() not in {"0", "false", "no", "off"}
    else:
        # Default to enabled if not specified (for local testing).
        monitoring_enabled = True

    cfg = Config(
        target_url=DEFAULT_TARGET_URL,
        match_keywords=DEFAULT_MATCH_KEYWORDS,
        similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_channel_id=os.environ["TELEGRAM_CHANNEL_ID"],
        telegram_owner_chat_id=os.environ["TELEGRAM_OWNER_CHAT_ID"],
        state_file=state_file,
        monitoring_enabled=monitoring_enabled,
        error_throttle_minutes=DEFAULT_ERROR_THROTTLE_MINUTES,
    )
    return cfg


# ---------------------------------------------------------------------------
# Telegram client class
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fetch & parse the target webpage
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> str:
    """
    Fetch target page and return HTML text.
    
    Uses a custom SSL context with relaxed security level to handle websites with
    weak SSL configurations (e.g., small Diffie-Hellman keys) that browsers accept
    but Python's SSL library rejects by default. This is common on older college websites.
    """
    import ssl
    from requests.adapters import HTTPAdapter
    from urllib3.poolmanager import PoolManager
    
    # Create SSL context with relaxed security level for weak DH keys
    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    # Use a custom HTTP adapter with the relaxed SSL context
    class CustomHTTPAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = ssl_context
            return super().init_poolmanager(*args, **kwargs)
    
    session = requests.Session()
    session.mount("https://", CustomHTTPAdapter())
    resp = session.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    return resp.text


def extract_announcements(html: str) -> list[Dict[str, Any]]:
    """
    Extract candidate announcement blocks from the HTML.

    Primary strategy (college-specific):
    - Look for <a> elements with class "active" that are nested anywhere inside
      a <div> with class "owl-item".
    - Ignore any "owl-item" elements that also have class "cloned" to avoid
      duplicates created by carousel libraries.

    Fallback strategy:
    - If nothing is found using the structure above, fall back to a more
      generic heuristic based on <li> and <a> tags so the script still works
      even if the page structure changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[Dict[str, Any]] = []

    def add_candidate(text: str, pdf_url: Optional[str]) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        candidates.append({"text": cleaned, "pdf_url": pdf_url})

    # ------------------------------------------------------------------
    # Primary (college-specific): notifications ticker
    # All notifications are inside a div with BOTH classes:
    #   tg-ticker owl-carousel
    # ------------------------------------------------------------------
    ticker = soup.select_one("div.tg-ticker.owl-carousel")
    if ticker:
        _debug("[extract] Found ticker container: div.tg-ticker.owl-carousel")

        # PSG-style ticker: notifications are direct children (often <section>).
        # We parse direct children first to avoid accidentally grabbing unrelated
        # nested markup.
        direct_items = ticker.find_all(recursive=False)
        _debug(f"[extract] Ticker direct children found: {len(direct_items)}")
        for item in direct_items:
            classes = item.get("class", [])
            if isinstance(classes, list) and "cloned" in classes:
                continue

            text = item.get_text(strip=True)
            pdf_url = None
            for link in item.select("a"):
                href = (link.get("href") or "").strip()
                if href.lower().endswith(".pdf"):
                    pdf_url = href
                    break
            add_candidate(text, pdf_url)

        # Generic ticker rule (if direct-children parsing yields nothing):
        # Look for anchors with class 'active' anywhere inside the ticker and
        # ignore duplicates that are part of a 'cloned' element.
        if not candidates:
            anchors = ticker.select("a.active")
            _debug(f"[extract] Ticker active anchors found: {len(anchors)}")
            for a_tag in anchors:
                cloned = False
                for parent in a_tag.parents:
                    if not hasattr(parent, "get"):
                        continue
                    classes = parent.get("class", [])
                    if isinstance(classes, list) and "cloned" in classes:
                        cloned = True
                        break
                if cloned:
                    continue

                text = a_tag.get_text(strip=True)
                href = (a_tag.get("href") or "").strip()
                pdf_url = href if href.lower().endswith(".pdf") else None
                add_candidate(text, pdf_url)

        # Final ticker fallback: common OwlCarousel item wrappers.
        if not candidates:
            items = ticker.select(".owl-item, .item")
            _debug(f"[extract] Ticker item blocks found: {len(items)}")
            for item in items:
                classes = item.get("class", [])
                if isinstance(classes, list) and "cloned" in classes:
                    continue
                text = item.get_text(strip=True)
                pdf_url = None
                for link in item.select("a"):
                    href = (link.get("href") or "").strip()
                    if href.lower().endswith(".pdf"):
                        pdf_url = href
                        break
                add_candidate(text, pdf_url)

    # ------------------------------------------------------------------
    # Fallback: scan other owl-carousel containers (best-effort resilience)
    # ------------------------------------------------------------------
    if not candidates:
        _debug("[extract] No ticker candidates; scanning other owl-carousel containers")
        for carousel in soup.select("div.owl-carousel"):
            for item in carousel.select("div.owl-item, div.item"):
                classes = item.get("class", [])
                if isinstance(classes, list) and "cloned" in classes:
                    continue
                text = item.get_text(strip=True)
                pdf_url = None
                for link in item.select("a"):
                    href = (link.get("href") or "").strip()
                    if href.lower().endswith(".pdf"):
                        pdf_url = href
                        break
                add_candidate(text, pdf_url)

    # ------------------------------------------------------------------
    # Last resort: whole-page scan (can include navigation items)
    # ------------------------------------------------------------------
    if not candidates:
        _debug("[extract] No carousel candidates; falling back to generic scanning")
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if not text:
                continue
            link = li.find("a")
            pdf_url = None
            if link and link.get("href"):
                href = (link.get("href") or "").strip()
                if href.lower().endswith(".pdf"):
                    pdf_url = href
            add_candidate(text, pdf_url)

    if not candidates:
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            if not text:
                continue
            href = (a.get("href") or "").strip()
            pdf_url = href if href.lower().endswith(".pdf") else None
            add_candidate(text, pdf_url)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[Dict[str, Any]] = []
    for cand in candidates:
        key = f"{(cand.get('text') or '').lower()}|{cand.get('pdf_url') or ''}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cand)
    return deduped


def fuzzy_matches(text: str, keywords: str, threshold: float) -> bool:
    """
    Check if any keyword fuzzy-matches the given text above the threshold.

    Keywords are comma-separated. We perform case-insensitive matching using:
    1. Substring check: if keyword appears anywhere in the text, it's a match
    2. Fuzzy similarity: if substring check fails, use SequenceMatcher ratio

    This handles both exact substring matches (e.g., "reappearance" in a longer
    announcement text) and fuzzy matches for typos/variations.
    """
    text_norm = text.lower()
    for raw_kw in keywords.split(","):
        kw = raw_kw.strip().lower()
        if not kw:
            continue
        
        # First check: if keyword appears as substring, it's definitely a match
        if kw in text_norm:
            return True
        
        # Second check: fuzzy similarity for partial matches and typos
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
    _debug(f"[detect] Checking {len(candidates)} candidates for {cfg.match_keywords!r}")
    for cand in candidates:
        text = cand.get("text") or ""
        pdf_url = cand.get("pdf_url")
        if not text:
            continue
        if fuzzy_matches(text, cfg.match_keywords, cfg.similarity_threshold):
            ann_id = text
            if pdf_url:
                ann_id = f"{text}|{pdf_url}"
            _debug(f"[detect] Match: {text[:120]!r}")
            return Announcement(
                id=ann_id,
                text=text,
                pdf_url=pdf_url,
                first_detected=now_iso,
            )
    return None


# ---------------------------------------------------------------------------
# Decide whether to send an error alert
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Update state for a failure or success
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Send Telegram notifications
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Run monitoring
# ---------------------------------------------------------------------------

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
        print(f"[monitor] Found {len(candidates)} candidate announcement(s)")
        
        announcement = detect_announcement(candidates, cfg)

        is_new = False
        if announcement:
            if not state.last_announcement or state.last_announcement.id != announcement.id:
                is_new = True
        else:
            _debug("[monitor] No matching announcement found")

        # Update state and send public alert if needed.
        state = update_for_success(state, announcement, cfg)
        save_state(cfg.state_file, state)

        if announcement and is_new:
            send_public_announcement(telegram, cfg, announcement, cfg.target_url)
        elif announcement and not is_new:
            _debug("[monitor] Skipping alert (already notified)")

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
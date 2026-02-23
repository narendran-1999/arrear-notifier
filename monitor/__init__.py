"""
Monitoring package for college announcement checks.

Main modules:
- monitor_core: Core monitoring logic (run_monitor)
- models: Data classes (Announcement, MonitorState, Config)
- state: State file operations
- config: Configuration loading
- scraper: Web scraping and announcement detection
- telegram_client: Telegram API integration
- utils: Utilities and constants
"""

from .monitor_core import run_monitor
from .models import Announcement, MonitorState, Config
from .state import load_state, save_state
from .config import load_config
from .scraper import fetch_page, extract_announcements, detect_announcements
from .telegram_client import TelegramClient, send_public_announcement, send_private_error

__all__ = [
    "run_monitor",
    "Announcement",
    "MonitorState",
    "Config",
    "load_state",
    "save_state",
    "load_config",
    "fetch_page",
    "extract_announcements",
    "detect_announcements",
    "TelegramClient",
    "send_public_announcement",
    "send_private_error",
]

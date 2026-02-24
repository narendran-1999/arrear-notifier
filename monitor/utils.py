"""
Utility functions and constants for the monitoring system.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Core, non-secret configuration
# ---------------------------------------------------------------------------

# College website URL to monitor for announcements.
DEFAULT_TARGET_URL = "https://www.psgtech.edu"

# Comma-separated keywords used for matching against announcement text.
DEFAULT_MATCH_KEYWORDS = "time limit exceeded"

# Similarity threshold (for fuzzy matching) in the range [0, 1]. Higher = stricter match.
DEFAULT_SIMILARITY_THRESHOLD = 0.8

# Minimum minutes between repeated error alerts with the same signature.
DEFAULT_ERROR_THROTTLE_MINUTES = 60

# Maximum history sizes for announcements and errors stored in the state file.
HISTORY_MAX_ANNOUNCEMENTS = 10
HISTORY_MAX_ERRORS = 50

# ISO format for datetime strings
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


# ---------------------------------------------------------------------------
# Environment (if local) and Debugging
# ---------------------------------------------------------------------------

# Load environment variables from .env file (for local testing).
# This looks for monitor/.env relative to this file's location.
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)

# Enable verbose logs by setting DEBUG=1 (or true/yes/on).
_DEBUG_ENV = os.getenv("DEBUG", "").strip().lower()
DEBUG = _DEBUG_ENV in {"1", "true", "yes", "on"}


def debug_print(message: str) -> None:
    """Print debug messages only when DEBUG is enabled."""
    if DEBUG:
        print(message)


# ---------------------------------------------------------------------------
# Functions to handle datetime strings
# ---------------------------------------------------------------------------

def now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def format_dt(dt: datetime) -> str:
    """Format a datetime as ISO string."""
    return dt.strftime(ISO_FORMAT)


def parse_dt(raw: str) -> datetime | None:
    """Parse ISO datetime string; return None on failure."""
    try:
        return datetime.strptime(raw, ISO_FORMAT)
    except Exception:
        return None

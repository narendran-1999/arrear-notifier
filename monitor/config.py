"""
Configuration loading from environment variables.
"""

from __future__ import annotations

import os

from .models import Config
from .utils import (
    DEFAULT_TARGET_URL,
    DEFAULT_MATCH_KEYWORDS,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_ERROR_THROTTLE_MINUTES,
)


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

"""
State file operations and state update logic.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Optional

from .models import Announcement, MonitorState, Config
from .utils import now, format_dt, parse_dt, HISTORY_MAX_ANNOUNCEMENTS, HISTORY_MAX_ERRORS


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


def should_send_error_alert(state: MonitorState, signature: str, cfg: Config) -> bool:
    """
    Decide whether to send a new error alert to the owner.

    We throttle on both time and signature to avoid spamming on repeated failures.
    """
    if state.error_signature != signature or not state.error_last_alert_time:
        return True

    last_time = parse_dt(state.error_last_alert_time)
    if not last_time:
        return True

    delta = now() - last_time
    return delta >= timedelta(minutes=cfg.error_throttle_minutes)


def update_for_error(state: MonitorState, error_message: str, cfg: Config) -> MonitorState:
    """Update state for a failure and return it."""
    now_str = format_dt(now())
    state.last_run_time = now_str
    state.last_run_status = "failure"
    state.monitoring_enabled = cfg.monitoring_enabled
    
    # Add to error history (prepend)
    new_error = {"timestamp": now_str, "message": error_message}
    state.error_history.insert(0, new_error)
    # Keep last N errors
    state.error_history = state.error_history[:HISTORY_MAX_ERRORS]
    
    return state


def update_for_success(state: MonitorState, announcement: Optional[Announcement], cfg: Config) -> MonitorState:
    """Update state for a successful run and return it."""
    state.last_run_time = format_dt(now())
    state.last_run_status = "success"
    state.error_signature = None
    state.error_last_alert_time = None
    state.monitoring_enabled = cfg.monitoring_enabled

    if announcement:
        # Check if this announcement ID already exists in history
        existing_index = next((i for i, a in enumerate(state.announcement_history) if a.id == announcement.id), -1)
        
        if existing_index != -1:
            # Update existing entry (preserve original detection time)
            original_detection = state.announcement_history[existing_index].first_detected
            announcement.first_detected = original_detection
            # Move to top to show it's still active/relevant
            state.announcement_history.pop(existing_index)
            state.announcement_history.insert(0, announcement)
        else:
            # new announcement
            state.announcement_history.insert(0, announcement)
        
        # Keep last N announcements
        state.announcement_history = state.announcement_history[:HISTORY_MAX_ANNOUNCEMENTS]

    return state

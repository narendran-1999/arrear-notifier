"""
Core monitoring logic.
"""

from __future__ import annotations

import sys

from .config import load_config
from .models import Config
from .state import load_state, save_state, update_for_error, update_for_success, should_send_error_alert
from .scraper import fetch_page, extract_announcements, detect_announcements
from .telegram_client import TelegramClient, send_public_announcement, send_private_error
from .utils import debug_print, format_dt, now


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
        state.last_run_time = format_dt(now())
        print("[monitor] Monitoring disabled via configuration.")
        try:
            save_state(cfg.state_file, state)
        except Exception as exc:
            print(f"[monitor] Failed to save state: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        html = fetch_page(cfg.target_url)
        candidates = extract_announcements(html)
        print(f"[monitor] Found {len(candidates)} candidate announcement(s)")
        
        announcements = detect_announcements(candidates, cfg)

        if not announcements:
            debug_print("[monitor] No matching announcement found")
            # Still update state with successful run status even if no announcements found
            state = update_for_success(state, None, cfg)
            try:
                save_state(cfg.state_file, state)
            except Exception as exc:
                print(f"[monitor] Failed to save state: {type(exc).__name__}: {exc}", file=sys.stderr)
                raise
        else:
            for announcement in announcements:
                is_new = True
                # Check if recently detected
                for past_ann in state.announcement_history:
                    if past_ann.id == announcement.id:
                        is_new = False
                        break

                # Send alert FIRST (if needed), before updating state
                # If send fails, exception propagates without saving state
                if is_new:
                    send_public_announcement(telegram, cfg, announcement, cfg.target_url)
                else:
                    debug_print("[monitor] Skipping alert (already notified)")
                
                # Only update and save state after successful send
                state = update_for_success(state, announcement, cfg)
                try:
                    save_state(cfg.state_file, state)
                except Exception as exc:
                    print(f"[monitor] Failed to save state: {type(exc).__name__}: {exc}", file=sys.stderr)
                    raise

        print("[monitor] Run completed successfully.")
        return 0

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        print(f"[monitor] Error during run: {error_message}", file=sys.stderr)
        signature = type(exc).__name__
        state = update_for_error(state, error_message, cfg)

        if should_send_error_alert(state, signature, cfg):
            if send_private_error(telegram, cfg, error_message):
                # Only mark as sent if actually succeeded
                state.error_signature = signature
                state.error_last_alert_time = format_dt(now())
            else:
                # Send failed; don't update alert state so we'll try again next time
                pass

        try:
            save_state(cfg.state_file, state)
        except Exception as save_exc:
            print(f"[monitor] Failed to save state: {type(save_exc).__name__}: {save_exc}", file=sys.stderr)

        return 1

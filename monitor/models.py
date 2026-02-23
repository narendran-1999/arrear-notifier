"""
Data models for the monitoring system.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional


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
    announcement_history: list[Announcement] = field(default_factory=list)
    error_history: list[Dict[str, str]] = field(default_factory=list)
    error_signature: Optional[str] = None
    error_last_alert_time: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        data: Dict[str, Any] = asdict(self)
        data["announcement_history"] = [asdict(a) for a in self.announcement_history]
        return data

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "MonitorState":
        # Migrate legacy single announcement to history if needed
        history = []
        if "announcement_history" in raw:
            for item in raw["announcement_history"]:
                history.append(Announcement(
                    id=str(item.get("id", "")),
                    text=str(item.get("text", "")),
                    pdf_url=item.get("pdf_url"),
                    first_detected=str(item.get("first_detected", "")),
                ))
        elif "last_announcement" in raw and raw["last_announcement"]:
            # Migration path for existing state file
            old_ann = raw["last_announcement"]
            history.append(Announcement(
                id=str(old_ann.get("id", "")),
                text=str(old_ann.get("text", "")),
                pdf_url=old_ann.get("pdf_url"),
                first_detected=str(old_ann.get("first_detected", "")),
            ))

        # Migrate legacy single error to history if needed
        errors = raw.get("error_history", [])
        if not errors and raw.get("last_error_message"):
            errors.append({
                "timestamp": raw.get("last_run_time", ""),
                "message": raw.get("last_error_message")
            })

        return cls(
            monitoring_enabled=bool(raw.get("monitoring_enabled", True)),
            last_run_time=raw.get("last_run_time"),
            last_run_status=raw.get("last_run_status"),
            announcement_history=history,
            error_history=errors,
            error_signature=raw.get("error_signature"),
            error_last_alert_time=raw.get("error_last_alert_time"),
        )


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

# Arrear Notifier

## Daily Execution

- **GITHUB ACTIONS & YML:**
    Avoid touching workflow YML files or GitHub Actions if you do not understand the scheduler; changes may affect job timing.
- **Scheduled runs (observed):**
    - Scheduled window ~09:00–12:00 IST
    - Observed run time ~10:20 AM IST
    - Observed execution delays from cron time: min. 1h 19m, max. 2h 7m.

---

## Project Overview

This small project detect notifications on a college website to send Telegram alerts, and records state in `state/state.json` to avoid duplicate notifications.

## Files

- `monitor/monitor.py` — main monitoring logic
- `state/state.json` — current known state (read & updated by the monitor)
- `index.html` — bot monitoring page
- `page-assets/` — frontend assets for bot monitoring page

## Quick Start

1. Create and activate a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables (example):

```bash
export TELEGRAM_BOT_TOKEN="<your-bot-token>"
export TELEGRAM_CHANNEL_ID="<your-channel-id>"
export TELEGRAM_OWNER_CHAT_ID="<your-chat-id>"
```

## Running Locally

Run the monitor script manually for testing:

```bash
python -m monitor.monitor
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

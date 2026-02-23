# Arrear Notifier

A simple Python project that checks a college website for specific announcements and sends alerts to Telegram.
It saves state in `state/state.json` to avoid duplicate notifications and to track errors.

---

## Project Structure (Modular Design)

The project is split into small, focused modules.

### `utils.py`

* Constants (URLs, keywords, limits)
* Date and time helpers (`now()`, `format_dt()`, `parse_dt()`)
* Debug logging
* Environment setup for local testing

### `models.py`

* `Announcement` — represents a detected announcement
* `MonitorState` — represents saved JSON state
* `Config` — runtime configuration model

### `config.py`

* `load_config()` — loads configuration from environment variables

### `state.py`

* `load_state()` / `save_state()` — read/write `state.json`
* `update_for_error()` / `update_for_success()` — update state correctly
* `should_send_error_alert()` — prevents repeated error spam

### `scraper.py`

* `fetch_page()` — fetch website with retries
* `extract_announcements()` — parse HTML
* `fuzzy_matches()` — substring matching + fuzzy matching fallback (handles typos/partial matches)
* `detect_announcements()` — filter relevant announcements

### `telegram_client.py`

* `TelegramClient` — Telegram API wrapper
* `send_public_announcement()` — send message to channel
* `send_private_error()` — send error to owner

### `monitor_core.py`

* `run_monitor()` — main orchestration logic
* Flow: fetch → extract → detect → send → save
* Handles errors and updates state safely

### `monitor.py` (CLI Entry Point)

Run the monitor:

```bash
python -m monitor.monitor
```

---

## Dependency Flow

```
utils
models
   ↓
config
state
scraper
telegram_client
   ↓
monitor_core
   ↓
monitor.py (CLI)
```

---

## Setup

### 1. Create virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export TELEGRAM_BOT_TOKEN="<your-bot-token>"
export TELEGRAM_CHANNEL_ID="<your-channel-id>"
export TELEGRAM_OWNER_CHAT_ID="<your-chat-id>"
```

---

## Running Locally

```bash
python -m monitor.monitor
```

---

## Importing in Python

```python
from monitor import run_monitor, load_config, Announcement

result = run_monitor()
```

---

## Testing Individual Components

```python
from monitor import load_config, fetch_page, extract_announcements, detect_announcements

cfg = load_config()
html = fetch_page(cfg.target_url)
candidates = extract_announcements(html)
announcements = detect_announcements(candidates, cfg)
```

---

## License

MIT License — see the [LICENSE](LICENSE) file for details.
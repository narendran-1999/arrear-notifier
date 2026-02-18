## College Announcement Monitor

Automated, free monitoring system that checks a college website daily for specific announcements (such as arrear / exam notifications), sends Telegram alerts, and exposes the latest announcement on a static GitHub Pages site.

### Repository structure

- `monitor/` – Python monitoring package (web scraping, fuzzy matching, Telegram, and state management).
- `state/state.json` – JSON state shared between the monitor and the status webpage.
- `page/` – Static GitHub Pages site (HTML/CSS/JS) that reads `state.json` and shows status plus the latest announcement.
- `.github/workflows/monitor.yml` – GitHub Actions workflow that runs the monitor on a daily schedule.

### Configuration

All sensitive values are provided via environment variables or GitHub Secrets. Required variables:

- `TARGET_URL` – College website URL to monitor.
- `MATCH_KEYWORDS` – Comma‑separated keywords for fuzzy matching (e.g. `arrear exam, revaluation`).
- `TELEGRAM_BOT_TOKEN` – Telegram Bot API token.
- `TELEGRAM_CHANNEL_ID` – Chat ID of the public channel for announcements.
- `TELEGRAM_OWNER_CHAT_ID` – Chat ID for private error alerts.

Optional variables:

- `STATE_FILE` – Path to state JSON file (default: `state/state.json`).
- `MONITORING_ENABLED` – `"true"` / `"false"` flag to turn monitoring on or off (default: `"true"`).
- `SIMILARITY_THRESHOLD` – Fuzzy match threshold between 0 and 1 (default: `0.6`).
- `ERROR_THROTTLE_MINUTES` – Minimum minutes between repeated error alerts with the same signature (default: `60`).

### Local development

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Export the required environment variables (or use a local `.env` mechanism if desired).
4. Run a single monitoring pass:

```bash
python -m monitor.monitor
```

### Deployment notes

- Enable GitHub Pages to serve from the repository root or a dedicated branch and ensure the `page/` and `state/` directories are included in the published content.
- Configure the GitHub Secrets used in `.github/workflows/monitor.yml` for the Telegram Bot and the target website.
- Disable the workflow schedule or set `MONITORING_ENABLED=false` to temporarily suspend monitoring while keeping the status page online.


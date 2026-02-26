<p align="center">
  <img src="static/iristransparentbh.svg" width="200" alt="Project Iris" style="background:#0d031b;padding:16px;border-radius:12px;">
</p>

<h1 align="center">Project Iris</h1>
<p align="center"><em>TikTok intelligence &amp; monitoring platform</em></p>

---

## Overview

Project Iris is a self-hosted TikTok account monitoring platform. Add accounts to a watchlist, run periodic automated checks, and get notified of any profile changes — follower counts, following counts, likes, video counts, bio updates, and more.

Built with Python, Flask, SQLite, and [Scrapling](https://github.com/D4Vinci/Scrapling) for anti-detection scraping.

---

## Features

| Feature | Description |
|---|---|
| **Instant profile check** | Look up any TikTok account on demand |
| **Watchlist monitoring** | Track multiple accounts automatically |
| **Periodic checks** | Configurable background monitor (default: every 15 min) |
| **Change detection** | Detects follower/following/likes/video/bio changes and logs events |
| **Failure tracking** | Logs scrape failures per account |
| **Full settings UI** | Every setting configurable from the web panel — no config files needed |
| **REST API** | JSON endpoints for status, watchlist, events, failures, and history |
| **Dark mode** | Respects system preference; toggle persists across sessions |
| **SQLite storage** | Zero external dependencies for persistence |

---

## Quick start

### 1. Clone and set up a virtual environment

```bash
git clone https://github.com/Sha-Dox/project-iris
cd project-iris
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

Open **http://localhost:8000** in your browser.

---

## Configuration

All settings are available from the **⚙ Settings** panel at the bottom of the dashboard. Changes take effect immediately (except items marked **restart required**).

| Setting | Default | Description |
|---|---|---|
| Web port | `8000` | Port Flask listens on *(restart required)* |
| Debug mode | `on` | Flask debug/reloader *(restart required)* |
| Monitor interval | `900 s` | Seconds between automatic check cycles |
| Auto-start monitor | `on` | Start background monitor when app boots *(restart required)* |
| Dashboard events limit | `30` | Max change events shown on dashboard |
| Dashboard failures limit | `20` | Max failures shown on dashboard |
| API default limit | `100` | Default `?limit=` for API list endpoints |
| API max limit | `500` | Hard ceiling for API `?limit=` |
| History default limit | `100` | Default snapshots returned by `/api/history/<username>` |

You can also set initial values via environment variables before first launch:

```bash
PORT=9000 MONITOR_INTERVAL_SECONDS=300 AUTO_START_MONITOR=0 python app.py
```

---

## REST API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Monitor status + current settings |
| `GET` | `/api/settings` | All current settings as JSON |
| `GET` | `/api/watchlist` | Active watchlist with latest snapshot data |
| `GET` | `/api/events?limit=N` | Recent change events |
| `GET` | `/api/failures?limit=N` | Recent scrape failures |
| `GET` | `/api/history/<username>?limit=N` | Snapshot history for one account |

---

## Project structure

```
project-iris/
├── app.py                  # Flask app, routes, settings engine
├── monitor.py              # Background monitor service
├── scraper.py              # Scrapling-based TikTok profile fetcher
├── storage.py              # SQLite persistence layer
├── iris.db                 # Database (auto-created on first run)
├── requirements.txt
├── static/
│   ├── iris.svg            # Logo (dark background)
│   └── iristransparentbh.svg  # Logo (transparent, white)
└── templates/
    └── index.html          # Dashboard UI
```

---

## Data model

```
watch_accounts   — accounts under surveillance
snapshots        — profile state captured at each check
events           — detected changes (diff between consecutive snapshots)
failures         — scrape errors with timestamp
settings         — key/value persistent configuration
```

---

## Requirements

- Python 3.10+
- See `requirements.txt` for Python packages (Flask, Scrapling)

---

## License

MIT

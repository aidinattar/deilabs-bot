# DeiLabs Bot

Unofficial toolset to manage DeiLabs presence with:
- a CLI (`deilabs`)
- a Telegram bot
- a small web dashboard

The bot does not know UniPD credentials.
Authentication is manual and based on a session file (`auth_<user_id>.json`).

## Quick Start (Users: Session File Only)

If you are a user and you only need to generate your session file, follow this section.

1. Move to the project folder.

```bash
cd /path/to/deilabs-bot
```

2. Install only the minimal dependencies for login/session generation.

```bash
python -m pip install ".[session]"
playwright install firefox
```

3. Generate your session file.

```bash
PYTHONPATH=src python -m deilabs_bot.cli login --user-id <YOUR_TELEGRAM_ID>
```

4. Send the generated file to the Telegram bot as a document.

Expected file path:

```bash
./auth/auth_<YOUR_TELEGRAM_ID>.json
```

If your session expires, repeat the same steps and upload the new file.

---

## Quick Start (Bot + Dashboard)

For the person running the whole service.

1. Create `.env` with at least:

```bash
TELEGRAM_BOT_TOKEN=...
ADMIN_USER_IDS=123456789
BOT_TIMEZONE=Europe/Rome
DEILABS_WEB_PORT=8080
```

2. Start services:

```bash
docker compose up -d --build
```

This starts:
- `deilabs-bot` (Telegram)
- `deilabs-web` (dashboard)

Dashboard URL:

```bash
http://127.0.0.1:${DEILABS_WEB_PORT:-8080}
```

---

## Details

### Core files

- `src/deilabs_bot/cli.py`: CLI commands
- `src/deilabs_bot/bot.py`: Telegram handlers and scheduled jobs
- `src/deilabs_bot/web.py`: Flask dashboard
- `src/deilabs_bot/client.py`: Playwright automation
- `src/deilabs_bot/db.py`: SQLite access and tables

### Session model

- Session is created with `deilabs ... login`.
- Bot actions (`/status`, `/punch`, `/exit`) use that saved session.
- If DeiLabs reports `session expired`, user must generate and upload a fresh file.

### Persistence

In Docker, persistent data is in volume `deilabs-data` mounted at `/data`.

Stored data:
- auth files
- uploaded files
- logs
- SQLite DB
- user preferences

Do not run `docker compose down -v` unless you want to delete persisted data.

### Database tables

- `session_uploads`
- `status_events`
- `current_status`

Dashboard data comes from `current_status`.

### Scheduled jobs

- `00:00`: set everyone to `outside`
- `10:00` (Mon-Fri only):
  - run status check
  - send reminder only to users not already `inside`
- recurring status check every 5 minutes

### Telegram commands

User commands:
- `/start`
- `/status`
- `/punch`
- `/exit`
- `/setlab`

Admin commands:
- `/admin`
- `/broadcast <message>`

### Dashboard endpoints

- `/`
- `/api/status`
- `/health`

Auto-refresh default: 5 minutes (`DEILABS_WEB_REFRESH_SECONDS=300`).

### Environment variables

Core:
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USER_IDS`
- `BOT_TIMEZONE`

Scheduler:
- `STATUS_CHECK_INTERVAL_MINUTES` (default: `5`)

Web:
- `DEILABS_WEB_HOST` (default: `0.0.0.0`)
- `DEILABS_WEB_PORT` (default: `8080`)
- `DEILABS_WEB_REFRESH_SECONDS` (default: `300`)
- `DEILABS_WEB_TITLE` (default: `DeiLabs Presence Dashboard`)

Paths (optional override):
- `DEILABS_DATA_DIR`

### Dependency profiles (pyproject extras)

- Session generation only: `.[session]`
- Bot + dashboard runtime: `.[bot]`
- Development tools + runtime deps: `.[dev]`

### Local development

```bash
python -m pip install -e ".[dev]"
playwright install
python -m deilabs_bot.bot
```

Web only:

```bash
deilabs-web
```

### Tests

```bash
PYTHONPATH=src pytest -q -p no:cacheprovider
```

### Common issues

- `session expired`: regenerate session file and upload it
- data missing after restart: verify `deilabs-data` volume
- `No module named deilabs_bot`: reinstall package (`pip install -e .`) or rebuild image

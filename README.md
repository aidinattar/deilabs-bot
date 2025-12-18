# DeiLabs Bot & CLI

This project provides:

1. A **Python CLI** to interact with the [DeiLabs platform](https://deilabs.dei.unipd.it/) using Playwright.
2. A **Telegram bot** that can check your presence status, enter/exit a laboratory, and manage your preferences, using a previously saved authenticated session.

**Important:**  
The bot does *not* handle UniPD credentials and does *not* perform automatic login.  
Authentication must be performed manually once through the CLI in a real browser window.

---

## Features

### CLI (`deilabs`)

- **`deilabs login --user-id <ID>`**  
  Opens a non-headless Playwright browser and allows the user to manually log in on DeiLabs.  
  After login, the authenticated session is saved under:

  ```bash
  auth/auth_<ID>.json
  ```

- **`deilabs status --user-id <ID>`**  
  Checks whether the user is currently marked as *inside* or *outside* the selected laboratory.

- **`deililabs punch --user-id <ID>`**  
  Marks the user as *inside* the laboratory (if not already inside).

- **`deilabs exit --user-id <ID>`**  
  Marks the user as *outside* the laboratory.

- **`deilabs setlab --user-id <ID> --lab "<LAB NAME>"`**  
  Sets the default laboratory for the specified user.

User preferences are stored in:

```bash
user_prefs.json
```

Session files are stored in:

```bash
auth/auth_<user_id>.json
```

---

## Telegram Bot

The Telegram bot provides:

### Commands

- **`/start`** – Shows the user’s Telegram ID and usage instructions.  
- **`/status`** – Displays current presence status.  
- **`/punch`** – Marks entry into the default laboratory.  
- **`/exit`** – Marks exit from the laboratory.  
- **`/setlab`** – Sets the user’s default lab.  
  If used with no arguments, it presents a keyboard with multiple laboratory options.
- **Document upload** – Send the `auth_<user_id>.json` file as a *document* in the chat to update your session without touching the server filesystem.

### Notes

- The bot can only operate *after* a valid session has been created with:

```bash
deilabs login --user-id <ID>
```

- The bot uses the same session file as the CLI.
- When the session file is updated locally, forward it to the bot chat (as a document) to refresh the copy stored under `auth/auth_<user_id>.json`.

---

## Project Structure

```css
deilabs-bot/
├─ src/
│  ├─ deilabs_bot/
│  │  ├─ bot.py            # Telegram bot
│  │  ├─ client.py         # Playwright client
│  │  ├─ labs.py           # Lab list + pagination
│  │  ├─ prefs.py          # User preference manager
│  │
│  └─ cli.py               # CLI entry point
│
├─ auth/                   # Saved Playwright sessions
│   └─ auth_<user_id>.json
│
└─ user_prefs.json         # Mapping user_id → lab name
```

---

## How the System Works

1. The user must log in manually once using the CLI:

   ```bash
   deilabs login --user-id <ID_TELEGRAM>
   ```

   - A Playwright browser window opens.
   - The user logs in on the **official DeiLabs website**.
   - The session is saved locally.

2. After that:
   - The Telegram bot can:
     - check status,
     - enter/exit,
     - manage laboratory selection,
   without repeating the login, unless the session expires.

---

## Limitations (Current System)

- Login must be done manually in a real browser.
- The bot cannot perform authentication workflows.
- The bot requires:
  - a session file under `auth/`,
  - a default lab set in `user_prefs.json`.

---

## Requirements

- Python 3.10+
- Playwright:

  ```bash
  pip install playwright
  playwright install
  ```

- Telegram Bot Token in env:

  ```bash
  export TELEGRAM_BOT_TOKEN="..."
  ```

---

## Running the Bot

From inside the `src/` folder:

```bash
python -m deilabs_bot.bot
```

---

## Current Status

The system supports:

- Manual login through Playwright.
- Enter/exit operations via CLI and Telegram.
- Status checking.
- Lab selection via command or Telegram inline keyboards.
- Consistent session handling per user.

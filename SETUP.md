# AI Usage Dashboard — Setup Guide

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 1a. Run the Alpha 0.2 migration (first time only)

```bash
cd D:/ai-dash-source
python database/migrate_users.py
```

This adds the `users` and `auth_otp` tables and the `user_id` column to the three data tables. Safe to re-run — all steps are idempotent.

## 1b. Fill in secrets

Edit `.streamlit/secrets.toml` (created automatically — never commit this file):

**Gmail SMTP** (for OTP / password-reset emails):
1. Google Account → Security → 2-Step Verification → App passwords
2. Create an app password for "Mail"
3. Paste the 16-char password as `SMTP_PASSWORD`

**Google OAuth** (optional — skip if you don't need Google sign-in):
1. [console.cloud.google.com](https://console.cloud.google.com) → create or select a project
2. APIs & Services → OAuth consent screen → External → fill in app name + email
3. Credentials → Create OAuth 2.0 Client ID → Web application
4. Authorized redirect URI: `http://localhost:8501`
5. Copy Client ID → `GOOGLE_CLIENT_ID`, Client Secret → `GOOGLE_CLIENT_SECRET`

## 2. Initialize the database

The database is created automatically on first run. To initialize manually:

```bash
python -c "
import sqlite3
from pathlib import Path
db = sqlite3.connect('database/usage.db')
db.executescript(Path('database/schema.sql').read_text())
db.commit()
print('Database initialized at database/usage.db')
"
```

## 3. Configure subscriptions

Edit `config/subscriptions.yaml` to set your actual monthly costs and repo root paths:

```yaml
tools:
  claude_code:
    monthly_cost: 20.00   # your actual cost
  cursor:
    monthly_cost: 20.00
  ...

repo_roots:
  - "D:/"
  - "C:/Users/YourName/Documents"
```

## 4. Configure Claude Code hooks

Add to `~/.claude/settings.json` (global) or project `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}
    ],
    "PreToolUse": [
      {"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}
    ],
    "PostToolUse": [
      {"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}
    ],
    "PostToolUseFailure": [
      {"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}
    ],
    "Stop": [
      {"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}
    ]
  }
}
```

**Note:** Use the full absolute path to `claude_hook.py`.

## 4a. Set your User ID for the collectors

After signing up in the dashboard for the first time, go to **Settings → Profile** and copy your User ID. Then set it as a persistent Windows environment variable so the collectors tag your data:

```bat
setx AI_DASH_USER_ID "paste-your-uuid-here"
```

Restart any open terminals and the background service after running this.

## 5. Start the background service

Open a terminal and run:

```bash
cd D:/ai-dash-source
python run_background.py
```

This starts three background threads:
- **WindowMonitor** — polls active window every 5s (Cursor, ChatGPT, Gemini)
- **RepoAnalyzer** — scans git repos every 10 min for commit correlation
- **PeriodicProcessor** — runs sessionizer + metrics every 5 min

Leave this running in the background. Logs are written to `background.log`.

## 6. Start the dashboard

In a **separate** terminal:

```bash
cd D:/ai-dash-source
streamlit run dashboard/app.py
```

Opens at http://localhost:8501

## 7. Verify data collection

After running for a few minutes with Claude Code active:

```bash
python -c "
import sqlite3
db = sqlite3.connect('database/usage.db')
print('raw_events:', db.execute('SELECT COUNT(*) FROM raw_events').fetchone()[0])
print('sessions:  ', db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0])
print('daily_metrics:', db.execute('SELECT COUNT(*) FROM daily_metrics').fetchone()[0])

print()
print('Recent events:')
for row in db.execute('SELECT timestamp, tool, event_type, session_id FROM raw_events ORDER BY id DESC LIMIT 10').fetchall():
    print(' ', row)
"
```

## Tool detection

Window title patterns (configurable in `subscriptions.yaml`):

| Tool | Window title must contain |
|---|---|
| Cursor | `Cursor` |
| ChatGPT | `ChatGPT` or `chat.openai.com` |
| Gemini | `Gemini` or `gemini.google.com` |

Claude Code is tracked exclusively via hooks (not window polling).

## Keeping the background service running

To auto-start on Windows login, create a batch file and add to Startup folder:

**start_ai_dashboard.bat:**
```bat
@echo off
cd /d D:\ai-dash-source
start /min python run_background.py
```

Place in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

## AFK detection

The window monitor uses `GetLastInputInfo()` (Windows API) to detect user inactivity.
If no keyboard/mouse input for ≥5 minutes (configurable: `afk_threshold_seconds`),
the current window session is flushed and not counted as active time.

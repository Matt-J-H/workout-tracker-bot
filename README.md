# Workout Tracker Discord Bot

A private Discord bot that helps you and your friends track weekly workouts:
a live at-a-glance board, per-person goals, streaks, and full history.

Weeks run **Sunday → Saturday** using one shared server timezone.

## Features

- **Per-person defaults** — set how many days/week you aim for, and optionally
  which days you plan to work out (`/goal`, `/planned`).
- **Weekly overrides** — bump this week's goal up or down without changing your
  default (`/override`).
- **Weekly board** — each week posts a fresh board message showing everyone's
  week at a glance (planned days, completed days, progress toward each goal),
  with **Log workout** and **Schedule** buttons. The current week's board stays
  stuck to the bottom of its channel (so notifications posted there don't bury
  it); when a new week begins, the old board is finalized (buttons removed) and a
  new one is posted below it, so the board channel becomes a running history of
  past weeks. Give the board its own **view-only** channel and members can still
  use the buttons (button clicks are interactions, not messages, so Send Messages
  isn't required) — nothing gets buried and the channel can be muted.
- **Logging** — `/done` (or the button) opens a form with the date (defaults to
  today, so you can back-fill a workout you forgot to log — future dates are
  rejected) plus optional type, duration, and notes. `/undo` removes your most
  recent entry.
- **Notifications** — when you log a workout, the bot posts to a configurable
  notification channel (separate from the board so the board can be muted; falls
  back to the board channel if unset) and pings a chosen role, calling it out
  extra when you complete your weekly goal.
- **Streaks & history** — consecutive weeks the goal was hit, best streak, total
  workouts, and recent-workout history (`/stats`, `/history`). All workouts are
  stored in SQLite for later metrics.

## Commands

| Command | Who | What |
| --- | --- | --- |
| `/setup [channel] [notify_channel] [notify_role] [timezone]` | Manage Server | Configure board channel (defaults to current), optional separate notifications channel, notify role, timezone; posts the board |
| `/refresh` | Manage Server | Refresh the current week's board (or start it) |
| `/goal days [planned_days]` | anyone | Set your default weekly goal (+ optional planned days) |
| `/planned days` | anyone | Set/clear your default planned days |
| `/override days [planned_days]` | anyone | Override just this week |
| `/myprofile` | anyone | Show your settings & this week |
| `/done` | anyone | Log a workout (form: date + optional details) |
| `/undo` | anyone | Remove your most recent logged workout |
| `/week [weeks_ago]` | anyone | Browse a past week's board (◀/▶ to navigate) |
| `/stats [member]` | anyone | Streaks & totals |
| `/history [member] [limit]` | anyone | Recent workouts |

Board legend: `#` done · `o` planned · `x` missed plan · `.` nothing ·
✅ goal hit · 🔥 week streak.

## Setup

### 1. Create the bot application
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Bot** tab → **Add Bot**. Copy the **token**.
3. Under **Privileged Gateway Intents**, enable **Server Members Intent**
   (used to show display names on the board).
4. **OAuth2 → URL Generator**: scopes `bot` and `applications.commands`;
   bot permissions: **View Channel**, **Send Messages**, **Embed Links**,
   **Read Message History**. Open the generated URL to invite the bot to your
   server. (Make sure those permissions also apply in the board channel itself.)

### 2. Configure
```bash
cp .env.example .env
# edit .env: paste DISCORD_TOKEN, your GUILD_ID, and your TIMEZONE
```
Enable Developer Mode in Discord (Settings → Advanced) to copy the server ID
(right-click server icon → Copy Server ID).

### 3. Install & run
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python bot.py
```

Because `GUILD_ID` is set, slash commands appear in your server instantly.

### 4. First-time in Discord
1. Run `/setup` in the channel you want the board in. Optionally pass a
   `notify_channel` (where workout notifications post — keep this separate so the
   board channel can be muted), a `notify_role` (pinged on each logged workout),
   and a `timezone`.
2. Everyone runs `/goal` to set their weekly target.
3. Log with the **Log workout** button or `/done`.

Tip: give the board its own channel (e.g. `#workout-board`), point
`notify_channel` at your chat channel, and members can mute the board channel
while still seeing notifications. The board channel keeps a message per week as a
history.

## Notes

- Requires **Python 3.11+** (tested on 3.14). `tzdata` is included so timezones
  work on Windows.
- Data lives in a single SQLite file (`data/tracker.db` by default) — easy to
  back up and to move when hosting.
- Once a week has any activity, its goal is "locked in", so later changes to
  your default don't rewrite past weeks.
- A new week's board appears automatically (within the hour) once the week rolls
  over, thanks to a background refresh.

## Hosting

The bot is a single long-running process plus one SQLite file, so almost any
always-on host works (a small VPS, a Raspberry Pi, Railway, Fly.io, etc.).
Ask when you're ready and we'll pick one and set it up.

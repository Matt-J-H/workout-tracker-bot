# Hosting on Railway

This runs the bot 24/7 in the cloud so you don't have to keep it running on your
own machine. Railway builds the repo, runs `python bot.py` as a background
worker, and stores the SQLite database on a persistent volume.

**Cost:** Railway's Hobby plan is ~$5/month and includes ~$5 of usage; a bot
this small uses only a couple dollars of that, so it's effectively covered.

---

## What's already set up for you

- `railway.json` — tells Railway to run `python bot.py` and restart on crashes.
- `Procfile` — same start command (portability/backup).
- `.python-version` — pins Python 3.12.
- `requirements.txt` — dependencies Railway installs automatically.
- `.gitignore` — keeps your `.env` (token!) and local database out of git.

You do **not** commit your `.env`. Secrets go into Railway's Variables instead.

---

## Step 1 — Put the code on GitHub

The local repo is already initialized and committed. Now create a GitHub repo
and push to it.

1. Go to <https://github.com/new>.
2. Name it e.g. `workout-tracker-bot`. **Keep it Private.** Do **not** add a
   README/.gitignore/license (the repo already has them).
3. Click **Create repository**. GitHub shows an "…or push an existing
   repository" box. Copy the repo URL (looks like
   `https://github.com/<you>/workout-tracker-bot.git`).
4. Back in this project folder, run:
   ```bash
   git remote add origin https://github.com/<you>/workout-tracker-bot.git
   git branch -M main
   git push -u origin main
   ```
   (If prompted to sign in, use your GitHub account / a personal access token.)

## Step 2 — Create the Railway project

1. Go to <https://railway.app> and sign in with GitHub.
2. **New Project → Deploy from GitHub repo →** pick `workout-tracker-bot`.
   (First time, you'll authorize Railway to access the repo.)
3. Railway starts a build immediately. It will **fail or crash-loop until you do
   Steps 3 and 4** — that's expected, because the token and database aren't set
   yet.

## Step 3 — Add a persistent volume (for the database)

Without this, every redeploy wipes your workout history.

1. Open your service → **Variables/Settings** area → **+ New Volume** (or
   right-click the service canvas → **Attach Volume**).
2. Set the **mount path** to `/data`.
3. Save. Railway attaches a small persistent disk mounted at `/data`.

## Step 4 — Set environment variables

In your service → **Variables**, add these (Railway → "New Variable", or "Raw
Editor" to paste all at once):

```
DISCORD_TOKEN=your-bot-token-here
GUILD_ID=your-server-id
TIMEZONE=America/Chicago
DATABASE_PATH=/data/tracker.db
```

- `DISCORD_TOKEN` — from the Discord Developer Portal (Bot tab). Keep it secret.
- `GUILD_ID` — your server's ID (Discord → enable Developer Mode → right-click
  server → Copy Server ID). This makes slash commands sync instantly.
- `TIMEZONE` — your shared timezone.
- `DATABASE_PATH` — **must** point inside the volume: `/data/tracker.db`.

Saving variables triggers a redeploy.

## Step 5 — Verify

1. Open the service → **Deployments → View Logs**.
2. You want to see: `Synced slash commands to guild ...` and
   `Logged in as <bot> (id: ...)`.
3. In Discord, run `/refresh` — the board should post.

Done — the bot now runs 24/7.

---

## Updating the bot later

Any time you change the code:
```bash
git add -A
git commit -m "describe your change"
git push
```
Railway auto-deploys the new version. Your database on the volume is untouched.

## Moving your existing data (optional)

If you've already built up workout history locally in `data/tracker.db` and want
to keep it, tell me — moving a SQLite file onto a Railway volume takes a couple
of extra steps (upload via the Railway CLI). Otherwise the bot starts with a
fresh database in the cloud.

## Checking that data is actually persisting

Run **`/dbstatus`** in Discord (admins only). It reports the database file path,
its size, when it was last written, and how many members/workouts are stored.

What you want to see:

- **File:** `/data/tracker.db` — an absolute path inside the volume.
- **Persistence:** the ✅ line. A ⚠️ means `DATABASE_PATH` is relative, i.e.
  ephemeral storage that is wiped on every redeploy.
- **Across a redeploy:** the counts should stay the same or grow — never reset
  to 0. That's the real proof it's persisting.

The startup logs (**Deployments → View Logs**) show the same thing:

```
INFO tracker.db: Database: /data/tracker.db (existing file)
```

`NEW empty file` on every deploy means the volume isn't wired up.

### Inspecting the volume directly (optional)

With the [Railway CLI](https://docs.railway.app/guides/cli) installed:

```bash
railway ssh
```

Then, inside the container:

```bash
ls -la /data
python -c "import sqlite3;c=sqlite3.connect('/data/tracker.db');print(c.execute('select count(*) from workout').fetchone())"
```

## Troubleshooting

- **Crash loop / exits immediately:** almost always a bad or missing
  `DISCORD_TOKEN`. Check the deploy logs.
- **Board posts but resets/empties after a redeploy:** the volume isn't mounted
  at `/data`, or `DATABASE_PATH` doesn't point to `/data/tracker.db`.
- **Commands don't appear:** `GUILD_ID` is wrong/missing (global sync can take up
  to an hour; guild sync is instant).
- **`ZoneInfoNotFoundError`:** `tzdata` is in `requirements.txt`, so this
  shouldn't happen on Railway — but double-check `TIMEZONE` is a valid IANA name.

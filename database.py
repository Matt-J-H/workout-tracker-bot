"""SQLite data-access layer (async, via aiosqlite).

All persistent state lives here. The week-goal design:
  * user_config holds each person's *default* weekly goal + intended days.
  * week_override holds a per-week snapshot. A row is written when someone
    overrides a week AND automatically the first time they log a workout in a
    week, which "locks in" the goal that applied that week so later changes to
    the default don't rewrite history.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import aiosqlite

from timeutils import week_start

log = logging.getLogger("tracker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id          INTEGER PRIMARY KEY,
    board_channel_id  INTEGER,
    board_message_id  INTEGER,
    board_week        TEXT,     -- ISO Sunday the current board_message_id is for
    notify_channel_id INTEGER,  -- where workout notifications go (falls back to board)
    notify_role_id    INTEGER,
    timezone          TEXT NOT NULL DEFAULT 'America/Chicago'
);

CREATE TABLE IF NOT EXISTS user_config (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    goal_days     INTEGER NOT NULL DEFAULT 3,
    intended_days TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS week_override (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    week_start    TEXT NOT NULL,          -- ISO date (a Sunday)
    goal_days     INTEGER NOT NULL,
    intended_days TEXT NOT NULL DEFAULT '',
    -- 1 = explicit /override by the user; 0 = auto-snapshot to lock history.
    -- The current week ignores auto-snapshots so live edits show immediately.
    is_explicit   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, week_start)
);

CREATE TABLE IF NOT EXISTS workout (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    workout_date TEXT NOT NULL,           -- ISO date in server tz
    created_at   TEXT NOT NULL,           -- ISO UTC timestamp
    wtype        TEXT,
    duration_min INTEGER,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_workout_lookup
    ON workout (guild_id, user_id, workout_date);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        resolved = os.path.abspath(self.path)
        existed = os.path.exists(resolved)
        log.info(
            "Database: %s (%s)",
            resolved,
            "existing file" if existed else "NEW empty file",
        )
        if not os.path.isabs(self.path):
            # On a container host (Railway/Fly/etc.) a relative path lands on the
            # ephemeral filesystem and is wiped on every redeploy, silently
            # resetting everyone's goals and history.
            log.warning(
                "DATABASE_PATH (%r) is a relative path. If this bot is hosted in a "
                "container, set DATABASE_PATH to a persistent volume (e.g. "
                "/data/tracker.db) or all data will be lost on every redeploy.",
                self.path,
            )

        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Apply lightweight schema migrations to existing databases."""
        async with self._db.execute("PRAGMA table_info(week_override)") as cur:
            wo_cols = {row["name"] for row in await cur.fetchall()}
        if "is_explicit" not in wo_cols:
            await self._db.execute(
                "ALTER TABLE week_override ADD COLUMN "
                "is_explicit INTEGER NOT NULL DEFAULT 0"
            )

        async with self._db.execute("PRAGMA table_info(guild_config)") as cur:
            gc_cols = {row["name"] for row in await cur.fetchall()}
        if "board_week" not in gc_cols:
            await self._db.execute(
                "ALTER TABLE guild_config ADD COLUMN board_week TEXT"
            )
        if "notify_channel_id" not in gc_cols:
            await self._db.execute(
                "ALTER TABLE guild_config ADD COLUMN notify_channel_id INTEGER"
            )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # ---------- guild config ----------
    async def get_guild_config(self, guild_id: int) -> aiosqlite.Row | None:
        async with self.db.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        ) as cur:
            return await cur.fetchone()

    async def upsert_guild_config(
        self,
        guild_id: int,
        *,
        board_channel_id: int | None = None,
        notify_channel_id: int | None = None,
        notify_role_id: int | None = None,
        timezone_name: str | None = None,
    ) -> None:
        existing = await self.get_guild_config(guild_id)
        if existing is None:
            await self.db.execute(
                """INSERT INTO guild_config
                   (guild_id, board_channel_id, notify_channel_id, notify_role_id, timezone)
                   VALUES (?, ?, ?, ?, COALESCE(?, 'America/Chicago'))""",
                (guild_id, board_channel_id, notify_channel_id, notify_role_id, timezone_name),
            )
        else:
            await self.db.execute(
                """UPDATE guild_config SET
                       board_channel_id  = COALESCE(?, board_channel_id),
                       notify_channel_id = COALESCE(?, notify_channel_id),
                       notify_role_id    = COALESCE(?, notify_role_id),
                       timezone          = COALESCE(?, timezone)
                   WHERE guild_id = ?""",
                (board_channel_id, notify_channel_id, notify_role_id, timezone_name, guild_id),
            )
        await self.db.commit()

    async def set_board_message(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        board_week: str | None = None,
    ) -> None:
        await self.db.execute(
            """UPDATE guild_config
               SET board_channel_id = ?, board_message_id = ?, board_week = ?
               WHERE guild_id = ?""",
            (channel_id, message_id, board_week, guild_id),
        )
        await self.db.commit()

    # ---------- user config ----------
    async def get_user_config(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        async with self.db.execute(
            "SELECT * FROM user_config WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            return await cur.fetchone()

    async def ensure_user_config(self, guild_id: int, user_id: int) -> aiosqlite.Row:
        row = await self.get_user_config(guild_id, user_id)
        if row is None:
            await self.db.execute(
                "INSERT INTO user_config (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await self.db.commit()
            row = await self.get_user_config(guild_id, user_id)
        assert row is not None
        return row

    async def set_user_goal(
        self,
        guild_id: int,
        user_id: int,
        goal_days: int,
        intended_days: str | None = None,
    ) -> None:
        await self.ensure_user_config(guild_id, user_id)
        if intended_days is None:
            await self.db.execute(
                "UPDATE user_config SET goal_days = ? WHERE guild_id = ? AND user_id = ?",
                (goal_days, guild_id, user_id),
            )
        else:
            await self.db.execute(
                """UPDATE user_config SET goal_days = ?, intended_days = ?
                   WHERE guild_id = ? AND user_id = ?""",
                (goal_days, intended_days, guild_id, user_id),
            )
        await self.db.commit()

    async def set_user_intended(
        self, guild_id: int, user_id: int, intended_days: str
    ) -> None:
        await self.ensure_user_config(guild_id, user_id)
        await self.db.execute(
            "UPDATE user_config SET intended_days = ? WHERE guild_id = ? AND user_id = ?",
            (intended_days, guild_id, user_id),
        )
        await self.db.commit()

    async def list_user_configs(self, guild_id: int) -> list[aiosqlite.Row]:
        async with self.db.execute(
            "SELECT * FROM user_config WHERE guild_id = ? ORDER BY user_id",
            (guild_id,),
        ) as cur:
            return list(await cur.fetchall())

    # ---------- week overrides / effective goal ----------
    async def get_week_override(
        self, guild_id: int, user_id: int, ws: str
    ) -> aiosqlite.Row | None:
        async with self.db.execute(
            """SELECT * FROM week_override
               WHERE guild_id = ? AND user_id = ? AND week_start = ?""",
            (guild_id, user_id, ws),
        ) as cur:
            return await cur.fetchone()

    async def set_week_override(
        self,
        guild_id: int,
        user_id: int,
        ws: str,
        goal_days: int,
        intended_days: str,
    ) -> None:
        # An explicit /override always wins, even over an existing auto-snapshot.
        await self.db.execute(
            """INSERT INTO week_override
                   (guild_id, user_id, week_start, goal_days, intended_days, is_explicit)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(guild_id, user_id, week_start)
               DO UPDATE SET goal_days = excluded.goal_days,
                             intended_days = excluded.intended_days,
                             is_explicit = 1""",
            (guild_id, user_id, ws, goal_days, intended_days),
        )
        await self.db.commit()

    async def ensure_week_snapshot(
        self, guild_id: int, user_id: int, ws: str, refresh: bool = True
    ) -> None:
        """Record/refresh the auto-snapshot that locks a week's goal for history.

        An explicit override is always left untouched. A missing snapshot is
        created from the current default. `refresh` should be True only for the
        current week: it re-syncs a non-explicit snapshot to the latest default
        so the locked value tracks recent settings. For a past week (back-dated
        logging) pass refresh=False so its historical goal is not rewritten.
        """
        cfg = await self.ensure_user_config(guild_id, user_id)
        existing = await self.get_week_override(guild_id, user_id, ws)
        if existing is None:
            await self.db.execute(
                """INSERT INTO week_override
                       (guild_id, user_id, week_start, goal_days, intended_days, is_explicit)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (guild_id, user_id, ws, cfg["goal_days"], cfg["intended_days"]),
            )
            await self.db.commit()
        elif refresh and not existing["is_explicit"]:
            await self.db.execute(
                """UPDATE week_override SET goal_days = ?, intended_days = ?
                   WHERE guild_id = ? AND user_id = ? AND week_start = ?""",
                (cfg["goal_days"], cfg["intended_days"], guild_id, user_id, ws),
            )
            await self.db.commit()

    async def effective_week(
        self, guild_id: int, user_id: int, ws: str, current_ws: str | None = None
    ) -> tuple[int, str]:
        """Return (goal_days, intended_days_str) that apply for a given week.

        For the current week, an auto-snapshot does NOT freeze settings — the
        live default is used so `/goal` and `/planned` edits show immediately.
        Explicit overrides always apply.
        """
        ov = await self.get_week_override(guild_id, user_id, ws)
        if ov is not None:
            is_current = current_ws is not None and ws == current_ws
            if ov["is_explicit"] or not is_current:
                return ov["goal_days"], ov["intended_days"]
        cfg = await self.ensure_user_config(guild_id, user_id)
        return cfg["goal_days"], cfg["intended_days"]

    # ---------- workouts ----------
    async def add_workout(
        self,
        guild_id: int,
        user_id: int,
        workout_date: str,
        wtype: str | None,
        duration_min: int | None,
        notes: str | None,
    ) -> int:
        cur = await self.db.execute(
            """INSERT INTO workout
               (guild_id, user_id, workout_date, created_at, wtype, duration_min, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, workout_date, _utcnow_iso(), wtype, duration_min, notes),
        )
        await self.db.commit()
        return cur.lastrowid

    async def done_days(self, guild_id: int, user_id: int, ws: str) -> set[str]:
        """Distinct dates (ISO strings) with a workout in the week starting `ws`."""
        end = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        async with self.db.execute(
            """SELECT DISTINCT workout_date FROM workout
               WHERE guild_id = ? AND user_id = ?
                 AND workout_date BETWEEN ? AND ?""",
            (guild_id, user_id, ws, end),
        ) as cur:
            return {row["workout_date"] for row in await cur.fetchall()}

    async def workouts_on(
        self, guild_id: int, user_id: int, day: str
    ) -> list[aiosqlite.Row]:
        async with self.db.execute(
            """SELECT * FROM workout
               WHERE guild_id = ? AND user_id = ? AND workout_date = ?
               ORDER BY id""",
            (guild_id, user_id, day),
        ) as cur:
            return list(await cur.fetchall())

    async def last_workout(
        self, guild_id: int, user_id: int
    ) -> aiosqlite.Row | None:
        """The most recently *logged* workout (by insertion order), for /undo."""
        async with self.db.execute(
            """SELECT * FROM workout
               WHERE guild_id = ? AND user_id = ?
               ORDER BY id DESC LIMIT 1""",
            (guild_id, user_id),
        ) as cur:
            return await cur.fetchone()

    async def delete_workout(self, workout_id: int) -> None:
        await self.db.execute("DELETE FROM workout WHERE id = ?", (workout_id,))
        await self.db.commit()

    async def recent_workouts(
        self, guild_id: int, user_id: int, limit: int
    ) -> list[aiosqlite.Row]:
        async with self.db.execute(
            """SELECT * FROM workout
               WHERE guild_id = ? AND user_id = ?
               ORDER BY workout_date DESC, id DESC LIMIT ?""",
            (guild_id, user_id, limit),
        ) as cur:
            return list(await cur.fetchall())

    async def total_workouts(self, guild_id: int, user_id: int) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) AS c FROM workout WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return row["c"] if row else 0

    # ---------- activity span / streaks ----------
    async def guild_earliest_week(self, guild_id: int) -> date | None:
        """Earliest week (Sunday) with any workout or override in the guild."""
        candidates: list[date] = []
        async with self.db.execute(
            "SELECT MIN(workout_date) AS m FROM workout WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            if row and row["m"]:
                candidates.append(week_start(date.fromisoformat(row["m"])))
        async with self.db.execute(
            "SELECT MIN(week_start) AS m FROM week_override WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            if row and row["m"]:
                candidates.append(date.fromisoformat(row["m"]))
        return min(candidates) if candidates else None

    async def earliest_activity_week(
        self, guild_id: int, user_id: int
    ) -> date | None:
        """Earliest week (Sunday) with either a workout or an override row."""
        candidates: list[date] = []
        async with self.db.execute(
            "SELECT MIN(workout_date) AS m FROM workout WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            if row and row["m"]:
                candidates.append(week_start(date.fromisoformat(row["m"])))
        async with self.db.execute(
            "SELECT MIN(week_start) AS m FROM week_override WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            if row and row["m"]:
                candidates.append(date.fromisoformat(row["m"]))
        return min(candidates) if candidates else None

    async def week_status(
        self, guild_id: int, user_id: int, ws: date, current_week: date
    ) -> tuple[int, int, bool]:
        """Return (done_count, goal, hit) for the week starting on `ws`."""
        ws_iso = ws.isoformat()
        goal, _ = await self.effective_week(
            guild_id, user_id, ws_iso, current_week.isoformat()
        )
        done = len(await self.done_days(guild_id, user_id, ws_iso))
        hit = goal > 0 and done >= goal
        return done, goal, hit

    async def compute_streak(
        self, guild_id: int, user_id: int, current_week: date
    ) -> int:
        """Consecutive weeks the goal was hit, ending at (and including if
        already hit) the current week."""
        earliest = await self.earliest_activity_week(guild_id, user_id)
        if earliest is None:
            return 0

        streak = 0
        week = current_week
        first = True
        while week >= earliest:
            _, _, hit = await self.week_status(guild_id, user_id, week, current_week)
            if first:
                first = False
                if hit:
                    streak += 1
                # current week not yet hit -> in progress, keep the streak going
            else:
                if hit:
                    streak += 1
                else:
                    break
            week = week - timedelta(days=7)
        return streak

    async def best_streak_and_hits(
        self, guild_id: int, user_id: int, current_week: date
    ) -> tuple[int, int]:
        """Return (best_ever_streak, total_weeks_hit) across all history."""
        earliest = await self.earliest_activity_week(guild_id, user_id)
        if earliest is None:
            return 0, 0

        best = 0
        run = 0
        total_hits = 0
        week = earliest
        while week <= current_week:
            _, _, hit = await self.week_status(guild_id, user_id, week, current_week)
            if hit:
                run += 1
                total_hits += 1
                best = max(best, run)
            elif week != current_week:
                # don't let an in-progress current week reset the run
                run = 0
            week = week + timedelta(days=7)
        return best, total_hits

"""Shared workout-logging logic used by both the /done command and the board
button, so the two paths behave identically."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import discord

from timeutils import days_to_str, parse_days, str_to_days, today_in, week_start


@dataclass
class LogResult:
    workout_date: date  # the date the workout was logged for
    done_count: int     # distinct workout days in that workout's week
    goal: int           # goal for that workout's week
    new_day: bool       # did this create a brand-new workout day that week?
    just_hit: bool      # did this complete that week's goal for the first time?
    streak: int         # current streak (as of the real current week)
    is_current_week: bool


async def record_workout(
    bot,
    guild: discord.Guild,
    user_id: int,
    *,
    workout_date: date,
    wtype: str | None = None,
    duration_min: int | None = None,
    notes: str | None = None,
) -> LogResult:
    db = bot.db
    cfg = await db.get_guild_config(guild.id)
    tz = cfg["timezone"] if cfg else "America/Chicago"

    current_ws = week_start(today_in(tz))
    ws = week_start(workout_date)           # the week the workout belongs to
    ws_iso = ws.isoformat()
    is_current_week = ws == current_ws

    await db.ensure_user_config(guild.id, user_id)
    # Lock in the goal for this workout's week. Only refresh the snapshot to the
    # live default for the *current* week; never rewrite a past week's locked value.
    await db.ensure_week_snapshot(guild.id, user_id, ws_iso, refresh=is_current_week)

    done_before = await db.done_days(guild.id, user_id, ws_iso)
    new_day = workout_date.isoformat() not in done_before

    await db.add_workout(
        guild.id, user_id, workout_date.isoformat(), wtype, duration_min, notes
    )

    goal, _ = await db.effective_week(guild.id, user_id, ws_iso, current_ws.isoformat())
    done_count = len(done_before) + (1 if new_day else 0)
    just_hit = new_day and goal > 0 and done_count == goal

    streak = 0
    if just_hit:
        # Backfilling a past week can bridge a gap, so recompute from "now".
        streak = await db.compute_streak(guild.id, user_id, current_ws)

    # Note: the caller refreshes the board *after* posting the notification so
    # the board stays at the bottom of the channel.
    return LogResult(
        workout_date=workout_date,
        done_count=done_count,
        goal=goal,
        new_day=new_day,
        just_hit=just_hit,
        streak=streak,
        is_current_week=is_current_week,
    )


async def apply_week_override(
    bot,
    guild: discord.Guild,
    user_id: int,
    *,
    goal_days: int,
    planned_days: str | None,
) -> tuple[int, list[int]]:
    """Set an explicit override for the *current* week.

    `planned_days` is the raw user text: None keeps the existing planned days,
    an empty string clears them, otherwise it's parsed. Returns (goal, planned
    indices). Raises ValueError with a user-facing message on bad input.
    """
    if not 0 <= goal_days <= 7:
        raise ValueError("Days this week must be a number between 0 and 7.")

    db = bot.db
    cfg = await db.get_guild_config(guild.id)
    tz = cfg["timezone"] if cfg else "America/Chicago"
    ws = week_start(today_in(tz)).isoformat()

    cur_goal, cur_intended = await db.effective_week(guild.id, user_id, ws, ws)
    if planned_days is None:
        intended_str = cur_intended
    else:
        intended_str = days_to_str(parse_days(planned_days))  # may raise ValueError

    await db.set_week_override(guild.id, user_id, ws, goal_days, intended_str)
    return goal_days, str_to_days(intended_str)


async def announce_workout(
    bot,
    guild: discord.Guild,
    member: discord.abc.User,
    result: LogResult,
) -> None:
    """Post the notification message that pings the notify role."""
    db = bot.db
    cfg = await db.get_guild_config(guild.id)
    if not cfg:
        return
    # Notifications go to the configured notify channel, falling back to the
    # board channel so existing single-channel setups keep working.
    channel_id = cfg["notify_channel_id"] or cfg["board_channel_id"]
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    role_mention = ""
    allowed = discord.AllowedMentions.none()
    if cfg["notify_role_id"]:
        role = guild.get_role(cfg["notify_role_id"])
        if role is not None:
            role_mention = role.mention + " "
            allowed = discord.AllowedMentions(roles=[role])

    name = getattr(member, "display_name", None) or member.name
    if result.is_current_week:
        when = "today" if result.new_day else "again today"
        week_phrase = "this week"
    else:
        when = f"on {result.workout_date.strftime('%a, %b %d')}"
        week_phrase = "that week"
    lines = [
        f"{role_mention}\U0001f4aa **{name}** logged a workout {when}! "
        f"({result.done_count}/{result.goal} {week_phrase})"
    ]
    if result.just_hit:
        streak_txt = ""
        if result.streak > 1:
            streak_txt = f" \U0001f525 **{result.streak}-week streak!**"
        elif result.streak == 1:
            streak_txt = " \U0001f525 First week in the books!"
        goal_week = "their weekly goal" if result.is_current_week else (
            f"their goal for the week of {result.workout_date.strftime('%b %d')}"
        )
        lines.append(
            f"\U0001f389 **{name}** hit {goal_week} of "
            f"{result.goal} workouts!{streak_txt}"
        )

    await channel.send("\n".join(lines), allowed_mentions=allowed)

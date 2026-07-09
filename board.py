"""Renders and maintains the weekly board messages.

Each week gets its own board message. Within a week the message is edited in
place; when a new week starts, the previous week's board is finalized (buttons
removed) and a fresh board is posted, so the board channel becomes a running
history of past weeks."""
from __future__ import annotations

import logging
from datetime import date

import discord

log = logging.getLogger("tracker.board")

from timeutils import (
    DAY_ABBR,
    today_in,
    week_dates,
    week_start,
    str_to_days,
)

NAME_W = 13  # width of the name column in the board grid


def _display_name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    if member is not None:
        return member.display_name
    return f"user-{user_id}"


def _clip(name: str, width: int) -> str:
    if len(name) <= width:
        return name.ljust(width)
    return name[: width - 1] + "…"  # ellipsis


async def render_board_embed(
    bot,
    guild: discord.Guild,
    target_week: date | None = None,
    footer_text: str | None = None,
) -> discord.Embed:
    """Render the grid for a week. Defaults to the current week (the live board);
    pass an earlier week's Sunday to render a historical snapshot. `footer_text`
    overrides the default footer."""
    db = bot.db
    cfg = await db.get_guild_config(guild.id)
    tz = cfg["timezone"] if cfg else "America/Chicago"

    today = today_in(tz)
    current_ws = week_start(today)
    ws = target_week or current_ws
    is_current = ws == current_ws
    ws_iso = ws.isoformat()
    current_iso = current_ws.isoformat()
    dates = week_dates(ws)

    header = "User".ljust(NAME_W) + " " + " ".join(f"{a:>2}" for a in DAY_ABBR)
    header += "  Prog"

    lines: list[str] = [header]

    users = await db.list_user_configs(guild.id)
    if not users:
        lines.append("(no one has set a goal yet — run /goal)")

    for u in users:
        user_id = u["user_id"]
        goal, intended_str = await db.effective_week(
            guild.id, user_id, ws_iso, current_iso
        )
        intended = set(str_to_days(intended_str))
        done_dates = await db.done_days(guild.id, user_id, ws_iso)
        done_count = len(done_dates)

        cells: list[str] = []
        for idx, d in enumerate(dates):
            iso = d.isoformat()
            if iso in done_dates:
                mark = "#"          # worked out
            elif idx in intended and d < today:
                mark = "x"          # planned but missed
            elif idx in intended:
                mark = "o"          # planned, upcoming/today
            else:
                mark = "."          # nothing planned
            cells.append(f"{mark:>2}")

        prog = f"{done_count}/{goal}"
        row = _clip(_display_name(guild, user_id), NAME_W) + " " + " ".join(cells)
        row += f"  {prog:<5}"

        trailing = ""
        if goal > 0 and done_count >= goal:
            trailing += " ✅"  # goal hit
            streak = await db.compute_streak(guild.id, user_id, ws)
            if streak > 0:
                trailing += f" \U0001f525{streak}"
        row += trailing
        lines.append(row)

    grid = "```\n" + "\n".join(lines) + "\n```"

    legend = (
        "`#` done  ·  `o` planned  ·  `x` missed plan  •  "
        "✅ goal hit  ·  \U0001f525 week streak"
    )

    title = f"\U0001f4c5 {ws.strftime('%b %d')} – {dates[-1].strftime('%b %d, %Y')}"
    embed = discord.Embed(title=title, description=grid + "\n" + legend, color=0x2ECC71)
    if footer_text is not None:
        embed.set_footer(text=footer_text)
    elif not is_current:
        embed.set_footer(text="Viewing a past week")
    return embed


async def update_board(bot, guild: discord.Guild) -> bool:
    """Post/refresh the board. Returns True if it succeeded, else False."""
    from views import LogWorkoutView  # local import to avoid a cycle

    db = bot.db
    cfg = await db.get_guild_config(guild.id)
    if not cfg or not cfg["board_channel_id"]:
        log.info("Board not configured for guild %s (run /setup).", guild.id)
        return False

    channel = guild.get_channel(cfg["board_channel_id"])
    if not isinstance(channel, discord.TextChannel):
        log.warning(
            "Board channel %s for guild %s is missing or not a text channel.",
            cfg["board_channel_id"],
            guild.id,
        )
        return False

    perms = channel.permissions_for(guild.me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        log.warning(
            "Missing permissions in #%s: view=%s send=%s embed=%s",
            channel.name,
            perms.view_channel,
            perms.send_messages,
            perms.embed_links,
        )
        return False

    tz = cfg["timezone"] if cfg else "America/Chicago"
    current_iso = week_start(today_in(tz)).isoformat()
    embed = await render_board_embed(bot, guild)

    existing = None
    if cfg["board_message_id"]:
        try:
            existing = await channel.fetch_message(cfg["board_message_id"])
        except discord.NotFound:
            existing = None

    same_week = existing is not None and cfg["board_week"] == current_iso

    try:
        if same_week:
            # Keep the current week's board stuck to the bottom: if it's already
            # the last message, just edit it (no new message); otherwise something
            # was posted below it, so delete and re-post so it stays at the bottom.
            # channel.last_message_id is tracked from gateway events, so this needs
            # no API call and no Read Message History permission.
            last_id = channel.last_message_id
            if last_id is None or existing.id == last_id:
                await existing.edit(embed=embed, view=LogWorkoutView())
            else:
                try:
                    await existing.delete()
                except discord.HTTPException:
                    pass
                new_msg = await channel.send(
                    embed=embed, view=LogWorkoutView(), silent=True
                )
                await db.set_board_message(
                    guild.id, channel.id, new_msg.id, board_week=current_iso
                )
        else:
            # A new week started (or there's no board yet). Finalize the old
            # week's board — re-render it as a completed week and drop its
            # buttons — then post a fresh board for the new week below it.
            if existing is not None and cfg["board_week"]:
                try:
                    old_ws = date.fromisoformat(cfg["board_week"])
                    final = await render_board_embed(
                        bot,
                        guild,
                        old_ws,
                        footer_text=f"Final · week of {old_ws.strftime('%b %d')}",
                    )
                    await existing.edit(embed=final, view=None)
                except (discord.HTTPException, ValueError):
                    pass
            # silent=True: posting the new weekly board shouldn't ping anyone.
            new_msg = await channel.send(
                embed=embed, view=LogWorkoutView(), silent=True
            )
            await db.set_board_message(
                guild.id, channel.id, new_msg.id, board_week=current_iso
            )
    except discord.Forbidden:
        log.warning("Forbidden while posting board in #%s", channel.name)
        return False

    return True

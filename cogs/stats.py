"""History & metrics: /stats, /history, /week."""
from __future__ import annotations

from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from board import render_board_embed
from timeutils import (
    DAY_NAMES,
    day_index,
    format_days,
    str_to_days,
    today_in,
    week_start,
)
from weekview import WeekHistoryView


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _tz(self, guild_id: int) -> str:
        cfg = await self.bot.db.get_guild_config(guild_id)
        return cfg["timezone"] if cfg else "America/Chicago"

    @app_commands.command(
        name="stats", description="Show streaks and totals for you or another member."
    )
    @app_commands.describe(member="Whose stats to show (defaults to you).")
    @app_commands.guild_only()
    async def stats(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        target = member or interaction.user
        db = self.bot.db
        tz = await self._tz(interaction.guild_id)
        cur_week = week_start(today_in(tz))

        cfg = await db.get_user_config(interaction.guild_id, target.id)
        if cfg is None:
            await interaction.response.send_message(
                f"{target.display_name} hasn't set up a goal yet.", ephemeral=True
            )
            return

        total = await db.total_workouts(interaction.guild_id, target.id)
        streak = await db.compute_streak(interaction.guild_id, target.id, cur_week)
        best, weeks_hit = await db.best_streak_and_hits(
            interaction.guild_id, target.id, cur_week
        )
        done, goal, _ = await db.week_status(
            interaction.guild_id, target.id, cur_week, cur_week
        )

        embed = discord.Embed(
            title=f"\U0001f4ca Stats — {target.display_name}", color=0x9B59B6
        )
        embed.add_field(name="Current streak", value=f"\U0001f525 {streak} week(s)", inline=True)
        embed.add_field(name="Best streak", value=f"{best} week(s)", inline=True)
        embed.add_field(name="Weeks goal hit", value=str(weeks_hit), inline=True)
        embed.add_field(name="This week", value=f"{done}/{goal}", inline=True)
        embed.add_field(name="Total workouts", value=str(total), inline=True)
        embed.add_field(
            name="Default plan",
            value=f"{cfg['goal_days']}/wk · {format_days(str_to_days(cfg['intended_days']))}",
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="history", description="Show recent logged workouts for you or a member."
    )
    @app_commands.describe(
        member="Whose history to show (defaults to you).",
        limit="How many recent entries to show (max 25).",
    )
    @app_commands.guild_only()
    async def history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        limit: app_commands.Range[int, 1, 25] = 10,
    ) -> None:
        target = member or interaction.user
        rows = await self.bot.db.recent_workouts(
            interaction.guild_id, target.id, limit
        )
        if not rows:
            await interaction.response.send_message(
                f"No workouts logged yet for {target.display_name}.", ephemeral=True
            )
            return

        lines: list[str] = []
        for r in rows:
            d = date.fromisoformat(r["workout_date"])
            weekday = DAY_NAMES[day_index(d)][:3]
            parts = [f"**{weekday} {d.strftime('%b %d')}**"]
            if r["wtype"]:
                parts.append(r["wtype"])
            if r["duration_min"]:
                parts.append(f"{r['duration_min']}min")
            line = " · ".join(parts)
            if r["notes"]:
                line += f"\n   _{r['notes']}_"
            lines.append(line)

        embed = discord.Embed(
            title=f"\U0001f4dc Recent workouts — {target.display_name}",
            description="\n".join(lines),
            color=0x1ABC9C,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="week",
        description="Browse the board for a past week (use the buttons to navigate).",
    )
    @app_commands.describe(weeks_ago="How many weeks back to start (0 = this week).")
    @app_commands.guild_only()
    async def week(
        self,
        interaction: discord.Interaction,
        weeks_ago: app_commands.Range[int, 0, 520] = 1,
    ) -> None:
        db = self.bot.db
        tz = await self._tz(interaction.guild_id)
        current_ws = week_start(today_in(tz))
        target_ws = current_ws - timedelta(days=7 * weeks_ago)

        earliest = await db.guild_earliest_week(interaction.guild_id)
        if earliest is not None and target_ws < earliest:
            target_ws = earliest

        embed = await render_board_embed(self.bot, interaction.guild, target_ws)
        view = WeekHistoryView(
            self.bot,
            interaction.guild,
            target_ws=target_ws,
            current_ws=current_ws,
            earliest=earliest,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))

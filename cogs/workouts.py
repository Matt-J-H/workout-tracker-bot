"""Logging workouts: the /done modal path and /undo."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from datetime import date

from board import update_board
from timeutils import today_in, week_start
from views import build_workout_modal


class Workouts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="done", description="Mark today's workout complete (opens a details form)."
    )
    @app_commands.guild_only()
    async def done(self, interaction: discord.Interaction) -> None:
        modal = await build_workout_modal(self.bot, interaction.guild_id)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="undo", description="Remove the most recent workout you logged."
    )
    @app_commands.guild_only()
    async def undo(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        cfg = await db.get_guild_config(interaction.guild_id)
        tz = cfg["timezone"] if cfg else "America/Chicago"

        entry = await db.last_workout(interaction.guild_id, interaction.user.id)
        if entry is None:
            await interaction.response.send_message(
                "You have no workouts to undo.", ephemeral=True
            )
            return

        await db.delete_workout(entry["id"])
        await update_board(self.bot, interaction.guild)

        # Report progress for the week the removed workout belonged to.
        removed = date.fromisoformat(entry["workout_date"])
        current_ws = week_start(today_in(tz)).isoformat()
        ws = week_start(removed).isoformat()
        remaining = len(await db.done_days(interaction.guild_id, interaction.user.id, ws))
        goal, _ = await db.effective_week(
            interaction.guild_id, interaction.user.id, ws, current_ws
        )
        when = "today" if ws == current_ws and removed == today_in(tz) else removed.isoformat()
        week_word = "this week" if ws == current_ws else "that week"
        await interaction.response.send_message(
            f"Removed your workout from **{when}**. You're now at "
            f"**{remaining}/{goal}** {week_word}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Workouts(bot))

"""Per-user configuration: default goal, intended days, and weekly overrides."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from board import update_board
from service import apply_week_override
from timeutils import (
    days_to_str,
    format_days,
    parse_days,
    str_to_days,
    today_in,
    week_end,
    week_start,
)


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _tz(self, guild_id: int) -> str:
        cfg = await self.bot.db.get_guild_config(guild_id)
        return cfg["timezone"] if cfg else "America/Chicago"

    @app_commands.command(
        name="goal",
        description="Set your default weekly goal (days per week) and optional planned days.",
    )
    @app_commands.describe(
        days="How many days per week you want to work out.",
        planned_days="Optional days you plan to work out, e.g. 'Mon, Wed, Fri'.",
    )
    @app_commands.guild_only()
    async def goal(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 7],
        planned_days: str | None = None,
    ) -> None:
        intended_str: str | None = None
        if planned_days is not None:
            try:
                parsed = parse_days(planned_days)
            except ValueError as e:
                await interaction.response.send_message(
                    f"{e}. Try something like `Mon, Wed, Fri`.", ephemeral=True
                )
                return
            if len(parsed) > days:
                await interaction.response.send_message(
                    f"You listed {len(parsed)} planned days but your goal is {days}. "
                    "Lower the plan or raise the goal.",
                    ephemeral=True,
                )
                return
            intended_str = days_to_str(parsed)

        await self.bot.db.set_user_goal(
            interaction.guild_id, interaction.user.id, days, intended_str
        )
        cfg = await self.bot.db.get_user_config(interaction.guild_id, interaction.user.id)
        planned = format_days(str_to_days(cfg["intended_days"]))
        await update_board(self.bot, interaction.guild)
        await interaction.response.send_message(
            f"Default goal set to **{days} day(s)/week**. Planned days: **{planned}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="planned",
        description="Set your default planned days (without changing your goal number).",
    )
    @app_commands.describe(days="Days you plan to work out, e.g. 'Mon, Wed, Fri'. Use 'none' to clear.")
    @app_commands.guild_only()
    async def planned(self, interaction: discord.Interaction, days: str) -> None:
        if days.strip().lower() in {"none", "clear", "-"}:
            parsed: list[int] = []
        else:
            try:
                parsed = parse_days(days)
            except ValueError as e:
                await interaction.response.send_message(
                    f"{e}. Try `Mon, Wed, Fri` or `none`.", ephemeral=True
                )
                return
        await self.bot.db.set_user_intended(
            interaction.guild_id, interaction.user.id, days_to_str(parsed)
        )
        await update_board(self.bot, interaction.guild)
        await interaction.response.send_message(
            f"Planned days set to **{format_days(parsed)}**.", ephemeral=True
        )

    @app_commands.command(
        name="override",
        description="Override your goal for THIS week only (e.g. busy schedule).",
    )
    @app_commands.describe(
        days="Goal days for this week.",
        planned_days="Optional planned days for this week, e.g. 'Tue, Thu'.",
    )
    @app_commands.guild_only()
    async def override(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 0, 7],
        planned_days: str | None = None,
    ) -> None:
        try:
            goal, intended = await apply_week_override(
                self.bot, interaction.guild, interaction.user.id,
                goal_days=days, planned_days=planned_days,
            )
        except ValueError as e:
            await interaction.response.send_message(
                f"{e} Try something like `Tue, Thu`.", ephemeral=True
            )
            return

        await update_board(self.bot, interaction.guild)
        await interaction.response.send_message(
            f"This week's goal set to **{goal} day(s)** "
            f"(planned: **{format_days(intended)}**). Your default is unchanged.",
            ephemeral=True,
        )

    @app_commands.command(name="myprofile", description="Show your current settings.")
    @app_commands.guild_only()
    async def myprofile(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        cfg = await db.ensure_user_config(interaction.guild_id, interaction.user.id)
        tz = await self._tz(interaction.guild_id)
        ws = week_start(today_in(tz))
        we = week_end(today_in(tz))
        goal, intended = await db.effective_week(
            interaction.guild_id, interaction.user.id, ws.isoformat(), ws.isoformat()
        )
        done = len(await db.done_days(interaction.guild_id, interaction.user.id, ws.isoformat()))

        embed = discord.Embed(title="Your workout profile", color=0x3498DB)
        embed.add_field(
            name="Default goal",
            value=f"{cfg['goal_days']} day(s)/week",
            inline=True,
        )
        embed.add_field(
            name="Default planned days",
            value=format_days(str_to_days(cfg["intended_days"])),
            inline=True,
        )
        embed.add_field(
            name=f"This week ({ws.strftime('%b %d')}–{we.strftime('%b %d')})",
            value=f"{done}/{goal} done · planned {format_days(str_to_days(intended))}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Profile(bot))

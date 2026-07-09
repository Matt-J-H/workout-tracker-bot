"""Persistent UI: the "Log workout" button on the board and its modal.

The view has timeout=None and a fixed custom_id so it keeps working after the
bot restarts (registered in the bot's setup_hook via add_view)."""
from __future__ import annotations

import discord

from board import update_board
from service import announce_workout, apply_week_override, record_workout
from timeutils import (
    days_input_str,
    format_days,
    parse_workout_date,
    today_in,
    week_start,
)


async def _server_today(bot, guild_id: int):
    cfg = await bot.db.get_guild_config(guild_id)
    tz = cfg["timezone"] if cfg else "America/Chicago"
    return today_in(tz)


async def build_workout_modal(bot, guild_id: int) -> "WorkoutModal":
    """Create the modal with the Date field pre-filled with the server's today."""
    return WorkoutModal(default_date=(await _server_today(bot, guild_id)).isoformat())


async def build_override_modal(bot, guild_id: int, user_id: int) -> "OverrideModal":
    """Create the schedule modal pre-filled with this week's current settings."""
    db = bot.db
    today = await _server_today(bot, guild_id)
    ws = week_start(today).isoformat()
    goal, intended_str = await db.effective_week(guild_id, user_id, ws, ws)
    from timeutils import str_to_days

    return OverrideModal(
        default_goal=str(goal),
        default_planned=days_input_str(str_to_days(intended_str)),
    )


class WorkoutModal(discord.ui.Modal, title="Log a workout"):
    def __init__(self, default_date: str) -> None:
        super().__init__()
        # Built in __init__ (not as class attrs) so each modal gets its own date
        # default without instances sharing state.
        self.workout_date = discord.ui.TextInput(
            label="Date (yyyy-mm-dd)",
            placeholder="YYYY-MM-DD",
            default=default_date,
            required=True,
            max_length=10,
        )
        self.wtype = discord.ui.TextInput(
            label="Type (optional)",
            placeholder="e.g. Push day, Run, Yoga",
            required=False,
            max_length=100,
        )
        self.duration = discord.ui.TextInput(
            label="Duration in minutes (optional)",
            placeholder="e.g. 45",
            required=False,
            max_length=5,
        )
        self.notes = discord.ui.TextInput(
            label="Notes (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        self.add_item(self.workout_date)
        self.add_item(self.wtype)
        self.add_item(self.duration)
        self.add_item(self.notes)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This only works inside the server.", ephemeral=True
            )
            return

        bot = interaction.client
        today = await _server_today(bot, interaction.guild_id)

        try:
            wdate = parse_workout_date(self.workout_date.value, today)
        except ValueError:
            await interaction.response.send_message(
                "I couldn't read that date. Use the format **YYYY-MM-DD** "
                "(e.g. `2026-07-07`).",
                ephemeral=True,
            )
            return
        if wdate > today:
            await interaction.response.send_message(
                f"You can't log a workout for a future date. Today is "
                f"**{today.isoformat()}**.",
                ephemeral=True,
            )
            return

        duration_min: int | None = None
        if self.duration.value.strip():
            try:
                duration_min = int(self.duration.value.strip())
            except ValueError:
                await interaction.response.send_message(
                    "Duration must be a whole number of minutes.", ephemeral=True
                )
                return

        result = await record_workout(
            bot,
            interaction.guild,
            interaction.user.id,
            workout_date=wdate,
            wtype=self.wtype.value.strip() or None,
            duration_min=duration_min,
            notes=self.notes.value.strip() or None,
        )

        # Acknowledge the modal silently (no ephemeral message) so nothing is
        # left sitting below the board in the board channel. Feedback comes from
        # the public notification and the board updating the person's row.
        await interaction.response.defer()

        # Post the notification first, then re-post the board so it stays last.
        await announce_workout(bot, interaction.guild, interaction.user, result)
        await update_board(bot, interaction.guild)


class OverrideModal(discord.ui.Modal, title="Schedule this week"):
    def __init__(self, default_goal: str, default_planned: str) -> None:
        super().__init__()
        self.goal = discord.ui.TextInput(
            label="Days this week (0–7)",
            placeholder="e.g. 4",
            default=default_goal,
            required=True,
            max_length=2,
        )
        self.planned = discord.ui.TextInput(
            label="Planned days (optional)",
            placeholder="e.g. Mon, Wed, Fri  (leave blank for none)",
            default=default_planned,
            required=False,
            max_length=100,
        )
        self.add_item(self.goal)
        self.add_item(self.planned)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This only works inside the server.", ephemeral=True
            )
            return

        try:
            goal = int(self.goal.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "Days this week must be a whole number between 0 and 7.",
                ephemeral=True,
            )
            return

        # Whatever's in the field is the new plan; blank/"none" clears it.
        raw = self.planned.value.strip()
        planned_arg = "" if raw.lower() in {"", "none", "clear", "-"} else raw

        bot = interaction.client
        try:
            goal, intended = await apply_week_override(
                bot, interaction.guild, interaction.user.id,
                goal_days=goal, planned_days=planned_arg,
            )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await interaction.response.send_message(
            f"This week set to **{goal} day(s)** "
            f"(planned: **{format_days(intended)}**). Your default is unchanged.",
            ephemeral=True,
        )
        await update_board(bot, interaction.guild)


class LogWorkoutView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Log workout",
        style=discord.ButtonStyle.success,
        emoji="\U0001f4aa",
        custom_id="etb:log_workout",
    )
    async def log_workout(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        modal = await build_workout_modal(interaction.client, interaction.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Schedule",
        style=discord.ButtonStyle.secondary,
        emoji="\U0001f4c5",
        custom_id="etb:schedule",
    )
    async def schedule(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        modal = await build_override_modal(
            interaction.client, interaction.guild_id, interaction.user.id
        )
        await interaction.response.send_modal(modal)

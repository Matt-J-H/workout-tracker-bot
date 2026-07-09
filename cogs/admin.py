"""Admin/setup commands (require Manage Server)."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from board import update_board


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup",
        description="Configure the board channel, notify role, and timezone (admins).",
    )
    @app_commands.describe(
        channel="Text channel for the weekly board (defaults to this channel).",
        notify_channel="Where workout notifications post (optional; defaults to the board channel).",
        notify_role="Optional role pinged when someone logs a workout (omit to keep current).",
        timezone="IANA timezone, e.g. America/Chicago (optional, keeps current if omitted).",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        notify_channel: discord.TextChannel | None = None,
        notify_role: discord.Role | None = None,
        timezone: str | None = None,
    ) -> None:
        # Default to the channel the command was run in.
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "The board needs a regular **text channel**. Pick a text channel "
                "for the `channel` option (not a voice, forum, or category channel), "
                "or just run `/setup` inside the channel you want to use.",
                ephemeral=True,
            )
            return
        channel = target

        if timezone is not None:
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                await interaction.response.send_message(
                    f"`{timezone}` is not a valid timezone. "
                    "Use an IANA name like `America/New_York`.",
                    ephemeral=True,
                )
                return

        db = self.bot.db
        prev = await db.get_guild_config(interaction.guild_id)
        prev_channel = prev["board_channel_id"] if prev else None

        await db.upsert_guild_config(
            interaction.guild_id,
            board_channel_id=channel.id,
            notify_channel_id=notify_channel.id if notify_channel else None,
            notify_role_id=notify_role.id if notify_role else None,
            timezone_name=timezone,
        )
        # Only start a brand-new board when the board channel actually changes;
        # otherwise re-running /setup would duplicate this week's board.
        if prev_channel != channel.id:
            await db.set_board_message(interaction.guild_id, channel.id, 0)
        posted = await update_board(self.bot, interaction.guild)

        cfg = await db.get_guild_config(interaction.guild_id)
        if posted:
            board_line = f"• Board: {channel.mention} ✅ (posted)"
        else:
            perms = channel.permissions_for(interaction.guild.me)
            missing = [
                name
                for name, ok in (
                    ("View Channel", perms.view_channel),
                    ("Send Messages", perms.send_messages),
                    ("Embed Links", perms.embed_links),
                )
                if not ok
            ]
            reason = (
                f"I'm missing these permissions in {channel.mention}: "
                f"**{', '.join(missing)}**."
                if missing
                else "I couldn't post there — check my channel permissions."
            )
            board_line = (
                f"• Board channel: {channel.mention} ⚠️ **board not posted**\n"
                f"  {reason}\n"
                f"  Fix my permissions, then run `/refresh`."
            )

        notify_chan_id = cfg["notify_channel_id"] or cfg["board_channel_id"]
        notify_chan = interaction.guild.get_channel(notify_chan_id) if notify_chan_id else None
        suffix = " (same as board)" if not cfg["notify_channel_id"] else ""
        notify_chan_line = (
            f"• Notifications: {notify_chan.mention}{suffix}"
            if notify_chan
            else "• Notifications: (board channel)"
        )
        if isinstance(notify_chan, discord.TextChannel):
            np = notify_chan.permissions_for(interaction.guild.me)
            if not (np.view_channel and np.send_messages):
                notify_chan_line += " ⚠️ I can't post there — check my permissions."

        if cfg["notify_role_id"]:
            role = interaction.guild.get_role(cfg["notify_role_id"])
            notify_role_line = f"• Notify role: {role.mention if role else 'set'}"
        else:
            notify_role_line = "• Notify role: none (workout logs won't ping a role)"

        await interaction.response.send_message(
            f"✅ Config saved.\n"
            f"{board_line}\n"
            f"{notify_chan_line}\n"
            f"{notify_role_line}\n"
            f"• Timezone: `{cfg['timezone']}`\n"
            f"Everyone can now set a goal with `/goal` and log with `/done`.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="refresh", description="Re-post/refresh the weekly board (admins)."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def refresh(self, interaction: discord.Interaction) -> None:
        posted = await update_board(self.bot, interaction.guild)
        if posted:
            await interaction.response.send_message("Board refreshed.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Couldn't post the board. Run `/setup` first, and make sure I have "
                "**View Channel**, **Send Messages**, and **Embed Links** in the "
                "board channel.",
                ephemeral=True,
            )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You need the **Manage Server** permission to do that."
        elif isinstance(error, app_commands.TransformerError):
            msg = (
                "That value wasn't valid — for the board, pick a regular **text "
                "channel** (not a voice, forum, or category channel), or run "
                "`/setup` inside the channel you want to use."
            )
        else:
            msg = f"Something went wrong: {error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))

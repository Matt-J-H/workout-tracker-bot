"""Keeps the *current* week's board stuck to the bottom of the board channel.

When anything is posted in the board channel (e.g. a workout notification, if
notifications share the board channel), the current board is re-posted so it
stays the last message. Reposts are debounced to avoid rate limits, and the
board's own message is ignored so its re-post doesn't trigger another one.

Finalized past-week boards are never touched — only the live board moves."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from board import update_board

log = logging.getLogger("tracker.sticky")

DEBOUNCE_SECONDS = 3.0


class Sticky(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending: dict[int, asyncio.Task] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return

        cfg = await self.bot.db.get_guild_config(message.guild.id)
        if not cfg or cfg["board_channel_id"] != message.channel.id:
            return
        # Ignore the board message itself so our own re-post doesn't loop.
        if cfg["board_message_id"] and message.id == cfg["board_message_id"]:
            return

        self._schedule(message.guild)

    def _schedule(self, guild: discord.Guild) -> None:
        existing = self._pending.get(guild.id)
        if existing is not None and not existing.done():
            existing.cancel()
        self._pending[guild.id] = asyncio.create_task(self._reposition(guild))

    async def _reposition(self, guild: discord.Guild) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            await update_board(self.bot, guild)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - never let the listener die
            log.exception("Failed to reposition board for guild %s", guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sticky(bot))

"""Ephemeral, navigable view for browsing past weeks' boards.

Not a persistent view: it lives for one browsing session (short timeout) on an
ephemeral message, with Prev/Next buttons that re-render the grid for the
selected week."""
from __future__ import annotations

from datetime import date, timedelta

import discord

from board import render_board_embed


class WeekHistoryView(discord.ui.View):
    def __init__(
        self,
        bot,
        guild: discord.Guild,
        *,
        target_ws: date,
        current_ws: date,
        earliest: date | None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.target_ws = target_ws
        self.current_ws = current_ws
        self.earliest = earliest
        self.message: discord.InteractionMessage | None = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        # Can't go earlier than the first week with any activity...
        self.prev.disabled = self.earliest is not None and self.target_ws <= self.earliest
        # ...or later than the current week.
        self.next.disabled = self.target_ws >= self.current_ws

    async def _rerender(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        embed = await render_board_embed(self.bot, self.guild, self.target_ws)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.target_ws = self.target_ws - timedelta(days=7)
        if self.earliest is not None and self.target_ws < self.earliest:
            self.target_ws = self.earliest
        await self._rerender(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.target_ws = self.target_ws + timedelta(days=7)
        if self.target_ws > self.current_ws:
            self.target_ws = self.current_ws
        await self._rerender(interaction)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

"""Entry point for the workout-tracker Discord bot."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from board import update_board
from config import load_config
from database import Database
from views import LogWorkoutView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tracker")

COGS = ["cogs.admin", "cogs.profile", "cogs.workouts", "cogs.stats", "cogs.sticky"]


class TrackerBot(commands.Bot):
    def __init__(self, cfg):
        intents = discord.Intents.default()
        intents.members = True  # needed to resolve display names on the board
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.cfg = cfg
        self.db = Database(cfg.database_path)

    async def setup_hook(self) -> None:
        await self.db.connect()

        for ext in COGS:
            await self.load_extension(ext)

        # Register the persistent board button so it survives restarts.
        self.add_view(LogWorkoutView())

        if self.cfg.guild_id:
            guild = discord.Object(id=self.cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced slash commands to guild %s", self.cfg.guild_id)
        else:
            await self.tree.sync()
            log.info("Synced global slash commands (may take up to an hour to appear).")

        self.refresh_boards.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, self.user.id if self.user else "?")

    @tasks.loop(minutes=60)
    async def refresh_boards(self) -> None:
        """Keep boards current for week rollovers even without new activity."""
        for guild in self.guilds:
            try:
                await update_board(self, guild)
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("Failed to refresh board for guild %s", guild.id)

    @refresh_boards.before_loop
    async def _before_refresh(self) -> None:
        await self.wait_until_ready()

    async def close(self) -> None:
        await self.db.close()
        await super().close()


def main() -> None:
    cfg = load_config()
    bot = TrackerBot(cfg)
    bot.run(cfg.token, log_handler=None)


if __name__ == "__main__":
    main()

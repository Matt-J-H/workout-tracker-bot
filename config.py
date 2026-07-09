"""Loads configuration from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int | None
    timezone: str
    database_path: str


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    guild_raw = os.getenv("GUILD_ID", "").strip()
    guild_id = int(guild_raw) if guild_raw.isdigit() else None

    timezone = os.getenv("TIMEZONE", "America/Chicago").strip() or "America/Chicago"
    database_path = os.getenv("DATABASE_PATH", "data/tracker.db").strip() or "data/tracker.db"

    return Config(
        token=token,
        guild_id=guild_id,
        timezone=timezone,
        database_path=database_path,
    )

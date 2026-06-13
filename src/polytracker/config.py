"""Centralized configuration for PolyTracker.

Settings are loaded from environment variables (via ``.env``) with sensible
defaults for everything else.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Dict

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Application settings loaded from environment and defaults."""

    # ── Telegram ──────────────────────────────────────────────────────
    token: str = ""
    """Telegram bot token (from TELEGRAM_TOKEN env var)."""

    allowed_user_id: int = 0
    """Telegram user ID allowed to control the bot (from CHAT_ID env var)."""

    # ── Database ──────────────────────────────────────────────────────
    db_file: str = "polytracker.db"
    """Path to the SQLite database file."""

    # ── Monitoring ────────────────────────────────────────────────────
    check_interval: int = 3
    """Seconds between each poll of all tracked wallets."""

    close_debounce_count: int = 3
    """How many consecutive polls a position must be absent before we call it closed."""

    min_size_change: float = 1.0
    """Minimum change in share count to trigger a buy/sell alert (avoids noise)."""

    # ── API ───────────────────────────────────────────────────────────
    api_page_limit: int = 500
    """Page size for Polymarket position API."""

    api_timeout: int = 10
    """HTTP request timeout in seconds."""

    api_verify_ssl: bool = False
    """Whether to verify SSL certificates when calling Polymarket APIs.

    Polymarket's ``data-api.polymarket.com`` has a known invalid SSL
    certificate (hostname mismatch). Set the ``POLYMARKET_VERIFY_SSL``
    environment variable to ``false`` to disable verification.
    """

    proxy_url: str = ""
    """HTTP/HTTPS proxy URL for Polymarket API requests.

    Useful if Polymarket is blocked in your country. Example:
    ``http://127.0.0.1:7890`` or ``socks5://127.0.0.1:1080``.
    Set via the ``PROXY_URL`` environment variable.
    """

    # ── Display ───────────────────────────────────────────────────────
    category_emojis: Dict[str, str] = field(
        default_factory=lambda: {
            "Football": "⚽",
            "Soccer": "⚽",
            "Basketball": "🏀",
            "NBA": "🏀",
            "Esports": "🎮",
            "Gaming": "🎮",
            "Politics": "🏛️",
            "Crypto": "₿",
        }
    )
    """Mapping of category keywords to emoji prefixes shown in alerts."""

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables.

        Exits the process if ``TELEGRAM_TOKEN`` or ``CHAT_ID`` are missing.
        """
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("CHAT_ID", "")

        if not token or not chat_id:
            print("Error: TELEGRAM_TOKEN or CHAT_ID not found. Make sure .env file exists.")
            sys.exit(1)

        verify_raw = os.getenv("POLYMARKET_VERIFY_SSL", "false").lower()

        return cls(
            token=token,
            allowed_user_id=int(chat_id),
            api_verify_ssl=verify_raw not in ("false", "0", "no"),
            proxy_url=os.getenv("PROXY_URL", ""),
        )


# Global settings singleton — importers get a ready-to-use instance.
settings = Settings.from_env()

"""Entry point for PolyTracker.

Run with::

    python -m polytracker

or (after ``pip install -e .``)::

    polytracker
"""

import asyncio
import logging
import sys

from telegram.ext import ApplicationBuilder, CommandHandler

from polytracker.bot import (
    add_wallet,
    check_wallets,
    help_command,
    list_wallets,
    post_init,
    remove_wallet,
    start,
)
from polytracker.config import settings
from polytracker.db import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def main() -> None:
    """Create the bot application, register handlers, and start polling."""
    init_db()

    # Windows requires a specific event-loop policy for asyncio sub-processes.
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = ApplicationBuilder().token(settings.token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_wallet))
    app.add_handler(CommandHandler("remove", remove_wallet))
    app.add_handler(CommandHandler("list", list_wallets))

    if app.job_queue is not None:
        app.job_queue.run_repeating(
            check_wallets,
            interval=settings.check_interval,
            first=5,
        )

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

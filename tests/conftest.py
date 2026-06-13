"""Test configuration — provides dummy credentials so the config module loads."""

import os

# These are set before any test imports so that
# ``polytracker.config.Settings.from_env()`` doesn't call ``sys.exit()``
# when no real .env file is present.
os.environ.setdefault("TELEGRAM_TOKEN", "test_token_dummy")
os.environ.setdefault("CHAT_ID", "12345")

"""One-shot import: read watchlist.json and populate the SQLite database.

Run once with::

    python import_watchlist.py
"""

import json
import os
import sys

# Ensure the polytracker package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from polytracker.db import add_wallet, init_db, upsert_position

WATCHLIST_FILE = "watchlist.json"


def main() -> None:
    if not os.path.exists(WATCHLIST_FILE):
        print(f"❌ {WATCHLIST_FILE} not found.")
        sys.exit(1)

    with open(WATCHLIST_FILE, "r") as f:
        data = json.load(f)

    init_db()
    wallet_count = 0
    position_count = 0

    for address, wallet in data.items():
        name = wallet.get("name", address[:10])
        add_wallet(address, name)
        wallet_count += 1

        for asset_id, pos in wallet.get("positions", {}).items():
            upsert_position(
                address,
                asset_id,
                {
                    "size": pos.get("size", 0),
                    "avgPrice": pos.get("avgPrice", 0),
                    "title": pos.get("title", "Unknown"),
                    "outcome": pos.get("outcome", "Unknown"),
                    "slug": pos.get("slug", ""),
                    "conditionId": None,
                },
            )
            position_count += 1

    print(f"✅ Imported {wallet_count} wallets with {position_count} positions into the database.")
    print(f"   Run the bot with: python -m polytracker")


if __name__ == "__main__":
    main()

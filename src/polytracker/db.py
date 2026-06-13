"""SQLite database layer for PolyTracker.

Uses context managers for all connections so resources are never leaked.
"""

import sqlite3
from typing import Any, Dict

from polytracker.config import settings

# ── Internal helpers ──────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    """Create and return a new database connection with row-factory set."""
    conn = sqlite3.connect(settings.db_file)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema ─────────────────────────────────────────────────────────────────


def init_db() -> None:
    """Create tables (if they don't exist) and apply any missing migrations.

    Safe to call multiple times — idempotent by design.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS wallets
                     (address TEXT PRIMARY KEY, name TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS positions
                     (asset_id TEXT, address TEXT, size REAL, avg_price REAL,
                      title TEXT, outcome TEXT, slug TEXT,
                      PRIMARY KEY (asset_id, address))""")

        # Migration: add condition_id column for older databases.
        try:
            c.execute("ALTER TABLE positions ADD COLUMN condition_id TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists — safe to ignore


# ── Wallets ────────────────────────────────────────────────────────────────


def get_tracked_wallets() -> Dict[str, str]:
    """Return ``{address: display_name}`` for every tracked wallet."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT address, name FROM wallets")
        return {row["address"]: row["name"] for row in c.fetchall()}


def add_wallet(address: str, name: str) -> None:
    """Insert a new wallet or update the display name of an existing one."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO wallets (address, name) VALUES (?, ?)",
            (address, name),
        )


def remove_wallet(address: str) -> None:
    """Delete a wallet **and** all of its stored positions."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM wallets WHERE address = ?", (address,))
        c.execute("DELETE FROM positions WHERE address = ?", (address,))


# ── Positions ──────────────────────────────────────────────────────────────


def get_wallet_positions(address: str) -> Dict[str, Dict[str, Any]]:
    """Return ``{asset_id: position_data}`` for a single wallet.

    Each position dict has the keys ``size``, ``avgPrice``, ``title``,
    ``outcome``, ``slug``, and ``conditionId``.
    """
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM positions WHERE address = ?", (address,))
        positions: Dict[str, Dict[str, Any]] = {}
        for row in c.fetchall():
            positions[row["asset_id"]] = {
                "size": row["size"],
                "avgPrice": row["avg_price"],
                "title": row["title"],
                "outcome": row["outcome"],
                "slug": row["slug"],
                "conditionId": row["condition_id"],
            }
        return positions


def upsert_position(address: str, asset_id: str, data: Dict[str, Any]) -> None:
    """Insert a position, or replace it if it already exists."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT OR REPLACE INTO positions
               (asset_id, address, size, avg_price, title, outcome, slug, condition_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset_id,
                address,
                data["size"],
                data["avgPrice"],
                data["title"],
                data["outcome"],
                data["slug"],
                data.get("conditionId"),
            ),
        )


def delete_position(address: str, asset_id: str) -> None:
    """Remove a single position for a given wallet."""
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM positions WHERE address = ? AND asset_id = ?",
            (address, asset_id),
        )

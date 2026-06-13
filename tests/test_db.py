"""Tests for the database layer.

Uses a temporary SQLite file per test so no real data is affected.
"""

import os
import tempfile

import pytest

from polytracker import db


@pytest.fixture(autouse=True)
def temp_db():
    """Replace the production database with a temporary file.

    Every test gets a fresh DB, and the file is cleaned up afterwards.
    """
    import gc

    old_file = db.settings.db_file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db.settings.db_file = db_path
    db.init_db()
    yield
    db.settings.db_file = old_file
    # Force GC to release any lingering SQLite connections on Windows
    gc.collect()
    try:
        os.unlink(db_path)
    except PermissionError:
        pass  # Best-effort cleanup; temp file may persist if still locked


# ── Wallet tests ───────────────────────────────────────────────────────────


class TestWallets:
    """CRUD operations on the ``wallets`` table."""

    def test_add_and_get(self):
        db.add_wallet("0xabc123", "test_wallet")
        wallets = db.get_tracked_wallets()
        assert wallets == {"0xabc123": "test_wallet"}

    def test_add_duplicate_updates_name(self):
        db.add_wallet("0xabc", "original")
        db.add_wallet("0xabc", "updated")
        assert db.get_tracked_wallets()["0xabc"] == "updated"

    def test_remove_wallet(self):
        db.add_wallet("0xabc", "test_wallet")
        db.remove_wallet("0xabc")
        assert db.get_tracked_wallets() == {}

    def test_remove_wallet_also_removes_positions(self):
        db.add_wallet("0xabc", "test_wallet")
        db.upsert_position(
            "0xabc",
            "asset1",
            {
                "size": 100,
                "avgPrice": 0.5,
                "title": "Test",
                "outcome": "Yes",
                "slug": "test",
                "conditionId": "cond1",
            },
        )
        db.remove_wallet("0xabc")
        assert db.get_wallet_positions("0xabc") == {}

    def test_get_returns_empty_dict_when_no_wallets(self):
        assert db.get_tracked_wallets() == {}


# ── Position tests ─────────────────────────────────────────────────────────


class TestPositions:
    """CRUD operations on the ``positions`` table."""

    def test_upsert_and_get(self):
        db.add_wallet("0xabc", "test")
        data = {
            "size": 100.0,
            "avgPrice": 0.5,
            "title": "Will it work?",
            "outcome": "Yes",
            "slug": "will-it-work",
            "conditionId": "cond1",
        }
        db.upsert_position("0xabc", "asset1", data)
        positions = db.get_wallet_positions("0xabc")
        assert "asset1" in positions
        assert positions["asset1"]["size"] == 100.0
        assert positions["asset1"]["avgPrice"] == 0.5

    def test_upsert_updates_existing(self):
        db.add_wallet("0xabc", "test")
        db.upsert_position(
            "0xabc",
            "asset1",
            {
                "size": 100,
                "avgPrice": 0.5,
                "title": "T",
                "outcome": "Y",
                "slug": "t",
                "conditionId": "c1",
            },
        )
        db.upsert_position(
            "0xabc",
            "asset1",
            {
                "size": 200,
                "avgPrice": 0.6,
                "title": "T",
                "outcome": "Y",
                "slug": "t",
                "conditionId": "c1",
            },
        )
        assert db.get_wallet_positions("0xabc")["asset1"]["size"] == 200.0
        assert db.get_wallet_positions("0xabc")["asset1"]["avgPrice"] == 0.6

    def test_delete_position(self):
        db.add_wallet("0xabc", "test")
        db.upsert_position(
            "0xabc",
            "asset1",
            {
                "size": 100,
                "avgPrice": 0.5,
                "title": "T",
                "outcome": "Y",
                "slug": "t",
                "conditionId": "c1",
            },
        )
        db.delete_position("0xabc", "asset1")
        assert db.get_wallet_positions("0xabc") == {}

    def test_get_empty_for_unknown_wallet(self):
        assert db.get_wallet_positions("0xnonexistent") == {}

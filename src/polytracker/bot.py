"""Telegram bot command handlers and wallet-monitoring logic."""

import asyncio
import logging
from typing import Any, Dict

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ContextTypes

from polytracker import api as api_client
from polytracker import db
from polytracker.config import settings

logger = logging.getLogger(__name__)

# Debounce tracker: maps "address_assetId" -> consecutive poll absences.
# When the count reaches ``close_debounce_count`` the position is declared
# closed and we send an alert.
_pending_deletes: Dict[str, int] = {}


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/start`` — verify the bot is alive."""
    if update.message is not None:
        await update.message.reply_text("🤖 **PolyTracker Ready**")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/help`` — show available commands."""
    if update.message is not None:
        await update.message.reply_text(
            "📚 **PolyTracker**\n"
            "`/add <address> <name>` — Add a wallet to track\n"
            "`/remove <name>` — Remove a wallet\n"
            "`/list` — List tracked wallets"
        )


async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/add <0x...> <name>`` — start tracking a new wallet."""
    if update.effective_user is None or update.effective_user.id != settings.allowed_user_id:
        return

    args = context.args
    if args is None or len(args) < 2:
        if update.message is not None:
            await update.message.reply_text("Usage: `/add 0x... Name`")
        return

    address = args[0]
    name = " ".join(args[1:])

    msg = await update.message.reply_text(f"⏳ Syncing **{name}**...")

    # Run the blocking HTTP sync in a thread executor so the async loop
    # isn't blocked.
    all_positions = await asyncio.get_running_loop().run_in_executor(
        None,
        api_client.fetch_positions_blocking,
        address,
    )

    db.add_wallet(address, name)

    for pos in all_positions:
        asset = pos.get("asset", pos.get("conditionId"))
        if asset:
            data = {
                "size": float(pos["size"]),
                "avgPrice": float(pos.get("avgPrice", 0)),
                "title": pos.get("title", "Unknown"),
                "outcome": pos.get("outcome", "Unknown"),
                "slug": pos.get("slug", ""),
                "conditionId": pos.get("conditionId", ""),
            }
            db.upsert_position(address, asset, data)

    if msg is not None:
        await msg.edit_text(f"✅ Added **{name}** ({len(all_positions)} bets synced).")


async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/remove <name>`` — stop tracking a wallet."""
    if update.effective_user is None or update.effective_user.id != settings.allowed_user_id:
        return

    args = context.args or []
    query = " ".join(args).lower()
    wallets = db.get_tracked_wallets()

    for addr, name in wallets.items():
        if query in name.lower() or query == addr.lower():
            db.remove_wallet(addr)

            # Purge any pending-delete entries for this address
            keys_to_clear = [k for k in _pending_deletes if k.startswith(addr)]
            for k in keys_to_clear:
                del _pending_deletes[k]

            if update.message is not None:
                await update.message.reply_text(f"🗑️ Removed **{name}**.")
            return

    if update.message is not None:
        await update.message.reply_text("❌ Not found.")


async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/list`` — show every tracked wallet."""
    if update.message is None:
        return
    wallets = db.get_tracked_wallets()
    msg = "📋 **Tracked Wallets:**\n"
    for addr, name in wallets.items():
        msg += f"• [{name}](https://polymarket.com/profile/{addr})\n"
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def post_init(application: Application) -> None:
    """Register the bot command menu after startup."""
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start"),
            BotCommand("add", "Add Wallet"),
            BotCommand("remove", "Remove Wallet"),
            BotCommand("list", "List Wallets"),
        ]
    )


# ═══════════════════════════════════════════════════════════════════════════
# Wallet monitoring (polling loop)
# ═══════════════════════════════════════════════════════════════════════════


async def check_wallets(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll all tracked wallets and fire alerts for any changes."""
    wallets = db.get_tracked_wallets()
    async with httpx.AsyncClient(
        verify=settings.api_verify_ssl, proxy=settings.proxy_url or None
    ) as client:
        tasks = [
            _process_wallet(client, context, address, name) for address, name in wallets.items()
        ]
        await asyncio.gather(*tasks)


async def _process_wallet(
    client: httpx.AsyncClient,
    context: ContextTypes.DEFAULT_TYPE,
    address: str,
    name: str,
) -> None:
    """Compare live API positions against stored data and alert on differences."""
    known_positions = db.get_wallet_positions(address)
    current_positions = await api_client.fetch_positions(client, address)

    if current_positions is None:
        return  # API error already logged — nothing we can do this cycle.

    clean_name = name.replace("_", " ")
    user_link = f"https://polymarket.com/profile/{address}"
    name_linked = f"[{clean_name}]({user_link})"

    current_asset_ids: set = set()

    # ── 1. Process every position the API returned ─────────────────────
    for pos in current_positions:
        asset_id = pos.get("asset", pos.get("conditionId"))
        if not asset_id:
            continue

        current_asset_ids.add(asset_id)

        # Cancel any pending-delete for this position — it's still alive.
        _pending_deletes.pop(f"{address}_{asset_id}", None)

        new_size = float(pos["size"])
        title = pos.get("title", "Unknown Event")
        outcome = pos.get("outcome", pos.get("outcomeLabel", "Unknown"))
        slug = pos.get("slug", "")
        new_avg_price = float(pos.get("avgPrice", 0))
        event_id = pos.get("eventId")
        condition_id = pos.get("conditionId")
        current_total_value = new_size * new_avg_price

        # Category label (with emoji)
        category = await api_client.get_event_category(client, event_id)
        display_title = f"**{category}** | {title}" if category else title

        # Old data (if any)
        old_data = known_positions.get(asset_id)
        old_size = old_data["size"] if old_data else 0.0
        old_avg_price = old_data["avgPrice"] if old_data else 0.0

        new_data_block = {
            "size": new_size,
            "avgPrice": new_avg_price,
            "title": title,
            "outcome": outcome,
            "slug": slug,
            "conditionId": condition_id,
        }

        market_link = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
        keyboard = [[InlineKeyboardButton("🚀 View Market", url=market_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # ── Case A: Brand-new position ──────────────────────────────
        if asset_id not in known_positions:
            msg = (
                f"✅ **NEW BET: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Value: ${current_total_value:,.2f}**\n"
                f"Size: {new_size:,.2f} Shares\n"
                f"Avg Price: {new_avg_price:.2f}¢"
            )
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            db.upsert_position(address, asset_id, new_data_block)

        # ── Case B: Increased position ──────────────────────────────
        elif new_size > old_size + settings.min_size_change:
            diff = new_size - old_size
            cost_now = new_size * new_avg_price
            cost_before = old_size * old_avg_price
            added_value = cost_now - cost_before

            estimated_trade_price = new_avg_price
            if diff > 0:
                price = added_value / diff
                if price >= 0:
                    estimated_trade_price = price

            msg = (
                f"📈 **INCREASED: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Added: ${added_value:,.2f}**\n"
                f"💰 **Position Total: ${current_total_value:,.2f}**\n"
                f"Shares: +{diff:,.2f}\n"
                f"Trade Price: ~{estimated_trade_price:.2f}¢\n"
                f"(Avg: {old_avg_price:.2f}¢ ➜ {new_avg_price:.2f}¢)"
            )
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            db.upsert_position(address, asset_id, new_data_block)

        # ── Case C: Decreased (partial sell) ────────────────────────
        elif new_size < old_size - settings.min_size_change:
            diff = old_size - new_size

            trades, _ = await api_client.fetch_recent_activity(client, address)
            trade_price = new_avg_price
            found_trade = False
            for t in trades or ():
                if t.get("asset") == asset_id and t.get("side") == "SELL":
                    trade_price = float(t.get("price", 0))
                    found_trade = True
                    break

            sold_value = diff * trade_price

            pnl_msg = ""
            if found_trade and old_avg_price > 0:
                pnl = (trade_price - old_avg_price) * diff
                pnl_percent = ((trade_price - old_avg_price) / old_avg_price) * 100
                symbol = "+" if pnl >= 0 else "-"
                pnl_msg = f"\n💵 **Realized PnL: {symbol}${abs(pnl):,.2f} ({pnl_percent:+.2f}%)**"

            msg = (
                f"📉 **SOLD: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Sold Value: ${sold_value:,.2f}**\n"
                f"💰 **Position Total: ${current_total_value:,.2f}**"
                f"{pnl_msg}\n"
                f"Shares: -{diff:,.2f}\n"
                f"Sell Price: {trade_price:.2f}¢"
            )
            await context.bot.send_message(
                chat_id=settings.allowed_user_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            db.upsert_position(address, asset_id, new_data_block)

        # ── Case D: Negligible change — just persist silently ───────
        else:
            db.upsert_position(address, asset_id, new_data_block)

    # ── 2. Detect closed positions (with debounce) ──────────────────
    for asset_id, old_data in known_positions.items():
        if asset_id in current_asset_ids:
            continue

        delete_key = f"{address}_{asset_id}"
        _pending_deletes[delete_key] = _pending_deletes.get(delete_key, 0) + 1

        if _pending_deletes[delete_key] >= settings.close_debounce_count:
            await _handle_closed_position(
                client,
                context,
                address,
                name,
                asset_id,
                old_data,
            )
            del _pending_deletes[delete_key]


async def _handle_closed_position(
    client: httpx.AsyncClient,
    context: ContextTypes.DEFAULT_TYPE,
    address: str,
    name: str,
    asset_id: str,
    old_data: Dict[str, Any],
) -> None:
    """Send a "position closed" alert and remove the record from the DB.

    Called after the position has been absent from the API for
    ``close_debounce_count`` consecutive polls.
    """
    title = old_data.get("title", "Unknown Event")
    outcome = old_data.get("outcome", "Unknown")
    slug = old_data.get("slug", "")
    condition_id = old_data.get("conditionId", "")

    trades, activity = await api_client.fetch_recent_activity(client, address)

    trade_price = 0.0
    exit_type = "Expired / Lost"
    found_exit = False

    # Check 1: Did they sell?
    for t in trades or ():
        if t.get("asset") == asset_id and t.get("side") == "SELL":
            trade_price = float(t.get("price", 0))
            exit_type = "Sold All"
            found_exit = True
            break

    # Check 2: Did they redeem?
    if not found_exit:
        for a in activity or ():
            if a.get("type") == "REDEEM" and a.get("conditionId") == condition_id:
                usdc_payout = float(a.get("usdcSize", 0))
                redeemed_size = float(a.get("size", 0))
                trade_price = (usdc_payout / redeemed_size) if redeemed_size > 0 else 0.0

                if trade_price > 0.9:
                    trade_price = 1.00
                    exit_type = "Redeemed (Won)"
                else:
                    trade_price = 0.00
                    exit_type = "Redeemed (Lost)"
                found_exit = True
                break

    if not found_exit:
        trade_price = 0.0
        exit_type = "Expired (Lost)"

    # Compute PnL
    pnl_msg = ""
    old_avg = old_data.get("avgPrice", 0.0)
    size_closed = old_data.get("size", 0.0)

    if old_avg > 0:
        pnl = (trade_price - old_avg) * size_closed
        pnl_percent = -100.0 if trade_price == 0 else ((trade_price - old_avg) / old_avg) * 100
        symbol = "+" if pnl >= 0 else "-"
        pnl_msg = f"\n💵 **Closed PnL: {symbol}${abs(pnl):,.2f} ({pnl_percent:+.2f}%)**"

    market_link = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
    keyboard = [[InlineKeyboardButton("👀 View Market", url=market_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    clean_name = name.replace("_", " ")
    user_link = f"https://polymarket.com/profile/{address}"
    name_linked = f"[{clean_name}]({user_link})"

    msg = (
        f"🚪 **POSITION CLOSED: {name_linked}**\n\n"
        f"Event: {title}\n"
        f"Pick: **{outcome}**"
        f"{pnl_msg}\n"
        f"Action: {exit_type}\n"
        f"Exit Price: ${trade_price:.2f}"
    )
    await context.bot.send_message(
        chat_id=settings.allowed_user_id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    db.delete_position(address, asset_id)

import logging
import json
import asyncio
import os
import sys
from dotenv import load_dotenv
import requests
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Application

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.getenv("CHAT_ID")

if not TOKEN or not ALLOWED_USER_ID:
    print("Error: TOKEN or CHAT_ID not found. Make sure .env file exists.")
    sys.exit(1)

ALLOWED_USER_ID = int(ALLOWED_USER_ID)
DATA_FILE = "watchlist.json"
CHECK_INTERVAL = 30 # Seconds between checks

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- DATA MANAGER ---
def load_data():
    """Loads the watchlist from a JSON file."""
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    """Saves the watchlist to a JSON file."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Global Watchlist variable (Loaded on startup)
watchlist = load_data()

# --- POLYMARKET API ---
def fetch_positions(wallet):
    url = "https://data-api.polymarket.com/positions"
    params = {"user": wallet, "sortBy": "CURRENT", "sortDirection": "DESC"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"API Error for {wallet}: {e}")
        return None

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **PolyTracker Ready!**\n\n"
        "Use `/help` to see how to use this bot.\n\n"
        "Quick Commands:\n"
        "`/add <address> <name>`\n"
        "`/remove <name>`\n"
        "`/list`",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **How to use PolyTracker**\n\n"
        "1. **Find a Trader:** Go to Polymarket, find a user you want to copy (e.g., from the Leaderboard), and copy their 0x wallet address from the URL.\n"
        "2. **Add to Watchlist:**\n"
        "   Use: `/add <address> <name>`\n"
        "   Example: `/add 0x8f0... TrumpWhale`\n\n"
        "3. **Receive Alerts:**\n"
        "   The bot checks every 60 seconds. You will receive alerts for:\n"
        "   ✅ **New Bets**\n"
        "   📈 **Increased Position**\n"
        "   📉 **Decreased Position (Sold)**\n"
        "   🚪 **Position Closed (Sold All/Redeemed)**\n\n"
        "🛠 **All Commands:**\n"
        "`/add <address> <name>` - Start tracking a wallet\n"
        "`/remove <name>` - Stop tracking a wallet\n"
        "`/list` - See currently tracked wallets\n"
        "`/help` - Show this guide",
        parse_mode='Markdown'
    )

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Security check
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/add 0x123... WhaleName`", parse_mode='Markdown')
        return

    address = args[0]
    name = " ".join(args[1:])

    if not address.startswith("0x") or len(address) < 10:
        await update.message.reply_text("❌ Invalid wallet address.")
        return

    # Add to memory and save
    watchlist[address] = {"name": name, "positions": {}}
    
    # Initialize positions immediately to avoid alert spam on first run
    msg = await update.message.reply_text(f"⏳ Initializing data for **{name}**...")
    positions = fetch_positions(address)
    
    if positions:
        for pos in positions:
            # Safely get asset ID
            asset = pos.get('asset', pos.get('conditionId'))
            if asset:
                # Store comprehensive data for smarter alerts
                watchlist[address]["positions"][asset] = {
                    "size": float(pos['size']),
                    "avgPrice": float(pos.get('avgPrice', 0)),
                    "title": pos.get('title', 'Unknown Event'),
                    "outcome": pos.get('outcome', pos.get('outcomeLabel', 'Unknown')),
                    "slug": pos.get('slug', '')
                }
    
    save_data(watchlist)
    await msg.edit_text(f"✅ Added **{name}** (`{address[:6]}...`) to tracker.", parse_mode='Markdown')

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID: return

    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/remove <name>` or `/remove <0xAddress>`", parse_mode='Markdown')
        return

    target_key = None
    for addr, data in watchlist.items():
        if query.lower() in data['name'].lower() or query == addr:
            target_key = addr
            break

    if target_key:
        name = watchlist[target_key]['name']
        del watchlist[target_key]
        save_data(watchlist)
        await update.message.reply_text(f"🗑️ Removed **{name}** from tracker.", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Could not find wallet matching '{query}'.")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not watchlist:
        await update.message.reply_text("📭 No wallets being tracked.")
        return

    msg = "📋 **Tracked Wallets:**\n"
    for addr, data in watchlist.items():
        user_link = f"https://polymarket.com/profile/{addr}"
        msg += f"• [**{data['name']}**]({user_link}): `{addr[:8]}...`\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- BACKGROUND TASK (The Tracker) ---
async def check_wallets(context: ContextTypes.DEFAULT_TYPE):
    # Iterate over a COPY of keys to avoid issues if list changes during loop
    for address in list(watchlist.keys()):
        data = watchlist[address]
        name = data['name']
        
        # FEATURE: Clickable User Name (FIXED FORMATTING)
        # We replace underscore with space in name to prevent markdown errors
        clean_name = name.replace("_", " ") 
        user_link = f"https://polymarket.com/profile/{address}"
        name_linked = f"[{clean_name}]({user_link})" # Removed the **asterisks** here
        
        known_positions = data['positions']
        current_positions = fetch_positions(address)
        
        # If API fails, skip this wallet for now
        if current_positions is None: 
            continue

        current_asset_ids = set()

        # Check for updates
        for pos in current_positions:
            asset_id = pos.get('asset', pos.get('conditionId'))
            if not asset_id: continue

            current_asset_ids.add(asset_id)

            new_size = float(pos['size'])
            title = pos.get('title', 'Unknown Event')
            outcome = pos.get('outcome', pos.get('outcomeLabel', 'Unknown'))
            slug = pos.get('slug', '')
            new_avg_price = float(pos.get('avgPrice', 0)) # Current Average Price

            # --- HANDLE DATA MIGRATION (Float -> Dict) ---
            old_data = known_positions.get(asset_id)
            old_size = 0.0
            old_avg_price = 0.0

            if old_data is not None:
                if isinstance(old_data, (int, float)):
                    old_size = float(old_data)
                elif isinstance(old_data, dict):
                    old_size = float(old_data.get('size', 0.0))
                    old_avg_price = float(old_data.get('avgPrice', 0.0))
            
            # Prepare new data block to save
            new_data_block = {
                "size": new_size,
                "avgPrice": new_avg_price,
                "title": title,
                "outcome": outcome,
                "slug": slug
            }

            market_link = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"

            # Logic: New Position
            if asset_id not in known_positions:
                msg = (
                    f"✅ **NEW BET: {name_linked}**\n\n"
                    f"Event: {title}\n"
                    f"Pick: **{outcome}**\n"
                    f"Size: {new_size:.2f} Shares\n"
                    f"Avg Price: {new_avg_price:.2f}¢\n\n"
                    f"[View Market]({market_link})"
                )
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown')
                known_positions[asset_id] = new_data_block
                save_data(watchlist)

            # Logic: Increased Position (Buffer +1.0)
            elif new_size > old_size + 1.0:
                diff = new_size - old_size
                
                # FEATURE: Calculate Estimated Trade Price
                estimated_trade_price = 0.0
                try:
                    cost_now = new_size * new_avg_price
                    cost_before = old_size * old_avg_price
                    if diff > 0:
                        estimated_trade_price = (cost_now - cost_before) / diff
                        if estimated_trade_price < 0: estimated_trade_price = 0
                except:
                    estimated_trade_price = new_avg_price

                msg = (
                    f"📈 **INCREASED: {name_linked}**\n\n"
                    f"Event: {title}\n"
                    f"Pick: **{outcome}**\n"
                    f"Added: +{diff:.2f} Shares\n"
                    f"Trade Price: ~{estimated_trade_price:.2f}¢\n"
                    f"(Avg: {old_avg_price:.2f}¢ ➜ {new_avg_price:.2f}¢)\n\n"
                    f"[View Market]({market_link})"
                )
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown')
                known_positions[asset_id] = new_data_block
                save_data(watchlist)

            # Logic: Decreased Position (Sold/Reduced)
            elif new_size < old_size - 1.0:
                diff = old_size - new_size
                msg = (
                    f"📉 **SOLD / DECREASED: {name_linked}**\n\n"
                    f"Event: {title}\n"
                    f"Pick: **{outcome}**\n"
                    f"Sold: -{diff:.2f} Shares\n\n"
                    f"[View Market]({market_link})"
                )
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown')
                known_positions[asset_id] = new_data_block
                save_data(watchlist)
            
            else:
                known_positions[asset_id] = new_data_block

        # Logic: Position Completely Closed
        for asset_id in list(known_positions.keys()):
            if asset_id not in current_asset_ids:
                old_data = known_positions[asset_id]
                
                if isinstance(old_data, (int, float)):
                    t_title, t_outcome, t_slug = "Unknown Event (Legacy Data)", "Unknown", ""
                else:
                    t_title = old_data.get('title', 'Unknown Event')
                    t_outcome = old_data.get('outcome', 'Unknown')
                    t_slug = old_data.get('slug', '')

                market_link = f"https://polymarket.com/event/{t_slug}" if t_slug else "https://polymarket.com"
                
                msg = (
                    f"🚪 **POSITION CLOSED: {name_linked}**\n\n"
                    f"Event: {t_title}\n"
                    f"Pick: **{t_outcome}**\n"
                    f"Action: Sold All or Redeemed\n\n"
                    f"[View Market]({market_link})"
                )
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown')
                
                del known_positions[asset_id]
                save_data(watchlist)
        
        await asyncio.sleep(1) 

# --- POST INIT (Sets the Menu) ---
async def post_init(application: Application):
    """Sets the button menu when the bot starts."""
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help guide"),
        BotCommand("add", "Track a wallet"),
        BotCommand("remove", "Stop tracking a wallet"),
        BotCommand("list", "List tracked wallets"),
    ])

# --- MAIN ---
if __name__ == '__main__':
    # KEY FIX FOR WINDOWS + PYTHON 3.13
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_wallet))
    app.add_handler(CommandHandler("remove", remove_wallet))
    app.add_handler(CommandHandler("list", list_wallets))

    job_queue = app.job_queue
    job_queue.run_repeating(check_wallets, interval=CHECK_INTERVAL, first=5)

    print("🤖 Bot is running...")
    app.run_polling()
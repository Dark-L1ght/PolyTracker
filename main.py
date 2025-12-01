import logging
import json
import asyncio
import os
import sys
import sqlite3
from dotenv import load_dotenv
import httpx 
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Application

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.getenv("CHAT_ID")

if not TOKEN or not ALLOWED_USER_ID:
    print("Error: TOKEN or CHAT_ID not found. Make sure .env file exists.")
    sys.exit(1)

ALLOWED_USER_ID = int(ALLOWED_USER_ID)
DB_FILE = "polytracker.db"
CHECK_INTERVAL = 10 

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Global trackers
pending_deletes = {}
category_cache = {} # Cache for event categories (EventID -> Category Name)

# --- DATABASE MANAGER (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS wallets
                 (address TEXT PRIMARY KEY, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions
                 (asset_id TEXT, address TEXT, size REAL, avg_price REAL, 
                  title TEXT, outcome TEXT, slug TEXT,
                  PRIMARY KEY (asset_id, address))''')
    conn.commit()
    conn.close()

def get_tracked_wallets():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT address, name FROM wallets")
    data = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return data

def get_wallet_positions(address):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT asset_id, size, avg_price, title, outcome, slug FROM positions WHERE address=?", (address,))
    positions = {}
    for row in c.fetchall():
        positions[row[0]] = {
            "size": row[1],
            "avgPrice": row[2],
            "title": row[3],
            "outcome": row[4],
            "slug": row[5]
        }
    conn.close()
    return positions

def upsert_position(address, asset_id, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO positions 
                 (asset_id, address, size, avg_price, title, outcome, slug)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (asset_id, address, data['size'], data['avgPrice'], 
               data['title'], data['outcome'], data['slug']))
    conn.commit()
    conn.close()

def delete_position(address, asset_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM positions WHERE address=? AND asset_id=?", (address, asset_id))
    conn.commit()
    conn.close()

def add_wallet_db(address, name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO wallets (address, name) VALUES (?, ?)", (address, name))
    conn.commit()
    conn.close()

def remove_wallet_db(address):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM wallets WHERE address=?", (address,))
    c.execute("DELETE FROM positions WHERE address=?", (address,))
    conn.commit()
    conn.close()

init_db()

# --- ASYNC API HELPER ---
async def fetch_positions(client, wallet):
    url = "https://data-api.polymarket.com/positions"
    params = {"user": wallet, "sortBy": "CURRENT", "sortDirection": "DESC"}
    try:
        r = await client.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"API Error for {wallet}: {e}")
        return None

async def get_event_category(client, event_id):
    """Fetches the category (Sport/Topic) for an event. Caches results."""
    if not event_id: return ""
    if event_id in category_cache:
        return category_cache[event_id]
    
    url = f"https://gamma-api.polymarket.com/events/{event_id}"
    try:
        r = await client.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if 'markets' in data and len(data['markets']) > 0:
                cat = data['markets'][0].get('category', '')
                if cat:
                    if "Football" in cat or "Soccer" in cat: cat = f"⚽ {cat}"
                    elif "Basketball" in cat or "NBA" in cat: cat = f"🏀 {cat}"
                    elif "Esports" in cat or "Gaming" in cat: cat = f"🎮 {cat}"
                    elif "Politics" in cat: cat = f"🏛️ {cat}"
                    elif "Crypto" in cat: cat = f"₿ {cat}"
                    
                    category_cache[event_id] = cat
                    return cat
    except:
        pass
    return ""

# --- PROCESS SINGLE WALLET ---
async def process_wallet(client, context, address, name):
    known_positions = get_wallet_positions(address)
    current_positions = await fetch_positions(client, address)
    
    if current_positions is None: 
        return

    clean_name = name.replace("_", " ") 
    user_link = f"https://polymarket.com/profile/{address}"
    name_linked = f"[{clean_name}]({user_link})"
    
    current_asset_ids = set()

    # 1. PROCESS ACTIVE
    for pos in current_positions:
        asset_id = pos.get('asset', pos.get('conditionId'))
        if not asset_id: continue

        current_asset_ids.add(asset_id)
        
        # Debounce reset
        delete_key = f"{address}_{asset_id}"
        if delete_key in pending_deletes:
            del pending_deletes[delete_key]

        new_size = float(pos['size'])
        title = pos.get('title', 'Unknown Event')
        outcome = pos.get('outcome', pos.get('outcomeLabel', 'Unknown'))
        slug = pos.get('slug', '')
        new_avg_price = float(pos.get('avgPrice', 0))
        event_id = pos.get('eventId')

        # Fetch Category (Lazy load)
        category = await get_event_category(client, event_id)
        if category:
            display_title = f"**{category}** | {title}"
        else:
            display_title = title

        old_data = known_positions.get(asset_id)
        old_size = 0.0
        old_avg_price = 0.0

        if old_data:
            old_size = old_data['size']
            old_avg_price = old_data['avgPrice']
        
        new_data_block = {
            "size": new_size,
            "avgPrice": new_avg_price,
            "title": title,
            "outcome": outcome,
            "slug": slug
        }

        market_link = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
        
        keyboard = [[InlineKeyboardButton("🚀 View Market", url=market_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Logic: New Position
        if asset_id not in known_positions:
            total_value = new_size * new_avg_price
            msg = (
                f"✅ **NEW BET: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Value: ${total_value:,.2f}**\n"
                f"Size: {new_size:,.2f} Shares\n"
                f"Avg Price: {new_avg_price:.2f}¢"
            )
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown', 
                reply_markup=reply_markup, disable_web_page_preview=True
            )
            upsert_position(address, asset_id, new_data_block)

        # Logic: Increased
        elif new_size > old_size + 1.0:
            diff = new_size - old_size
            estimated_trade_price = new_avg_price
            
            # Calculate Value of the ADDED amount
            added_value = 0.0
            try:
                cost_now = new_size * new_avg_price
                cost_before = old_size * old_avg_price
                added_value = cost_now - cost_before
                if diff > 0:
                    estimated_trade_price = added_value / diff
                    if estimated_trade_price < 0: estimated_trade_price = 0
            except: pass

            msg = (
                f"📈 **INCREASED: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Added: ${added_value:,.2f}**\n"
                f"Shares: +{diff:,.2f}\n"
                f"Trade Price: ~{estimated_trade_price:.2f}¢\n"
                f"(Avg: {old_avg_price:.2f}¢ ➜ {new_avg_price:.2f}¢)"
            )
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown', 
                reply_markup=reply_markup, disable_web_page_preview=True
            )
            upsert_position(address, asset_id, new_data_block)

        # Logic: Decreased
        elif new_size < old_size - 1.0:
            diff = old_size - new_size
            # Estimate sold value based on current price
            sold_value = diff * new_avg_price 
            
            msg = (
                f"📉 **SOLD: {name_linked}**\n\n"
                f"Event: {display_title}\n"
                f"Pick: **{outcome}**\n"
                f"💰 **Sold Value: ~${sold_value:,.2f}**\n"
                f"Shares: -{diff:,.2f}"
            )
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown', 
                reply_markup=reply_markup, disable_web_page_preview=True
            )
            upsert_position(address, asset_id, new_data_block)
        
        else:
            upsert_position(address, asset_id, new_data_block)

    # 2. PROCESS CLOSED (Debounced)
    for asset_id, old_data in known_positions.items():
        if asset_id not in current_asset_ids:
            delete_key = f"{address}_{asset_id}"
            pending_deletes[delete_key] = pending_deletes.get(delete_key, 0) + 1
            
            if pending_deletes[delete_key] >= 3:
                t_title = old_data.get('title', 'Unknown Event')
                t_outcome = old_data.get('outcome', 'Unknown')
                t_slug = old_data.get('slug', '')
                
                market_link = f"https://polymarket.com/event/{t_slug}" if t_slug else "https://polymarket.com"
                keyboard = [[InlineKeyboardButton("👀 View Market", url=market_link)]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg = (
                    f"🚪 **POSITION CLOSED: {name_linked}**\n\n"
                    f"Event: {t_title}\n"
                    f"Pick: **{t_outcome}**\n"
                    f"Action: Sold All or Redeemed"
                )
                await context.bot.send_message(
                    chat_id=ALLOWED_USER_ID, text=msg, parse_mode='Markdown', 
                    reply_markup=reply_markup, disable_web_page_preview=True
                )
                delete_position(address, asset_id)
                del pending_deletes[delete_key]

# --- MAIN TRACKER LOOP ---
async def check_wallets(context: ContextTypes.DEFAULT_TYPE):
    wallets = get_tracked_wallets()
    async with httpx.AsyncClient() as client:
        tasks = []
        for address, name in wallets.items():
            tasks.append(process_wallet(client, context, address, name))
        await asyncio.gather(*tasks)

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 **PolyTracker Ready (SQLite + Categories + $$$)**")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 **PolyTracker**\n`/add <addr> <name>`\n`/remove <name>`\n`/list`")

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/add 0x... Name`")
        return
    address = args[0]
    name = " ".join(args[1:])
    
    msg = await update.message.reply_text(f"⏳ Syncing **{name}**...")
    
    try:
        r = requests.get("https://data-api.polymarket.com/positions", 
                         params={"user": address, "sortBy": "CURRENT", "sortDirection": "DESC"})
        positions = r.json()
    except:
        positions = []

    add_wallet_db(address, name)
    if positions:
        for pos in positions:
            asset = pos.get('asset', pos.get('conditionId'))
            if asset:
                data = {
                    "size": float(pos['size']),
                    "avgPrice": float(pos.get('avgPrice', 0)),
                    "title": pos.get('title', 'Unknown'),
                    "outcome": pos.get('outcome', 'Unknown'),
                    "slug": pos.get('slug', '')
                }
                upsert_position(address, asset, data)
    
    await msg.edit_text(f"✅ Added **{name}**.")

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID: return
    query = " ".join(context.args).lower()
    wallets = get_tracked_wallets()
    for addr, name in wallets.items():
        if query in name.lower() or query == addr.lower():
            remove_wallet_db(addr)
            await update.message.reply_text(f"🗑️ Removed **{name}**.")
            return
    await update.message.reply_text("❌ Not found.")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = get_tracked_wallets()
    msg = "📋 **Tracked Wallets:**\n"
    for addr, name in wallets.items():
        msg += f"• [{name}](https://polymarket.com/profile/{addr})\n"
    await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start"),
        BotCommand("add", "Add Wallet"),
        BotCommand("remove", "Remove Wallet"),
        BotCommand("list", "List Wallets"),
    ])

if __name__ == '__main__':
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_wallet))
    app.add_handler(CommandHandler("remove", remove_wallet))
    app.add_handler(CommandHandler("list", list_wallets))

    app.job_queue.run_repeating(check_wallets, interval=CHECK_INTERVAL, first=5)

    print("🤖 Bot is running...")
    app.run_polling()
# PolyTracker Bot

PolyTracker is a Python-based Telegram bot that tracks Polymarket traders in real-time. It monitors specific wallets and sends instant alerts when they open new positions, increase their bets, or exit trades.

## ✨ Features

- **Real-Time Alerts** — Get notified immediately when a tracked wallet places a bet.
- **Position Tracking:**
  - **New Bets** — Detects fresh positions instantly.
  - **Increases** — Tracks when a trader adds to an existing position.
  - **Sells/Exits** — Alerts when a trader sells part of their position or exits completely.
  - **Smart Analytics** — Calculates the estimated Trade Price for position increases and tracks Average Entry Price.
  - **Persistence** — Saves all data to a local SQLite database, so you never lose data even if the bot restarts.

## 🛠️ Prerequisites

- Python 3.9+ (Tested on Python 3.13)
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Your Telegram User ID

## 📥 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Dark-L1ght/PolyTracker.git
   cd PolyTracker
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

   Or install in editable mode for development:
   ```bash
   pip install -e ".[dev]"
   ```

## ⚙️ Configuration

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your secrets:
   ```
   TELEGRAM_TOKEN=your_bot_token_here
   CHAT_ID=your_numeric_chat_id_here
   ```

## 🚀 Usage

```bash
python -m polytracker
```

Or if installed with `pip install -e .`:
```bash
polytracker
```

## 🎮 Bot Commands

| Command | Example | Description |
|---------|---------|-------------|
| `/start` | `/start` | Initialize the bot and check connection. |
| `/add` | `/add 0x123... walletName` | Track a new wallet address. |
| `/remove` | `/remove walletName` | Stop tracking a wallet. |
| `/list` | `/list` | Show all currently tracked wallets. |
| `/help` | `/help` | Show available commands and usages. |

## 🏗️ Project Structure

```
src/polytracker/
├── __init__.py      # Package metadata
├── __main__.py      # Entry point
├── config.py        # Centralized settings (env vars + defaults)
├── db.py            # SQLite database layer
├── api.py           # Polymarket API client
└── bot.py           # Telegram command handlers + monitoring logic
```

## 🧪 Running Tests

```bash
pip install -e ".[dev]"
pytest -v
```

## 📝 Disclaimer

This bot is for educational and informational purposes only. Tracking traders does not guarantee profits. Prediction markets carry financial risk. Use responsibly.

Built with 💙 using `python-telegram-bot` and the Polymarket API.

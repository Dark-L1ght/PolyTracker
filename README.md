# PolyTracker Bot

PolyTracker is a Python-based Telegram bot that tracks Polymarket traders in real-time. It monitors specific wallets and sends instant alerts when they open new positions, increase their bets, or exit trades.

## ✨ Features

- Real-Time Alerts: Get notified immediately when a tracked wallet places a bet.

- Position Tracking:

  - New Bets: Detects fresh positions instantly.

  - Increases: Tracks when a trader adds to an existing position.

  - Sells/Exits: Alerts when a trader sells part of their position or exits completely.

  - Smart Analytics: Calculates the estimated Trade Price for position increases and tracks Average Entry Price.

  - Persistence: Saves your watchlist to watchlist.json, so you never lose data even if the bot restarts.

## 🛠️ Prerequisites

- Python 3.9+ (Tested on Python 3.13)

- A Telegram Bot Token (mine use @BotFather)

- Your Telegram User ID

## 📥 Installation
1.  Clone the repository:
```
git clone https://github.com/Dark-L1ght/PolyTracker.git
cd polytracker-bot
```

2. Create a virtual environment (Optional but Recommended):
```
python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate
```

3. Install dependencies:
```
pip install -r requirements.txt
```

## ⚙️ Configuration

1. Create a file named .env in the root directory.

2. Copy paste below, and add your secrets to it:
```
TELEGRAM_TOKEN=your_bot_token_here
CHAT_ID=your_numeric_chat_id_here
```

## 🚀 Usage

- Start the bot:
```
python main.py
```

- Open Telegram and message your bot.

## 🎮 Bot Commands

| Command | Usage | Description |
|---------| ----- | ----------- |
| /start  | /start |Initialize the bot and check connection. |
| /add |/add 0x123... walletName | Track a new wallet address. Add name after address|
| /remove | /remove walletName |Stop tracking a wallet. |
| /list | /list | Show all currently tracked wallets. |
| /help | /help | Show available commands and usages. |

## 📝 Disclaimer

This bot is for educational and informational purposes only. Tracking traders does not guarantee profits. Prediction markets carry financial risk. Use responsibly.

Built with 💙 using `python-telegram-bot` and Polymarket API.

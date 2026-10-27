# Telegram Deal Forwarder for ExtraPe Bot (@Extrape_bot)

A production-ready Telegram userbot automation tool built with **Python 3.10+** and **Telethon**. It monitors specified deal and loot channels in real-time, extracts affiliate-eligible e-commerce links (Amazon, Flipkart, Myntra, Ajio, etc.), and automatically passes them to **@Extrape_bot** for conversion with rate-limiting, randomized human pacing, and anti-flood protection.

---

## 📁 Project Structure

```text
telegrammessage forwarder/
├── .env.example          # Template for required environment variables
├── .gitignore            # Protects credentials (.env) and session files (*.session)
├── requirements.txt      # Python dependencies (Telethon, python-dotenv, aiohttp)
├── config.py             # Environment parser and setting validator
├── amazon.py             # Amazon redirect resolver, ASIN parser, and affiliate tag injector
├── extractor.py          # Deal link parser (regex & Telegram rich entities)
├── forwarder.py          # Main real-time event listener & dual-routing worker
├── test_extractor.py     # Unit tests for URL extraction
├── test_amazon.py        # Unit tests for Amazon affiliate tagging
└── README.md             # Complete setup and deployment guide
```

---

## 🚀 Key Features

- **Smart Dual-Route Deal Filtering**:
  - **Amazon Deals**: Automatically extracted and filtered out before ExtraPe. Short links (`amzn.to`, `amzn.in`, `a.co`) are resolved to find the product ASIN, re-tagged with **your personal Amazon Associate Tag**, and posted directly to **your Telegram channel** with photos/media intact!
  - **Non-Amazon Deals** (Flipkart, Myntra, Ajio, Tata Cliq, etc.): Forwarded to **@ExtraPeBot** for conversion.
- **Real-Time Channel Monitoring**: Listens to multiple source channels concurrently using Telethon's event engine.
- **Self & Bot Message Filtering**: Automatically skips messages sent by the userbot itself or other third-party bots in the channels.
- **Deep Link & Entity Extraction**:
  - Extracts standard plaintext and markdown URLs.
  - Extracts Telegram **Rich Entities** (`MessageEntityTextUrl`), converting links hidden behind text buttons (e.g. `👉 Click Here to Buy`).
- **Domain Filtering**: Only forwards deals from designated e-commerce sites to prevent passing noise.
- **Asynchronous Queue & Rate Limiter**:
  - Uses an internal `asyncio.Queue` to sequence outgoing messages.
  - Adds randomized pacing intervals (e.g., 2–4 seconds) between dispatches.
  - Automatically catches Telegram `FloodWaitError` and sleeps for the required duration without dropping messages.

---

## 🔑 Prerequisites: Getting Telegram API Credentials

1. Log in to [my.telegram.org](https://my.telegram.org) with your Telegram phone number.
2. Navigate to **API development tools**.
3. Fill in the application details:
   - **App title**: e.g., `DealForwarder`
   - **Short name**: e.g., `dealforwarder`
   - **Platform**: `Desktop` or `Other`
4. Copy your **`api_id`** (numeric integer) and **`api_hash`** (alphanumeric string).

---

## 🛠️ Step-by-Step Installation & Setup

### 1. Clone / Navigate to Project Directory
```bash
cd "/Users/apple/telegrammessage forwarder"
```

### 2. Create and Activate a Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Create your `.env` File
Copy the provided `.env.example` to `.env`:
```bash
cp .env.example .env
```

Open `.env` in your editor and configure your credentials:
```ini
# Telegram Credentials
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_PHONE=+919876543210

# Source Channels (comma-separated usernames or numeric channel IDs)
SOURCE_CHANNELS=lootdeals,techoffers,-1001987654321

# Target Bot
TARGET_BOT=@Extrape_bot

# Forwarding Options
FORWARD_FULL_MESSAGE=False
FILTER_DOMAINS=True
ALLOWED_DOMAINS=amazon,amzn,flipkart,fkrt,myntra,ajio,tatacliq,nykaa,croma,meesho,boat-lifestyle

# Safe Rate Pacing (in seconds)
MIN_DELAY_SECONDS=2.0
MAX_DELAY_SECONDS=4.0
```

> **Tip for Channel IDs**: If a channel is private or does not have a public `@username`, add the userbot to that channel or forward a message from it to `@userinfobot` or `@JsonDumpBot` to get its numeric ID (starts with `-100...`).

---

## 🔐 Initial Interactive Authentication

The first time you run the script, Telethon requires interactive authentication to generate a session file:

```bash
python3 forwarder.py
```

You will see prompts in the terminal:
1. **Phone number**: Enter your Telegram account phone number (with country code, e.g., `+919876543210`).
2. **Login Code**: Telegram will send a login code via the official Telegram app on your phone/desktop. Enter the numeric code.
3. **2FA Password** *(if enabled)*: Enter your Telegram two-step verification password.

Once authenticated, Telethon creates `extrape_userbot.session`. Future runs will automatically log in without asking for codes.

---

## 🧪 Running Unit Tests

To verify that the URL extractor and domain filter work as expected:
```bash
python3 test_extractor.py
```

---

## 🖥️ Running in Production (24/7 Deployment)

To keep the forwarder running uninterrupted in the background:

### Option A: Using `screen` or `tmux`
```bash
# Start a new tmux session
tmux new -s dealforwarder

# Activate venv and run
source venv/bin/activate
python3 forwarder.py

# Detach from session: Press Ctrl+B, then D
# Reattach anytime:
tmux attach -t dealforwarder
```

### Option B: Using `nohup` (Background Process)
```bash
nohup venv/bin/python3 forwarder.py > forwarder.log 2>&1 &
```

### Option C: Systemd Service (Linux Server)
Create `/etc/systemd/system/dealforwarder.service`:
```ini
[Unit]
Description=Telegram Deal Forwarder Userbot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/telegrammessage forwarder
ExecStart=/path/to/telegrammessage forwarder/venv/bin/python3 forwarder.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dealforwarder
sudo systemctl start dealforwarder
```

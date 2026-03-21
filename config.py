# ============================================================
# config.py — SOLANA AI SNIPER BOT — CONTROL CENTER
# ============================================================
import os

# ── TELEGRAM ALERTS BOT ──────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PASTE_HERE")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "PASTE_HERE")

# ── TELEGRAM USER ACCOUNT (for alpha group scanner) ───────
# Get API_ID + API_HASH from: my.telegram.org → API Development Tools
# TELEGRAM_SESSION_STRING: copy from Render logs after first run
TELEGRAM_API_ID         = os.getenv("TELEGRAM_API_ID",         "")
TELEGRAM_API_HASH       = os.getenv("TELEGRAM_API_HASH",       "")
TELEGRAM_PHONE          = os.getenv("TELEGRAM_PHONE",          "")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")

# ── ALPHA GROUPS TO SCAN ──────────────────────────────────
# Add group @usernames after joining them on Telegram
# Leave empty [] to disable scanner
ALPHA_GROUPS = [
    "solana",
]

# ── SOLANA RPC ────────────────────────────────────────────
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "PASTE_HERE")
HELIUS_RPC_URL = "https://api.mainnet-beta.solana.com"
HELIUS_WS_URL = "wss://api.mainnet-beta.solana.com"

# ── YOUR SOLANA WALLET ────────────────────────────────────
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_PUBLIC_KEY  = os.getenv("WALLET_PUBLIC_KEY",  "")

# ── SUPABASE ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "PASTE_HERE")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "PASTE_HERE")

# ── KOL WATCHLIST ─────────────────────────────────────────
WATCHED_INFLUENCERS = [
    "cz_binance",
    "elonmusk",
    "VitalikButerin",
    "solana",
    "aeyakovenko",
    "rajgokal",
    "weremeow",
    "bloomstarbms",
]

# Priority — checked every 10 seconds across ALL Nitter instances
# These are the accounts whose posts cause the biggest pumps
PRIORITY_INFLUENCERS = [
    "elonmusk",
    "cz_binance",
]

POST_WATCH_WINDOW_MINS = 20

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

# ── MONITORED PROGRAMS ────────────────────────────────────
MONITORED_PROGRAMS = [
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", # Raydium AMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora
    "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qoqzdZhx",  # Moonshot
]

# ── AI SCORING ────────────────────────────────────────────
MIN_WIN_PROBABILITY    = 60
KOL_POST_BONUS         = 20
MAX_TOKEN_AGE_MINS     = 30   # Reduced — catch tokens earlier

# ── HARD FILTERS ──────────────────────────────────────────
MAX_BUY_TAX            = 5
MAX_SELL_TAX           = 5
MIN_LIQUIDITY_USD      = 1000
MAX_TOP_HOLDER_PCT     = 20
REQUIRE_LP_LOCKED      = True
REQUIRE_RENOUNCED      = True
REJECT_HONEYPOT        = True
REJECT_BUNDLED         = True

# ── CAPITAL MANAGEMENT ────────────────────────────────────
MAX_POSITION_PCT       = 10

# ── TAKE PROFIT ───────────────────────────────────────────
TP_STAGE_1_X           = 10
TP_STAGE_2_X           = 25
TP_STAGE_3_X           = 50

# ── STOP LOSS ─────────────────────────────────────────────
STOP_LOSS_PCT          = 40

# ── SMART WALLET ENGINE ───────────────────────────────────
MIN_WALLET_WIN_RATE    = 80
MIN_WALLET_TRADES      = 20

# ── RATE LIMITING ─────────────────────────────────────────
MAX_CONCURRENT_CHECKS  = 1
API_CALL_DELAY_SECS    = 2

# ── MODE ──────────────────────────────────────────────────
PAPER_TRADING          = True

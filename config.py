# ============================================================
# config.py — SOLANA AI SNIPER BOT — CONTROL CENTER
# ============================================================
import os

# ── TELEGRAM ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PASTE_HERE")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "PASTE_HERE")

# ── SOLANA RPC ────────────────────────────────────────────
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "PASTE_HERE")
HELIUS_RPC_URL = "https://api.devnet.solana.com"
HELIUS_WS_URL  = "wss://api.devnet.solana.com"

# ── WALLET — stored as env var, NEVER hardcoded ──────────
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_PUBLIC_KEY  = os.getenv("WALLET_PUBLIC_KEY",  "")

# ── SUPABASE ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "PASTE_HERE")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "PASTE_HERE")

# ── INFLUENCER WATCHLIST ──────────────────────────────────
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

TWITTER_POLL_INTERVAL  = 30   # seconds between checks
POST_WATCH_WINDOW_MINS = 20   # mins to watch chain after KOL post

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

# ── MONITORED PROGRAMS (All Solana launchpads) ───────────
MONITORED_PROGRAMS = [
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", # Raydium AMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora
    "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qoqzdZhx",  # Moonshot
]

# ── AI SCORING ────────────────────────────────────────────
MIN_WIN_PROBABILITY    = 80
KOL_POST_BONUS         = 20
MAX_TOKEN_AGE_MINS     = 10

# ── HARD FILTERS ──────────────────────────────────────────
MAX_BUY_TAX            = 5
MAX_SELL_TAX           = 5
MIN_LIQUIDITY_USD      = 5000
MAX_TOP_HOLDER_PCT     = 20
REQUIRE_LP_LOCKED      = True
REQUIRE_RENOUNCED      = True
REJECT_HONEYPOT        = True
REJECT_BUNDLED         = True

# ── CAPITAL MANAGEMENT ────────────────────────────────────
# Score-based sizing — never exceeds 10%
# Score 80-84 → 6% of wallet
# Score 85-89 → 8% of wallet
# Score 90+   → 10% of wallet
MAX_POSITION_PCT       = 10

# ── TAKE PROFIT ───────────────────────────────────────────
TP_STAGE_1_X           = 10   # At 10x → sell 50%
TP_STAGE_2_X           = 25   # At 25x → sell 25%
TP_STAGE_3_X           = 50   # At 50x → sell last 25%

# ── STOP LOSS ─────────────────────────────────────────────
STOP_LOSS_PCT          = 40   # Exit 100% if down 40%

# ── SMART WALLET ENGINE ───────────────────────────────────
MIN_WALLET_WIN_RATE    = 80
MIN_WALLET_TRADES      = 20

# ── RATE LIMITING ─────────────────────────────────────────
MAX_CONCURRENT_CHECKS  = 3    # Max 3 tokens analyzed at once
API_CALL_DELAY_SECS    = 0.5  # Delay between API calls

# ── MODE ──────────────────────────────────────────────────
PAPER_TRADING  = False # TRUE = no real money, alerts only
                                # Set to False when ready to go live

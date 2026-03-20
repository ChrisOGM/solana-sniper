# ============================================================
# config.py — SOLANA AI SNIPER BOT — CONTROL CENTER
# ============================================================

# ── TELEGRAM ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "PASTE_YOUR_CHAT_ID_HERE"

# ── SOLANA RPC (Helius — Free Tier) ──────────────────────
HELIUS_API_KEY = "PASTE_YOUR_HELIUS_KEY_HERE"
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL  = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# ── YOUR SOLANA WALLET ────────────────────────────────────
WALLET_PRIVATE_KEY  = "PASTE_YOUR_WALLET_PRIVATE_KEY_HERE"
WALLET_PUBLIC_KEY   = "PASTE_YOUR_WALLET_PUBLIC_ADDRESS_HERE"

# ── SUPABASE DATABASE ─────────────────────────────────────
SUPABASE_URL = "PASTE_YOUR_SUPABASE_URL_HERE"
SUPABASE_KEY = "PASTE_YOUR_SUPABASE_ANON_KEY_HERE"

# ── INFLUENCER TWITTER WATCHLIST ──────────────────────────
# Bot monitors these accounts 24/7 via Nitter (free, no API key)
# As soon as any of them posts, bot scans for related token deploys
WATCHED_INFLUENCERS = [
    "cz_binance",        # CZ — Binance founder
    "elonmusk",          # Elon — massive market mover
    "VitalikButerin",    # Vitalik
    "solana",            # Official Solana account
    "aeyakovenko",       # Anatoly — Solana founder
    "rajgokal",          # Raj — Solana co-founder
    "weremeow",          # Popular Solana degen
    "bloomstarbms",      # BMS — your guy
    # Add any KOL you want here
]

# How often to check each influencer for new posts (seconds)
TWITTER_POLL_INTERVAL = 30  # Check every 30 seconds

# After a KOL posts, how long to watch for related token deploys
POST_WATCH_WINDOW_MINS = 20  # Watch for 20 mins after post

# Nitter instances (free Twitter mirrors — no API key needed)
# Bot rotates between them if one goes down
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

# ── WHAT TO MONITOR ON-CHAIN ──────────────────────────────
MONITORED_PROGRAMS = [
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", # Raydium AMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora
    "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qoqzdZhx",  # Moonshot
]

# ── AI SCORING ────────────────────────────────────────────
MIN_WIN_PROBABILITY  = 80

# Bonus score if token is linked to a KOL post
KOL_POST_BONUS       = 20   # +20 points added to score
                             # e.g. token scores 65 normally
                             # but CZ just posted about it = 85 → BUY

MAX_TOKEN_AGE_MINS   = 30

# ── HARD FILTERS (Strict — no exceptions) ────────────────
MAX_BUY_TAX          = 5
MAX_SELL_TAX         = 5
MIN_LIQUIDITY_USD    = 5000
MAX_TOP_HOLDER_PCT   = 20
REQUIRE_LP_LOCKED    = True
REQUIRE_RENOUNCED    = True
REJECT_HONEYPOT      = True
REJECT_BUNDLED       = True

# ── CAPITAL MANAGEMENT ────────────────────────────────────
MAX_POSITION_PCT     = 10
# Score-based sizing:
# Score 80–84  → 6% of wallet
# Score 85–89  → 8% of wallet
# Score 90+    → 10% of wallet
# KOL-linked token that scores 90+ → still capped at 10%

# ── TAKE PROFIT STRATEGY ──────────────────────────────────
TP_STAGE_1_X         = 10   # At 10x → sell 50%
TP_STAGE_2_X         = 25   # At 25x → sell 25%
TP_STAGE_3_X         = 50   # At 50x → sell final 25%

# ── STOP LOSS ─────────────────────────────────────────────
STOP_LOSS_PCT        = 40

# ── SMART WALLET ENGINE ───────────────────────────────────
MIN_WALLET_WIN_RATE  = 80
MIN_WALLET_TRADES    = 20

# ── MODE ──────────────────────────────────────────────────
PAPER_TRADING        = True

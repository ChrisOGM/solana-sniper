# ============================================================
# pattern_engine.py — ON-CHAIN PATTERN RECOGNITION
# Rescores borderline tokens (60–79) using 5 pattern checks
# If patterns push score to 80+ — auto buys
# ============================================================

import asyncio
import aiohttp
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from config import HELIUS_API_KEY

# ── Pattern thresholds ────────────────────────────────────
LIQ_SPIKE_RATIO       = 2.0    # Liquidity doubles = spike
CLUSTER_COUNT         = 5      # 5+ unique wallets in 60 secs
CLUSTER_WINDOW_SECS   = 60
VOL_ACCEL_RATIO       = 3.0    # Buy vol grows 3x faster than sells
SMART_CONVERGENCE_MIN = 2      # 2+ smart wallets = convergence
STEALTH_VOL_USD       = 5000   # $5k+ volume with <5% price move
STEALTH_PRICE_MAX_PCT = 5.0

# ── Pattern bonus scores ──────────────────────────────────
PATTERN_SCORES = {
    "liquidity_spike":          15,
    "wallet_clustering":        20,
    "volume_acceleration":      15,
    "smart_money_convergence":  25,
    "stealth_accumulation":     20,
}

# ── Per-token state for pattern tracking ──────────────────
token_state   = defaultdict(lambda: {
    "liquidity_history": [],   # [(datetime, usd)]
    "first_seen":        datetime.utcnow()
})

# ── Results cache — avoid re-checking same token ──────────
pattern_cache = {}   # { address: { patterns, bonus, total, detected_at } }

# ── Check interval ────────────────────────────────────────
CHECK_INTERVAL = 30  # seconds


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_pattern_engine():
    print("[PATTERN] Starting on-chain pattern recognition engine...")
    while True:
        try:
            await run_pattern_checks()
        except Exception as e:
            print(f"[PATTERN] Loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# ============================================================
# MAIN CHECK LOOP
# ============================================================

async def run_pattern_checks():
    """
    Checks borderline tokens (scored 60–79 in last 20 mins)
    for on-chain patterns that could push them over 80.
    """
    borderline = get_borderline_tokens()
    if not borderline:
        return

    print(f"[PATTERN] Checking {len(borderline)} borderline tokens...")

    for token in borderline:
        token_address = token.get("token_address", "")
        token_name    = token.get("token_name", "Unknown")
        base_score    = token.get("score", 0)

        if not token_address or len(token_address) < 30:
            continue

        # Skip if recently checked
        if token_address in pattern_cache:
            cached    = pattern_cache[token_address]
            age_secs  = (datetime.utcnow() - cached["detected_at"]).total_seconds()
            if age_secs < 120:  # Don't recheck within 2 minutes
                continue

        try:
            patterns, bonus = await analyse_all_patterns(token_address)

            if not patterns:
                continue

            total = min(base_score + bonus, 100)

            pattern_cache[token_address] = {
                "patterns":    patterns,
                "bonus":       bonus,
                "total_score": total,
                "detected_at": datetime.utcnow()
            }

            print(
                f"[PATTERN] 🎯 {token_name}: "
                f"{len(patterns)} patterns | +{bonus} | Total: {total}/100"
            )

            if total >= 80:
                await trigger_pattern_buy(
                    token_address, token_name,
                    base_score, bonus, patterns, total
                )

        except Exception as e:
            print(f"[PATTERN] Check error {token_address[:16]}: {e}")

    clean_caches()


# ============================================================
# PATTERN ANALYSIS
# ============================================================

async def analyse_all_patterns(token_address):
    """
    Runs all 5 pattern checks.
    Returns (list_of_pattern_names, total_bonus_score)
    """
    patterns = []
    bonus    = 0

    # Single DexScreener fetch — reused by all checks
    dex = await fetch_dex_data(token_address)
    if not dex:
        return [], 0

    # Pattern 1 — Liquidity Spike
    found, detail = check_liquidity_spike(token_address, dex)
    if found:
        patterns.append(f"💧 Liquidity Spike ({detail})")
        bonus += PATTERN_SCORES["liquidity_spike"]

    # Pattern 2 — Wallet Clustering
    found, detail = await check_wallet_clustering(token_address)
    if found:
        patterns.append(f"👥 Wallet Cluster ({detail})")
        bonus += PATTERN_SCORES["wallet_clustering"]

    # Pattern 3 — Volume Acceleration
    found, detail = check_volume_acceleration(dex)
    if found:
        patterns.append(f"📈 Volume Acceleration ({detail})")
        bonus += PATTERN_SCORES["volume_acceleration"]

    # Pattern 4 — Smart Money Convergence
    found, detail = check_smart_money_convergence(token_address)
    if found:
        patterns.append(f"🧠 Smart Money Convergence ({detail})")
        bonus += PATTERN_SCORES["smart_money_convergence"]

    # Pattern 5 — Stealth Accumulation
    found, detail = check_stealth_accumulation(dex)
    if found:
        patterns.append(f"🕵️ Stealth Accumulation ({detail})")
        bonus += PATTERN_SCORES["stealth_accumulation"]

    return patterns, bonus


def check_liquidity_spike(token_address, dex):
    """Liquidity doubled in last 2 minutes"""
    try:
        current = dex.get("liquidity", {}).get("usd", 0)
        if current <= 0:
            return False, ""

        now     = datetime.utcnow()
        history = token_state[token_address]["liquidity_history"]
        history.append((now, current))

        # Keep last 10 minutes only
        history[:] = [(t, l) for t, l in history
                      if now - t < timedelta(minutes=10)]

        # Compare to 2 minutes ago
        old = [(t, l) for t, l in history
               if now - t >= timedelta(minutes=2)]
        if not old:
            return False, ""

        old_liq = old[0][1]
        if old_liq <= 0:
            return False, ""

        ratio = current / old_liq
        if ratio >= LIQ_SPIKE_RATIO:
            return True, f"{ratio:.1f}x in 2mins"
        return False, ""
    except Exception as e:
        print(f"[PATTERN] Liquidity spike error: {e}")
        return False, ""


async def check_wallet_clustering(token_address):
    """5+ unique wallets buying in 60 seconds"""
    try:
        url = (
            f"https://api.helius.xyz/v0/addresses/{token_address}"
            f"/transactions?api-key={HELIUS_API_KEY}&limit=50"
        )
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return False, ""
                txs = await r.json()
                if not isinstance(txs, list):
                    return False, ""

        now    = datetime.utcnow()
        cutoff = now - timedelta(seconds=CLUSTER_WINDOW_SECS)
        buyers = set()

        for tx in txs:
            ts = tx.get("timestamp", 0)
            if not ts:
                continue
            if datetime.utcfromtimestamp(ts) < cutoff:
                continue
            fee_payer = tx.get("feePayer", "")
            if not fee_payer:
                continue
            for transfer in tx.get("tokenTransfers", []):
                if (transfer.get("mint") == token_address and
                        float(transfer.get("tokenAmount", 0) or 0) > 0 and
                        transfer.get("toUserAccount") == fee_payer):
                    buyers.add(fee_payer)
                    break

        count = len(buyers)
        if count >= CLUSTER_COUNT:
            return True, f"{count} wallets/60s"
        return False, ""
    except Exception as e:
        print(f"[PATTERN] Wallet cluster error: {e}")
        return False, ""


def check_volume_acceleration(dex):
    """Buy volume growing 3x faster than sells (5min vs 1hr rate)"""
    try:
        txns     = dex.get("txns", {})
        m5_buys  = txns.get("m5", {}).get("buys",  0)
        m5_sells = txns.get("m5", {}).get("sells", 1)
        h1_buys  = txns.get("h1", {}).get("buys",  0)
        h1_sells = txns.get("h1", {}).get("sells", 1)

        if not h1_buys or not h1_sells:
            return False, ""

        recent_ratio  = m5_buys  / max(m5_sells,  1)
        overall_ratio = h1_buys  / max(h1_sells,  1)

        if overall_ratio <= 0:
            return False, ""

        accel = recent_ratio / overall_ratio
        if accel >= VOL_ACCEL_RATIO:
            return True, f"{accel:.1f}x acceleration"
        return False, ""
    except Exception as e:
        print(f"[PATTERN] Volume accel error: {e}")
        return False, ""


def check_smart_money_convergence(token_address):
    """2+ smart wallets bought this token independently"""
    try:
        from database import supabase
        if not supabase:
            return False, ""

        result = supabase.table("trades") \
            .select("source") \
            .eq("token_address", token_address) \
            .eq("action", "BUY") \
            .execute()

        if not result.data:
            return False, ""

        copy_buys = sum(
            1 for t in result.data
            if t.get("source") == "COPY_TRADE"
        )
        if copy_buys >= SMART_CONVERGENCE_MIN:
            return True, f"{copy_buys} smart wallets"
        return False, ""
    except Exception as e:
        print(f"[PATTERN] Smart convergence error: {e}")
        return False, ""


def check_stealth_accumulation(dex):
    """Large buy volume with tiny price impact — smart money loading up quietly"""
    try:
        vol_m5   = float(dex.get("volume",      {}).get("m5", 0) or 0)
        chg_m5   = abs(float(dex.get("priceChange", {}).get("m5", 0) or 0))

        if vol_m5 > STEALTH_VOL_USD and chg_m5 < STEALTH_PRICE_MAX_PCT:
            return True, f"${vol_m5:,.0f} vol, {chg_m5:.1f}% move"
        return False, ""
    except Exception as e:
        print(f"[PATTERN] Stealth check error: {e}")
        return False, ""


# ============================================================
# TRIGGER BUY
# ============================================================

async def trigger_pattern_buy(token_address, token_name,
                               base_score, bonus, patterns, total_score):
    try:
        from database import token_already_seen, mark_token_seen
        from filters import run_hard_filters
        from telegram_bot import send_alert, alert_new_token_detected

        if token_already_seen(token_address):
            return

        # Re-run filters — state may have changed
        passed, reason = run_hard_filters(token_address)
        if not passed:
            mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
            return

        # Get ticker
        ticker = "???"
        try:
            url  = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                ticker = pairs[0].get("baseToken", {}).get("symbol", "???")
        except Exception:
            pass

        mark_token_seen(token_address, token_name, score=total_score, decision="BOUGHT")

        pattern_text = "\n".join(f"  • {p}" for p in patterns)
        breakdown    = {
            "base_score":     f"{base_score}/100",
            "pattern_bonus":  f"+{bonus}",
            "patterns_found": pattern_text
        }

        await alert_new_token_detected(
            ticker, token_name, token_address,
            total_score, breakdown, "PATTERN_ENGINE"
        )

        from executor import execute_buy
        await execute_buy(
            token_address=token_address,
            token_name=token_name,
            ticker=ticker,
            score=total_score,
            source="PATTERN_ENGINE"
        )

    except Exception as e:
        print(f"[PATTERN] trigger_pattern_buy error: {e}")


# ============================================================
# HELPERS
# ============================================================

async def fetch_dex_data(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                if r.status != 200:
                    return None
                data  = await r.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    return None
                return max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
    except Exception as e:
        print(f"[PATTERN] fetch_dex_data error: {e}")
        return None


def get_borderline_tokens():
    """Tokens scored 60–79 in last 20 minutes — candidates for pattern confirmation"""
    try:
        from database import supabase
        if not supabase:
            return []
        cutoff = (datetime.utcnow() - timedelta(minutes=20)).isoformat()
        result = supabase.table("tokens_seen") \
            .select("token_address, token_name, score") \
            .eq("decision", "SKIPPED") \
            .gte("score", 60) \
            .lte("score", 79) \
            .gte("seen_at", cutoff) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"[PATTERN] get_borderline_tokens error: {e}")
        return []


def clean_caches():
    """Removes stale cache entries"""
    now    = datetime.utcnow()
    cutoff = now - timedelta(hours=1)

    # Clean pattern cache
    stale = [a for a, d in pattern_cache.items()
             if d.get("detected_at", now) < cutoff]
    for a in stale:
        del pattern_cache[a]

    # Clean token state
    stale = [a for a, d in token_state.items()
             if now - d.get("first_seen", now) > timedelta(hours=2)]
    for a in stale:
        del token_state[a]

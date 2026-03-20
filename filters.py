# ============================================================
# filters.py — HARD FILTER ENGINE (DEBUGGED)
# ============================================================

import requests
from config import (
    MAX_BUY_TAX, MAX_SELL_TAX, MIN_LIQUIDITY_USD,
    MAX_TOP_HOLDER_PCT, REQUIRE_LP_LOCKED,
    REQUIRE_RENOUNCED, REJECT_HONEYPOT, REJECT_BUNDLED,
    HELIUS_API_KEY
)

# ── Correct GoPlus endpoint for Solana ─────────────────────
GOPLUS_SOLANA_URL = "https://api.gopluslabs.io/api/v1/solana/token_security"
DEXSCREENER_URL   = "https://api.dexscreener.com/latest/dex/tokens"

# ============================================================
# MASTER FILTER
# ============================================================

def run_hard_filters(token_address):
    print(f"[FILTER] Checking: {token_address}")

    # ── GoPlus Security ────────────────────────────────────
    security = get_goplus_data(token_address)

    if security:
        # Honeypot
        if REJECT_HONEYPOT and security.get("is_honeypot") == "1":
            return False, "HONEYPOT DETECTED"

        # Buy tax
        try:
            buy_tax = float(security.get("buy_tax", 0)) * 100
            if buy_tax > MAX_BUY_TAX:
                return False, f"BUY TAX TOO HIGH: {buy_tax:.1f}%"
        except:
            pass

        # Sell tax
        try:
            sell_tax = float(security.get("sell_tax", 0)) * 100
            if sell_tax > MAX_SELL_TAX:
                return False, f"SELL TAX TOO HIGH: {sell_tax:.1f}%"
        except:
            pass

        # LP locked
        if REQUIRE_LP_LOCKED:
            if security.get("lp_locked", "0") != "1":
                return False, "LP NOT LOCKED"

        # Renounced — on Solana this means checking freeze authority
        if REQUIRE_RENOUNCED:
            freeze = security.get("freeze_authority", None)
            if freeze and freeze != "" and freeze != "null":
                return False, "FREEZE AUTHORITY EXISTS — NOT RENOUNCED"

        # Top holder concentration
        try:
            holders = security.get("holders", [])
            if holders:
                top_pct = float(holders[0].get("percent", 0)) * 100
                if top_pct > MAX_TOP_HOLDER_PCT:
                    return False, f"TOP HOLDER TOO HIGH: {top_pct:.1f}%"
                if REJECT_BUNDLED and is_bundled(holders):
                    return False, "BUNDLED SUPPLY DETECTED"
        except:
            pass

        # Dev sold
        if security.get("dev_sold") == "1":
            return False, "DEV ALREADY SOLD"

    else:
        # GoPlus unavailable — log but don't block
        # We still run liquidity check below
        print(f"[FILTER] ⚠️ GoPlus unavailable for {token_address} — skipping security check")

    # ── Liquidity via DexScreener ──────────────────────────
    liquidity = get_liquidity(token_address)
    if liquidity == -1:
        # DexScreener also down — skip this token, too risky
        return False, "LIQUIDITY DATA UNAVAILABLE — SKIPPING"
    if liquidity < MIN_LIQUIDITY_USD:
        return False, f"LIQUIDITY TOO LOW: ${liquidity:,.0f}"

    print(f"[FILTER] ✅ PASSED all filters: {token_address}")
    return True, "PASSED"


# ============================================================
# GOPLUS — correct Solana endpoint
# ============================================================

def get_goplus_data(token_address):
    try:
        # Correct URL format for Solana
        url = f"{GOPLUS_SOLANA_URL}?contract_addresses={token_address}"
        response = requests.get(url, timeout=6)
        data = response.json()
        if data.get("code") == 1:
            result = data.get("result", {})
            # GoPlus returns data keyed by lowercase address
            return result.get(token_address, result.get(token_address.lower(), {}))
        return None
    except Exception as e:
        print(f"[FILTER] GoPlus error: {e}")
        return None


# ============================================================
# LIQUIDITY — DexScreener (free, no key)
# ============================================================

def get_liquidity(token_address):
    try:
        url = f"{DEXSCREENER_URL}/{token_address}"
        response = requests.get(url, timeout=6)
        data = response.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return 0
        best = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        return best.get("liquidity", {}).get("usd", 0)
    except Exception as e:
        print(f"[FILTER] DexScreener error: {e}")
        return -1  # -1 = unavailable (different from 0 = no liquidity)


# ============================================================
# BUNDLED SUPPLY DETECTION
# ============================================================

def is_bundled(holders):
    if len(holders) < 5:
        return False
    try:
        top5 = [float(h.get("percent", 0)) * 100 for h in holders[:5]]
        similar = sum(1 for p in top5 if abs(p - top5[0]) < 1.5)
        return similar >= 3
    except:
        return False

# ============================================================
# scorer.py — AI SCORING ENGINE (DEBUGGED)
# ============================================================

import requests
import random
from datetime import datetime
from config import (
    MIN_WIN_PROBABILITY, KOL_POST_BONUS,
    MAX_TOKEN_AGE_MINS, NITTER_INSTANCES,
    HELIUS_API_KEY
)

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens"

# ============================================================
# MASTER SCORER
# ============================================================

def score_token(token_address, token_name, ticker, deploy_time):
    score = 0
    breakdown = {}

    print(f"[SCORER] Scoring {ticker} ({token_address})")

    # Age check — skip old tokens
    age_mins = get_token_age_minutes(deploy_time)
    if age_mins > MAX_TOKEN_AGE_MINS:
        return 0, {"reason": f"Too old: {age_mins:.0f} mins"}, "SKIP"

    # Fetch DexScreener data ONCE — pass to all functions
    # This avoids hammering the API with repeated calls
    dex_data = get_dexscreener_data(token_address)

    # ── 1. Holder activity (0–20 pts) ──────────────────────
    h_score, h_note = score_holders(dex_data)
    score += h_score
    breakdown["holders"] = f"{h_score}/20 — {h_note}"

    # ── 2. Liquidity depth (0–20 pts) ──────────────────────
    l_score, l_note = score_liquidity(dex_data)
    score += l_score
    breakdown["liquidity"] = f"{l_score}/20 — {l_note}"

    # ── 3. Buy/sell pressure (0–20 pts) ────────────────────
    p_score, p_note = score_buy_pressure(dex_data)
    score += p_score
    breakdown["buy_pressure"] = f"{p_score}/20 — {p_note}"

    # ── 4. Smart wallets inside (0–20 pts) ─────────────────
    w_score, w_note = score_smart_wallet_presence(token_address)
    score += w_score
    breakdown["smart_wallets"] = f"{w_score}/20 — {w_note}"

    # ── 5. Social hype (0–20 pts) ──────────────────────────
    s_score, s_note = score_social_signals(ticker, token_name)
    score += s_score
    breakdown["social"] = f"{s_score}/20 — {s_note}"

    # ── 6. KOL bonus (+20 if linked to influencer post) ────
    k_bonus, k_note = check_kol_link(ticker, token_name)
    score += k_bonus
    breakdown["kol_bonus"] = f"+{k_bonus} — {k_note}"

    # Hard cap at 100
    score = min(score, 100)

    recommendation = "BUY" if score >= MIN_WIN_PROBABILITY else "SKIP"
    print(f"[SCORER] {ticker} → {score}/100 → {recommendation}")
    return score, breakdown, recommendation


# ============================================================
# DEXSCREENER — single fetch reused by all scoring functions
# ============================================================

def get_dexscreener_data(token_address):
    try:
        url = f"{DEXSCREENER_URL}/{token_address}"
        response = requests.get(url, timeout=6)
        data = response.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None
        # Return highest liquidity pair
        return max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
    except Exception as e:
        print(f"[SCORER] DexScreener fetch error: {e}")
        return None


def score_holders(dex_data):
    try:
        if not dex_data:
            return 0, "No data"
        buys = dex_data.get("txns", {}).get("h1", {}).get("buys", 0)
        if buys > 200: return 20, f"{buys} buys in 1hr — strong"
        elif buys > 100: return 12, f"{buys} buys in 1hr — moderate"
        elif buys > 50:  return 6,  f"{buys} buys in 1hr — low"
        return 0, f"Only {buys} buys in 1hr"
    except:
        return 0, "Error"


def score_liquidity(dex_data):
    try:
        if not dex_data:
            return 0, "No data"
        liq = dex_data.get("liquidity", {}).get("usd", 0)
        if liq > 100000: return 20, f"${liq:,.0f} — excellent"
        elif liq > 50000: return 15, f"${liq:,.0f} — good"
        elif liq > 20000: return 10, f"${liq:,.0f} — moderate"
        elif liq > 5000:  return 5,  f"${liq:,.0f} — low"
        return 0, f"${liq:,.0f} — too low"
    except:
        return 0, "Error"


def score_buy_pressure(dex_data):
    try:
        if not dex_data:
            return 0, "No data"
        txns = dex_data.get("txns", {}).get("m5", {})
        buys  = txns.get("buys", 0)
        sells = txns.get("sells", 1)
        ratio = round(buys / max(sells, 1), 2)
        if ratio >= 4:   return 20, f"{ratio}x buy ratio — extreme"
        elif ratio >= 2.5: return 14, f"{ratio}x buy ratio — strong"
        elif ratio >= 1.5: return 8,  f"{ratio}x buy ratio — moderate"
        return 0, f"{ratio}x buy ratio — weak"
    except:
        return 0, "Error"


def score_smart_wallet_presence(token_address):
    try:
        from database import get_all_smart_wallets
        smart_wallets = set(get_all_smart_wallets())
        if not smart_wallets:
            return 0, "No smart wallets in DB yet"

        # Correct Helius URL with API key
        url = (f"https://api.helius.xyz/v0/addresses/{token_address}"
               f"/transactions?api-key={HELIUS_API_KEY}&limit=50")
        response = requests.get(url, timeout=6)
        txs = response.json()

        if not isinstance(txs, list):
            return 0, "No transaction data"

        matches = sum(
            1 for tx in txs
            if tx.get("feePayer") in smart_wallets
        )
        if matches >= 3: return 20, f"{matches} smart wallets inside"
        elif matches == 2: return 14, f"{matches} smart wallets inside"
        elif matches == 1: return 7,  f"1 smart wallet inside"
        return 0, "No smart wallets detected"
    except Exception as e:
        print(f"[SCORER] Smart wallet check error: {e}")
        return 0, "Error checking wallets"


def score_social_signals(ticker, token_name):
    """Free Twitter scraping via Nitter with full fallback"""
    try:
        instance = random.choice(NITTER_INSTANCES)
        url = f"{instance}/search?q=%24{ticker}&f=tweets"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, timeout=8, headers=headers)

        if response.status_code != 200:
            return 0, "Nitter unavailable — skipped"

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")
        tweets = soup.find_all("div", class_="tweet-content")
        count = len(tweets)

        if count >= 20: return 20, f"Viral — {count} mentions"
        elif count >= 10: return 14, f"High buzz — {count} mentions"
        elif count >= 5:  return 8,  f"Some buzz — {count} mentions"
        elif count >= 1:  return 4,  f"Low buzz — {count} mentions"
        return 0, "No mentions found"
    except Exception as e:
        # Never crash the whole scorer because Twitter is down
        print(f"[SCORER] Social check failed: {e}")
        return 0, "Social check unavailable"


def check_kol_link(ticker, token_name):
    try:
        from database import get_recent_kol_posts
        recent_posts = get_recent_kol_posts(minutes=20)
        ticker_lower = ticker.lower()
        name_lower   = token_name.lower()
        for post in recent_posts:
            keywords = post.get("keywords", "").lower().split(", ")
            for kw in keywords:
                if kw and (kw in ticker_lower or kw in name_lower):
                    return KOL_POST_BONUS, f"Linked to @{post.get('influencer')} — '{kw}'"
        return 0, "No KOL link"
    except Exception as e:
        print(f"[SCORER] KOL check error: {e}")
        return 0, "KOL check error"


def get_token_age_minutes(deploy_time):
    try:
        if not deploy_time:
            return 0
        now = datetime.utcnow()
        if isinstance(deploy_time, str):
            deploy_time = datetime.fromisoformat(deploy_time)
        return (now - deploy_time).total_seconds() / 60
    except:
        return 0


# ============================================================
# POSITION SIZING — score based capital allocation
# ============================================================

def calculate_position_size(score, wallet_balance_sol):
    """
    Score 80–84 → 6% of wallet
    Score 85–89 → 8% of wallet
    Score 90+   → 10% of wallet
    Hard cap: never more than 10%
    """
    if score >= 90:
        pct = 0.10
    elif score >= 85:
        pct = 0.08
    elif score >= 80:
        pct = 0.06
    else:
        pct = 0  # Should never reach here

    position = round(wallet_balance_sol * pct, 4)
    print(f"[SCORER] Position size: {pct*100:.0f}% = {position} SOL")
    return position

# ============================================================
# database.py — ALL DATA STORAGE
# ============================================================

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime

# Initialize Supabase connection
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================
# TRADES — log every buy and sell
# ============================================================

def log_trade(token_address, token_name, ticker, action,
              price_usd, mcap_usd, amount_sol, score,
              source, paper_trade=True):
    """
    action = 'BUY' or 'SELL'
    source = 'AI_DISCOVERY' or 'COPY_TRADE' or 'KOL_LINKED'
    """
    data = {
        "token_address": token_address,
        "token_name":    token_name,
        "ticker":        ticker,
        "action":        action,
        "price_usd":     price_usd,
        "mcap_usd":      mcap_usd,
        "amount_sol":    amount_sol,
        "score":         score,
        "source":        source,
        "paper_trade":   paper_trade,
        "timestamp":     datetime.utcnow().isoformat()
    }
    supabase.table("trades").insert(data).execute()
    print(f"[DB] Trade logged: {action} {ticker} | Score: {score} | Source: {source}")


def get_open_positions():
    """Returns all tokens we currently hold (bought but not sold)"""
    result = supabase.table("trades")\
        .select("*")\
        .eq("action", "BUY")\
        .eq("exited", False)\
        .execute()
    return result.data


def mark_position_exited(token_address):
    """Marks a trade as fully exited"""
    supabase.table("trades")\
        .update({"exited": True, "exit_time": datetime.utcnow().isoformat()})\
        .eq("token_address", token_address)\
        .execute()


# ============================================================
# SMART WALLETS — track and score wallets
# ============================================================

def save_smart_wallet(wallet_address, win_rate, total_trades,
                      avg_multiplier, notes=""):
    data = {
        "wallet_address": wallet_address,
        "win_rate":       win_rate,
        "total_trades":   total_trades,
        "avg_multiplier": avg_multiplier,
        "notes":          notes,
        "added_at":       datetime.utcnow().isoformat()
    }
    supabase.table("smart_wallets").upsert(data).execute()
    print(f"[DB] Smart wallet saved: {wallet_address} | Win rate: {win_rate}%")


def get_all_smart_wallets():
    """Returns all tracked smart wallets"""
    result = supabase.table("smart_wallets")\
        .select("wallet_address")\
        .execute()
    return [row["wallet_address"] for row in result.data]


def update_wallet_stats(wallet_address, win_rate, total_trades):
    supabase.table("smart_wallets")\
        .update({"win_rate": win_rate, "total_trades": total_trades})\
        .eq("wallet_address", wallet_address)\
        .execute()


# ============================================================
# KOL POSTS — log every influencer post detected
# ============================================================

def log_kol_post(influencer, post_text, post_url, keywords):
    data = {
        "influencer":  influencer,
        "post_text":   post_text[:500],   # store first 500 chars
        "post_url":    post_url,
        "keywords":    ", ".join(keywords),
        "detected_at": datetime.utcnow().isoformat()
    }
    supabase.table("kol_posts").insert(data).execute()
    print(f"[DB] KOL post logged: @{influencer} | Keywords: {keywords}")


def get_recent_kol_posts(minutes=20):
    """Returns KOL posts from the last X minutes"""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
    result = supabase.table("kol_posts")\
        .select("*")\
        .gte("detected_at", cutoff)\
        .execute()
    return result.data


# ============================================================
# TOKENS SEEN — avoid analyzing same token twice
# ============================================================

def token_already_seen(token_address):
    result = supabase.table("tokens_seen")\
        .select("token_address")\
        .eq("token_address", token_address)\
        .execute()
    return len(result.data) > 0


def mark_token_seen(token_address, token_name, score, decision):
    """
    decision = 'BOUGHT', 'SKIPPED', 'FILTERED'
    """
    data = {
        "token_address": token_address,
        "token_name":    token_name,
        "score":         score,
        "decision":      decision,
        "seen_at":       datetime.utcnow().isoformat()
    }
    supabase.table("tokens_seen").insert(data).execute()


# ============================================================
# PERFORMANCE — daily PNL summary
# ============================================================

def get_performance_summary():
    """Returns win rate and PNL across all paper trades"""
    result = supabase.table("trades")\
        .select("*")\
        .eq("paper_trade", True)\
        .execute()

    trades = result.data
    if not trades:
        return {"message": "No trades yet"}

    buys  = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]

    total_invested = sum(t["amount_sol"] for t in buys)
    total_returned = sum(t["amount_sol"] for t in sells)
    pnl            = total_returned - total_invested

    return {
        "total_trades":    len(buys),
        "total_invested":  round(total_invested, 4),
        "total_returned":  round(total_returned, 4),
        "pnl_sol":         round(pnl, 4),
        "pnl_pct":         round((pnl / total_invested * 100) if total_invested else 0, 2)
    }

# ============================================================
# database.py — ALL DATA STORAGE
# ============================================================

from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta

# Safe Supabase import — works whether or not library is installed
try:
    from supabase import create_client, Client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("[DB] ✅ Supabase connected")
    SUPABASE_OK = True
except Exception as e:
    print(f"[DB] ⚠️ Supabase unavailable: {e}")
    supabase = None
    SUPABASE_OK = False


# ============================================================
# SAFE QUERY HELPER
# All DB functions use this — never crashes bot if DB is down
# ============================================================

def db_available():
    if not SUPABASE_OK or supabase is None:
        print("[DB] Skipping — Supabase not connected")
        return False
    return True


# ============================================================
# TRADES
# ============================================================

def log_trade(token_address, token_name, ticker, action,
              price_usd, mcap_usd, amount_sol, score,
              source, paper_trade=True):
    if not db_available():
        return
    try:
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
            "exited":        False,
            "timestamp":     datetime.utcnow().isoformat()
        }
        supabase.table("trades").insert(data).execute()
        print(f"[DB] Trade logged: {action} {ticker} | Score: {score}")
    except Exception as e:
        print(f"[DB] log_trade error: {e}")


def get_open_positions():
    if not db_available():
        return []
    try:
        result = supabase.table("trades") \
            .select("*") \
            .eq("action", "BUY") \
            .eq("exited", False) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"[DB] get_open_positions error: {e}")
        return []


def mark_position_exited(token_address):
    if not db_available():
        return
    try:
        supabase.table("trades") \
            .update({
                "exited":    True,
                "exit_time": datetime.utcnow().isoformat()
            }) \
            .eq("token_address", token_address) \
            .eq("exited", False) \
            .execute()
    except Exception as e:
        print(f"[DB] mark_position_exited error: {e}")


# ============================================================
# SMART WALLETS
# ============================================================

def save_smart_wallet(wallet_address, win_rate,
                      total_trades, avg_multiplier, notes=""):
    if not db_available():
        return
    try:
        data = {
            "wallet_address": wallet_address,
            "win_rate":       win_rate,
            "total_trades":   total_trades,
            "avg_multiplier": avg_multiplier,
            "notes":          notes,
            "added_at":       datetime.utcnow().isoformat()
        }
        supabase.table("smart_wallets").upsert(data).execute()
        print(f"[DB] Smart wallet saved: {wallet_address[:20]}...")
    except Exception as e:
        print(f"[DB] save_smart_wallet error: {e}")


def get_all_smart_wallets():
    if not db_available():
        return []
    try:
        result = supabase.table("smart_wallets") \
            .select("wallet_address") \
            .execute()
        if not result.data:
            return []
        return [row["wallet_address"] for row in result.data]
    except Exception as e:
        print(f"[DB] get_all_smart_wallets error: {e}")
        return []


def update_wallet_stats(wallet_address, win_rate, total_trades):
    if not db_available():
        return
    try:
        supabase.table("smart_wallets") \
            .update({
                "win_rate":     win_rate,
                "total_trades": total_trades
            }) \
            .eq("wallet_address", wallet_address) \
            .execute()
    except Exception as e:
        print(f"[DB] update_wallet_stats error: {e}")


# ============================================================
# KOL POSTS
# ============================================================

def log_kol_post(influencer, post_text, post_url, keywords):
    if not db_available():
        return
    try:
        data = {
            "influencer":  influencer,
            "post_text":   post_text[:500],
            "post_url":    post_url,
            "keywords":    ", ".join(keywords),
            "detected_at": datetime.utcnow().isoformat()
        }
        supabase.table("kol_posts").insert(data).execute()
        print(f"[DB] KOL post logged: @{influencer}")
    except Exception as e:
        print(f"[DB] log_kol_post error: {e}")


def get_recent_kol_posts(minutes=20):
    if not db_available():
        return []
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        result = supabase.table("kol_posts") \
            .select("*") \
            .gte("detected_at", cutoff) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"[DB] get_recent_kol_posts error: {e}")
        return []


# ============================================================
# TOKENS SEEN — duplicate protection
# ============================================================

def token_already_seen(token_address):
    if not db_available():
        return False
    try:
        result = supabase.table("tokens_seen") \
            .select("token_address") \
            .eq("token_address", token_address) \
            .execute()
        return len(result.data) > 0 if result.data else False
    except Exception as e:
        print(f"[DB] token_already_seen error: {e}")
        return False


def mark_token_seen(token_address, token_name, score, decision):
    if not db_available():
        return
    try:
        data = {
            "token_address": token_address,
            "token_name":    token_name,
            "score":         score,
            "decision":      decision,
            "seen_at":       datetime.utcnow().isoformat()
        }
        supabase.table("tokens_seen").insert(data).execute()
    except Exception as e:
        print(f"[DB] mark_token_seen error: {e}")


# ============================================================
# PERFORMANCE SUMMARY
# ============================================================

def get_performance_summary():
    if not db_available():
        return {"message": "Database not connected"}
    try:
        result = supabase.table("trades") \
            .select("*") \
            .execute()

        trades = result.data if result.data else []
        if not trades:
            return {"message": "No trades yet"}

        buys  = [t for t in trades if t.get("action") == "BUY"]
        sells = [t for t in trades if t.get("action") == "SELL"]

        total_invested = sum(float(t.get("amount_sol") or 0) for t in buys)
        total_returned = sum(float(t.get("amount_sol") or 0) for t in sells)
        pnl            = total_returned - total_invested
        win_rate       = (len(sells) / len(buys) * 100) if buys else 0

        return {
            "total_trades":   len(buys),
            "total_invested": round(total_invested, 4),
            "total_returned": round(total_returned, 4),
            "pnl_sol":        round(pnl, 4),
            "win_rate":       round(win_rate, 2)
        }
    except Exception as e:
        print(f"[DB] get_performance_summary error: {e}")
        return {"message": f"Error: {e}"}

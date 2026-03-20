# ============================================================
# exit_manager.py — TAKE PROFIT & STOP LOSS ENGINE
# Monitors all open positions every 15 seconds
# Sells in 3 stages — never dumps everything at once
# ============================================================

import asyncio
import requests
from config import (
    TP_STAGE_1_X, TP_STAGE_2_X, TP_STAGE_3_X,
    STOP_LOSS_PCT, PAPER_TRADING
)

# Check interval in seconds
CHECK_INTERVAL = 15

# Tracks which TP stages already fired per token
# { token_address: { "stage1": False, "stage2": False, "stage3": False } }
tp_stages_fired = {}


# ============================================================
# MAIN LOOP
# ============================================================

async def start_exit_manager():
    print("[EXIT] Starting exit manager...")
    while True:
        try:
            await check_all_positions()
        except Exception as e:
            print(f"[EXIT] Loop error: {e}")
            # Import inside except to avoid circular import on startup
            try:
                from telegram_bot import alert_bot_error
                await alert_bot_error("ExitManager", str(e))
            except Exception:
                pass
        await asyncio.sleep(CHECK_INTERVAL)


# ============================================================
# CHECK ALL OPEN POSITIONS
# ============================================================

async def check_all_positions():
    # Import here to avoid circular imports
    from database import get_open_positions

    positions = get_open_positions()
    if not positions:
        return

    print(f"[EXIT] Checking {len(positions)} open position(s)...")

    for position in positions:
        try:
            await evaluate_position(position)
        except Exception as e:
            ticker = position.get("ticker", "???")
            print(f"[EXIT] Error evaluating {ticker}: {e}")


# ============================================================
# EVALUATE ONE POSITION
# ============================================================

async def evaluate_position(position):
    token_address = position.get("token_address", "")
    token_name    = position.get("token_name", "Unknown")
    ticker        = position.get("ticker", "???")
    paper         = position.get("paper_trade", True)

    # Safe float conversion — never crashes on None or empty string
    try:
        entry_price = float(position.get("price_usd") or 0)
        amount_sol  = float(position.get("amount_sol") or 0)
    except (TypeError, ValueError):
        print(f"[EXIT] {ticker} — invalid price/amount data, skipping")
        return

    if entry_price <= 0 or amount_sol <= 0:
        print(f"[EXIT] {ticker} — missing entry data, skipping")
        return

    # Get current price
    current_price = get_current_price(token_address)

    if current_price is None:
        # API unavailable — try again next cycle
        print(f"[EXIT] {ticker} — price API unavailable, retrying")
        return

    if current_price <= 0:
        print(f"[EXIT] {ticker} — price is 0, token may be dead")
        return

    # Current multiplier vs entry
    multiplier = current_price / entry_price

    # Initialize stage tracking for this token
    if token_address not in tp_stages_fired:
        tp_stages_fired[token_address] = {
            "stage1": False,
            "stage2": False,
            "stage3": False
        }

    stages = tp_stages_fired[token_address]

    # ── STOP LOSS — checked first, capital protection ──────
    loss_pct = (1 - multiplier) * 100
    if multiplier <= (1 - STOP_LOSS_PCT / 100):
        print(f"[EXIT] 🛑 STOP LOSS: {ticker} | -{loss_pct:.1f}%")
        sol_lost = round(amount_sol * (STOP_LOSS_PCT / 100), 4)
        await execute_sell(
            token_address, token_name, ticker,
            sell_pct=100,
            amount_sol=amount_sol,
            current_price=current_price,
            reason="STOP_LOSS",
            paper=paper
        )
        try:
            from telegram_bot import alert_stop_loss
            await alert_stop_loss(
                ticker, token_name, token_address,
                loss_pct, sol_lost, paper
            )
        except Exception as e:
            print(f"[EXIT] Telegram alert error: {e}")
        # Mark fully exited and clean up
        try:
            from database import mark_position_exited
            mark_position_exited(token_address)
        except Exception as e:
            print(f"[EXIT] mark_position_exited error: {e}")
        if token_address in tp_stages_fired:
            del tp_stages_fired[token_address]
        return

    # ── TAKE PROFIT STAGE 3 — 50x → sell last 25% ─────────
    if not stages["stage3"] and multiplier >= TP_STAGE_3_X:
        stages["stage3"] = True
        sol_returned = round(amount_sol * 0.25 * multiplier, 4)
        await execute_sell(
            token_address, token_name, ticker,
            sell_pct=25,
            amount_sol=amount_sol * 0.25,
            current_price=current_price,
            reason="TP_STAGE_3",
            paper=paper
        )
        try:
            from telegram_bot import alert_take_profit
            await alert_take_profit(
                ticker, token_name, token_address,
                stage=3, multiplier=multiplier,
                sol_returned=sol_returned,
                remaining_pct=0, paper=paper
            )
        except Exception as e:
            print(f"[EXIT] Telegram alert error: {e}")
        # All stages done — mark fully exited
        try:
            from database import mark_position_exited
            mark_position_exited(token_address)
        except Exception as e:
            print(f"[EXIT] mark_position_exited error: {e}")
        if token_address in tp_stages_fired:
            del tp_stages_fired[token_address]
        return

    # ── TAKE PROFIT STAGE 2 — 25x → sell 25% ──────────────
    if not stages["stage2"] and multiplier >= TP_STAGE_2_X:
        stages["stage2"] = True
        sol_returned = round(amount_sol * 0.25 * multiplier, 4)
        await execute_sell(
            token_address, token_name, ticker,
            sell_pct=25,
            amount_sol=amount_sol * 0.25,
            current_price=current_price,
            reason="TP_STAGE_2",
            paper=paper
        )
        try:
            from telegram_bot import alert_take_profit
            await alert_take_profit(
                ticker, token_name, token_address,
                stage=2, multiplier=multiplier,
                sol_returned=sol_returned,
                remaining_pct=25, paper=paper
            )
        except Exception as e:
            print(f"[EXIT] Telegram alert error: {e}")
        return

    # ── TAKE PROFIT STAGE 1 — 10x → sell 50% ──────────────
    if not stages["stage1"] and multiplier >= TP_STAGE_1_X:
        stages["stage1"] = True
        sol_returned = round(amount_sol * 0.50 * multiplier, 4)
        await execute_sell(
            token_address, token_name, ticker,
            sell_pct=50,
            amount_sol=amount_sol * 0.50,
            current_price=current_price,
            reason="TP_STAGE_1",
            paper=paper
        )
        try:
            from telegram_bot import alert_take_profit
            await alert_take_profit(
                ticker, token_name, token_address,
                stage=1, multiplier=multiplier,
                sol_returned=sol_returned,
                remaining_pct=50, paper=paper
            )
        except Exception as e:
            print(f"[EXIT] Telegram alert error: {e}")
        return

    # Nothing triggered — log status
    print(
        f"[EXIT] {ticker} — {multiplier:.2f}x | "
        f"TP1:{stages['stage1']} "
        f"TP2:{stages['stage2']} "
        f"TP3:{stages['stage3']}"
    )


# ============================================================
# EXECUTE SELL
# ============================================================

async def execute_sell(token_address, token_name, ticker,
                        sell_pct, amount_sol, current_price,
                        reason, paper):
    # Get entry price safely
    entry_price = get_entry_price(token_address)
    sol_returned = round(amount_sol * (current_price / entry_price), 4)

    if paper:
        try:
            from database import log_trade
            log_trade(
                token_address=token_address,
                token_name=token_name,
                ticker=ticker,
                action="SELL",
                price_usd=current_price,
                mcap_usd=0,
                amount_sol=sol_returned,
                score=0,
                source=reason,
                paper_trade=True
            )
        except Exception as e:
            print(f"[EXIT] log_trade error: {e}")
        print(
            f"[EXIT] 📝 Paper sell: {ticker} | "
            f"{sell_pct}% | {sol_returned} SOL | {reason}"
        )
        return

    # Live sell — Jupiter reverse swap
    try:
        from executor import (
            get_swap_transaction, sign_transaction,
            send_transaction, confirm_transaction
        )
        LAMPORTS = 1_000_000_000
        token_amount = int(amount_sol * LAMPORTS)

        quote = await get_jupiter_quote_reverse(token_address, token_amount)
        if not quote:
            print(f"[EXIT] No sell quote for {ticker}")
            return

        swap_tx   = await get_swap_transaction(quote)
        signed    = sign_transaction(swap_tx)
        sig       = await send_transaction(signed)
        confirmed = await confirm_transaction(sig)

        if confirmed:
            try:
                from database import log_trade
                log_trade(
                    token_address=token_address,
                    token_name=token_name,
                    ticker=ticker,
                    action="SELL",
                    price_usd=current_price,
                    mcap_usd=0,
                    amount_sol=sol_returned,
                    score=0,
                    source=reason,
                    paper_trade=False
                )
            except Exception as e:
                print(f"[EXIT] log_trade error: {e}")
            print(f"[EXIT] ✅ Live sell confirmed: {ticker} | {reason}")
        else:
            print(f"[EXIT] ❌ Sell TX not confirmed: {ticker}")

    except Exception as e:
        print(f"[EXIT] Live sell error for {ticker}: {e}")


# ============================================================
# JUPITER REVERSE QUOTE — token → SOL
# ============================================================

async def get_jupiter_quote_reverse(token_address, token_amount):
    import aiohttp
    SOL_MINT = "So11111111111111111111111111111111111111112"
    try:
        params = {
            "inputMint":   token_address,
            "outputMint":  SOL_MINT,
            "amount":      token_amount,
            "slippageBps": 300,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://quote-api.jup.ag/v6/quote",
                params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if data.get("routePlan") else None
    except Exception as e:
        print(f"[EXIT] Reverse quote error: {e}")
        return None


# ============================================================
# HELPERS
# ============================================================

def get_current_price(token_address):
    """
    Returns float  — current price in USD
    Returns None   — API unavailable (retry next cycle)
    Returns 0      — token has no price / dead
    """
    try:
        url      = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=6)
        data     = response.json()
        pairs    = data.get("pairs", [])
        if not pairs:
            return 0
        best  = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        price = best.get("priceUsd", 0)
        return float(price) if price else 0
    except Exception as e:
        print(f"[EXIT] get_current_price error: {e}")
        return None


def get_entry_price(token_address):
    """Gets original buy price from DB — returns 1 as safe fallback"""
    try:
        from database import supabase
        result = supabase.table("trades") \
            .select("price_usd") \
            .eq("token_address", token_address) \
            .eq("action", "BUY") \
            .order("timestamp", desc=False) \
            .limit(1) \
            .execute()
        if result.data:
            price = result.data[0].get("price_usd", 1)
            return float(price) if price else 1
        return 1
    except Exception as e:
        print(f"[EXIT] get_entry_price error: {e}")
        return 1

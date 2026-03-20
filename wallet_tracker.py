# ============================================================
# wallet_tracker.py — SMART WALLET COPY TRADING ENGINE
# Engine 2 — tracks wallets with 80%+ win rate
# Mirrors their buys after passing full filter + score checks
# Runs parallel to listener — never blocks it
# ============================================================

import asyncio
import aiohttp
import json
import websockets
from datetime import datetime
from config import (
    HELIUS_WS_URL, HELIUS_API_KEY,
    MIN_WALLET_WIN_RATE, MIN_WALLET_TRADES,
    API_CALL_DELAY_SECS, MAX_CONCURRENT_CHECKS
)
from database import (
    get_all_smart_wallets,
    token_already_seen,
    mark_token_seen,
    save_smart_wallet
)
from filters import run_hard_filters
from scorer import score_token, calculate_position_size
from telegram_bot import (
    alert_smart_wallet_buy,
    alert_new_token_detected,
    alert_filter_rejected,
    alert_bot_error
)

# Rate limiter shared with listener
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


# ============================================================
# MAIN ENTRY — auto-reconnects forever
# ============================================================

async def start_wallet_tracker():
    print("[WALLET] Starting smart wallet tracker...")
    while True:
        try:
            await connect_and_track()
        except Exception as e:
            print(f"[WALLET] Connection lost: {e}")
            await alert_bot_error("WalletTracker",
                f"Disconnected — reconnecting in 5s")
            await asyncio.sleep(5)


async def connect_and_track():
    smart_wallets = get_all_smart_wallets()

    if not smart_wallets:
        print("[WALLET] ⚠️ No smart wallets in DB yet")
        print("[WALLET] Add wallets via add_smart_wallet() then restart")
        # Sleep and retry — wallets may be added later
        await asyncio.sleep(60)
        return

    print(f"[WALLET] Tracking {len(smart_wallets)} smart wallet(s)")

    async with websockets.connect(
        HELIUS_WS_URL,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
        print("[WALLET] ✅ Connected — watching smart wallets")

        # Subscribe to each smart wallet's transactions
        for i, wallet_address in enumerate(smart_wallets):
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id":      i + 100,  # Offset from listener IDs
                "method":  "logsSubscribe",
                "params":  [
                    {"mentions": [wallet_address]},
                    {"commitment": "confirmed"}
                ]
            }
            await ws.send(json.dumps(subscribe_msg))

        print(f"[WALLET] Subscribed to {len(smart_wallets)} wallet(s)")

        # Listen forever
        async for raw_message in ws:
            try:
                message = json.loads(raw_message)
                await process_wallet_message(message, smart_wallets)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"[WALLET] Message error: {e}")
                continue


# ============================================================
# PROCESS INCOMING WALLET TRANSACTIONS
# ============================================================

async def process_wallet_message(message, smart_wallets):
    # Skip confirmations
    if "result" in message and "error" not in message:
        return

    try:
        params    = message.get("params", {})
        result    = params.get("result", {})
        value     = result.get("value", {})
        logs      = value.get("logs", [])
        signature = value.get("signature", "")

        if not logs or not signature:
            return

        # Only care about swap/buy transactions
        is_swap = (
            any("swap"      in log.lower() for log in logs) or
            any("Swap"      in log         for log in logs) or
            any("buy"       in log.lower() for log in logs) or
            any("exchange"  in log.lower() for log in logs)
        )

        if not is_swap:
            return

        # Get full transaction details
        tx_info = await fetch_wallet_transaction(signature)
        if not tx_info:
            return

        wallet_address = tx_info.get("wallet_address", "")
        token_address  = tx_info.get("token_address", "")

        # Validate
        if not wallet_address or not token_address:
            return
        if len(token_address) < 30:
            return

        # Confirm this is actually one of our tracked wallets
        if wallet_address not in smart_wallets:
            return

        # Get wallet win rate from DB for alert
        win_rate = get_wallet_win_rate(wallet_address)

        print(f"[WALLET] 🧠 Smart wallet buy: "
              f"{wallet_address[:8]}... → {token_address[:20]}...")

        # Duplicate protection — don't buy what we already hold
        if token_already_seen(token_address):
            print(f"[WALLET] Already seen {token_address[:20]}... — skipping")
            return

        # Alert that smart wallet bought
        token_name, ticker = await get_token_name_ticker(token_address)

        await alert_smart_wallet_buy(
            wallet_address=wallet_address,
            ticker=ticker,
            token_name=token_name,
            token_address=token_address,
            wallet_win_rate=win_rate
        )

        # Rate limit protection
        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            await process_copy_trade(
                token_address, token_name,
                ticker, wallet_address
            )

    except Exception as e:
        print(f"[WALLET] process_wallet_message error: {e}")


# ============================================================
# COPY TRADE PIPELINE
# ============================================================

async def process_copy_trade(token_address, token_name,
                              ticker, wallet_address):
    deploy_time = datetime.utcnow()  # Treat as fresh token

    # Step 1 — Hard filters (same strict rules as Engine 1)
    passed, reason = run_hard_filters(token_address)

    if not passed:
        await alert_filter_rejected(ticker, token_address, reason)
        mark_token_seen(
            token_address, token_name,
            score=0, decision="FILTERED"
        )
        print(f"[WALLET] {ticker} failed filters: {reason}")
        return

    # Step 2 — AI Score (same engine as Engine 1)
    score, breakdown, recommendation = score_token(
        token_address, token_name, ticker, deploy_time
    )

    # For copy trades we use slightly lower threshold (75 vs 80)
    # because smart wallet entry IS a strong signal itself
    COPY_TRADE_MIN_SCORE = 75

    if score < COPY_TRADE_MIN_SCORE:
        mark_token_seen(
            token_address, token_name,
            score=score, decision="SKIPPED"
        )
        print(f"[WALLET] {ticker} score too low: {score}/100")
        return

    # Step 3 — Execute buy
    mark_token_seen(
        token_address, token_name,
        score=score, decision="BOUGHT"
    )

    # Add copy trade source to breakdown
    short_wallet = f"{wallet_address[:6]}...{wallet_address[-4:]}"
    breakdown["copy_source"] = f"Smart wallet {short_wallet}"

    await alert_new_token_detected(
        ticker, token_name, token_address,
        score, breakdown, source="COPY_TRADE"
    )

    from executor import execute_buy
    await execute_buy(
        token_address=token_address,
        token_name=token_name,
        ticker=ticker,
        score=score,
        source="COPY_TRADE"
    )


# ============================================================
# FETCH TRANSACTION DETAILS
# ============================================================

async def fetch_wallet_transaction(signature):
    """
    Gets full transaction data and extracts:
    - which wallet made the swap
    - which token they bought
    """
    try:
        url     = f"https://api.helius.xyz/v0/transactions?api-key={HELIUS_API_KEY}"
        payload = {"transactions": [signature]}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list):
                    return None

                tx = data[0]
                return extract_swap_info(tx)

    except Exception as e:
        print(f"[WALLET] fetch_wallet_transaction error: {e}")
        return None


def extract_swap_info(tx):
    """
    Extracts wallet address and token bought from transaction
    """
    try:
        fee_payer       = tx.get("feePayer", "")
        token_transfers = tx.get("tokenTransfers", [])

        if not fee_payer or not token_transfers:
            return None

        # Find the token that was received (positive amount = bought)
        token_address = None
        for transfer in token_transfers:
            # Positive tokenAmount = tokens received = this is what was bought
            amount = transfer.get("tokenAmount", 0)
            mint   = transfer.get("mint", "")
            to     = transfer.get("toUserAccount", "")

            if (float(amount) > 0 and
                mint and len(mint) > 30 and
                to == fee_payer):
                token_address = mint
                break

        if not token_address:
            return None

        # Skip SOL and known stablecoins
        SKIP_TOKENS = {
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
        }
        if token_address in SKIP_TOKENS:
            return None

        return {
            "wallet_address": fee_payer,
            "token_address":  token_address
        }

    except Exception as e:
        print(f"[WALLET] extract_swap_info error: {e}")
        return None


# ============================================================
# HELPERS
# ============================================================

async def get_token_name_ticker(token_address):
    """Gets token name and ticker from DexScreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status != 200:
                    return "Unknown", "???"
                data  = await resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    base = pairs[0].get("baseToken", {})
                    return (
                        base.get("name",   "Unknown"),
                        base.get("symbol", "???")
                    )
    except Exception:
        pass
    return "Unknown", "???"


def get_wallet_win_rate(wallet_address):
    """Gets win rate for a wallet from DB"""
    try:
        from database import supabase
        result = supabase.table("smart_wallets") \
            .select("win_rate") \
            .eq("wallet_address", wallet_address) \
            .execute()
        if result.data:
            return result.data[0].get("win_rate", 0)
        return 0
    except Exception:
        return 0


# ============================================================
# UTILITY — Add smart wallets to DB manually
# Run this once to seed your initial wallet list
# ============================================================

def add_smart_wallet(wallet_address, win_rate,
                     total_trades, avg_multiplier, notes=""):
    """
    Call this to add a known good wallet to the tracker.
    Example:
        add_smart_wallet(
            "ABC123...",
            win_rate=85,
            total_trades=50,
            avg_multiplier=12.5,
            notes="Top Pump.fun trader"
        )
    """
    if win_rate < MIN_WALLET_WIN_RATE:
        print(f"[WALLET] Rejected — win rate {win_rate}% below minimum {MIN_WALLET_WIN_RATE}%")
        return False

    if total_trades < MIN_WALLET_TRADES:
        print(f"[WALLET] Rejected — only {total_trades} trades, need {MIN_WALLET_TRADES}+")
        return False

    save_smart_wallet(
        wallet_address=wallet_address,
        win_rate=win_rate,
        total_trades=total_trades,
        avg_multiplier=avg_multiplier,
        notes=notes
    )
    print(f"[WALLET] ✅ Added: {wallet_address[:20]}... | "
          f"Win rate: {win_rate}% | Trades: {total_trades}")
    return True

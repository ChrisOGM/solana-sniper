# ============================================================
# wallet_tracker.py — AUTONOMOUS SMART WALLET ENGINE
# Self-discovers, scores, and copy trades top Solana wallets
# Profit-optimized — targets wallets with highest multipliers
# ============================================================

import asyncio
import aiohttp
import json
import websockets
import requests
from datetime import datetime, timedelta
from config import (
    HELIUS_WS_URL, HELIUS_API_KEY,
    MIN_WALLET_WIN_RATE, MIN_WALLET_TRADES,
    API_CALL_DELAY_SECS, MAX_CONCURRENT_CHECKS
)
from database import (
    get_all_smart_wallets,
    save_smart_wallet,
    token_already_seen,
    mark_token_seen
)
from filters import run_hard_filters
from scorer import score_token

# ── Discovery Settings ────────────────────────────────────
DISCOVERY_INTERVAL    = 6 * 60 * 60   # Run discovery every 6 hours
MIN_WIN_MULTIPLIER    = 3.0            # Token must have 3x'd to count as win
MIN_AVG_MULTIPLIER    = 5.0            # Wallet avg multiplier must be 5x+
MAX_WALLET_AGE_DAYS   = 30             # Ignore wallets inactive 30+ days
COPY_TRADE_MIN_SCORE  = 70             # Lower than AI discovery (80)
                                       # Smart wallet buy IS a signal itself

# ── Tokens to never trade ─────────────────────────────────
STABLE_TOKENS = {
    "So11111111111111111111111111111111111111112",   # SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", # BONK
}

# Rate limiter
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_wallet_tracker():
    print("[WALLET] 🚀 Autonomous smart wallet engine starting...")
    await asyncio.gather(
        wallet_discovery_loop(),
        copy_trade_loop(),
        return_exceptions=True
    )


# ============================================================
# ENGINE 1 — WALLET DISCOVERY (every 6 hours)
# ============================================================

async def wallet_discovery_loop():
    # Run immediately on startup then every 6 hours
    while True:
        try:
            print("[WALLET] 🔍 Starting wallet discovery scan...")
            await discover_smart_wallets()
        except Exception as e:
            print(f"[WALLET] Discovery error: {e}")
        print(f"[WALLET] Next discovery in 6 hours")
        await asyncio.sleep(DISCOVERY_INTERVAL)


async def discover_smart_wallets():
    """
    Full autonomous discovery pipeline:
    1. Find tokens that pumped hard recently
    2. Find wallets that bought them early
    3. Score each wallet by win rate + multiplier
    4. Save best wallets to DB automatically
    """
    # Step 1 — Get pumped tokens from multiple sources
    pumped_tokens = await get_pumped_tokens()
    if not pumped_tokens:
        print("[WALLET] No pumped tokens found this cycle")
        return

    print(f"[WALLET] Analyzing {len(pumped_tokens)} pumped tokens...")

    # Step 2 — Find early buyers of each pumped token
    # wallet_data = { address: { wins, losses, multipliers, last_seen } }
    wallet_data = {}

    for token in pumped_tokens[:30]:  # Top 30 tokens
        try:
            token_address   = token.get("token_address", "")
            peak_multiplier = float(token.get("peak_multiplier", 1))

            if not token_address or len(token_address) < 30:
                continue

            early_buyers = await get_early_buyers(token_address)

            for wallet in early_buyers:
                if not wallet or len(wallet) < 30:
                    continue
                if wallet in STABLE_TOKENS:
                    continue

                if wallet not in wallet_data:
                    wallet_data[wallet] = {
                        "wins":        0,
                        "losses":      0,
                        "multipliers": [],
                        "last_seen":   datetime.utcnow()
                    }

                if peak_multiplier >= MIN_WIN_MULTIPLIER:
                    wallet_data[wallet]["wins"] += 1
                    wallet_data[wallet]["multipliers"].append(peak_multiplier)
                else:
                    wallet_data[wallet]["losses"] += 1

            await asyncio.sleep(0.3)

        except Exception as e:
            print(f"[WALLET] Token scan error: {e}")
            continue

    # Step 3 — Score and save qualifying wallets
    existing  = set(get_all_smart_wallets())
    new_count = 0
    updated   = 0

    for wallet_address, data in wallet_data.items():
        try:
            total  = data["wins"] + data["losses"]
            if total < MIN_WALLET_TRADES:
                continue

            win_rate = (data["wins"] / total) * 100
            if win_rate < MIN_WALLET_WIN_RATE:
                continue

            avg_mult = (
                sum(data["multipliers"]) / len(data["multipliers"])
                if data["multipliers"] else 1.0
            )

            # Profit filter — only wallets averaging 5x+
            if avg_mult < MIN_AVG_MULTIPLIER:
                continue

            is_new = wallet_address not in existing

            save_smart_wallet(
                wallet_address=wallet_address,
                win_rate=round(win_rate, 1),
                total_trades=total,
                avg_multiplier=round(avg_mult, 2),
                notes=(
                    f"Auto-discovered | "
                    f"{win_rate:.0f}% WR | "
                    f"{avg_mult:.1f}x avg | "
                    f"{data['wins']}W/{data['losses']}L"
                )
            )

            if is_new:
                existing.add(wallet_address)
                new_count += 1
                print(
                    f"[WALLET] ✅ New: {wallet_address[:16]}... | "
                    f"WR: {win_rate:.0f}% | Avg: {avg_mult:.1f}x"
                )
            else:
                updated += 1

        except Exception as e:
            print(f"[WALLET] Save error: {e}")

    total_tracked = len(existing)
    print(
        f"[WALLET] Discovery done — "
        f"{new_count} new | {updated} updated | "
        f"{total_tracked} total tracked"
    )

    # Send Telegram summary
    try:
        from telegram_bot import send_alert
        if new_count > 0 or updated > 0:
            await send_alert(
                f"🧠 *WALLET DISCOVERY COMPLETE*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ New wallets found: *{new_count}*\n"
                f"🔄 Wallets updated: *{updated}*\n"
                f"👀 Total tracked: *{total_tracked}*\n\n"
                f"All wallets require:\n"
                f"• {MIN_WALLET_WIN_RATE}%+ win rate\n"
                f"• {MIN_AVG_MULTIPLIER}x+ average gain\n"
                f"• {MIN_WALLET_TRADES}+ trade history\n"
                f"Copy trading active for all ✅"
            )
    except Exception as e:
        print(f"[WALLET] Summary alert error: {e}")


# ============================================================
# GET PUMPED TOKENS — multiple sources for reliability
# ============================================================

async def get_pumped_tokens():
    """
    Pulls recently pumped Solana tokens from multiple sources
    Combines results for maximum coverage
    """
    all_tokens = []

    # Source 1 — DexScreener gainers
    try:
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs", [])
                    for pair in pairs:
                        if pair.get("chainId") != "solana":
                            continue
                        change = float(
                            pair.get("priceChange", {}).get("h24", 0) or 0
                        )
                        if change >= 150:
                            addr = pair.get("baseToken", {}).get("address", "")
                            if addr and addr not in STABLE_TOKENS:
                                all_tokens.append({
                                    "token_address":   addr,
                                    "peak_multiplier": (change / 100) + 1
                                })
    except Exception as e:
        print(f"[WALLET] DexScreener source error: {e}")

    # Source 2 — DexScreener boosted tokens
    try:
        url = "https://api.dexscreener.com/token-boosts/latest/v1"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for item in data:
                            if item.get("chainId") == "solana":
                                addr = item.get("tokenAddress", "")
                                if addr and addr not in STABLE_TOKENS:
                                    all_tokens.append({
                                        "token_address":   addr,
                                        "peak_multiplier": 5.0
                                    })
    except Exception as e:
        print(f"[WALLET] Boosted tokens source error: {e}")

    # Source 3 — Pump.fun recent launches via Helius
    try:
        pump_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        url = (
            f"https://api.helius.xyz/v0/addresses/{pump_program}"
            f"/transactions?api-key={HELIUS_API_KEY}&limit=20"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    txs = await resp.json()
                    if isinstance(txs, list):
                        for tx in txs:
                            for transfer in tx.get("tokenTransfers", []):
                                mint = transfer.get("mint", "")
                                if mint and mint not in STABLE_TOKENS and len(mint) > 30:
                                    all_tokens.append({
                                        "token_address":   mint,
                                        "peak_multiplier": 3.0
                                    })
    except Exception as e:
        print(f"[WALLET] Pump.fun source error: {e}")

    # Deduplicate by token address
    seen    = set()
    unique  = []
    for t in all_tokens:
        addr = t.get("token_address", "")
        if addr and addr not in seen:
            seen.add(addr)
            unique.append(t)

    print(f"[WALLET] Found {len(unique)} unique pumped tokens")
    return unique


# ============================================================
# GET EARLY BUYERS
# ============================================================

async def get_early_buyers(token_address):
    """
    Gets wallets that bought a token in its first transactions
    Earlier = smarter money
    """
    try:
        # Get first 100 transactions of this token
        url = (
            f"https://api.helius.xyz/v0/addresses/{token_address}"
            f"/transactions?api-key={HELIUS_API_KEY}&limit=100"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return []
                txs = await resp.json()
                if not isinstance(txs, list):
                    return []

                buyers = []
                for tx in txs:
                    fee_payer = tx.get("feePayer", "")
                    if not fee_payer or len(fee_payer) < 30:
                        continue

                    # Check if this wallet received the token (bought it)
                    for transfer in tx.get("tokenTransfers", []):
                        if (transfer.get("mint") == token_address and
                                float(transfer.get("tokenAmount", 0) or 0) > 0 and
                                transfer.get("toUserAccount") == fee_payer):
                            buyers.append(fee_payer)
                            break

                # Return unique buyers — first 20 are the smart money
                unique_buyers = list(dict.fromkeys(buyers))
                return unique_buyers[:20]

    except Exception as e:
        print(f"[WALLET] get_early_buyers error: {e}")
        return []


# ============================================================
# ENGINE 2 — COPY TRADE LOOP (runs 24/7)
# ============================================================

async def copy_trade_loop():
    """Watches all tracked wallets and copies their buys in real time"""
    print("[WALLET] Copy trade monitor starting...")
    while True:
        try:
            await connect_and_copy()
        except Exception as e:
            print(f"[WALLET] Copy trade lost connection: {e}")
            try:
                from telegram_bot import alert_bot_error
                await alert_bot_error("WalletCopyTrade", "Reconnecting in 5s")
            except Exception:
                pass
            await asyncio.sleep(5)


async def connect_and_copy():
    smart_wallets = get_all_smart_wallets()

    if not smart_wallets:
        print("[WALLET] No wallets tracked yet — discovery running in background")
        await asyncio.sleep(30)
        return

    print(f"[WALLET] 👀 Copy trading {len(smart_wallets)} wallet(s) live")

    async with websockets.connect(
        HELIUS_WS_URL,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
        # Subscribe to all tracked wallets
        for i, wallet in enumerate(smart_wallets):
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id":      i + 200,
                "method":  "logsSubscribe",
                "params":  [
                    {"mentions": [wallet]},
                    {"commitment": "confirmed"}
                ]
            }))

        print(f"[WALLET] ✅ Subscribed to {len(smart_wallets)} wallets")

        # Listen for transactions
        async for raw in ws:
            try:
                msg = json.loads(raw)
                await handle_wallet_message(msg, set(smart_wallets))
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"[WALLET] Message error: {e}")


async def handle_wallet_message(message, smart_wallets):
    if "result" in message and "error" not in message:
        return

    try:
        params    = message.get("params", {})
        value     = params.get("result", {}).get("value", {})
        logs      = value.get("logs", [])
        signature = value.get("signature", "")

        if not logs or not signature:
            return

        # Only swap transactions
        log_text = " ".join(logs).lower()
        if not any(w in log_text for w in ["swap", "buy", "exchange"]):
            return

        # Get transaction details
        tx = await fetch_transaction(signature)
        if not tx:
            return

        wallet  = tx.get("wallet_address", "")
        token   = tx.get("token_address", "")

        if not wallet or not token:
            return
        if len(token) < 30:
            return
        if token in STABLE_TOKENS:
            return
        if wallet not in smart_wallets:
            return
        if token_already_seen(token):
            return

        print(f"[WALLET] 🎯 Smart wallet buying: {wallet[:8]}... → {token[:16]}...")

        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            await execute_copy_trade(wallet, token)

    except Exception as e:
        print(f"[WALLET] handle_wallet_message error: {e}")


# ============================================================
# EXECUTE COPY TRADE
# ============================================================

async def execute_copy_trade(wallet_address, token_address):
    token_name, ticker = await get_token_details(token_address)
    deploy_time        = datetime.utcnow()
    win_rate           = get_wallet_win_rate(wallet_address)

    # Alert — smart wallet detected
    try:
        from telegram_bot import alert_smart_wallet_buy
        await alert_smart_wallet_buy(
            wallet_address=wallet_address,
            ticker=ticker,
            token_name=token_name,
            token_address=token_address,
            wallet_win_rate=win_rate
        )
    except Exception as e:
        print(f"[WALLET] Alert error: {e}")

    # Hard filters
    passed, reason = run_hard_filters(token_address)
    if not passed:
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        print(f"[WALLET] {ticker} filtered: {reason}")
        return

    # AI Score
    score, breakdown, _ = score_token(
        token_address, token_name, ticker, deploy_time
    )

    if score < COPY_TRADE_MIN_SCORE:
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        print(f"[WALLET] {ticker} score too low: {score}/100 (need {COPY_TRADE_MIN_SCORE}+)")
        return

    # Execute
    mark_token_seen(token_address, token_name, score=score, decision="BOUGHT")
    short = f"{wallet_address[:6]}...{wallet_address[-4:]}"
    breakdown["copy_source"] = f"Wallet {short} ({win_rate}% WR)"

    try:
        from telegram_bot import alert_new_token_detected
        await alert_new_token_detected(
            ticker, token_name, token_address,
            score, breakdown, "COPY_TRADE"
        )
    except Exception as e:
        print(f"[WALLET] Alert error: {e}")

    try:
        from executor import execute_buy
        await execute_buy(
            token_address=token_address,
            token_name=token_name,
            ticker=ticker,
            score=score,
            source="COPY_TRADE"
        )
    except Exception as e:
        print(f"[WALLET] Execute buy error: {e}")


# ============================================================
# HELPERS
# ============================================================

async def fetch_transaction(signature):
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

                tx        = data[0]
                fee_payer = tx.get("feePayer", "")
                if not fee_payer:
                    return None

                token_address = None
                for transfer in tx.get("tokenTransfers", []):
                    amount = float(transfer.get("tokenAmount", 0) or 0)
                    mint   = transfer.get("mint", "")
                    to     = transfer.get("toUserAccount", "")
                    if (amount > 0 and mint and
                            len(mint) > 30 and
                            mint not in STABLE_TOKENS and
                            to == fee_payer):
                        token_address = mint
                        break

                if not token_address:
                    return None

                return {
                    "wallet_address": fee_payer,
                    "token_address":  token_address
                }
    except Exception as e:
        print(f"[WALLET] fetch_transaction error: {e}")
        return None


async def get_token_details(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status == 200:
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
    try:
        from database import supabase
        if not supabase:
            return 0
        result = supabase.table("smart_wallets") \
            .select("win_rate") \
            .eq("wallet_address", wallet_address) \
            .execute()
        if result.data:
            return result.data[0].get("win_rate", 0)
    except Exception:
        pass
    return 0

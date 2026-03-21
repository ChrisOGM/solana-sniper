# ============================================================
# wallet_tracker.py — AUTONOMOUS SMART WALLET ENGINE
# Fixed: WebSocket alerts only after 3 consecutive failures
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

DISCOVERY_INTERVAL    = 6 * 60 * 60
MIN_WIN_MULTIPLIER    = 3.0
MIN_AVG_MULTIPLIER    = 5.0
COPY_TRADE_MIN_SCORE  = 70
ALERT_AFTER_FAILURES  = 3  # Only alert after 3 consecutive failures

STABLE_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
}

semaphore              = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
copy_trade_failures    = 0


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_wallet_tracker():
    print("[WALLET] Starting autonomous smart wallet engine...")
    await asyncio.gather(
        wallet_discovery_loop(),
        copy_trade_loop(),
        return_exceptions=True
    )


# ============================================================
# ENGINE 1 — WALLET DISCOVERY
# ============================================================

async def wallet_discovery_loop():
    print("[WALLET] Wallet discovery engine started")
    while True:
        try:
            print("[WALLET] 🔍 Scanning for smart wallets...")
            await discover_smart_wallets()
        except Exception as e:
            print(f"[WALLET] Discovery error: {e}")
        print(f"[WALLET] Next discovery in 6 hours")
        await asyncio.sleep(DISCOVERY_INTERVAL)


async def discover_smart_wallets():
    pumped_tokens = await get_pumped_tokens()
    if not pumped_tokens:
        print("[WALLET] No pumped tokens found")
        return

    print(f"[WALLET] Analyzing {len(pumped_tokens)} pumped tokens...")
    wallet_data = {}

    for token in pumped_tokens[:30]:
        try:
            token_address   = token.get("token_address", "")
            peak_multiplier = float(token.get("peak_multiplier", 1))
            if not token_address or len(token_address) < 30:
                continue

            early_buyers = await get_early_buyers(token_address)
            for wallet in early_buyers:
                if not wallet or len(wallet) < 30 or wallet in STABLE_TOKENS:
                    continue
                if wallet not in wallet_data:
                    wallet_data[wallet] = {"wins": 0, "losses": 0, "multipliers": []}
                if peak_multiplier >= MIN_WIN_MULTIPLIER:
                    wallet_data[wallet]["wins"] += 1
                    wallet_data[wallet]["multipliers"].append(peak_multiplier)
                else:
                    wallet_data[wallet]["losses"] += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[WALLET] Token scan error: {e}")

    existing  = set(get_all_smart_wallets())
    new_count = 0

    for wallet_address, data in wallet_data.items():
        try:
            total    = data["wins"] + data["losses"]
            if total < MIN_WALLET_TRADES:
                continue
            win_rate = (data["wins"] / total) * 100
            if win_rate < MIN_WALLET_WIN_RATE:
                continue
            avg_mult = (
                sum(data["multipliers"]) / len(data["multipliers"])
                if data["multipliers"] else 1.0
            )
            if avg_mult < MIN_AVG_MULTIPLIER:
                continue
            if wallet_address in existing:
                continue

            save_smart_wallet(
                wallet_address=wallet_address,
                win_rate=round(win_rate, 1),
                total_trades=total,
                avg_multiplier=round(avg_mult, 2),
                notes=f"Auto | {win_rate:.0f}% WR | {avg_mult:.1f}x avg"
            )
            existing.add(wallet_address)
            new_count += 1
            print(f"[WALLET] ✅ New: {wallet_address[:16]}... | WR: {win_rate:.0f}%")
        except Exception as e:
            print(f"[WALLET] Save error: {e}")

    print(f"[WALLET] Discovery done — {new_count} new wallets")

    if new_count > 0:
        try:
            from telegram_bot import send_alert
            await send_alert(
                f"🧠 *WALLET DISCOVERY*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ New wallets: *{new_count}*\n"
                f"👀 Total tracked: *{len(existing)}*\n"
                f"Copy trading active ✅"
            )
        except Exception:
            pass


async def get_pumped_tokens():
    all_tokens = []
    try:
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs", [])
                    for pair in pairs:
                        if pair.get("chainId") != "solana":
                            continue
                        change = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                        if change >= 150:
                            addr = pair.get("baseToken", {}).get("address", "")
                            if addr and addr not in STABLE_TOKENS:
                                all_tokens.append({
                                    "token_address":   addr,
                                    "peak_multiplier": (change / 100) + 1
                                })
    except Exception as e:
        print(f"[WALLET] DexScreener error: {e}")

    try:
        url = "https://api.dexscreener.com/token-boosts/latest/v1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
        print(f"[WALLET] Boosted tokens error: {e}")

    seen   = set()
    unique = []
    for t in all_tokens:
        addr = t.get("token_address", "")
        if addr and addr not in seen:
            seen.add(addr)
            unique.append(t)
    return unique


async def get_early_buyers(token_address):
    try:
        url = (
            f"https://api.helius.xyz/v0/addresses/{token_address}"
            f"/transactions?api-key={HELIUS_API_KEY}&limit=100"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
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
            for transfer in tx.get("tokenTransfers", []):
                if (transfer.get("mint") == token_address and
                        float(transfer.get("tokenAmount", 0) or 0) > 0 and
                        transfer.get("toUserAccount") == fee_payer):
                    buyers.append(fee_payer)
                    break

        unique = list(dict.fromkeys(buyers))
        return unique[:20]
    except Exception as e:
        print(f"[WALLET] get_early_buyers error: {e}")
        return []


# ============================================================
# ENGINE 2 — COPY TRADE
# ============================================================

async def copy_trade_loop():
    global copy_trade_failures
    print("[WALLET] Copy trade monitor starting...")
    while True:
        try:
            copy_trade_failures = 0
            await connect_and_copy()
        except Exception as e:
            copy_trade_failures += 1
            print(f"[WALLET] Copy trade lost connection ({copy_trade_failures}): {e}")

            # Only alert after 3 consecutive failures
            if copy_trade_failures >= ALERT_AFTER_FAILURES:
                try:
                    from telegram_bot import alert_bot_error
                    await alert_bot_error(
                        "WalletCopyTrade",
                        f"Reconnecting after {copy_trade_failures} drops"
                    )
                    copy_trade_failures = 0
                except Exception:
                    pass

            await asyncio.sleep(5)


async def connect_and_copy():
    smart_wallets = get_all_smart_wallets()
    if not smart_wallets:
        print("[WALLET] No wallets tracked yet")
        await asyncio.sleep(60)
        return

    print(f"[WALLET] 👀 Copy trading {len(smart_wallets)} wallet(s)")

    async with websockets.connect(
        HELIUS_WS_URL,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
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

        log_text = " ".join(logs).lower()
        if not any(w in log_text for w in ["swap", "buy", "exchange"]):
            return

        tx = await fetch_transaction(signature)
        if not tx:
            return

        wallet = tx.get("wallet_address", "")
        token  = tx.get("token_address", "")

        if not wallet or not token or len(token) < 30:
            return
        if token in STABLE_TOKENS or wallet not in smart_wallets:
            return
        if token_already_seen(token):
            return

        print(f"[WALLET] 🎯 Smart wallet buying: {wallet[:8]}...")

        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            await execute_copy_trade(wallet, token)

    except Exception as e:
        print(f"[WALLET] handle_wallet_message error: {e}")


async def execute_copy_trade(wallet_address, token_address):
    token_name, ticker = await get_token_details(token_address)
    deploy_time        = datetime.utcnow()
    win_rate           = get_wallet_win_rate(wallet_address)

    try:
        from telegram_bot import alert_smart_wallet_buy
        await alert_smart_wallet_buy(
            wallet_address, ticker, token_name,
            token_address, win_rate
        )
    except Exception:
        pass

    passed, reason = run_hard_filters(token_address)
    if not passed:
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        return

    score, breakdown, _ = score_token(token_address, token_name, ticker, deploy_time)

    if score < COPY_TRADE_MIN_SCORE:
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        return

    mark_token_seen(token_address, token_name, score=score, decision="BOUGHT")
    short = f"{wallet_address[:6]}...{wallet_address[-4:]}"
    breakdown["copy_source"] = f"Wallet {short} ({win_rate}% WR)"

    try:
        from telegram_bot import alert_new_token_detected
        await alert_new_token_detected(
            ticker, token_name, token_address,
            score, breakdown, "COPY_TRADE"
        )
    except Exception:
        pass

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
                    if (amount > 0 and mint and len(mint) > 30 and
                            mint not in STABLE_TOKENS and to == fee_payer):
                        token_address = mint
                        break
                if not token_address:
                    return None
                return {"wallet_address": fee_payer, "token_address": token_address}
    except Exception as e:
        print(f"[WALLET] fetch_transaction error: {e}")
        return None


async def get_token_details(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        base = pairs[0].get("baseToken", {})
                        return base.get("name", "Unknown"), base.get("symbol", "???")
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

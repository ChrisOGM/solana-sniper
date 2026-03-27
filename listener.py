# ============================================================
# listener.py — SOLANA TOKEN LISTENER
# Based on verified working Pump.fun bot implementations
# Uses blockSubscribe + create instruction filter
# Pump.fun program: 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
# ============================================================

import asyncio
import json
import aiohttp
import websockets
from datetime import datetime
from config import HELIUS_API_KEY, API_CALL_DELAY_SECS, MAX_CONCURRENT_CHECKS
from filters import run_hard_filters
from scorer import score_token
from database import token_already_seen, mark_token_seen
from telegram_bot import alert_filter_rejected

# ── Pump.fun program ID (verified from working bots) ──────
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# ── Stable tokens to skip ─────────────────────────────────
IGNORE_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

semaphore   = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
seen_sigs   = set()  # Deduplicate transactions


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_listener():
    print("[LISTENER] Starting Pump.fun token listener...")
    while True:
        try:
            await connect_and_listen()
        except Exception as e:
            print(f"[LISTENER] Reconnecting in 10s: {e}")
            await asyncio.sleep(10)


async def connect_and_listen():
    # Use Helius for reliable WebSocket
    ws_url = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

    async with websockets.connect(
        ws_url,
        ping_interval=30,
        ping_timeout=15,
        close_timeout=5,
        max_size=10_000_000
    ) as ws:
        print("[LISTENER] ✅ Connected to Solana mainnet")

        # Subscribe using logsSubscribe to Pump.fun program
        # This is the verified working method from Chainstack docs
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "logsSubscribe",
            "params":  [
                {"mentions": [PUMP_FUN_PROGRAM]},
                {"commitment": "confirmed"}
            ]
        }))

        print(f"[LISTENER] Subscribed to Pump.fun: {PUMP_FUN_PROGRAM}")
        print("[LISTENER] 👀 Watching for new token launches...")

        async for raw in ws:
            try:
                msg = json.loads(raw)
                await handle_message(msg)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"[LISTENER] Error: {e}")


# ============================================================
# HANDLE MESSAGE
# ============================================================

async def handle_message(msg):
    # Skip subscription confirmations
    if "result" in msg and isinstance(msg.get("result"), int):
        print(f"[LISTENER] Subscription confirmed: {msg['result']}")
        return

    try:
        params    = msg.get("params", {})
        result    = params.get("result", {})
        value     = result.get("value", {})
        logs      = value.get("logs", [])
        signature = value.get("signature", "")
        err       = value.get("err", None)

        # Skip failed transactions — key fix from working bots
        if err is not None:
            return

        if not logs or not signature:
            return

        # Skip already seen
        if signature in seen_sigs:
            return

        # Check for create instruction — verified pattern from working bots
        # Pump.fun emits "Create" when a new token is launched
        is_create = any(
            "Instruction: Create" in log or
            "create" in log.lower() and "pump" in log.lower()
            for log in logs
        )

        if not is_create:
            return

        seen_sigs.add(signature)

        # Keep set manageable
        if len(seen_sigs) > 10000:
            oldest = list(seen_sigs)[:5000]
            for s in oldest:
                seen_sigs.discard(s)

        print(f"[LISTENER] 🎯 New token create: {signature[:20]}...")

        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            await process_signature(signature)

    except Exception as e:
        print(f"[LISTENER] handle_message error: {e}")


# ============================================================
# PROCESS SIGNATURE
# ============================================================

async def process_signature(signature):
    """
    Gets full transaction details from Helius Enhanced API
    and extracts the new token mint address
    """
    try:
        url     = f"https://api.helius.xyz/v0/transactions?api-key={HELIUS_API_KEY}"
        payload = {"transactions": [signature]}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 429:
                    print("[LISTENER] Rate limited — waiting 10s")
                    await asyncio.sleep(10)
                    return
                if resp.status != 200:
                    return
                data = await resp.json()
                if not data or not isinstance(data, list):
                    return

                tx = data[0]
                await extract_and_process_token(tx)

    except Exception as e:
        print(f"[LISTENER] process_signature error: {e}")


async def extract_and_process_token(tx):
    """
    Extracts token mint from Helius enhanced transaction.
    Based on Chainstack working bot implementation.
    """
    try:
        # Get postTokenBalances — this is where the new mint appears
        post_token_balances = tx.get("meta", {})
        if not post_token_balances:
            post_token_balances = {}

        token_transfers = tx.get("tokenTransfers", [])
        account_data    = tx.get("accountData", [])
        timestamp       = tx.get("timestamp", None)

        deploy_time = (
            datetime.utcfromtimestamp(timestamp)
            if timestamp else datetime.utcnow()
        )

        mint_address = None

        # Method 1 — tokenTransfers (most reliable for Pump.fun)
        for transfer in token_transfers:
            mint = transfer.get("mint", "")
            if mint and len(mint) > 30 and mint not in IGNORE_MINTS:
                mint_address = mint
                break

        # Method 2 — accountData with large SOL spend (mint rent)
        if not mint_address:
            for account in account_data:
                addr   = account.get("account", "")
                change = account.get("nativeBalanceChange", 0)
                # New token accounts have negative SOL change for rent
                if change < -1388880 and addr and len(addr) > 30:
                    if addr not in IGNORE_MINTS:
                        mint_address = addr
                        break

        if not mint_address:
            return

        # Skip if already seen
        if token_already_seen(mint_address):
            return

        print(f"[LISTENER] 🪙 Token found: {mint_address[:20]}...")

        # Get name from Pump.fun API directly (faster than DexScreener for new tokens)
        token_name, ticker = await get_pump_token_info(mint_address)

        token_info = {
            "token_address": mint_address,
            "token_name":    token_name,
            "ticker":        ticker,
            "deploy_time":   deploy_time,
            "source":        "AI_DISCOVERY"
        }

        await run_pipeline(token_info)

    except Exception as e:
        print(f"[LISTENER] extract_and_process_token error: {e}")


# ============================================================
# GET TOKEN INFO
# ============================================================

async def get_pump_token_info(mint_address):
    """
    Gets token name and ticker.
    Tries Pump.fun API first (fastest for new tokens)
    then falls back to DexScreener.
    """
    # Try Pump.fun API first
    try:
        url = f"https://frontend-api.pump.fun/coins/{mint_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    name   = data.get("name",   "Unknown")
                    symbol = data.get("symbol", "???")
                    if name and name != "Unknown":
                        return name, symbol
    except Exception:
        pass

    # Fallback to DexScreener
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        base = pairs[0].get("baseToken", {})
                        return base.get("name", "Unknown"), base.get("symbol", "???")
    except Exception:
        pass

    return "Unknown", "???"


# ============================================================
# FULL PIPELINE
# ============================================================

async def run_pipeline(token_info):
    token_address = token_info["token_address"]
    token_name    = token_info["token_name"]
    ticker        = token_info["ticker"]
    deploy_time   = token_info["deploy_time"]
    source        = token_info["source"]

    # Hard filters
    passed, reason = run_hard_filters(token_address)
    if not passed:
        await alert_filter_rejected(ticker, token_address, reason)
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        print(f"[PIPELINE] ❌ {ticker}: {reason}")
        return

    # AI Score
    score, breakdown, recommendation = score_token(
        token_address, token_name, ticker, deploy_time
    )

    print(f"[PIPELINE] 📊 {ticker}: {score}/100 → {recommendation}")

    if recommendation == "SKIP":
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        return

    # Buy
    mark_token_seen(token_address, token_name, score=score, decision="BOUGHT")

    from telegram_bot import alert_new_token_detected
    await alert_new_token_detected(
        ticker, token_name, token_address,
        score, breakdown, source
    )

    from executor import execute_buy
    await execute_buy(
        token_address=token_address,
        token_name=token_name,
        ticker=ticker,
        score=score,
        source=source
    )

# ============================================================
# listener.py — SOLANA BLOCKCHAIN LISTENER
# Watches entire Solana chain via Helius WebSocket
# Auto-reconnects — never goes blind silently
# ============================================================

import asyncio
import json
import websockets
import aiohttp
from datetime import datetime
from config import (
    HELIUS_WS_URL, HELIUS_API_KEY,
    MONITORED_PROGRAMS, API_CALL_DELAY_SECS,
    MAX_CONCURRENT_CHECKS
)
from filters import run_hard_filters
from scorer import score_token, calculate_position_size
from database import token_already_seen, mark_token_seen
from telegram_bot import alert_filter_rejected, alert_bot_error

# Limits concurrent token checks — protects free API rate limits
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


# ============================================================
# MAIN ENTRY — auto-reconnects forever
# ============================================================

async def start_listener():
    print("[LISTENER] Starting Solana chain listener...")
    while True:
        try:
            await connect_and_listen()
        except Exception as e:
            print(f"[LISTENER] Connection lost: {e}")
            await alert_bot_error("Listener", f"WebSocket dropped — reconnecting in 5s")
            await asyncio.sleep(5)
            print("[LISTENER] Reconnecting...")


async def connect_and_listen():
    async with websockets.connect(
        HELIUS_WS_URL,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
        print("[LISTENER] ✅ Connected to Solana via Helius")

        # Subscribe to all launchpad programs simultaneously
        for i, program_id in enumerate(MONITORED_PROGRAMS):
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [program_id]},
                    {"commitment": "confirmed"}
                ]
            }
            await ws.send(json.dumps(subscribe_msg))
            print(f"[LISTENER] Subscribed: {program_id[:20]}...")

        # Listen forever
        async for raw_message in ws:
            try:
                message = json.loads(raw_message)
                await process_message(message)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"[LISTENER] Message error: {e}")
                continue


# ============================================================
# PROCESS INCOMING MESSAGES
# ============================================================

async def process_message(message):
    # Skip subscription confirmations
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

        # Detect new token deployments across all launchpads
        is_new_token = (
            any("InitializeMint"   in log for log in logs) or
            any("MintTo"           in log for log in logs) or
            any("initialize"       in log.lower() and
                "mint"             in log.lower() for log in logs) or
            any("create"           in log.lower() and
                "mint"             in log.lower() for log in logs)
        )

        if not is_new_token:
            return

        print(f"[LISTENER] New deployment: {signature[:20]}...")

        token_info = await fetch_token_from_signature(signature)
        if not token_info:
            return

        token_address = token_info.get("token_address", "")

        # Guard: skip empty or invalid addresses
        if not token_address or len(token_address) < 30:
            return

        # Duplicate protection
        if token_already_seen(token_address):
            return

        # Process with rate limiting
        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            await process_new_token(token_info)

    except Exception as e:
        print(f"[LISTENER] process_message error: {e}")


# ============================================================
# FETCH TOKEN FROM TRANSACTION
# ============================================================

async def fetch_token_from_signature(signature):
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
                return extract_token_info(data[0])

    except Exception as e:
        print(f"[LISTENER] fetch_token error: {e}")
        return None


def extract_token_info(tx):
    try:
        token_transfers = tx.get("tokenTransfers", [])
        account_data    = tx.get("accountData", [])
        token_address   = None

        # Find the newly created mint
        for transfer in token_transfers:
            mint = transfer.get("mint", "")
            if mint and len(mint) > 30:  # Valid Solana address length
                token_address = mint
                break

        # Fallback — scan account data
        if not token_address:
            for account in account_data:
                addr = account.get("account", "")
                if addr and len(addr) > 30:
                    token_address = addr
                    break

        # If still nothing — skip this transaction
        if not token_address:
            return None

        timestamp   = tx.get("timestamp", None)
        deploy_time = (
            datetime.utcfromtimestamp(timestamp)
            if timestamp else datetime.utcnow()
        )

        return {
            "token_address": token_address,
            "token_name":    "Unknown",
            "ticker":        "???",
            "deploy_time":   deploy_time,
            "source":        "AI_DISCOVERY"
        }

    except Exception as e:
        print(f"[LISTENER] extract_token_info error: {e}")
        return None


# ============================================================
# ENRICH — get real name and ticker from DexScreener
# ============================================================

async def enrich_token_data(token_info):
    token_address = token_info["token_address"]
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status != 200:
                    return token_info
                data  = await resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    base = pairs[0].get("baseToken", {})
                    token_info["token_name"] = base.get("name",   "Unknown")
                    token_info["ticker"]     = base.get("symbol", "???")
    except Exception as e:
        print(f"[LISTENER] enrich error: {e}")
    return token_info


# ============================================================
# FULL PIPELINE — filter → score → buy
# ============================================================

async def process_new_token(token_info):
    token_address = token_info["token_address"]
    deploy_time   = token_info["deploy_time"]
    source        = token_info["source"]

    # Step 1 — Get real name/ticker
    token_info = await enrich_token_data(token_info)
    token_name = token_info["token_name"]
    ticker     = token_info["ticker"]

    print(f"[PIPELINE] {ticker} ({token_address[:20]}...)")

    # Step 2 — Hard filters
    passed, reason = run_hard_filters(token_address)

    if not passed:
        await alert_filter_rejected(ticker, token_address, reason)
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        return

    # Step 3 — AI Scoring
    score, breakdown, recommendation = score_token(
        token_address, token_name, ticker, deploy_time
    )

    if recommendation == "SKIP":
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        print(f"[PIPELINE] Skipped {ticker} — {score}/100")
        return

    # Step 4 — Execute buy
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

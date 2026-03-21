# ============================================================
# listener.py — SOLANA BLOCKCHAIN LISTENER
# Auto-reconnects silently — only alerts after 3 failures
# ============================================================

import asyncio
import json
import aiohttp
import websockets
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

semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

# Only send Telegram alert after this many consecutive failures
# Silences the spam from frequent free-tier disconnects
ALERT_AFTER_FAILURES = 3
consecutive_failures = 0


# ============================================================
# MAIN LISTENER
# ============================================================

async def start_listener():
    global consecutive_failures
    print("[LISTENER] Starting Solana chain listener...")
    while True:
        try:
            consecutive_failures = 0  # Reset on successful connect
            await connect_and_listen()
        except Exception as e:
            consecutive_failures += 1
            print(f"[LISTENER] Connection lost ({consecutive_failures}): {e}")

            # Only alert Telegram after 3 consecutive failures
            # Prevents spam from normal free-tier disconnects
            if consecutive_failures >= ALERT_AFTER_FAILURES:
                try:
                    await alert_bot_error(
                        "Listener",
                        f"WebSocket dropped {consecutive_failures}x — reconnecting"
                    )
                    consecutive_failures = 0  # Reset after alerting
                except Exception:
                    pass

            await asyncio.sleep(5)


async def connect_and_listen():
    async with websockets.connect(
        HELIUS_WS_URL,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
        print("[LISTENER] ✅ Connected to Solana via Helius")

        for i, program_id in enumerate(MONITORED_PROGRAMS):
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [program_id]},
                    {"commitment": "confirmed"}
                ]
            }))

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
# PROCESS MESSAGES
# ============================================================

async def process_message(message):
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

        is_new_token = (
            any("InitializeMint" in log for log in logs) or
            any("MintTo"         in log for log in logs) or
            any("initialize" in log.lower() and "mint" in log.lower() for log in logs) or
            any("create"     in log.lower() and "mint" in log.lower() for log in logs)
        )

        if not is_new_token:
            return

        token_info = await fetch_token_from_signature(signature)
        if not token_info:
            return

        token_address = token_info.get("token_address", "")
        if not token_address or len(token_address) < 30:
            return

        if token_already_seen(token_address):
            return

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

        for transfer in token_transfers:
            mint = transfer.get("mint", "")
            if mint and len(mint) > 30:
                token_address = mint
                break

        if not token_address:
            for account in account_data:
                addr = account.get("account", "")
                if addr and len(addr) > 30:
                    token_address = addr
                    break

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


async def enrich_token_data(token_info):
    token_address = token_info["token_address"]
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
                        token_info["token_name"] = base.get("name",   "Unknown")
                        token_info["ticker"]     = base.get("symbol", "???")
    except Exception:
        pass
    return token_info


async def process_new_token(token_info):
    token_address = token_info["token_address"]
    deploy_time   = token_info["deploy_time"]
    source        = token_info["source"]

    token_info = await enrich_token_data(token_info)
    token_name = token_info["token_name"]
    ticker     = token_info["ticker"]

    passed, reason = run_hard_filters(token_address)
    if not passed:
        await alert_filter_rejected(ticker, token_address, reason)
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        return

    score, breakdown, recommendation = score_token(
        token_address, token_name, ticker, deploy_time
    )

    if recommendation == "SKIP":
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        return

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

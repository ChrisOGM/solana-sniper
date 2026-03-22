# ============================================================
# listener.py — SOLANA TOKEN LISTENER
# Rewritten based on how working Pump.fun bots actually detect tokens
# Uses correct log patterns: "Create" instruction, not InitializeMint
# Handles both Pump.fun and PumpSwap (new DEX)
# ============================================================

import asyncio
import json
import aiohttp
import websockets
import base64
import struct
from datetime import datetime
from config import (
    HELIUS_API_KEY,
    HELIUS_WS_URL,
    API_CALL_DELAY_SECS,
    MAX_CONCURRENT_CHECKS
)
from filters import run_hard_filters
from scorer import score_token
from database import token_already_seen, mark_token_seen
from telegram_bot import alert_filter_rejected

# ── Program IDs ───────────────────────────────────────────
PUMP_FUN_PROGRAM    = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP_PROGRAM   = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"  # PumpSwap AMM
RAYDIUM_PROGRAM     = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
METEORA_PROGRAM     = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"

# ── Token detection patterns (what working bots actually look for) ─
# Pump.fun emits these specific strings in logs when a token is created
CREATE_PATTERNS = [
    "Program log: Instruction: Create",
    "Program log: Instruction: Create_v2",
    "Program log: Instruction: Initialize",
    "InitializeMint2",
    "Program log: Create",
]

# ── Stable tokens to ignore ───────────────────────────────
IGNORE_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_listener():
    print("[LISTENER] Starting Solana token listener...")
    print(f"[LISTENER] Watching: Pump.fun + PumpSwap + Raydium + Meteora")
    while True:
        try:
            await connect_and_listen()
        except Exception as e:
            print(f"[LISTENER] Reconnecting in 10s: {e}")
            await asyncio.sleep(10)


async def connect_and_listen():
    # Use Helius WebSocket with API key for reliable connection
    ws_url = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

    async with websockets.connect(
        ws_url,
        ping_interval=30,
        ping_timeout=10,
        close_timeout=5,
        max_size=10_000_000  # 10MB max message size
    ) as ws:
        print("[LISTENER] ✅ Connected to Solana mainnet via Helius")

        # Subscribe to Pump.fun program logs
        # This is how working bots detect new token launches
        subscription_id = 1
        for program_id in [PUMP_FUN_PROGRAM, PUMP_SWAP_PROGRAM,
                           RAYDIUM_PROGRAM, METEORA_PROGRAM]:
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id":      subscription_id,
                "method":  "logsSubscribe",
                "params":  [
                    {"mentions": [program_id]},
                    {"commitment": "confirmed"}
                ]
            }))
            subscription_id += 1

        print("[LISTENER] Subscribed to all Solana launchpads")

        async for raw in ws:
            try:
                msg = json.loads(raw)
                await handle_message(msg)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"[LISTENER] Message error: {e}")


# ============================================================
# HANDLE INCOMING MESSAGES
# ============================================================

async def handle_message(msg):
    """
    Filters messages for new token creation events.
    Working bots look for specific log strings, not just any transaction.
    """
    # Skip subscription confirmations
    if "result" in msg and "error" not in msg:
        return

    try:
        params    = msg.get("params", {})
        result    = params.get("result", {})
        value     = result.get("value", {})
        logs      = value.get("logs", [])
        signature = value.get("signature", "")
        err       = value.get("err", None)

        # Skip failed transactions
        if err is not None:
            return

        if not logs or not signature:
            return

        # Check if this transaction contains a token creation instruction
        # This is the key fix — working bots check for specific log strings
        is_new_token = any(
            pattern in log
            for log in logs
            for pattern in CREATE_PATTERNS
        )

        if not is_new_token:
            return

        print(f"[LISTENER] 🎯 New token event: {signature[:20]}...")

        # Process with rate limiting
        async with semaphore:
            await asyncio.sleep(API_CALL_DELAY_SECS)
            token_info = await get_token_from_signature(signature, logs)
            if token_info:
                await process_new_token(token_info)

    except Exception as e:
        print(f"[LISTENER] handle_message error: {e}")


# ============================================================
# GET TOKEN INFO FROM TRANSACTION
# ============================================================

async def get_token_from_signature(signature, logs):
    """
    Extracts token mint address from transaction.
    Uses Helius Enhanced Transactions API for structured data.
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
                    print("[LISTENER] Rate limited — waiting 5s")
                    await asyncio.sleep(5)
                    return None
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list):
                    return None
                return extract_token_from_tx(data[0], logs)

    except Exception as e:
        print(f"[LISTENER] get_token_from_signature error: {e}")
        return None


def extract_token_from_tx(tx, logs):
    """
    Extracts the newly created token mint from a transaction.
    Checks tokenTransfers first, then accountData.
    """
    try:
        # Method 1 — Check tokenTransfers (most reliable)
        token_transfers = tx.get("tokenTransfers", [])
        for transfer in token_transfers:
            mint = transfer.get("mint", "")
            if mint and len(mint) > 30 and mint not in IGNORE_MINTS:
                return build_token_info(mint, tx)

        # Method 2 — Check account data for new mints
        account_data = tx.get("accountData", [])
        for account in account_data:
            # New mints have a large negative SOL change (rent deposit)
            native_change = account.get("nativeBalanceChange", 0)
            addr          = account.get("account", "")
            if (native_change < -1000000 and  # Spent SOL for rent
                    addr and len(addr) > 30 and
                    addr not in IGNORE_MINTS):
                return build_token_info(addr, tx)

        # Method 3 — Extract from logs directly
        # Pump.fun logs contain the mint address
        for log in logs:
            if "mint:" in log.lower():
                parts = log.split()
                for part in parts:
                    if len(part) > 30 and is_valid_base58(part):
                        if part not in IGNORE_MINTS:
                            return build_token_info(part, tx)

        return None

    except Exception as e:
        print(f"[LISTENER] extract_token_from_tx error: {e}")
        return None


def build_token_info(mint_address, tx):
    """Builds token info dict from mint address and transaction"""
    timestamp   = tx.get("timestamp", None)
    deploy_time = (
        datetime.utcfromtimestamp(timestamp)
        if timestamp else datetime.utcnow()
    )
    return {
        "token_address": mint_address,
        "token_name":    "Unknown",
        "ticker":        "???",
        "deploy_time":   deploy_time,
        "source":        "AI_DISCOVERY"
    }


def is_valid_base58(s):
    """Quick check if string looks like a valid Solana address"""
    valid = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(c in valid for c in s) and 32 <= len(s) <= 44


# ============================================================
# ENRICH TOKEN DATA
# ============================================================

async def enrich_token_data(token_info):
    """Gets real name and ticker from DexScreener"""
    token_address = token_info["token_address"]
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
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

    # Also try Pump.fun API directly for very new tokens
    if token_info["token_name"] == "Unknown":
        try:
            url = f"https://frontend-api.pump.fun/coins/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token_info["token_name"] = data.get("name",   "Unknown")
                        token_info["ticker"]     = data.get("symbol", "???")
        except Exception:
            pass

    return token_info


# ============================================================
# PROCESS NEW TOKEN — full pipeline
# ============================================================

async def process_new_token(token_info):
    token_address = token_info["token_address"]
    deploy_time   = token_info["deploy_time"]
    source        = token_info["source"]

    # Duplicate check
    if token_already_seen(token_address):
        return

    # Enrich with real name/ticker
    token_info = await enrich_token_data(token_info)
    token_name = token_info["token_name"]
    ticker     = token_info["ticker"]

    print(f"[PIPELINE] Analyzing: {ticker} ({token_address[:20]}...)")

    # Hard filters
    passed, reason = run_hard_filters(token_address)
    if not passed:
        await alert_filter_rejected(ticker, token_address, reason)
        mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
        print(f"[PIPELINE] ❌ Filtered: {ticker} — {reason}")
        return

    # AI Score
    score, breakdown, recommendation = score_token(
        token_address, token_name, ticker, deploy_time
    )

    print(f"[PIPELINE] Score: {ticker} = {score}/100 → {recommendation}")

    if recommendation == "SKIP":
        mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
        return

    # Buy signal
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

# ============================================================
# executor.py — JUPITER SWAP EXECUTION ENGINE
# Handles all buys in correct Jupiter V6 sequence
# Paper trading mode: logs everything, spends nothing
# ============================================================

import aiohttp
import asyncio
import base64
import json
import requests
from config import (
    WALLET_PRIVATE_KEY, WALLET_PUBLIC_KEY,
    HELIUS_RPC_URL, PAPER_TRADING
)
from scorer import calculate_position_size
from database import log_trade
from telegram_bot import alert_buy_executed, alert_bot_error

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"
SOL_MINT          = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL  = 1_000_000_000
SLIPPAGE_BPS      = 300  # 3% slippage tolerance


# ============================================================
# MAIN EXECUTE BUY
# ============================================================

async def execute_buy(token_address, token_name, ticker,
                      score, source):
    print(f"[EXECUTOR] Buy signal: {ticker} | Score: {score}")

    # ── Step 1: Get wallet SOL balance ───────────────────
    balance_sol = await get_wallet_balance()
    if balance_sol is None:
        await alert_bot_error("Executor", f"Could not fetch wallet balance for {ticker}")
        return

    if balance_sol < 0.01:
        print(f"[EXECUTOR] Wallet too low ({balance_sol} SOL) — skipping {ticker}")
        return

    # ── Step 2: Calculate position size ──────────────────
    amount_sol = calculate_position_size(score, balance_sol)
    if amount_sol <= 0:
        print(f"[EXECUTOR] Position size 0 — skipping")
        return

    amount_lamports = int(amount_sol * LAMPORTS_PER_SOL)

    print(f"[EXECUTOR] Buying {amount_sol} SOL worth of {ticker}")

    # ── PAPER TRADING MODE ────────────────────────────────
    if PAPER_TRADING:
        await handle_paper_buy(
            token_address, token_name, ticker,
            amount_sol, score, source
        )
        return

    # ── LIVE TRADING MODE ─────────────────────────────────
    await handle_live_buy(
        token_address, token_name, ticker,
        amount_sol, amount_lamports, score, source
    )


# ============================================================
# PAPER TRADING BUY — no real money, full simulation
# ============================================================

async def handle_paper_buy(token_address, token_name, ticker,
                            amount_sol, score, source):
    # Get current price from DexScreener
    price_usd, mcap_usd = get_current_price(token_address)

    # Log as paper trade
    log_trade(
        token_address=token_address,
        token_name=token_name,
        ticker=ticker,
        action="BUY",
        price_usd=price_usd,
        mcap_usd=mcap_usd,
        amount_sol=amount_sol,
        score=score,
        source=source,
        paper_trade=True
    )

    await alert_buy_executed(
        ticker=ticker,
        token_name=token_name,
        token_address=token_address,
        amount_sol=amount_sol,
        price_usd=price_usd,
        mcap_usd=mcap_usd,
        score=score,
        paper=True
    )
    print(f"[EXECUTOR] 📝 Paper buy logged: {ticker} | {amount_sol} SOL")


# ============================================================
# LIVE TRADING BUY — real Jupiter swap
# ============================================================

async def handle_live_buy(token_address, token_name, ticker,
                           amount_sol, amount_lamports,
                           score, source):
    try:
        # Step 1 — Get Jupiter quote
        quote = await get_jupiter_quote(token_address, amount_lamports)
        if not quote:
            await alert_bot_error("Executor", f"No Jupiter quote for {ticker}")
            return

        # Step 2 — Build swap transaction
        swap_tx = await get_swap_transaction(quote)
        if not swap_tx:
            await alert_bot_error("Executor", f"Could not build swap tx for {ticker}")
            return

        # Step 3 — Sign transaction
        signed_tx = sign_transaction(swap_tx)
        if not signed_tx:
            await alert_bot_error("Executor", f"Could not sign tx for {ticker}")
            return

        # Step 4 — Send to Solana via Helius
        tx_signature = await send_transaction(signed_tx)
        if not tx_signature:
            await alert_bot_error("Executor", f"Send tx failed for {ticker}")
            return

        # Step 5 — Wait for confirmation
        confirmed = await confirm_transaction(tx_signature)
        if not confirmed:
            await alert_bot_error("Executor",
                f"TX not confirmed for {ticker} — sig: {tx_signature[:20]}...")
            return

        # Step 6 — Log confirmed trade
        price_usd, mcap_usd = get_current_price(token_address)

        log_trade(
            token_address=token_address,
            token_name=token_name,
            ticker=ticker,
            action="BUY",
            price_usd=price_usd,
            mcap_usd=mcap_usd,
            amount_sol=amount_sol,
            score=score,
            source=source,
            paper_trade=False
        )

        await alert_buy_executed(
            ticker=ticker,
            token_name=token_name,
            token_address=token_address,
            amount_sol=amount_sol,
            price_usd=price_usd,
            mcap_usd=mcap_usd,
            score=score,
            paper=False
        )

        print(f"[EXECUTOR] ✅ Live buy confirmed: {ticker} | TX: {tx_signature[:20]}...")

    except Exception as e:
        print(f"[EXECUTOR] Live buy error: {e}")
        await alert_bot_error("Executor", f"Buy failed for {ticker}: {e}")


# ============================================================
# JUPITER API CALLS
# ============================================================

async def get_jupiter_quote(token_address, amount_lamports):
    """Gets best swap route from Jupiter"""
    try:
        params = {
            "inputMint":   SOL_MINT,
            "outputMint":  token_address,
            "amount":      amount_lamports,
            "slippageBps": SLIPPAGE_BPS,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                JUPITER_QUOTE_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    print(f"[EXECUTOR] Jupiter quote status: {resp.status}")
                    return None
                data = await resp.json()
                # Check quote has valid route
                if not data.get("routePlan"):
                    print(f"[EXECUTOR] No route found")
                    return None
                return data
    except Exception as e:
        print(f"[EXECUTOR] Quote error: {e}")
        return None


async def get_swap_transaction(quote):
    """Builds the swap transaction from a Jupiter quote"""
    try:
        payload = {
            "quoteResponse":             quote,
            "userPublicKey":             WALLET_PUBLIC_KEY,
            "wrapAndUnwrapSol":          True,
            "prioritizationFeeLamports": 100000,  # Priority fee prevents tx drop
            "dynamicComputeUnitLimit":   True
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                JUPITER_SWAP_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    print(f"[EXECUTOR] Swap build status: {resp.status}")
                    return None
                data = await resp.json()
                return data.get("swapTransaction")
    except Exception as e:
        print(f"[EXECUTOR] Swap build error: {e}")
        return None


def sign_transaction(swap_tx_base64):
    """Signs the base64 transaction with your private key"""
    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction

        # Decode the transaction
        raw_tx = base64.b64decode(swap_tx_base64)
        tx     = VersionedTransaction.from_bytes(raw_tx)

        # Load keypair from private key
        keypair = Keypair.from_base58_string(WALLET_PRIVATE_KEY)

        # Sign
        tx.sign([keypair])

        # Return as base64
        return base64.b64encode(bytes(tx)).decode("utf-8")

    except Exception as e:
        print(f"[EXECUTOR] Sign error: {e}")
        return None


async def send_transaction(signed_tx_base64):
    """Sends signed transaction to Solana via Helius RPC"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "sendTransaction",
            "params":  [
                signed_tx_base64,
                {
                    "encoding":            "base64",
                    "skipPreflight":       False,
                    "preflightCommitment": "confirmed",
                    "maxRetries":          3
                }
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    print(f"[EXECUTOR] RPC error: {data['error']}")
                    return None
                return data.get("result")  # Transaction signature
    except Exception as e:
        print(f"[EXECUTOR] Send tx error: {e}")
        return None


async def confirm_transaction(signature, max_retries=20):
    """Polls Solana until transaction is confirmed or times out"""
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getSignatureStatuses",
        "params":  [[signature]]
    }
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HELIUS_RPC_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    data    = await resp.json()
                    results = data.get("result", {}).get("value", [None])
                    status  = results[0] if results else None

                    if status:
                        confirmation = status.get("confirmationStatus", "")
                        if confirmation in ("confirmed", "finalized"):
                            print(f"[EXECUTOR] ✅ TX confirmed: {signature[:20]}...")
                            return True
                        err = status.get("err")
                        if err:
                            print(f"[EXECUTOR] TX failed on chain: {err}")
                            return False

        except Exception as e:
            print(f"[EXECUTOR] Confirm poll error: {e}")

        await asyncio.sleep(3)  # Wait 3s between polls

    print(f"[EXECUTOR] TX confirmation timeout: {signature[:20]}...")
    return False


# ============================================================
# HELPERS
# ============================================================

async def get_wallet_balance():
    """Gets current SOL balance of trading wallet"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "getBalance",
            "params":  [WALLET_PUBLIC_KEY]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                data    = await resp.json()
                lamports = data.get("result", {}).get("value", 0)
                balance  = lamports / LAMPORTS_PER_SOL
                print(f"[EXECUTOR] Wallet balance: {balance:.4f} SOL")
                return balance
    except Exception as e:
        print(f"[EXECUTOR] Balance check error: {e}")
        return None


def get_current_price(token_address):
    """Returns (price_usd, mcap_usd) from DexScreener"""
    try:
        url      = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=6)
        data     = response.json()
        pairs    = data.get("pairs", [])
        if not pairs:
            return 0.0, 0.0
        best = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        price   = float(best.get("priceUsd", 0) or 0)
        mcap    = float(best.get("marketCap", 0) or 0)
        return price, mcap
    except Exception as e:
        print(f"[EXECUTOR] Price fetch error: {e}")
        return 0.0, 0.0

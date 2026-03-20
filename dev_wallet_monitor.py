# ============================================================
# dev_wallet_monitor.py — DEV WALLET MONITOR
# Tracks wallets that launched successful tokens before
# Detects SOL accumulation = launch incoming
# Alerts BEFORE the token even deploys
# ============================================================

import asyncio
import aiohttp
import requests
from datetime import datetime, timedelta
from config import HELIUS_API_KEY, HELIUS_WS_URL

LAMPORTS                    = 1_000_000_000
SOL_ACCUMULATION_THRESHOLD  = 2.0    # SOL received in 24hrs = pre-launch signal
WATCH_DURATION_MINS         = 120    # Watch for deploy for 2 hours
REFRESH_INTERVAL            = 1800   # Refresh wallet list every 30 mins
CHECK_INTERVAL              = 60     # Check each wallet every 60 seconds

# Track accumulation and alerts
accumulation_tracker = {}   # { wallet: { sol_received, last_updated } }
alerted_wallets      = set() # Wallets already sent pre-launch alert
deploy_watchers      = set() # Wallets currently being watched for deploy


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_dev_wallet_monitor():
    print("[DEVMON] Starting dev wallet monitor...")
    await asyncio.gather(
        accumulation_monitor_loop(),
        periodic_wallet_refresh(),
        return_exceptions=True
    )


# ============================================================
# ACCUMULATION MONITOR
# Polls dev wallets periodically for SOL accumulation
# WebSocket account subscription is unreliable on free tier
# Polling is more stable and predictable
# ============================================================

async def accumulation_monitor_loop():
    while True:
        try:
            dev_wallets = get_dev_wallets()
            if not dev_wallets:
                print("[DEVMON] No dev wallets in DB yet — waiting for discovery")
                await asyncio.sleep(300)
                continue

            print(f"[DEVMON] Checking {len(dev_wallets)} dev wallets for SOL accumulation...")

            for wallet in dev_wallets:
                try:
                    await analyze_wallet_accumulation(wallet)
                    await asyncio.sleep(0.5)  # Rate limit between wallets
                except Exception as e:
                    print(f"[DEVMON] Check error {wallet[:16]}: {e}")

        except Exception as e:
            print(f"[DEVMON] Monitor loop error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def analyze_wallet_accumulation(wallet_address):
    """
    Checks if dev wallet received significant SOL in last 24 hours.
    SOL accumulation before a launch is a consistent on-chain signal.
    """
    try:
        url = (
            f"https://api.helius.xyz/v0/addresses/{wallet_address}"
            f"/transactions?api-key={HELIUS_API_KEY}&limit=20"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return
                txs = await resp.json()
                if not isinstance(txs, list):
                    return

        now          = datetime.utcnow()
        cutoff       = now - timedelta(hours=24)
        sol_received = 0.0

        for tx in txs:
            ts = tx.get("timestamp", 0)
            if not ts:
                continue
            tx_time = datetime.utcfromtimestamp(ts)
            if tx_time < cutoff:
                continue

            # Sum SOL received by this wallet
            for transfer in tx.get("nativeTransfers", []):
                if transfer.get("toUserAccount") == wallet_address:
                    amount = transfer.get("amount", 0)
                    sol_received += amount / LAMPORTS

        # Update tracker
        accumulation_tracker[wallet_address] = {
            "sol_received": sol_received,
            "last_updated": now
        }

        # Trigger pre-launch alert if threshold crossed
        if (sol_received >= SOL_ACCUMULATION_THRESHOLD and
                wallet_address not in alerted_wallets and
                wallet_address not in deploy_watchers):

            alerted_wallets.add(wallet_address)
            print(
                f"[DEVMON] 🚨 Accumulation detected: "
                f"{wallet_address[:16]}... | {sol_received:.2f} SOL"
            )
            await send_prelaunch_alert(wallet_address, sol_received)

            # Start watching for the actual token deploy
            deploy_watchers.add(wallet_address)
            asyncio.create_task(watch_for_deploy(wallet_address))

    except Exception as e:
        print(f"[DEVMON] analyze_wallet_accumulation error: {e}")


# ============================================================
# PRE-LAUNCH ALERT
# ============================================================

async def send_prelaunch_alert(wallet_address, sol_received):
    try:
        from telegram_bot import send_alert
        win_rate = 0
        avg_mult = 0
        short    = f"{wallet_address[:8]}...{wallet_address[-6:]}"

        try:
            from database import supabase
            if supabase:
                result = supabase.table("smart_wallets") \
                    .select("win_rate, avg_multiplier") \
                    .eq("wallet_address", wallet_address) \
                    .execute()
                if result.data:
                    win_rate = result.data[0].get("win_rate", 0)
                    avg_mult = result.data[0].get("avg_multiplier", 0)
        except Exception:
            pass

        await send_alert(
            f"🚨 *DEV WALLET PRE-LAUNCH SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👛 Wallet: `{short}`\n"
            f"💰 SOL received (24hrs): *{sol_received:.2f} SOL*\n"
            f"📊 Win rate: *{win_rate}%*\n"
            f"📈 Avg multiplier: *{avg_mult}x*\n\n"
            f"⚠️ *Launch likely imminent*\n"
            f"👀 Watching for token deploy (2hrs)...\n\n"
            f"📋 `{wallet_address}`"
        )
    except Exception as e:
        print(f"[DEVMON] Pre-launch alert error: {e}")


# ============================================================
# WATCH FOR DEPLOY
# ============================================================

async def watch_for_deploy(wallet_address):
    """
    After pre-launch signal — polls for new token from this wallet.
    Checks every 30 seconds for 2 hours.
    """
    print(f"[DEVMON] 👀 Watching for deploy: {wallet_address[:16]}...")

    known_tokens = await get_wallet_tokens(wallet_address)
    checks       = 0
    max_checks   = int(WATCH_DURATION_MINS * 60 / 30)  # checks every 30 secs

    while checks < max_checks:
        await asyncio.sleep(30)
        checks += 1

        try:
            current_tokens = await get_wallet_tokens(wallet_address)
            new_tokens     = current_tokens - known_tokens

            for token_address in new_tokens:
                known_tokens.add(token_address)
                print(f"[DEVMON] 🎯 New token deployed: {token_address[:20]}...")

                try:
                    from telegram_bot import send_alert
                    await send_alert(
                        f"🎯 *DEV WALLET DEPLOYED TOKEN*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"👛 Wallet: `{wallet_address[:16]}...`\n"
                        f"🪙 Token: `{token_address}`\n"
                        f"⚡ Running full pipeline..."
                    )
                except Exception:
                    pass

                asyncio.create_task(
                    run_dev_token_pipeline(token_address, wallet_address)
                )

        except Exception as e:
            print(f"[DEVMON] Deploy watch check error: {e}")

    # Watch expired
    print(f"[DEVMON] Deploy watch expired: {wallet_address[:16]}...")
    deploy_watchers.discard(wallet_address)
    # Reset alert flag so wallet can trigger again next cycle
    alerted_wallets.discard(wallet_address)
    # Reset accumulation
    if wallet_address in accumulation_tracker:
        accumulation_tracker[wallet_address]["sol_received"] = 0


async def get_wallet_tokens(wallet_address):
    """Returns set of token mint addresses held by wallet"""
    tokens = set()
    try:
        url = (
            f"https://api.helius.xyz/v0/addresses/{wallet_address}"
            f"/balances?api-key={HELIUS_API_KEY}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for token in data.get("tokens", []):
                        mint = token.get("mint", "")
                        if mint and len(mint) > 30:
                            tokens.add(mint)
    except Exception as e:
        print(f"[DEVMON] get_wallet_tokens error: {e}")
    return tokens


# ============================================================
# DEV TOKEN PIPELINE
# ============================================================

async def run_dev_token_pipeline(token_address, dev_wallet):
    """
    Full pipeline for token deployed by a known dev wallet.
    Gets +15 bonus score — known successful dev is a strong signal.
    """
    try:
        from database import token_already_seen, mark_token_seen
        from filters import run_hard_filters
        from scorer import score_token
        from telegram_bot import alert_new_token_detected, send_alert
        import aiohttp

        if token_already_seen(token_address):
            return

        # Get token info
        token_name, ticker = "Unknown", "???"
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if r.status == 200:
                        data = await r.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            base       = pairs[0].get("baseToken", {})
                            token_name = base.get("name", "Unknown")
                            ticker     = base.get("symbol", "???")
        except Exception:
            pass

        # Hard filters
        passed, reason = run_hard_filters(token_address)
        if not passed:
            mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
            print(f"[DEVMON] {ticker} filtered: {reason}")
            return

        # AI Score + dev wallet bonus
        deploy_time              = datetime.utcnow()
        score, breakdown, _      = score_token(
            token_address, token_name, ticker, deploy_time
        )
        DEV_BONUS                = 15
        score                    = min(score + DEV_BONUS, 100)
        breakdown["dev_bonus"]   = f"+{DEV_BONUS} — Known successful dev wallet"

        if score < 80:
            mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
            print(f"[DEVMON] {ticker} score too low after bonus: {score}/100")
            return

        mark_token_seen(token_address, token_name, score=score, decision="BOUGHT")

        await alert_new_token_detected(
            ticker, token_name, token_address,
            score, breakdown, "DEV_WALLET"
        )

        from executor import execute_buy
        await execute_buy(
            token_address=token_address,
            token_name=token_name,
            ticker=ticker,
            score=score,
            source="DEV_WALLET"
        )

    except Exception as e:
        print(f"[DEVMON] Pipeline error: {e}")


# ============================================================
# HELPERS
# ============================================================

def get_dev_wallets():
    """
    Gets high-performing wallets from DB.
    Filters for wallets with 10x+ avg and 75%+ win rate
    — these are the serious dev/whale wallets.
    """
    try:
        from database import supabase
        if not supabase:
            return []
        result = supabase.table("smart_wallets") \
            .select("wallet_address") \
            .gte("avg_multiplier", 10.0) \
            .gte("win_rate", 75.0) \
            .execute()
        return [r["wallet_address"] for r in result.data] if result.data else []
    except Exception as e:
        print(f"[DEVMON] get_dev_wallets error: {e}")
        return []


async def periodic_wallet_refresh():
    """Refreshes dev wallet list from DB periodically"""
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        wallets = get_dev_wallets()
        print(f"[DEVMON] Refreshed wallet list — {len(wallets)} dev wallets")

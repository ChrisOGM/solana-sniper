# ============================================================
# telegram_scanner.py — TELEGRAM ALPHA GROUP SCANNER
# OTP verification via web page — no terminal needed
# Session string persists across restarts via env var
# ============================================================

import asyncio
import re
from datetime import datetime, timedelta
from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    TELEGRAM_SESSION_STRING,
    ALPHA_GROUPS
)

# ── Solana address patterns ───────────────────────────────
SOLANA_ADDR  = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
PUMPFUN_URL  = re.compile(r'pump\.fun/(?:coin/)?([1-9A-HJ-NP-Za-km-z]{32,44})')
DEXSCREENER  = re.compile(r'dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})')
BIRDEYE      = re.compile(r'birdeye\.so/token/([1-9A-HJ-NP-Za-km-z]{32,44})')
GMGN         = re.compile(r'gmgn\.ai/sol/token/([1-9A-HJ-NP-Za-km-z]{32,44})')

# ── Always ignore ─────────────────────────────────────────
IGNORE_ADDRESSES = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe1brs",
    "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s",
}

# ── State ─────────────────────────────────────────────────
processed_addresses = set()
seen_message_ids    = set()
address_timestamps  = []
MAX_PER_MINUTE      = 5


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_telegram_scanner():
    print("[SCANNER] Starting Telegram alpha scanner...")

    # Check config
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("[SCANNER] ⚠️ TELEGRAM_API_ID / TELEGRAM_API_HASH not set")
        print("[SCANNER] Get from my.telegram.org — scanner disabled")
        try:
            from keep_alive import set_scanner_status
            set_scanner_status("disabled")
        except Exception:
            pass
        while True:
            await asyncio.sleep(3600)
        return

    if not ALPHA_GROUPS:
        print("[SCANNER] ⚠️ ALPHA_GROUPS empty — add groups to config.py")
        try:
            from keep_alive import set_scanner_status
            set_scanner_status("disabled")
        except Exception:
            pass
        while True:
            await asyncio.sleep(3600)
        return

    # Auto-reconnect loop
    while True:
        try:
            await connect_and_scan()
        except Exception as e:
            print(f"[SCANNER] Disconnected: {e}")
            try:
                from telegram_bot import alert_bot_error
                await alert_bot_error("TelegramScanner", f"Reconnecting in 30s")
            except Exception:
                pass
            await asyncio.sleep(30)


# ============================================================
# CONNECT AND SCAN
# ============================================================

async def connect_and_scan():
    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        print("[SCANNER] ❌ Telethon not installed — check requirements.txt")
        await asyncio.sleep(3600)
        return

    session = (StringSession(TELEGRAM_SESSION_STRING)
               if TELEGRAM_SESSION_STRING
               else StringSession())

    client = TelegramClient(
        session,
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        connection_retries=5,
        retry_delay=5,
        auto_reconnect=True
    )

    # ── Phone-based auth with web OTP input ──────────────
    if not TELEGRAM_SESSION_STRING:
        print("[SCANNER] First-time auth — sending OTP to your phone...")

        try:
            from keep_alive import set_scanner_status, get_otp_from_web
            set_scanner_status("waiting")
        except Exception:
            get_otp_from_web = None

        # Send OTP to phone
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(TELEGRAM_PHONE)
            print(f"[SCANNER] OTP sent to {TELEGRAM_PHONE}")

            # Alert user to open OTP page
            try:
                from telegram_bot import send_alert
                await send_alert(
                    f"🔐 *TELEGRAM SCANNER SETUP*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Telegram sent an OTP to your phone.\n\n"
                    f"Open this URL in your browser to enter it:\n"
                    f"`https://solana-sniper-8pb5.onrender.com/otp`\n\n"
                    f"⏳ Waiting 5 minutes for your code..."
                )
            except Exception:
                pass

            print("[SCANNER] Waiting for OTP via web form...")
            print("[SCANNER] Open: https://solana-sniper-8pb5.onrender.com/otp")

            # Wait for OTP from web form (5 minute timeout)
            loop = asyncio.get_event_loop()
            otp_code = await loop.run_in_executor(
                None,
                lambda: get_otp_from_web(timeout=300) if get_otp_from_web else None
            )

            if not otp_code:
                print("[SCANNER] ⏰ OTP timeout — retrying in 60s")
                await asyncio.sleep(60)
                return

            try:
                await client.sign_in(TELEGRAM_PHONE, otp_code)
                print("[SCANNER] ✅ Authenticated successfully!")
            except Exception as e:
                print(f"[SCANNER] Auth failed: {e}")
                await asyncio.sleep(30)
                return

        # Save session string
        session_str = client.session.save()
        print("\n" + "="*60)
        print("ADD THIS TO RENDER ENVIRONMENT VARIABLES:")
        print(f"Key:   TELEGRAM_SESSION_STRING")
        print(f"Value: {session_str}")
        print("="*60 + "\n")

        try:
            from telegram_bot import send_alert
            await send_alert(
                f"✅ *SCANNER AUTHENTICATED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Check your Render deploy logs.\n"
                f"Copy TELEGRAM_SESSION_STRING value\n"
                f"→ Add to Render Environment Variables\n"
                f"→ Redeploy\n\n"
                f"After that: no more OTP needed ever."
            )
        except Exception:
            pass

    else:
        # Session string exists — connect directly, no OTP
        await client.start()

    # Update status
    try:
        from keep_alive import set_scanner_status
        set_scanner_status("active")
    except Exception:
        pass

    print(f"[SCANNER] ✅ Connected as Telegram user")
    print(f"[SCANNER] Monitoring: {ALPHA_GROUPS}")

    try:
        from telegram_bot import send_alert
        await send_alert(
            f"🔍 *TELEGRAM ALPHA SCANNER ONLINE*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 Groups: *{len(ALPHA_GROUPS)}*\n"
            f"⚡ Real-time contract detection active\n"
            f"🎯 Auto-buy threshold: 80/100"
        )
    except Exception:
        pass

    # Message handler
    @client.on(events.NewMessage(chats=ALPHA_GROUPS))
    async def on_message(event):
        try:
            await handle_message(event)
        except Exception as e:
            print(f"[SCANNER] Handler error: {e}")

    print("[SCANNER] 👀 Listening for contract addresses...")
    await client.run_until_disconnected()


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(event):
    global address_timestamps

    message = event.message
    if not message or not message.message:
        return

    text   = message.message
    msg_id = f"{event.chat_id}:{message.id}"

    if msg_id in seen_message_ids:
        return
    seen_message_ids.add(msg_id)

    # Keep set manageable
    if len(seen_message_ids) > 50000:
        oldest = list(seen_message_ids)[:25000]
        for m in oldest:
            seen_message_ids.discard(m)

    addresses = extract_addresses(text)
    if not addresses:
        return

    try:
        chat       = await event.get_chat()
        group_name = getattr(chat, 'title', str(event.chat_id))
    except Exception:
        group_name = "Alpha Group"

    now = datetime.utcnow()
    address_timestamps = [t for t in address_timestamps
                          if now - t < timedelta(minutes=1)]

    for address in addresses:
        if address in processed_addresses:
            continue
        if address in IGNORE_ADDRESSES:
            continue

        if len(address_timestamps) >= MAX_PER_MINUTE:
            await asyncio.sleep(15)
            address_timestamps = [t for t in address_timestamps
                                   if datetime.utcnow() - t < timedelta(minutes=1)]

        processed_addresses.add(address)
        address_timestamps.append(datetime.utcnow())

        print(f"[SCANNER] 🎯 [{group_name}]: {address[:20]}...")

        try:
            from telegram_bot import send_alert
            await send_alert(
                f"📡 *ALPHA GROUP SIGNAL*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 *{group_name}*\n"
                f"📋 `{address}`\n"
                f"⚡ Running safety checks..."
            )
        except Exception as e:
            print(f"[SCANNER] Alert error: {e}")

        asyncio.create_task(run_scanner_pipeline(address, group_name))


# ============================================================
# ADDRESS EXTRACTION
# ============================================================

def extract_addresses(text):
    found = set()
    for pattern in [PUMPFUN_URL, DEXSCREENER, BIRDEYE, GMGN]:
        for match in pattern.finditer(text):
            addr = match.group(1)
            if is_valid_solana_address(addr):
                found.add(addr)
    for match in SOLANA_ADDR.finditer(text):
        addr = match.group(0)
        if is_valid_solana_address(addr):
            found.add(addr)
    return list(found)


def is_valid_solana_address(address):
    if not address or len(address) < 32 or len(address) > 44:
        return False
    if address in IGNORE_ADDRESSES:
        return False
    valid = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    return all(c in valid for c in address)


# ============================================================
# SCANNER PIPELINE
# ============================================================

async def run_scanner_pipeline(token_address, group_name):
    try:
        from database import token_already_seen, mark_token_seen
        from filters import run_hard_filters
        from scorer import score_token
        from telegram_bot import send_alert, alert_new_token_detected
        import aiohttp

        if token_already_seen(token_address):
            return

        token_name, ticker = await get_token_info(token_address)
        deploy_time        = datetime.utcnow()

        passed, reason = run_hard_filters(token_address)
        if not passed:
            mark_token_seen(token_address, token_name, score=0, decision="FILTERED")
            await send_alert(
                f"🛡️ *GROUP SIGNAL FILTERED*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 {token_name} (${ticker})\n"
                f"❌ {reason}\n"
                f"👥 {group_name}"
            )
            return

        score, breakdown, recommendation = score_token(
            token_address, token_name, ticker, deploy_time
        )

        if recommendation == "SKIP":
            mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
            await send_alert(
                f"📊 *GROUP SIGNAL — LOW SCORE*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 {token_name} (${ticker})\n"
                f"📊 Score: {score}/100 (need 80+)\n"
                f"👥 {group_name}"
            )
            return

        mark_token_seen(token_address, token_name, score=score, decision="BOUGHT")
        breakdown["alpha_source"] = f"Telegram: {group_name}"

        await alert_new_token_detected(
            ticker, token_name, token_address,
            score, breakdown, "TELEGRAM_ALPHA"
        )

        from executor import execute_buy
        await execute_buy(
            token_address=token_address,
            token_name=token_name,
            ticker=ticker,
            score=score,
            source="TELEGRAM_ALPHA"
        )

    except Exception as e:
        print(f"[SCANNER] Pipeline error {token_address[:16]}: {e}")


async def get_token_info(token_address):
    import aiohttp
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=6)) as r:
                if r.status == 200:
                    data  = await r.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        base = pairs[0].get("baseToken", {})
                        return base.get("name", "Unknown"), base.get("symbol", "???")
    except Exception:
        pass
    return "Unknown", "???"

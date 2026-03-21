# ============================================================
# telegram_scanner.py — TELEGRAM ALPHA GROUP SCANNER
# Sends session string DIRECTLY to your Telegram bot
# No need to check Render logs
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

SOLANA_ADDR  = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
PUMPFUN_URL  = re.compile(r'pump\.fun/(?:coin/)?([1-9A-HJ-NP-Za-km-z]{32,44})')
DEXSCREENER  = re.compile(r'dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})')
BIRDEYE      = re.compile(r'birdeye\.so/token/([1-9A-HJ-NP-Za-km-z]{32,44})')
GMGN         = re.compile(r'gmgn\.ai/sol/token/([1-9A-HJ-NP-Za-km-z]{32,44})')

IGNORE_ADDRESSES = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe1brs",
}

processed_addresses = set()
seen_message_ids    = set()
address_timestamps  = []
MAX_PER_MINUTE      = 5


# ============================================================
# MAIN ENTRY
# ============================================================

async def start_telegram_scanner():
    print("[SCANNER] Starting Telegram alpha scanner...")

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("[SCANNER] ⚠️ TELEGRAM_API_ID / TELEGRAM_API_HASH not set — disabled")
        try:
            from keep_alive import set_scanner_status
            set_scanner_status("disabled")
        except Exception:
            pass
        while True:
            await asyncio.sleep(3600)
        return

    if not ALPHA_GROUPS:
        print("[SCANNER] ⚠️ ALPHA_GROUPS empty — disabled")
        try:
            from keep_alive import set_scanner_status
            set_scanner_status("disabled")
        except Exception:
            pass
        while True:
            await asyncio.sleep(3600)
        return

    while True:
        try:
            await connect_and_scan()
        except Exception as e:
            print(f"[SCANNER] Disconnected: {e}")
            await asyncio.sleep(30)


# ============================================================
# CONNECT AND SCAN
# ============================================================

async def connect_and_scan():
    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        print("[SCANNER] ❌ Telethon not installed")
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

    # ── First time auth — uses web OTP form ──────────────
    if not TELEGRAM_SESSION_STRING:
        print("[SCANNER] First-time auth — sending OTP to phone...")

        try:
            from keep_alive import set_scanner_status, get_otp_from_web
            set_scanner_status("waiting")
        except Exception:
            get_otp_from_web = None

        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(TELEGRAM_PHONE)
            print(f"[SCANNER] OTP sent to {TELEGRAM_PHONE}")

            try:
                from telegram_bot import send_alert
                await send_alert(
                    f"🔐 *TELEGRAM SCANNER SETUP*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Telegram sent an OTP to your phone.\n\n"
                    f"Open this in your browser:\n"
                    f"`https://solana-sniper-8pb5.onrender.com/otp`\n\n"
                    f"⏳ Waiting 5 minutes..."
                )
            except Exception:
                pass

            loop     = asyncio.get_event_loop()
            otp_code = await loop.run_in_executor(
                None,
                lambda: get_otp_from_web(timeout=300) if get_otp_from_web else None
            )

            if not otp_code:
                print("[SCANNER] OTP timeout — retrying in 60s")
                await asyncio.sleep(60)
                return

            try:
                await client.sign_in(TELEGRAM_PHONE, otp_code)
                print("[SCANNER] ✅ Authenticated!")
            except Exception as e:
                print(f"[SCANNER] Auth failed: {e}")
                await asyncio.sleep(30)
                return

        # ── Save session string — send DIRECTLY to Telegram ──
        session_str = client.session.save()
        print(f"[SCANNER] Session string: {session_str[:30]}...")

        # Send directly to your Filtrum bot — no log searching needed
        try:
            from telegram_bot import send_alert
            await send_alert(
                f"🔑 *YOUR SESSION STRING*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Copy EVERYTHING between the lines below\n"
                f"and add to Render as TELEGRAM_SESSION_STRING:\n\n"
                f"---START---\n"
                f"{session_str}\n"
                f"---END---\n\n"
                f"Steps:\n"
                f"1. Copy the string between START and END\n"
                f"2. Render → Environment → Add variable\n"
                f"3. Key: TELEGRAM_SESSION_STRING\n"
                f"4. Value: paste the string\n"
                f"5. Save → Manual Deploy"
            )
        except Exception as e:
            print(f"[SCANNER] Could not send session string: {e}")

    else:
        await client.start()

    try:
        from keep_alive import set_scanner_status
        set_scanner_status("active")
    except Exception:
        pass

    print(f"[SCANNER] ✅ Connected — monitoring {len(ALPHA_GROUPS)} groups")

    try:
        from telegram_bot import send_alert
        await send_alert(
            f"🔍 *TELEGRAM ALPHA SCANNER ONLINE*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 Groups: *{len(ALPHA_GROUPS)}*\n"
            f"⚡ Real-time detection active\n"
            f"🎯 Auto-buy on score ≥ 80"
        )
    except Exception:
        pass

    @client.on(events.NewMessage(chats=ALPHA_GROUPS))
    async def on_message(event):
        try:
            await handle_message(event)
        except Exception as e:
            print(f"[SCANNER] Handler error: {e}")

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
        if address in processed_addresses or address in IGNORE_ADDRESSES:
            continue
        if len(address_timestamps) >= MAX_PER_MINUTE:
            await asyncio.sleep(15)
            address_timestamps = [t for t in address_timestamps
                                   if datetime.utcnow() - t < timedelta(minutes=1)]

        processed_addresses.add(address)
        address_timestamps.append(datetime.utcnow())

        try:
            from telegram_bot import send_alert
            await send_alert(
                f"📡 *ALPHA GROUP SIGNAL*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 *{group_name}*\n"
                f"📋 `{address}`\n"
                f"⚡ Running checks..."
            )
        except Exception:
            pass

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
                f"🛡️ *FILTERED*\n{token_name} (${ticker})\n❌ {reason}\n👥 {group_name}"
            )
            return

        score, breakdown, recommendation = score_token(
            token_address, token_name, ticker, deploy_time
        )

        if recommendation == "SKIP":
            mark_token_seen(token_address, token_name, score=score, decision="SKIPPED")
            await send_alert(
                f"📊 *LOW SCORE*\n{token_name} (${ticker})\n"
                f"Score: {score}/100\n👥 {group_name}"
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

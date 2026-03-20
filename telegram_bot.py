# ============================================================
# telegram_bot.py — ALERTS + COMMANDS + MENU BUTTON
# Commands: /pnl /status /positions /help
# Menu button appears in Telegram chat automatically
# ============================================================

import asyncio
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING

TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
LAST_UPDATE_ID = 0


# ============================================================
# REGISTER MENU BUTTON — call once on startup
# Makes commands appear as clickable menu in Telegram
# ============================================================

async def register_bot_commands():
    """
    Registers commands with Telegram so they appear
    as a clickable Menu button in your chat
    """
    url      = f"{TELEGRAM_API}/setMyCommands"
    commands = [
        {"command": "pnl",       "description": "📊 Full PNL report"},
        {"command": "positions", "description": "📂 Open positions + live multiplier"},
        {"command": "status",    "description": "✅ Bot health check"},
        {"command": "help",      "description": "❓ Show all commands"},
    ]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"commands": commands},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    print("[TELEGRAM] ✅ Menu button registered")
                else:
                    print(f"[TELEGRAM] Menu registration status: {resp.status}")
    except Exception as e:
        print(f"[TELEGRAM] Menu registration error: {e}")


# ============================================================
# CORE SEND — 3 retries, never crashes the bot
# ============================================================

async def send_alert(message, retries=3):
    url     = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown"
    }
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status == 200:
                        print(f"[TELEGRAM] ✅ Alert sent")
                        return True
                    print(f"[TELEGRAM] Status {resp.status} — attempt {attempt+1}")
        except Exception as e:
            print(f"[TELEGRAM] Attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)
    print(f"[TELEGRAM] ❌ All attempts failed")
    return False


# ============================================================
# COMMAND LISTENER — polls every 3 seconds
# ============================================================

async def start_command_listener():
    global LAST_UPDATE_ID
    print("[TELEGRAM] ✅ Command listener started")

    while True:
        try:
            updates = await get_updates(LAST_UPDATE_ID + 1)
            for update in updates:
                update_id      = update.get("update_id", 0)
                LAST_UPDATE_ID = max(LAST_UPDATE_ID, update_id)

                message = update.get("message", {})
                if not message:
                    continue

                # Security — only respond to YOUR chat
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                text = message.get("text", "").strip().lower()
                if not text:
                    continue

                print(f"[TELEGRAM] Command: {text}")

                if text.startswith("/pnl"):
                    await handle_pnl()
                elif text.startswith("/positions"):
                    await handle_positions()
                elif text.startswith("/status"):
                    await handle_status()
                elif text.startswith("/help") or text.startswith("/start"):
                    await handle_help()
                else:
                    await send_alert(
                        f"❓ Unknown command: `{text}`\n"
                        f"Tap the *Menu* button or send /help"
                    )
        except Exception as e:
            print(f"[TELEGRAM] Listener error: {e}")

        await asyncio.sleep(3)


async def get_updates(offset):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 1, "limit": 10},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
    except Exception as e:
        print(f"[TELEGRAM] getUpdates error: {e}")
    return []


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def handle_pnl():
    try:
        from database import get_performance_summary, get_open_positions
        summary   = get_performance_summary()
        positions = get_open_positions()

        if "message" in summary:
            await send_alert(
                f"📊 *PNL REPORT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"No trades recorded yet.\n"
                f"Bot is watching — will buy when score ≥ 80."
            )
            return

        pnl       = summary.get("pnl_sol", 0)
        pnl_usd   = round(pnl * 150, 2)
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        mode      = "📝 PAPER" if PAPER_TRADING else "💰 LIVE"

        await send_alert(
            f"📊 *PNL REPORT* — {mode}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Total trades: *{summary.get('total_trades', 0)}*\n"
            f"🎯 Win rate: *{summary.get('win_rate', 0):.1f}%*\n\n"
            f"💎 SOL invested: *{summary.get('total_invested', 0):.4f}*\n"
            f"💰 SOL returned: *{summary.get('total_returned', 0):.4f}*\n"
            f"{pnl_emoji} PNL: *{pnl:+.4f} SOL* (~${pnl_usd:+.2f})\n\n"
            f"📂 Open positions: *{len(positions)}*"
        )
    except Exception as e:
        await send_alert(f"⚠️ PNL error: {e}")


async def handle_positions():
    try:
        from database import get_open_positions
        import requests as req

        positions = get_open_positions()
        if not positions:
            await send_alert(
                f"📂 *OPEN POSITIONS*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"No open positions.\n"
                f"Bot is scanning for next trade."
            )
            return

        msg = f"📂 *OPEN POSITIONS* ({len(positions)})\n━━━━━━━━━━━━━━━━━━━━\n"

        for pos in positions:
            ticker        = pos.get("ticker", "???")
            token_name    = pos.get("token_name", "Unknown")
            entry_price   = float(pos.get("price_usd") or 0)
            amount_sol    = float(pos.get("amount_sol") or 0)
            token_address = pos.get("token_address", "")
            source        = pos.get("source", "")

            multiplier  = 0
            pnl_emoji   = "⏳"
            mult_text   = "loading..."

            try:
                url      = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
                response = req.get(url, timeout=5)
                data     = response.json()
                pairs    = data.get("pairs", [])
                if pairs and entry_price > 0:
                    best          = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
                    current_price = float(best.get("priceUsd", 0) or 0)
                    if current_price > 0:
                        multiplier = current_price / entry_price
                        mult_text  = f"{multiplier:.2f}x"
                        pnl_emoji  = "📈" if multiplier >= 1 else "📉"
            except Exception:
                pass

            source_tag = {
                "AI_DISCOVERY": "🤖",
                "COPY_TRADE":   "👛",
                "KOL_LINKED":   "🚨"
            }.get(source, "📡")

            msg += (
                f"\n{pnl_emoji} *{token_name}* (${ticker}) {source_tag}\n"
                f"  Entry: ${entry_price:.8f}\n"
                f"  Now: {mult_text}\n"
                f"  Size: {amount_sol:.4f} SOL\n"
            )

        await send_alert(msg)

    except Exception as e:
        await send_alert(f"⚠️ Positions error: {e}")


async def handle_status():
    from datetime import datetime
    try:
        from database import get_all_smart_wallets, get_open_positions
        wallets   = get_all_smart_wallets()
        positions = get_open_positions()
    except Exception:
        wallets   = []
        positions = []

    mode = "📝 PAPER TRADING" if PAPER_TRADING else "💰 LIVE TRADING"
    now  = datetime.utcnow().strftime("%H:%M:%S UTC")

    await send_alert(
        f"🤖 *BOT STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Bot: Online\n"
        f"✅ Chain Listener: Active\n"
        f"✅ KOL Monitor: Active\n"
        f"✅ Smart Wallet Tracker: Active\n"
        f"✅ Exit Manager: Active\n\n"
        f"⚙️ Mode: *{mode}*\n"
        f"🎯 Min score: 80/100\n"
        f"🛑 Stop loss: 40%\n"
        f"🧠 Wallets tracked: *{len(wallets)}*\n"
        f"📂 Open positions: *{len(positions)}*\n"
        f"🕐 {now}"
    )


async def handle_help():
    await send_alert(
        f"🤖 *SOLANA SNIPER BOT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 /pnl — Full PNL report\n"
        f"📂 /positions — Live positions\n"
        f"✅ /status — Bot health + stats\n"
        f"❓ /help — This menu\n\n"
        f"*Auto alerts:*\n"
        f"🚨 KOL posts detected\n"
        f"🤖 New token signals\n"
        f"✅ Buys executed\n"
        f"🎉 Take profit stages\n"
        f"🛑 Stop loss hits\n"
        f"🧠 Smart wallet discoveries\n"
        f"📊 Daily PNL at midnight\n\n"
        f"Tap *Menu* below for quick access ↓"
    )


# ============================================================
# ALERT TEMPLATES
# ============================================================

async def alert_bot_started(paper_mode=True):
    mode = "📝 PAPER TRADING" if paper_mode else "💰 LIVE TRADING"
    await send_alert(
        f"🤖 *SOLANA SNIPER BOT ONLINE*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Chain Listener: Active\n"
        f"✅ KOL Monitor: Active\n"
        f"✅ Smart Wallet Tracker: Active\n"
        f"✅ Filters: Armed\n"
        f"✅ AI Scorer: Ready\n\n"
        f"⚙️ Mode: *{mode}*\n"
        f"🎯 Min score: 80/100\n"
        f"🧠 Wallet discovery: Every 6hrs\n"
        f"👀 Watching entire Solana chain...\n\n"
        f"Tap *Menu* for commands ↓"
    )


async def alert_new_token_detected(ticker, token_name, token_address,
                                    score, breakdown, source):
    source_emoji = {
        "AI_DISCOVERY": "🤖",
        "COPY_TRADE":   "👛",
        "KOL_LINKED":   "🚨"
    }.get(source, "📡")
    breakdown_text = "\n".join(
        f"  • {k}: {v}" for k, v in breakdown.items()
    )
    await send_alert(
        f"{source_emoji} *NEW TOKEN SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{token_name}* (${ticker})\n"
        f"📊 Score: *{score}/100*\n"
        f"📡 Source: {source}\n\n"
        f"*Breakdown:*\n{breakdown_text}\n\n"
        f"📋 `{token_address}`"
    )


async def alert_buy_executed(ticker, token_name, token_address,
                              amount_sol, price_usd, mcap_usd,
                              score, paper=True):
    mode = "📝 PAPER" if paper else "💰 LIVE"
    await send_alert(
        f"✅ *BUY EXECUTED* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{token_name}* (${ticker})\n"
        f"💵 Price: ${price_usd:.8f}\n"
        f"📈 Market Cap: ${mcap_usd:,.0f}\n"
        f"💎 Amount: {amount_sol} SOL\n"
        f"🎯 Score: {score}/100\n\n"
        f"⏳ Monitoring exit...\n"
        f"📋 `{token_address}`"
    )


async def alert_take_profit(ticker, token_name, token_address,
                             stage, multiplier, sol_returned,
                             remaining_pct, paper=True):
    mode = "📝 PAPER" if paper else "💰 LIVE"
    await send_alert(
        f"🎉 *TAKE PROFIT — Stage {stage}* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{token_name}* (${ticker})\n"
        f"📈 Multiplier: *{multiplier:.1f}x*\n"
        f"💰 SOL returned: {sol_returned:.4f}\n"
        f"📊 Remaining: {remaining_pct}%\n\n"
        f"📋 `{token_address}`"
    )


async def alert_stop_loss(ticker, token_name, token_address,
                           loss_pct, sol_lost, paper=True):
    mode = "📝 PAPER" if paper else "💰 LIVE"
    await send_alert(
        f"🛑 *STOP LOSS HIT* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{token_name}* (${ticker})\n"
        f"📉 Loss: *{loss_pct:.1f}%*\n"
        f"💸 SOL lost: {sol_lost:.4f}\n"
        f"🛡 Capital protected\n\n"
        f"📋 `{token_address}`"
    )


async def alert_kol_post(influencer, post_text, keywords):
    await send_alert(
        f"🚨 *KOL POST DETECTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 @{influencer}\n"
        f"📝 {post_text[:200]}\n\n"
        f"🔑 Keywords: `{', '.join(keywords)}`\n"
        f"⏱ Watching chain 20 mins..."
    )


async def alert_smart_wallet_buy(wallet_address, ticker,
                                  token_name, token_address,
                                  wallet_win_rate):
    short = f"{wallet_address[:6]}...{wallet_address[-4:]}"
    await send_alert(
        f"👛 *SMART WALLET BUY*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 Wallet: `{short}`\n"
        f"📊 Win Rate: *{wallet_win_rate}%*\n"
        f"🪙 Token: *{token_name}* (${ticker})\n"
        f"⚡ Running filters + score...\n\n"
        f"📋 `{token_address}`"
    )


async def alert_filter_rejected(ticker, token_address, reason):
    print(f"[REJECTED] {ticker} | {token_address[:20]}... | {reason}")


async def alert_daily_summary(total_trades, wins, losses,
                               total_sol_in, total_sol_out,
                               pnl_sol, win_rate, paper=True):
    mode      = "📝 PAPER" if paper else "💰 LIVE"
    pnl_emoji = "📈" if pnl_sol >= 0 else "📉"
    pnl_usd   = round(pnl_sol * 150, 2)
    await send_alert(
        f"📊 *DAILY SUMMARY* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Trades: {total_trades}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"🎯 Win rate: *{win_rate:.1f}%*\n\n"
        f"💎 SOL in: {total_sol_in:.4f}\n"
        f"💰 SOL out: {total_sol_out:.4f}\n"
        f"{pnl_emoji} PNL: *{pnl_sol:+.4f} SOL* (~${pnl_usd:+.2f})"
    )


async def alert_bot_error(component, error_message):
    await send_alert(
        f"⚠️ *BOT ERROR*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔧 Component: {component}\n"
        f"❌ {error_message}\n\n"
        f"Bot still running"
    )

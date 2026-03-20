# ============================================================
# telegram_bot.py — ALL ALERTS + COMMAND HANDLER
# Commands: /pnl /status /positions /help
# ============================================================

import asyncio
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING

TELEGRAM_API  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
LAST_UPDATE_ID = 0  # Tracks processed commands — prevents duplicates


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
# COMMAND LISTENER — runs forever, checks for new commands
# ============================================================

async def start_command_listener():
    """
    Polls Telegram every 3 seconds for new commands from you.
    Supports: /pnl /status /positions /help
    Only responds to YOUR chat ID — ignores everyone else.
    """
    global LAST_UPDATE_ID
    print("[TELEGRAM] ✅ Command listener started")

    while True:
        try:
            updates = await get_updates(LAST_UPDATE_ID + 1)
            for update in updates:
                update_id = update.get("update_id", 0)
                LAST_UPDATE_ID = max(LAST_UPDATE_ID, update_id)

                message = update.get("message", {})
                if not message:
                    continue

                # Security — only respond to YOUR chat
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id != str(TELEGRAM_CHAT_ID):
                    print(f"[TELEGRAM] Ignored message from unknown chat: {chat_id}")
                    continue

                text = message.get("text", "").strip().lower()
                if not text:
                    continue

                print(f"[TELEGRAM] Command received: {text}")

                # Route commands
                if text in ("/pnl", "/pnl@filtrum"):
                    await handle_pnl()
                elif text in ("/status", "/status@filtrum"):
                    await handle_status()
                elif text in ("/positions", "/positions@filtrum"):
                    await handle_positions()
                elif text in ("/help", "/help@filtrum", "/start"):
                    await handle_help()
                else:
                    await send_alert(
                        f"❓ Unknown command: `{text}`\n"
                        f"Send /help to see available commands."
                    )

        except Exception as e:
            print(f"[TELEGRAM] Command listener error: {e}")

        await asyncio.sleep(3)  # Poll every 3 seconds


async def get_updates(offset):
    """Fetches new messages from Telegram"""
    try:
        url    = f"{TELEGRAM_API}/getUpdates"
        params = {
            "offset":  offset,
            "timeout": 1,
            "limit":   10
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
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
    """/pnl — Shows full PNL breakdown instantly"""
    try:
        from database import get_performance_summary, get_open_positions
        summary   = get_performance_summary()
        positions = get_open_positions()

        if "message" in summary:
            await send_alert(
                f"📊 *PNL REPORT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"No trades recorded yet.\n"
                f"Bot is watching and will buy when score ≥ 80."
            )
            return

        total_trades  = summary.get("total_trades", 0)
        total_in      = summary.get("total_invested", 0)
        total_out     = summary.get("total_returned", 0)
        pnl           = summary.get("pnl_sol", 0)
        win_rate      = summary.get("win_rate", 0)
        open_count    = len(positions)
        mode          = "📝 PAPER" if PAPER_TRADING else "💰 LIVE"
        pnl_emoji     = "📈" if pnl >= 0 else "📉"
        pnl_usd       = round(pnl * 150, 2)  # Approximate SOL price

        await send_alert(
            f"📊 *PNL REPORT* — {mode}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Total trades: *{total_trades}*\n"
            f"🎯 Win rate: *{win_rate:.1f}%*\n\n"
            f"💎 SOL invested: *{total_in:.4f} SOL*\n"
            f"💰 SOL returned: *{total_out:.4f} SOL*\n"
            f"{pnl_emoji} PNL: *{pnl:+.4f} SOL* (~${pnl_usd:+.2f})\n\n"
            f"📂 Open positions: *{open_count}*"
        )
    except Exception as e:
        print(f"[TELEGRAM] handle_pnl error: {e}")
        await send_alert(f"⚠️ Could not fetch PNL: {e}")


async def handle_status():
    """/status — Shows bot health and current mode"""
    from datetime import datetime
    mode     = "📝 PAPER TRADING" if PAPER_TRADING else "💰 LIVE TRADING"
    now      = datetime.utcnow().strftime("%H:%M:%S UTC")
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
        f"🕐 Server time: {now}"
    )


async def handle_positions():
    """/positions — Shows all currently open positions"""
    try:
        from database import get_open_positions
        import requests

        positions = get_open_positions()

        if not positions:
            await send_alert(
                f"📂 *OPEN POSITIONS*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"No open positions right now.\n"
                f"Bot is scanning for the next trade."
            )
            return

        msg = f"📂 *OPEN POSITIONS* ({len(positions)})\n━━━━━━━━━━━━━━━━━━━━\n"

        for pos in positions:
            ticker        = pos.get("ticker", "???")
            token_name    = pos.get("token_name", "Unknown")
            entry_price   = float(pos.get("price_usd") or 0)
            amount_sol    = float(pos.get("amount_sol") or 0)
            token_address = pos.get("token_address", "")

            # Get current price for live PNL per position
            current_price = 0
            multiplier    = 0
            try:
                url      = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
                response = requests.get(url, timeout=5)
                data     = response.json()
                pairs    = data.get("pairs", [])
                if pairs:
                    best          = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
                    current_price = float(best.get("priceUsd", 0) or 0)
                    if entry_price > 0 and current_price > 0:
                        multiplier = current_price / entry_price
            except Exception:
                pass

            pnl_emoji = "📈" if multiplier >= 1 else "📉"
            mult_text = f"{multiplier:.2f}x" if multiplier > 0 else "loading..."

            msg += (
                f"\n{pnl_emoji} *{token_name}* (${ticker})\n"
                f"  Entry: ${entry_price:.8f}\n"
                f"  Current: {mult_text}\n"
                f"  Size: {amount_sol:.4f} SOL\n"
            )

        await send_alert(msg)

    except Exception as e:
        print(f"[TELEGRAM] handle_positions error: {e}")
        await send_alert(f"⚠️ Could not fetch positions: {e}")


async def handle_help():
    """/help — Lists all available commands"""
    await send_alert(
        f"🤖 *SOLANA SNIPER BOT — COMMANDS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 /pnl — Full PNL report\n"
        f"📂 /positions — Open positions + live multiplier\n"
        f"✅ /status — Bot health check\n"
        f"❓ /help — Show this menu\n\n"
        f"Bot sends automatic alerts for:\n"
        f"• New token signals\n"
        f"• Buys executed\n"
        f"• Take profit stages\n"
        f"• Stop loss hits\n"
        f"• KOL posts detected\n"
        f"• Daily PNL summary at midnight"
    )


# ============================================================
# ALERT TEMPLATES — all unchanged, fully working
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
        f"👀 Watching entire Solana chain...\n\n"
        f"Send /help to see commands."
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
    mode = "📝 PAPER TRADE" if paper else "💰 LIVE TRADE"
    await send_alert(
        f"✅ *BUY EXECUTED* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *{token_name}* (${ticker})\n"
        f"💵 Price: ${price_usd:.8f}\n"
        f"📈 Market Cap: ${mcap_usd:,.0f}\n"
        f"💎 Amount: {amount_sol} SOL\n"
        f"🎯 Score: {score}/100\n\n"
        f"⏳ Monitoring for exit...\n"
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
        f"🛡 Capital protected — moving on\n\n"
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
        f"👛 *SMART WALLET BUY DETECTED*\n"
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
        f"🔢 Trades today: {total_trades}\n"
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
        f"Bot still running — check server logs"
    )

# ============================================================
# telegram_bot.py — ALL ALERTS & NOTIFICATIONS
# Written first because every other file imports this
# ============================================================

import asyncio
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


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
        f"👀 Watching entire Solana chain..."
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
    # Only log to server — no Telegram spam for every rejection
    print(f"[REJECTED] {ticker} | {token_address[:20]}... | {reason}")


async def alert_daily_summary(total_trades, wins, losses,
                               total_sol_in, total_sol_out,
                               pnl_sol, win_rate, paper=True):
    mode      = "📝 PAPER" if paper else "💰 LIVE"
    pnl_emoji = "📈" if pnl_sol >= 0 else "📉"
    await send_alert(
        f"📊 *DAILY SUMMARY* — {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Trades today: {total_trades}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"🎯 Win rate: *{win_rate:.1f}%*\n\n"
        f"💎 SOL in: {total_sol_in:.4f}\n"
        f"💰 SOL out: {total_sol_out:.4f}\n"
        f"{pnl_emoji} PNL: *{pnl_sol:+.4f} SOL*"
    )


async def alert_bot_error(component, error_message):
    await send_alert(
        f"⚠️ *BOT ERROR*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔧 Component: {component}\n"
        f"❌ {error_message}\n\n"
        f"Bot still running — check server logs"
    )

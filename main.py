# ============================================================
# main.py — BOT ENTRY POINT
# All engines run simultaneously via asyncio.gather
# One engine crashing never kills the others
# ============================================================

import asyncio
from datetime import datetime, time as dtime, timedelta
from config import PAPER_TRADING, ALPHA_GROUPS, TELEGRAM_API_ID
from keep_alive import keep_alive
from telegram_bot import (
    alert_bot_started,
    alert_daily_summary,
    register_bot_commands,
    start_command_listener
)
from database          import get_performance_summary
from listener          import start_listener
from twitter           import monitor_influencers
from wallet_tracker    import start_wallet_tracker
from exit_manager      import start_exit_manager
from pattern_engine    import start_pattern_engine
from dev_wallet_monitor import start_dev_wallet_monitor


# ============================================================
# DAILY SUMMARY
# ============================================================

async def daily_summary_loop():
    while True:
        now           = datetime.utcnow()
        next_midnight = datetime.combine(now.date(), dtime.min) + timedelta(days=1)
        sleep_secs    = (next_midnight - now).total_seconds()
        print(f"[MAIN] Daily summary in {sleep_secs/3600:.1f}h")
        await asyncio.sleep(sleep_secs)
        try:
            summary = get_performance_summary()
            if "message" not in summary:
                await alert_daily_summary(
                    total_trades  = summary.get("total_trades",   0),
                    wins          = summary.get("total_trades",   0),
                    losses        = 0,
                    total_sol_in  = summary.get("total_invested", 0),
                    total_sol_out = summary.get("total_returned", 0),
                    pnl_sol       = summary.get("pnl_sol",        0),
                    win_rate      = summary.get("win_rate",       0),
                    paper         = PAPER_TRADING
                )
        except Exception as e:
            print(f"[MAIN] Daily summary error: {e}")


# ============================================================
# HEALTH CHECK
# ============================================================

async def health_check_loop():
    while True:
        await asyncio.sleep(600)
        print(f"[MAIN] ✅ {datetime.utcnow().strftime('%H:%M:%S UTC')}")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 55)
    print("  SOLANA AI SNIPER BOT — STARTING UP")
    print("=" * 55)
    print(f"  Mode: {'📝 PAPER' if PAPER_TRADING else '💰 LIVE'}")
    print(f"  Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 55)

    # Register Telegram menu button
    await register_bot_commands()

    # Startup alert
    await alert_bot_started(paper_mode=PAPER_TRADING)

    # Core engines — always run
    engines = [
        start_listener(),           # AI token discovery
        monitor_influencers(),      # KOL Twitter (priority + regular)
        start_wallet_tracker(),     # Autonomous wallet discovery + copy trade
        start_exit_manager(),       # Take profit / stop loss
        start_pattern_engine(),     # On-chain pattern recognition
        start_dev_wallet_monitor(), # Dev wallet pre-launch detection
        start_command_listener(),   # /pnl /status /positions /help
        daily_summary_loop(),       # Midnight PNL report
        health_check_loop(),        # Keep-alive log
    ]

    # Telegram scanner — only if credentials configured
    if TELEGRAM_API_ID and ALPHA_GROUPS:
        from telegram_scanner import start_telegram_scanner
        engines.append(start_telegram_scanner())
        print("[MAIN] ✅ Telegram alpha scanner: ENABLED")
    else:
        print("[MAIN] ⚠️  Telegram scanner: DISABLED")
        print("[MAIN]    → Add TELEGRAM_API_ID + groups to ALPHA_GROUPS to enable")

    # Run all engines — exceptions contained per engine
    await asyncio.gather(*engines, return_exceptions=True)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MAIN] Stopped")
    except Exception as e:
        print(f"[MAIN] Fatal: {e}")

# ============================================================
# main.py — BOT ENTRY POINT
# Starts all 4 engines simultaneously and keeps them running
# ============================================================

import asyncio
from datetime import datetime, time as dtime
from config import PAPER_TRADING
from telegram_bot import (
    alert_bot_started,
    alert_daily_summary,
    alert_bot_error
)
from database import get_performance_summary
from listener       import start_listener
from twitter        import monitor_influencers
from wallet_tracker import start_wallet_tracker
from exit_manager   import start_exit_manager


# ============================================================
# DAILY SUMMARY — fires at midnight every day
# ============================================================

async def daily_summary_loop():
    while True:
        now = datetime.utcnow()
        # Calculate seconds until next midnight
        midnight   = datetime.combine(now.date(), dtime.min)
        from datetime import timedelta
        next_midnight = midnight + timedelta(days=1)
        sleep_secs = (next_midnight - now).total_seconds()

        print(f"[MAIN] Daily summary in {sleep_secs/3600:.1f} hours")
        await asyncio.sleep(sleep_secs)

        try:
            summary = get_performance_summary()
            if "message" not in summary:
                await alert_daily_summary(
                    total_trades = summary.get("total_trades", 0),
                    wins         = summary.get("total_trades", 0),
                    losses       = 0,
                    total_sol_in = summary.get("total_invested", 0),
                    total_sol_out= summary.get("total_returned", 0),
                    pnl_sol      = summary.get("pnl_sol", 0),
                    win_rate     = summary.get("win_rate", 0),
                    paper        = PAPER_TRADING
                )
        except Exception as e:
            print(f"[MAIN] Daily summary error: {e}")


# ============================================================
# HEALTH CHECK — prints status every 10 minutes
# ============================================================

async def health_check_loop():
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        print(f"[MAIN] ✅ Bot alive — {datetime.utcnow().strftime('%H:%M:%S UTC')}")


# ============================================================
# MAIN — starts everything simultaneously
# ============================================================

async def main():
    print("=" * 50)
    print("  SOLANA AI SNIPER BOT — STARTING UP")
    print("=" * 50)

    mode = "📝 PAPER TRADING" if PAPER_TRADING else "💰 LIVE TRADING"
    print(f"  Mode: {mode}")
    print(f"  Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 50)

    # Send startup alert to Telegram
    await alert_bot_started(paper_mode=PAPER_TRADING)

    # Run all 5 tasks simultaneously
    # If any one crashes, the others keep running
    # Each engine has its own reconnect logic
    await asyncio.gather(
        start_listener(),        # Engine 1: AI token discovery
        monitor_influencers(),   # Engine 1b: KOL Twitter monitor
        start_wallet_tracker(),  # Engine 2: Smart wallet copy trading
        start_exit_manager(),    # Exit: Take profit / stop loss
        daily_summary_loop(),    # Reporting: Daily PNL summary
        health_check_loop(),     # Monitoring: Keep-alive log
        return_exceptions=True   # Don't let one crash kill all
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MAIN] Bot stopped by user")
    except Exception as e:
        print(f"[MAIN] Fatal error: {e}")

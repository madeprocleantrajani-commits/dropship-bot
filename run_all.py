"""
Master Runner v2
-----------------
Runs all bots in sequence (or specific ones).

Usage:
  python run_all.py                    # Run everything
  python run_all.py amazon ebay        # Run specific bots
  python run_all.py report             # Just generate report

Available bots (in execution order):
  trends       - Google Trends scanner
  amazon       - Amazon Best Sellers tracker
  demand       - Amazon autocomplete demand scanner
  ebay         - eBay sold listings scanner
  aliexpress   - AliExpress product research
  prices       - Price monitor
  competitors  - Competitor store tracker
  discover     - Auto-discover competitor stores
  report       - Daily intelligence report
"""

import sys
import time
from datetime import datetime
from config import get_logger
from alert_bot import send_alert

log = get_logger("runner")

BOTS = {
    "trends": ("trend_scanner", "run_full_scan"),
    "amazon": ("amazon_tracker", "run_amazon_scan"),
    "demand": ("amazon_demand", "scan_demand"),
    "ebay": ("ebay_scanner", "run_ebay_scan"),
    "aliexpress": ("aliexpress_scanner", "run_aliexpress_scan"),
    "prices": ("price_monitor", "check_prices"),
    "competitors": ("competitor_tracker", "run_competitor_scan"),
    "discover": ("competitor_finder", "discover_competitors"),
    "report": ("report_generator", "generate_daily_report"),
}

# Default order — optimized for data dependencies
DEFAULT_ORDER = [
    "trends", "amazon", "demand", "ebay",
    "aliexpress", "prices", "competitors", "report",
]


def run_bot(name: str) -> bool:
    if name not in BOTS:
        log.error(f"Unknown bot: {name}. Available: {', '.join(BOTS.keys())}")
        return False

    module_name, func_name = BOTS[name]
    log.info(f"Starting: {name}")

    try:
        module = __import__(module_name)
        func = getattr(module, func_name)
        func()
        log.info(f"Completed: {name}")
        return True
    except Exception as e:
        log.error(f"FAILED: {name} — {e}")
        send_alert(f"BOT FAILURE: {name}\nError: {str(e)[:200]}")
        return False


def main():
    start_time = datetime.now()

    if len(sys.argv) > 1:
        bot_names = sys.argv[1:]
    else:
        bot_names = DEFAULT_ORDER

    log.info(f"=== DROPSHIP BOT SUITE v2 — {start_time.strftime('%Y-%m-%d %H:%M')} ===")
    log.info(f"Running: {', '.join(bot_names)}")

    results = {}
    for name in bot_names:
        success = run_bot(name)
        results[name] = "OK" if success else "FAILED"
        time.sleep(2)

    elapsed = (datetime.now() - start_time).total_seconds()
    log.info(f"=== COMPLETE in {elapsed:.0f}s ===")
    for name, status in results.items():
        log.info(f"  {name}: {status}")

    failed = [n for n, s in results.items() if s == "FAILED"]
    if failed:
        send_alert(f"BOT RUN COMPLETE (failures)\nFailed: {', '.join(failed)}")


if __name__ == "__main__":
    main()

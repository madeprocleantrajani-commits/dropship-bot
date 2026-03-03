#!/usr/bin/env python3
"""
Dropship Bot Monitor
--------------------
Watch all bots from your terminal.

Usage:
  python monitor.py              Show full status dashboard
  python monitor.py status       Same as above
  python monitor.py data         Show latest data summary
  python monitor.py logs         Tail all logs in real time (Ctrl+C to stop)
  python monitor.py report       Print latest report to screen
"""

import sys
import os
import json
import glob
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"


def _fmt_size(size_bytes: int) -> str:
    """Format file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _load_json(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None


def show_status():
    """Full status dashboard."""
    print()
    print("╔" + "═" * 56 + "╗")
    print("║" + " DROPSHIP BOT STATUS DASHBOARD ".center(56) + "║")
    print("║" + f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ".center(56) + "║")
    print("╚" + "═" * 56 + "╝")

    # ── Data Files ──
    print("\n  DATA FILES:")
    print("  " + "─" * 54)

    prefixes = [
        ("trends", "Google Trends"),
        ("amazon", "Amazon BSR"),
        ("aliexpress", "AliExpress"),
        ("competitors", "Competitors"),
        ("prices", "Price Monitor"),
        ("analysis", "Intelligence"),
    ]

    for prefix, label in prefixes:
        files = sorted(glob.glob(str(DATA_DIR / f"{prefix}_*.json")), reverse=True)
        if files:
            stat = os.stat(files[0])
            size = _fmt_size(stat.st_size)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
            name = os.path.basename(files[0])

            # Quick check if data is actually useful
            data = _load_json(files[0])
            status = "✓"
            note = ""
            if data:
                if prefix == "trends":
                    hot = len(data.get("hot_products", []))
                    disc = len(data.get("discoveries", []))
                    if hot == 0 and disc == 0:
                        has_kw_data = any(
                            n.get("keywords")
                            for n in data.get("niches", {}).values()
                        )
                        if not has_kw_data:
                            status = "⚠"
                            note = "(empty — rate limited?)"
                        else:
                            note = f"({hot} hot, {disc} disc)"
                    else:
                        note = f"({hot} hot, {disc} disc)"
                elif prefix == "amazon":
                    prods = data.get("total_products_scanned", 0)
                    movers = data.get("total_movers_found", 0)
                    note = f"({prods} products, {movers} movers)"
                elif prefix == "aliexpress":
                    found = data.get("total_products_found", 0)
                    if found == 0:
                        status = "⚠"
                        note = "(0 products — blocked?)"
                    else:
                        note = f"({found} products)"
                elif prefix == "analysis":
                    cands = len(data.get("amazon", {}).get("dropship_candidates", []))
                    cross = len(data.get("cross_references", []))
                    note = f"({cands} candidates, {cross} cross-matches)"

            print(f"  {status} {label:<16} {size:>8}  {mtime}  {note}")
        else:
            print(f"  ✗ {label:<16} {'—':>8}  No data yet")

    # ── Log Files ──
    print("\n  BOT LOGS:")
    print("  " + "─" * 54)

    log_files = sorted(glob.glob(str(LOGS_DIR / "*.log")))
    for log_file in log_files:
        stat = os.stat(log_file)
        name = os.path.basename(log_file)
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
        size = _fmt_size(stat.st_size)

        # Get last line
        try:
            with open(log_file) as f:
                lines = f.readlines()
                if lines:
                    last = lines[-1].strip()
                    # Extract just the message part after the pipe separators
                    parts = last.split(" | ")
                    if len(parts) >= 4:
                        last = parts[-1]
                    last = last[:55]
                else:
                    last = "(empty)"
        except:
            last = "(error)"

        print(f"  {name:<28} {size:>8}  {mtime}")
        print(f"    └ {last}")

    # ── Latest Report ──
    print("\n  REPORTS:")
    print("  " + "─" * 54)

    reports = sorted(glob.glob(str(REPORTS_DIR / "daily_*.txt")), reverse=True)
    if reports:
        stat = os.stat(reports[0])
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
        size = _fmt_size(stat.st_size)
        print(f"  Latest: {os.path.basename(reports[0])}  ({size}, {mtime})")
    else:
        print("  No reports yet. Run: python report_generator.py")

    # ── Cron Schedule ──
    print("\n  CRON SCHEDULE:")
    print("  " + "─" * 54)
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        cron_lines = [
            l for l in result.stdout.splitlines() if "dropship" in l
        ]
        if cron_lines:
            for line in cron_lines:
                print(f"  {line}")
        else:
            print("  No cron jobs found for dropship-bots")
    except:
        print("  Could not read crontab")

    print()


def show_data_summary():
    """Show summary of latest data from each source."""
    print()
    print("═" * 56)
    print("  LATEST DATA SUMMARY")
    print("═" * 56)

    # Amazon
    files = sorted(glob.glob(str(DATA_DIR / "amazon_*.json")), reverse=True)
    if files:
        data = _load_json(files[0])
        if data:
            print(f"\n  AMAZON ({os.path.basename(files[0])}):")
            print(f"  Products: {data.get('total_products_scanned', 0)}")
            print(f"  Movers: {data.get('total_movers_found', 0)}")
            cats = data.get("best_sellers", {})
            for cat, products in cats.items():
                print(f"    {cat}: {len(products)} best sellers")
                for p in products[:3]:
                    print(f"      #{p.get('rank', '?')} {p.get('title', '?')[:45]}")
            movers = data.get("movers_and_shakers", {})
            for cat, m_list in movers.items():
                if m_list:
                    print(f"    {cat} movers: {len(m_list)}")
                    for m in m_list[:3]:
                        print(f"      ↑ {m.get('title', '?')[:45]}")

    # Trends
    files = sorted(glob.glob(str(DATA_DIR / "trends_*.json")), reverse=True)
    if files:
        data = _load_json(files[0])
        if data:
            print(f"\n  TRENDS ({os.path.basename(files[0])}):")
            hot = data.get("hot_products", [])
            disc = data.get("discoveries", [])
            print(f"  Hot: {len(hot)}  |  Discoveries: {len(disc)}")
            for h in hot[:5]:
                print(
                    f"    ↑ {h['keyword']}  "
                    f"(interest: {h.get('current_interest', 0)}/100)"
                )
            for d in disc[:5]:
                print(f"    ▲ \"{d['query']}\" +{d.get('growth', 0)}%")

    # AliExpress
    files = sorted(glob.glob(str(DATA_DIR / "aliexpress_*.json")), reverse=True)
    if files:
        data = _load_json(files[0])
        if data:
            print(f"\n  ALIEXPRESS ({os.path.basename(files[0])}):")
            print(f"  Products: {data.get('total_products_found', 0)}")
            deals = data.get("best_deals", [])
            if deals:
                print(f"  Best deals:")
                for d in deals[:5]:
                    print(
                        f"    ${d.get('source_price', '?')} → "
                        f"${d.get('potential_retail', '?')} retail  "
                        f"{d.get('title', '?')[:35]}"
                    )

    # Analysis
    files = sorted(glob.glob(str(DATA_DIR / "analysis_*.json")), reverse=True)
    if files:
        data = _load_json(files[0])
        if data:
            print(f"\n  INTELLIGENCE ({os.path.basename(files[0])}):")
            cands = data.get("amazon", {}).get("dropship_candidates", [])
            cross = data.get("cross_references", [])
            print(f"  Candidates: {len(cands)}  |  Cross-matches: {len(cross)}")
            if cands:
                print("  Top candidates:")
                for c in cands[:5]:
                    print(
                        f"    {c.get('dropship_score', 0)}/100  "
                        f"{c['title'][:40]}"
                    )
            niches = data.get("niche_scores", {})
            if niches:
                sorted_n = sorted(
                    niches.values(), key=lambda x: x["total"], reverse=True
                )
                print("  Niche grades:")
                for ns in sorted_n:
                    name = ns["name"].replace("_", " ")
                    print(f"    {ns['grade']}  {name} ({ns['total']}/100)")

    print()


def show_report():
    """Print latest report."""
    reports = sorted(glob.glob(str(REPORTS_DIR / "daily_*.txt")), reverse=True)
    if reports:
        with open(reports[0]) as f:
            print(f.read())
    else:
        print("No reports found. Run: python report_generator.py")


def watch_logs():
    """Tail all log files in real time."""
    print("═" * 56)
    print("  LIVE LOG MONITOR")
    print("  Ctrl+C to exit")
    print("═" * 56)
    print()

    log_files = sorted(glob.glob(str(LOGS_DIR / "*.log")))
    if not log_files:
        print("No log files found. Run a bot first.")
        return

    try:
        subprocess.run(["tail", "-f", "-n", "20"] + log_files)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


# ── Main ──

if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "status"

    if cmd in ("status", "s"):
        show_status()
    elif cmd in ("data", "d"):
        show_data_summary()
    elif cmd in ("logs", "l", "watch", "tail"):
        watch_logs()
    elif cmd in ("report", "r"):
        show_report()
    else:
        print(f"Unknown command: {cmd}")
        print()
        print("Usage:")
        print("  python monitor.py              Full status dashboard")
        print("  python monitor.py status       Same as above")
        print("  python monitor.py data         Latest data summary")
        print("  python monitor.py logs         Tail logs (real-time)")
        print("  python monitor.py report       Print latest report")

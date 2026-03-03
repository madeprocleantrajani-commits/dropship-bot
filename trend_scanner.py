"""
Google Trends Scanner
---------------------
Scans seed keywords for:
  - Interest over time (is demand rising or falling?)
  - Related rising queries (discover new product ideas)
  - Regional interest (which US states search most)

Outputs: data/trends_YYYY-MM-DD.json
Run: daily via cron
"""
import json
import time
import random
from datetime import datetime
from pytrends.request import TrendReq

from config import (
    SEED_KEYWORDS, TRENDS_GEO, TRENDS_TIMEFRAME,
    DATA_DIR, PROXY_URL, get_logger,
)
from alert_bot import send_alert

log = get_logger("trend_scanner")


def scan_interest_over_time(pytrends, keywords: list[str]) -> dict:
    """Get interest over time for a batch of keywords (max 5)."""
    try:
        pytrends.build_payload(keywords, cat=0, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO)
        df = pytrends.interest_over_time()
        if df.empty:
            return {}

        results = {}
        for kw in keywords:
            if kw in df.columns:
                values = df[kw].tolist()
                results[kw] = {
                    "current": values[-1] if values else 0,
                    "avg": round(sum(values) / len(values), 1) if values else 0,
                    "max": max(values) if values else 0,
                    "min": min(values) if values else 0,
                    "trend": "rising" if len(values) >= 4 and values[-1] > sum(values[-4:]) / 4 else "stable_or_falling",
                    "last_7": values[-7:] if len(values) >= 7 else values,
                }
        return results
    except Exception as e:
        log.error(f"Interest over time failed for {keywords}: {e}")
        return {}


def scan_rising_queries(pytrends, keyword: str) -> list[dict]:
    """Find rising related queries — these are goldmine product ideas."""
    try:
        pytrends.build_payload([keyword], cat=0, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO)
        related = pytrends.related_queries()

        rising = related.get(keyword, {}).get("rising")
        if rising is not None and not rising.empty:
            return rising.head(15).to_dict("records")
        return []
    except Exception as e:
        log.error(f"Rising queries failed for {keyword}: {e}")
        return []


def scan_top_queries(pytrends, keyword: str) -> list[dict]:
    """Find top related queries — stable demand indicators."""
    try:
        pytrends.build_payload([keyword], cat=0, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO)
        related = pytrends.related_queries()

        top = related.get(keyword, {}).get("top")
        if top is not None and not top.empty:
            return top.head(10).to_dict("records")
        return []
    except Exception as e:
        log.error(f"Top queries failed for {keyword}: {e}")
        return []


def scan_regional_interest(pytrends, keyword: str) -> list[dict]:
    """See which US states search this product most."""
    try:
        pytrends.build_payload([keyword], cat=0, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO)
        df = pytrends.interest_by_region(resolution="REGION", inc_low_vol=False)
        if df.empty:
            return []

        df = df.sort_values(by=keyword, ascending=False)
        top_regions = df.head(10)
        return [
            {"region": idx, "interest": int(row[keyword])}
            for idx, row in top_regions.iterrows()
        ]
    except Exception as e:
        log.error(f"Regional interest failed for {keyword}: {e}")
        return []


def run_full_scan():
    """Run a complete trend scan across all seed keywords."""
    log.info("Starting full trend scan...")
    # Build requests args with optional proxy
    req_args = {
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    }
    if PROXY_URL:
        req_args["proxies"] = {"https": PROXY_URL, "http": PROXY_URL}
        log.info("Using proxy for Google Trends requests")

    pytrends = TrendReq(
        hl="en-US", tz=360, retries=3, backoff_factor=3.0,
        requests_args=req_args,
    )

    report = {
        "scan_date": datetime.now().isoformat(),
        "geo": TRENDS_GEO,
        "timeframe": TRENDS_TIMEFRAME,
        "niches": {},
        "hot_products": [],  # Products with rising demand
        "discoveries": [],   # New product ideas from rising queries
    }

    for niche_name, keywords in SEED_KEYWORDS.items():
        log.info(f"Scanning niche: {niche_name} ({len(keywords)} keywords)")
        niche_data = {"keywords": {}}

        # Process in batches of 5 (Google Trends limit)
        for i in range(0, len(keywords), 5):
            batch = keywords[i:i+5]
            interest = scan_interest_over_time(pytrends, batch)
            niche_data["keywords"].update(interest)
            time.sleep(random.uniform(8, 15))  # Longer delay for datacenter IPs

        # Get rising/top queries for each keyword
        for kw in keywords:
            if kw in niche_data["keywords"]:
                rising = scan_rising_queries(pytrends, kw)
                top = scan_top_queries(pytrends, kw)
                niche_data["keywords"][kw]["rising_queries"] = rising
                niche_data["keywords"][kw]["top_queries"] = top

                # Flag hot products
                kw_data = niche_data["keywords"][kw]
                if kw_data.get("trend") == "rising" and kw_data.get("current", 0) > 50:
                    report["hot_products"].append({
                        "keyword": kw,
                        "niche": niche_name,
                        "current_interest": kw_data["current"],
                        "avg_interest": kw_data["avg"],
                    })

                # Collect discoveries from rising queries
                for rq in rising:
                    if rq.get("value", 0) > 200:  # "Breakout" threshold
                        report["discoveries"].append({
                            "query": rq["query"],
                            "growth": rq["value"],
                            "source_keyword": kw,
                            "niche": niche_name,
                        })

                time.sleep(random.uniform(8, 12))

        report["niches"][niche_name] = niche_data

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"trends_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Trend report saved: {output_file}")
    log.info(f"Hot products found: {len(report['hot_products'])}")
    log.info(f"New discoveries: {len(report['discoveries'])}")

    # Send Telegram alert if there are hot findings
    if report["hot_products"] or report["discoveries"]:
        msg = f"TREND SCAN COMPLETE\n"
        msg += f"Date: {today}\n\n"

        if report["hot_products"]:
            msg += "HOT PRODUCTS (rising demand):\n"
            for p in report["hot_products"][:5]:
                msg += f"  - {p['keyword']} (interest: {p['current_interest']}/100)\n"

        if report["discoveries"]:
            msg += "\nNEW DISCOVERIES (breakout queries):\n"
            for d in report["discoveries"][:5]:
                msg += f"  - \"{d['query']}\" (+{d['growth']}%) from {d['source_keyword']}\n"

        send_alert(msg)

    return report


if __name__ == "__main__":
    run_full_scan()

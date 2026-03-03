"""
Amazon Demand Scanner
----------------------
Taps Amazon's autocomplete API to discover what buyers
are ACTUALLY searching for. No scraping, no IP blocking.

This is free demand data straight from Amazon:
  - Type "portable b" → Amazon suggests "portable blender",
    "portable battery charger", "portable bidet"...
  - The ORDER of suggestions = relative search volume
  - Suggestions that appear = proven buyer intent

Also expands each seed keyword to find related product ideas
you haven't thought of yet.

Outputs: data/demand_YYYY-MM-DD.json
Run: daily via cron (lightweight, no rate limits)
"""

import json
import time
import random
import string
from datetime import datetime
from urllib.parse import quote_plus

import requests

from config import DATA_DIR, SEED_KEYWORDS, get_logger, is_physical_product
from alert_bot import send_alert

log = get_logger("amazon_demand")

AUTOCOMPLETE_URL = (
    "https://completion.amazon.com/api/2017/suggestions"
    "?mid=ATVPDKIKX0DER"
    "&alias=aps"
    "&prefix={query}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def get_suggestions(query: str) -> list[str]:
    """Get Amazon autocomplete suggestions for a query."""
    url = AUTOCOMPLETE_URL.format(query=quote_plus(query))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        suggestions = []
        for item in data.get("suggestions", []):
            value = item.get("value", "")
            if value and is_physical_product(value):
                suggestions.append(value)
        return suggestions
    except Exception as e:
        log.error(f"Autocomplete failed for '{query}': {e}")
        return []


def expand_keyword(keyword: str) -> dict:
    """
    Expand a keyword by appending letters a-z to discover
    deeper product ideas.
    Example: "portable blender" → try "portable blender a",
    "portable blender b", etc.
    """
    expansions = {}

    # Base suggestions
    base = get_suggestions(keyword)
    expansions["base"] = base
    time.sleep(random.uniform(0.3, 0.8))

    # Letter expansions (a-z)
    for letter in string.ascii_lowercase:
        query = f"{keyword} {letter}"
        suggestions = get_suggestions(query)
        if suggestions:
            # Only keep suggestions we haven't seen
            new = [s for s in suggestions if s not in base]
            if new:
                expansions[letter] = new
        time.sleep(random.uniform(0.2, 0.5))

    return expansions


def scan_demand() -> dict:
    """Scan Amazon demand for all seed keywords."""
    log.info("Starting Amazon demand scan...")

    report = {
        "scan_date": datetime.now().isoformat(),
        "keywords": {},
        "all_suggestions": [],  # Flat list of every unique suggestion
        "top_discoveries": [],  # Suggestions NOT in our seed keywords
    }

    seen = set()
    all_seed_kws = set()
    for keywords in SEED_KEYWORDS.values():
        for kw in keywords:
            all_seed_kws.add(kw.lower())

    for niche, keywords in SEED_KEYWORDS.items():
        log.info(f"Scanning niche: {niche}")

        for kw in keywords:
            log.info(f"  Expanding: {kw}")

            # Get base suggestions (what Amazon shows when you type this)
            base = get_suggestions(kw)
            time.sleep(random.uniform(0.5, 1.0))

            # Expand with letter suffixes for deeper discovery
            expanded = []
            for letter in "abcdefghijklmnop":  # First 16 letters
                query = f"{kw} {letter}"
                suggestions = get_suggestions(query)
                new = [s for s in suggestions if s not in base and s not in expanded]
                expanded.extend(new)
                time.sleep(random.uniform(0.2, 0.5))

            kw_data = {
                "niche": niche,
                "base_suggestions": base,
                "expanded_suggestions": expanded[:30],
                "total_ideas": len(base) + len(expanded),
            }
            report["keywords"][kw] = kw_data

            # Collect all unique suggestions
            for s in base + expanded:
                s_lower = s.lower()
                if s_lower not in seen:
                    seen.add(s_lower)
                    report["all_suggestions"].append(s)

                    # Discovery = suggestion not matching any seed keyword
                    if s_lower not in all_seed_kws:
                        is_new = True
                        for seed in all_seed_kws:
                            if seed in s_lower or s_lower in seed:
                                is_new = False
                                break
                        if is_new:
                            report["top_discoveries"].append({
                                "suggestion": s,
                                "source_keyword": kw,
                                "niche": niche,
                            })

    # Sort discoveries by length (shorter = more popular/generic)
    report["top_discoveries"].sort(key=lambda x: len(x["suggestion"]))

    # Stats
    report["stats"] = {
        "keywords_scanned": len(report["keywords"]),
        "total_unique_suggestions": len(report["all_suggestions"]),
        "new_discoveries": len(report["top_discoveries"]),
    }

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"demand_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(
        f"Demand scan complete: {report['stats']['total_unique_suggestions']} "
        f"suggestions, {report['stats']['new_discoveries']} discoveries"
    )
    log.info(f"Saved: {output_file}")

    # Telegram alert
    if report["top_discoveries"]:
        msg = "AMAZON DEMAND SCAN\n"
        msg += f"Keywords: {report['stats']['keywords_scanned']}\n"
        msg += f"Suggestions: {report['stats']['total_unique_suggestions']}\n"
        msg += f"New ideas: {report['stats']['new_discoveries']}\n\n"
        msg += "TOP DISCOVERIES:\n"
        for d in report["top_discoveries"][:10]:
            msg += f"  • {d['suggestion']} (from: {d['source_keyword']})\n"
        send_alert(msg)

    return report


if __name__ == "__main__":
    scan_demand()

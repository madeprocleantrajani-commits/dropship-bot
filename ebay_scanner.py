"""
eBay Sold Listings Scanner
----------------------------
Scrapes eBay's completed/sold listings to answer the question:
"Is anyone ACTUALLY buying this product?"

Amazon BSR tells you what's popular.
eBay sold listings tell you what people PAID MONEY for recently.

For each seed keyword, we find:
  - How many sold in the last 30 days
  - What prices they sold at (min, avg, max)
  - Price distribution (what buyers are willing to pay)
  - Sell-through rate indicator

This is the ultimate demand validation — real transactions, not rankings.

Outputs: data/ebay_YYYY-MM-DD.json
Run: daily via cron
"""

import json
import re
import time
import random
from datetime import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config import (
    DATA_DIR, SEED_KEYWORDS, get_logger, get_session,
    is_physical_product, parse_price,
)
from alert_bot import send_alert

log = get_logger("ebay_scanner")

EBAY_SOLD_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw={query}"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"  # Sort by most recent
    "&_ipg=60"  # 60 results per page
)


def scrape_sold_listings(keyword: str) -> dict:
    """
    Scrape eBay sold/completed listings for a keyword.
    Returns sold count, price analysis, and top listings.
    """
    session = get_session(use_proxy=True)
    url = EBAY_SOLD_URL.format(query=quote_plus(keyword))

    result = {
        "keyword": keyword,
        "sold_count": 0,
        "listings": [],
        "prices": [],
        "price_analysis": {},
    }

    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            log.warning(f"eBay returned {resp.status_code} for '{keyword}'")
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # Total results count
        count_el = soup.select_one(".srp-controls__count-heading span")
        if count_el:
            count_text = count_el.get_text(strip=True).replace(",", "")
            try:
                result["sold_count"] = int(re.search(r"\d+", count_text).group())
            except (ValueError, AttributeError):
                pass

        # Individual listings
        items = soup.select(".s-item")

        for item in items[:40]:
            listing = {}

            # Title
            title_el = item.select_one(".s-item__title")
            if title_el:
                title = title_el.get_text(strip=True)
                # Skip "Shop on eBay" promo cards
                if "shop on ebay" in title.lower():
                    continue
                listing["title"] = title

            if not listing.get("title"):
                continue

            # Skip digital products
            if not is_physical_product(listing["title"]):
                continue

            # Sold price
            price_el = item.select_one(".s-item__price")
            if price_el:
                price_text = price_el.get_text(strip=True)
                listing["price_raw"] = price_text

                # Handle price ranges "US $10.99 to $15.99"
                prices_found = re.findall(r"\$?([\d,.]+)", price_text)
                if prices_found:
                    try:
                        listing["price"] = float(prices_found[0].replace(",", ""))
                        result["prices"].append(listing["price"])
                    except ValueError:
                        pass

            # Sold date
            sold_el = item.select_one(".s-item__title--tagblock .POSITIVE")
            if sold_el:
                listing["sold_date"] = sold_el.get_text(strip=True)

            # Shipping
            ship_el = item.select_one(".s-item__shipping")
            if ship_el:
                listing["shipping"] = ship_el.get_text(strip=True)

            # Seller
            seller_el = item.select_one(".s-item__seller-info-text")
            if seller_el:
                listing["seller"] = seller_el.get_text(strip=True)

            # URL
            link_el = item.select_one(".s-item__link")
            if link_el:
                listing["url"] = link_el.get("href", "")

            result["listings"].append(listing)

        # Price analysis
        if result["prices"]:
            prices = result["prices"]
            result["price_analysis"] = {
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "avg": round(sum(prices) / len(prices), 2),
                "median": round(sorted(prices)[len(prices) // 2], 2),
                "under_15": sum(1 for p in prices if p < 15),
                "15_to_30": sum(1 for p in prices if 15 <= p < 30),
                "30_to_50": sum(1 for p in prices if 30 <= p < 50),
                "over_50": sum(1 for p in prices if p >= 50),
                "sample_size": len(prices),
            }

        log.info(
            f"eBay '{keyword}': {result['sold_count']} sold, "
            f"{len(result['listings'])} scraped, "
            f"avg ${result['price_analysis'].get('avg', 0):.2f}"
        )

    except requests.RequestException as e:
        log.error(f"Request failed for '{keyword}': {e}")
    except Exception as e:
        log.error(f"Parse error for '{keyword}': {e}")

    return result


def run_ebay_scan(keywords: list[str] = None) -> dict:
    """Scan eBay sold listings for all seed keywords."""
    log.info("Starting eBay sold listings scan...")

    if not keywords:
        keywords = []
        for niche_kws in SEED_KEYWORDS.values():
            keywords.extend(niche_kws)

    report = {
        "scan_date": datetime.now().isoformat(),
        "keywords_scanned": len(keywords),
        "results": {},
        "top_sellers": [],  # Keywords with most sold items
        "price_insights": [],  # Best price intelligence
    }

    for kw in keywords:
        log.info(f"Scanning: {kw}")
        data = scrape_sold_listings(kw)
        report["results"][kw] = {
            "sold_count": data["sold_count"],
            "listings_scraped": len(data["listings"]),
            "price_analysis": data["price_analysis"],
            "top_listings": data["listings"][:5],
        }
        time.sleep(random.uniform(3, 6))

    # Rank keywords by sold count
    ranked = sorted(
        report["results"].items(),
        key=lambda x: x[1]["sold_count"],
        reverse=True,
    )

    for kw, data in ranked[:15]:
        if data["sold_count"] > 0:
            report["top_sellers"].append({
                "keyword": kw,
                "sold_count": data["sold_count"],
                "avg_price": data["price_analysis"].get("avg", 0),
                "median_price": data["price_analysis"].get("median", 0),
            })

    # Price insights — keywords where avg sold price suggests good margins
    for kw, data in ranked:
        pa = data.get("price_analysis", {})
        if pa.get("avg", 0) >= 15 and data["sold_count"] >= 10:
            report["price_insights"].append({
                "keyword": kw,
                "sold_count": data["sold_count"],
                "avg_sold_price": pa["avg"],
                "price_range": f"${pa.get('min', 0):.2f}–${pa.get('max', 0):.2f}",
            })

    # Stats
    report["stats"] = {
        "total_sold_found": sum(
            r["sold_count"] for r in report["results"].values()
        ),
        "keywords_with_sales": sum(
            1 for r in report["results"].values() if r["sold_count"] > 0
        ),
        "avg_sold_price_all": 0,
    }

    all_prices = []
    for r in report["results"].values():
        if r["price_analysis"].get("avg"):
            all_prices.append(r["price_analysis"]["avg"])
    if all_prices:
        report["stats"]["avg_sold_price_all"] = round(
            sum(all_prices) / len(all_prices), 2
        )

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"ebay_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"eBay scan complete: {output_file}")

    # Telegram alert
    if report["top_sellers"]:
        msg = "EBAY SOLD LISTINGS SCAN\n"
        msg += f"Keywords: {len(keywords)}\n"
        msg += f"Total sold items found: {report['stats']['total_sold_found']}\n\n"
        msg += "TOP SELLERS (most sold):\n"
        for ts in report["top_sellers"][:8]:
            msg += (
                f"  {ts['keyword']}: {ts['sold_count']} sold "
                f"(avg ${ts['avg_price']:.2f})\n"
            )
        send_alert(msg)

    return report


if __name__ == "__main__":
    run_ebay_scan()

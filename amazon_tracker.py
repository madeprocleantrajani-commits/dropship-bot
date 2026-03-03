"""
Amazon Best Sellers Tracker v2
-------------------------------
Tracks Amazon Best Sellers and Movers & Shakers.

v2 changes:
  - Physical product filter (no digital/subscriptions)
  - Brand flagging (marks major brands as non-dropshippable)
  - BSR history tracking (rank change vs yesterday)
  - EUR→USD price conversion
  - Proxy support
  - Review count parsing

Outputs: data/amazon_YYYY-MM-DD.json
Run: daily via cron
"""

import json
import time
import random
import glob
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import (
    AMAZON_CATEGORIES, DATA_DIR, REQUEST_DELAY, get_logger, get_session,
    is_physical_product, is_major_brand, parse_price, to_usd,
)
from alert_bot import send_alert

log = get_logger("amazon_tracker")


def _load_yesterday() -> dict | None:
    """Load yesterday's scan for BSR history comparison."""
    files = sorted(glob.glob(str(DATA_DIR / "amazon_*.json")), reverse=True)
    # Skip today's file if it exists, grab the previous one
    today = datetime.now().strftime("%Y-%m-%d")
    for f in files:
        if today not in f:
            try:
                with open(f) as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, IOError):
                pass
    return None


def _build_asin_rank_map(yesterday: dict | None) -> dict:
    """Build ASIN → rank mapping from yesterday's data."""
    if not yesterday:
        return {}
    rank_map = {}
    for cat, products in yesterday.get("best_sellers", {}).items():
        for p in products:
            asin = p.get("asin", "")
            if asin:
                rank_map[asin] = {
                    "rank": p.get("rank", 999),
                    "category": cat,
                    "price": p.get("price_raw", ""),
                }
    return rank_map


def scrape_best_sellers(session: requests.Session, category: str, url: str) -> list[dict]:
    """Scrape top products from an Amazon Best Sellers page."""
    products = []

    try:
        response = session.get(url, timeout=15)
        if response.status_code != 200:
            log.warning(f"Amazon returned {response.status_code} for {category}")
            return products

        soup = BeautifulSoup(response.text, "html.parser")

        items = soup.select("[data-asin]")
        if not items:
            items = soup.select(".zg-grid-general-faceout")

        for rank, item in enumerate(items[:30], 1):
            product = {"rank": rank, "category": category}

            # Title
            title_el = item.select_one(
                ".p13n-sc-truncate, "
                "._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y, "
                ".a-link-normal span"
            )
            if title_el:
                product["title"] = title_el.get_text(strip=True)

            # Skip digital products
            if not product.get("title") or not is_physical_product(product["title"]):
                continue

            # Flag major brands
            product["is_brand"] = is_major_brand(product["title"])

            # Price (raw from page — may be EUR from Ireland VPS)
            price_el = item.select_one(
                ".p13n-sc-price, "
                "._cDEzb_p13n-sc-price_3mJ9Z, "
                ".a-price .a-offscreen"
            )
            if price_el:
                product["price_raw"] = price_el.get_text(strip=True)
                product["price_eur"] = parse_price(product["price_raw"])
                product["price_usd"] = to_usd(product["price_eur"])

            # Rating
            rating_el = item.select_one(".a-icon-alt, [aria-label*='out of 5']")
            if rating_el:
                text = (
                    rating_el.get_text(strip=True)
                    if rating_el.name != "i"
                    else rating_el.get("aria-label", "")
                )
                product["rating_raw"] = text
                try:
                    product["rating"] = float(text.split()[0])
                except (ValueError, IndexError):
                    product["rating"] = None

            # Review count
            review_el = item.select_one(".a-size-small span:last-child")
            if review_el:
                review_text = review_el.get_text(strip=True).replace(",", "")
                try:
                    product["review_count"] = int(review_text)
                except ValueError:
                    product["review_count_raw"] = review_text

            # ASIN
            asin = item.get("data-asin", "")
            if asin:
                product["asin"] = asin
                product["url"] = f"https://www.amazon.com/dp/{asin}"

            products.append(product)

        log.info(f"Scraped {len(products)} physical products from {category}")

    except requests.RequestException as e:
        log.error(f"Request failed for {category}: {e}")
    except Exception as e:
        log.error(f"Parse error for {category}: {e}")

    return products


def scrape_movers_and_shakers(session: requests.Session, category: str) -> list[dict]:
    """
    Scrape Movers & Shakers — products with biggest rank improvements
    in the last 24 hours.
    """
    url = f"https://www.amazon.com/gp/movers-and-shakers/{category.replace('-', '')}"
    movers = []

    try:
        response = session.get(url, timeout=15)
        if response.status_code != 200:
            log.warning(f"Movers returned {response.status_code} for {category}")
            return movers

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select("[data-asin]")

        for item in items[:20]:
            product = {"category": category}

            title_el = item.select_one(".p13n-sc-truncate, a span")
            if title_el:
                product["title"] = title_el.get_text(strip=True)

            if not product.get("title") or not is_physical_product(product["title"]):
                continue

            product["is_brand"] = is_major_brand(product["title"])

            change_el = item.select_one(".zg-percent-change, .a-color-success")
            if change_el:
                product["rank_change"] = change_el.get_text(strip=True)

            price_el = item.select_one(".p13n-sc-price, .a-price .a-offscreen")
            if price_el:
                product["price_raw"] = price_el.get_text(strip=True)
                product["price_eur"] = parse_price(product["price_raw"])
                product["price_usd"] = to_usd(product["price_eur"])

            asin = item.get("data-asin", "")
            if asin:
                product["asin"] = asin
                product["url"] = f"https://www.amazon.com/dp/{asin}"

            movers.append(product)

        log.info(f"Found {len(movers)} physical movers in {category}")

    except Exception as e:
        log.error(f"Movers failed for {category}: {e}")

    return movers


def add_bsr_history(products: dict, movers: dict, yesterday_map: dict):
    """Add BSR rank change info by comparing to yesterday's snapshot."""
    if not yesterday_map:
        return

    for cat, prod_list in products.items():
        for p in prod_list:
            asin = p.get("asin", "")
            if asin in yesterday_map:
                old = yesterday_map[asin]
                old_rank = old["rank"]
                new_rank = p["rank"]
                p["rank_yesterday"] = old_rank
                p["rank_change"] = old_rank - new_rank  # positive = improved
                if p["rank_change"] > 0:
                    p["rank_direction"] = "up"
                elif p["rank_change"] < 0:
                    p["rank_direction"] = "down"
                else:
                    p["rank_direction"] = "stable"
            else:
                p["rank_yesterday"] = None
                p["rank_direction"] = "new"  # New to the list


def run_amazon_scan():
    """Run full Amazon scan."""
    log.info("Starting Amazon scan...")
    session = get_session()

    # Load yesterday for BSR history
    yesterday = _load_yesterday()
    yesterday_map = _build_asin_rank_map(yesterday)
    if yesterday_map:
        log.info(f"Loaded {len(yesterday_map)} products from previous scan for BSR tracking")

    all_best_sellers = {}
    all_movers = {}
    digital_filtered = 0

    for category, url in AMAZON_CATEGORIES.items():
        log.info(f"Scanning: {category}")

        best = scrape_best_sellers(session, category, url)
        all_best_sellers[category] = best
        time.sleep(REQUEST_DELAY + random.uniform(1, 3))

        movers = scrape_movers_and_shakers(session, category)
        all_movers[category] = movers
        time.sleep(REQUEST_DELAY + random.uniform(1, 3))

    # Add BSR history
    add_bsr_history(all_best_sellers, all_movers, yesterday_map)

    # Count stats
    total_products = sum(len(v) for v in all_best_sellers.values())
    total_movers = sum(len(v) for v in all_movers.values())
    brand_count = sum(
        1 for prods in all_best_sellers.values()
        for p in prods if p.get("is_brand")
    )
    rising_count = sum(
        1 for prods in all_best_sellers.values()
        for p in prods if p.get("rank_direction") == "up"
    )

    report = {
        "scan_date": datetime.now().isoformat(),
        "best_sellers": all_best_sellers,
        "movers_and_shakers": all_movers,
        "total_products_scanned": total_products,
        "total_movers_found": total_movers,
        "brand_flagged": brand_count,
        "rising_products": rising_count,
        "digital_filtered": digital_filtered,
        "has_bsr_history": bool(yesterday_map),
    }

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"amazon_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Amazon report saved: {output_file}")
    log.info(
        f"Products: {total_products} | Movers: {total_movers} | "
        f"Brands: {brand_count} | Rising: {rising_count}"
    )

    # Telegram alert
    msg = f"AMAZON SCAN COMPLETE\n"
    msg += f"Physical products: {total_products}\n"
    msg += f"Movers: {total_movers}\n"
    msg += f"Major brands flagged: {brand_count}\n"
    if rising_count:
        msg += f"Rising in rank: {rising_count}\n"
    send_alert(msg)

    return report


if __name__ == "__main__":
    run_amazon_scan()

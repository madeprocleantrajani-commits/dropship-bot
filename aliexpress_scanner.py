"""
AliExpress Product Research Bot
---------------------------------
Searches AliExpress for products matching trending keywords.
Finds supplier options with pricing, order counts, and ratings.

This helps you:
  - Find the cheapest source for trending products
  - Compare suppliers (price, shipping, reviews)
  - Calculate potential profit margins

Outputs: data/aliexpress_YYYY-MM-DD.json
Run: daily or on-demand after trend scan
"""
import json
import time
import random
import re
from datetime import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, REQUEST_DELAY, HEADERS, get_logger, get_session
from alert_bot import send_alert

log = get_logger("aliexpress_scanner")


def search_aliexpress(keyword: str, max_pages: int = 2) -> list[dict]:
    """
    Search AliExpress for a product keyword.
    Returns list of products with price, orders, rating, etc.
    """
    products = []
    session = get_session(use_proxy=True)  # Use proxy if available

    for page in range(1, max_pages + 1):
        url = (
            f"https://www.aliexpress.com/wholesale"
            f"?SearchText={quote_plus(keyword)}"
            f"&page={page}"
            f"&SortType=total_tranpro_desc"  # Sort by orders
        )

        try:
            response = session.get(url, timeout=15)
            if response.status_code != 200:
                log.warning(f"AliExpress returned {response.status_code} for '{keyword}' page {page}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            # AliExpress product cards
            items = soup.select("[class*='product-card'], [class*='search-card']")

            if not items:
                # Try extracting from embedded JSON (AliExpress uses SSR)
                scripts = soup.find_all("script")
                for script in scripts:
                    text = script.string or ""
                    if "searchResult" in text or "itemList" in text:
                        # Try to extract product data from JavaScript
                        products.extend(_parse_json_products(text, keyword))
                        break

            for item in items:
                product = {"search_keyword": keyword}

                # Title
                title_el = item.select_one("h1, h3, [class*='title'] a, a[title]")
                if title_el:
                    product["title"] = title_el.get_text(strip=True) or title_el.get("title", "")

                # Price
                price_el = item.select_one("[class*='price'], .mGXnE")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    product["price_raw"] = price_text
                    # Extract numeric price
                    match = re.search(r"\$?([\d.]+)", price_text)
                    if match:
                        product["price_usd"] = float(match.group(1))

                # Orders / sold count
                sold_el = item.select_one("[class*='sold'], [class*='trade']")
                if sold_el:
                    product["orders"] = sold_el.get_text(strip=True)

                # Rating
                rating_el = item.select_one("[class*='rating'], [class*='star']")
                if rating_el:
                    product["rating"] = rating_el.get_text(strip=True)

                # Store name
                store_el = item.select_one("[class*='store'], [class*='seller']")
                if store_el:
                    product["store"] = store_el.get_text(strip=True)

                # Product URL
                link_el = item.select_one("a[href*='/item/']")
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("//"):
                        href = "https:" + href
                    product["url"] = href

                # Image URL
                img_el = item.select_one("img[src]")
                if img_el:
                    product["image"] = img_el.get("src", "")

                if product.get("title"):
                    products.append(product)

            log.info(f"Found {len(items)} items for '{keyword}' page {page}")

        except requests.RequestException as e:
            log.error(f"Request failed for '{keyword}' page {page}: {e}")
        except Exception as e:
            log.error(f"Parse error for '{keyword}': {e}")

        time.sleep(REQUEST_DELAY + random.uniform(1, 3))

    return products


def _parse_json_products(script_text: str, keyword: str) -> list[dict]:
    """Try to extract product data from AliExpress embedded JSON."""
    products = []
    try:
        # Look for product arrays in the script
        patterns = [
            r'"itemList"\s*:\s*(\[.+?\])',
            r'"items"\s*:\s*(\[.+?\])',
        ]
        for pattern in patterns:
            match = re.search(pattern, script_text, re.DOTALL)
            if match:
                items = json.loads(match.group(1))
                for item in items[:30]:
                    product = {
                        "search_keyword": keyword,
                        "title": item.get("title", ""),
                        "price_raw": item.get("price", ""),
                        "orders": str(item.get("trade", {}).get("tradeDesc", "")),
                        "rating": str(item.get("evaluation", {}).get("starRating", "")),
                        "url": item.get("productDetailUrl", ""),
                        "image": item.get("image", {}).get("imgUrl", ""),
                    }
                    # Extract numeric price
                    price_str = str(item.get("price", {}).get("minPrice", ""))
                    if price_str:
                        try:
                            product["price_usd"] = float(price_str)
                        except ValueError:
                            pass
                    if product["title"]:
                        products.append(product)
                break
    except (json.JSONDecodeError, KeyError):
        pass
    return products


def calculate_margins(products: list[dict], target_retail: float = None) -> list[dict]:
    """
    Calculate potential profit margins.
    Rule of thumb: retail price = 2.5x - 4x source price.
    """
    for product in products:
        source_price = product.get("price_usd")
        if source_price and source_price > 0:
            # Estimate retail prices at different markup levels
            product["margin_analysis"] = {
                "source_price": source_price,
                "retail_2.5x": round(source_price * 2.5, 2),
                "retail_3x": round(source_price * 3, 2),
                "retail_4x": round(source_price * 4, 2),
                "profit_at_3x": round(source_price * 3 - source_price, 2),
                "margin_pct_at_3x": "67%",
                "estimated_ad_cost": round(source_price * 0.8, 2),  # ~30% of retail
                "net_profit_at_3x": round(source_price * 3 - source_price - source_price * 0.8, 2),
            }
    return products


def scan_for_keywords(keywords: list[str]) -> dict:
    """Scan AliExpress for a list of keywords."""
    log.info(f"Scanning AliExpress for {len(keywords)} keywords...")
    all_results = {}

    for kw in keywords:
        log.info(f"Searching: {kw}")
        products = search_aliexpress(kw, max_pages=2)
        products = calculate_margins(products)

        # Sort by orders (most popular first)
        products.sort(
            key=lambda x: _parse_order_count(x.get("orders", "0")),
            reverse=True
        )

        all_results[kw] = products
        time.sleep(REQUEST_DELAY + random.uniform(2, 5))

    return all_results


def _parse_order_count(orders_str: str) -> int:
    """Parse order count strings like '1,234 sold' or '10K+ sold'."""
    try:
        cleaned = orders_str.lower().replace(",", "").replace("+", "")
        cleaned = re.sub(r"[^\d.k]", "", cleaned)
        if "k" in cleaned:
            return int(float(cleaned.replace("k", "")) * 1000)
        match = re.search(r"(\d+)", cleaned)
        return int(match.group(1)) if match else 0
    except (ValueError, AttributeError):
        return 0


def run_aliexpress_scan(keywords: list[str] = None):
    """
    Run AliExpress scan.
    If no keywords provided, reads hot products from latest trend scan.
    """
    if not keywords:
        # Try to load keywords from latest trend scan
        keywords = _load_trending_keywords()

    if not keywords:
        # Fall back to seed keywords from config
        from config import SEED_KEYWORDS
        log.info("No trending keywords — using seed keywords from config")
        keywords = []
        for niche_kws in SEED_KEYWORDS.values():
            keywords.extend(niche_kws[:2])  # Top 2 from each niche
        keywords = keywords[:12]  # Cap at 12

    if not keywords:
        log.warning("No keywords to scan.")
        return None

    results = scan_for_keywords(keywords)

    # Build report
    report = {
        "scan_date": datetime.now().isoformat(),
        "keywords_scanned": len(keywords),
        "total_products_found": sum(len(v) for v in results.values()),
        "results": {},
        "best_deals": [],
    }

    for kw, products in results.items():
        report["results"][kw] = products[:15]  # Top 15 per keyword

        # Find best deals (cheapest with high orders)
        for p in products[:5]:
            if p.get("price_usd") and p["price_usd"] < 15:
                report["best_deals"].append({
                    "keyword": kw,
                    "title": p.get("title", "")[:80],
                    "source_price": p.get("price_usd"),
                    "orders": p.get("orders", "N/A"),
                    "potential_retail": p.get("margin_analysis", {}).get("retail_3x", "N/A"),
                    "net_profit_est": p.get("margin_analysis", {}).get("net_profit_at_3x", "N/A"),
                })

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"aliexpress_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"AliExpress report saved: {output_file}")

    # Alert
    if report["best_deals"]:
        msg = "ALIEXPRESS SCAN COMPLETE\n"
        msg += f"Products found: {report['total_products_found']}\n\n"
        msg += "BEST DEALS (source < $15):\n"
        for deal in report["best_deals"][:5]:
            msg += (
                f"  - {deal['title'][:40]}...\n"
                f"    Source: ${deal['source_price']} | "
                f"Retail: ${deal['potential_retail']} | "
                f"Profit: ${deal['net_profit_est']}\n"
            )
        send_alert(msg)

    return report


def _load_trending_keywords() -> list[str]:
    """Load hot keywords from the latest trend scan."""
    import glob
    trend_files = sorted(glob.glob(str(DATA_DIR / "trends_*.json")), reverse=True)
    if not trend_files:
        return []

    try:
        with open(trend_files[0]) as f:
            data = json.load(f)

        keywords = []
        # Get hot products
        for hp in data.get("hot_products", []):
            keywords.append(hp["keyword"])
        # Get discoveries
        for d in data.get("discoveries", []):
            keywords.append(d["query"])

        return keywords[:15]  # Limit to 15
    except (json.JSONDecodeError, KeyError):
        return []


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Custom keywords from command line
        keywords = sys.argv[1:]
        run_aliexpress_scan(keywords)
    else:
        # Auto-load from trend scan
        run_aliexpress_scan()

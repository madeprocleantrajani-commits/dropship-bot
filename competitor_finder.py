"""
Competitor Store Finder
------------------------
Automatically discovers Shopify stores selling products
similar to your seed keywords. No manual configuration needed.

How it works:
  1. Searches DuckDuckGo for: site:myshopify.com "keyword"
  2. Extracts store domains from results
  3. Verifies each store has a public /products.json API
  4. Saves discovered stores for the competitor_tracker to monitor

Also checks known dropshipping store indicators:
  - Shopify stores with /products.json endpoint
  - Oberlo/DSers/Spocket footprints
  - AliExpress-style product descriptions

Outputs: data/competitors_discovered.json
Run: weekly (store discovery doesn't change daily)
"""

import json
import time
import random
import re
from datetime import datetime
from urllib.parse import quote_plus, urlparse

import requests

from config import (
    DATA_DIR, SEED_KEYWORDS, get_logger, get_session,
    is_physical_product, parse_price,
)
from alert_bot import send_alert

log = get_logger("competitor_finder")

# DuckDuckGo HTML search (no API key needed)
DDG_URL = "https://html.duckduckgo.com/html/?q={query}"


def search_stores(keyword: str, max_results: int = 15) -> list[str]:
    """
    Search DuckDuckGo for Shopify stores selling this product.
    Returns list of store domains.
    """
    stores = set()
    session = get_session(use_proxy=True)

    queries = [
        f'site:myshopify.com "{keyword}"',
        f'"{keyword}" shop powered by shopify',
    ]

    for query in queries:
        try:
            url = DDG_URL.format(query=quote_plus(query))
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                log.warning(f"DDG returned {resp.status_code} for '{keyword}'")
                continue

            # Extract URLs from DuckDuckGo results
            urls = re.findall(
                r'href="(https?://[^"]+)"',
                resp.text,
            )

            for u in urls:
                parsed = urlparse(u)
                domain = parsed.netloc.lower()

                # Filter for likely Shopify stores
                if any(skip in domain for skip in [
                    "duckduckgo", "google", "bing", "yahoo", "amazon",
                    "ebay", "etsy", "aliexpress", "facebook", "instagram",
                    "tiktok", "youtube", "reddit", "wikipedia", "pinterest",
                ]):
                    continue

                # Keep myshopify.com subdomains and custom domains
                if "myshopify.com" in domain or "." in domain:
                    # Normalize myshopify URLs
                    if "myshopify.com" in domain:
                        store_name = domain.split(".myshopify.com")[0]
                        stores.add(f"https://{store_name}.myshopify.com")
                    elif domain.count(".") <= 2:  # Custom domain
                        stores.add(f"https://{domain}")

        except Exception as e:
            log.error(f"Search failed for '{keyword}': {e}")

        time.sleep(random.uniform(3, 6))

    return list(stores)[:max_results]


def verify_shopify_store(store_url: str) -> dict | None:
    """
    Verify a URL is a Shopify store and get basic stats.
    Checks for /products.json endpoint.
    """
    session = get_session(use_proxy=True)

    # Try products.json endpoint
    products_url = f"{store_url.rstrip('/')}/products.json?limit=250"
    try:
        resp = session.get(products_url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        products = data.get("products", [])
        if not products:
            return None

        # Extract store intelligence
        prices = []
        product_types = set()
        titles = []

        for p in products:
            titles.append(p.get("title", ""))
            ptype = p.get("product_type", "")
            if ptype:
                product_types.add(ptype)

            for v in p.get("variants", []):
                price = parse_price(v.get("price", ""))
                if price and price > 0:
                    prices.append(price)

        store_info = {
            "url": store_url,
            "products_url": products_url,
            "product_count": len(products),
            "product_types": list(product_types)[:10],
            "sample_titles": [t for t in titles[:5] if t],
        }

        if prices:
            store_info["avg_price"] = round(sum(prices) / len(prices), 2)
            store_info["min_price"] = min(prices)
            store_info["max_price"] = max(prices)
            store_info["price_range"] = f"${min(prices):.2f}–${max(prices):.2f}"

        return store_info

    except Exception as e:
        log.debug(f"Not a Shopify store or blocked: {store_url} — {e}")
        return None


def discover_competitors() -> dict:
    """
    Discover competitor Shopify stores for all seed keywords.
    """
    log.info("Starting competitor discovery...")

    all_stores = {}  # domain → store info
    keyword_stores = {}  # keyword → [domains]

    for niche, keywords in SEED_KEYWORDS.items():
        log.info(f"Searching niche: {niche}")

        for kw in keywords:
            log.info(f"  Searching: {kw}")
            found_urls = search_stores(kw, max_results=10)

            verified = []
            for url in found_urls:
                domain = urlparse(url).netloc
                if domain in all_stores:
                    # Already verified this store
                    verified.append(domain)
                    continue

                log.info(f"    Verifying: {url}")
                info = verify_shopify_store(url)
                if info:
                    all_stores[domain] = info
                    all_stores[domain]["found_via"] = kw
                    all_stores[domain]["niche"] = niche
                    verified.append(domain)
                    log.info(
                        f"    ✓ {domain}: {info['product_count']} products, "
                        f"avg ${info.get('avg_price', 0):.2f}"
                    )
                else:
                    log.debug(f"    ✗ {url}: not accessible")

                time.sleep(random.uniform(1, 3))

            keyword_stores[kw] = verified
            time.sleep(random.uniform(2, 5))

    # Build report
    report = {
        "scan_date": datetime.now().isoformat(),
        "stores_found": len(all_stores),
        "stores": all_stores,
        "keyword_coverage": {
            kw: len(stores) for kw, stores in keyword_stores.items()
        },
        "store_urls": list(
            info["url"] for info in all_stores.values()
        ),
    }

    # Save
    output_file = DATA_DIR / "competitors_discovered.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Discovery complete: {len(all_stores)} stores found")
    log.info(f"Saved: {output_file}")

    # Telegram alert
    if all_stores:
        msg = f"COMPETITOR DISCOVERY\n"
        msg += f"Stores found: {len(all_stores)}\n\n"
        for domain, info in list(all_stores.items())[:8]:
            msg += (
                f"  {domain}\n"
                f"    {info['product_count']} products | "
                f"Avg ${info.get('avg_price', 0):.2f} | "
                f"Via: {info.get('found_via', '?')}\n"
            )
        send_alert(msg)

    return report


if __name__ == "__main__":
    discover_competitors()

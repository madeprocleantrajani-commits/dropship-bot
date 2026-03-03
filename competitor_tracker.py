"""
Competitor Store Tracker
-------------------------
Monitors competitor Shopify/e-commerce stores for:
  - New products added
  - Price changes
  - Best sellers (by collection/tag)

Most Shopify stores expose their product catalog via:
  /products.json (public API)
  /collections/all/products.json

This is 100% legal — it's a public API endpoint.

Outputs: data/competitors_YYYY-MM-DD.json
Run: daily via cron
"""
import json
import time
import random
from datetime import datetime
from urllib.parse import urlparse

import requests

from config import COMPETITOR_STORES, DATA_DIR, REQUEST_DELAY, HEADERS, get_logger
from alert_bot import send_alert

log = get_logger("competitor_tracker")

# Persistent competitor data
COMPETITOR_DATA_FILE = DATA_DIR / "competitor_history.json"


def load_competitor_history() -> dict:
    if COMPETITOR_DATA_FILE.exists():
        try:
            with open(COMPETITOR_DATA_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_competitor_history(data: dict):
    with open(COMPETITOR_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def fetch_shopify_products(store_url: str) -> list[dict]:
    """
    Fetch all products from a Shopify store using the public products.json API.
    Works on most Shopify stores.
    """
    products = []
    base_url = store_url.rstrip("/")
    page = 1

    session = requests.Session()
    session.headers.update(HEADERS)

    while True:
        url = f"{base_url}/products.json?limit=250&page={page}"

        try:
            response = session.get(url, timeout=15)

            if response.status_code == 404:
                # Try alternative endpoint
                url = f"{base_url}/collections/all/products.json?limit=250&page={page}"
                response = session.get(url, timeout=15)

            if response.status_code != 200:
                log.warning(f"Store {base_url} returned {response.status_code}")
                break

            data = response.json()
            page_products = data.get("products", [])

            if not page_products:
                break

            for p in page_products:
                product = {
                    "id": p.get("id"),
                    "title": p.get("title", ""),
                    "handle": p.get("handle", ""),
                    "vendor": p.get("vendor", ""),
                    "product_type": p.get("product_type", ""),
                    "tags": p.get("tags", []),
                    "created_at": p.get("created_at", ""),
                    "updated_at": p.get("updated_at", ""),
                    "url": f"{base_url}/products/{p.get('handle', '')}",
                    "variants": [],
                    "images": [],
                }

                # Get pricing from variants
                for v in p.get("variants", []):
                    product["variants"].append({
                        "title": v.get("title", ""),
                        "price": v.get("price", ""),
                        "compare_at_price": v.get("compare_at_price"),
                        "available": v.get("available", True),
                        "sku": v.get("sku", ""),
                    })

                # Get first image
                images = p.get("images", [])
                if images:
                    product["images"] = [img.get("src", "") for img in images[:3]]

                # Main price (first variant)
                if product["variants"]:
                    try:
                        product["price"] = float(product["variants"][0]["price"])
                    except (ValueError, TypeError):
                        product["price"] = None

                products.append(product)

            page += 1
            time.sleep(REQUEST_DELAY)

        except requests.RequestException as e:
            log.error(f"Failed to fetch {url}: {e}")
            break
        except json.JSONDecodeError:
            log.warning(f"Invalid JSON from {url} — store may not be Shopify")
            break

    log.info(f"Found {len(products)} products from {base_url}")
    return products


def analyze_store_changes(store_url: str, current_products: list[dict], history: dict) -> dict:
    """Compare current products with previous scan to find changes."""
    store_key = urlparse(store_url).netloc
    changes = {
        "new_products": [],
        "removed_products": [],
        "price_changes": [],
    }

    prev_data = history.get(store_key, {})
    prev_products = {p["id"]: p for p in prev_data.get("products", [])}
    curr_products = {p["id"]: p for p in current_products}

    # New products
    for pid, product in curr_products.items():
        if pid not in prev_products:
            changes["new_products"].append({
                "title": product["title"],
                "price": product.get("price"),
                "url": product["url"],
                "type": product["product_type"],
            })

    # Removed products
    for pid, product in prev_products.items():
        if pid not in curr_products:
            changes["removed_products"].append({
                "title": product["title"],
                "price": product.get("price"),
            })

    # Price changes
    for pid, product in curr_products.items():
        if pid in prev_products:
            old_price = prev_products[pid].get("price")
            new_price = product.get("price")
            if old_price and new_price and old_price != new_price:
                changes["price_changes"].append({
                    "title": product["title"],
                    "old_price": old_price,
                    "new_price": new_price,
                    "change_pct": round(((new_price - old_price) / old_price) * 100, 1),
                    "url": product["url"],
                })

    return changes


def get_store_stats(products: list[dict]) -> dict:
    """Calculate store statistics."""
    prices = [p["price"] for p in products if p.get("price")]
    types = {}
    for p in products:
        t = p.get("product_type", "unknown")
        types[t] = types.get(t, 0) + 1

    return {
        "total_products": len(products),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
        "min_price": min(prices) if prices else 0,
        "max_price": max(prices) if prices else 0,
        "price_range": f"${min(prices):.2f} - ${max(prices):.2f}" if prices else "N/A",
        "product_types": dict(sorted(types.items(), key=lambda x: x[1], reverse=True)),
    }


def run_competitor_scan():
    """Scan all competitor stores."""
    if not COMPETITOR_STORES:
        log.info("No competitor stores configured. Add URLs to COMPETITOR_STORES in config.py")
        return

    log.info(f"Scanning {len(COMPETITOR_STORES)} competitor stores...")
    history = load_competitor_history()
    all_changes = {}
    report = {
        "scan_date": datetime.now().isoformat(),
        "stores": {},
    }

    for store_url in COMPETITOR_STORES:
        store_key = urlparse(store_url).netloc
        log.info(f"Scanning: {store_key}")

        products = fetch_shopify_products(store_url)

        if not products:
            log.warning(f"No products found for {store_key}")
            continue

        # Analyze changes
        changes = analyze_store_changes(store_url, products, history)
        stats = get_store_stats(products)

        report["stores"][store_key] = {
            "url": store_url,
            "stats": stats,
            "changes": changes,
            "top_products": sorted(
                products, key=lambda x: x.get("price", 0) or 0, reverse=True
            )[:10],
        }

        if any(changes.values()):
            all_changes[store_key] = changes

        # Update history
        history[store_key] = {
            "last_scan": datetime.now().isoformat(),
            "products": products,
        }

        time.sleep(REQUEST_DELAY + random.uniform(1, 3))

    # Save history
    save_competitor_history(history)

    # Save daily report
    today = datetime.now().strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"competitors_{today}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Competitor report saved: {output_file}")

    # Alert on changes
    if all_changes:
        msg = "COMPETITOR TRACKER ALERTS\n\n"
        for store, changes in all_changes.items():
            msg += f"--- {store} ---\n"
            if changes["new_products"]:
                msg += f"  {len(changes['new_products'])} NEW products:\n"
                for p in changes["new_products"][:3]:
                    msg += f"    + {p['title'][:40]} (${p.get('price', 'N/A')})\n"
            if changes["removed_products"]:
                msg += f"  {len(changes['removed_products'])} REMOVED products\n"
            if changes["price_changes"]:
                msg += f"  {len(changes['price_changes'])} price changes:\n"
                for p in changes["price_changes"][:3]:
                    msg += f"    {p['title'][:30]}: ${p['old_price']} -> ${p['new_price']} ({p['change_pct']:+.1f}%)\n"
            msg += "\n"

        send_alert(msg)

    return report


if __name__ == "__main__":
    run_competitor_scan()

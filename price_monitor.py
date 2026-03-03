"""
Price Monitor Bot
------------------
Tracks prices of products you're actively selling/considering.
Alerts you when:
  - A supplier drops their price (better margins!)
  - A competitor changes their price
  - Price crosses your target threshold

Also tracks price history over time so you can spot patterns.

Outputs: data/prices_YYYY-MM-DD.json
Run: every 4-6 hours via cron
"""
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    TRACKED_PRODUCTS, DATA_DIR, HEADERS,
    REQUEST_DELAY, get_logger
)
from alert_bot import send_alert

log = get_logger("price_monitor")

# Price history file (persistent)
PRICE_HISTORY_FILE = DATA_DIR / "price_history.json"


def load_price_history() -> dict:
    """Load existing price history."""
    if PRICE_HISTORY_FILE.exists():
        try:
            with open(PRICE_HISTORY_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_price_history(history: dict):
    """Save updated price history."""
    with open(PRICE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def extract_price(url: str) -> dict:
    """
    Extract price from a product page.
    Supports: AliExpress, Amazon, generic e-commerce.
    """
    result = {"url": url, "timestamp": datetime.now().isoformat()}

    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        response = session.get(url, timeout=15)

        if response.status_code != 200:
            result["error"] = f"HTTP {response.status_code}"
            return result

        soup = BeautifulSoup(response.text, "html.parser")

        # Strategy 1: Look for common price selectors
        price_selectors = [
            # AliExpress
            "[class*='product-price'] .price--current",
            "[class*='uniform-banner-box'] .es--wrap",
            # Amazon
            ".a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            # Generic
            "[class*='price'] [class*='current']",
            "[itemprop='price']",
            ".price",
            "[data-price]",
        ]

        for selector in price_selectors:
            el = soup.select_one(selector)
            if el:
                price_text = el.get_text(strip=True) or el.get("content", "")
                price_val = _parse_price(price_text)
                if price_val:
                    result["price"] = price_val
                    result["price_raw"] = price_text
                    break

        # Strategy 2: Look for price in meta tags
        if "price" not in result:
            meta_price = soup.find("meta", {"property": "product:price:amount"})
            if meta_price:
                price_val = _parse_price(meta_price.get("content", ""))
                if price_val:
                    result["price"] = price_val

        # Strategy 3: Regex scan for price patterns in page
        if "price" not in result:
            text = soup.get_text()
            matches = re.findall(r"\$(\d+\.?\d*)", text)
            if matches:
                prices = [float(m) for m in matches if 0.5 < float(m) < 500]
                if prices:
                    result["price"] = min(prices)
                    result["price_note"] = "extracted via regex (verify manually)"

        # Get product title
        title_el = soup.find("title")
        if title_el:
            result["page_title"] = title_el.get_text(strip=True)[:100]

    except requests.RequestException as e:
        result["error"] = str(e)
        log.error(f"Request failed for {url}: {e}")
    except Exception as e:
        result["error"] = str(e)
        log.error(f"Parse error for {url}: {e}")

    return result


def _parse_price(text: str) -> float | None:
    """Parse a price string into a float."""
    try:
        cleaned = text.replace(",", "").replace(" ", "")
        match = re.search(r"[\$]?([\d]+\.?\d*)", cleaned)
        if match:
            val = float(match.group(1))
            if 0.01 < val < 10000:
                return val
    except (ValueError, AttributeError):
        pass
    return None


def check_prices():
    """Check prices for all tracked products."""
    if not TRACKED_PRODUCTS:
        log.info("No products being tracked. Add products to TRACKED_PRODUCTS in config.py")
        return

    log.info(f"Checking prices for {len(TRACKED_PRODUCTS)} products...")
    history = load_price_history()
    alerts = []

    for product in TRACKED_PRODUCTS:
        name = product["name"]
        url = product["url"]
        target = product.get("target_price")

        log.info(f"Checking: {name}")
        result = extract_price(url)

        if "error" in result:
            log.warning(f"Failed to get price for {name}: {result['error']}")
            continue

        current_price = result.get("price")
        if not current_price:
            log.warning(f"Could not extract price for {name}")
            continue

        # Initialize history for this product
        if name not in history:
            history[name] = {
                "url": url,
                "target_price": target,
                "price_log": [],
                "lowest_price": current_price,
                "highest_price": current_price,
            }

        h = history[name]
        prev_price = h["price_log"][-1]["price"] if h["price_log"] else None

        # Log the price
        h["price_log"].append({
            "price": current_price,
            "timestamp": datetime.now().isoformat(),
        })

        # Keep only last 90 days of data
        h["price_log"] = h["price_log"][-540:]  # ~6 checks/day * 90 days

        # Update bounds
        h["lowest_price"] = min(h["lowest_price"], current_price)
        h["highest_price"] = max(h["highest_price"], current_price)

        # Check for alerts
        if prev_price:
            change_pct = ((current_price - prev_price) / prev_price) * 100

            if change_pct <= -5:
                alerts.append(
                    f"PRICE DROP: {name}\n"
                    f"  Was: ${prev_price:.2f} → Now: ${current_price:.2f} ({change_pct:.1f}%)"
                )

            elif change_pct >= 10:
                alerts.append(
                    f"PRICE INCREASE: {name}\n"
                    f"  Was: ${prev_price:.2f} → Now: ${current_price:.2f} (+{change_pct:.1f}%)"
                )

        if target and current_price <= target:
            alerts.append(
                f"TARGET HIT: {name}\n"
                f"  Price: ${current_price:.2f} (target was ${target:.2f})"
            )

        if current_price == h["lowest_price"] and len(h["price_log"]) > 1:
            alerts.append(f"ALL-TIME LOW: {name} at ${current_price:.2f}")

        time.sleep(REQUEST_DELAY + random.uniform(1, 2))

    # Save updated history
    save_price_history(history)
    log.info("Price history updated")

    # Send alerts
    if alerts:
        msg = "PRICE MONITOR ALERTS\n\n" + "\n\n".join(alerts)
        send_alert(msg)
        log.info(f"Sent {len(alerts)} price alerts")

    # Save daily snapshot
    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = {
        "scan_date": datetime.now().isoformat(),
        "products_checked": len(TRACKED_PRODUCTS),
        "alerts": alerts,
        "current_prices": {
            p["name"]: {
                "price": history.get(p["name"], {}).get("price_log", [{}])[-1].get("price"),
                "lowest_ever": history.get(p["name"], {}).get("lowest_price"),
                "highest_ever": history.get(p["name"], {}).get("highest_price"),
            }
            for p in TRACKED_PRODUCTS
            if p["name"] in history
        },
    }

    output_file = DATA_DIR / f"prices_{today}.json"
    with open(output_file, "w") as f:
        json.dump(snapshot, f, indent=2)

    return snapshot


if __name__ == "__main__":
    check_prices()

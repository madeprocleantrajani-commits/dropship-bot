"""
Central configuration for all dropship bots.
Loads settings from .env file and provides shared utilities.
"""
import os
import re
import logging
from pathlib import Path
from dotenv import load_dotenv

import requests

# Load environment variables
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# === Directories ===
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"

for d in [DATA_DIR, LOGS_DIR, REPORTS_DIR]:
    d.mkdir(exist_ok=True)

# === Telegram Alerts ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === Proxy ===
# Set PROXY_URL in .env to route all scraping through a residential proxy.
# Supports HTTP/HTTPS/SOCKS5. Examples:
#   PROXY_URL=http://user:pass@proxy.example.com:8080
#   PROXY_URL=socks5://user:pass@proxy.example.com:1080
# Leave empty to connect directly (works for Amazon, fails for Trends/AliExpress).
PROXY_URL = os.getenv("PROXY_URL", "")

# === Currency ===
# VPS is in Ireland so Amazon returns EUR prices.
# We convert to USD for margin calculations.
EUR_TO_USD = float(os.getenv("EUR_TO_USD", "1.08"))

# === Google Trends ===
TRENDS_GEO = "US"
TRENDS_TIMEFRAME = "today 3-m"  # Last 3 months

# === Seed Keywords ===
# Physical products only — no digital, no subscriptions.
SEED_KEYWORDS = {
    "home_gadgets": [
        "portable blender", "led strip lights", "smart plug",
        "air purifier", "electric lighter",
    ],
    "fitness": [
        "posture corrector", "massage gun", "resistance bands",
        "ab roller", "yoga mat",
    ],
    "pet_products": [
        "dog camera", "cat water fountain", "pet grooming glove",
        "dog car seat cover", "automatic pet feeder",
    ],
    "tech_accessories": [
        "car phone mount", "wireless charger", "laptop stand",
        "ring light", "bluetooth tracker",
    ],
    "beauty_health": [
        "jade roller", "teeth whitening kit", "hair growth serum",
        "blackhead remover", "essential oil diffuser",
    ],
    "outdoor": [
        "camping hammock", "solar power bank", "insulated water bottle",
        "tactical flashlight", "portable fan",
    ],
}

# === Physical Product Filter ===
# Products matching these patterns are DIGITAL / NON-SHIPPABLE and get excluded.
DIGITAL_KEYWORDS = [
    "subscription", "auto-renewal", "renewal", "monthly plan",
    "yearly plan", "annual plan", "digital download", "ebook",
    "e-book", "kindle edition", "gift card", "egift", "e-gift",
    "streaming", "membership", "warranty", "protection plan",
    "extended warranty", "service plan", "cloud storage",
    "software license", "app subscription", "prime membership",
    "audible", "kindle unlimited",
    # Specific Amazon digital products
    "blink plus plan", "blink basic", "ring protect",
    "alexa together", "amazon music", "luna controller",
    "fire tv plan",
]

# === Brand Filter ===
# Major brands you CANNOT dropship (brand-gated or impossible to source cheap).
# Products from these brands get flagged, not removed — useful market intel.
MAJOR_BRANDS = [
    "apple", "samsung", "sony", "nike", "adidas", "bose",
    "dyson", "nintendo", "microsoft", "google", "amazon basics",
    "anker", "logitech", "jbl", "beats", "philips", "kitchenaid",
    "instant pot", "ninja", "keurig", "roomba", "irobot",
    "garmin", "fitbit", "gopro", "canon", "dell", "hp ",
    "lenovo", "lg ", "whirlpool", "cuisinart",
]

# === Amazon Tracking ===
AMAZON_CATEGORIES = {
    "electronics": "https://www.amazon.com/Best-Sellers-Electronics/zgbs/electronics/",
    "home-kitchen": "https://www.amazon.com/Best-Sellers-Home-Kitchen/zgbs/home-garden/",
    "sports": "https://www.amazon.com/Best-Sellers-Sports-Outdoors/zgbs/sporting-goods/",
    "beauty": "https://www.amazon.com/Best-Sellers-Beauty/zgbs/beauty/",
    "pet-supplies": "https://www.amazon.com/Best-Sellers-Pet-Supplies/zgbs/pet-supplies/",
    "tools": "https://www.amazon.com/Best-Sellers-Tools/zgbs/hi/",
}

# === AliExpress ===
ALIEXPRESS_SEARCH_URL = "https://www.aliexpress.com/wholesale"

# === Price Monitor ===
TRACKED_PRODUCTS = [
    # {"name": "Product Name", "url": "https://...", "target_price": 5.99}
]

# === Competitor Tracking ===
# Auto-discovered by competitor_finder.py — no manual config needed.
COMPETITOR_STORES = [
    # "https://competitor-store.com",
]

# === Scraping Settings ===
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 2  # seconds between requests (be polite)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

import random


def get_session(use_proxy: bool = True) -> requests.Session:
    """
    Create a requests session with:
      - Random user agent rotation
      - US locale headers
      - Proxy (if configured)
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    if use_proxy and PROXY_URL:
        session.proxies = {
            "http": PROXY_URL,
            "https": PROXY_URL,
        }
    return session


def is_physical_product(title: str) -> bool:
    """Return True if the product appears to be a physical, shippable item."""
    title_lower = title.lower()
    for kw in DIGITAL_KEYWORDS:
        if kw in title_lower:
            return False
    return True


def is_major_brand(title: str) -> bool:
    """Return True if the product is from a major brand (hard to dropship)."""
    title_lower = title.lower()
    for brand in MAJOR_BRANDS:
        if brand in title_lower:
            return True
    return False


def parse_price(price_str: str) -> float | None:
    """Parse price from any format: '$29.99', 'EUR 10.15', etc."""
    if not price_str:
        return None
    try:
        cleaned = re.sub(r"[€$£¥]|EUR|USD|GBP|\xa0", "", str(price_str)).strip()
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        match = re.search(r"[\d.]+", cleaned)
        if match:
            return round(float(match.group()), 2)
    except (ValueError, AttributeError):
        pass
    return None


def to_usd(eur_price: float | None) -> float | None:
    """Convert EUR price to USD."""
    if eur_price is None:
        return None
    return round(eur_price * EUR_TO_USD, 2)


# === Logging ===


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(LOGS_DIR / f"{name}.log")
    fh.setLevel(logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger

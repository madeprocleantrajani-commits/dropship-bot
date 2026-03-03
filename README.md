# Dropship Intelligence Bot Suite

Automated product research and market intelligence for dropshipping.

## What's Included

| Bot | What It Does | Schedule |
|-----|-------------|----------|
| `trend_scanner.py` | Scans Google Trends for rising products + breakout queries | Daily 6 AM |
| `amazon_tracker.py` | Tracks Amazon Best Sellers + Movers & Shakers | Daily 7 AM |
| `aliexpress_scanner.py` | Finds suppliers + calculates profit margins | Daily 8 AM |
| `price_monitor.py` | Tracks prices for products you're selling | Every 6 hrs |
| `competitor_tracker.py` | Monitors competitor Shopify stores for changes | Daily 9 AM |
| `report_generator.py` | Combines everything into a daily intelligence report | Daily 6 PM |
| `alert_bot.py` | Sends Telegram alerts when bots find opportunities | Real-time |

## Quick Start

### 1. Deploy to VPS

```bash
# From your Mac:
cd ~/Desktop/dropship-bots
bash deploy.sh user@YOUR_VPS_IP
```

### 2. Configure Telegram Alerts

```bash
# SSH into your VPS:
ssh user@YOUR_VPS_IP
nano ~/dropship-bots/.env
```

Add your Telegram bot token and chat ID (instructions in .env.example).

### 3. Test Run

```bash
cd ~/dropship-bots

# Test one bot:
venv/bin/python trend_scanner.py

# Run everything:
venv/bin/python run_all.py

# Run specific bots:
venv/bin/python run_all.py trends amazon
```

### 4. Set Up Automation

```bash
bash ~/dropship-bots/setup_cron.sh ~/dropship-bots
```

This adds cron jobs WITHOUT touching your existing cron entries.

## File Structure

```
dropship-bots/
├── config.py              # Central config (keywords, categories, settings)
├── alert_bot.py           # Telegram notifications
├── trend_scanner.py       # Google Trends research
├── amazon_tracker.py      # Amazon Best Sellers
├── aliexpress_scanner.py  # Supplier research
├── price_monitor.py       # Price tracking
├── competitor_tracker.py  # Competitor monitoring
├── report_generator.py    # Daily summary
├── run_all.py             # Master runner
├── deploy.sh              # VPS deployment script
├── setup_cron.sh          # Cron job installer
├── requirements.txt       # Python dependencies
├── .env                   # Your API keys (not committed)
├── data/                  # Bot output (JSON files)
├── logs/                  # Bot logs
└── reports/               # Daily reports
```

## Configuration

Edit `config.py` to customize:

- **SEED_KEYWORDS** — Product niches to scan (add your own)
- **AMAZON_CATEGORIES** — Which Amazon categories to track
- **TRACKED_PRODUCTS** — Products you're actively monitoring prices for
- **COMPETITOR_STORES** — Shopify store URLs to track

## Commands

```bash
# Run specific bot
venv/bin/python trend_scanner.py
venv/bin/python amazon_tracker.py
venv/bin/python aliexpress_scanner.py
venv/bin/python price_monitor.py
venv/bin/python competitor_tracker.py
venv/bin/python report_generator.py

# Run all bots in sequence
venv/bin/python run_all.py

# Run specific bots
venv/bin/python run_all.py trends amazon report

# AliExpress search with custom keywords
venv/bin/python aliexpress_scanner.py "portable blender" "led mirror"

# Test Telegram alerts
venv/bin/python alert_bot.py

# Check logs
tail -f logs/trend_scanner.log
tail -f logs/runner.log
```

## Adding Products to Track

Edit `config.py`:

```python
TRACKED_PRODUCTS = [
    {"name": "Portable Blender", "url": "https://aliexpress.com/item/...", "target_price": 5.99},
    {"name": "LED Strip Lights", "url": "https://aliexpress.com/item/...", "target_price": 3.50},
]
```

## Adding Competitor Stores

Edit `config.py`:

```python
COMPETITOR_STORES = [
    "https://competitor-store.myshopify.com",
    "https://another-store.com",
]
```

## Removing Cron Jobs

```bash
crontab -l | sed '/DROPSHIP BOTS/,/DROPSHIP BOTS END/d' | crontab -
```

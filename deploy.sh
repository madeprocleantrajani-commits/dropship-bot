#!/bin/bash
# ============================================
# Deploy Dropship Bots to VPS
# ============================================
# Run this FROM YOUR LOCAL MACHINE (Mac) to deploy to your VPS.
#
# Usage: bash deploy.sh user@your-vps-ip
# Example: bash deploy.sh root@192.168.1.100
#
# What it does:
#   1. Uploads all bot files to ~/dropship-bots/ on your VPS
#   2. Creates a Python virtual environment
#   3. Installs dependencies
#   4. Does NOT touch any existing files/bots on the VPS

VPS="${1}"
REMOTE_DIR="dropship-bots"

if [ -z "${VPS}" ]; then
    echo "Usage: bash deploy.sh user@your-vps-ip"
    echo "Example: bash deploy.sh root@192.168.1.100"
    exit 1
fi

echo "Deploying to ${VPS}:~/${REMOTE_DIR}/"
echo ""

# Upload files
echo "1/4 — Uploading bot files..."
scp -r \
    config.py \
    alert_bot.py \
    trend_scanner.py \
    amazon_tracker.py \
    amazon_demand.py \
    aliexpress_scanner.py \
    ebay_scanner.py \
    price_monitor.py \
    competitor_tracker.py \
    competitor_finder.py \
    intelligence.py \
    monitor.py \
    report_generator.py \
    run_all.py \
    requirements.txt \
    setup_cron.sh \
    dropship-bot.service \
    .env.example \
    "${VPS}:~/${REMOTE_DIR}/" 2>/dev/null

# If the directory didn't exist, create it and retry
if [ $? -ne 0 ]; then
    echo "Creating remote directory..."
    ssh "${VPS}" "mkdir -p ~/${REMOTE_DIR}/{data,logs,reports}"
    scp -r \
        config.py \
        alert_bot.py \
        trend_scanner.py \
        amazon_tracker.py \
        amazon_demand.py \
        aliexpress_scanner.py \
        ebay_scanner.py \
        price_monitor.py \
        competitor_tracker.py \
        competitor_finder.py \
        intelligence.py \
        monitor.py \
        report_generator.py \
        run_all.py \
        requirements.txt \
        setup_cron.sh \
        dropship-bot.service \
        .env.example \
        "${VPS}:~/${REMOTE_DIR}/"
fi

# Set up virtual environment and install deps
echo "2/4 — Setting up Python environment..."
ssh "${VPS}" << 'REMOTE_SCRIPT'
cd ~/dropship-bots
mkdir -p data logs reports

# Create venv if not exists
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created"
fi

# Install dependencies
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
echo "Dependencies installed"

# Create .env from example if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env with your Telegram bot token:"
    echo "  nano ~/dropship-bots/.env"
fi
REMOTE_SCRIPT

echo ""
echo "3/4 — Verifying installation..."
ssh "${VPS}" "cd ~/dropship-bots && venv/bin/python -c 'import pytrends, requests, bs4; print(\"All dependencies OK\")'"

echo ""
echo "============================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================"
echo ""
echo "Next steps (SSH into your VPS):"
echo ""
echo "  ssh ${VPS}"
echo ""
echo "  # 1. Configure Telegram alerts:"
echo "  nano ~/dropship-bots/.env"
echo ""
echo "  # 2. Test a single bot:"
echo "  cd ~/dropship-bots && venv/bin/python trend_scanner.py"
echo ""
echo "  # 3. Run everything:"
echo "  cd ~/dropship-bots && venv/bin/python run_all.py"
echo ""
echo "  # 4. Set up automated scheduling:"
echo "  bash ~/dropship-bots/setup_cron.sh ~/dropship-bots"
echo ""
echo "  # 5. Check logs:"
echo "  tail -f ~/dropship-bots/logs/trend_scanner.log"
echo ""
echo "  # Optional — run as a systemd service (auto-restart on crash/reboot):"
echo "  sudo cp ~/dropship-bots/dropship-bot.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable dropship-bot"
echo "  sudo systemctl start dropship-bot"
echo "  sudo systemctl status dropship-bot"
echo ""

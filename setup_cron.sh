#!/bin/bash
# ============================================
# Cron Setup Script for Dropship Bots
# ============================================
# Run this ONCE on your VPS to set up automated scheduling.
# It adds cron jobs WITHOUT touching your existing cron entries.
#
# Usage: bash setup_cron.sh /path/to/dropship-bots
# Example: bash setup_cron.sh /home/user/dropship-bots

BOT_DIR="${1:-$(pwd)}"
PYTHON="${BOT_DIR}/venv/bin/python"
LOG_DIR="${BOT_DIR}/logs"

# Verify setup
if [ ! -f "${BOT_DIR}/run_all.py" ]; then
    echo "ERROR: run_all.py not found in ${BOT_DIR}"
    echo "Usage: bash setup_cron.sh /path/to/dropship-bots"
    exit 1
fi

if [ ! -f "${PYTHON}" ]; then
    echo "ERROR: Virtual environment not found at ${BOT_DIR}/venv"
    echo "Run: python3 -m venv ${BOT_DIR}/venv && ${BOT_DIR}/venv/bin/pip install -r ${BOT_DIR}/requirements.txt"
    exit 1
fi

echo "Setting up cron jobs for: ${BOT_DIR}"
echo "Python: ${PYTHON}"
echo ""

# Build new cron entries
CRON_MARKER="# === DROPSHIP BOTS ==="
CRON_ENTRIES="${CRON_MARKER}
# Trend Scanner — Daily at 6:00 AM UTC
0 6 * * * cd ${BOT_DIR} && ${PYTHON} trend_scanner.py >> ${LOG_DIR}/cron_trends.log 2>&1

# Amazon Tracker — Daily at 7:00 AM UTC
0 7 * * * cd ${BOT_DIR} && ${PYTHON} amazon_tracker.py >> ${LOG_DIR}/cron_amazon.log 2>&1

# AliExpress Scanner — Daily at 8:00 AM UTC (after trends, uses trending keywords)
0 8 * * * cd ${BOT_DIR} && ${PYTHON} aliexpress_scanner.py >> ${LOG_DIR}/cron_aliexpress.log 2>&1

# Price Monitor — Every 6 hours
0 */6 * * * cd ${BOT_DIR} && ${PYTHON} price_monitor.py >> ${LOG_DIR}/cron_prices.log 2>&1

# Competitor Tracker — Daily at 9:00 AM UTC
0 9 * * * cd ${BOT_DIR} && ${PYTHON} competitor_tracker.py >> ${LOG_DIR}/cron_competitors.log 2>&1

# Daily Report — Every evening at 6:00 PM UTC
0 18 * * * cd ${BOT_DIR} && ${PYTHON} report_generator.py >> ${LOG_DIR}/cron_report.log 2>&1
${CRON_MARKER} END"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "DROPSHIP BOTS"; then
    echo "Dropship bot cron jobs already exist. Removing old entries first..."
    crontab -l | sed "/${CRON_MARKER}/,/${CRON_MARKER} END/d" | crontab -
fi

# Append to existing crontab (preserves all other cron jobs)
(crontab -l 2>/dev/null; echo ""; echo "${CRON_ENTRIES}") | crontab -

echo "Cron jobs installed successfully!"
echo ""
echo "Current crontab:"
crontab -l
echo ""
echo "To verify: crontab -l"
echo "To remove: crontab -l | sed '/DROPSHIP BOTS/,/DROPSHIP BOTS END/d' | crontab -"

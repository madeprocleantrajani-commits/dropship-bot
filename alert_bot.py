"""
Telegram Alert Bot
-------------------
Sends alerts to your Telegram when bots find something interesting.

Setup:
  1. Message @BotFather on Telegram
  2. Send /newbot and follow instructions
  3. Copy the bot token to your .env file
  4. Start a chat with your new bot (send it any message)
  5. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates
  6. Find your chat_id in the response
  7. Add both to .env

All other bots import send_alert() from this module.
"""
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_logger

log = get_logger("alert_bot")

MAX_MESSAGE_LENGTH = 4096  # Telegram limit


def send_alert(message: str, parse_mode: str = None) -> bool:
    """
    Send a message to your Telegram bot.
    Returns True if sent successfully.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        log.info(f"Alert (not sent): {message[:200]}...")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Split long messages
    chunks = _split_message(message)

    success = True
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                log.error(f"Telegram API error: {response.status_code} — {response.text}")
                success = False
            else:
                log.info("Telegram alert sent successfully")
        except requests.RequestException as e:
            log.error(f"Failed to send Telegram alert: {e}")
            success = False

    return success


def send_document(file_path: str, caption: str = "") -> bool:
    """Send a file (like a JSON report) to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"

    try:
        with open(file_path, "rb") as f:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption[:1024],
            }
            files = {"document": f}
            response = requests.post(url, data=payload, files=files, timeout=30)

            if response.status_code == 200:
                log.info(f"Document sent: {file_path}")
                return True
            else:
                log.error(f"Failed to send document: {response.text}")
                return False
    except Exception as e:
        log.error(f"Document send error: {e}")
        return False


def _split_message(text: str) -> list[str]:
    """Split a message into chunks that fit Telegram's limit."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MESSAGE_LENGTH:
            chunks.append(text)
            break

        # Try to split at a newline
        split_at = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if split_at == -1:
            split_at = MAX_MESSAGE_LENGTH

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


# === Quick test ===
if __name__ == "__main__":
    success = send_alert(
        "Dropship Bot Alert System\n"
        "Status: ONLINE\n\n"
        "If you see this message, your Telegram alerts are working!"
    )
    if success:
        print("Test alert sent! Check your Telegram.")
    else:
        print("Alert not sent. Check your .env configuration.")

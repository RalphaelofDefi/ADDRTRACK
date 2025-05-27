import os
import logging
import requests
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API URLs
TOKEN_METADATA_URL = "https://solana-gateway.moralis.io/token/mainnet/{}/metadata"
TOKEN_HOLDERS_URL = "https://solana-gateway.moralis.io/token/mainnet/{}/holders?limit=50"

# Icon mappings for links
LINK_ICONS = {
    "moralis": "🌐 Moralis",
    "website": "🖥️ Website",
    "telegram": "💬 Telegram",
    "reddit": "🔴 Reddit"
}

# Metadata fetcher
def fetch_token_metadata(token_address):
    url = TOKEN_METADATA_URL.format(token_address)
    headers = {"Accept": "application/json", "X-API-Key": MORALIS_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

# Holders fetcher
def fetch_token_holders(token_address):
    url = TOKEN_HOLDERS_URL.format(token_address)
    headers = {"Accept": "application/json", "X-API-Key": MORALIS_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("result", [])
    return None

# Handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_address = update.message.text.strip()

    try:
        metadata = fetch_token_metadata(token_address)
        if not metadata:
            await update.message.reply_text("No record found.")
            return

        name = metadata.get("name", "N/A")
        symbol = metadata.get("symbol", "N/A")
        logo = metadata.get("logo")
        mc = metadata.get("fullyDilutedValue", "N/A")
        links = metadata.get("links", {})

        # Build metadata message
        meta_msg = f"<b>{name} ({symbol})</b>\n"
        meta_msg += f"MC: ${mc}\n\n"

        for key, label in LINK_ICONS.items():
            if key in links:
                meta_msg += f"<a href=\"{links[key]}\">{label}</a>\n"

        # Send logo as photo if available
        if logo:
            await update.message.reply_photo(photo=logo, caption=meta_msg, parse_mode="HTML")
        else:
            await update.message.reply_text(meta_msg, parse_mode="HTML")

        # Fetch holders
        holders = fetch_token_holders(token_address)
        if not holders:
            await update.message.reply_text("No record found.")
            return

        total_tokens = sum(float(holder.get("amountFormatted", 0)) for holder in holders)

        holder_msgs = []
        for i, holder in enumerate(holders):
            addr = holder.get("address")
            amount = float(holder.get("amountFormatted", 0))
            usd_val = holder.get("value", {}).get("usd", 0)
            is_contract = holder.get("isContract", False)
            pct = (amount / total_tokens) * 100 if total_tokens else 0

            emoji = ""
            if pct >= 1:
                emoji = "🐋 "  # Whale emoji
            if is_contract:
                emoji += "🛠"  # Gear emoji

            msg = f"{i+1}. <code>{addr}</code>\nToken: {amount:.4f}, USD: ${usd_val:.2f}, {emoji} {pct:.2f}%\n"
            holder_msgs.append(msg)

        # Split into chunks to avoid Telegram message limit
        batch = ""
        for msg in holder_msgs:
            if len(batch) + len(msg) > 4000:
                await update.message.reply_text(batch, parse_mode="HTML")
                batch = msg
            else:
                batch += msg
        if batch:
            await update.message.reply_text(batch, parse_mode="HTML")

    except Exception as e:
        logger.error("Error handling token address: %s", e)
        await update.message.reply_text("An error occurred while fetching data.")

# Bot entry point
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app.run_polling()

if __name__ == '__main__':
    main()

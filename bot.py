import os
import logging
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_token_metadata(address: str):
    url = f"https://solana-gateway.moralis.io/token/mainnet/{address}/metadata"
    headers = {
        "Accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Metadata API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Metadata fetch error: {e}")
        return None

async def fetch_token_holders(address: str):
    url = f"https://solana-gateway.moralis.io/token/mainnet/{address}/holders?limit=50"
    headers = {
        "Accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("result", [])
        else:
            logger.warning(f"Holders API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Holders fetch error: {e}")
        return None

def is_valid_solana_address(address: str):
    return len(address) in (32, 44) and address.isalnum()

def format_links(links: dict) -> str:
    icons = {
        "twitter": "🐦",
        "moralis": "🌐"
    }
    return "\n".join(f"{icons.get(k, '🔗')} {v}" for k, v in links.items())

def format_metadata(metadata: dict) -> str:
    name = metadata.get("name", "N/A")
    symbol = metadata.get("symbol", "N/A")
    logo = metadata.get("logo", "")
    mc = metadata.get("fullyDilutedValue", "N/A")
    links = metadata.get("links", {})
    link_section = format_links(links)

    result = f"<b>{name} ({symbol})</b>\n"
    if logo:
        result += f"<a href='{logo}'>🖼️ Logo</a>\n"
    result += f"💰 <b>MC:</b> ${mc}\n"
    if links:
        result += link_section + "\n"
    return result

def format_holders(holders: list, total_supply: float, decimals: int) -> str:
    lines = []
    for i, holder in enumerate(holders, start=1):
        address = holder.get("address", "")
        balance = int(holder.get("amount", 0)) / (10 ** decimals)
        usd_value = float(holder.get("valueUsd", 0.0))
        percentage = (balance / total_supply) * 100 if total_supply else 0
        is_contract = holder.get("isContract", False)
        emoji = "🐋" if percentage >= 1 else ""
        contract_flag = " [Contract]" if is_contract else ""
        line = (
            f"{i}. <code>{address}</code>\n"
            f"   💵 ${usd_value:,.2f} | 🪙 {balance:.2f} | 📊 {percentage:.4f}% {emoji}{contract_flag}"
        )
        lines.append(line)

    final = "\n\n".join(lines)
    return final[:4000] if len(final) > 4000 else final  # Avoid Telegram message too long

async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()

    if not is_valid_solana_address(address):
        await update.message.reply_text("❌ Invalid Solana token address.")
        return

    try:
        # Fetch metadata
        metadata = await fetch_token_metadata(address)
        if not metadata:
            await update.message.reply_text("⚠️ No token metadata found.")
            return

        decimals = int(metadata.get("decimals", 0))
        total_supply = float(metadata.get("totalSupplyFormatted", 0.0))

        meta_text = format_metadata(metadata)

        # Fetch holders
        holders = await fetch_token_holders(address)
        if not holders:
            await update.message.reply_text("⚠️ No record found.")
            return

        holders_text = format_holders(holders, total_supply, decimals)

        full_message = meta_text + "\n\n<b>Top Holders:</b>\n\n" + holders_text
        await update.message.reply_text(full_message, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    except Exception as e:
        logger.error(f"Error fetching holders: {e}")
        await update.message.reply_text("❌ An error occurred while fetching data.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import requests
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import MessageHandler, filters
import re


# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Helper to split long text into chunks under Telegram's limit
def split_message(text, max_chars=4096):
    chunks = []
    while len(text) > max_chars:
        split_index = text.rfind("\n", 0, max_chars)
        if split_index == -1:
            split_index = max_chars
        chunks.append(text[:split_index])
        text = text[split_index:]
    chunks.append(text)
    return chunks

# Command handler for no /holders
async def token_address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()

    # Simple Solana address check (base58, usually 32-44 characters)
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", message_text):
        return  # Ignore non-address messages

    context.args = [message_text]
    await holders(update, context)


# Command handler for /holders
async def holders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a Solana token address. Usage: /holders <token_address>")
        return

    token_address = context.args[0]
    url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/top-holders"

    headers = {
        "accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            await update.message.reply_text("No record found.")
            return

        data = response.json()
        holders = data.get("result", [])
        total_supply = float(data.get("totalSupply", 0))

        if not holders:
            await update.message.reply_text("No record found.")
            return

        message_lines = []
        for idx, holder in enumerate(holders[:50], start=1):
            address = holder.get("ownerAddress", "N/A")
            balance = float(holder.get("balanceFormatted", 0))
            usd_value = float(holder.get("usdValue", 0))
            percentage = float(holder.get("percentageRelativeToTotalSupply", 0))
            is_contract = holder.get("isContract", False)
#BELOW ADD in else for dolphin and wallet addy
            whale_emoji = " 🐋" if percentage > 1 else " 🐬"
            contract_emoji = " 🏗️ This is a Contract address " if is_contract else " 💳 This is a wallet address"

            line = (
                f"{idx}. `{address}`\n"
                f"   💰 Balance: {balance:,.2f}\n"
                f"   💵 USD Value: ${usd_value:,.2f}\n"
                f"   📊 Percentage: {percentage:.4f}%{whale_emoji}{contract_emoji}\n"
            )
            message_lines.append(line)

        full_message = "\n".join(message_lines)

        # Split into Telegram-safe chunks
        for chunk in split_message(full_message):
            await update.message.reply_text(chunk, parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error fetching holders: {e}")
        await update.message.reply_text("An error occurred while fetching data.")

# Main function to start the bot
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("holders", holders))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, token_address_handler))
    application.run_polling()

if __name__ == "__main__":
    main()

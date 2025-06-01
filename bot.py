import os
import requests
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import MessageHandler, filters
import re
from telegram.constants import ParseMode
from collections import Counter

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
    matches = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", message_text)
    if not matches:
        return  # Ignore if no address

    address = matches[0]
    tokens = message_text.split()

    count = 50  # default
    percent = 0.0  # default

    if len(tokens) > 1:
        try:
            count = int(tokens[1])
            count = max(1, min(count, 100))
        except:
            pass

    if len(tokens) > 2:
        try:
            percent = float(tokens[2])
        except:
            pass

    context.args = [address, str(count), str(percent)]
    await holders(update, context)

# METADATA
def fetch_token_metadata(token_address):
    url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/metadata"
    headers = {
        "Accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching metadata: {e}")
        return None

# Command handler for /holders
async def holders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a Solana token address. Usage: /holders <address> [count] [%min]")
        return

    token_address = context.args[0]
    try:
        count = int(context.args[1]) if len(context.args) > 1 else 50
        count = max(1, min(count, 100))
    except:
        count = 50

    try:
        percent_min = float(context.args[2]) if len(context.args) > 2 else 0.0
    except:
        percent_min = 0.0

    # Fetch token metadata
    metadata = fetch_token_metadata(token_address)
    if metadata:
        name = metadata.get("name", "N/A")
        symbol = metadata.get("symbol", "N/A")
        logo = metadata.get("logo", "")
        market_cap = metadata.get("fullyDilutedValue", "N/A")
        links = metadata.get("links", {})

        # Build token info message
        token_info = f"*Token Info*\n"
        token_info += f"📛 *Name:* {name}\n"
        token_info += f"🔠 *Symbol:* {symbol}\n"
        token_info += f"💰 *Market Cap:* ${float(market_cap):,.2f}\n"

        # Build link section with icons
        icons = {
            "moralis": "🌐",
            "website": "🌍",
            "telegram": "📢",
            "reddit": "🔴"
        }

        link_text = ""
        for key, icon in icons.items():
            link = links.get(key)
            if link:
                link_text += f"{icon} [{key.capitalize()}]({link})\n"

        # Send the logo image first
        if logo:
            await update.message.reply_photo(photo=logo)

        # Send metadata info and links
        await update.message.reply_text(token_info + link_text, parse_mode='Markdown')

    # Fetch top holders
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
        shown = 0
        for idx, holder in enumerate(holders):
            percentage = float(holder.get("percentageRelativeToTotalSupply", 0))
            if percentage < percent_min:
                continue
            if shown >= count:
                break

            address = holder.get("ownerAddress", "N/A")
            balance = float(holder.get("balanceFormatted", 0))
            usd_value = float(holder.get("usdValue", 0))
            is_contract = holder.get("isContract", False)

            whale_emoji = " 🐋" if percentage > 1 else " 🐬"
            contract_emoji = " 🏗️ This is a Contract address " if is_contract else ""

            line = (
                f"{shown + 1}. `{address}`\n"
                f"   💰 Balance: {balance:,.2f}\n"
                f"   💵 USD Value: ${usd_value:,.2f}\n"
                f"   📊 Percentage: {percentage:.4f}%{whale_emoji}{contract_emoji}\n"
            )
            message_lines.append(line)
            shown += 1

        full_message = "\n".join(message_lines)

        # Split into Telegram-safe chunks
        for chunk in split_message(full_message):
            await update.message.reply_text(chunk, parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error fetching holders: {e}")
        await update.message.reply_text("An error occurred while fetching data.")

# /QUERY HANDLER-----------------------------------------------------------------------------

MAX_ADDRESSES = 15

async def query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /query <token_address1> <token_address2> ... percent=<min_percent>")
        return

    # Extract minimum percentage (default: 1)
    min_percent = 1.0
    percent_args = [arg for arg in args if arg.startswith("percent=")]
    if percent_args:
        try:
            min_percent = float(percent_args[0].split("=")[1])
            args.remove(percent_args[0])
        except ValueError:
            await update.message.reply_text("Invalid percentage format. Use `percent=1`.")
            return

    # Filter and validate Solana addresses
    token_addresses = [a for a in args if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a)]
    if not token_addresses or len(token_addresses) > MAX_ADDRESSES:
        await update.message.reply_text(f"Send between 1 and {MAX_ADDRESSES} valid Solana token addresses.")
        return

    headers = {
        "accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }

    combined_message = []

    for token_address in token_addresses:
        try:
            url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/top-holders"
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                combined_message.append(f"❌ `{token_address}`: No record found.\n")
                continue

            data = response.json()
            holders = data.get("result", [])
            total_supply = float(data.get("totalSupply", 0))

            if not holders:
                combined_message.append(f"❌ `{token_address}`: No holders found.\n")
                continue

            filtered = [
                h for h in holders[:100]
                if float(h.get("percentageRelativeToTotalSupply", 0)) >= min_percent
            ]

            if not filtered:
                combined_message.append(f"⚠️ `{token_address}`: No holders above {min_percent}%.\n")
                continue

            combined_message.append(f"🔹 Top Holders of `{token_address}` with ≥ {min_percent}%:\n")

            for idx, holder in enumerate(filtered[:50], start=1):
                address = holder.get("ownerAddress", "N/A")
                balance = float(holder.get("balanceFormatted", 0))
                usd_value = float(holder.get("usdValue", 0))
                percentage = float(holder.get("percentageRelativeToTotalSupply", 0))
                is_contract = holder.get("isContract", False)

                whale_emoji = " 🐋" if percentage > 1 else " 🐬"
                contract_note = " 🏗️ Contract" if is_contract else ""

                combined_message.append(
                    f"{idx}. `{address}`\n"
                    f"   💰 {balance:,.2f}   💵 ${usd_value:,.2f}   📊 {percentage:.2f}%{whale_emoji} {contract_note}"
                )

            combined_message.append("")  # Separator

        except Exception as e:
            logging.error(f"Error in /query for {token_address}: {e}")
            combined_message.append(f"❌ `{token_address}`: Error fetching data.\n")

    # Send result in safe Telegram chunks
    for chunk in split_message("\n".join(combined_message)):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)

#------------------------------/FIND COMMAND---------------------------------------------------------------

async def find_common_holders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("Usage: /find [threshold_percent] <token1> <token2> ... <tokenN> (2–15 tokens)")
        return

    # Default threshold
    threshold = 1.0

    # Check if the first argument is a percentage
    try:
        first_arg = float(args[0])
        threshold = first_arg
        token_addresses = args[1:]
    except ValueError:
        # No threshold provided
        token_addresses = args

    if not (2 <= len(token_addresses) <= 15):
        await update.message.reply_text("Please provide between 2 to 15 token addresses.")
        return


    headers = {
        "accept": "application/json",
        "X-API-Key": MORALIS_API_KEY
    }

    holders_list = []

    for token in token_addresses:
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token}/top-holders"
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                await update.message.reply_text(f"Error fetching holders for {token}")
                return
            data = response.json().get("result", [])
            holders = {
                holder["ownerAddress"]
                for holder in data
                if float(holder.get("percentageRelativeToTotalSupply", 0)) >= threshold
            }
            holders_list.append(holders)

        except Exception as e:
            logging.error(f"Error with {token}: {e}")
            await update.message.reply_text(f"An error occurred with token: {token}")
            return

    # Intersect all sets to find common holders
    if not holders_list:
        await update.message.reply_text("No holders found.")
        return

    common = set.intersection(*holders_list)
    if not common:
        await update.message.reply_text("No wallets found that meet the criteria across all tokens.")
        return

    wallet_lines = [f"`{wallet}`" for wallet in common]
    full_msg = "🔍 Wallets holding all tokens with at least " + f"{threshold}%:\n\n" + "\n".join(wallet_lines)

    for chunk in split_message(full_msg):
        await update.message.reply_text(chunk, parse_mode='Markdown')


#----------------------------------------------------------------------------------------------
# Main function to start the bot
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("holders", holders))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, token_address_handler))
    application.add_handler(CommandHandler("query", query))
    application.add_handler(CommandHandler("find", find_common_holders))
    application.run_polling()

if __name__ == "__main__":
    main()

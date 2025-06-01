# Full code in parts due to length, copy & paste into bot.py

import os
import requests
import logging
import csv
import tempfile
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

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

def generate_csv(filename: str, rows: list, headers: list) -> str:
    temp_path = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', prefix=filename + "_")
    with open(temp_path.name, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return temp_path.name

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

# --- /holders command ---
async def token_address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    matches = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", message_text)
    if not matches:
        return
    address = matches[0]
    tokens = message_text.split()
    count = 50
    percent = 0.0
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

    metadata = fetch_token_metadata(token_address)
    if metadata:
        name = metadata.get("name", "N/A")
        symbol = metadata.get("symbol", "N/A").replace("/", "_")
        logo = metadata.get("logo", "")
        market_cap = metadata.get("fullyDilutedValue", "N/A")
        links = metadata.get("links", {})
        token_info = f"*Token Info*\n"
        token_info += f"📛 *Name:* {name}\n"
        token_info += f"🔠 *Symbol:* {symbol}\n"
        token_info += f"💰 *Market Cap:* ${float(market_cap):,.2f}\n"
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
        if logo:
            await update.message.reply_photo(photo=logo)
        await update.message.reply_text(token_info + link_text, parse_mode='Markdown')
    else:
        symbol = "holders"

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
        if not holders:
            await update.message.reply_text("No record found.")
            return

        message_lines = []
        csv_rows = []
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
            csv_rows.append([shown + 1, address, balance, usd_value, percentage, "Yes" if is_contract else "No"])
            shown += 1

        symbol_filename = symbol if metadata else "holders"
        csv_path = generate_csv(symbol_filename, csv_rows, ["Rank", "Wallet Address", "Balance", "USD Value", "Percentage", "Is Contract"])
        for chunk in split_message("\n".join(message_lines)):
            await update.message.reply_text(chunk, parse_mode='Markdown')
        await update.message.reply_document(document=open(csv_path, "rb"), filename=os.path.basename(csv_path))

    except Exception as e:
        logging.error(f"Error fetching holders: {e}")
        await update.message.reply_text("An error occurred while fetching data.")

# --- /query ---
async def query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /query <address1> <address2> ... <min_percentage>")
        return

    *addresses, min_percent_str = context.args
    try:
        min_percent = float(min_percent_str)
    except:
        await update.message.reply_text("Invalid percentage.")
        return

    all_holders = {}
    symbol_list = []

    for token_address in addresses:
        metadata = fetch_token_metadata(token_address)
        symbol = metadata.get("symbol", token_address[:4]).replace("/", "_") if metadata else token_address[:4]
        symbol_list.append(symbol)
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/top-holders"
        headers = {
            "accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                continue
            data = response.json()
            for holder in data.get("result", []):
                pct = float(holder.get("percentageRelativeToTotalSupply", 0))
                if pct < min_percent:
                    continue
                addr = holder.get("ownerAddress")
                if addr:
                    all_holders.setdefault(addr, []).append(token_address)
        except Exception as e:
            logging.error(f"Query fetch error for {token_address}: {e}")

    result = [addr for addr, tokens in all_holders.items() if len(tokens) == len(addresses)]

    if not result:
        await update.message.reply_text("No wallets found holding all tokens at the specified percentage.")
        return

    symbol_filename = "_".join(symbol_list[:5])
    csv_path = generate_csv(symbol_filename, [[i+1, addr] for i, addr in enumerate(result)], ["Rank", "Wallet Address"])

    preview = "\n".join([f"{i+1}. `{addr}`" for i, addr in enumerate(result[:30])])
    await update.message.reply_text(preview, parse_mode='Markdown')
    await update.message.reply_document(document=open(csv_path, "rb"), filename=os.path.basename(csv_path))

# --- /find ---
async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /find <address1> <address2> ... <min_percentage>")
        return

    *addresses, min_percent_str = context.args
    try:
        min_percent = float(min_percent_str)
    except:
        await update.message.reply_text("Invalid percentage.")
        return

    token_holder_maps = []
    symbol_list = []

    for token_address in addresses:
        metadata = fetch_token_metadata(token_address)
        symbol = metadata.get("symbol", token_address[:4]).replace("/", "_") if metadata else token_address[:4]
        symbol_list.append(symbol)

        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/top-holders"
        headers = {
            "accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }

        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                continue
            data = response.json()
            holders = set()
            for holder in data.get("result", []):
                if float(holder.get("percentageRelativeToTotalSupply", 0)) >= min_percent:
                    holders.add(holder["ownerAddress"])
            token_holder_maps.append(holders)
        except Exception as e:
            logging.error(f"Find fetch error for {token_address}: {e}")

    if not token_holder_maps:
        await update.message.reply_text("No data retrieved.")
        return

    common_holders = set.intersection(*token_holder_maps)

    if not common_holders:
        await update.message.reply_text("No common wallets found holding all tokens above threshold.")
        return

    symbol_filename = "_".join(symbol_list[:5])
    csv_path = generate_csv(symbol_filename, [[i+1, addr] for i, addr in enumerate(common_holders)], ["Rank", "Wallet Address"])

    preview = "\n".join([f"{i+1}. `{addr}`" for i, addr in enumerate(list(common_holders)[:30])])
    await update.message.reply_text(preview, parse_mode='Markdown')
    await update.message.reply_document(document=open(csv_path, "rb"), filename=os.path.basename(csv_path))

# --- Bot Start ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("holders", holders))
    app.add_handler(CommandHandler("query", query))
    app.add_handler(CommandHandler("find", find))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, token_address_handler))
    app.run_polling()

if __name__ == "__main__":
    main()

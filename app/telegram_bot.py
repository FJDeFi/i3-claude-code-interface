import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text

    try:
        r = requests.post(f"{API_URL}/prompt", params={"prompt": prompt})
        job_id = r.json()["job_id"]

        await update.message.reply_text(f"🧠 Job submitted: {job_id}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle))

    print("Telegram bot running...")
    app.run_polling()

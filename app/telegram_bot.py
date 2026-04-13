import asyncio
import os
import time
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RESULT_POLL_INTERVAL = float(os.getenv("RESULT_POLL_INTERVAL", "1"))
RESULT_TIMEOUT = float(os.getenv("RESULT_TIMEOUT", "60"))


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text

    try:
        r = await asyncio.to_thread(
            requests.post, f"{API_URL}/prompt", params={"prompt": prompt}, timeout=15
        )
        r.raise_for_status()
        job_id = r.json()["job_id"]

        await update.message.reply_text(f"🧠 Job submitted: {job_id}")

        start = time.monotonic()
        while time.monotonic() - start < RESULT_TIMEOUT:
            await asyncio.sleep(RESULT_POLL_INTERVAL)
            result_resp = await asyncio.to_thread(
                requests.get, f"{API_URL}/result/{job_id}", timeout=15
            )
            result_resp.raise_for_status()
            payload = result_resp.json()

            if payload.get("error"):
                await update.message.reply_text(f"❌ Job error: {payload['error']}")
                return

            status = payload.get("status")
            if status == "done":
                await update.message.reply_text(
                    f"✅ Result:\n{payload.get('result', '')}"
                )
                return
            if status == "failed":
                await update.message.reply_text(
                    f"❌ Job failed:\n{payload.get('result', '')}"
                )
                return

        await update.message.reply_text(
            f"⏳ Job still running after {int(RESULT_TIMEOUT)}s: {job_id}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle))

    print("Telegram bot running...")
    app.run_polling()

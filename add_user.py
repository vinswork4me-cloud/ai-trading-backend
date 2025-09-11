import os
import asyncio
import asyncpg
from twilio.rest import Client
import requests

# ---------------- ENV VARIABLES ----------------
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM", "whatsapp:+14155238886")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ---------------- USER CONFIG ----------------
USER_ID = 1  # can be any number you want
PHONE_NUMBER = "+919685891345"  # e.g., +919876543210
TELEGRAM_CHAT_ID = "5562038165"  # get from bot
NOTIFY_WHATSAPP = True
NOTIFY_TELEGRAM = True

# ---------------- NOTIFICATIONS ----------------
def send_whatsapp_message(message: str, phone_number: str):
    if not (TWILIO_SID and TWILIO_TOKEN and phone_number):
        print("⚠️ WhatsApp not configured")
        return
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=message,
            from_=WHATSAPP_FROM,
            to=f"whatsapp:{phone_number}"
        )
        print(f"✅ WhatsApp sent: {message}")
    except Exception as e:
        print(f"❌ WhatsApp failed: {e}")

def send_telegram_message(message: str, chat_id: str):
    if not (TELEGRAM_TOKEN and chat_id):
        print("⚠️ Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        requests.post(url, json=payload)
        print(f"✅ Telegram sent: {message}")
    except Exception as e:
        print(f"❌ Telegram failed: {e}")

async def add_user_and_test():
    if not SUPABASE_DB_URL:
        print("❌ SUPABASE_DB_URL not set")
        return

    pool = await asyncpg.create_pool(dsn=SUPABASE_DB_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, notify_whatsapp, notify_telegram, phone_number, telegram_chat_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                notify_whatsapp = EXCLUDED.notify_whatsapp,
                notify_telegram = EXCLUDED.notify_telegram,
                phone_number = EXCLUDED.phone_number,
                telegram_chat_id = EXCLUDED.telegram_chat_id
        """, USER_ID, NOTIFY_WHATSAPP, NOTIFY_TELEGRAM, PHONE_NUMBER, TELEGRAM_CHAT_ID)
        print(f"✅ User {USER_ID} added/updated successfully")

    # Send test notification
    test_message = "🟢 Test notification: WhatsApp & Telegram setup working!"
    if NOTIFY_WHATSAPP:
        send_whatsapp_message(test_message, PHONE_NUMBER)
    if NOTIFY_TELEGRAM:
        send_telegram_message(test_message, TELEGRAM_CHAT_ID)

    await pool.close()

if __name__ == "__main__":
    asyncio.run(add_user_and_test())

import os
import asyncio
import asyncpg

# ---------------- ENV VARIABLES ----------------
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

# ---------------- USER INFO ----------------
USER_ID = 1  # Change if you want a different ID
PHONE_NUMBER = "+919685891345"  # Your WhatsApp number with country code
TELEGRAM_CHAT_ID = "@Mytalemystory"   # Your Telegram chat ID

# Notifications
NOTIFY_WHATSAPP = True
NOTIFY_TELEGRAM = True

async def main():
    if not SUPABASE_DB_URL:
        print("❌ SUPABASE_DB_URL is not set in environment")
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

    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())

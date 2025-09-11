import os
import ccxt
import asyncpg
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from twilio.rest import Client
from fastapi_utils.tasks import repeat_every

# ---------------- ENV VARIABLES ----------------
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
MODE = os.getenv("MODE", "PAPER")

# Twilio WhatsApp (global sandbox fallback)
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM", "whatsapp:+14155238886")

# Telegram Bot
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Default watchlist for background scanner
WATCHLIST = ["BTC/USD", "ETH/USD"]

# ---------------- FASTAPI SETUP ----------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    if SUPABASE_DB_URL:
        db_pool = await asyncpg.create_pool(dsn=SUPABASE_DB_URL, min_size=1, max_size=5)
        async with db_pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id SERIAL PRIMARY KEY,
                notify_whatsapp BOOLEAN DEFAULT false,
                notify_telegram BOOLEAN DEFAULT false,
                phone_number TEXT,
                telegram_chat_id TEXT
            );
            """)

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

# ---------------- EXCHANGE ----------------
def get_exchange():
    return ccxt.kraken({"enableRateLimit": True})

def resolve_symbol(symbol: str, markets: dict):
    symbol = symbol.upper()
    if symbol in markets: return symbol
    if "BTC" in symbol:
        alt = symbol.replace("BTC", "XBT")
        if alt in markets: return alt
    if "XBT" in symbol:
        alt = symbol.replace("XBT", "BTC")
        if alt in markets: return alt
    if "USD" in symbol:
        alt = symbol.replace("USD", "ZUSD")
        if alt in markets: return alt
    if "ZUSD" in symbol:
        alt = symbol.replace("ZUSD", "USD")
        if alt in markets: return alt
    raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

# ---------------- DB HELPERS ----------------
async def get_user_settings(user_id: int):
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_settings WHERE user_id=$1", user_id)
        return dict(row) if row else None

async def update_user_settings(user_id: int, settings: dict):
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, notify_whatsapp, notify_telegram, phone_number, telegram_chat_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                notify_whatsapp = EXCLUDED.notify_whatsapp,
                notify_telegram = EXCLUDED.notify_telegram,
                phone_number = EXCLUDED.phone_number,
                telegram_chat_id = EXCLUDED.telegram_chat_id
        """, user_id, settings.get("notify_whatsapp"), settings.get("notify_telegram"),
             settings.get("phone_number"), settings.get("telegram_chat_id"))

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

async def notify_user(user_id: int, message: str):
    settings = await get_user_settings(user_id)
    if not settings:
        print(f"⚠️ No settings for user {user_id}")
        return
    if settings["notify_whatsapp"]:
        send_whatsapp_message(message, settings["phone_number"])
    if settings["notify_telegram"]:
        send_telegram_message(message, settings["telegram_chat_id"])

# ---------------- ENDPOINTS ----------------
@app.get("/")
async def root():
    return {"message": "Trading AI with Kraken + Notifications is running 🚀"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/settings/update/{user_id}")
async def update_settings(user_id: int, settings: dict):
    await update_user_settings(user_id, settings)
    return {"status": "ok", "user_id": user_id, "settings": settings}

@app.get("/settings/get/{user_id}")
async def get_settings(user_id: int):
    settings = await get_user_settings(user_id)
    if not settings:
        raise HTTPException(status_code=404, detail="User not found")
    return settings

@app.get("/price/{symbol:path}")
async def get_price(symbol: str):
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        resolved = resolve_symbol(symbol, markets)
        ticker = ex.fetch_ticker(resolved)
        return {"input": symbol, "resolved": resolved, "price": ticker["last"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signal/{user_id}/{symbol:path}")
async def ema_signal(user_id: int, symbol: str):
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        resolved = resolve_symbol(symbol, markets)
        ohlcv = ex.fetch_ohlcv(resolved, timeframe="1m", limit=100)
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
        df["ema9"] = df["close"].ewm(span=9).mean()
        df["ema21"] = df["close"].ewm(span=21).mean()
        last = df.iloc[-1]
        signal = "HOLD"
        if last["ema9"] > last["ema21"]:
            signal = "BUY"
        elif last["ema9"] < last["ema21"]:
            signal = "SELL"

        if signal in ["BUY", "SELL"]:
            await notify_user(user_id, f"⚡ {signal} Signal for {resolved} at {last['close']}")

        return {"user_id": user_id, "input": symbol, "resolved": resolved, "signal": signal, "price": last["close"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- EXTRA ENDPOINTS ----------------
@app.get("/ping-exchange")
async def ping_exchange():
    """Check if exchange API is alive"""
    try:
        ex = get_exchange()
        ex.load_markets()
        return {"status": "ok", "exchange": "Kraken"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/markets")
async def get_markets():
    """Return available trading markets"""
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        return {"count": len(markets), "markets": list(markets.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- BACKGROUND SCANNER ----------------
# ---------------- BACKGROUND SCANNER ----------------
@app.on_event("startup")
@repeat_every(seconds=60)  # run every 1 min
async def run_signal_checker():
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        for symbol in WATCHLIST:
            try:
                # Convert BTC-USD -> BTC/USD for Kraken
                symbol = symbol.replace("-", "/")
                resolved = resolve_symbol(symbol, markets)
                ohlcv = ex.fetch_ohlcv(resolved, timeframe="1m", limit=100)
                df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
                df["ema9"] = df["close"].ewm(span=9).mean()
                df["ema21"] = df["close"].ewm(span=21).mean()
                last = df.iloc[-1]
                signal = "HOLD"
                if last["ema9"] > last["ema21"]:
                    signal = "BUY"
                elif last["ema9"] < last["ema21"]:
                    signal = "SELL"

                if signal in ["BUY", "SELL"]:
                    # notify ALL users in DB
                    async with db_pool.acquire() as conn:
                        rows = await conn.fetch("SELECT user_id FROM user_settings")
                        for row in rows:
                            await notify_user(row["user_id"], f"⏰ {signal} Signal (auto) for {resolved} at {last['close']}")
            except Exception as inner_err:
                print(f"⚠️ Error scanning {symbol}: {inner_err}")
    except Exception as e:
        print(f"❌ Background scanner failed: {e}")

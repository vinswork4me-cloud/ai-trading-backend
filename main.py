import os
import ccxt
import asyncpg
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ENV variables
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
MODE = os.getenv("MODE", "PAPER")  # PAPER or LIVE

app = FastAPI()

# Allow frontend (we’ll set Vercel later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for dev, later restrict to your frontend domain
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

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

# ------------------------------
# Exchange connection (Kraken)
# ------------------------------
def get_exchange():
    return ccxt.kraken({
        "enableRateLimit": True
    })

# ------------------------------
# Health endpoint
# ------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# ------------------------------
# Ping exchange
# ------------------------------
@app.get("/ping-exchange")
async def ping_exchange():
    try:
        ex = get_exchange()
        ticker = ex.fetch_ticker("BTC/USD")  # Kraken uses BTC/USD
        return {"status": "connected", "price": ticker["last"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ------------------------------
# Price endpoint
# ------------------------------
@app.get("/price/{symbol}")
async def get_price(symbol: str = "BTC/USD"):
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        if symbol not in markets:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on Kraken")
        ticker = ex.fetch_ticker(symbol)
        return {"symbol": symbol, "price": ticker["last"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------
# Simple EMA signal endpoint
# ------------------------------
@app.get("/signal/{symbol}")
async def ema_signal(symbol: str = "BTC/USD"):
    try:
        ex = get_exchange()
        ohlcv = ex.fetch_ohlcv(symbol, timeframe="1m", limit=100)
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
        df["ema9"] = df["close"].ewm(span=9).mean()
        df["ema21"] = df["close"].ewm(span=21).mean()
        last = df.iloc[-1]
        signal = "HOLD"
        if last["ema9"] > last["ema21"]:
            signal = "BUY"
        elif last["ema9"] < last["ema21"]:
            signal = "SELL"
        return {"symbol": symbol, "signal": signal, "price": last["close"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

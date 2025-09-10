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

# Allow frontend (for development, later restrict to frontend domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_pool = None

# --------------------------
# Database connection (Supabase)
# --------------------------
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

# --------------------------
# Kraken exchange connection
# --------------------------
def get_exchange():
    return ccxt.kraken({
        "enableRateLimit": True
    })

# --------------------------
# Helper: Kraken symbol formatting
# --------------------------
def format_symbol_for_kraken(symbol: str):
    symbol = symbol.upper()
    mapping = {
        "BTC/USD": "XBT/ZUSD",
        "ETH/USD": "ETH/ZUSD",
        "BTC/USDT": "XBT/USDT",
        "ETH/USDT": "ETH/USDT",
    }
    return mapping.get(symbol, symbol)

# --------------------------
# Root endpoint
# --------------------------
@app.get("/")
async def root():
    return {"message": "AI Trading Backend is running. Use /health, /price, /signal endpoints."}

# --------------------------
# Health check
# --------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# --------------------------
# Ping exchange
# --------------------------
@app.get("/ping-exchange")
async def ping_exchange():
    try:
        ex = get_exchange()
        symbol = format_symbol_for_kraken("BTC/USD")
        ticker = ex.fetch_ticker(symbol)
        return {"status": "connected", "symbol": symbol, "price": ticker["last"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# --------------------------
# Price endpoint
# --------------------------
@app.get("/price/{symbol}")
async def get_price(symbol: str):
    try:
        ex = get_exchange()
        symbol = format_symbol_for_kraken(symbol)
        markets = ex.load_markets()
        if symbol not in markets:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on Kraken")
        ticker = ex.fetch_ticker(symbol)
        return {"symbol": symbol, "price": ticker["last"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --------------------------
# EMA signal endpoint
# --------------------------
@app.get("/signal/{symbol}")
async def ema_signal(symbol: str):
    try:
        ex = get_exchange()
        symbol = format_symbol_for_kraken(symbol)
        ohlcv = ex.fetch_ohlcv(symbol, timeframe="1m", limit=100)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
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

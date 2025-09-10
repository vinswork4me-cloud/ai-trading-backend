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

# Allow frontend (later restrict origins in prod)
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

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

# ----------- Exchange Setup -----------
def get_exchange():
    return ccxt.kraken({"enableRateLimit": True})

def resolve_symbol(symbol: str, markets: dict):
    """Tries to find the correct Kraken symbol for a user request."""
    symbol = symbol.upper()
    if symbol in markets:
        return symbol

    # Handle BTC vs XBT difference
    if "BTC" in symbol:
        alt = symbol.replace("BTC", "XBT")
        if alt in markets:
            return alt
    if "XBT" in symbol:
        alt = symbol.replace("XBT", "BTC")
        if alt in markets:
            return alt

    # Handle USD vs ZUSD difference
    if "USD" in symbol:
        alt = symbol.replace("USD", "ZUSD")
        if alt in markets:
            return alt
    if "ZUSD" in symbol:
        alt = symbol.replace("ZUSD", "USD")
        if alt in markets:
            return alt

    raise HTTPException(
        status_code=404,
        detail=f"Symbol {symbol} not found. Try /markets to see available pairs."
    )

# ----------- Endpoints -----------

@app.get("/")
async def root():
    return {"message": "Kraken Trading API is running"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ping-exchange")
async def ping_exchange():
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        symbol = resolve_symbol("BTC/USD", markets)
        ticker = ex.fetch_ticker(symbol)
        return {"status": "connected", "symbol": symbol, "price": ticker["last"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/markets")
async def get_markets():
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        return {"markets": list(markets.keys())[:50]}  # show first 50 markets
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/price/{symbol}")
async def get_price(symbol: str):
    try:
        ex = get_exchange()
        markets = ex.load_markets()
        resolved = resolve_symbol(symbol, markets)
        ticker = ex.fetch_ticker(resolved)
        return {"input": symbol, "resolved": resolved, "price": ticker["last"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signal/{symbol}")
async def ema_signal(symbol: str):
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
        return {"input": symbol, "resolved": resolved, "signal": signal, "price": last["close"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

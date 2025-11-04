#!/usr/bin/env python3
# BTC 1H Signal Bot (text-only alerts)
# Confluence signals for BTC/USDT across Binance US and Bybit
# Sends alerts 10 minutes before each UTC hourly close
# Render Free Web Service compatible (Flask heartbeat on $PORT)

import os, time, requests, threading
from datetime import datetime, timezone
from flask import Flask  # heartbeat for Render

# === ENV ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BINANCE_US = "https://api.binance.us/api/v3/klines"
BYBIT_KLINES = "https://api.bybit.com/v5/market/kline"
BYBIT_ORDERBOOK = "https://api.bybit.com/v5/market/orderbook"

SYMBOL = "BTCUSDT"
INTERVAL = "60"         # Bybit 60m
LOOKBACK = 24           # 24 hours
VOL_SPIKE_MULT = 1.8    # volume spike threshold

# === Data helpers ===
def fetch_binance():
    p = {"symbol": SYMBOL, "interval": "1h", "limit": LOOKBACK + 1}
    r = requests.get(BINANCE_US, params=p, timeout=10)
    r.raise_for_status()
    j = r.json()
    # Binance returns ms timestamps
    return [{"time": int(x[0]) // 1000,
             "open": float(x[1]), "high": float(x[2]),
             "low": float(x[3]), "close": float(x[4]),
             "vol": float(x[5])} for x in j]

def fetch_bybit():
    p = {"category": "linear", "symbol": SYMBOL, "interval": INTERVAL, "limit": LOOKBACK + 1}
    r = requests.get(BYBIT_KLINES, params=p, timeout=10)
    r.raise_for_status()
    j = r.json()["result"]["list"]
    out = []
    # Bybit returns newest first; reverse to oldest→newest
    for x in reversed(j):
        out.append({
            "time": int(x["start"]),
            "open": float(x["open"]), "high": float(x["high"]),
            "low": float(x["low"]), "close": float(x["close"]),
            "vol": float(x["volume"])
        })
    return out

def get_vwap(candles):
    tot_vol, tot_vp = 0.0, 0.0
    for c in candles:
        typical = (c["high"] + c["low"] + c["close"]) / 3.0
        tot_vp += typical * c["vol"]
        tot_vol += c["vol"]
    return (tot_vp / tot_vol) if tot_vol else None

def get_orderflow_snapshot():
    """Lightweight snapshot from Bybit order book to include delta/imbalance context."""
    try:
        p = {"category": "linear", "symbol": SYMBOL, "limit": 200}
        r = requests.get(BYBIT_ORDERBOOK, params=p, timeout=5)
        r.raise_for_status()
        res = r.json()["result"]
        bids = res["b"]  # [price, size]
        asks = res["a"]
        bid_sum = sum(float(x[1]) for x in bids)
        ask_sum = sum(float(x[1]) for x in asks)
        delta = bid_sum - ask_sum
        imb = (bid_sum / (bid_sum + ask_sum) * 100.0) if (bid_sum + ask_sum) else 0.0
        return delta, imb
    except Exception:
        return None, None

# === Signals ===
def detect_fakeout(candles):
    highs = [x["high"] for x in candles[:-1]]
    lows  = [x["low"]  for x in candles[:-1]]
    last  = candles[-1]
    if not highs or not lows:
        return False
    range_high, range_low = max(highs), min(lows)

    vols = [x["vol"] for x in candles[:-1]]
    avg_vol = (sum(vols) / len(vols)) if vols else 0.0

    cond_up = last["high"] > range_high and last["close"] < range_high and last["vol"] > avg_vol * VOL_SPIKE_MULT
    cond_dn = last["low"]  < range_low  and last["close"] > range_low  and last["vol"] > avg_vol * VOL_SPIKE_MULT
    return cond_up or cond_dn

def detect_vwap_flip(candles):
    mid = len(candles) // 2
    v1 = get_vwap(candles[:mid])
    v2 = get_vwap(candles[mid:])
    if v1 is None or v2 is None:
        return False
    slope_up   = v2 > v1
    last_close = candles[-1]["close"]
    return (slope_up and last_close > v2) or ((not slope_up) and last_close < v2)

# === Alerts ===
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram env vars missing, skipping send.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

# === Core check ===
def check_signals():
    now = datetime.now(timezone.utc)
    # Run only 10 minutes before hourly close (e.g., 12:50, 13:50, ...)
    if now.minute < 50:
        return

    try:
        bnb  = fetch_binance()
        bybt = fetch_bybit()

        fakeout  = detect_fakeout(bnb)     and detect_fakeout(bybt)
        vwapflip = detect_vwap_flip(bnb)    and detect_vwap_flip(bybt)
        delta, imb = get_orderflow_snapshot()

        if fakeout or vwapflip:
            msg = (
                f"⚡ *BTC 1H Signal Alert* ⚡\n"
                f"Time (UTC): {now.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"Exchange Confluence: BinanceUS ✅  Bybit ✅\n"
                f"Fakeout: {'✅' if fakeout else '❌'}\n"
                f"VWAP Flip: {'✅' if vwapflip else '❌'}\n\n"
                f"Order Flow Delta: {delta:.2f} | Imbalance: {imb:.1f}%\n\n"
                f"_Signal generated ~10 minutes before hourly close._"
            )
            print(msg)
            send_telegram(msg)

    except Exception as e:
        print(f"⚠️ Error checking signals: {e}")

# === Flask heartbeat for Render Free Web Service ===
app = Flask(__name__)

@app.route("/")
def health():
    return "BTC 1H Signal Bot is running (heartbeat)."

def run_web():
    port = int(os.getenv("PORT", "10000"))
    # threaded=True so it doesn't block the bot loop
    app.run(host="0.0.0.0", port=port, threaded=True)

# === Main loop ===
if __name__ == "__main__":
    # Start heartbeat web server in the background
    threading.Thread(target=run_web, daemon=True).start()

    print("✅ BTC 1H Signal Bot started — monitoring Binance US + Bybit (UTC)")
    while True:
        try:
            check_signals()
            time.sleep(600)  # check every 10 minutes
        except Exception as e:
            print(f"⚠️ Error in main loop: {e}")
            time.sleep(60)

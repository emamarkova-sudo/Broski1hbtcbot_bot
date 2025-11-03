#!/usr/bin/env python3
# BTC 1H Signal Bot (text-only alerts)
# Confluence signals for BTC/USDT across Binance US and Bybit
# Triggers 10 minutes before each UTC hourly close when both exchanges confirm

import os, time, math, requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
BINANCE_US = "https://api.binance.us/api/v3/klines"
BYBIT = "https://api.bybit.com/v5/market/kline"
BYBIT_ORDERFLOW = "https://api.bybit.com/v5/market/orderbook"

SYMBOL = "BTCUSDT"
INTERVAL = "60"
LOOKBACK = 24
VOL_SPIKE_MULT = 1.8

# === Helper functions ===
def fetch_binance():
    p = {"symbol": SYMBOL, "interval": "1h", "limit": LOOKBACK + 1}
    r = requests.get(BINANCE_US, params=p, timeout=10)
    r.raise_for_status()
    j = r.json()
    return [{"time": int(x[0]) // 1000,
             "open": float(x[1]), "high": float(x[2]),
             "low": float(x[3]), "close": float(x[4]),
             "vol": float(x[5])} for x in j]

def fetch_bybit():
    p = {"category": "linear", "symbol": SYMBOL, "interval": INTERVAL, "limit": LOOKBACK + 1}
    r = requests.get(BYBIT, params=p, timeout=10)
    r.raise_for_status()
    j = r.json()["result"]["list"]
    out = []
    for x in reversed(j):
        out.append({
            "time": int(x["start"]),
            "open": float(x["open"]), "high": float(x["high"]),
            "low": float(x["low"]), "close": float(x["close"]),
            "vol": float(x["volume"])
        })
    return out

def get_vwap(candles):
    tot_vol, tot_vp = 0, 0
    for c in candles:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        tot_vp += typical * c["vol"]
        tot_vol += c["vol"]
    return tot_vp / tot_vol if tot_vol else None

def get_orderflow_snapshot():
    try:
        p = {"category": "linear", "symbol": SYMBOL, "limit": 200}
        r = requests.get(BYBIT_ORDERFLOW, params=p, timeout=5)
        r.raise_for_status()
        j = r.json()["result"]["b"]
        bid_sum = sum(float(x[1]) for x in j)
        ask_sum = sum(float(x[1]) for x in r.json()["result"]["a"])
        delta = bid_sum - ask_sum
        imb = (bid_sum / (ask_sum + bid_sum)) * 100 if (ask_sum + bid_sum) else 0
        return delta, imb
    except Exception:
        return None, None

def detect_fakeout(candles):
    highs = [x["high"] for x in candles[:-1]]
    lows = [x["low"] for x in candles[:-1]]
    last = candles[-1]
    range_high, range_low = max(highs), min(lows)
    vols = [x["vol"] for x in candles[:-1]]
    avg_vol = sum(vols) / len(vols)
    cond_up = last["high"] > range_high and last["close"] < range_high and last["vol"] > avg_vol * VOL_SPIKE_MULT
    cond_down = last["low"] < range_low and last["close"] > range_low and last["vol"] > avg_vol * VOL_SPIKE_MULT
    return cond_up or cond_down

def detect_vwap_flip(candles):
    mid = len(candles) // 2
    v1 = get_vwap(candles[:mid])
    v2 = get_vwap(candles[mid:])
    if not v1 or not v2:
        return False
    slope_up = v2 > v1 and c_

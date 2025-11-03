#!/usr/bin/env python3
# BTC 1H Telegram Signal Bot (text-only)
# Simplified: Binance data + Telegram alerts

import os, time, requests
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
TELEGRAM_BOT_TOKEN = os.getenv("8278425461:AAGrM3joAUSK3V0eFt2WXY80Mjex3D1mpO0", "").strip()
TELEGRAM_CHAT_ID = os.getenv("5042733315", "").strip()
POLL_SECONDS = 60
RANGE_LOOKBACK = 24
VOL_SPIKE_MULTIPLIER = 1.8

BINANCE = "https://api.binance.com"
TG = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""

def fetch_klines(symbol="BTCUSDT", interval="1h", limit=200):
    url = f"{BINANCE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return [
        {"open_time": int(row[0]), "open": float(row[1]), "high": float(row[2]),
         "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
         "close_time": int(row[6])}
        for row in r.json()
    ]

def sma(values, n): return sum(values[-n:]) / n if len(values) >= n else None

def compute_range(klines, lookback=24):
    closed = klines[:-1]
    if len(closed) < lookback: return None, None
    w = closed[-lookback:]
    return max(k["high"] for k in w), min(k["low"] for k in w)

def detect_fakeout(klines, rh, rl):
    if len(klines) < 30: return None
    last = klines[-2]
    vols = [k["volume"] for k in klines[:-1]]
    vol_sma = sma(vols, 20)
    vol_spike = vol_sma and last["volume"] > VOL_SPIKE_MULTIPLIER * vol_sma
    if rh and last["high"] > rh and last["close"] < rh and vol_spike:
        return ("Bearish", rh, last, vol_sma)
    if rl and last["low"] < rl and last["close"] > rl and vol_spike:
        return ("Bullish", rl, last, vol_sma)
    return None

def send_tg(msg):
    if not TG or not TELEGRAM_CHAT_ID:
        print("[DRY]", msg); return
    try:
        r = requests.post(f"{TG}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10)
        if r.status_code != 200: print("TG error:", r.text)
    except Exception as e: print("TG exc:", e)

def main():
    send_tg("✅ <b>BTC 1H bot started</b>")
    last_ts = None
    while True:
        try:
            k = fetch_klines(SYMBOL, INTERVAL, 200)
            rh, rl = compute_range(k, RANGE_LOOKBACK)
            fake = detect_fakeout(k, rh, rl)
            if fake:
                side, lvl, last, vsma = fake
                if last_ts != last["close_time"]:
                    msg = (f"🚨 <b>BTC 1H {side} Fakeout</b>\n"
                           f"Level: ${lvl:,.0f}\n"
                           f"Close: ${last['close']:,.0f} | High: ${last['high']:,.0f} | Low: ${last['low']:,.0f}\n"
                           f"Vol: {last['volume']:,.0f} vs 20SMA {vsma:,.0f}\n"
                           "Bias: Setup forming – wait for retest.")
                    send_tg(msg)
                    last_ts = last["close_time"]
        except Exception as e:
            send_tg(f"❗Error: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()

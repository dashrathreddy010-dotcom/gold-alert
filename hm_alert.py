"""
Hilega-Milega + 9/15 EMA  ->  Telegram alerts for XAU/USD 4H

BUY  : EMA3(RSI9) crosses ABOVE WMA21(RSI9)  AND close > EMA9 AND close > EMA15
EXIT : EMA3(RSI9) crosses BELOW WMA21(RSI9)  (only if a BUY is open)

Setup:
    pip install requests pandas numpy
    set environment variables:
        TWELVEDATA_KEY   (free key from twelvedata.com)
        TELEGRAM_TOKEN   (from @BotFather)
        TELEGRAM_CHAT_ID (your chat id)

Run:
    python hm_alert.py --test     # sends a test message to Telegram
    python hm_alert.py --check    # prints the latest signal state, no alert
    python hm_alert.py            # runs forever, checks every 5 minutes
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

# ---------------- SETTINGS ----------------
SYMBOL = "XAU/USD"
INTERVAL = "4h"
RSI_LEN = 9
CANDLES = 500            # enough history for RSI/EMA to settle
CHECK_EVERY_SEC = 300    # 5 minutes
STATE_FILE = "hm_state.json"
SEND_EXIT_ALERTS = True

TD_KEY = os.getenv("TWELVEDATA_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


# ---------------- DATA ----------------
def fetch_candles() -> pd.DataFrame:
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "outputsize": CANDLES,
            "timezone": "UTC",
            "apikey": TD_KEY,
        },
        timeout=20,
    )
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"Data error: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df["close"] = df["close"].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)

    # drop the still-forming candle (only closed candles count)
    now = datetime.now(timezone.utc)
    bar = timedelta(hours=4)
    df = df[df["datetime"] + bar <= now].reset_index(drop=True)
    return df


# ---------------- INDICATORS (same as Pine) ----------------
def pine_rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()   # Wilder RMA
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def pine_wma(series: pd.Series, length: int) -> pd.Series:
    w = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def pine_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    rsi = pine_rsi(df["close"], RSI_LEN)
    wma21 = pine_wma(rsi, 21)
    ema3 = pine_ema(rsi, 3)
    ema9 = pine_ema(df["close"], 9)
    ema15 = pine_ema(df["close"], 15)

    cross_up = (ema3 > wma21) & (ema3.shift(1) <= wma21.shift(1))
    cross_dn = (ema3 < wma21) & (ema3.shift(1) >= wma21.shift(1))

    df["rsi"], df["wma21"], df["ema3"] = rsi, wma21, ema3
    df["ema9"], df["ema15"] = ema9, ema15
    df["buy"] = cross_up & (df["close"] > ema9) & (df["close"] > ema15)
    df["exit"] = cross_dn
    return df


# ---------------- TELEGRAM ----------------
def send_telegram(text: str):
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"},
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram error: {r.text}")


# ---------------- STATE ----------------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_candle": None, "in_position": False}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ---------------- MAIN LOGIC ----------------
def check_once(send: bool = True):
    df = add_signals(fetch_candles())
    last = df.iloc[-1]
    candle_id = last["datetime"].isoformat()
    close_time = (last["datetime"] + timedelta(hours=4)).strftime("%d %b %H:%M UTC")

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] candle {candle_id} | "
        f"close {last['close']:.2f} | buy={bool(last['buy'])} exit={bool(last['exit'])}"
    )

    if not send:
        return

    state = load_state()
    if state["last_candle"] == candle_id:
        return  # already handled this candle

    if last["buy"] and not state["in_position"]:
        send_telegram(
            f"🟢 <b>BUY SIGNAL - XAUUSD 4H</b>\n"
            f"Price: <b>{last['close']:.2f}</b>\n"
            f"Candle closed: {close_time}\n"
            f"HM green crossed above red, price above EMA 9 & 15"
        )
        state["in_position"] = True

    elif last["exit"] and state["in_position"]:
        if SEND_EXIT_ALERTS:
            send_telegram(
                f"🔴 <b>EXIT SIGNAL - XAUUSD 4H</b>\n"
                f"Price: <b>{last['close']:.2f}</b>\n"
                f"Candle closed: {close_time}\n"
                f"HM green crossed below red"
            )
        state["in_position"] = False

    state["last_candle"] = candle_id
    save_state(state)


def main():
    if "--test" in sys.argv:
        send_telegram("✅ Test alert: your XAUUSD Hilega-Milega bot is connected.")
        print("Test message sent.")
        return
    if "--check" in sys.argv:
        check_once(send=False)
        return

    print("Bot running. Press Ctrl+C to stop.")
    while True:
        try:
            check_once()
        except Exception as e:
            print("Error:", e)
        time.sleep(CHECK_EVERY_SEC)


if __name__ == "__main__":
    main()

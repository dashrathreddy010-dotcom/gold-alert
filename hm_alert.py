"""
Hilega-Milega + 9/15 EMA -> Telegram alerts for XAU/USD 4H  (GitHub Actions version)

BUY  : EMA3(RSI9) crosses ABOVE WMA21(RSI9) AND close > EMA9 AND close > EMA15
EXIT : EMA3(RSI9) crosses BELOW WMA21(RSI9) (only if a BUY is open)

Secrets needed: TWELVEDATA_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

SYMBOL = "XAU/USD"
INTERVAL = "4h"
RSI_LEN = 9
CANDLES = 500
STATE_FILE = "hm_state.json"
SEND_EXIT_ALERTS = True
MAX_AGE_MIN = 90   # ignore signals older than this (avoids stale alerts)

TD_KEY = os.getenv("TWELVEDATA_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


def fetch_candles() -> pd.DataFrame:
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": SYMBOL, "interval": INTERVAL, "outputsize": CANDLES,
                "timezone": "UTC", "apikey": TD_KEY},
        timeout=30,
    )
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"Data error: {data}")
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df["close"] = df["close"].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)
    now = datetime.now(timezone.utc)
    df = df[df["datetime"] + timedelta(hours=4) <= now].reset_index(drop=True)  # closed candles only
    return df


def pine_rsi(s, n):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l)


def pine_wma(s, n):
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def pine_ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def add_signals(df):
    rsi = pine_rsi(df["close"], RSI_LEN)
    wma21 = pine_wma(rsi, 21)
    ema3 = pine_ema(rsi, 3)
    ema9 = pine_ema(df["close"], 9)
    ema15 = pine_ema(df["close"], 15)
    up = (ema3 > wma21) & (ema3.shift(1) <= wma21.shift(1))
    dn = (ema3 < wma21) & (ema3.shift(1) >= wma21.shift(1))
    df["buy"] = up & (df["close"] > ema9) & (df["close"] > ema15)
    df["exit"] = dn
    return df


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram error: {r.text}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_candle": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def main():
    if "--test" in sys.argv:
        send_telegram("✅ Test alert: your XAUUSD Hilega-Milega bot is connected (GitHub).")
        print("Test message sent.")
        return

    df = add_signals(fetch_candles())

    # Replay the strategy on history to know if a BUY is currently open
    in_pos = False
    for i in range(len(df) - 1):
        if df.loc[i, "buy"] and not in_pos:
            in_pos = True
        elif df.loc[i, "exit"] and in_pos:
            in_pos = False

    last = df.iloc[-1]
    candle_id = last["datetime"].isoformat()
    closed_at = last["datetime"] + timedelta(hours=4)
    age_min = (datetime.now(timezone.utc) - closed_at).total_seconds() / 60
    print(f"Last closed candle {candle_id} | close {last['close']:.2f} | "
          f"buy={bool(last['buy'])} exit={bool(last['exit'])} | in_position_before={in_pos}")

    if "--check" in sys.argv:
        return

    state = load_state()
    if state["last_candle"] == candle_id:
        print("Already handled this candle.")
        return
    if age_min > MAX_AGE_MIN:
        print("Candle too old, skipping.")
        return

    when = closed_at.strftime("%d %b %H:%M UTC")
    if last["buy"] and not in_pos:
        send_telegram(
            f"🟢 <b>BUY SIGNAL - XAUUSD 4H</b>\n"
            f"Price: <b>{last['close']:.2f}</b>\n"
            f"Candle closed: {when}\n"
            f"HM green crossed above red, price above EMA 9 & 15"
        )
        print("BUY alert sent.")
    elif last["exit"] and in_pos and SEND_EXIT_ALERTS:
        send_telegram(
            f"🔴 <b>EXIT SIGNAL - XAUUSD 4H</b>\n"
            f"Price: <b>{last['close']:.2f}</b>\n"
            f"Candle closed: {when}\n"
            f"HM green crossed below red"
        )
        print("EXIT alert sent.")

    state["last_candle"] = candle_id
    save_state(state)


if __name__ == "__main__":
    main()

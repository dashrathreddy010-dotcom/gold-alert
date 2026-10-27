"""
Hilega-Milega + 9/15 EMA -> Telegram alerts for XAU/USD DAILY

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
INTERVAL = "1day"
BAR = timedelta(days=1)
RSI_LEN = 9
CANDLES = 500
STATE_FILE = "hm_state_1d.json"
SEND_EXIT_ALERTS = True
MAX_AGE_MIN = 180   # ignore signals older than this

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
    df = df[df["datetime"].dt.dayofweek != 6].reset_index(drop=True)  # drop Sunday stub bars
    now = datetime.now(timezone.utc)
    df = df[df["datetime"] + BAR <= now].reset_index(drop=True)  # closed candles only
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
        send_telegram("✅ Test alert: your XAUUSD DAILY Hilega-Milega bot is connected (GitHub).")
        print("Test message sent.")
        return

    df = add_signals(fetch_candles())
    last = df.iloc[-1]
    print(f"Last closed 1D candle {last['datetime'].isoformat()} | close {last['close']:.2f} | "
          f"buy={bool(last['buy'])} exit={bool(last['exit'])}")

    if "--check" in sys.argv:
        return

    # Replay the strategy over history to list every BUY/EXIT event in order
    in_pos = False
    events = []
    for i in range(len(df)):
        row = df.iloc[i]
        if row["buy"] and not in_pos:
            in_pos = True
            events.append(("BUY", row))
        elif row["exit"] and in_pos:
            in_pos = False
            events.append(("EXIT", row))

    state = load_state()
    last_done = pd.Timestamp(state["last_candle"]) if state["last_candle"] else None
    now = datetime.now(timezone.utc)
    sent = 0

    for kind, row in events:
        if last_done is not None and row["datetime"] <= last_done:
            continue  # already handled in an earlier run
        closed_at = row["datetime"] + BAR
        if (now - closed_at).total_seconds() / 60 > MAX_AGE_MIN:
            continue  # too old
        when = closed_at.strftime("%d %b %H:%M UTC")
        if kind == "BUY":
            send_telegram(
                f"🟢 <b>BUY SIGNAL - XAUUSD 1D</b>\n"
                f"Price: <b>{row['close']:.2f}</b>\n"
                f"Candle closed: {when}\n"
                f"HM green crossed above red, price above EMA 9 & 15"
            )
            sent += 1
        elif SEND_EXIT_ALERTS:
            send_telegram(
                f"🔴 <b>SELL (EXIT) SIGNAL - XAUUSD 1D</b>\n"
                f"Price: <b>{row['close']:.2f}</b>\n"
                f"Candle closed: {when}\n"
                f"HM green crossed below red"
            )
            sent += 1

    print(f"Alerts sent this run: {sent}")
    state["last_candle"] = last["datetime"].isoformat()
    state["recent"] = [f"{r.datetime:%Y-%m-%d %a %H:%M} {r.close:.2f}" for r in df.tail(8).itertuples()]
    save_state(state)


if __name__ == "__main__":
    main()

"""Diagnostic: show what the bot sees on each timeframe (signals, recent candles, indicator values)."""
import os, sys
from datetime import timedelta, timezone
import pandas as pd
import hm_alert_1h as h1, hm_alert_15m as h15, hm_alert_1d as h1d
import numpy as np
import requests, time

IST = timezone(timedelta(hours=5, minutes=30))
out = []

def analyse(label, mod):
    df = mod.fetch_candles()
    df = mod.add_signals(df)
    rsi = mod.pine_rsi(df["close"], mod.RSI_LEN)
    ema3 = mod.pine_ema(rsi, 3); wma21 = mod.pine_wma(rsi, 21)
    ema9 = mod.pine_ema(df["close"], 9); ema15 = mod.pine_ema(df["close"], 15)
    in_pos = False; events = []
    for i in range(len(df)):
        r = df.iloc[i]
        if r["buy"] and not in_pos: in_pos = True; events.append(("BUY", i))
        elif r["exit"] and in_pos: in_pos = False; events.append(("EXIT", i))
    out.append(f"===== {label} =====  candles={len(df)}  position_open_now={in_pos}")
    out.append("last 8 BUY/EXIT events (candle CLOSE time):")
    for k, i in events[-8:]:
        ct = df.iloc[i]["datetime"] + mod.BAR
        out.append(f"  {k:4s} closed {ct:%Y-%m-%d %H:%M} UTC = {ct.astimezone(IST):%d %b %H:%M} IST  close={df.iloc[i]['close']:.2f}")
    out.append("last 8 candles: close | ema3(rsi) | wma21(rsi) | ema9 | ema15 | buy exit")
    for i in range(max(0, len(df) - 8), len(df)):
        r = df.iloc[i]; ct = r["datetime"] + mod.BAR
        out.append(f"  closed {ct:%m-%d %H:%M}UTC | {r['close']:.2f} | {ema3.iloc[i]:.2f} | {wma21.iloc[i]:.2f} | {ema9.iloc[i]:.2f} | {ema15.iloc[i]:.2f} | {bool(r['buy'])} {bool(r['exit'])}")
    out.append("")

for label, mod in (("1H", h1), ("15M", h15)):
    try:
        analyse(label, mod)
    except Exception as e:
        out.append(f"{label} error: {e}")
    time.sleep(9)
open("diag_output.txt", "w").write("\n".join(out))
print("\n".join(out))

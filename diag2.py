"""Diagnostic 2: (1) how fragile was the 1H BUY at 11:00 UTC, (2) does Twelve Data revise a candle's close after it closes?"""
import os, time, math, requests
import numpy as np, pandas as pd
from datetime import datetime, timezone
import hm_alert_1h as h1

out = []
def log(s): print(s, flush=True); out.append(s)

# ---------- (1) sensitivity of the 11:00 UTC 1H BUY ----------
df = h1.fetch_candles()
idx = df.index[df["datetime"] == pd.Timestamp("2026-10-27 10:00", tz="UTC")]
if len(idx):
    i = idx[0]
    base = df.copy()
    flip = None
    for d in np.arange(0, 6.01, 0.05):
        t = base.copy(); t.loc[i:, "close"] = t.loc[i:, "close"].values  # keep later closes unchanged
        t.loc[i, "close"] = base.loc[i, "close"] - d
        s = h1.add_signals(t)
        if not bool(s.loc[i, "buy"]):
            flip = round(d, 2); break
    log(f"1H BUY candle (closed 11:00 UTC) real close={base.loc[i,'close']:.2f}. "
        f"Signal disappears if the close were just ${flip} lower (price fell by that much)." )
else:
    log("11:00 candle not found")
time.sleep(9)

# ---------- (2) revision sampling around the next 15m close ----------
def raw(n=3):
    r = requests.get("https://api.twelvedata.com/time_series",
        params={"symbol":"XAU/USD","interval":"15min","outputsize":n,"timezone":"UTC","apikey":os.environ["TWELVEDATA_KEY"]}, timeout=30).json()
    return r.get("values", r)

now = time.time()
boundary = (int(now)//900 + 1)*900
if boundary - now < 45: boundary += 900
log(f"waiting for 15m close at {datetime.fromtimestamp(boundary, timezone.utc):%H:%M:%S} UTC (now {datetime.fromtimestamp(now, timezone.utc):%H:%M:%S})")
time.sleep(max(0, boundary + 2 - time.time()))
for k in range(12):
    t0 = time.time()
    try:
        v = raw(3)
        rows = " || ".join(f"{x['datetime']} close={x['close']}" for x in v)
        log(f"+{t0-boundary:5.1f}s : {rows}")
    except Exception as e:
        log(f"+{t0-boundary:5.1f}s : error {e}")
    time.sleep(max(0, 15 - (time.time()-t0)))
open("diag2_output.txt","w").write("\n".join(out))

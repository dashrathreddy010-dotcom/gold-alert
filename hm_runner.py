"""
Always-on runner for the Hilega-Milega bots (15m, 4H, 1D; 1H is OFF).

Instead of waking up on GitHub's (slow, unreliable) cron, this job stays alive
for ~5h40m and wakes up by itself a few seconds after EVERY candle close.
The next job is queued by the workflow's concurrency group and starts the
moment this one ends.
"""

import os
import sys
import json
import time
import subprocess
import importlib
from datetime import datetime

import requests

RUN_MINUTES = float(os.getenv("RUN_MINUTES", "340"))   # how long this job lives
DELAY = 8          # seconds after candle close before the first check
RETRY_GAP = 12     # seconds between retries if the new candle isn't published yet
MAX_TRIES = 6      # tries per candle close
MIN_API_GAP = 8.5  # seconds between Twelve Data calls (free plan: 8 calls/minute)
NO_GIT = os.getenv("NO_GIT") == "1"


def now():
    return time.time()


def sleep(s):
    time.sleep(s)


def next_boundary(ts, step):
    """Next candle close (unix time) strictly after ts. Epoch is 00:00 UTC, so this aligns to UTC."""
    return (int(ts) // step + 1) * step


class Bot:
    def __init__(self, name, minutes, mod=None):
        self.name = name
        self.step = minutes * 60
        self.mod = mod or importlib.import_module(name)
        self.misses = 0
        orig = self.mod.send_telegram

        def wrapped(text, _orig=orig):
            _orig(text)
            print(f"[{self.name}] ALERT SENT", flush=True)
        self.mod.send_telegram = wrapped


def read_last(bot):
    try:
        with open(bot.mod.STATE_FILE) as f:
            return datetime.fromisoformat(json.load(f)["last_candle"]).timestamp()
    except Exception:
        return 0.0


def call_main(bot):
    try:
        bot.mod.main()
    except Exception as e:
        print(f"[{bot.name}] error: {e}", flush=True)


def check_bot(bot, boundary):
    """Run the bot until the candle that just closed has been processed."""
    expected_start = boundary - bot.step
    tries = MAX_TRIES if bot.misses < 3 else 1   # market closed -> don't burn API calls
    for i in range(tries):
        call_main(bot)
        if read_last(bot) >= expected_start:
            bot.misses = 0
            return True
        if i < tries - 1:
            sleep(RETRY_GAP)
    bot.misses += 1
    return False


def commit_state(bots, msg):
    if NO_GIT:
        return
    files = [b.mod.STATE_FILE for b in bots if os.path.exists(b.mod.STATE_FILE)]
    try:
        subprocess.run(["git", "add", *files], check=False)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", msg], check=False, capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "--autostash"], check=False, capture_output=True)
        subprocess.run(["git", "push"], check=False, capture_output=True)
    except Exception as e:
        print("git error:", e, flush=True)


def run(bots):
    start = now()
    deadline = start + RUN_MINUTES * 60
    print(f"Runner started; will run {RUN_MINUTES:.0f} min", flush=True)

    # catch-up pass: picks up anything that closed while no runner was alive
    for b in bots:
        call_main(b)
    commit_state(bots, "state: catch-up")

    due = {b.name: next_boundary(now(), b.step) for b in bots}
    while True:
        b = min(bots, key=lambda x: due[x.name])
        trigger = due[b.name] + DELAY
        if trigger > deadline:
            break
        wait = trigger - now()
        if wait > 0:
            sleep(wait)
        ok = check_bot(b, due[b.name])
        print(f"[{b.name}] candle closing at {datetime.utcfromtimestamp(due[b.name]):%Y-%m-%d %H:%M} UTC "
              f"-> {'processed' if ok else 'no new candle'}", flush=True)
        commit_state(bots, f"state: {b.name}")
        nb = due[b.name] + b.step
        if nb + DELAY <= now():
            nb = next_boundary(now(), b.step)
        due[b.name] = nb

    commit_state(bots, "state: runner end")
    print("Runner finished (next job takes over).", flush=True)


def main():
    sys.argv = ["x"]
    orig_get = requests.get
    last = [0.0]

    def throttled_get(url, *a, **k):
        if "twelvedata" in str(url):
            wait = MIN_API_GAP - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
        return orig_get(url, *a, **k)

    requests.get = throttled_get
    # 1H bot is switched OFF on request (hm_alert_1h.py is still in the repo; re-add it here to turn it on)
    bots = [Bot("hm_alert_15m", 15), Bot("hm_alert", 240), Bot("hm_alert_1d", 1440)]
    run(bots)


if __name__ == "__main__":
    main()

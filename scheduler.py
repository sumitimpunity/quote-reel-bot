"""
scheduler.py - leave this running and it posts at each time in config.json "post_times".

    python scheduler.py

Adds a random 0-12 minute delay to each slot so posts don't look robotic.
If the computer was asleep and a slot was missed by more than 45 minutes, that slot is skipped
(better than dumping three reels at once when the laptop wakes up).
"""
import json, random, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def next_slot(cfg, tz, now):
    slots = []
    for day in (0, 1):
        d = (now + timedelta(days=day)).date()
        for t in cfg["post_times"]:
            h, m = map(int, t.split(":"))
            slots.append(datetime(d.year, d.month, d.day, h, m, tzinfo=tz))
    return min(s for s in slots if s > now)


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg["timezone"])
    print(f"Scheduler running. Slots: {', '.join(cfg['post_times'])} ({cfg['timezone']}). Ctrl+C to stop.")
    while True:
        now = datetime.now(tz)
        slot = next_slot(cfg, tz, now)
        fire_at = slot + timedelta(minutes=random.randint(0, 12))
        print(f"Next post at {fire_at:%a %d %b %H:%M}")
        while datetime.now(tz) < fire_at:
            time.sleep(min(60, max(1, (fire_at - datetime.now(tz)).total_seconds())))
        late = (datetime.now(tz) - fire_at).total_seconds() / 60
        if late > 45:
            print(f"Missed the {slot:%H:%M} slot by {late:.0f} min (computer asleep?) - skipping it.")
            continue
        subprocess.run([sys.executable, str(ROOT / "post_next.py")])
        # Reload config so edits to post_times take effect without a restart.
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

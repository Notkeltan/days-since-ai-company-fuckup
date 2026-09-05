#!/usr/bin/env python3
"""Post the counter's current state to Bluesky, and only to Bluesky.

    python scripts/seed_bluesky.py --dry-run
    python scripts/seed_bluesky.py

Bluesky came late: the account existed and was posting on X for over a week
before @dayssince.keltan.net was set up. post.py fans out to both platforms
together and refuses to post twice in a day, so there is no path through it that
catches Bluesky up without either double-posting on X or waiting for tomorrow.

This is that path, and it is deliberately one-way and one-off. It never touches
X, never writes state.json, and is dispatched by hand rather than scheduled -
the daily fan-out takes over from the next post.

Env: BSKY_HANDLE, BSKY_APP_PASSWORD (both required; the workflow supplies them).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import post as counter  # noqa: E402  - reuses the real templates and renderer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", help="override today's date (yyyy-mm-dd)")
    a = ap.parse_args()

    from datetime import date
    today = date.fromisoformat(a.today) if a.today else datetime.now(counter.TZ).date()

    incidents = counter.load_incidents()
    resetting = [i for i in incidents if i.resets]
    latest = resetting[-1]
    state = counter.load_state()

    done = counter.streaks(resetting)
    record = max((s[0] for s in done), default=None)
    if len(state.get("resets_seen", [])) < 2:
        record = None          # same gate as the daily post: no record until two
    days = max(0, (today - latest.date).days)

    censor = "incident" if latest.tone == "somber" else counter.CENSOR
    counter.NOUN = counter.noun_forms(censor)[1]
    last_label = f"{latest.date.isoformat()} · {latest.company}"

    prev = resetting[-2] if len(resetting) > 1 else None
    streak = (latest.date - prev.date).days if prev else 0
    text = counter.reset_text(latest, streak, record, days)

    counter.OUT.mkdir(exist_ok=True)
    img = counter.OUT / "reset.png"
    counter.render(days, record=record, last=last_label, last_title=latest.title,
                   handle=counter.HANDLE, censor=censor).save(img)
    alt = (f"Workplace-safety-style sign reading: This industry has gone {days} days "
           f"since the last major AI company {counter.NOUN}. "
           + (f"Previous record: {record} days. " if record is not None else "")
           + f"Last {counter.NOUN}: {last_label} — {latest.title}")

    print("─── would post to Bluesky ───")
    print(text)
    print(f"[image: {img}]")
    print("\n─── reply ───")
    print(counter.reply_text(latest))

    if a.dry_run:
        print("\ndry run; nothing sent")
        return

    if not (os.environ.get("BSKY_HANDLE") and os.environ.get("BSKY_APP_PASSWORD")):
        sys.exit("BSKY_HANDLE and BSKY_APP_PASSWORD must both be set")

    bsky = counter.BlueskyPoster()
    root = bsky.post(text, img, alt)
    print(f"\nposted: {root}")
    reply = bsky.post(counter.reply_text(latest), reply_to=root)
    print(f"reply : {reply}")


if __name__ == "__main__":
    main()

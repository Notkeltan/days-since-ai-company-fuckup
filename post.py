#!/usr/bin/env python3
"""Daily runner for the counter account.

    python post.py --dry-run          # print what would be posted, save preview PNGs
    python post.py                    # post for real (needs env vars below)
    python post.py --force            # post even if already posted today

Behaviour
---------
1. Reads incidents.yaml, finds the most recent `resets: true` entry.
2. If that entry's id differs from state.json → posts a RESET (streak ended),
   then a reply with the detail + source.
3. Otherwise posts the daily count with the sign image.
   If the current streak beats the previous record, says so.
4. Any tier-2 entries added since the last run get posted as an "honourable
   mention" reply under the day's post.
5. Writes state.json (commit it back in CI so tomorrow knows what happened).

Env vars (only needed without --dry-run)
----------------------------------------
X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET   # X: Consumer Key/Secret + Access Token/Secret (OAuth 1.0a, Read and Write)
BSKY_HANDLE, BSKY_APP_PASSWORD                             # optional: also post to Bluesky
COUNTER_TZ           default Australia/Sydney
COUNTER_HANDLE       shown small on the sign, e.g. @dayssinceailab
COUNTER_CENSOR       stars (default) | grawlix | bar | fup | stuffup | incident | none
                     — how the swear is rendered on the sign and in post text
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from render_sign import CENSOR_MODES, noun_forms, render

HERE = Path(__file__).resolve().parent
INCIDENTS = HERE / "incidents.yaml"
STATE = HERE / "state.json"
OUT = HERE / "out"

TZ = ZoneInfo(os.environ.get("COUNTER_TZ", "Australia/Sydney"))
HANDLE = os.environ.get("COUNTER_HANDLE", "")
CENSOR = os.environ.get("COUNTER_CENSOR", "stars")
if CENSOR not in CENSOR_MODES:
    sys.exit(f"COUNTER_CENSOR must be one of {list(CENSOR_MODES)}")
NOUN = noun_forms(CENSOR)[1]   # text form, e.g. "f**kup"; swapped to "incident" while a somber reset is current
MAX_LEN = 280


@dataclass
class Incident:
    id: str
    date: date
    company: str
    category: str
    tier: int
    resets: bool
    tone: str
    title: str
    detail: str
    source: str

    @classmethod
    def from_dict(cls, d: dict) -> "Incident":
        return cls(
            id=d["id"], date=_as_date(d["date"]), company=d["company"], category=d["category"],
            tier=int(d["tier"]), resets=bool(d["resets"]), tone=d.get("tone", "snark"),
            title=d["title"].strip(), detail=d.get("detail", "").strip(), source=d.get("source", "").strip(),
        )


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def load_incidents() -> list[Incident]:
    data = yaml.safe_load(INCIDENTS.read_text(encoding="utf-8"))
    items = [Incident.from_dict(d) for d in data["incidents"]]
    items.sort(key=lambda i: i.date)
    return items


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")


def days_word(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def streaks(resetting: list[Incident]) -> list[tuple[int, Incident, Incident]]:
    """(length, from, to) for every completed streak between resets."""
    out = []
    for a, b in zip(resetting, resetting[1:]):
        out.append(((b.date - a.date).days, a, b))
    return out


def clip(text: str, limit: int = MAX_LEN) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ── message templates ───────────────────────────────────────────────────────

def daily_text(days: int, record: int | None, is_new_record: bool, record_from: str | None) -> str:
    head = f"{days_word(days)} since the last major AI company {NOUN}."
    if record is None:
        return clip(head)
    if is_new_record:
        return clip(f"{head}\n\nThat's a new record. The previous best was {days_word(record)} ({record_from}).")
    if days > record:
        return clip(f"{head}\n\nStill a record. Previous best: {days_word(record)}.")
    return clip(f"{head}\n\nPrevious record: {days_word(record)}.")


def reset_text(inc: Incident, streak: int, record: int | None, days_now: int) -> str:
    if inc.tone == "somber":
        # No jokes, no record-keeping flourish, no image.
        return clip(f"Counter reset.\n\n{inc.company}: {inc.title}")
    if days_now:
        # Back-dated: incidents are dated to first disclosure, and the detector
        # can surface one days after the fact. Saying "reset to 0" then would be
        # a lie by a fortnight, so the post owns the gap instead.
        body = (f"Counter reset to {days_now}.\n\n{inc.company}: {inc.title}\n\n"
                f"First disclosed {inc.date.isoformat()}. The streak ended there, "
                f"at {days_word(streak)}.")
        if record is not None and streak <= record:
            body += f" Previous record stands at {days_word(record)}."
        elif record is not None:
            body += " That was a new record."
        return clip(body)
    body = f"Counter reset to 0.\n\n{inc.company}: {inc.title}\n\nStreak ended at {days_word(streak)}."
    if record is not None and streak <= record:
        body += f" Previous record stands at {days_word(record)}."
    elif record is not None and streak > record:
        body += f" That was a new record."
    return clip(body)


def reply_text(inc: Incident) -> str:
    parts = [p for p in (inc.detail, f"Source: {inc.source}" if inc.source else "") if p]
    return clip("\n\n".join(parts))


def mention_text(inc: Incident) -> str:
    return clip(f"Noted but not counter-resetting (tier 2): {inc.company} — {inc.title}\n\nSource: {inc.source}")


# ── posting backends ─────────────────────────────────────────────────────────

class Poster:
    def post(self, text: str, image: Path | None = None, alt: str = "", reply_to: str | None = None) -> str: ...


class DryRun(Poster):
    def __init__(self) -> None:
        self.n = 0

    def post(self, text, image=None, alt="", reply_to=None):
        self.n += 1
        print(f"\n─── POST #{self.n}" + (f" (reply to {reply_to})" if reply_to else "") + " ───")
        print(text)
        if image:
            print(f"[image: {image}]  alt: {alt}")
        return f"dry-{self.n}"


class XPoster(Poster):
    """X API v2 over OAuth 1.0a user context. Endpoints (all api.x.com):
         POST /2/media/upload   multipart, media_category=tweet_image
         POST /2/media/metadata alt text
         POST /2/tweets         text + media_ids (+ reply)
    Pay-per-use pricing (2026): post $0.015, post containing a URL $0.20,
    media metadata $0.005. Keep URLs out of the daily post."""
    API = "https://api.x.com/2"

    def __init__(self) -> None:
        import requests
        from requests_oauthlib import OAuth1
        k, s, t, ts = (os.environ[v] for v in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
        self.s = requests.Session()
        self.s.auth = OAuth1(k, s, t, ts)

    def _check(self, r):
        if r.status_code >= 300:
            raise RuntimeError(f"X API {r.status_code}: {r.text[:300]}")
        return r.json()

    def upload(self, image: Path, alt: str = "") -> str:
        with image.open("rb") as fh:
            r = self.s.post(f"{self.API}/media/upload",
                            files={"media": (image.name, fh, "image/png")},
                            data={"media_category": "tweet_image"})
        media_id = self._check(r)["data"]["id"]
        if alt:
            self._check(self.s.post(f"{self.API}/media/metadata",
                                    json={"id": media_id, "metadata": {"alt_text": {"text": alt[:1000]}}}))
        return media_id

    def post(self, text, image=None, alt="", reply_to=None):
        body: dict = {"text": text}
        if image:
            body["media"] = {"media_ids": [self.upload(image, alt)]}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        return self._check(self.s.post(f"{self.API}/tweets", json=body))["data"]["id"]


class BlueskyPoster(Poster):
    def __init__(self) -> None:
        from atproto import Client
        self.c = Client()
        self.c.login(os.environ["BSKY_HANDLE"], os.environ["BSKY_APP_PASSWORD"])
        self._refs: dict[str, tuple] = {}

    def post(self, text, image=None, alt="", reply_to=None):
        from atproto import models
        reply_ref = None
        if reply_to and reply_to in self._refs:
            root, parent = self._refs[reply_to]
            reply_ref = models.AppBskyFeedPost.ReplyRef(root=root, parent=parent)
        if image:
            r = self.c.send_image(text=text[:300], image=image.read_bytes(), image_alt=alt[:1000], reply_to=reply_ref)
        else:
            r = self.c.send_post(text=text[:300], reply_to=reply_ref)
        strong = models.create_strong_ref(r)
        root = self._refs[reply_to][0] if reply_to and reply_to in self._refs else strong
        self._refs[r.uri] = (root, strong)
        return r.uri


class Fanout(Poster):
    """Post to several backends; returns the first backend's id (X) for threading."""
    def __init__(self, backends: list[Poster]) -> None:
        self.b = backends
        self._map: dict[str, list[str]] = {}

    def post(self, text, image=None, alt="", reply_to=None):
        ids = []
        for i, be in enumerate(self.b):
            rt = self._map[reply_to][i] if reply_to and reply_to in self._map else None
            try:
                ids.append(be.post(text, image, alt, rt))
            except Exception as e:  # one platform failing shouldn't kill the other
                print(f"[warn] {type(be).__name__} failed: {e}", file=sys.stderr)
                ids.append(None)
        key = ids[0] or ids[1] or f"local-{len(self._map)}"
        self._map[key] = ids
        return key


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="post even if already posted today")
    ap.add_argument("--on-new", action="store_true",
                    help="push mode: post only if incidents.yaml actually gained something "
                         "(a new reset or a new tier-2 mention); edits to existing entries post nothing")
    ap.add_argument("--today", help="override today's date (yyyy-mm-dd) for testing")
    a = ap.parse_args()

    today = date.fromisoformat(a.today) if a.today else datetime.now(TZ).date()
    incidents = load_incidents()
    resetting = [i for i in incidents if i.resets]
    if not resetting:
        sys.exit("no resetting incidents in incidents.yaml")
    latest = resetting[-1]
    state = load_state()

    known_ids = set(state.get("known_ids", []))
    new_mentions = [i for i in incidents if i.tier == 2 and i.id not in known_ids and known_ids]
    is_reset = state.get("last_incident_id") not in (None, latest.id)

    # --on-new is what the push trigger uses. Any edit to incidents.yaml fires that
    # workflow, including typo fixes and confidence bumps, and those must stay silent.
    if a.on_new and not (is_reset or new_mentions):
        print("incidents.yaml changed but nothing new to announce")
        return

    posted_today = state.get("last_post_date") == today.isoformat()
    if posted_today and not (a.force or (a.on_new and (is_reset or new_mentions))):
        print("already posted today; use --force to override")
        return

    # The record line stays off until the account has watched two resets happen
    # for itself. Before that it would be quoting history it wasn't around for.
    # `resets_seen` counts the resets this account actually posted, including the
    # one going out right now.
    resets_seen = list(state.get("resets_seen", []))
    if is_reset and latest.id not in resets_seen:
        resets_seen.append(latest.id)
    show_record = len(resets_seen) >= 2

    done = streaks(resetting)
    record = max((s[0] for s in done), default=None) if show_record else None
    record_from = None
    if record is not None:
        rs = max(done, key=lambda s: s[0])
        record_from = f"{rs[1].date.isoformat()} → {rs[2].date.isoformat()}"
    days = max(0, (today - latest.date).days)  # future-dated entries count as day 0
    is_new_record = record is not None and days > record and not state.get("record_announced_for") == latest.id

    OUT.mkdir(exist_ok=True)
    if a.dry_run:
        poster: Poster = DryRun()
    else:
        backends: list[Poster] = [XPoster()]
        if os.environ.get("BSKY_HANDLE"):
            backends.append(BlueskyPoster())
        poster = Fanout(backends)

    last_label = f"{latest.date.isoformat()} · {latest.company}"
    # Somber rule: while the current reset is a somber one, the sign and the
    # captions say INCIDENT, not the swear. Reverts automatically at the next reset.
    global NOUN
    censor = "incident" if latest.tone == "somber" else CENSOR
    NOUN = noun_forms(censor)[1]
    if is_reset:
        # ── RESET ──
        prev = next(i for i in resetting if i.id == state["last_incident_id"])
        streak = (latest.date - prev.date).days
        prior_record = max((s[0] for s in done if s[2].id != latest.id), default=None) if show_record else None
        text = reset_text(latest, streak, prior_record, days)
        img = None
        alt = ""
        if latest.tone != "somber":
            img = OUT / "reset.png"
            # `days`, not 0 - the sign has to agree with the incident's date
            render(days, record=prior_record, last=last_label, last_title=latest.title, handle=HANDLE, censor=censor).save(img)
            alt = (f"Workplace-safety-style sign reading: This industry has gone {days} days since the last major AI company {NOUN}. "
                   + (f"Previous record: {prior_record} days. " if prior_record is not None else "")
                   + f"Last {NOUN}: {last_label} — {latest.title}")
        root = poster.post(text, img, alt)
        poster.post(reply_text(latest), reply_to=root)
        state["record_announced_for"] = None
    else:
        # ── DAILY ──
        text = daily_text(days, record, is_new_record, record_from)
        img = OUT / "sign.png"
        render(days, record=record, last=last_label, last_title=latest.title, handle=HANDLE, censor=censor).save(img)
        alt = (f"Workplace-safety-style sign reading: This industry has gone {days} days since the last major AI company {NOUN}. "
               + (f"Previous record: {record} days. " if record is not None else "")
               + f"Last {NOUN}: {last_label} — {latest.title}")
        root = poster.post(text, img, alt)
        if is_new_record:
            state["record_announced_for"] = latest.id

    for m in new_mentions:
        poster.post(mention_text(m), reply_to=root)

    state.update({
        "last_incident_id": latest.id,
        "last_post_date": today.isoformat(),
        "known_ids": sorted({i.id for i in incidents}),
        "resets_seen": resets_seen,
    })
    if not a.dry_run:
        save_state(state)
    else:
        print("\n[state would become]", json.dumps(state, indent=2))


if __name__ == "__main__":
    main()

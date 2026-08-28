#!/usr/bin/env python3
"""Daily autonomous incident detection.

    python detect.py --dry-run           # research, print findings, change nothing
    python detect.py                     # research, append qualifying entries
    python detect.py --replay f.json     # re-run the decision logic on a saved
                                         # model response, no API call (testing)

What it does
------------
Asks Claude Opus 5, at max reasoning effort with web search and web fetch, to
sweep for things a frontier AI company has had to apologise for since the last
entry in incidents.yaml. It is told to work like a desk editor, not a headline
reader: several classes of source, corroboration before belief, and an explicit
distinction between "one outlet reported it" and "it is established".

Whatever it returns is then put through `qualifies()` here in Python. The model
recommends; this file decides. A finding only reaches incidents.yaml if it
clears an evidence bar that is enforced in code, so a persuasive but thin
finding cannot talk its way onto the account. Everything else is written to
out/review.json for a human.

Env
---
ANTHROPIC_API_KEY     required
DETECTOR_MODE         auto (default) | review
                      review sends every finding to out/review.json instead of
                      appending, even ones that clear the bar.
DETECTOR_EFFORT       max (default) | xhigh | high | medium | low
DETECTOR_LOOKBACK     days of history to search (default 14)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
INCIDENTS = HERE / "incidents.yaml"
OUT = HERE / "out"

TZ = ZoneInfo(os.environ.get("COUNTER_TZ", "Australia/Sydney"))
# `or` rather than a get() default: an unset repo variable arrives from Actions
# as an empty string, not as an absent key, so a default would never apply.
MODE = os.environ.get("DETECTOR_MODE") or "auto"
EFFORT = os.environ.get("DETECTOR_EFFORT") or "max"
LOOKBACK = int(os.environ.get("DETECTOR_LOOKBACK") or 14)

if MODE not in ("auto", "review"):
    sys.exit(f"DETECTOR_MODE must be auto or review, got {MODE!r}")
if EFFORT not in ("low", "medium", "high", "xhigh", "max"):
    sys.exit(f"DETECTOR_EFFORT must be one of low/medium/high/xhigh/max, got {EFFORT!r}")

COMPANIES = ["OpenAI", "Anthropic", "Google DeepMind", "Meta", "xAI",
             "Microsoft", "DeepSeek", "Mistral", "Amazon", "Alibaba/Qwen"]
CATEGORIES = ["model_behaviour", "security_privacy", "governance",
              "deception", "safety_process", "misuse", "legal"]

MODEL = "claude-opus-5"


# ── the brief ────────────────────────────────────────────────────────────────

SYSTEM = f"""You find incidents for a public counter that tracks days since a
major AI company last did something it had to apologise for. The account's only
asset is being right and being even-handed. A single wrong entry costs it more
than a hundred missed ones, so a missed incident is a bad day and a false one is
the end of the account.

WHO COUNTS
Only organisations training frontier-scale models: {", ".join(COMPANIES)}.
Companies that ship AI products without training frontier models (Character.AI,
Replit, Perplexity, Cursor, and the like) do not count, however bad the story.

TIER 1 - resets the counter. Public, sourced, and one of:
  model_behaviour  a shipped model causing serious harm at scale, or pulled
  security_privacy user data exposed
  governance       safety team collapse, board crisis, NDA clawbacks - the
                   "responsible steward" story breaking
  deception        hidden system-prompt rules, benchmark chart crimes,
                   undisclosed breaches
  safety_process   an internal policy that permitted the harm
  misuse           BIG third-party misuse of the company's model: nation-state
                   actors, many victims, or the company itself has to disclose,
                   revoke or patch. Small-scale jailbreak content is not this.

TIER 2 - logged, does not reset. Real but smaller: a hallucinated legal
citation, one hostile output to one user, a vendor breach.

NEVER COUNTS
- Lawsuits, at any stage: filing, settlement, judgment. The counter tracks what
  these companies did, not what they were sued for. A lawsuit may be logged as
  tier 2 context but never resets. If the underlying conduct is independently
  documented, the conduct can count on its own merits.
- Capability announcements, benchmarks, funding, pricing, executive departures
  with no stated safety reason.
- Anything you could not source.

HOW TO WORK
Do not stop at what the news is carrying. Headlines lag, repeat each other, and
one outlet's mistake becomes five outlets' mistake within a day. Search several
different kinds of source and treat agreement between independent kinds as the
thing that makes a story real:
  - the company's own newsroom, blog, status page, changelog, threat-intel and
    incident write-ups - the strongest source there is, and often the only place
    a disclosure appears
  - regulators and enforcement: FTC, state attorneys general, Ofcom, the EU AI
    Office, data-protection authorities
  - security researchers and disclosure trackers publishing primary findings
  - technical press and wire services
  - practitioner communities where problems surface first: Hacker News, the
    relevant subreddits, researchers posting directly
Search each company by name against the current window, and search the window
generically too, so you are not only finding what you thought to look for.

WHAT COUNTS AS CORROBORATED
Two outlets rewriting the same wire story are ONE source. Independence means
different reporting, not different mastheads. An aggregator or content farm is
not a source. A source is PRIMARY if it is the company itself, a regulator, a
court or agency document, or the researcher who found the thing.

Distinguish clearly between: an allegation, a report by one outlet, a story
several independent outlets have confirmed, and something the company has
acknowledged. Say which one you have. If a story is a day old and thinly
sourced, say so and recommend holding rather than posting - it costs nothing to
catch it tomorrow.

DATING
Date every incident to its FIRST public disclosure: the earliest moment it was
visible to anyone outside the company. If a researcher posted it on the 3rd and
the press ran it on the 6th, the date is the 3rd. If a company disclosed in
November something it detected in September, the date is November - the counter
measures what the world could see, so it cannot start before disclosure. Where
first disclosure and wide coverage differ, say which is which in your reasoning.

TONE
Set tone "somber" for anything involving a death, a child, or abuse imagery.
Those posts drop the jokes entirely. If in doubt, somber.

Be conservative. Recommend "post" only for things you would defend in public
against the company's own comms team. Recommend "hold" for anything you believe
but cannot yet stand up, and say what would confirm it. Returning nothing is a
perfectly good answer and most days it is the right one."""

TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
    {
        "name": "submit_findings",
        "description": "Report the sweep's results. Call exactly once, at the end, "
                       "even when nothing was found (send an empty findings list).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "sweep_notes": {
                    "type": "string",
                    "description": "What you searched and what you deliberately ruled out. "
                                   "Read by a human when the sweep looks wrong.",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string",
                                     "description": "yyyy-mm-dd of FIRST public disclosure - the day it "
                                                    "first surfaced anywhere, not the day it happened and "
                                                    "not the day the press picked it up"},
                            "company": {"type": "string", "enum": COMPANIES},
                            "tier": {"type": "integer", "enum": [1, 2]},
                            "category": {"type": "string", "enum": CATEGORIES},
                            "tone": {"type": "string", "enum": ["snark", "somber"]},
                            "title": {"type": "string", "maxLength": 120,
                                      "description": "One line, at most 120 characters - it is rendered "
                                                     "on the sign, so write it short rather than letting "
                                                     "a good finding be rejected for length."},
                            "detail": {"type": "string",
                                       "description": "One sentence of context for the reply."},
                            "sources": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "url": {"type": "string"},
                                        "publisher": {"type": "string"},
                                        "primary": {"type": "boolean",
                                                    "description": "The company itself, a regulator, a court "
                                                                   "or agency document, or the researcher who "
                                                                   "found it"},
                                    },
                                    "required": ["url", "publisher", "primary"],
                                    "additionalProperties": False,
                                },
                            },
                            "independent_sources": {
                                "type": "integer",
                                "description": "How many of the sources are independently reported. "
                                               "Outlets rewriting one wire story count once.",
                            },
                            "establishment": {
                                "type": "string",
                                "enum": ["allegation", "single_report", "corroborated", "acknowledged"],
                            },
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "recommend": {"type": "string", "enum": ["post", "hold"]},
                            "reasoning": {
                                "type": "string",
                                "description": "Why it clears or fails the rubric, and for a hold, "
                                               "what would confirm it.",
                            },
                        },
                        "required": ["date", "company", "tier", "category", "tone", "title",
                                     "detail", "sources", "independent_sources", "establishment",
                                     "confidence", "recommend", "reasoning"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["sweep_notes", "findings"],
            "additionalProperties": False,
        },
    },
]


# ── incidents.yaml ───────────────────────────────────────────────────────────

def load() -> dict:
    return yaml.safe_load(INCIDENTS.read_text(encoding="utf-8"))


def known(data: dict) -> tuple[set[str], date]:
    """Existing ids, and the date of the most recent entry of any tier."""
    ids = {i["id"] for i in data["incidents"]}
    dates = [i["date"] if isinstance(i["date"], date) else date.fromisoformat(str(i["date"]))
             for i in data["incidents"]]
    return ids, max(dates)


def brief(data: dict, today: date) -> str:
    """What the account already knows, so the model doesn't re-report it."""
    recent = sorted(data["incidents"],
                    key=lambda i: str(i["date"]))[-25:]
    lines = [f"  {i['date']}  tier {i['tier']}  {i['company']}: {i['title']}" for i in recent]
    return (f"Today is {today.isoformat()}.\n\n"
            f"Report only incidents whose FIRST public disclosure falls between "
            f"{(today - timedelta(days=LOOKBACK)).isoformat()} and {today.isoformat()}. "
            f"Something that first surfaced before that window is old news, even if it is "
            f"being widely covered today.\n\n"
            f"Already logged, most recent {len(recent)} of {len(data['incidents'])} entries - "
            f"do not report these again, and do not report a fresh angle on one of them as "
            f"a new incident:\n" + "\n".join(lines))


def slug(company: str, title: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{company} {title}".lower()).strip("-")
    if len(base) > 48:
        base = base[:48].rsplit("-", 1)[0]
    s, n = base, 2
    while s in existing:
        s, n = f"{base}-{n}", n + 1
    return s


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def entry_yaml(f: dict, iid: str) -> str:
    src = "; ".join(s["url"] for s in f["sources"])
    return (f"\n  - id: {iid}\n"
            f"    date: {f['date']}\n"
            f"    company: {q(f['company'])}\n"
            f"    category: {f['category']}\n"
            f"    tier: {f['tier']}\n"
            f"    resets: {'true' if f['tier'] == 1 else 'false'}\n"
            f"    tone: {f['tone']}\n"
            f"    title: {q(f['title'])}\n"
            f"    detail: {q(f['detail'])}\n"
            f"    source: {q(src)}\n"
            f"    confidence: {f['confidence']}\n")


# ── the bar, enforced here rather than asked for ─────────────────────────────

def qualifies(f: dict, today: date, ids: set[str]) -> tuple[bool, str]:
    """The model recommends; this decides. Returns (ok, why not)."""
    if f.get("recommend") != "post":
        return False, "model recommended holding"
    if f.get("confidence") != "high":
        return False, f"confidence is {f.get('confidence')}"
    if f.get("establishment") not in ("corroborated", "acknowledged"):
        return False, f"only {f.get('establishment')}"
    if int(f.get("independent_sources", 0)) < 2:
        return False, f"{f.get('independent_sources')} independent source(s), need 2"
    if not any(s.get("primary") for s in f.get("sources", [])):
        return False, "no primary source"
    if f.get("company") not in COMPANIES:
        return False, f"{f.get('company')} is not a frontier company"
    if f.get("category") == "legal" and f.get("tier") == 1:
        return False, "lawsuits never reset"
    try:
        d = date.fromisoformat(f["date"])
    except (KeyError, ValueError):
        return False, "unparseable date"
    if d > today:
        return False, "dated in the future"
    if (today - d).days > 30:
        return False, "older than 30 days"
    if not all(str(s.get("url", "")).startswith("http") for s in f.get("sources", [])):
        return False, "a source is not a URL"
    if len(f.get("title", "")) > 120:
        return False, "title over 120 characters"
    if slug(f["company"], f["title"], set()) in ids:
        return False, "already logged"
    return True, ""


# ── the call ─────────────────────────────────────────────────────────────────

def research(prompt: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    kwargs = dict(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        tools=TOOLS,
        output_config={"effort": EFFORT},
        thinking={"type": "adaptive"},
        # A search sweep is dozens of server-tool round trips and every one
        # re-sends the whole accumulated conversation. The first metered run
        # billed 3.64M input tokens for a single sweep. Caching the growing
        # prefix is the one lever that costs nothing in quality.
        cache_control={"type": "ephemeral"},
        messages=[{"role": "user", "content": prompt}],
    )
    # Server-side refusal fallback: a safety classifier declining a sweep about
    # harm at AI companies would otherwise end the run. Dropped rather than
    # fatal if the installed SDK predates the parameter.
    # Degrade one optional parameter at a time rather than failing the sweep:
    # an SDK too old for any of these should still produce findings.
    attempts = [
        ("full", client.beta.messages.stream,
         dict(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)),
        ("without refusal fallback", client.messages.stream, dict(kwargs)),
        ("without prompt caching", client.messages.stream,
         {k: v for k, v in kwargs.items() if k != "cache_control"}),
    ]
    msg = None
    for label, call, params in attempts:
        try:
            with call(**params) as stream:
                msg = stream.get_final_message()
            break
        except TypeError as e:
            print(f"[warn] {label} rejected by this SDK ({e}); retrying reduced", file=sys.stderr)
    if msg is None:
        raise RuntimeError("every request shape was rejected; check the anthropic SDK version")

    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {getattr(msg, 'stop_details', None)}")
    for block in msg.content:
        if block.type == "tool_use" and block.name == "submit_findings":
            payload = dict(block.input)
            payload["_usage"] = {"input": msg.usage.input_tokens,
                                 "output": msg.usage.output_tokens}
            return payload
    raise RuntimeError(f"no submit_findings call (stop_reason={msg.stop_reason})")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="research but change nothing")
    ap.add_argument("--replay", help="decide over a saved response instead of calling the API")
    ap.add_argument("--today", help="override today's date (yyyy-mm-dd)")
    a = ap.parse_args()

    today = date.fromisoformat(a.today) if a.today else datetime.now(TZ).date()
    data = load()
    ids, newest = known(data)
    OUT.mkdir(exist_ok=True)

    if a.replay:
        result = json.loads(Path(a.replay).read_text(encoding="utf-8"))
    else:
        result = research(brief(data, today))
        (OUT / "detection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"sweep notes: {result.get('sweep_notes', '')}\n")
    findings = result.get("findings", [])
    if not findings:
        print("nothing found")
        (OUT / "review.json").write_text("[]", encoding="utf-8")
        return

    accepted, held = [], []
    for f in findings:
        ok, why = qualifies(f, today, ids)
        label = "ACCEPT" if ok else f"HOLD ({why})"
        print(f"[{label}] {f['date']} tier {f['tier']} {f['company']}: {f['title']}")
        print(f"         {f['independent_sources']} independent, {f['establishment']}, "
              f"{f['confidence']} confidence")
        print(f"         {f['reasoning']}")
        for s in f.get("sources", []):
            print(f"         - {'primary ' if s.get('primary') else '        '}{s['url']}")
        print()
        (accepted if ok else held).append(f)

    if MODE != "auto":
        held, accepted = held + accepted, []
        print(f"DETECTOR_MODE={MODE}: everything goes to review.")

    (OUT / "review.json").write_text(json.dumps(held, indent=2), encoding="utf-8")

    if a.dry_run:
        print(f"dry run: would append {len(accepted)}, hold {len(held)}")
        return

    if accepted:
        text = INCIDENTS.read_text(encoding="utf-8").rstrip("\n")
        for f in accepted:
            iid = slug(f["company"], f["title"], ids)
            ids.add(iid)
            text += "\n" + entry_yaml(f, iid)
        yaml.safe_load(text)  # must still parse before it touches disk
        INCIDENTS.write_text(text + "\n", encoding="utf-8")
        print(f"appended {len(accepted)} to incidents.yaml")
    print(f"{len(held)} held for review")


if __name__ == "__main__":
    main()

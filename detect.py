#!/usr/bin/env python3
"""Daily autonomous incident detection.

    python detect.py --dry-run           # research, print findings, change nothing
    python detect.py                     # research, append qualifying entries
    python detect.py --replay f.json     # re-run the decision logic on a saved
                                         # model response, no API call (testing)

What it does
------------
Feeds Claude Opus 5 the last few days of MIRI's AI StopWatch daily digest and
asks which items, if any, clear this counter's rubric.

No browsing of any kind: one request, one answer. Search cost $19.32 a sweep and
link-following cost $3.20; the digest alone is about $0.20. The trade is real
and deliberate - the model can no longer open the documents it cites, so the
brief tells it to treat the dispatch text as its only witness and to be harder
to convince as a result.

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
DETECTOR_EFFORT       high (default) | max | xhigh | medium | low
DETECTOR_LOOKBACK     days of digest to read (default 3)
DIGEST_FEED           the AI StopWatch daily-digest RSS feed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
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
EFFORT = os.environ.get("DETECTOR_EFFORT") or "high"
LOOKBACK = int(os.environ.get("DETECTOR_LOOKBACK") or 3)
DIGEST_FEED = os.environ.get("DIGEST_FEED") or "https://aistop.watch/feed?sectionId=380361"

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
Your input is the AI StopWatch daily digest, a newsroom run by analysts at the
Machine Intelligence Research Institute. Read every dispatch given to you in
full. It is a curated feed, not a search result: assume the editors already
judged these items worth writing up, and that your job is the different one of
deciding which of them clear this counter's rubric.

The digest has a point of view - it is written by people who think this
technology is dangerous. Your rubric does not change because of that. An item
written up with alarm can still be a capability announcement, a lawsuit, or a
company outside scope, and you should say so.

YOU CANNOT BROWSE
You have no search and no fetch. The dispatch text in front of you is the entire
evidence base, and you must not pretend otherwise. Never claim you read a
document you were only given a link to.

That changes what the source fields mean, so read this carefully. Mark a source
primary when the dispatch shows you the primary document's own content - quotes
it, or describes its specific contents closely enough that the reporting is
plainly derived from reading it. A bare link with no description of what is in
it is NOT a primary source you can count; it is a lead. Say in your reasoning
which words in the dispatch you are relying on.

Because you cannot check anything, be harder to convince than you would be with
the documents open. Claim "acknowledged" only where the dispatch shows the
company saying the thing itself. Where the dispatch is summarising other
people's reporting, that is at best "corroborated", and often "single_report".
When the dispatch is your only witness and it is thin, hold. Tomorrow's dispatch
costs nothing and often settles it.

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
"somber" means one specific thing: a real person died, a child was involved, or
abuse imagery. Those posts drop the sign, the swear and the record line, because
a joke over a body is indefensible.

It does not mean serious, alarming, or large. A breach, a rogue agent, a
governance collapse, a nation-state actor - all snark, however grave they are.
Reach for somber only when a named human being was harmed, and say in your
reasoning which of the three applies. Marking an ordinary corporate failure
somber wastes the one gesture the account has for the days that need it.

Be conservative. Recommend "post" only for things you would defend in public
against the company's own comms team. Recommend "hold" for anything you believe
but cannot yet stand up, and say what would confirm it. Returning nothing is a
perfectly good answer and most days it is the right one."""

TOOLS = [
    # No browsing at all. web_fetch reading three linked documents took one sweep
    # from ~20k input tokens to 594k, because every round trip resends what has
    # accumulated. With no server tools this is a single request: one prompt, one
    # answer. The digest text is the whole evidence base - see the brief.
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
                    "description": "Under 150 words. Which dispatches you read, and a bare "
                                   "list of what you ruled out with three or four words of "
                                   "reason each - 'lawsuit', 'out of scope', 'before the "
                                   "window'. No prose. Your per-finding reasoning is where "
                                   "the argument goes; this is only an index.",
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
                            # No maxLength here. Adding one to this strict schema
                            # coincided with the model emitting its whole tool
                            # call as text instead of structured input; the limit
                            # is stated in the description and checked in
                            # qualifies() instead.
                            "title": {"type": "string",
                                      "description": "One line, at most 120 characters - it is rendered "
                                                     "on the sign, so write it short rather than letting "
                                                     "a good finding be held back for length."},
                            "detail": {"type": "string",
                                       "description": "One sentence of context for the reply."},
                            "digest_url": {
                                "type": "string",
                                "description": "The AI StopWatch URL for this item - the "
                                               "aistop.watch/i/... section anchor if the dispatch "
                                               "shows one for it, otherwise the dispatch's own "
                                               "aistop.watch/p/... link from its header. This is "
                                               "the only link the post carries.",
                            },
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
                                "description": "Under 120 words. Why it clears or fails the rubric, "
                                               "which words in the dispatch you are relying on, and "
                                               "for a hold, what would confirm it.",
                            },
                        },
                        "required": ["date", "company", "tier", "category", "tone", "title",
                                     "detail", "digest_url", "sources", "independent_sources",
                                     "establishment", "confidence", "recommend", "reasoning"],
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


def fetch_digest(today: date) -> str:
    """The AI StopWatch daily digest, as plain text with its links preserved."""
    if "://" not in DIGEST_FEED or DIGEST_FEED.startswith("file://"):
        xml = Path(DIGEST_FEED.replace("file://", "")).read_text(encoding="utf-8", errors="replace")
    else:
        import requests
        r = requests.get(DIGEST_FEED, timeout=60,
                         headers={"User-Agent": "days-since-counter (github.com/Notkeltan)"})
        r.raise_for_status()
        xml = r.text
    return parse_digest(xml, today)


def parse_digest(xml: str, today: date) -> str:
    cutoff = today - timedelta(days=LOOKBACK)
    out = []
    for raw in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def field(tag: str) -> str:
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", raw, re.S)
            return m.group(1) if m else ""
        try:
            pub = parsedate_to_datetime(field("pubDate")).date()
        except (TypeError, ValueError):
            continue
        if pub < cutoff:
            continue
        body = field("content:encoded") or field("description")
        # Keep hrefs - the whole point is to follow them to a primary source.
        # Square brackets, not angle: the tag stripper below eats anything in <>.
        body = re.sub(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 [\1]", body, flags=re.S)
        # Image CDNs and licence boilerplate are never a source and each URL is
        # ~150 characters of noise the model has to read past.
        body = re.sub(r"\[https?://[^\]]*(?:substackcdn\.com|creativecommons\.org|/image/fetch/)[^\]]*\]",
                      "", body)
        body = re.sub(r"<(p|div|h[1-6]|li|br)[^>]*>", "\n", body)
        body = unescape(re.sub(r"<[^>]+>", "", body))
        body = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()
        link = field("link").strip()
        out.append(f"===== DISPATCH {pub.isoformat()} - {unescape(field('title'))} "
                   f"({link}) =====\n\n{body}")

    if not out:
        raise RuntimeError(f"no digest dispatches since {cutoff}; has the feed moved?")
    return "\n\n".join(reversed(out))


def brief(data: dict, today: date, digest: str) -> str:
    """What the account already knows, plus the digest to judge."""
    recent = sorted(data["incidents"], key=lambda i: str(i["date"]))[-25:]
    lines = [f"  {i['date']}  tier {i['tier']}  {i['company']}: {i['title']}" for i in recent]
    return (
        f"Today is {today.isoformat()}.\n\n"
        f"Report only incidents whose FIRST public disclosure falls between "
        f"{(today - timedelta(days=LOOKBACK)).isoformat()} and {today.isoformat()}. "
        f"Something that first surfaced before that window is old news, even if it is "
        f"being written about today.\n\n"
        f"ALREADY LOGGED - the most recent {len(recent)} of {len(data['incidents'])} entries:\n"
        + "\n".join(lines) +
        "\n\nDo not report the same disclosure twice. But a later disclosure about an "
        "incident already on this list IS a new incident when it discloses something "
        "materially new in its own right - a postmortem showing the thing was far worse "
        "or wider than was known, or a company admitting a safeguard or process failure "
        "that was not part of the original story. Judge the new document on its own "
        "merits and date it to its own first disclosure. Do not wave something away as "
        "\"a fresh angle on an existing entry\" when the company has just admitted "
        "something new about itself.\n\n"
        "THE DIGEST FOLLOWS. Everything below is the source material.\n\n" + digest
    )


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
            f"    digest: {q(f.get('digest_url', ''))}\n"
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
        # No cache_control. It was added to survive the 3.6M-token search sweep;
        # the digest prompt is ~18k, so it buys almost nothing, and it was one of
        # two changes present on the run where the model returned its tool call
        # as text. Not worth carrying an unverified parameter for no gain.
        messages=[{"role": "user", "content": prompt}],
    )
    # Server-side refusal fallback: a safety classifier declining a sweep about
    # harm at AI companies would otherwise end the run. Dropped rather than
    # fatal if the installed SDK predates the parameter.
    attempts = [
        ("full", client.beta.messages.stream,
         dict(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)),
        ("without refusal fallback", client.messages.stream, dict(kwargs)),
    ]
    msg = None
    for label, call, params in attempts:
        try:
            with call(**params) as stream:
                msg = stream.get_final_message()
            break
        except TypeError as e:
            print(f"[warn] {label} rejected by this SDK ({e}); retrying reduced", file=sys.stderr)
        except anthropic.APIStatusError as e:
            # Say the useful thing rather than 40 lines of stream internals.
            detail = str(e)
            if "credit balance is too low" in detail:
                sys.exit("Anthropic credit balance is empty - top it up in the console. "
                         "The counter keeps posting; it just is not watching until then.")
            if e.status_code == 401:
                sys.exit("ANTHROPIC_API_KEY rejected (401). Check the secret.")
            if e.status_code == 429:
                sys.exit("Rate limited by the Anthropic API (429). Nothing posted; try later.")
            raise
    if msg is None:
        raise RuntimeError("every request shape was rejected; check the anthropic SDK version")

    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {getattr(msg, 'stop_details', None)}")
    for block in msg.content:
        if block.type == "tool_use" and block.name == "submit_findings":
            payload = dict(block.input)
            payload["_usage"] = {k: v for k, v in vars(msg.usage).items()
                                 if isinstance(v, int)}
            return salvage(payload)
    raise RuntimeError(f"no submit_findings call (stop_reason={msg.stop_reason})")


def salvage(payload: dict) -> dict:
    """Guard against a tool call that came back serialised into one field.

    Opus 5 has been seen packing the whole call into the first parameter as
    text - sweep_notes ending in `</sweep_notes><parameter name="findings">[...]`
    with findings empty. A detector that reports "nothing found" when it in fact
    found things is the worst failure this file can have, because it is
    indistinguishable from a quiet day. Recover if possible, and refuse to
    return a false all-clear if not.
    """
    notes = payload.get("sweep_notes", "")
    if payload.get("findings") or '<parameter name="findings"' not in notes:
        return payload
    m = re.search(r'<parameter name="findings">\s*(\[.*)', notes, re.S)
    if m:
        try:
            payload["findings"] = json.loads(m.group(1).strip())
            payload["sweep_notes"] = notes[:m.start()].replace("</sweep_notes>", "").strip()
            print(f"[warn] tool call came back as text; recovered "
                  f"{len(payload['findings'])} finding(s)", file=sys.stderr)
            return payload
        except json.JSONDecodeError as e:
            raise RuntimeError(f"tool call came back as text and would not parse: {e}")
    raise RuntimeError("tool call came back as text; refusing to report a false all-clear")


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
        result = research(brief(data, today, fetch_digest(today)))
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

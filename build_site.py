#!/usr/bin/env python3
"""Build the public site: a page anyone can read and JSON anyone can scrape.

    python build_site.py            # writes ./site
    python build_site.py --today 2026-09-02

Three files, all static, all served with CORS by GitHub Pages:

    index.html      the sign, the count, the rubric in brief
    current.json    the small one - just the number and the last incident
    data.json       everything, including the full incident history

The point of publishing the data is that the counter stops being something you
have to take the account's word for. Anyone can recompute the number from
incidents.yaml and disagree in public with the working shown.

Security note: every value that reaches the HTML goes through html.escape().
Incident titles are written by a model and by whoever files an issue, so they
are untrusted input as far as this file is concerned.
"""
from __future__ import annotations

import argparse
import csv
import os
import io
import json
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
REPO = "https://github.com/Notkeltan/days-since-ai-company-fuckup"
HANDLE = "@xRiskMemes"
# Custom domain for GitHub Pages, from the PAGES_DOMAIN repo variable.
#
# Deliberately opt-in and empty by default. A CNAME file in the artifact SETS
# the custom domain, and Pages then redirects the github.io URL to it - so
# shipping one before DNS resolves takes the live site down. Set the variable
# only once the DNS record actually answers.
DOMAIN = os.environ.get("PAGES_DOMAIN", "").strip()
SITE_URL = (f"https://{DOMAIN}" if DOMAIN
            else "https://notkeltan.github.io/days-since-ai-company-fuckup")

SCHEMA = 1


# ── SCP object classes ───────────────────────────────────────────────────────
# Flavour, not rubric. Nothing here affects the counter; it is derived from
# fields already in incidents.yaml so it is reproducible and argues with itself
# the same way every time.
#
# The classes are about how hard a thing is to CONTAIN, not how dangerous it is,
# which turns out to fit AI incidents almost too well. Safe does not mean
# harmless - it means understood and reliably held.

OBJECT_CLASSES = {
    "Safe": "Understood and reliably contained. Not the same as harmless.",
    "Euclid": "Insufficiently understood or inherently unpredictable; containment is not always reliable.",
    "Keter": "Exceedingly difficult to contain consistently. Usually because it is already out.",
    "Argus": "Contained by somebody other than the Foundation, who are deemed capable of it.",
    "Pending": "Not enough information to classify yet.",
    "Uncontained": "Not yet contained. Ongoing effort required to establish containment.",
}


def object_class(inc: dict, is_current: bool) -> str | None:
    """First match wins. Returns None where a joke would be indecent."""
    if inc["tone"] == "somber":
        return None          # the account's own rule: no jokes over a body
    if inc["confidence"] == "low":
        return "Pending"
    if inc["category"] == "legal":
        return "Argus"       # the courts have this one
    if is_current and inc["resets"]:
        return "Uncontained"
    if inc["tier"] == 2:
        return "Safe"
    if inc["category"] == "misuse":
        return "Keter"       # third parties have the model; it cannot be recalled
    return "Euclid"


def load(today: date) -> dict:
    data = yaml.safe_load((HERE / "incidents.yaml").read_text(encoding="utf-8"))
    incidents = []
    for i in data["incidents"]:
        d = i["date"] if isinstance(i["date"], date) else date.fromisoformat(str(i["date"]))
        incidents.append({
            "id": i["id"],
            "date": d.isoformat(),
            "company": i["company"],
            "category": i["category"],
            "tier": int(i["tier"]),
            "resets": bool(i["resets"]),
            "tone": i.get("tone", "snark"),
            "title": i["title"],
            "detail": i.get("detail", ""),
            # Older entries cite by name ("NYT, 2024-07-04") rather than by URL.
            # Both are kept: `sources` is what was recorded, `source_urls` is the
            # subset you can actually follow.
            "sources": [s.strip() for s in str(i.get("source", "")).split(";") if s.strip()],
            "source_urls": [s.strip() for s in str(i.get("source", "")).split(";")
                            if s.strip().startswith("http")],
            "digest": i.get("digest", ""),
            "confidence": i.get("confidence", "high"),
        })
    incidents.sort(key=lambda i: i["date"])

    resets = [i for i in incidents if i["resets"]]
    latest = resets[-1]
    days = max(0, (today - date.fromisoformat(latest["date"])).days)

    streaks = [
        {"days": (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days,
         "from": a["date"], "to": b["date"], "ended_by": b["id"]}
        for a, b in zip(resets, resets[1:])
    ]
    record = max(streaks, key=lambda s: s["days"]) if streaks else None

    for i in incidents:
        i["object_class"] = object_class(i, i["id"] == latest["id"])

    by_id = {i["id"]: i for i in incidents}
    for s in streaks:
        by_id[s["ended_by"]]["ended_streak_days"] = s["days"]

    def tally(items, key):
        out: dict[str, int] = {}
        for i in items:
            out[key(i)] = out.get(key(i), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "days_since_last_reset": days,
        "last_reset": latest,
        "longest_streak": record,
        "totals": {
            "incidents": len(incidents),
            "resets": len(resets),
            "resets_by_company": tally(resets, lambda i: i["company"]),
            "incidents_by_company": tally(incidents, lambda i: i["company"]),
            "by_category": tally(incidents, lambda i: i["category"]),
            "by_tier": tally(incidents, lambda i: f"tier {i['tier']}"),
            "by_year": tally(incidents, lambda i: i["date"][:4]),
            "by_confidence": tally(incidents, lambda i: i["confidence"]),
        },
        "streaks": streaks,
        "object_classes": {
            "note": "Flavour only, derived from the fields above. It has no bearing on "
                    "whether something resets the counter. Classes describe how hard a "
                    "thing is to contain, not how bad it is. Incidents marked somber get "
                    "no class - the account does not make jokes over those.",
            "definitions": OBJECT_CLASSES,
            "counts": tally([i for i in incidents if i["object_class"]],
                            lambda i: i["object_class"]),
        },
        # Stated explicitly because plenty of trackers quietly serve a rolling
        # window. This is every entry there has ever been, and nothing in this
        # file prunes by age. Each daily commit is also a dated snapshot, so the
        # git history reconstructs what the counter said on any past day.
        "coverage": {
            "complete": True,
            "rolling_window": False,
            "earliest": incidents[0]["date"] if incidents else None,
            "latest": incidents[-1]["date"] if incidents else None,
            "note": "Full history since the first logged entry. Nothing is aged out.",
        },
        "incidents": incidents,
        "licence": {
            "id": "CC-BY-SA-3.0",
            "url": "https://creativecommons.org/licenses/by-sa/3.0/",
            "note": "Same licence as the SCP Wiki, which is where the object classes "
                    "come from. Use it commercially if you like; credit the project, "
                    "link back, and license what you build under the same terms.",
            "attribution": "Days Since The Last Major AI Company F**kup by keltan",
        },
        "source_repo": REPO,
    }


def page(d: dict) -> str:
    e = escape
    latest = d["last_reset"]
    rec = d["longest_streak"]
    rows = "\n".join(
        f'      <tr><td>{e(i["date"])}</td><td>{e(i["company"])}</td>'
        f'<td>{"reset" if i["resets"] else "logged"}</td>'
        f'<td>{e(i["object_class"] or "—")}</td><td>{e(i["title"])}</td></tr>'
        for i in reversed(d["incidents"][-15:])
    )
    table = "\n".join(
        f"      <tr><td>{e(c)}</td><td>{n}</td></tr>"
        for c, n in d["totals"]["resets_by_company"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Days Since The Last Major AI Company F**kup</title>
<meta name="description" content="One number, once a day: days since a major AI company last did something it had to apologise for. Free, scrapeable JSON.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&amp;family=Oswald:wght@400;600&amp;display=swap" rel="stylesheet">
<style>
  :root {{ --cream:#f7f3e8; --ink:#121212; --red:#c41e1e; --grey:#6e6e6e; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--cream); color:var(--ink);
         font-family:Oswald,system-ui,sans-serif; line-height:1.55; }}
  .stripes {{ height:22px; background:repeating-linear-gradient(-45deg,
              #f5c518 0 24px,#121212 24px 48px); }}
  main {{ max-width:60rem; margin:0 auto; padding:2rem 1.25rem 4rem; }}
  h1 {{ font-family:Anton,Impact,sans-serif; font-size:clamp(1.8rem,5vw,3rem);
        line-height:1.05; margin:1.5rem 0 .25rem; text-transform:uppercase; }}
  h2 {{ font-family:Anton,Impact,sans-serif; text-transform:uppercase;
        margin:2.5rem 0 .5rem; font-size:1.4rem; }}
  .count {{ font-family:Anton,Impact,sans-serif; font-size:clamp(5rem,22vw,12rem);
            color:var(--red); line-height:.9; text-align:center;
            border:8px solid var(--red); background:#fff; padding:.1em .25em;
            display:block; width:fit-content; margin:1.5rem auto; }}
  .sub {{ text-align:center; color:var(--grey); text-transform:uppercase;
          letter-spacing:.04em; }}
  a {{ color:var(--red); }}
  table {{ border-collapse:collapse; width:100%; margin-top:.5rem; font-size:.95rem; }}
  th,td {{ text-align:left; padding:.4rem .6rem; border-bottom:1px solid #ddd;
           vertical-align:top; }}
  th {{ text-transform:uppercase; font-size:.8rem; color:var(--grey); }}
  code,pre {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.9rem; }}
  pre {{ background:#fff; border:1px solid #ddd; padding:.8rem; overflow-x:auto; }}
  .wrap {{ overflow-x:auto; }}
  footer {{ color:var(--grey); font-size:.9rem; margin-top:3rem; }}
</style>
<div class="stripes"></div>
<main>
  <p class="sub">This industry has gone</p>
  <span class="count">{d["days_since_last_reset"]}</span>
  <p class="sub">days since the last major AI company f**kup</p>

  <h1>Days since the last major AI company f**kup</h1>
  <p>One number, once a day, on <a href="https://x.com/{e(HANDLE.lstrip("@"))}">{e(HANDLE)}</a>.
     It resets when a frontier AI company does something it has to apologise for.
     Every entry has a primary source before it posts.</p>

  <p><strong>Last reset:</strong> {e(latest["date"])} &middot; {e(latest["company"])} &mdash;
     {e(latest["title"])}</p>
  {f'<p><strong>Longest streak on record:</strong> {rec["days"]} days ({e(rec["from"])} to {e(rec["to"])}).</p>' if rec else ""}

  <h2>Take the data</h2>
  <p>It is CC BY-SA 3.0. Scrape it, embed it, argue with it. Updated once a day, and the
     files are static with permissive CORS, so you can fetch them straight from a
     browser.</p>
  <div class="wrap"><table>
    <tr><th>File</th><th>What's in it</th></tr>
    <tr><td><a href="current.json">current.json</a></td><td>Just the number and the last reset. Small enough to poll.</td></tr>
    <tr><td><a href="data.json">data.json</a></td><td>Every entry since {e(d["coverage"]["earliest"])}, streaks, per-company totals. Complete history, never a rolling window.</td></tr>
    <tr><td><a href="sign.png">sign.png</a></td><td>Today's sign image, as posted.</td></tr>
  </table></div>
  <pre>curl -s {e(SITE_URL)}/current.json</pre>
  <p>Fields are documented in the repo. <code>schema</code> is versioned; it goes up
     if a field's meaning changes, never silently.</p>

  <h2>What counts</h2>
  <p>Frontier model trainers only. Tier 1 resets the counter: harm at scale from a
     shipped model, exposed user data, a governance or safety-team collapse,
     deception, an internal process that permitted the harm, or large-scale misuse
     of the company's model. Tier 2 is logged without resetting.</p>
  <p><strong>Lawsuits never reset it</strong>, at any stage. The counter tracks what
     these companies did, not what they were sued for. Nor do capability
     announcements, funding, pricing, or departures without a stated safety
     reason. Incidents are dated to first public disclosure.</p>
  <p>Where an incident involves a death, a child, or abuse imagery, the jokes come
     off: no sign, no swear.</p>
  <p>The full rubric, the code, and every entry are in
     <a href="{e(REPO)}">the repository</a>. If something here is wrong, open an
     issue with a source and it gets corrected.</p>

  <h2>Resets by company</h2>
  <div class="wrap"><table>
    <tr><th>Company</th><th>Resets</th></tr>
{table}
  </table></div>
  <p class="sub" style="text-align:left;text-transform:none">Counting {d["totals"]["resets"]} resets
     across {d["totals"]["incidents"]} logged entries. The table is the point: same
     rules for everyone, and the numbers fall where they fall.</p>

  <h2>Object classes</h2>
  <p>Flavour, borrowed from the <a href="https://scp-wiki.wikidot.com/object-classes">SCP
     Foundation</a> and derived mechanically from the fields above. It has no bearing on
     whether something resets the counter. The classes describe how hard a thing is to
     <em>contain</em>, not how bad it is &mdash; Safe does not mean harmless &mdash; which
     turns out to fit this subject uncomfortably well. Incidents marked somber get no
     class; the account does not make jokes over those.</p>
  <div class="wrap"><table>
    <tr><th>Class</th><th>Meaning</th></tr>
    <tr><td><strong>Safe</strong></td><td>{e(OBJECT_CLASSES["Safe"])}</td></tr>
    <tr><td><strong>Euclid</strong></td><td>{e(OBJECT_CLASSES["Euclid"])}</td></tr>
    <tr><td><strong>Keter</strong></td><td>{e(OBJECT_CLASSES["Keter"])}</td></tr>
    <tr><td><strong>Argus</strong></td><td>{e(OBJECT_CLASSES["Argus"])}</td></tr>
    <tr><td><strong>Pending</strong></td><td>{e(OBJECT_CLASSES["Pending"])}</td></tr>
    <tr><td><strong>Uncontained</strong></td><td>{e(OBJECT_CLASSES["Uncontained"])}</td></tr>
  </table></div>

  <h2>Recent entries</h2>
  <p>The fifteen most recent, for reading. The complete record &mdash; all
     {d["totals"]["incidents"]} entries back to {e(d["coverage"]["earliest"])} &mdash; is in
     <a href="data.json">data.json</a>. Nothing is ever aged out, and every daily
     commit in <a href="{e(REPO)}">the repo</a> is a dated snapshot, so you can
     reconstruct what the counter said on any past day.</p>
  <div class="wrap"><table>
    <tr><th>Date</th><th>Company</th><th>Effect</th><th>Class</th><th>What happened</th></tr>
{rows}
  </table></div>

  <footer>
    <p><a href="{e(d["licence"]["url"])}">CC BY-SA 3.0</a> &mdash; the same licence as the
       SCP Wiki. Take it, including commercially: credit
       &ldquo;{e(d["licence"]["attribution"])}&rdquo;, link back, and license what you
       build on it under the same terms.</p>
    <p>Generated {e(d["generated_at"])}. Run by
       <a href="https://x.com/Actuallykeltan">@Actuallykeltan</a>. Not affiliated with
       any of the companies listed, and not speaking for anyone's employer.</p>
  </footer>
</main>
<div class="stripes"></div>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="override today's date (yyyy-mm-dd)")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else datetime.now().date()

    d = load(today)
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    (SITE / "current.json").write_text(json.dumps({
        "schema": SCHEMA,
        "generated_at": d["generated_at"],
        "as_of": d["as_of"],
        "days_since_last_reset": d["days_since_last_reset"],
        "last_reset": {k: d["last_reset"][k] for k in ("id", "date", "company", "title")},
        "source_repo": REPO,
    }, indent=2) + "\n", encoding="utf-8")
    (SITE / "index.html").write_text(page(d), encoding="utf-8")

    # Flat CSV for the spreadsheet half of the world.
    cols = ["id", "date", "company", "category", "tier", "resets", "tone",
            "confidence", "ended_streak_days", "title", "detail", "digest", "sources"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for i in d["incidents"]:
        row = dict(i)
        row["sources"] = " | ".join(i["sources"])
        w.writerow(row)
    (SITE / "incidents.csv").write_text(buf.getvalue(), encoding="utf-8")

    # The counter's value for every day it has ever had one. This is the series
    # you would want to plot, and deriving it from resets is fiddly enough that
    # publishing it saves everyone the same small piece of work.
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "days_since_last_reset", "last_reset_id", "last_reset_company"])
    resets = [i for i in d["incidents"] if i["resets"]]
    start, cur = date.fromisoformat(resets[0]["date"]), today
    day, idx = start, 0
    while day <= cur:
        while idx + 1 < len(resets) and date.fromisoformat(resets[idx + 1]["date"]) <= day:
            idx += 1
        w.writerow([day.isoformat(), (day - date.fromisoformat(resets[idx]["date"])).days,
                    resets[idx]["id"], resets[idx]["company"]])
        day = date.fromordinal(day.toordinal() + 1)
    (SITE / "history.csv").write_text(buf.getvalue(), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    if DOMAIN:
        (SITE / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")

    sign = HERE / "out" / "sign.png"
    if sign.exists():
        (SITE / "sign.png").write_bytes(sign.read_bytes())

    print(f"site built: {d['days_since_last_reset']} days, "
          f"{d['totals']['incidents']} entries, {d['totals']['resets']} resets")


if __name__ == "__main__":
    main()

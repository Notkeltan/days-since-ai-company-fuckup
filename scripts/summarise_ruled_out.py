#!/usr/bin/env python3
"""Print a GitHub job summary for findings an existing ruling set aside.

    python scripts/summarise_ruled_out.py >> "$GITHUB_STEP_SUMMARY"

A finding matched to an entry in declined.yaml opens no review issue - that is
the whole point of the file. But "opens no issue" must not mean "reaches nobody":
a ruling that fires on the wrong story would then look exactly like a quiet day.
The run page is free to write to and free to read, so it goes there.

Silent by design when there is nothing to say, and it never fails its caller -
a broken summary must not be able to fail a sweep that otherwise worked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out" / "ruled-out.json"


def main() -> None:
    try:
        rows = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    except (OSError, ValueError) as e:
        print(f"> Could not read {OUT.name}: {e}")
        return
    if not rows:
        return
    print("### Set aside by an existing ruling\n")
    print(f"{len(rows)} finding(s) matched an entry in `declined.yaml` and were not "
          "re-raised. Nothing was posted and no review issue was opened. If one of "
          "these is wrong, the ruling is what needs changing.\n")
    print("| first disclosed | company | title |")
    print("|---|---|---|")
    for r in rows:
        cell = lambda v: str(v or "").replace("|", "\\|").replace("\n", " ")
        print(f"| {cell(r.get('date'))} | {cell(r.get('company'))} | {cell(r.get('title'))} |")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                     # never fail the sweep over a summary
        print(f"> Ruled-out summary failed: {e}", file=sys.stderr)

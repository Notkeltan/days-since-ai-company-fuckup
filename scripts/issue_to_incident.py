#!/usr/bin/env python3
"""Turn a GitHub issue-form body into an incidents.yaml entry.

    python scripts/issue_to_incident.py body.md    # prints the entry it appended

Issue forms render each field as "### <Label>\n\n<value>". Dropdowns give the
option text; empty fields give "_No response_".
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
INCIDENTS = HERE / "incidents.yaml"

LABELS = {"Date": "date", "Lab": "lab", "Tier": "tier", "Category": "category", "Tone": "tone",
          "Title": "title", "Detail": "detail", "Source URL": "source", "Confidence": "confidence"}


def parse(body: str) -> dict:
    fields = {}
    for m in re.finditer(r"^### (.+?)\s*\n+(.*?)(?=^### |\Z)", body, re.S | re.M):
        label, value = m.group(1).strip(), m.group(2).strip()
        if label in LABELS and value and value != "_No response_":
            fields[LABELS[label]] = value
    missing = [k for k in ("date", "lab", "tier", "category", "title", "detail", "source") if k not in fields]
    if missing:
        sys.exit(f"missing fields: {missing}")
    if date.fromisoformat(fields["date"]) > date.today():
        sys.exit("date is in the future")
    fields["tier"] = int(fields["tier"])
    fields.setdefault("tone", "snark")
    fields.setdefault("confidence", "high")
    return fields


def slug(lab: str, title: str, d: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{lab} {title}".lower()).strip("-")
    if len(base) > 48:
        base = base[:48].rsplit("-", 1)[0]
    existing = {i["id"] for i in yaml.safe_load(INCIDENTS.read_text())["incidents"]}
    s = base
    n = 2
    while s in existing:
        s = f"{base}-{n}"
        n += 1
    return s


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def main() -> None:
    body = Path(sys.argv[1]).read_text()
    f = parse(body)
    entry = (
        f"\n  - id: {slug(f['lab'], f['title'], f['date'])}\n"
        f"    date: {f['date']}\n"
        f"    lab: {q(f['lab'])}\n"
        f"    category: {f['category']}\n"
        f"    tier: {f['tier']}\n"
        f"    resets: {'true' if f['tier'] == 1 else 'false'}\n"
        f"    tone: {f['tone']}\n"
        f"    title: {q(f['title'])}\n"
        f"    detail: {q(f['detail'])}\n"
        f"    source: {q(f['source'])}\n"
        f"    confidence: {f['confidence']}\n"
    )
    text = INCIDENTS.read_text().rstrip("\n") + "\n" + entry
    yaml.safe_load(text)  # must still parse
    INCIDENTS.write_text(text)
    print(entry)


if __name__ == "__main__":
    main()

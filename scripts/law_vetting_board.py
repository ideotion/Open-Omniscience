#!/usr/bin/env python3
"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S6 of the law-vertical brief (2026-07-17): put every law-catalog row that needs a
maintainer decision on ONE page, so the whole backlog can be answered in a single pass
instead of a domain at a time.

    python3 scripts/law_vetting_board.py > docs/product/LAW_VETTING_BOARD.md
    python3 scripts/law_vetting_board.py --check      # counts only, for the guard

WHY THIS IS GENERATED AND NOT WRITTEN. A hand-typed decision table is exactly where a
cell gets back-filled: the shape has a slot for every intersection and an empty one
reads as an omission, so the format itself invites completing a row from memory. Every
cell here except the Decision column is copied from the catalog, and the guard in
tests/test_law_vetting_board.py re-derives the counts, so a row cannot describe a
source that is not there.

WHAT THE BUCKETS ARE AND ARE NOT. Buckets 1 and 2 are FACTS: they read
``verification.status`` and whether a row has a domain. Buckets 3 and 4 are a KEYWORD
TRIAGE over the catalog's own prose — a row lands there because its evidence or notes
contain a word like "robots" or "maintenance". That is a reading aid for a human, never
a verdict about a domain, which is why every row carries its evidence verbatim: the
maintainer is deciding from the sentence, not from the bucket. A triage keyword can
both over- and under-select, and the page says so rather than implying the list is
exhaustive.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guidance, not logic
    sys.exit("pyyaml is required: pip install pyyaml")

_ROOT = Path(__file__).resolve().parents[1]
GENERATED = _ROOT / "configs" / "legal_sources_generated.yml"
CURATED = _ROOT / "configs" / "legal_sources.yml"

#: Triage keywords, applied to a row's OWN evidence/notes/license_note. Deliberately
#: broad: a false positive costs the maintainer one glance at a verbatim sentence, a
#: false negative hides a domain that needs a decision.
BLOCKED_RE = re.compile(
    r"robots|bot[-\s]?wall|captcha|cloudflare|\b403\b|blocked|disallow|forbidden",
    re.I,
)
DOWN_RE = re.compile(
    r"maintenance|non[-\s]?functional|\bdown\b|offline|placeholder|\b409\b|"
    r"expired certificate|not resolve|unreachable",
    re.I,
)


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [s for s in (data.get("sources") or []) if isinstance(s, dict)]


def _prose(s: dict) -> str:
    """Every free-text field the producing session could have recorded a blocker in."""
    ver = s.get("verification") or {}
    parts = (ver.get("evidence"), s.get("notes"), s.get("license_note"))
    return " ".join(str(p) for p in parts if p)


def _evidence(s: dict) -> str:
    ver = s.get("verification") or {}
    text = str(ver.get("evidence") or s.get("notes") or "").strip()
    return " ".join(text.split())


def _cell(text: str, limit: int = 260) -> str:
    """Markdown-safe, length-bounded, and HONEST about the bound: a truncated cell says
    so, so nobody reads a clipped sentence as the whole record."""
    text = text.replace("|", "\\|").replace("\n", " ")
    if len(text) <= limit:
        return text or "—"
    return text[:limit].rstrip() + f"… [truncated, {len(text)} chars in the catalog]"


def classify(sources: list[dict]) -> dict[str, list[dict]]:
    """Pure. A row appears in AT MOST ONE bucket, in this order, so the page has no
    duplicate decisions: gap, lead, blocked, down."""
    buckets: dict[str, list[dict]] = {"gap": [], "lead": [], "blocked": [], "down": []}
    for s in sources:
        status = (s.get("verification") or {}).get("status")
        prose = _prose(s)
        if status == "lead" and not s.get("domain"):
            buckets["gap"].append(s)
        elif status == "lead":
            buckets["lead"].append(s)
        elif BLOCKED_RE.search(prose):
            buckets["blocked"].append(s)
        elif DOWN_RE.search(prose):
            buckets["down"].append(s)
    for v in buckets.values():
        v.sort(key=lambda s: (str(s.get("country") or ""), str(s.get("domain") or "")))
    return buckets


_SECTIONS = [
    (
        "gap",
        "1. Confirmed gaps — nothing to fetch, only to acknowledge",
        "A `lead` row with **no domain**: the producing session looked and found no "
        "official portal at all, and recorded the absence rather than inventing one. "
        "These need no adapter and no fetch; the decision is whether the record stands.",
        "Stands as a gap? / re-open",
    ),
    (
        "lead",
        "2. Unverified leads — a real domain nobody loaded",
        "A `lead` row **with** a domain: the URL was found but never fetched, so it "
        "ships disabled and no document under it is watched. Each is one of: enable it, "
        "route it through an adapter, or record it as a gap.",
        "Enable / adapter / gap / drop",
    ),
    (
        "blocked",
        "3. Access-blocked or bot-walled — cannot be scraped fail-closed",
        "The row's own prose mentions robots, a bot wall, a CAPTCHA or a 403. This "
        "project never evades a block, so scraping is off the table by ruling: each of "
        "these is either an adapter/API path or an honest gap. Read the evidence column "
        "— the bucket is a keyword triage, not a finding.",
        "Adapter / API / honest gap",
    ),
    (
        "down",
        "4. Recorded as down or non-functional",
        "The row's prose says the site was unreachable, in maintenance or serving a "
        "placeholder when it was checked. A dated observation ages; the decision is "
        "whether to re-check, park or drop.",
        "Re-check / park / drop",
    ),
]


def render(sources: list[dict], *, as_of: str) -> str:
    buckets = classify(sources)
    total = sum(len(v) for v in buckets.values())
    out: list[str] = []
    out.append("# Law vetting board — every catalog row awaiting a maintainer decision")
    out.append("")
    out.append(
        "> **Generated** by `scripts/law_vetting_board.py` from "
        "`configs/legal_sources_generated.yml` + `configs/legal_sources.yml`. Do not "
        "hand-edit: re-run the script. Every cell but **Decision** is copied from the "
        "catalog, and `tests/test_law_vetting_board.py` re-derives the counts, so no "
        "row here can describe a source that is not in the file."
    )
    out.append(">")
    out.append(
        f"> **{total} rows need a decision** out of {len(sources)} catalog sources "
        f"(catalog `as_of` {as_of}). Sections 1 and 2 are facts read off "
        "`verification.status`; sections 3 and 4 are a **keyword triage** over the "
        "catalog's own evidence and notes, offered so the backlog can be scanned in one "
        "pass. A triage keyword both over- and under-selects, so these two sections are "
        "a starting point and not an exhaustive list of blocked or dead domains."
    )
    out.append(">")
    out.append(
        "> Nothing here is scraped around. A host's robots refusal or bot wall is that "
        "host's choice; the only honest answers are an adapter/API path the publisher "
        "offers, or a recorded gap."
    )
    out.append("")
    for key, title, blurb, decision_hint in _SECTIONS:
        rows = buckets[key]
        out.append(f"## {title} — {len(rows)}")
        out.append("")
        out.append(blurb)
        out.append("")
        if not rows:
            out.append("_None in the catalog at this revision._")
            out.append("")
            continue
        out.append(f"| Country | Domain | Kind | What the catalog records | Decision ({decision_hint}) |")
        out.append("| --- | --- | --- | --- | --- |")
        for s in rows:
            country = str(s.get("country") or "—")
            domain = str(s.get("domain") or "_(none — deliberate)_")
            kind = str(s.get("kind") or s.get("source_type") or "—")
            out.append(
                f"| {country} | {domain} | {kind} | {_cell(_evidence(s))} |  |"
            )
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="print the per-bucket counts only")
    args = ap.parse_args(argv)

    data = yaml.safe_load(GENERATED.read_text(encoding="utf-8")) or {}
    sources = _rows(GENERATED) + _rows(CURATED)
    if args.check:
        for key, rows in classify(sources).items():
            print(f"{key}: {len(rows)}")
        return 0
    sys.stdout.write(render(sources, as_of=str(data.get("as_of", "unknown"))))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

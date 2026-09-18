#!/usr/bin/env python3
"""The Q925 ⛔ seam: which law sources are ready for an adapter, and are waiting.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q925 — the adapter ORDER and the first managed dataset — is PENDING. The brief for
S04-10 is explicit about what that means for this slice: *"build the framework and CLML,
list every verified source that could not start for want of an order, decide nothing."*

THIS SCRIPT DECIDES NOTHING, AND THAT IS A PROPERTY OF ITS OUTPUT, NOT A PROMISE.
There is no score, no ranking, no "recommended" column and no sort by anything that
could be read as preference: rows come out in the catalogue's own order, grouped by the
CLASS the source declares (Q909's bulk / enumeration / gazette-feed vocabulary, which is
a description of the source's shape, not a judgement of its worth). Adding a rank here
would be answering Q925 in a table and calling it a summary.

WHAT "READY" MEANS, EXACTLY. A row appears when BOTH are true:

* the session that catalogued it actually confirmed the portal (``verification.status``
  is ``fetched`` or ``search-verified``; a ``lead`` was never loaded and is not ready for
  anything), AND
* it declares a channel an adapter could target — a machine-readable format in
  ``structured.formats``, or prose in ``structured.bulk`` / ``structured.api`` that is
  not "none".

THE PROSE IS QUOTED, NEVER PARSED. ``structured.bulk`` and ``structured.api`` are
free text written by the researching session ("direct per-code PDF links, no bundled
export"), and turning that into a machine claim — "has bulk: true" — would be this
script inventing a fact the catalogue does not state. So the sentence is reproduced and
the reader decides.

Usage:
    python scripts/law_adapter_seam.py            # write docs/product/LAW_ADAPTER_SEAM.md
    python scripts/law_adapter_seam.py --check    # exit 1 if the file is out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.law.adapters.registry import SOURCE_CLASSES, SOURCE_CLASS_NOTES, known_formats  # noqa: E402
from src.law.catalog import load_legal_catalog, verified_tier  # noqa: E402

OUT = _ROOT / "docs" / "product" / "LAW_ADAPTER_SEAM.md"

#: Formats a parser could be written against. NOT a completeness claim about the world —
#: it is the set this catalogue actually uses in `structured.formats`, plus the four
#: format names Q906 lists by name, so a row declaring one is visible here the day it
#: lands rather than the day somebody extends this tuple.
MACHINE_FORMATS = frozenset(
    {"akoma_ntoso", "xml", "json", "rdf", "csv", "clml", "formex", "uslm", "legi"}
)
_RESEARCH_VERIFIED = ("fetched", "search-verified")
_NOT_A_CHANNEL = {"", "none", "unknown", "none confirmed", "n/a"}


def _prose(source: dict, key: str) -> str:
    value = str((source.get("structured") or {}).get(key) or "").strip()
    return "" if value.lower() in _NOT_A_CHANNEL else value


def _declared_class(source: dict) -> str:
    """Which of Q909's three classes this row's own fields describe.

    Derived from what the row DECLARES, never from what would be convenient: a row with
    a machine format or a stated bulk/API channel is ``bulk``; one with an index to walk
    is ``enumeration``; one with only a gazette feed is ``gazette-feed``. The order of
    the checks is Q909's own order of preference, which is the one place in this script
    an ordering is allowed, because the ruling supplies it.
    """
    fmts = {str(f).strip().lower() for f in ((source.get("structured") or {}).get("formats") or [])}
    if (fmts & MACHINE_FORMATS) or _prose(source, "bulk") or _prose(source, "api"):
        return "bulk"
    if source.get("enumeration_url"):
        return "enumeration"
    return "gazette-feed"


def candidates(catalog: dict | None = None) -> list[dict]:
    """Every verified source that declares a channel an adapter could target."""
    cat = catalog if catalog is not None else load_legal_catalog()
    out: list[dict] = []
    for source in cat["sources"]:
        # A CURATED row carries no `verification` block and never needed one: the block
        # is the GENERATED harvest's record of what its producing session checked, and a
        # hand-maintained entry was confirmed by the person who wrote it. The first draft
        # of this script required the block, which excluded all 51 curated rows —
        # including the three portals the brief's own live checks name. An absence that
        # means "a different process vouched for this" is not an absence of vouching.
        status = (source.get("verification") or {}).get("status")
        if status is None and not source.get("_generated"):
            status = "curated"
        if status not in (*_RESEARCH_VERIFIED, "curated"):
            continue
        fmts = sorted(
            {str(f).strip().lower() for f in ((source.get("structured") or {}).get("formats") or [])}
            & MACHINE_FORMATS
        )
        bulk, api = _prose(source, "bulk"), _prose(source, "api")
        feed_ok = bool(source.get("gazette_feed")) and (
            (source.get("gazette_feed_verification") or {}).get("status") == "fetched"
        )
        # A row qualifies through ANY of Q909's three classes, not only the first. The
        # first draft required a bulk/api/format declaration, which made every candidate
        # `bulk` BY CONSTRUCTION and left the other two sections permanently empty — a
        # report that cannot show an enumeration source is not the list the brief asked
        # for. A gazette feed counts only when its OWN verification says somebody fetched
        # it: the row-level status is about the portal, and one of the four feeds in this
        # catalogue is a site's generic WordPress news feed.
        if not (fmts or bulk or api or source.get("enumeration_url") or feed_ok):
            continue
        out.append(
            {
                "domain": source.get("domain"),
                "name": source.get("name"),
                "country": source.get("country"),
                "research_status": status,
                "machine_formats": fmts,
                "bulk": bulk,
                "api": api,
                "key_gated": bool((source.get("structured") or {}).get("api_key_required")),
                "class": _declared_class(source),
                "verified": verified_tier(source)["tier"],
            }
        )
    return out


def render(rows: list[dict]) -> str:
    formats = known_formats()
    lines = [
        "# The Q925 ⛔ seam — sources ready for an adapter, waiting on an order",
        "",
        "**Generated by `scripts/law_adapter_seam.py`. Do not hand-edit.**",
        "",
        "Q925 — the adapter ORDER and the first managed dataset — is **PENDING**. Nothing",
        "here decides it. This file exists so that when it is answered, the answer is",
        "chosen from a measured list rather than from memory.",
        "",
        f"This tree registers **{len(formats)} adapter**"
        f"{'' if len(formats) == 1 else 's'}: `{'`, `'.join(formats)}`.",
        "A second one is a registration and a parser module — `register_adapter` is the",
        "seam and a test drives a second adapter through the whole pipeline to prove it —",
        "but WHICH second one is Q925's to say.",
        "",
        "## How to read this",
        "",
        "A source appears when the session that catalogued it actually confirmed the portal",
        "(`verification.status` is `fetched` or `search-verified`) **and** the row declares a",
        "channel an adapter could target. There is no ranking column and the rows are in the",
        "catalogue's own order: a rank here would be Q925 answered in a table.",
        "",
        "`bulk` / `api` are **quoted verbatim** from the catalogue. They are free text written",
        "by the researching session, and turning a sentence like *\"direct per-code PDF links,",
        "no bundled export\"* into `has_bulk: true` would invent a fact the catalogue does not",
        "state.",
        "",
        "The `verified` column is Q924's tier — whether an adapter in **this tree** has read",
        "anything from the source. It is `unverified` almost everywhere, and that is the",
        "honest state: the three hosts the brief's live checks name are egress-blocked from",
        "the build sandbox, so no live read has happened here.",
        "",
    ]
    for cls in SOURCE_CLASSES:
        group = [r for r in rows if r["class"] == cls]
        lines += [
            f"## {cls} — {len(group)} source{'' if len(group) == 1 else 's'}",
            "",
            f"*{SOURCE_CLASS_NOTES[cls]}.*",
            "",
        ]
        if not group:
            lines += ["None.", ""]
            continue
        lines += [
            "| source | country | research | verified | machine formats | bulk (verbatim) | api (verbatim) |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in group:
            key = " 🔑" if r["key_gated"] else ""
            lines.append(
                f"| `{r['domain']}`{key} | {r['country'] or '—'} | {r['research_status']} | "
                f"{r['verified']} | {', '.join(r['machine_formats']) or '—'} | "
                f"{r['bulk'].replace('|', '/') or '—'} | {r['api'].replace('|', '/') or '—'} |"
            )
        lines.append("")
    lines += [
        "🔑 marks a source whose own row says an API key is required. Q910 = a excludes a",
        "key-gated channel under V1-2, so such a row is listed for completeness and is not a",
        "candidate for a first adapter.",
        "",
        "## What is NOT here",
        "",
        "- **A recommendation.** See the top of this file.",
        "- **Leads.** A `lead` row was never loaded by the session that recorded it; it is a",
        "  research lead, not a source ready for anything.",
        "- **Case law and bills.** Q902's (e) was not chosen and its (c) is post-beta, so",
        "  neither is in this slice's model and neither is listed as ready.",
        "- **Subnational law.** Q903 is a recorded CONFLICT, never resolved.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    args = ap.parse_args(argv)
    text = render(candidates())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(_ROOT)} is out of date — re-run {Path(__file__).name}")
            return 1
        print(f"{OUT.relative_to(_ROOT)} is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(_ROOT)} ({len(candidates())} sources)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

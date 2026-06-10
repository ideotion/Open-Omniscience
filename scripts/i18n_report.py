#!/usr/bin/env python3
"""
i18n completeness report — measure how fully each UI locale covers the English source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

English (``en.json``) is the canonical source: every chrome string the UI shows has a key
there. A locale is "complete" when it translates every English key; any missing key falls
back to English at runtime (so a partial locale never breaks the UI — it just shows some
English). This script makes that coverage visible and is safe to wire into CI as a soft
gate (``--min`` fails the build if a locale claiming ``status: complete`` regresses).

Usage:
    python scripts/i18n_report.py                 # human-readable table
    python scripts/i18n_report.py --json          # machine-readable
    python scripts/i18n_report.py --min 100       # exit 1 if a 'complete' locale < 100%
    python scripts/i18n_report.py --audit-chrome  # UI strings NOT yet keyed in en.json

``--audit-chrome`` (maintainer asked 2026-06-10, after a French live test showed
untranslated Settings text) extracts every constant text node + placeholder/
title/aria-label from the UI the same way the runtime engine sees them, and
diffs against en.json — so "how much chrome is untranslatable" is a measurable
number, not a feeling. Fragments split by inline markup are listed too (they
need per-fragment keys or markup changes).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

_LOCALES = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
_UI = Path(__file__).resolve().parent.parent / "src" / "static" / "index.html"


class _ChromeExtractor(HTMLParser):
    """Collect translatable chrome the way i18n.js does: whole text nodes
    (whitespace-normalised) + placeholder/title/aria-label attributes."""

    SKIP = {"script", "style", "code", "pre", "textarea", "svg", "path", "circle", "rect"}
    ATTRS = ("placeholder", "title", "aria-label")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.texts: set[str] = set()

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        for k, v in attrs:
            if k in self.ATTRS and v:
                self._add(v)

    def handle_endtag(self, tag):
        while self.stack and self.stack[-1] != tag:
            self.stack.pop()
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not any(t in self.SKIP for t in self.stack):
            self._add(data)

    def _add(self, s: str) -> None:
        k = re.sub(r"\s+", " ", s).strip()
        if len(k) < 3 or "${" in k:
            return
        if re.fullmatch(r"[\W\d_…→↗·—-]+", k):
            return
        self.texts.add(k)


def audit_chrome() -> dict:
    parser = _ChromeExtractor()
    parser.feed(_UI.read_text(encoding="utf-8"))
    en_keys = _keys(_load(_LOCALES / "en.json"))
    missing = sorted(t for t in parser.texts if t not in en_keys)
    return {
        "ui_strings": len(parser.texts),
        "keyed": len(parser.texts) - len(missing),
        "missing_from_en": len(missing),
        "missing": missing,
    }


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _keys(data: dict) -> set[str]:
    return {k for k in data if k != "_meta"}


def build_report() -> dict:
    en = _load(_LOCALES / "en.json")
    source_keys = _keys(en)
    n = len(source_keys)
    locales = []
    for path in sorted(_LOCALES.glob("*.json")):
        code = path.stem
        if code == "en":
            continue
        data = _load(path)
        meta = data.get("_meta", {})
        have = _keys(data) & source_keys
        missing = sorted(source_keys - have)
        # Coverage = keys present (an *absent* key is what falls back to English at runtime).
        # A present key whose value equals the English source is counted as covered: in many
        # languages a term is a genuine loanword (Wikipedia, Briefing, Mode), so an identical
        # value is a deliberate translation, not a gap. We surface those separately as a hint.
        covered = len(have)
        identical = sorted(k for k in have if str(data.get(k, "")).strip() and data[k] == k)
        pct = round(100 * covered / n, 1) if n else 100.0
        locales.append(
            {
                "code": code,
                "name": meta.get("name", code),
                "native": meta.get("native", ""),
                "declared_status": meta.get("status", "unknown"),
                "translated": covered,
                "total": n,
                "percent": pct,
                "missing": missing,
                "identical_to_english": identical,
            }
        )
    locales.sort(key=lambda x: (-x["percent"], x["code"]))
    return {"source": "en", "source_keys": n, "locales": locales}


def _print_table(report: dict) -> None:
    print(f"i18n coverage — {report['source_keys']} English chrome keys\n")
    print(f"  {'locale':<8}{'name':<14}{'status':<11}{'coverage':>10}")
    print("  " + "-" * 43)
    for loc in report["locales"]:
        bar = f"{loc['translated']}/{loc['total']} ({loc['percent']}%)"
        print(f"  {loc['code']:<8}{loc['name']:<14}{loc['declared_status']:<11}{bar:>10}")
    stubs = [loc["code"] for loc in report["locales"] if loc["percent"] < 5]
    if stubs:
        print(f"\n  stub locales (≈English fallback): {', '.join(stubs)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="i18n completeness report")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument(
        "--min",
        type=float,
        default=None,
        help="fail (exit 1) if any locale declaring status:complete is below this %%",
    )
    ap.add_argument(
        "--audit-chrome",
        action="store_true",
        help="list UI chrome strings not yet keyed in en.json (untranslatable today)",
    )
    args = ap.parse_args(argv)

    if args.audit_chrome:
        audit = audit_chrome()
        if args.json:
            print(json.dumps(audit, ensure_ascii=False, indent=2))
        else:
            print(
                f"chrome audit — {audit['ui_strings']} UI strings, "
                f"{audit['keyed']} keyed, {audit['missing_from_en']} untranslatable:\n"
            )
            for m in audit["missing"]:
                print(f"  {m}")
        return 0

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_table(report)

    if args.min is not None:
        regressed = [
            loc
            for loc in report["locales"]
            if loc["declared_status"] == "complete" and loc["percent"] < args.min
        ]
        if regressed:
            names = ", ".join(f"{loc['code']} ({loc['percent']}%)" for loc in regressed)
            print(
                f"\nFAIL: locales declared 'complete' below {args.min}%: {names}", file=sys.stderr
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

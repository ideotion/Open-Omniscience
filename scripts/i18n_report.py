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


# Surfaces the chrome audit reads BESIDES index.html.
#
# WHY (GUI audit 2026-07-28, finding I-1): this audit used to open index.html
# and nothing else, so it reported "1069 UI strings, 801 keyed" and --min 100
# read a green 2130/2130 x12 -- while app.js, the actual 18.5k-line UI engine,
# was entirely invisible to it. That is how the coverage number could say
# "100%" while untranslated surfaces kept turning up in the field. Widening the
# scope does NOT change the blocking --min gate (that compares locale files
# against en.json and never touches these paths); it only lets the REPORT see
# what the engine actually renders.
_AUX_HTML = ("taskmanager.html", "unlock.html", "investigate.html")


def _aux_js() -> tuple[str, ...]:
    """The JS surfaces the audit reads: every app module, plus reader.js.

    The UI engine is no longer one file -- app.js was decomposed into ordered
    modules (S-3, docs/design/APPJS_DECOMPOSITION_2026-08-20.md) -- so this list
    is READ FROM index.html rather than hard-coded. That is finding I-1's own
    lesson applied to its own fix: a hand-kept list drifts from the thing it
    describes, and here the drift would silently re-blind both JS ratchets to
    ~22k lines of engine, which is exactly the failure this scope exists to end.
    """
    html = _UI.read_text(encoding="utf-8")
    mods = [
        m.group(1)
        for m in re.finditer(r'<script src="/static/(app(?:-[a-z-]+)?\.js)"', html)
    ]
    assert mods, "index.html loads no app module -- the script tags moved or were renamed"
    return (*mods, "reader.js")

# String shapes in JS that reach the DOM (and so are translatable by i18n.js
# if a key exists). Deliberately conservative: a shape that could match a
# non-user-facing literal is left out rather than inflating the count.
_JS_SHAPES = (
    re.compile(r"<th[^>]*>([A-Za-z][^<{`$]{2,80})</th>"),
    re.compile(r"<button[^>]*>([A-Za-z][^<{`$]{2,80})</button>"),
    re.compile(r'placeholder="([A-Za-z][^"{`$]{2,90})"'),
    re.compile(r'\btitle="([A-Za-z][^"{`$]{2,120})"'),
    re.compile(r'aria-label="([A-Za-z][^"{`$]{2,90})"'),
    re.compile(r'\.textContent\s*=\s*"([^"{`$]{3,120})"'),
    re.compile(r'\btoast\(\s*"([^"{`$]{3,140})"'),
    # The t() call site itself -- the HIGHEST-signal shape, and the one this list
    # was missing. Every other pattern here is an inference that a literal reaches
    # the DOM; `t("...")` is the code SAYING SO. i18n.js's t() is an exact map
    # lookup with no normalisation (`map[s] == null ? s : map[s]`), so a literal
    # with no en.json key renders verbatim English in all 11 other locales --
    # including, before this landed, .card-caveat text and the additive-restore
    # assurance, which the non-negotiables require to ship x12.
    re.compile(r'\bt\(\s*"((?:[^"\\{`$]|\\.){3,200})"'),
    re.compile(r"\bt\(\s*'((?:[^'\\{`$]|\\.){3,200})'"),
)


def _js_chrome(text: str) -> set[str]:
    out: set[str] = set()
    for rx in _JS_SHAPES:
        for m in rx.finditer(text):
            k = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(k) < 3 or "${" in k:
                continue
            if re.fullmatch(r"[\W\d_…→↗·—-]+", k):
                continue
            if k.startswith(("http", "/api", "data:", "var(", "#")):
                continue
            out.add(k)
    return out


def _static_dir() -> Path:
    return _UI.parent


# The t() CALL SITES, on their own.
#
# Every other shape in _JS_SHAPES is an INFERENCE that a literal reaches the DOM;
# `t("...")` is the code saying so outright, and i18n.js's t() is an exact map
# lookup with no normalisation -- so a t() literal with no en.json key renders
# verbatim English in all 11 other locales, every time, with no ambiguity about
# whether the string was user-facing. That makes this subset the highest-signal
# slice of the untranslatable count and the one worth driving to zero on its own
# schedule, rather than leaving it inside a blended number that also carries
# regex guesses. Reported by --audit-chrome; gated by --max-unkeyed-t-calls.
_T_CALL = (
    re.compile(r'\bt\(\s*"((?:[^"\\{`$]|\\.){1,400})"'),
    re.compile(r"\bt\(\s*'((?:[^'\\{`$]|\\.){1,400})'"),
)


def unkeyed_t_calls() -> dict:
    """Every t("literal") in the JS whose literal has no en.json key."""
    en_keys = _keys(_load(_LOCALES / "en.json"))
    sites = 0
    unkeyed: set[str] = set()
    for name in _aux_js():
        path = _static_dir() / name
        assert path.exists(), f"{name} is listed by index.html but missing from src/static"
        text = path.read_text(encoding="utf-8")
        for rx in _T_CALL:
            for m in rx.finditer(text):
                k = re.sub(r"\s+", " ", m.group(1)).strip()
                if not k:
                    continue
                sites += 1
                if k not in en_keys:
                    unkeyed.add(k)
    return {"sites": sites, "unkeyed_count": len(unkeyed), "unkeyed": sorted(unkeyed)}


def audit_chrome() -> dict:
    parser = _ChromeExtractor()
    parser.feed(_UI.read_text(encoding="utf-8"))
    texts = set(parser.texts)
    per_file = {"index.html": len(parser.texts)}

    for name in _AUX_HTML:
        path = _static_dir() / name
        if not path.exists():
            continue
        aux = _ChromeExtractor()
        aux.feed(path.read_text(encoding="utf-8"))
        per_file[name] = len(aux.texts)
        texts |= aux.texts

    for name in _aux_js():
        path = _static_dir() / name
        assert path.exists(), f"{name} is listed by index.html but missing from src/static"
        found = _js_chrome(path.read_text(encoding="utf-8"))
        per_file[name] = len(found)
        texts |= found

    en_keys = _keys(_load(_LOCALES / "en.json"))
    missing = sorted(t for t in texts if t not in en_keys)
    return {
        "ui_strings": len(texts),
        "keyed": len(texts) - len(missing),
        "missing_from_en": len(missing),
        "missing": missing,
        "per_file": per_file,
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
    ap.add_argument(
        "--max-untranslatable",
        type=int,
        default=None,
        metavar="N",
        help=(
            "fail (exit 1) if MORE than N UI strings have no en.json key. A ratchet, "
            "like MYPY_BASELINE: it may only be lowered."
        ),
    )
    ap.add_argument(
        "--max-unkeyed-t-calls",
        type=int,
        default=None,
        metavar="N",
        help=(
            "fail (exit 1) if MORE than N distinct t(\"...\") literals have no en.json "
            "key. The tight half of the ratchet above: these are certainly user-facing."
        ),
    )
    args = ap.parse_args(argv)

    if args.max_unkeyed_t_calls is not None:
        tcalls = unkeyed_t_calls()
        n = tcalls["unkeyed_count"]
        print(
            f'unkeyed t("...") literals: {n} of {tcalls["sites"]} call sites '
            f"(ratchet {args.max_unkeyed_t_calls})",
            file=sys.stderr,
        )
        if n > args.max_unkeyed_t_calls:
            print(
                f"\nFAIL: {n} t() literals have no en.json key, above the ratchet of "
                f"{args.max_unkeyed_t_calls}. t() is an exact lookup, so each of these "
                f"renders verbatim English in all 11 other locales. Add the key to all "
                f"12 locale files. This number may only go down.",
                file=sys.stderr,
            )
            for k in tcalls["unkeyed"][:20]:
                print(f"    {k[:110]}", file=sys.stderr)
            if n > 20:
                print(f"    ... and {n - 20} more (--audit-chrome --json)", file=sys.stderr)
            return 1
        if n < args.max_unkeyed_t_calls:
            print(f"  (the ratchet can now be lowered to {n})", file=sys.stderr)
        return 0

    # The ratchet. --min compares the locale files against en.json, so it answers
    # "are the 12 locales mutually consistent?" and CANNOT see a UI string that was
    # never keyed at all -- which is how it reported a green 2394/2394 x12 while
    # hundreds of strings, .card-caveat text among them, rendered English in every
    # locale. This gate closes exactly that gap and is the one that blocks.
    if args.max_untranslatable is not None:
        audit = audit_chrome()
        n = audit["missing_from_en"]
        print(
            f"untranslatable UI strings: {n} (ratchet {args.max_untranslatable})",
            file=sys.stderr,
        )
        if n > args.max_untranslatable:
            print(
                f"\nFAIL: {n} UI strings have no en.json key, above the ratchet of "
                f"{args.max_untranslatable}. Add the keys (all 12 locales), or lower "
                f"nothing -- this number may only go down. "
                f"Run --audit-chrome to list them.",
                file=sys.stderr,
            )
            return 1
        if n < args.max_untranslatable:
            print(
                f"  (the ratchet can now be lowered to {n})",
                file=sys.stderr,
            )
        return 0

    if args.audit_chrome:
        audit = audit_chrome()
        audit["t_calls"] = unkeyed_t_calls()
        if args.json:
            print(json.dumps(audit, ensure_ascii=False, indent=2))
        else:
            print(
                f"chrome audit — {audit['ui_strings']} UI strings, "
                f"{audit['keyed']} keyed, {audit['missing_from_en']} untranslatable\n"
            )
            tc = audit["t_calls"]
            print(
                f"  of which t(\"...\") literals (certainly user-facing): "
                f"{tc['unkeyed_count']} unkeyed of {tc['sites']} call sites\n"
            )
            print("  scanned:")
            for name, count in sorted(audit.get("per_file", {}).items()):
                print(f"    {count:5d}  {name}")
            print()
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

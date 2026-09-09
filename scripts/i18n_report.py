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
    """The JS surfaces the audit reads: every top-level static module index.html
    loads by a plain ``<script src="/static/NAME.js">`` tag, plus reader.js.

    The UI engine is no longer one file -- app.js was decomposed into ordered
    modules (S-3, docs/design/APPJS_DECOMPOSITION_2026-08-20.md) -- so this list
    is READ FROM index.html rather than hard-coded. That is finding I-1's own
    lesson applied to its own fix: a hand-kept list drifts from the thing it
    describes, and here the drift would silently re-blind both JS ratchets to
    ~22k lines of engine, which is exactly the failure this scope exists to end.

    WIDENED (i18n consolidation pass 2026-09-09, closing a scanner blind spot
    from the 2026-09-08 visual audit): the old regex matched only filenames
    shaped ``app*.js``, so every OTHER top-level module loaded the same way --
    ``oosky.js`` (the Observatory canvas, which paints its own domain-wedge
    labels with ``ctx.fillText`` and, per a sibling fix in this same pass, now
    routes them through ``OOI18N.t`` before painting) chief among them -- was
    structurally invisible to both JS ratchets no matter how many t() calls it
    carried. The class of file this must still NOT reach is ``guis/*.js``
    (handled separately by ``_guis_js()``, including two modules injected at
    runtime that never appear in any ``<script src>`` at all) and any vendored
    third-party script; excluding "/" from the matched filename keeps both out
    without an explicit denylist.
    """
    html = _UI.read_text(encoding="utf-8")
    mods = [
        m.group(1)
        for m in re.finditer(r'<script src="/static/([A-Za-z0-9_.-]+\.js)"', html)
    ]
    assert mods, "index.html loads no static module -- the script tags moved or were renamed"
    assert "oosky.js" in mods, (
        "oosky.js dropped out of index.html's <script src> list -- the canvas "
        "domain labels it paints would go dark to both JS ratchets again"
    )
    return (*mods, "reader.js")


# The two aux HTML shells (taskmanager.html, unlock.html) each carry ONE large
# inline <script> block (their own external i18n.js tag is already covered by
# scanning that file directly). Neither `_ChromeExtractor` (its SKIP set
# excludes `script` content, correctly -- that content is JS, not chrome text)
# nor `_aux_js()` (which only ever globs *files*, and an inline block is not
# one) can reach it, so on this pass alone ~127 real t()/t9()/t9m() call sites
# across the two files sat outside both JS ratchets -- not undercounted, simply
# never visited. `[^>]*\bsrc=` in the negative lookahead is what keeps this from
# also swallowing each file's own `<script src="/static/i18n.js">` tag as a
# second, empty "inline" body.
_AUX_INLINE_JS_HOSTS = ("taskmanager.html", "unlock.html")


def _aux_inline_js() -> dict[str, str]:
    """{"taskmanager.html#inline", ...} -> the text of that file's one inline
    ``<script>...</script>`` block, for feeding through the same JS-literal
    regexes used on every real ``.js`` file."""
    out: dict[str, str] = {}
    for name in _AUX_INLINE_JS_HOSTS:
        path = _static_dir() / name
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        if blocks:
            # Exactly one inline block is the shape both files have today; if a
            # second one is ever added, concatenating is still correct -- every
            # regex here matches individual literals, not whole-file structure.
            out[f"{name}#inline"] = "\n".join(blocks)
    return out


_MAIN_PY = Path(__file__).resolve().parent.parent / "src" / "api" / "main.py"


def _reader_template_html() -> str:
    """Best-effort textual approximation of the rendered HTML from
    ``src/api/main.py``'s server-side article-reader page (its
    ``doc = f\"\"\"...\"\"\"`` template) -- the ONE HTML-emitting code path in the
    whole API layer, which the audit found has zero scanner coverage in any
    mode (``src/api/`` is on no code path this tool ever opens). That reader
    page loads ``/static/i18n.js`` itself and is translated the exact same
    way index.html is -- an exact whole-text-node lookup against the locale
    files -- so its chrome belongs in the same audit, not a separate one.

    This is NOT an f-string evaluator: it unescapes the literal ``{{``/``}}``
    the template uses for CSS braces, then blanks every remaining bare
    ``{expr}`` interpolation (the article title, ids, injected sub-fragments
    like ``{meta_rows}``) so dynamic per-article content can never be misread
    as translatable chrome. That is sufficient here because every
    interpolation this specific template contains is a bare name/attribute
    expression with no nested braces -- verified by the absence of any
    `{`/`}` character left over inside a still-non-empty extracted text node
    once this substitution runs.
    """
    src = _MAIN_PY.read_text(encoding="utf-8")
    m = re.search(r'doc = f"""(.*?)"""\n\s*return HTMLResponse\(content=doc\)', src, re.S)
    if not m:
        return ""
    body = m.group(1)
    body = body.replace("{{", "\x00OPEN\x00").replace("}}", "\x00CLOSE\x00")
    body = re.sub(r"\{[^{}]*\}", " ", body)
    return body.replace("\x00OPEN\x00", "{").replace("\x00CLOSE\x00", "}")


def _guis_js() -> tuple[str, ...]:
    """The GUIs-gallery JS surface: every module under src/static/guis/, except
    the vendored third-party library (audit finding P1-01).

    _aux_js() finds its files by scanning index.html's <script src> tags, which
    works for boot.js and gallery.js (ordinary static tags) but CANNOT reach the
    two Alpine-powered skins, ui-command.js and ui-canvas.js: per CLAUDE.md
    invariant #30, boot.js's own GUIS registry injects those at RUNTIME
    (`document.createElement("script"); s.src = ...; appendChild`), so they never
    appear as a <script src> in any static HTML -- no widening of the markup
    regex can find them. Enumerating the directory directly reaches all four
    (and any future addition) without needing to parse boot.js's JS object
    literal. `vendor/` is excluded: it holds Alpine.js itself, a third-party
    library, not app chrome.
    """
    mods = sorted(f"guis/{p.name}" for p in (_static_dir() / "guis").glob("*.js"))
    assert mods, "src/static/guis has no .js files -- the gallery moved or was removed"
    return tuple(mods)

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
    #
    # Matches `t(`, `t9(` AND `t9m(` -- many modules locally alias OOI18N.t to
    # `t9`/`t9m` (`const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s) => s`)
    # rather than calling it `t` directly. `\bt\(` alone never matches `t9(` --
    # the character after `t` is the digit `9`, which is a word character, so
    # there is no `\b` between them either -- so every t9()/t9m() call site was
    # structurally invisible here, not merely undercounted (audit finding P1-01).
    # `t9m` is tried before `t9` so it isn't partially matched as `t9` + literal `m`.
    re.compile(r'\bt(?:9m|9)?\(\s*"((?:[^"\\{`$]|\\.){3,200})"'),
    re.compile(r"\bt(?:9m|9)?\(\s*'((?:[^'\\{`$]|\\.){3,200})'"),
    # Backtick-delimited counterparts of the three shapes above whose regex
    # hardcodes its own opening quote character rather than merely searching
    # for the substring pattern (2026-09-09 blind-spot close, visual audit
    # table item 4): `<th>`/`<button>`/`placeholder=`/`title=`/`aria-label=`
    # already match regardless of what quote style wraps the JS string that
    # contains them, because they search for the literal HTML substring, not
    # the string's own delimiter -- only these three ever hardcode `"`/`'`
    # directly after `=`/`(`, so only these three need a backtick sibling. A
    # backtick literal that carries a real `${...}` interpolation is
    # correctly excluded (no `$` in the character class), same as the
    # quote-delimited versions above.
    re.compile(r"\.textContent\s*=\s*`([^`{$]{3,120})`"),
    re.compile(r"\btoast\(\s*`([^`{$]{3,140})`"),
    re.compile(r"\bt(?:9m|9)?\(\s*`((?:[^`\\{$]|\\.){3,200})`"),
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
#
# Also matches the `t9(`/`t9m(` local-alias convention -- see the identical note
# on the duplicate pair inside _JS_SHAPES above (audit finding P1-01): a plain
# `\bt\(` never matches `t9(`/`t9m(` at all, so every aliased call site was
# invisible to this gate, not merely undercounted.
_T_CALL = (
    re.compile(r'\bt(?:9m|9)?\(\s*"((?:[^"\\{`$]|\\.){1,400})"'),
    re.compile(r"\bt(?:9m|9)?\(\s*'((?:[^'\\{`$]|\\.){1,400})'"),
    # Backtick sibling (2026-09-09 blind-spot close, table item 4) -- see the
    # identical addition + rationale on _JS_SHAPES above.
    re.compile(r"\bt(?:9m|9)?\(\s*`((?:[^`\\{$]|\\.){1,400})`"),
)


def unkeyed_t_calls() -> dict:
    """Every t("literal") in the JS whose literal has no en.json key."""
    en_keys = _keys(_load(_LOCALES / "en.json"))
    sites = 0
    unkeyed: set[str] = set()
    sources = {name: (_static_dir() / name).read_text(encoding="utf-8") for name in (*_aux_js(), *_guis_js())}
    for name in sources:
        assert (_static_dir() / name).exists(), f"{name} is listed by index.html but missing from src/static"
    # The two aux HTML shells' one inline <script> each (2026-09-09 blind-spot
    # close, table item 2) -- see _aux_inline_js()'s own docstring for why
    # neither _ChromeExtractor nor the .js-file glob above could ever reach it.
    sources.update(_aux_inline_js())
    for text in sources.values():
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

    for name in (*_aux_js(), *_guis_js()):
        path = _static_dir() / name
        assert path.exists(), f"{name} is listed by index.html but missing from src/static"
        found = _js_chrome(path.read_text(encoding="utf-8"))
        per_file[name] = len(found)
        texts |= found

    # The two blind spots a plain file/DOM scan structurally cannot reach --
    # see each helper's own docstring. Both additive: neither can ever
    # subtract from what the scan above already found.
    for label, text in _aux_inline_js().items():
        found = _js_chrome(text)
        per_file[label] = len(found)
        texts |= found

    reader_html = _reader_template_html()
    if reader_html:
        rdr = _ChromeExtractor()
        rdr.feed(reader_html)
        per_file["src/api/main.py (reader)"] = len(rdr.texts)
        texts |= rdr.texts

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

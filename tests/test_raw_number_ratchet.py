"""Leading "+N" and "lo–hi" tokens beside text keep their order under Arabic (0.5.1, R277).

Measured in Chromium under ``dir=rtl`` (qual-lane/rtl-raw-number-sites-2026-10-26.md): a leading plus is drawn
on the far side of its digits even alone, and a dash range after translated text is drawn reversed. The
fix is ``ooLtrIsolate`` (app-core.js), a first-strong isolate only under a right-to-left page; left-to-right
output is byte-identical. RULED 2026-11-07 (item 46, S4 b): a percent sign stays AFTER its digits and an en-dash
range reads low to high beside Arabic: 17 percent sites and 5 range sites go through ``ooLtrIsolate`` (a token)
or ``ooLtrPct`` (a sentence a translation frame has already composed, where the sign is the translator's).

THE RATCHET. Each file's count of a raw ``+${`` and of a raw ``${a}–${b}`` template must EQUAL its pin
(zero slack, the same shape as ``test_raw_date_ratchet.py``). What the pinned remainder is:

* hard-coded English strings that are never translated (app-diagnostics, app-sources: ``+${n}`` in a toast
  or a status line);
* ``"+"`` / ``'+'`` string literals (``_PLUS_STR`` below) that are character tests on a diff line, already
  isolated by the older always-wrapping ``_ltrIsolate`` (app-library.js), a size sign, a join, or the markets
  pill, whose whole token (sign, digits, percent) is now one isolate.

``ooLtrIsolate`` is RTL-only on purpose (left-to-right output is the input, byte for byte, which matters for
``textContent``, option strings and tests); ``_ltrIsolate`` always wraps and stays for the sites that already
use it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

_PLUS = re.compile(r"(?<![\w$})\]])\+\$\{")
_PLUS_STR = re.compile(r"""(?<!ooLtrIsolate\()["']\+["']""")
_RANGE = re.compile(r"(?<!ooLtrIsolate\(`)\$\{[^}$]*\}\s*–\s*\$\{")

_PINS = {
    "plus": {"app-diagnostics.js": 2, "app-sources.js": 1},
    "plus_str": {
        "app-backup.js": 3, "app-core.js": 1, "app-corpus.js": 1, "app-gov-law.js": 2, "app-living.js": 2,
        "app-map.js": 7, "app-markets.js": 1, "app-settings.js": 1, "app-shell.js": 1, "ooversions.js": 1,
    },
    "range": {},
}


def _files():
    return sorted(
        p for ext in ("*.js", "*.html") for p in _STATIC.rglob(ext) if "vendor" not in p.relative_to(_STATIC).parts
    )


def _counts(pattern):
    out = {}
    for p in _files():
        n = len(pattern.findall(p.read_text(encoding="utf-8")))
        if n:
            out[p.relative_to(_STATIC).as_posix()] = n
    return out


def test_every_raw_plus_token_is_accounted_for_and_nothing_holds_room():
    got = _counts(_PLUS)
    assert got == _PINS["plus"], (
        "a raw leading +N changed: render it through ooLtrIsolate(...) (see this file's docstring), or move the pin "
        f"if it is one of the kinds listed there. Found: {got}"
    )


def test_every_plus_string_literal_is_accounted_for_and_nothing_holds_room():
    got = _counts(_PLUS_STR)
    assert got == _PINS["plus_str"], (
        "a '+' string literal changed: if it prefixes a number that is DRAWN, render the whole token through "
        f"ooLtrIsolate(...); otherwise move the pin. Found: {got}"
    )


def test_every_raw_range_token_is_accounted_for_and_nothing_holds_room():
    got = _counts(_RANGE)
    assert got == _PINS["range"], (
        "a raw lo–hi range changed: render it through ooLtrIsolate(...), or move the pin if it is one of the "
        f"kinds listed in this file's docstring. Found: {got}"
    )


def test_the_patterns_find_what_they_are_meant_to_find():
    for hit in ("<b>+${n}</b>", " +${names.length - 1}", "`+${x}`", "(+${x})".replace("(", " ")):
        assert _PLUS.search(hit), hit
    for miss in ("a+${n}", "${a}+${b}", "x)+${n}", "${n}"):
        assert not _PLUS.search(miss), miss
    assert _RANGE.search("${row.lo}–${row.hi}") and _RANGE.search("${a} – ${b}")
    assert not _RANGE.search("${a}-${b}") and not _RANGE.search("${a}—${b}")


def test_the_swapped_sites_use_the_helper():
    core = (_STATIC / "app-core.js").read_text(encoding="utf-8")
    assert "function ooLtrIsolate(" in core and '"\\u2068" + v + "\\u2069"' in core
    for name, n in (("app-agenda.js", 6), ("app-analysis.js", 5), ("app-core.js", 3), ("app-corpus.js", 1),
                    ("app-map.js", 5), ("app-ai-tools.js", 1), ("app-settings.js", 3), ("ooversions.js", 1),
                    ("app-diagnostics.js", 3), ("app-library.js", 1), ("app-markets.js", 1), ("app-backup.js", 2)):
        text = (_STATIC / name).read_text(encoding="utf-8")
        got = text.count("ooLtrIsolate(") - (1 if name == "app-core.js" else 0)
        assert got == n, (name, got, n)


def test_the_helper_behaves_under_both_directions():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oo_ltr_isolate_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


#: 2026-11-07 (item 46, S4 b): the percent sites and the range sites, by file, as the maintainer's ruling listed them
#: (17 percent, 5 range). A file's count of ``ooLtrPct(`` CALLS is a sentence a translation frame composed; a
#: ``ooLtrIsolate(`` carrying a percent or a range is a token. Removing one wrap reddens by file name.
_PERCENT_ISOLATES = {  # token percent sites: "...%" inside ooLtrIsolate(...)
    "app-analysis.js": 2, "app-core.js": 1, "app-diagnostics.js": 3, "app-library.js": 1, "app-map.js": 4,
    "app-settings.js": 2, "app-markets.js": 1,
}   # counted per WRAP, not per site: diagnostics line 501 carries two, so the 17 ruled sites are 2+1+2+1+5+3+2+1
_PERCENT_FRAMES = {"app-map.js": 2, "app-settings.js": 1, "app-sources.js": 2}   # ooLtrPct( calls
_RANGE_ISOLATES = {"app-agenda.js": 1, "app-analysis.js": 2, "app-backup.js": 2, "app-settings.js": 1}   # settings: the R277 lo-hi


def _isolate_args(text):
    """Every ``ooLtrIsolate(`` argument, up to its balanced close, so a nested template does not truncate it."""
    out = []
    at = 0
    while True:
        at = text.find("ooLtrIsolate(", at)
        if at == -1:
            return out
        i = at + len("ooLtrIsolate(")
        depth = 1
        j = i
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        out.append(text[i:j - 1])
        at = j


def test_each_percent_and_range_site_is_wrapped_and_the_frame_sites_use_the_sentence_helper():
    got_pct, got_range, got_frames = {}, {}, {}
    for name in sorted({*_PERCENT_ISOLATES, *_RANGE_ISOLATES, *_PERCENT_FRAMES}):
        text = (_STATIC / name).read_text(encoding="utf-8")
        args = _isolate_args(text)
        pct = sum(1 for a in args if "%" in a and "–" not in a)
        rng = sum(1 for a in args if "–" in a and "%" not in a and "->" not in a)
        if pct:
            got_pct[name] = pct
        if rng:
            got_range[name] = rng
        calls = text.count("ooLtrPct(") - (1 if name == "app-core.js" else 0)
        if calls:
            got_frames[name] = calls
    assert got_pct == _PERCENT_ISOLATES, got_pct
    assert got_range == _RANGE_ISOLATES, got_range
    assert got_frames == _PERCENT_FRAMES, got_frames

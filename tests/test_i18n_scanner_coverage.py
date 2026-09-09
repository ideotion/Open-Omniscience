"""Guard: the four i18n scanner blind spots closed 2026-09-09 stay closed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

i18n consolidation pass, acting on the 2026-09-08 visual audit's table of
scanner blind spots (docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md). Measured
that day: ``--min 100`` reported a real, green 3151/3151 (locale-file parity
only), while ``audit_chrome()`` reported 552 untranslatable chrome strings and
``unkeyed_t_calls()`` 294 unkeyed ``t()`` call sites -- both true, and both
ratchets that only cap growth rather than requiring closure, so a green CI run
was compatible with hundreds of permanently-English strings. On TOP of that,
four mechanisms were invisible to the tool BY CONSTRUCTION, contributing zero
to either number no matter how many untranslated strings they carried:

  (1) ``src/api/main.py``'s server-rendered article-reader page -- the tool had
      zero code paths into ``src/api/`` in any mode, so this is the informed-
      consent string at the reader footer arrived at as literally unseen, not
      merely uncounted.
  (2) ``taskmanager.html``/``unlock.html``'s ONE inline ``<script>`` each --
      ``_ChromeExtractor``'s SKIP set correctly excludes ``<script>`` content
      (that content is JS, not chrome text) and the JS-file glob only ever
      matched *files*, so ~120 real ``t()``/``t9()``/``t9m()`` call sites fell
      between the two scanners entirely.
  (3) Canvas text (``oosky.js``'s ``ctx.fillText``) -- no DOM node exists for
      any text-based scanner to find, AND the file-discovery regex only ever
      matched filenames shaped ``app*.js``, so ``oosky.js`` itself was excluded
      from the JS scan regardless.
  (4) Chrome text inside backtick template literals -- every extraction regex
      for the three shapes that hardcode their own opening quote character
      (``.textContent = "..."``, ``toast("...")``, ``t("...")``) required a
      ``"``/``'`` delimiter, so a backtick-quoted literal of any of those three
      shapes was invisible no matter how plainly translatable it was.

Each fix below is verified by proving the SPECIFIC gap it closes, not merely
that some function runs without raising -- most of these assertions fail
against the pre-fix ``scripts/i18n_report.py`` and pass against the fixed one,
checked by reverting the relevant helper (rather than needing an old git
revision) and re-measuring.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "i18n_report.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _module():
    spec = importlib.util.spec_from_file_location("i18n_report_scanner_coverage", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# (1) src/api/main.py's server-rendered article-reader page
# --------------------------------------------------------------------------- #


def test_reader_template_extracts_the_informed_consent_string():
    """THE flagged finding: an informed-consent string that ships to every
    reader, in every locale, and was completely unseen by any scanner path.
    This reads main.py directly (not en.json), so it stays true regardless of
    whether a later pass ever keys the string -- it is a discoverability
    guard, not a translation-completeness one.
    """
    mod = _module()
    html = mod._reader_template_html()
    assert html, "the reader template extractor found nothing -- doc = f\"\"\" in main.py moved or was renamed"
    parser = mod._ChromeExtractor()
    parser.feed(html)
    assert (
        "Opening the source makes a live request from your machine; the site "
        "may see your visit. You'll be asked to confirm."
    ) in parser.texts, (
        "the reader page's informed-consent string is not reachable through "
        "_reader_template_html() -- the one string this blind spot was named for"
    )
    # A handful of other known reader-chrome strings, to prove this is a real
    # whole-template scan and not a fluke match on one line.
    for expected in ("Read", "Summary", "Related", "Article views"):
        assert expected in parser.texts, f"reader chrome {expected!r} not extracted"


def test_reader_template_never_leaks_dynamic_interpolations_as_chrome():
    """The extractor blanks single-brace f-string interpolations (article
    title, ids, injected sub-fragments) so per-article dynamic content can
    never be misread as a translatable constant -- that would be actively
    dangerous (a "key" that is really one article's headline)."""
    mod = _module()
    html = mod._reader_template_html()
    parser = mod._ChromeExtractor()
    parser.feed(html)
    for t in parser.texts:
        assert "{" not in t and "}" not in t, f"a raw interpolation leaked into extracted chrome: {t!r}"


def test_reader_scan_is_wired_into_audit_chrome():
    """The extractor alone is not the fix -- it must actually be CALLED by
    audit_chrome(), or this blind spot is closed on paper only."""
    mod = _module()
    audit = mod.audit_chrome()
    assert "src/api/main.py (reader)" in audit["per_file"], (
        "audit_chrome() never calls _reader_template_html() -- the reader page "
        "is extracted correctly in isolation but never reaches the report"
    )
    assert audit["per_file"]["src/api/main.py (reader)"] > 0


# --------------------------------------------------------------------------- #
# (2) taskmanager.html / unlock.html inline <script> blocks
# --------------------------------------------------------------------------- #


def test_aux_inline_js_finds_the_one_inline_script_in_each_shell():
    mod = _module()
    inline = mod._aux_inline_js()
    assert set(inline) == {"taskmanager.html#inline", "unlock.html#inline"}, (
        f"expected exactly the two known aux shells, got {sorted(inline)}"
    )
    for name, text in inline.items():
        assert len(text) > 5000, f"{name} looks truncated ({len(text)} chars) -- check the regex"
        assert "t(" in text or "t9(" in text, f"{name}: no t()/t9()/t9m() call at all -- suspicious"


def test_aux_inline_js_excludes_the_external_i18n_script_tag():
    """Both shells ALSO carry ``<script src="/static/i18n.js"></script>`` --
    the negative lookahead must skip that tag rather than capturing an empty
    inline body for it (which would silently pass the "exactly one block"
    shape while hiding a wiring bug)."""
    mod = _module()
    for text in mod._aux_inline_js().values():
        assert "i18n.js" not in text


def test_removing_aux_inline_js_measurably_lowers_both_gates():
    """THE regression, proven by removing the fix rather than re-deriving
    numbers by hand: with the two inline scripts hidden from the scanner (the
    pre-fix behaviour), the two blocking gates must go DOWN -- proving those
    ~120 t() call sites and their chrome-shaped literals were real
    contributions, not zero-effect plumbing.
    """
    mod = _module()
    before_t = mod.unkeyed_t_calls()
    before_chrome = mod.audit_chrome()

    mod._aux_inline_js = lambda: {}  # simulate the pre-fix scanner

    after_t = mod.unkeyed_t_calls()
    after_chrome = mod.audit_chrome()

    assert after_t["sites"] < before_t["sites"], (
        "hiding the two inline <script> blocks did not reduce t()-call-site "
        "count -- unkeyed_t_calls() may no longer be reading _aux_inline_js()"
    )
    assert after_chrome["ui_strings"] < before_chrome["ui_strings"], (
        "hiding the two inline <script> blocks did not reduce the chrome "
        "count -- audit_chrome() may no longer be reading _aux_inline_js()"
    )


# --------------------------------------------------------------------------- #
# (3) canvas text -- oosky.js (and its siblings) must be scanned at all
# --------------------------------------------------------------------------- #


def test_aux_js_widened_past_the_app_star_js_filter():
    """The old file-discovery regex only matched ``app*.js`` -- so
    ``oosky.js``, ``ooviz.js``, ``osmpbf.js``, ``i18n.js`` and
    ``sw-register.js`` (every top-level static module NOT named ``app*.js``)
    were excluded from the JS scan by construction, independent of whether
    any of them carried a literal t() call worth finding.
    """
    mod = _module()
    mods = mod._aux_js()
    for name in ("oosky.js", "ooviz.js", "osmpbf.js", "i18n.js", "sw-register.js"):
        assert name in mods, f"{name} is not discovered by _aux_js() -- the widened regex regressed"
    # And it must NOT have started matching guis/*.js (that subdirectory has
    # its own discovery path, _guis_js(), and double-counting it would be a
    # different bug than the one this test guards).
    assert not any("guis/" in m for m in mods), "_aux_js() must not reach into guis/ -- that is _guis_js()'s job"


def test_narrowing_aux_js_back_to_app_star_drops_oosky_from_the_scan():
    """Proves the OLD regex really was the mechanism of exclusion (not some
    other filter), by reinstating it and checking oosky.js disappears."""
    mod = _module()
    html = mod._UI.read_text(encoding="utf-8")
    old_pattern = re.compile(r'<script src="/static/(app(?:-[a-z-]+)?\.js)"')
    old_mods = [m.group(1) for m in old_pattern.finditer(html)]
    assert "oosky.js" not in old_mods, (
        "the OLD app*.js-only pattern unexpectedly already matched oosky.js -- "
        "this test's premise is stale, re-check the historical regex"
    )
    assert "oosky.js" in mod._aux_js(), "the CURRENT widened pattern must include it"


def test_oosky_js_is_reachable_through_the_widened_scan_with_a_real_count():
    """oosky.js is scanned (audit_chrome's per-file table carries a real,
    non-error entry for it) even though its one canvas-label t() call site
    passes a VARIABLE (``_t(da.domain)``), not a string literal -- which no
    static regex can ever resolve to the literal domain names without
    executing the module. That is an honest, structural limit of a
    regex-based scanner (the actual domain strings are keyed directly in
    en.json and verified end-to-end by tests/test_canvas_labels_and_caveat_key.py's
    Node harness instead) -- what this test guards is only that oosky.js is
    now VISITED, not silently skipped as before.
    """
    mod = _module()
    audit = mod.audit_chrome()
    assert "oosky.js" in audit["per_file"], "oosky.js must appear in the per-file breakdown"
    assert audit["per_file"]["oosky.js"] == 0, (
        "oosky.js's only t() call site passes a variable, not a literal -- if "
        "this count changed, either a literal was added (fine, update this "
        "test) or the scanner started hallucinating a match"
    )


# --------------------------------------------------------------------------- #
# (4) backtick-delimited literals
# --------------------------------------------------------------------------- #

_BACKTICK_SAMPLE = """
function render() {
  el.textContent = `Nothing here yet.`;
  toast(`Could not reach the server.`);
  return t(`Section tabs`);
}
"""


def test_js_chrome_shapes_capture_backtick_delimited_literals():
    mod = _module()
    found = mod._js_chrome(_BACKTICK_SAMPLE)
    assert "Nothing here yet." in found, "backtick .textContent = `...` is not captured"
    assert "Could not reach the server." in found, "backtick toast(`...`) is not captured"
    assert "Section tabs" in found, "backtick t(`...`) is not captured by _js_chrome"


def test_t_call_regex_captures_backtick_delimited_literals():
    mod = _module()
    hits = set()
    for rx in mod._T_CALL:
        for m in rx.finditer(_BACKTICK_SAMPLE):
            hits.add(re.sub(r"\s+", " ", m.group(1)).strip())
    assert "Section tabs" in hits, "_T_CALL does not recognise a backtick-delimited t(`...`) literal"


def test_backtick_literal_with_real_interpolation_is_never_captured():
    """A backtick literal carrying a genuine ``${...}`` cannot be a translation
    key (it is not a constant) -- the fix must not have widened the character
    class so far that it starts swallowing these."""
    mod = _module()
    sample = "el.textContent = `Loaded ${n} articles`; toast(`Failed: ${err}`);"
    found = mod._js_chrome(sample)
    assert not any("${" in s or "Loaded" in s or "Failed" in s for s in found), (
        f"an interpolated backtick literal was captured as if it were a constant: {found}"
    )


def test_backtick_shapes_did_not_exist_before_this_fix():
    """Anchors the regression: without the three backtick-specific patterns
    this fix added, none of the three samples above would ever have matched --
    proven here by re-running with only the ORIGINAL quote-delimited patterns.
    """
    original_js_shapes = (
        re.compile(r'\.textContent\s*=\s*"([^"{`$]{3,120})"'),
        re.compile(r'\btoast\(\s*"([^"{`$]{3,140})"'),
        re.compile(r'\bt(?:9m|9)?\(\s*"((?:[^"\\{`$]|\\.){3,200})"'),
        re.compile(r"\bt(?:9m|9)?\(\s*'((?:[^'\\{`$]|\\.){3,200})'"),
    )
    out = set()
    for rx in original_js_shapes:
        for m in rx.finditer(_BACKTICK_SAMPLE):
            out.add(m.group(1))
    assert out == set(), (
        f"the pre-fix (quote-only) shapes unexpectedly matched something in the "
        f"backtick sample: {out} -- this test's premise is stale"
    )


# --------------------------------------------------------------------------- #
# The ratchets themselves: ci.yml must name the REAL, currently-measured
# counts -- neither more (slack the project's ratchet convention forbids) nor
# less (a red build for no reason).
# --------------------------------------------------------------------------- #


def _ci_ratchet(flag: str) -> int:
    text = _CI.read_text(encoding="utf-8")
    m = re.search(rf"i18n_report\.py {re.escape(flag)} (\d+)", text)
    assert m, f"{flag} not found in ci.yml -- did the step get renamed or removed?"
    return int(m.group(1))


def test_ci_untranslatable_ratchet_matches_the_real_count():
    mod = _module()
    real = mod.audit_chrome()["missing_from_en"]
    ci_value = _ci_ratchet("--max-untranslatable")
    assert ci_value == real, (
        f"ci.yml's --max-untranslatable is {ci_value} but the real measured count "
        f"is {real} -- a ratchet with slack enforces nothing, and one below the "
        f"real count reddens CI for no fixable reason"
    )


def test_ci_unkeyed_t_calls_ratchet_matches_the_real_count():
    mod = _module()
    real = mod.unkeyed_t_calls()["unkeyed_count"]
    ci_value = _ci_ratchet("--max-unkeyed-t-calls")
    assert ci_value == real, (
        f"ci.yml's --max-unkeyed-t-calls is {ci_value} but the real measured count "
        f"is {real} -- a ratchet with slack enforces nothing, and one below the "
        f"real count reddens CI for no fixable reason"
    )


@pytest.mark.parametrize("flag", ["--max-untranslatable", "--max-unkeyed-t-calls"])
def test_ci_ratchet_values_are_sane(flag):
    """A trivial sanity floor so a typo (e.g. a stray extra digit, or 0) fails
    loudly here instead of only as a mysteriously-red or mysteriously-lenient
    CI run."""
    value = _ci_ratchet(flag)
    assert 0 < value < 5000

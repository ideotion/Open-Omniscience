"""Wave 5 (K, frontend) — guard test for the LUNAR-CORRELATION first-class surface.

New test file (per the wave contract; touches no existing shared test). Pure
stdlib + string assertions over the static frontend, so it runs on py3.11 without
the app's runtime deps. It pins the upgrade of the raw-JSON diagnostics button into
a first-class Insights subtab that renders the read-only
GET /api/insights/lunar-correlation screen honestly.

Honesty invariants pinned here: the method + "correlation is not causation" caveat
are VISIBLE by default; the common outcome (nothing survives) is stated, never
hidden; the survivor flag is the FDR verdict, not a ranking; no fabricated score;
every new user-facing string is keyed in ALL 12 locales.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"


def _html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def _app() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


_ITEM2_KEYS = [
    "Lunar",
    "Lunar correlation",
    (
        "Does a keyword's daily coverage line up with the moon's illuminated fraction? This "
        "screens the most-mentioned keywords with a circular-shift permutation test and "
        "corrects the whole family with Benjamini-Hochberg FDR, so a survivor beat multiple "
        "testing — never a bare significant p. Correlation is not causation; the common, honest "
        "outcome is that nothing survives. Counts and statistics only, no score."
    ),
    "Terms to screen",
    "FDR level",
    "Test one keyword",
    "keyword to test",
    "Term",
    "p-value",
    "active days",
    "q-value",
    "survived",
    "tested",
    "survivors",
    "Screening the corpus… a permutation test runs per keyword, so this can take a few seconds.",
    "No series survived the multiple-testing correction — the honest, expected result.",
    "No series had enough active days to test.",
    "A single test, not corrected for multiple comparisons — screen many keywords for an honest, FDR-corrected result.",
    "Too few active days to test this keyword honestly.",
]


def test_lunar_is_an_insights_subtab():
    """A Lunar subtab + its panel live in the Insights area (an Insights subtab)."""
    html = _html()
    assert 'data-tab="lunar"' in html and 'id="ins-lunar"' in html, (
        "the Lunar Insights subtab button + panel must exist"
    )
    # It is a peer of the existing Insights views (class ins-view), lazy-loaded once.
    seg = html[html.index('id="ins-lunar"'):]
    seg = seg[: seg.index("</section>")]
    assert 'class="panel ins-view"' in html[html.index('id="ins-lunar"') - 40:html.index('id="ins-lunar"') + 40]
    app = _app()
    assert 'if (cat === "lunar") loadLunar();' in app, "showInsightCat must lazy-load loadLunar"


def test_lunar_consumes_the_real_endpoint():
    """loadLunar screens via the existing endpoint; lunarTestTerm does the single test."""
    app = _app()
    assert "async function loadLunar(" in app and "async function lunarTestTerm(" in app
    assert "/api/insights/lunar-correlation?limit=${lim}&fdr_q=${q}" in app, (
        "the screen must call the real endpoint with limit + fdr_q"
    )
    assert '"/api/insights/lunar-correlation?term=" + encodeURIComponent(term)' in app, (
        "the single-term test must call the endpoint with ?term="
    )


def test_lunar_method_and_caveat_are_visible():
    """The method + 'correlation is not causation' caveat render VISIBLE by default."""
    html = _html()
    seg = html[html.index('id="ins-lunar"'):]
    seg = seg[: seg.index("</section>")]
    # The caveat is an ordinary visible hint paragraph, never a hidden/toggled block.
    assert 'class="hint"' in seg and "Correlation is not causation" in seg, (
        "the intro must state the method + non-causation caveat, visibly"
    )
    assert "hidden" not in seg.lower(), "no part of the lunar panel may be hidden by default"
    assert "no score" in seg, "the panel must state counts/statistics only, no score"


def test_lunar_states_the_empty_result_and_fdr_verdict():
    """Nothing surviving is stated (never hidden); the survivor flag is the FDR verdict."""
    app = _app()
    ln = app[app.index("async function loadLunar("):]
    ln = ln[: ln.index("async function lunarTestTerm(")]
    # The 'nothing survives' honest outcome is surfaced prominently when survivors==0.
    assert "d.survivors === 0" in ln and (
        't("No series survived the multiple-testing correction' in ln
    ), "an empty (zero-survivor) result must be stated, never hidden"
    # tested==0 honest empty state.
    assert 't("No series had enough active days to test.")' in ln
    # The survivor flag is the FDR verdict (r.survives), not a ranking/score.
    assert "r.survives" in ln and 't("survived")' in ln
    # Honest summary is counts only (tested/skipped/survivors).
    assert 't("tested")' in ln and 't("skipped")' in ln and 't("survivors")' in ln
    # NO fabricated score anywhere in the lunar surface.
    both = ln + app[app.index("async function lunarTestTerm("):app.index("// -- Watches")]
    assert "score" not in both.lower(), "the lunar surface must not compute or show a score"


def test_lunar_single_test_carries_the_one_test_is_not_a_screen_note():
    """The single-term test shows the 'one test is not a screen' note + honest skip."""
    app = _app()
    lt = app[app.index("async function lunarTestTerm("):]
    lt = lt[: lt.index("// -- Watches")]
    assert 't("A single test, not corrected for multiple comparisons' in lt, (
        "the single-term test must warn that one test is not a screen"
    )
    assert 't("Too few active days to test this keyword honestly.")' in lt, (
        "a keyword with too few active days must degrade honestly"
    )


def test_item2_strings_keyed_in_every_locale():
    """Every new lunar string is present in ALL 12 locales — i18n stays 100%."""
    for code in ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        data = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        for k in _ITEM2_KEYS:
            assert k in data, f"locale {code} is missing the lunar key: {k!r}"
            assert str(data[k]).strip(), f"locale {code} has an empty value for {k!r}"

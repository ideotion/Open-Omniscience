"""Wave 5 (K, frontend) — guard test for the Wikipedia TRACKED-CHANGES view.

New test file (per the wave contract; touches no existing shared test). Pure
stdlib + string assertions over the static frontend, so it runs on py3.11 without
the app's runtime deps. It pins the frontend wiring for the per-page tracked
revision history the "tracked-changes tab" ruling asks for (Wikipedia-as-a-living-
source), consuming the ALREADY-EXISTING endpoint GET /api/wiki/pages/{id}/revisions.

Honesty invariants pinned here: the stored diff is labelled a captured slice (not a
live re-diff), the window is honest (showing N of M), the caveat is VISIBLE, and
every new user-facing string is keyed in ALL 12 locales (i18n stays 100%).
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


# The user-facing strings this feature introduces (must be keyed in every locale).
_ITEM1_KEYS = [
    "Tracked changes",
    "anon",
    "minor",
    "bot",
    "full text stored",
    "The exact text of this revision is stored on this machine.",
    "tracked revisions",
    "Showing",
    "No tracked revisions stored for this page yet.",
    "No flagged tracked revisions stored for this page yet.",
    "No stored diff (no parent, or tracked without diffs).",
    (
        "The tracked slice of edits stored on this machine, newest first — not necessarily "
        "every historical revision. Each diff is the compact added / removed summary captured "
        "when the edit was tracked (truncated per side), not a live re-diff. Counts only, no score."
    ),
    "See this page's tracked revision history — the stored edits, newest first, with each diff.",
]


def test_tracked_changes_dialog_exists():
    """The #wiki-tc dialog with its body, method/caveat slot and flagged-only toggle."""
    html = _html()
    assert 'id="wiki-tc"' in html, "the tracked-changes dialog must exist"
    for needle in ('id="wiki-tc-body"', 'id="wiki-tc-method"', 'id="wiki-tc-flagged"',
                   'id="wiki-tc-title"'):
        assert needle in html, f"tracked-changes dialog missing {needle}"
    # The method/caveat slot uses the visible caveat styling, never a hidden block.
    seg = html[html.index('id="wiki-tc"'):]
    seg = seg[: seg.index("</dialog>")]
    assert 'id="wiki-tc-method" class="card-caveat"' in seg, (
        "the caveat/method must render in a VISIBLE .card-caveat line, never hidden"
    )
    assert 'onchange="loadWikiTC()"' in seg, "the flagged-only toggle must reload the view"


def test_watched_page_row_opens_tracked_changes():
    """Each watched-page row carries a Tracked-changes affordance that opens the view."""
    app = _app()
    assert 'onclick="openWikiTC(' in app, (
        "the watched-pages table must offer a per-page Tracked-changes button"
    )
    # The button lives in loadWikiPages, alongside Track / Delete.
    lp = app[app.index("async function loadWikiPages("):]
    lp = lp[: lp.index("async function addWikiPage(")]
    assert "openWikiTC(${p.id}" in lp, "the button must pass the page id"
    assert ">Tracked changes</button>" in lp, "the button label must be Tracked changes"


def test_tracked_changes_consumes_the_real_endpoint_with_honesty():
    """loadWikiTC calls the existing revisions endpoint and renders it honestly."""
    app = _app()
    assert "function openWikiTC(" in app and "async function loadWikiTC(" in app
    assert "function _wikiRevRow(" in app, "a per-revision renderer must exist"
    # Consumes the ALREADY-EXISTING endpoint, newest-first tracked slice, with diffs.
    assert "/api/wiki/pages/${_wikiTc.id}/revisions?limit=50&flagged_only=${flagged}&include_diff=true" in app, (
        "must fetch the real per-page revisions endpoint with flagged_only + include_diff"
    )
    tc = app[app.index("async function loadWikiTC("):]
    tc = tc[: tc.index("// --- Search-tab time-range control")]
    # Honest window: showing count / total tracked revisions (the endpoint discloses a slice).
    assert 'd.count} / ${d.total}' in tc and 't("tracked revisions")' in tc, (
        "must show an honest 'showing N of M' window"
    )
    # VISIBLE caveat mirroring the endpoint method — never behind a toggle.
    assert 'meth.textContent = t("The tracked slice of edits stored on this machine' in tc, (
        "the caveat/method must be rendered VISIBLE by default"
    )
    # Honest empty states (both flagged and unflagged), never a blank pane.
    assert 'No tracked revisions stored for this page yet.' in tc
    assert 'No flagged tracked revisions stored for this page yet.' in tc
    # 'full text stored' marker for locally-materializable revisions.
    assert "r.has_full_text" in app and 't("full text stored")' in app
    # No fabricated score anywhere in the surface.
    assert "score" not in tc.lower().replace("no score", "").replace("no_score", ""), (
        "the tracked-changes surface must not compute or show a score"
    )


def test_tracked_changes_diff_is_a_stored_slice_not_a_live_rediff():
    """The stored diff renders added/removed lines, and the caveat says it is not a re-diff."""
    app = _app()
    row = app[app.index("function _wikiRevRow("):]
    row = row[: row.index("async function loadWikiTC(")]
    # Added / removed lines styled distinctly (ok / err), context lines muted.
    assert 'l.charAt(0) === "+" ? "ok"' in row and 'l.charAt(0) === "-" ? "err"' in row, (
        "diff lines must render added/removed visually distinct"
    )
    assert 't("No stored diff (no parent, or tracked without diffs).")' in row, (
        "a revision without a stored diff must degrade honestly"
    )
    # The keyed caveat states the diff is captured/truncated, not a live re-diff.
    long_caveat = next(k for k in _ITEM1_KEYS if "not a live re-diff" in k)
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    assert long_caveat in en, "the caveat key must exist in en.json"
    assert "not a live re-diff" in en[long_caveat] and "no score" in en[long_caveat]


def test_item1_strings_keyed_in_every_locale():
    """Every new string is present in ALL 12 locales — i18n stays 100% (no gate regression)."""
    for code in ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        data = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        for k in _ITEM1_KEYS:
            assert k in data, f"locale {code} is missing the tracked-changes key: {k!r}"
            assert str(data[k]).strip(), f"locale {code} has an empty value for {k!r}"

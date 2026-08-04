"""The Library tile's qualification line said "Never judged" about a count that includes
sources tried repeatedly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

``_count_sources_never_judged`` counts ``Source.status == "unqualified"``. But
``log_no_evidence_attempts`` (``src/catalog/qualification.py``) writes a ``no_evidence``
``SourceQualificationAttempt`` row and DELIBERATELY leaves ``Source.status`` untouched --
that is the whole reason it exists, the 2026-07-23 livelock fix, so an attempt that finds
nothing to judge is on the record without pretending to be a verdict. An ENABLED source
with no feed therefore produces one of those rows every time it rotates to the front of
the queue and stays in this bucket forever, while the label claimed it had never been
judged.

Measured on a 76,679-source fixture shaped from the ledger's own field figures (~3,600
enabled, ~73,000 disabled candidates): 1,253 in the line, of which 663 genuinely never
attempted -- so 590, about half, had attempt rows behind them. The PERCENTAGE is a
property of that fixture's assumed feedless share; the DEFECT is structural and holds at
any share, which is why the tests below assert the distinction rather than a ratio.

Two facts are pinned, in both directions each time:
  * the store can tell the two populations apart (and did not before);
  * the frontend states an absent reading as absent, never as zero -- rendering 0 would
    claim every waiting source had been attempted, the exact inverse of "not recorded".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_NO_EVIDENCE,
)
from src.database.models import Source, SourceQualificationAttempt
from src.database.session import SessionLocal, init_db
from src.database.snapshots import ALL_METRICS, _FILTERED_METRICS

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    """Rolled back, never committed: the recorded pollution lesson is about rows that
    survive into later tests, and nothing here reaches the shared store."""
    init_db()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _src(db, *, status: str, enabled: bool) -> Source:
    s = Source(name=f"t{uuid.uuid4().hex[:8]}", domain=f"{uuid.uuid4().hex[:10]}.example",
               status=status, enabled=enabled)
    db.add(s)
    db.flush()
    return s


def _attempt(db, source: Source, verdict: str, *, days_ago: int = 1) -> None:
    db.add(SourceQualificationAttempt(
        source_id=source.id, attempted_at=datetime.now(UTC) - timedelta(days=days_ago),
        verdict=verdict, criteria_version="oo-source-qualification-1"))
    db.flush()


# --- the store -------------------------------------------------------------------------

def test_the_new_metric_is_registered_and_served():
    assert "sources_never_attempted" in _FILTERED_METRICS
    assert "sources_never_attempted" in ALL_METRICS, (
        "ALL_METRICS is the Library endpoint's allowlist; a metric absent from it 400s"
    )


def test_never_attempted_excludes_a_source_that_was_tried_and_concluded_nothing(db):
    """THE DISCRIMINATING CASE. Both functions see the same source; only one counts it."""
    never = _FILTERED_METRICS["sources_never_attempted"]
    judged = _FILTERED_METRICS["sources_never_judged"]
    base_never, base_judged = never(db), judged(db)

    _src(db, status=STATUS_UNQUALIFIED, enabled=True)              # never selected yet
    assert never(db) == base_never + 1
    assert judged(db) == base_judged + 1

    tried = _src(db, status=STATUS_UNQUALIFIED, enabled=True)      # the feedless case
    _attempt(db, tried, VERDICT_NO_EVIDENCE)
    assert judged(db) == base_judged + 2, (
        "status is still unqualified, so the legacy line must still count it -- its "
        "definition is frozen so its own history stays comparable"
    )
    assert never(db) == base_never + 1, (
        "but it HAS been attempted, so the honest metric must not count it. If this fails "
        "the NOT EXISTS is inverted and the new number is just the old one renamed."
    )


def test_repeated_attempts_on_one_source_do_not_double_count(db):
    """The table is append-only, so a source on the ladder has several rows. EXISTS, not a
    join, is what keeps that one source rather than one per attempt."""
    never = _FILTERED_METRICS["sources_never_attempted"]
    judged = _FILTERED_METRICS["sources_never_judged"]
    base_never, base_judged = never(db), judged(db)
    s = _src(db, status=STATUS_UNQUALIFIED, enabled=True)
    for d in (30, 20, 10, 3):
        _attempt(db, s, VERDICT_NO_EVIDENCE, days_ago=d)
    assert never(db) == base_never
    assert judged(db) == base_judged + 1


def test_both_metrics_ignore_disabled_candidates_and_judged_sources(db):
    """The negative-space twin: an over-eager metric would sweep in the ~73,000 disabled
    discovery candidates, which belong to `sources_candidates`, or count sources that DO
    carry a verdict."""
    never = _FILTERED_METRICS["sources_never_attempted"]
    judged = _FILTERED_METRICS["sources_never_judged"]
    base_never, base_judged = never(db), judged(db)

    _src(db, status=STATUS_UNQUALIFIED, enabled=False)   # a disabled candidate
    q = _src(db, status=STATUS_QUALIFIED, enabled=True)  # has a verdict
    _attempt(db, q, STATUS_QUALIFIED)
    d = _src(db, status=STATUS_DISQUALIFIED, enabled=True)
    _attempt(db, d, STATUS_DISQUALIFIED)

    assert never(db) == base_never, "none of these three is an enabled, verdict-less source"
    assert judged(db) == base_judged


def test_a_disabled_source_with_no_attempt_is_still_not_counted(db):
    """Stated separately because it is the one a reader most expects to be included: it is
    verdict-less AND never attempted, and it is still out, because the line is about the
    sources actually admitted to collection."""
    never = _FILTERED_METRICS["sources_never_attempted"]
    base = never(db)
    _src(db, status=STATUS_UNQUALIFIED, enabled=False)
    assert never(db) == base


# --- the frontend ----------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_qual_split_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "qual_split_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_the_false_label_is_gone_from_the_tile() -> None:
    """Scoped to the label table, not the whole file: a whole-file search for "Never
    judged" would also match the comment that RECORDS its removal, which is the comment a
    future session reads before deciding the removal was a mistake.

    Brace-matched by the shared helper rather than sliced to the first ``}``. The ratchet
    in test_source_slicing_discipline rejected the hand-rolled version, and writing the
    shared shape it asked for immediately exposed that raw brace-counting truncates on a
    ``}`` inside a string value -- so the helper now skips strings and comments.
    """
    from tests.js_source_helper import object_literal, read_static, strip_comments

    table = strip_comments(object_literal(read_static("app.js"), "LIB_QUAL_LABELS"))
    assert "Never judged" not in table, (
        "the label claimed no attempt had been made about a count that includes sources "
        "tried repeatedly"
    )
    assert "Awaiting a verdict" in table


def test_the_split_metric_is_fetched_but_not_charted() -> None:
    """It is a SUBSET of the line above it, and it starts recording today while the others
    have months -- so as a fifth line it would read as a separate population that began at
    zero. Fetched for the note, kept out of the series."""
    from tests.js_source_helper import (
        array_literal,
        function_body,
        read_static,
        strip_comments,
    )

    app = read_static("app.js")
    # Bracket-matched, not "from this declaration to the next one by name" -- which is
    # correct only while those two stay adjacent, in that order.
    metrics = array_literal(app, "LIB_QUAL_METRICS")
    assert "sources_never_attempted" not in metrics, (
        "LIB_QUAL_METRICS drives the charted series; the subset must not join it"
    )
    tile = strip_comments(function_body(app, "_libQualificationTile"))
    assert "LIB_QUAL_SPLIT_METRIC" in tile, "but it must still be fetched"
    assert "_libQualSplitNote" in tile, "and rendered as a note"


def test_the_caveat_states_that_waiting_does_not_mean_untried() -> None:
    from tests.js_source_helper import function_body, read_static, strip_comments

    body = strip_comments(function_body(read_static("app.js"), "enlargeLibQualification"))
    assert "does not mean untried" in body, (
        "the prose carried the same false claim as the label and had to be corrected too"
    )
    assert "never-judged" not in body


# --- three defects the browser found that source reading did not -----------------------

def test_the_scale_control_no_longer_discards_the_callers_caveat() -> None:
    """``note = HINTS[mode] || caveat`` made the second branch DEAD CODE, because
    HINTS[mode] is a non-empty string for all three modes -- so every caller passing
    ``{scales: true}`` had its caveat silently dropped. Two were: this tile's
    "never a quality score / awaiting a verdict does not mean untried", and the index
    comparison's provenance line. Found by opening the modal and reading its last line.

    The two statements now occupy the two slots they belong to, so neither can evict the
    other: the mode text in the dynamic hint, the caller's caveat in the note.
    """
    from tests.js_source_helper import function_body, read_static, strip_comments

    body = strip_comments(function_body(read_static("app.js"), "chartEnlarge"))
    assert "HINTS[mode] || caveat" not in body, (
        "the dead branch is back: HINTS[mode] is never empty, so the caveat never renders"
    )
    assert 'note.textContent = caveat || ""' in body, "the note carries the caller's caveat"
    assert 'hint.textContent = HINTS[mode] || ""' in body, (
        "and the hint still tracks the mode, which is what the earlier stale-note fix was for"
    )


def test_the_commodities_family_view_passes_no_caveat_to_the_modal() -> None:
    """Its caveat IS a per-mode statement ("Indexed to 100 at the window start…"), which is
    exactly why the note went stale on a scale toggle. HINTS says it for every mode, so the
    caller passes none -- and keeps its inline .card-caveat for the un-enlarged view, so
    nothing is lost."""
    from tests.js_source_helper import read_static

    app = read_static("app.js")
    # Anchored on the call itself, which provably occurs, rather than on a guessed
    # delimiter: the whole file would be satisfied by any chartEnlarge anywhere.
    at = app.index("chartEnlarge(t(g.label)")
    call = app[at:app.index(";", at) + 1]
    assert "_famCaveat" not in call, (
        f"passing the per-mode caveat into the modal is what made the note go stale: {call}"
    )
    assert '""' in call and "{scales: true}" in call
    assert "host._famCaveat = cavText" in app, (
        "the inline family-view caveat must survive: this is a modal-only change"
    )


def test_the_activity_view_re_renders_on_a_language_switch() -> None:
    """The note is an INTERPOLATED tf() string, so once composed it is not a key and the
    i18n DOM walker cannot re-translate it; the Library renders each view once. Caught by
    screenshotting the tile in French, where every neighbouring label had translated and
    this one sentence had not -- the recorded frozen-locale class, recurring the moment a
    new interpolated string was added to a render-once surface."""
    from tests.js_source_helper import read_static, strip_comments

    app = strip_comments(read_static("app.js"))
    at = app.index('addEventListener("oo:langchange"')
    handler = app[at:at + 4000]
    assert '_libViewLoaded.has("activity")' in handler, (
        "the Activity view must re-render on a language switch, or its interpolated note "
        "stays frozen in whatever locale first rendered it"
    )
    assert "renderLibraryActivityGraphs()" in handler


def test_the_legend_carries_no_unit_because_the_slot_is_the_unit_of_n() -> None:
    """ooChart's legend renders `label` then `n=N · unit`, where N is the DATAPOINT count.
    So the slot is the unit OF N, not of the values.

    Both other fillings were wrong, and the second is the instructive one. The label read
    "Qualified n=29 · Qualified" -- redundant. Then "sources" read "Qualified n=29 ·
    sources", which a reader takes as "29 sources in this category" and which cannot be
    true of all four series at once (they end at 4, 2, 3 and 1 on a chart whose axis tops
    out at 6). It is 29 daily samples. An adversarial critic reading the rendered
    screenshot caught it and did the arithmetic; no mechanical check could have.
    """
    from tests.js_source_helper import function_body, read_static, strip_comments

    body = strip_comments(function_body(read_static("app.js"), "_libQualificationTile"))
    at = body.index("_libQualSeries = LIB_QUAL_METRICS.map")
    mapper = body[at:body.index("}));", at)]
    assert "unit:" not in mapper, (
        f"the legend must carry no unit; the slot describes n, not the values: {mapper}"
    )


def test_a_log_axis_is_refused_when_the_data_contains_a_zero() -> None:
    """log10(0) is undefined, and the clamp to LOGEPS invented a position for it: measured
    on this tile, four integer series in 0..6 produced a log-space axis spanning -9..0.78,
    so the real differences occupied ~5% of the plot, the tick labels read "0.003" and TWO
    "0" gridlines -- values no count can take -- and every true zero was drawn as a point
    on the floor with a line through it. A fabricated axis, found by reading the ticks off
    a screenshot.

    It never showed before because logY shipped for the markets boards, where an index
    value is never 0. Now the mode is refused, falls back to a zero-based integer-tick
    linear axis, and says so.
    """
    from tests.js_source_helper import function_body, read_static, strip_comments

    chart = strip_comments(function_body(read_static("app.js"), "ooChart"))
    assert "const logOk" in chart and "const logRefused" in chart
    assert "+p.v > 0" in chart, "the refusal must test positivity, not merely non-null"
    for expr in ("logOk ? Math.log10", "logOk ? Math.pow(10, d)"):
        assert expr in chart, f"the transform must follow the refusal: {expr}"
    assert "opts.zeroBase && !logOk" in chart, (
        "a refused log must fall back to the zero-based axis counts deserve"
    )
    assert "const tickInt = !logOk" in chart, "and to integer ticks"
    assert "cannot place a zero" in chart, "and must SAY that it refused"

    # The tile's own "log scale" chip must ask the same question, or it claims a scale the
    # chart declined to use.
    tile = strip_comments(read_static("app.js"))
    assert tile.count("_libQualSpread(_libQualSeries) > 50 && _libQualLogOk(") == 2, (
        "both the chip and the render path decide log the same way"
    )
    assert "function _libQualLogOk" in tile


def test_the_scale_control_does_not_offer_a_mode_the_chart_will_refuse() -> None:
    """Offering it put two statements on screen at once: the hint claiming "Log scale
    (base 10) — equal ratios are equal distances" above a chart that had drawn a linear
    axis and said so underneath. Verified in a browser both ways: a zero-containing series
    disables the chip and forcing a click changes nothing, while a positive-only series
    (the markets case logY was built for) keeps a working Log mode."""
    from tests.js_source_helper import function_body, read_static, strip_comments

    body = strip_comments(function_body(read_static("app.js"), "chartEnlarge"))
    assert "const logPossible" in body
    assert '+p.v > 0' in body, "positivity, not merely non-null"
    assert 'k === "log" && !logPossible' in body, "only the log chip is ever disabled"
    assert "!b || b.disabled" in body, (
        "the delegated handler must ignore a disabled chip too, so a future change that "
        "styles instead of disabling cannot make the mode reachable again"
    )


def test_the_refusal_strings_are_keyed_in_all_twelve_locales() -> None:
    for key in (
        "Linear scale: a log axis cannot place a zero, and this data has some.",
        "A log axis cannot place a zero, and this data has some.",
    ):
        for f in sorted(_LOC.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            assert key in d and str(d[key]).strip(), f"{f.stem}: missing {key!r}"


def test_an_ltr_value_is_bidi_isolated_before_it_enters_a_translated_sentence() -> None:
    """Measured in the real Arabic page: "بدأ التسجيل في " + an ISO timestamp renders in
    visual order ".07T18:00:00-07-2026" -- the year at the wrong end, a MISREAD date rather
    than merely an ugly one. U+2068/U+2069 around the value fixes it, and they are plain
    characters so they survive esc()."""
    from tests.js_source_helper import function_body, read_static, strip_comments

    app = read_static("app.js")
    assert "⁨" in app and "⁩" in app, "the isolate characters themselves"
    assert "function _ltrIsolate" in app
    body = strip_comments(function_body(app, "_libQualificationTile"))
    assert '.replace("{x}", _ltrIsolate(began))' in body, (
        "the timestamp is the value that needs it: digits joined by punctuation are what "
        "bidi reorders, which is why the bare counts beside it do not get one"
    )


# --- i18n ------------------------------------------------------------------------------

_LOC = _ROOT / "src" / "static" / "locales"
_SUPERSEDED_CAVEAT = (
    "Counts only, never a quality score. Qualified = actively collecting; "
    "disqualified/never-judged are enabled but not (yet) admitted; candidates are "
    "disabled, awaiting review."
)
_NEW_KEYS = [
    "Awaiting a verdict",
    "Qualified",
    "Disqualified",
    "Candidates",
    "Source qualification",
    "log scale",
    "Awaiting a verdict: {awaiting} · never attempted: {never} · tried without one: "
    "{tried}",
    "Not yet recorded: how many of these have never been attempted.",
    "The two readings come from different snapshots, so the split is not comparable yet.",
]


def test_every_new_string_is_keyed_in_all_twelve_locales() -> None:
    files = sorted(_LOC.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for k in _NEW_KEYS:
            assert k in d, f"{f.stem}: missing key {k[:50]!r}"
            assert str(d[k]).strip(), f"{f.stem}: empty value for {k[:50]!r}"


def test_the_superseded_caveat_is_replaced_not_orphaned_beside_its_replacement() -> None:
    """A re-key, not an addition. The old string was translated in all twelve locales, so
    adding the new one beside it would orphan twelve reviewed translations while leaving
    the i18n gate green -- the recorded ALERT_CAVEAT failure."""
    for f in sorted(_LOC.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert _SUPERSEDED_CAVEAT not in d, (
            f"{f.stem}: the old caveat survived; a re-key must replace the entry"
        )
        new = [k for k in d if k.startswith("Counts only, never a quality score.")]
        assert len(new) == 1, f"{f.stem}: expected exactly one qualification caveat, got {len(new)}"
        assert "does not mean untried" in new[0]


def test_the_split_template_keeps_its_placeholders_in_every_locale() -> None:
    """A mangled {awaiting} renders as a literal brace, and a DROPPED one renders the
    sentence with a number missing -- which reads as a complete statement about fewer
    facts than it names."""
    ph = re.compile(r"\{(\w+)\}")
    tpl = next(k for k in _NEW_KEYS if "{awaiting}" in k)
    for f in sorted(_LOC.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert set(ph.findall(d[tpl])) == set(ph.findall(tpl)), (
            f"{f.stem}: placeholders differ -> {d[tpl]!r}"
        )

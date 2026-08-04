"""The figure aggregates (GUI visualization plan §7 — C1, C2, C5).

The tests that matter here are the NEGATIVE-SPACE ones: a figure is dishonest long
before it is wrong, and the ways it goes dishonest are all absences —

  * an unmeasured language reported as a measured zero,
  * a quarantine reason invented at zero so the axis looks complete,
  * a Gini of 0 (perfect EQUALITY) standing in for "undefined",
  * an empty curve because a maintained counter was NULL, which states that no
    source holds any article.

Every one of those passes a positive-space test suite unnoticed, so each has its own
case below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.figures import (
    quarantine_composition,
    sentiment_measurability,
    source_concentration,
)
from src.database.models import Article, Base, Source


@pytest.fixture()
def db():
    """An isolated in-memory corpus.

    Never SessionLocal: seeding the shared process DB pollutes every later test that
    reads it (the recorded 2026-07-06 lesson — one wave-2 test reddened seven others).
    """
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


def _src(db, dom, **kw):
    s = Source(name=dom, domain=dom, **kw)
    db.add(s)
    db.flush()
    return s


def _art(db, src, n, *, lang="en", tone=None, quar=None, ver=None, days=1):
    # The key must include EVERY parameter that distinguishes a batch, or two calls
    # that differ only in (say) criteria_version collide on the unique articles.hash
    # and the test fails on its own fixture rather than on the behaviour.
    tag = f"{lang}-{quar or 'ok'}-{ver or 'nov'}"
    for i in range(n):
        a = Article(
            source_id=src.id, title=f"{dom_key(src)}-{tag}-{i}",
            url=f"https://{src.domain}/{tag}/{i}",
            canonical_url=f"https://{src.domain}/{tag}/{i}",
            content="body " * 30, hash=f"h-{src.id}-{tag}-{i}",
            language=lang, sentiment_score=tone,
            quarantined=bool(quar) or None, quarantine_reason=quar,
            quarantine_criteria_version=ver,
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days),
        )
        db.add(a)
    db.flush()


def dom_key(src):
    return src.domain.split(".")[0]


# --- C2: sentiment measurability ------------------------------------------- //


def test_an_unmeasured_language_is_unmeasured_and_not_a_zero(db):
    """The whole point of C2. An article whose language the scorer cannot read has NO
    tone value; reporting it as a measured zero would be the fabricated neutral the
    scorer itself refuses to produce."""
    s = _src(db, "a.example")
    _art(db, s, 3, lang="en", tone=0.4)
    _art(db, s, 5, lang="fr")                      # no tone: unreadable lexicon
    out = sentiment_measurability(db)
    rows = {r["language"]: r for r in out["rows"]}
    assert rows["fr"]["measured"] == 0
    assert rows["fr"]["unmeasured"] == 5           # present as UNMEASURED, not absent
    assert rows["fr"]["supported"] is False
    assert rows["en"]["measured"] == 3 and rows["en"]["unmeasured"] == 0
    assert rows["en"]["supported"] is True


def test_a_measured_zero_tone_is_a_measurement_not_a_gap(db):
    """The mirror case, and the one an over-eager fix breaks: 0.0 is a REAL VADER
    result for genuinely neutral English, so it must count as measured."""
    s = _src(db, "b.example")
    _art(db, s, 4, lang="en", tone=0.0)
    out = sentiment_measurability(db)
    row = next(r for r in out["rows"] if r["language"] == "en")
    assert row["measured"] == 4, "a tone of exactly 0.0 was measured, not missing"
    assert row["unmeasured"] == 0


def test_region_subtags_fold_but_distinct_languages_never_merge(db):
    """en-US and en are one bucket; en and fr are two. An over-eager key merges real
    languages and the shares still sum to 1, so nothing looks wrong."""
    s = _src(db, "c.example")
    _art(db, s, 2, lang="en", tone=0.1)
    _art(db, s, 3, lang="en-US", tone=0.2)
    _art(db, s, 4, lang="fr")
    out = sentiment_measurability(db)
    rows = {r["language"]: r["n"] for r in out["rows"]}
    assert rows["en"] == 5, "en-US must fold into en (normalize_lang)"
    assert rows["fr"] == 4, "fr must stay its own language"
    assert "en-us" not in rows


def test_articles_with_no_asserted_language_are_reported_apart(db):
    """An untagged article is the tone gate's own blind spot. Bucketing it under a
    plausible language would hide exactly the number worth knowing."""
    s = _src(db, "d.example")
    _art(db, s, 2, lang="en", tone=0.3)
    _art(db, s, 7, lang="")
    out = sentiment_measurability(db)
    assert out["untagged"]["n"] == 7
    assert all(r["language"] for r in out["rows"]), "no empty-string language bucket"
    assert out["n"] == 9, "the total counts untagged articles too"


def test_quarantined_articles_are_excluded_from_the_language_split(db):
    """§3.4 of the plan: two gates disagreeing about one input. This figure sides with
    the article gate, and says so in its method."""
    s = _src(db, "e.example")
    _art(db, s, 3, lang="en", tone=0.5)
    _art(db, s, 4, lang="en", tone=0.5, quar="nav_soup", ver="v1")
    out = sentiment_measurability(db)
    row = next(r for r in out["rows"] if r["language"] == "en")
    assert row["n"] == 3
    assert "quarantined articles are excluded" in out["method"]


# --- C1: quarantine composition -------------------------------------------- //


def test_a_reason_that_condemned_nothing_is_absent_not_zero(db):
    """A zero-height bar reads as a measured zero. The vocabulary of possible reasons
    is not the vocabulary of reasons that FIRED, and only the second is data."""
    s = _src(db, "f.example")
    _art(db, s, 5, lang="en")
    _art(db, s, 2, lang="en", quar="nav_soup", ver="v1")
    out = quarantine_composition(db)
    reasons = {r["reason"] for r in out["rows"]}
    assert reasons == {"nav_soup"}, "only the reason that actually fired is a row"
    assert out["n"] == 2 and out["corpus_articles"] == 7
    assert "no article are absent rather than shown at zero" in out["caveat"]


def test_reasons_are_split_by_criteria_version(db):
    """The same reason under two criteria versions is two different judgements, so
    collapsing them would present a re-judged article as a single verdict."""
    s = _src(db, "g.example")
    _art(db, s, 3, lang="en", quar="nav_soup", ver="v1")
    _art(db, s, 1, lang="en", quar="nav_soup", ver="v2")
    out = quarantine_composition(db)
    keyed = {(r["reason"], r["criteria_version"]): r["n"] for r in out["rows"]}
    assert keyed == {("nav_soup", "v1"): 3, ("nav_soup", "v2"): 1}
    assert out["criteria_versions"] == ["v1", "v2"]


def test_an_empty_quarantine_is_an_empty_figure_not_a_missing_one(db):
    """A corpus with nothing quarantined must return a well-formed empty payload, so
    the frontend can render the honest empty state rather than crash or draw an axis
    through nothing."""
    s = _src(db, "h.example")
    _art(db, s, 4, lang="en")
    out = quarantine_composition(db)
    assert out["rows"] == [] and out["n"] == 0
    assert out["corpus_articles"] == 4
    assert out["method"] and out["caveat"]


# --- C5: source concentration ---------------------------------------------- //


def test_concentration_counts_live_when_the_maintained_counter_is_null(db):
    """The defect this test exists for: the first cut filtered on
    ``Source.article_count > 0``, and that column is NULLABLE and NULL on any corpus
    the background reconcile has never touched — so the figure reported an empty
    corpus while 180 real articles sat in the table. Reusing a maintained counter
    means inheriting its documented fallback (src/api/source_io.py:163-177)."""
    big, small = _src(db, "i.example"), _src(db, "j.example")
    _art(db, big, 9, lang="en")
    _art(db, small, 1, lang="fr")
    assert big.article_count is None, "the fixture must reproduce the NULL-counter case"
    out = source_concentration(db)
    assert out["n"] == 2, "both sources must appear despite the NULL counter"
    assert out["articles"] == 10
    assert out["basis"] == "live", "counted now, and it says so"


def test_the_method_string_is_fixed_so_it_can_be_translated(db):
    """A browser screenshot in Arabic caught this: the i18n engine matches an EXACT
    key, so a method sentence the server composes per-corpus can NEVER be translated
    and renders in English in all 11 non-English locales — for the very text that
    carries the figure's honesty. The basis-dependent clause therefore travels as the
    `basis` FIELD and the frontend composes it from its own keyed template.

    Guard the property directly: the same figure computed under two different bases
    must produce the SAME method string."""
    now = datetime.now(UTC).replace(tzinfo=None)
    a = _src(db, "q.example")                                  # NULL counter -> live
    b = _src(db, "r.example")
    _art(db, a, 3, lang="en")
    _art(db, b, 7, lang="en")
    live_out = source_concentration(db)
    assert live_out["basis"] == "live"

    a.article_count, a.counter_reconciled_at = 3, now
    b.article_count, b.counter_reconciled_at = 7, now
    db.flush()
    exact_out = source_concentration(db)
    assert exact_out["basis"] == "exact"

    assert live_out["method"] == exact_out["method"], (
        "the method sentence must not vary with the basis, or it cannot be keyed"
    )
    for word in ("live", "reconciled", "drifted"):
        assert word not in live_out["method"], (
            f"the method sentence still splices the basis in ({word!r}) — that is the "
            "untranslatable shape"
        )


def test_gini_is_undefined_not_zero_for_a_single_source(db):
    """gini() returns None below n=2. A Gini of 0 means perfect EQUALITY — the
    opposite claim — so None must never be rendered as 0."""
    s = _src(db, "k.example")
    _art(db, s, 5, lang="en")
    out = source_concentration(db)
    assert out["gini"] is None, "undefined, never 0"
    assert out["n"] == 1


def test_a_reconciled_counter_is_exact_and_a_stale_one_is_estimated(db):
    """basis is a DISCLOSURE, not a score: it says whether the number was verified."""
    now = datetime.now(UTC).replace(tzinfo=None)
    a = _src(db, "l.example", article_count=4, counter_reconciled_at=now)
    b = _src(db, "m.example", article_count=6, counter_reconciled_at=now)
    _art(db, a, 1, lang="en")
    out = source_concentration(db)
    assert out["basis"] == "exact" and out["counters_fresh"] == 2
    assert out["articles"] == 10, "the counters are read, not recounted"

    b.counter_reconciled_at = now - timedelta(days=9)
    db.flush()
    out2 = source_concentration(db)
    assert out2["basis"] == "estimated", "one stale member makes the whole curve estimated"


def test_the_lorenz_curve_starts_at_the_origin_and_reaches_one(db):
    """A curve that starts at the first source rather than at (0,0) is a fragment, and
    reads as less inequality than there is."""
    for i, n in enumerate((1, 2, 3, 40)):
        _art(db, _src(db, f"n{i}.example"), n, lang="en")
    out = source_concentration(db)
    assert out["curve"][0] == {"sources": 0.0, "articles": 0.0}
    assert out["curve"][-1]["sources"] == pytest.approx(1.0)
    assert out["curve"][-1]["articles"] == pytest.approx(1.0)
    xs = [p["sources"] for p in out["curve"]]
    ys = [p["articles"] for p in out["curve"]]
    assert xs == sorted(xs) and ys == sorted(ys), "a Lorenz curve is non-decreasing"
    assert out["gini"] is not None and out["gini"] > 0.5, "this corpus is very skewed"


# --- the cross-cutting honesty guard -------------------------------------- //


def test_no_figure_payload_carries_a_score_shaped_key(db):
    """The recursive no-score walkers ban score/rating/rank/trust/verdict/grade as key
    SUBSTRINGS — and note that the status word "degraded" contains "grade", which is
    how a categorical status accidentally trips the ban. Walk our own payloads."""
    banned = ("score", "rating", "rank", "trust", "verdict", "grade", "credibility")
    s = _src(db, "o.example")
    _art(db, s, 3, lang="en", tone=0.2)
    _art(db, s, 2, lang="fr", quar="nav_soup", ver="v1")

    def walk(node, path=""):
        bad = []
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                for b in banned:
                    if b in low:
                        bad.append(f"{path}.{k} (contains {b!r})")
                bad += walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                bad += walk(v, f"{path}[{i}]")
        return bad

    for name, out in (
        ("quarantine_composition", quarantine_composition(db)),
        ("sentiment_measurability", sentiment_measurability(db)),
        ("source_concentration", source_concentration(db)),
    ):
        offenders = walk(out, name)
        assert not offenders, f"score-shaped keys: {offenders}"


def test_every_figure_states_its_method_and_caveat_and_n(db):
    """The frontend renders these verbatim, so a figure that omits one ships without
    its honesty furniture and nothing downstream can put it back."""
    s = _src(db, "p.example")
    _art(db, s, 3, lang="en", tone=0.2)
    for out in (quarantine_composition(db), sentiment_measurability(db),
                source_concentration(db)):
        assert out.get("method"), "a figure must state how it was computed"
        assert out.get("caveat"), "a figure must state what it does not mean"
        assert "n" in out, "a figure must state its n"

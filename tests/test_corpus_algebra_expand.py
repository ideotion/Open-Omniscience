"""The Conjunction Lens' other two views were built, tested, and unreachable.

`analytics.conjunction` has carried `per_article_intensity` (which articles pack the most
of the N terms) and `conditional_trend` (when the conjunction was discussed) since the
lens shipped -- both unit-tested. Nothing called them: `/api/insights/corpus-algebra`
returned `corpus_algebra`'s dict verbatim, and a repo-wide grep found the two names
nowhere outside their own module and its tests. Work that exists and cannot be reached is
indistinguishable from work that does not exist.

They are now `expand=` views on the endpoint, and the properties below are what makes
that wiring rather than a new feature:

  * an expansion reads the SAME `article_ids` the call already computed, so it can never
    describe a different set than the one returned beside it;
  * the response WITHOUT `expand` is byte-identical to before -- an expansion is extra
    database work and a caller who did not ask must not pay for it;
  * an unknown token is refused by name BEFORE the work, because an ignored `expand` is a
    caller believing it received a view it never got.

`vocabulary_contrast` is the third such helper and is deliberately left unexposed. It
contrasts TWO corpora, and which two sides an `intersection` of three terms splits into is
a product question. Picking a plausible split would publish an invented semantic under a
tested function's name -- the test at the bottom pins that it stays unexposed, so the
choice is a decision rather than an omission someone quietly "fixes".
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.api.insights import _ALGEBRA_EXPANSIONS, insights_corpus_algebra
from src.database.models import Base, Keyword, KeywordMention


def _corpus() -> Session:
    """election -> 1,2,3 ; france -> 2,3,4 ; protest -> 3,4,5 (mirrors test_conjunction)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    kws = {}
    for term in ("election", "france", "protest"):
        k = Keyword(term=term, normalized_term=term)
        s.add(k)
        s.flush()
        kws[term] = k
    for term, arts in {"election": [1, 2, 3], "france": [2, 3, 4], "protest": [3, 4, 5]}.items():
        for i, aid in enumerate(arts):
            s.add(
                KeywordMention(
                    keyword_id=kws[term].id, article_id=aid, count=1 + i,
                    observed_on=date(2026, 1, 1 + aid),
                )
            )
    s.commit()
    return s


def _call(db, **kw):
    params = {"terms": "election,france", "op": "intersection", "cap": 4000,
              "expand": None, "bucket": "week", "db": db}
    params.update(kw)
    return insights_corpus_algebra(**params)


def test_without_expand_the_response_is_unchanged():
    """The back-compat property, asserted as EQUALITY rather than by eyeballing keys: a
    caller that did not opt in must get exactly what it got before, and must not silently
    start paying for two extra aggregations."""
    from src.analytics.conjunction import corpus_algebra

    db = _corpus()
    assert _call(db) == corpus_algebra(db, ["election", "france"], op="intersection", cap=4000)
    assert "intensity" not in _call(db)
    assert "trend" not in _call(db)


def test_intensity_describes_the_same_set_the_call_returned():
    """The property that makes this wiring: the expansion is computed FROM the returned
    ids, so the two halves of one response cannot disagree about which articles they mean."""
    db = _corpus()
    out = _call(db, expand="intensity")
    assert out["article_ids"] == [2, 3]
    got = {r["article_id"] for r in out["intensity"]["articles"]}
    assert got <= set(out["article_ids"]), "an expansion must not name an article outside the set"
    assert out["intensity"]["n_terms"] == 2
    # Densest first: article 3 carries both terms with more mentions than article 2.
    assert [r["article_id"] for r in out["intensity"]["articles"]] == [3, 2]
    assert out["intensity"]["method"] and out["intensity"]["caveat"]


def test_trend_describes_the_same_set_and_honours_its_bucket():
    db = _corpus()
    out = _call(db, expand="trend", bucket="day")
    assert out["trend"]["bucket"] == "day"
    assert out["trend"]["total"] > 0
    assert out["trend"]["points"], "the set has mention dates; the trend must not be empty"
    # Every bucketed count comes from the two articles in the intersection, never more.
    assert out["trend"]["total"] <= sum(1 for _ in out["article_ids"]) * len(out["trend"]["points"])
    assert out["trend"]["method"] and out["trend"]["caveat"]


def test_both_expansions_compose():
    db = _corpus()
    out = _call(db, expand="intensity,trend")
    assert "intensity" in out and "trend" in out
    assert out["op"] == "intersection", "the base payload must survive the expansions"


def test_expand_is_whitespace_and_case_tolerant():
    db = _corpus()
    assert "intensity" in _call(db, expand="  INTENSITY , ")


def test_an_unknown_expansion_is_refused_by_name_before_the_work():
    """Silently ignoring it would leave the caller believing it got a view it never got --
    the same failure the unknown-op 400 already exists to prevent."""
    db = _corpus()
    with pytest.raises(HTTPException) as exc:
        _call(db, expand="intensity,vibes")
    assert exc.value.status_code == 400
    assert "vibes" in str(exc.value.detail)
    assert "intensity" in str(exc.value.detail), "the refusal must name what IS accepted"


def test_the_unknown_op_refusal_still_wins_over_a_valid_expand():
    db = _corpus()
    with pytest.raises(HTTPException) as exc:
        _call(db, op="sideways", expand="trend")
    assert exc.value.status_code == 400


def test_an_empty_set_expands_to_empty_views_not_to_an_error():
    """`difference` of a term against itself is empty. Both helpers have an early return
    for that; the endpoint must reach it rather than crash or omit the key it promised."""
    db = _corpus()
    out = _call(db, terms="election,france,protest", op="difference", expand="intensity,trend")
    assert out["article_ids"] == [1]
    out2 = _call(db, terms="nosuchterm", op="intersection", expand="intensity,trend")
    assert out2["article_ids"] == []
    assert out2["intensity"]["articles"] == []
    assert out2["trend"]["points"] == []


def test_vocabulary_contrast_stays_unexposed_on_purpose():
    """A decision, not an omission. It contrasts TWO corpora and the endpoint has one set;
    choosing the split is a product question, and answering it here would ship an invented
    semantic under a tested function's name."""
    import inspect

    from src.analytics import conjunction
    from src.api import insights

    assert hasattr(conjunction, "vocabulary_contrast"), "the helper still exists"
    # A CALL, not a mention: the endpoint's docstring names it precisely to say why it is
    # absent, so a bare substring check would fail on the explanation for the thing it checks.
    src = inspect.getsource(insights.insights_corpus_algebra)
    assert "vocabulary_contrast(" not in src, "it must not be called from the endpoint"
    assert "contrast" not in _ALGEBRA_EXPANSIONS
    assert set(_ALGEBRA_EXPANSIONS) == {"intensity", "trend"}

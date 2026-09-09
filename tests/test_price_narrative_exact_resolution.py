"""Audit §4.1 (P0), SECOND site: the commodity price↔coverage Lead.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-09-08 visual audit named `GET /api/insights/trend?term=Dy` -- `Dy`
silently resolving to the English word "already" through `resolve_keyword`'s
`LIKE %term%` fallback, and a chart headed "Price × coverage — Dy" drawn from
that unrelated word's articles. That path was fixed by routing `queries.py`'s
display callers through `exact=True`.

`src/briefing/producers.py`'s `price_narrative` had the SAME defect and was not
in that sweep, with a worse consequence: it does not merely label a chart, it
runs a significance test against whatever keyword the fallback landed on and
publishes the result to Home as a Lead, with a "Why am I seeing this?" trail
reading "the days where you have both a price for this commodity and coverage
about it".

WHAT THE LIVE CORPUS ACTUALLY SHOWED, 2026-09-09, before the fix -- recorded
exactly, because the temptation to round it up is the thing being guarded
against. All three symbols carrying prices resolved to unrelated words (Dy ->
"already", Nd -> "indiqué", Pr -> "proposed", with 36/28/37 dated mentions), and
NO card was published from any of them: the price dates and those keywords'
article dates did not overlap, so `correlate_price_with_news` returned
`insufficient_data` with n=0. The defect was latent on that corpus.

Which is exactly why the case is CONSTRUCTED here rather than sampled. What
stood between a wrong pairing and a published Lead was a date overlap -- an
accident of corpus size, not a check. These fixtures supply the overlap and
show what the producer does with it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

pytest.importorskip("scipy", reason="price_narrative needs the [analysis] extra (scipy)")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.database.models import (  # noqa: E402
    Article,
    Base,
    CommodityPrice,
    Keyword,
    KeywordMention,
    MarketExtractionRule,
    Source,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_homograph_corpus(db, *, keyword: str) -> int:
    """A commodity symbol `Dy` with prices, and ONE keyword that merely CONTAINS
    it as a substring, with mentions on the very same days.

    The overlap is the point. `already` contains `d`+`y`… no -- it contains the
    literal substring "dy" (`alrea|dy`), which is all `LIKE %dy%` asks for, and
    it is a far more common word than any commodity, so it ranks first by
    mention count. Returns the number of articles seeded.
    """
    db.add(Source(id=1, name="Metals Wire", domain="metals.test"))
    db.add(MarketExtractionRule(
        id=1, source_id=1, category="commodity", symbol="Dy", label="Dy",
        url="https://metals.test/dy", selector=".price",
    ))
    db.add(Keyword(id=1, term=keyword, normalized_term=keyword))
    db.commit()

    today = date.today()
    days = [today - timedelta(days=i) for i in range(5, -1, -1)]
    prices = [1000.0, 1050.0, 1010.0, 1090.0, 1030.0, 1120.0]
    counts = [1, 3, 1, 4, 1, 5]   # tracks the price swings closely enough to correlate

    for d, p in zip(days, prices, strict=True):
        db.add(CommodityPrice(symbol="Dy", observed_on=d, price=p, market="lme"))

    aid = 0
    now = datetime.now(UTC)
    for d, n in zip(days, counts, strict=True):
        for _ in range(n):
            aid += 1
            db.add(Article(
                id=aid, url=f"https://metals.test/a{aid}",
                canonical_url=f"https://metals.test/a{aid}", source_id=1,
                title="T", content="c", hash=f"h{aid}",
                published_at=datetime(d.year, d.month, d.day, tzinfo=UTC), created_at=now,
            ))
            db.add(KeywordMention(keyword_id=1, article_id=aid, observed_on=d, count=1))
    db.commit()
    return aid


def test_a_substring_keyword_never_becomes_a_commoditys_coverage(db):
    """THE GUARD. "already" contains "dy"; it is not coverage of dysprosium.

    With the overlap supplied, this is verbatim what the pre-fix code publishes
    (captured by running it, 2026-09-09):

        Dy: price moves vs coverage
        Daily price change and news volume for Dy correlate +0.97 (p=0.00522, n=5).
        Why am I seeing this? On the days where you have both a price for this
        commodity and coverage about it, the price moves and the volume of
        coverage tend to rise and fall together.

    with ``card.key == "already"``. A significance-tested correspondence, its
    arithmetic shown, between dysprosium's price and an English adverb. After the
    fix the commodity resolves to nothing and is skipped -- the honest empty
    answer its sibling lenses already give.
    """
    _seed_homograph_corpus(db, keyword="already")

    from src.briefing.producers import price_narrative

    cards = price_narrative(db)
    assert cards == [], (
        "a commodity whose label and symbol have no keyword of their own must "
        "produce NO card -- got: "
        + "; ".join(f"{c.title!r} :: {c.summary!r}" for c in cards)
    )


def test_the_fixture_really_would_have_produced_a_card_without_the_guard(db):
    """ANTI-VACUITY, and the reason this file exists as its own test.

    The live corpus produced no card either -- for the wrong reason (no date
    overlap). A guard that cannot tell "correctly refused" from "nothing was
    ever going to fire" proves nothing, so prove the fixture is loaded: rename
    the SAME keyword to the commodity's own term and the SAME data must now
    publish a card. If this fails, the test above is passing vacuously and the
    fixture needs stronger correlation, not a weaker assertion.
    """
    n = _seed_homograph_corpus(db, keyword="dy")   # now an EXACT match

    from src.briefing.producers import price_narrative

    cards = price_narrative(db)
    assert cards, (
        "the fixture must be capable of producing a card when the keyword resolves "
        "exactly -- otherwise the refusal test above is vacuous"
    )
    assert cards[0].key == "dy"
    assert len(cards[0].article_ids) == n


def test_the_resolver_itself_refuses_the_substring_under_exact(db):
    """The unit beneath both: the same probe, at the resolution step, so a
    failure here says WHERE it broke rather than only that a card appeared."""
    _seed_homograph_corpus(db, keyword="already")

    from src.analytics.queries import resolve_keyword

    fuzzy = resolve_keyword(db, "Dy")
    exact = resolve_keyword(db, "Dy", exact=True)
    assert fuzzy is not None and fuzzy.normalized_term == "already", (
        "the fuzzy fallback is expected to still do this -- it is deliberately kept "
        "for human-typed search boxes; if it no longer does, this guard is testing "
        "a hazard that no longer exists and should be re-derived"
    )
    assert exact is None, "exact resolution must return nothing, never the nearest match"

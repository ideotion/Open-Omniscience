"""Audit finding 2026-07-17: price_narrative's Card used the raw commodity/ticker
``symbol`` as its ``key``, but the correlation is actually computed against a
RESOLVED KEYWORD whose ``normalized_term`` can differ from the symbol (e.g. the
ticker "XAU" vs the keyword "gold" that articles are actually indexed under).
Clicking the card re-ran a search for the wrong string and found nothing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
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


def test_price_narrative_key_is_the_resolved_keyword_not_the_raw_symbol(db):
    from src.briefing.producers import price_narrative

    db.add(Source(id=1, name="Metals Wire", domain="metals.test"))
    db.commit()
    # The rule's raw symbol is a ticker; the human label resolves to a DIFFERENT
    # keyword than the ticker string itself -- exactly the mismatch that made the
    # old `key=symbol` unclickable.
    db.add(MarketExtractionRule(
        id=1, source_id=1, category="commodity", symbol="XAU", label="Gold",
        url="https://metals.test/gold", selector=".price",
    ))
    db.add(Keyword(id=1, term="gold", normalized_term="gold"))
    db.commit()

    today = date.today()
    days = [today - timedelta(days=i) for i in range(5, -1, -1)]  # 6 days, oldest first
    prices = [1000.0, 1050.0, 1010.0, 1090.0, 1030.0, 1120.0]  # varies enough to correlate
    article_counts = [1, 3, 1, 4, 1, 5]  # roughly tracks the price swings

    for d, p in zip(days, prices, strict=True):
        db.add(CommodityPrice(symbol="XAU", observed_on=d, price=p, market="lbma"))

    aid = 0
    now = datetime.now(UTC)
    for d, n in zip(days, article_counts, strict=True):
        for _ in range(n):
            aid += 1
            db.add(Article(
                id=aid, url=f"https://metals.test/a{aid}", canonical_url=f"https://metals.test/a{aid}",
                source_id=1, title="T", content="c", hash=f"h{aid}",
                published_at=datetime(d.year, d.month, d.day, tzinfo=UTC),
                created_at=now,
            ))
            db.add(KeywordMention(keyword_id=1, article_id=aid, observed_on=d, count=1))
    db.commit()

    cards = price_narrative(db)
    assert cards, "expected a price_narrative card (enough overlapping points to correlate)"
    c = cards[0]
    # The key is the RESOLVED keyword's normalized term ("gold"), never the raw
    # ticker symbol ("XAU") the price series happens to use.
    assert c.key == "gold"
    assert c.key != "XAU"
    # And it carries the exact analyzed article set (every mention of the resolved
    # keyword), so a click-through opens real articles instead of a dead search.
    assert c.article_ids
    assert set(c.article_ids) == set(range(1, aid + 1))


def test_price_narrative_a_null_result_is_not_a_lead(db):
    """Row 14 (2026-07-18 field export): "CORN r=0.17 p=0.721; COFFEE p=0.712; BRENT
    p=0.514" -- statistically null results were surfaced as Leads. A non-significant
    (or too-weak) correlation must produce NO card; it stays visible in /#markets."""
    from src.briefing.producers import price_narrative

    db.add(Source(id=1, name="Grain Wire", domain="grain.test"))
    db.commit()
    db.add(MarketExtractionRule(
        id=1, source_id=1, category="commodity", symbol="ZC", label="Corn",
        url="https://grain.test/corn", selector=".price",
    ))
    db.add(Keyword(id=1, term="corn", normalized_term="corn"))
    db.commit()

    today = date.today()
    days = [today - timedelta(days=i) for i in range(7, -1, -1)]
    prices = [1000.0, 1010.0, 1000.0, 1010.0, 1000.0, 1010.0, 1000.0, 1010.0]  # oscillates
    article_counts = [1, 2, 1, 3, 2, 1, 3, 2]  # noisy, not tracking the oscillation -> r~0, p=1.0

    for d, p in zip(days, prices, strict=True):
        db.add(CommodityPrice(symbol="ZC", observed_on=d, price=p, market="cbot"))

    aid = 0
    now = datetime.now(UTC)
    for d, n in zip(days, article_counts, strict=True):
        for _ in range(n):
            aid += 1
            db.add(Article(
                id=aid, url=f"https://grain.test/a{aid}", canonical_url=f"https://grain.test/a{aid}",
                source_id=1, title="T", content="c", hash=f"h{aid}",
                published_at=datetime(d.year, d.month, d.day, tzinfo=UTC),
                created_at=now,
            ))
            db.add(KeywordMention(keyword_id=1, article_id=aid, observed_on=d, count=1))
    db.commit()

    assert price_narrative(db) == []

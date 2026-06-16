"""
Card-shape contract for every briefing producer (audit PR F).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Complements test_briefing.py (which checks the evidence-tier ``_trigger``): this
file asserts the FULL card SHAPE for every card any producer in
``src/briefing/producers.py`` emits over a corpus that fires a broad set of them —
required fields are non-empty strings, the bucket is valid, the card serialises to
a dict, and (the honesty guard) neither the ``Card`` dataclass NOR the runtime
``signal``/``evidence`` dicts carry a composite-score key. A producer that grows a
score field, an empty caveat, or an invalid bucket fails here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.briefing import producers as P
from src.briefing.card import (
    _BANNED_FIELD_FRAGMENTS,
    BUCKETS,
    Card,
    assert_no_score_fields,
)
from src.database.models import Article, Base, Source


@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    """A small indexed corpus across two countries/sources that fires several
    producers (rising/diet/lonely/coverage…). Mirrors test_briefing.py's pattern."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(name="Beta", domain="beta.test", country="us"))
    s.commit()

    now = datetime.now(UTC)
    for i in range(14):
        src_id = 1 if i % 3 else 2  # Alpha-heavy -> a concentrated reading diet
        when = now - timedelta(days=i % 5)
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=src_id,
            title=f"Story {i}",
            hash=f"h{i}",
            language="en",
            content=(
                "The election dominated the election news as election coverage spread."
                if i < 7
                else "Markets moved on quiet trading and steady prices today."
            ),
            published_at=when,
            created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr" if src_id == 1 else "us")
    return s


def _check_no_score_keys(d: dict, where: str) -> None:
    """No runtime payload dict may carry a COMPOSITE-score key (trust_score,
    credibility, quality_score, veracity, reliability_score, bias_score, verdict).
    Bare measured-value keys are allowed; the dataclass guard covers field names."""
    for k in d:
        kl = str(k).lower()
        bad = next((frag for frag in _BANNED_FIELD_FRAGMENTS if frag in kl), None)
        assert bad is None, f"{where}: key {k!r} implies a forbidden composite score ({bad})"


def _assert_card_shape(card: object, producer_name: str) -> None:
    assert isinstance(card, Card), f"{producer_name}: produced a non-Card object"
    for fld in ("type", "title", "summary", "bucket", "method", "caveat"):
        val = getattr(card, fld)
        assert isinstance(val, str) and val.strip(), (
            f"{producer_name}: card.{fld} must be a non-empty string (honesty: every "
            "card states its method AND its caveat)"
        )
    assert card.bucket in BUCKETS, f"{producer_name}: card.bucket {card.bucket!r} not in BUCKETS"
    _check_no_score_keys(card.signal or {}, f"{producer_name}.signal")
    for ev in card.evidence or []:
        if isinstance(ev, dict):
            _check_no_score_keys(ev, f"{producer_name}.evidence[]")
    out = card.to_dict()
    assert isinstance(out, dict) and out.get("id"), f"{producer_name}: to_dict() missing id"


def test_card_dataclass_has_no_score_field():
    """The import-time honesty guard still holds for the live Card dataclass."""
    assert_no_score_fields(Card)  # raises CardSchemaError if a score field is added


def test_every_producer_emits_schema_valid_cards(corpus):
    """Run EVERY default producer over the corpus; every card it emits must be
    schema-valid, validly bucketed, serialisable, and score-free."""
    fired = 0
    for name, producer in P._DEFAULT_PRODUCERS:
        cards = producer(corpus) or []
        for card in cards:
            _assert_card_shape(card, name)
            fired += 1
    assert fired >= 3, "the corpus fixture should fire several producers (sanity floor)"


def test_producer_failures_are_isolated_not_fatal():
    """registry.run_all must isolate a misbehaving producer (one bad producer can
    never blank the whole feed) — a registered raiser is logged, not propagated."""
    from src.briefing import registry

    def _boom(_session):
        raise RuntimeError("boom")

    registry.register("audit_boom_producer", _boom)
    try:
        # No session is fine — _boom raises before touching it; run_all swallows it.
        cards = registry.run_all(object())
        assert isinstance(cards, list)  # did not raise
    finally:
        # Restore the registry so we don't leak the bad producer into other tests.
        registry._REGISTRY = [(n, p) for (n, p) in registry._REGISTRY if n != "audit_boom_producer"]

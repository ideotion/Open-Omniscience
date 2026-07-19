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
    CardSchemaError,
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


def _mk(**kw):
    base = dict(
        type="rising", title="x", summary="s", bucket="rising", method="m", caveat="c"
    )
    base.update(kw)
    return Card(**base)


def test_translatable_title_template_and_vars_roundtrip():
    """S4.5: a card may carry a TRANSLATABLE title = a fixed template + language-neutral
    data vars; both survive to_dict for the UI's OOI18N.tf(). The English `title` stays
    the fallback (additive)."""
    c = _mk(title="“inflation” is rising", title_i18n="“{term}” is rising",
            title_vars={"term": "inflation"})
    d = c.to_dict()
    assert d["title"] == "“inflation” is rising"          # English fallback preserved
    assert d["title_i18n"] == "“{term}” is rising"        # keyable frame
    assert d["title_vars"] == {"term": "inflation"}       # untranslated data
    # a card WITHOUT a template is byte-compatible (empty defaults, no crash)
    plain = _mk().to_dict()
    assert plain["title_i18n"] == "" and plain["title_vars"] == {}


def test_translatable_title_placeholder_must_have_a_var():
    """A {name} in the template with no matching var would render a literal “{name}” —
    a broken frame. It must fail loudly, never ship."""
    with pytest.raises(CardSchemaError):
        _mk(title_i18n="“{term}” near {place}", title_vars={"term": "x"})


def test_translatable_title_vars_must_be_scalars():
    """title_vars carry DATA the frame interpolates — JSON scalars only, never a dict/list
    that could smuggle structure past the translator."""
    with pytest.raises(CardSchemaError):
        _mk(title_i18n="“{term}” is rising", title_vars={"term": ["not", "scalar"]})


def test_rising_producer_emits_a_translatable_title(corpus):
    """S4.5 reference producer: `rising_now` cards carry title_i18n/title_vars whose
    template interpolates back to the English title, with the keyword term left as data."""
    cards = P.rising_now(corpus) or []
    if not cards:  # the corpus fixture may not fire `rising_now`
        pytest.skip("rising_now did not fire on this corpus fixture")
    for c in cards:
        assert c.title_i18n == "“{term}” is rising"
        term = c.title_vars.get("term")
        assert term and c.title_i18n.replace("{term}", term) == c.title


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


def test_f1_producers_carry_article_ids():
    """Field diagnostics 2026-07-01 (F1): these producers emitted cards with NO
    ``article_ids``, so clicking one ran a synthetic-seed text search (e.g.
    ``heatwave|fr|France|2026-06-05``, ``ownership-change``) that loaded ~0 — the card
    LOST its corpus. Each recoverable one now carries its exact article set so the click
    opens ``openAnalysisForIds`` over precisely those articles. Guarded at the SOURCE: the
    small fixture can't reliably fire weather/ownership/lineage, and this is exactly the
    line that regressed (a Card without ``article_ids``)."""
    import inspect

    # The first four landed in PR #513; framing_split + emotion_profile were the two the
    # "do we forget anything?" re-audit (2026-07-01) caught still holding an exact analysed
    # article set — framing_split its ``rows``, emotion_profile the mention articles the
    # profile was computed over — yet shipping without ``article_ids``.
    for fn in (
        P.lonely_signal,
        P.weather_corroboration,
        P.ownership_change,
        P.story_lineage,
        P.framing_split,
        P.emotion_profile_card,
    ):
        assert "article_ids=" in inspect.getsource(fn), (
            f"{fn.__name__} must pass article_ids to its Card so the click opens the exact "
            "corpus (F1 home-card hard-linking; field diagnostics 2026-07-01)"
        )


def test_lonely_signal_card_carries_its_article_when_it_fires(corpus):
    """Runtime check where the fixture allows it: if lonely_signal fires, its card carries
    the representative article id (a non-empty, hard-linked corpus), not an empty set."""
    for card in P.lonely_signal(corpus) or []:
        assert card.article_ids and all(isinstance(i, int) for i in card.article_ids), (
            "a lonely_signal card must hard-link its single article (F1)"
        )


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


def test_run_all_drops_exact_type_key_duplicates_across_producers():
    """S5.1 (Leads-calibration cross-card dedup belt): two DIFFERENT producers that
    happen to emit the SAME (type, key) card must not both survive into the feed --
    the belt beneath each producer's own dedup key, loudly logged (never silent)."""
    from src.briefing import registry
    from src.briefing.card import Card

    def _one(_session):
        return [Card(type="audit_dup", title="t1", summary="s1", bucket="context",
                     method="m", caveat="c", key="dup-key")]

    def _two(_session):
        return [Card(type="audit_dup", title="t2", summary="s2", bucket="context",
                     method="m", caveat="c", key="dup-key")]

    registry.register("audit_dup_producer_1", _one)
    registry.register("audit_dup_producer_2", _two)
    try:
        cards = registry.run_all(object())
        dups = [c for c in cards if c.type == "audit_dup" and c.key == "dup-key"]
        assert len(dups) == 1, dups
        assert dups[0].title == "t1"  # the FIRST (registration-order) occurrence survives
    finally:
        registry._REGISTRY = [
            (n, p) for (n, p) in registry._REGISTRY
            if n not in ("audit_dup_producer_1", "audit_dup_producer_2")
        ]

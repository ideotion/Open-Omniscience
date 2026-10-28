"""Applying the deduced source topics writes in chunks, not one source at a time, and keeps what the ORM write did.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``apply_source_topics`` used to ``session.get`` every candidate and flush one UPDATE per changed source INSIDE the write window: 86,470
sources held it for 27 to 30 s (18 s when there was nothing to add), and every other writer queued behind it. It now reads and writes
``SOURCE_TOPICS_CHUNK`` sources per statement (R390, ``docs`` figures in ``_write_topics_in_bulk``). A bulk UPDATE skips the ORM's
``before_update`` hook, so the ``feed_key`` it maintained is written in the same statement; these tests pin that, the final state against
the old per-source rule, the stand-in skip, an edit made between the decide and the apply phase, and that a second run writes nothing.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from src.analytics import source_topics as st
from src.database.feed_key import feed_key
from src.database.models import Base, Source
from src.database.stand_in import SOURCE_DOMAIN_PREFIX

TOPICS = ["politics", "economy"]


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(factory, rows):
    s = factory()
    for r in rows:
        s.add(Source(**r))
    s.commit()
    ids = [x[0] for x in s.execute(select(Source.id).order_by(Source.id))]
    s.close()
    return ids


def _make_every_feed_key_stale(factory):
    """The model's ``before_insert`` hook derives ``feed_key`` from ``rss_url``, so a stale value can only be planted round the ORM."""
    s = factory()
    s.execute(text("UPDATE sources SET feed_key = 'STALE'"))
    s.commit()
    s.close()


def _state(factory):
    s = factory()
    try:
        return [tuple(r) for r in s.execute(select(Source.id, Source.tags, Source.feed_key).order_by(Source.id))]
    finally:
        s.close()


def _legacy_tags(tags, topics):
    """The rule the per-source path applied (the module's old loop, written out): union, additive, order kept."""
    existing = [t.strip() for t in (tags or "").split(",") if t.strip()]
    fresh = [t for t in topics if t not in set(existing)]
    return ",".join(existing + fresh) if fresh else tags


def _candidates(monkeypatch, ids, topics=TOPICS):
    monkeypatch.setattr(st, "source_topic_candidates", lambda *a, **k: {"candidates": [{"id": i, "topics": topics} for i in ids]})


def test_a_stale_feed_key_is_healed_as_the_orm_write_did(factory, monkeypatch):
    ids = _seed(factory, [{"name": "a", "domain": "a.example", "rss_url": "https://a.example/feed", "tags": "news"}])
    _make_every_feed_key_stale(factory)
    _candidates(monkeypatch, ids)
    assert st.apply_source_topics(factory()) == {"sources_updated": 1, "tags_added": 2}
    [(_, tags, key)] = _state(factory)
    assert tags == "news,politics,economy"
    assert key == feed_key("https://a.example/feed") != "STALE"


def test_the_final_state_equals_the_per_source_rule(factory, monkeypatch):
    rows = [
        {"name": "none", "domain": "n.example", "rss_url": "https://n.example/f", "tags": None},
        {"name": "empty", "domain": "e.example", "rss_url": "https://e.example/f", "tags": ""},
        {"name": "news", "domain": "w.example", "rss_url": "https://w.example/f", "tags": "news"},
        {"name": "has one", "domain": "h.example", "rss_url": "https://h.example/f", "tags": "news, politics"},
        {"name": "has both", "domain": "b.example", "rss_url": "https://b.example/f", "tags": "economy,politics"},
        {"name": "no feed", "domain": "o.example", "rss_url": None, "tags": "news"},
    ]
    ids = _seed(factory, rows)
    _make_every_feed_key_stale(factory)
    before = {i: t for i, t, _ in _state(factory)}
    _candidates(monkeypatch, ids)
    result = st.apply_source_topics(factory())
    after = _state(factory)
    expected = {i: _legacy_tags(before[i], TOPICS) for i in ids}
    assert {i: t for i, t, _ in after} == expected
    assert result["sources_updated"] == sum(1 for i in ids if expected[i] != before[i])
    # a row the rule changed is healed by the write (the ORM hook's side effect); a row it left alone is not written at all, as before
    assert [k for _, _, k in after] == [feed_key(r["rss_url"]) if expected[i] != before[i] else "STALE" for i, r in zip(ids, rows, strict=True)]


def test_a_stand_in_source_and_a_vanished_source_are_skipped(factory, monkeypatch):
    ids = _seed(
        factory,
        [
            {"name": "real", "domain": "r.example", "rss_url": "https://r.example/f", "tags": "news"},
            {"name": "stand-in", "domain": SOURCE_DOMAIN_PREFIX + "x", "rss_url": None, "tags": "news"},
        ],
    )
    _candidates(monkeypatch, [*ids, 999_999])  # the last id does not exist: deleted between the decide and the apply phase
    assert st.apply_source_topics(factory()) == {"sources_updated": 1, "tags_added": 2}
    assert [t for _, t, _ in _state(factory)] == ["news,politics,economy", "news"]


def test_an_edit_made_between_decide_and_apply_is_not_clobbered(factory, monkeypatch):
    ids = _seed(factory, [{"name": "a", "domain": "a.example", "rss_url": "https://a.example/f", "tags": "news"}])
    _candidates(monkeypatch, ids, ["politics"])
    other = factory()
    other.query(Source).filter(Source.id == ids[0]).update({"tags": "news,politics,curated"})  # the operator's edit, after the decide
    other.commit()
    assert st.apply_source_topics(factory()) == {"sources_updated": 0, "tags_added": 0}
    assert [t for _, t, _ in _state(factory)] == ["news,politics,curated"]


def test_a_second_run_writes_nothing(factory, monkeypatch):
    ids = _seed(factory, [{"name": f"s{i}", "domain": f"s{i}.example", "rss_url": f"https://s{i}.example/f", "tags": "news"} for i in range(30)])
    _candidates(monkeypatch, ids)
    assert st.apply_source_topics(factory())["sources_updated"] == 30
    settled = _state(factory)
    writes: list[str] = []
    s = factory()
    event.listen(s.get_bind(), "before_cursor_execute", lambda c, cur, stmt, p, ctx, many: writes.append(stmt.lstrip()[:6].upper()))
    assert st.apply_source_topics(s) == {"sources_updated": 0, "tags_added": 0}
    assert "UPDATE" not in writes, "an idempotent re-run issued an UPDATE"
    assert _state(factory) == settled


def test_statements_do_not_grow_with_the_number_of_sources(factory, monkeypatch):
    # a chunk of one IS the per-source shape; 999 is the variable ceiling the constant exists to stay under
    assert 100 <= st.SOURCE_TOPICS_CHUNK <= 999
    n = 2 * st.SOURCE_TOPICS_CHUNK + 1
    ids = _seed(factory, [{"name": f"s{i}", "domain": f"s{i}.example", "rss_url": f"https://s{i}.example/f", "tags": "news"} for i in range(n)])
    _candidates(monkeypatch, ids)
    s = factory()
    count = [0]
    event.listen(s.get_bind(), "before_cursor_execute", lambda *a: count.__setitem__(0, count[0] + 1))
    assert st.apply_source_topics(s)["sources_updated"] == n
    chunks = math.ceil(n / st.SOURCE_TOPICS_CHUNK)
    # a read and a write per chunk, plus the transaction's own statements; the per-source shape issued more than n
    assert count[0] <= 2 * chunks + 6, f"{count[0]} statements for {n} sources in {chunks} chunks"
    assert all(t == "news,politics,economy" for _, t, _ in _state(factory))

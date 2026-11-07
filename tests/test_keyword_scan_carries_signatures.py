"""The keyword scan hands the export each ranked keyword's language signature, so the export no
longer reads the mention rows of its window a second time.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

C9 (cold ``/keywords`` on 9.9 M mentions, 2026-11-07): ``fetch_signatures`` re-read the mention rows of
every exported keyword to count their articles per language, which the ordered scan had already counted
(``counts`` in ``scan_keywords``) and thrown away. The scan now keeps, for each row the ranker keeps, that
count; ``signatures_for`` turns it back into the ``language_signature`` dict and reads the mention rows
only for a row that carries none.

What is pinned, and why each line is not a restatement of the implementation:

* the signature built from what the ranker carried is EQUAL to the one the old read builds, in both of the
  ranker's modes (heaps, and the SQLite spill) and with the dict's KEY ORDER compared, because the export
  prints the dict in that order and an unordered ``==`` would not see a reordering;
* a keyword in one language is derived (``{dominant: articles}``), an orphan has the empty signature, and a
  row that carries nothing falls back to the read (so a caller of ``Ranker.add`` that passes no counts keeps
  working);
* the heap's row budget counts a row that carries a signature for what it costs, and counts a one-language
  row for exactly one row, so ``memory_plan`` and ``ROW_BYTES`` stay as they were;
* the constants that price a signature cover a measured tuple.
"""

from __future__ import annotations

import gc
import random
import tracemalloc
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import src.analytics.keyword_log_export as kle
import src.analytics.keyword_log_scan as kls
from src.database.models import Article, Base, Keyword, KeywordMention, Source

LANGS = ["en", "fr", "de", None, "ru", "es"]


def _store(tmp_path: Path):
    """Articles in six languages (one with none), keywords of every shape: one language, several, an
    orphan, and ties between languages (the dominant one is then the code ascending)."""
    path = tmp_path / "sig.db"
    eng = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    rnd = random.Random(11)
    with sessionmaker(bind=eng, future=True)() as s:
        s.add_all([Source(name=f"S{i}", domain=f"s{i}.test") for i in range(4)])
        s.commit()
        s.add_all(
            Article(url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1 + i % 4,
                    title="t", content="c", hash=f"{i:064d}", language=LANGS[i % len(LANGS)])
            for i in range(240)
        )
        s.commit()
        s.add_all(Keyword(term=f"k{i}", normalized_term=f"k{i}", language=LANGS[i % 3]) for i in range(1, 61))
        s.commit()
        rows = []
        for kid in range(1, 61):
            if kid % 9 == 0:
                continue  # an orphan
            if kid % 4 == 0:  # one language: the articles whose index is 0 mod 6 are all English
                ids = rnd.sample([a for a in range(1, 241) if (a - 1) % 6 == 0], 7)
            else:
                ids = rnd.sample(range(1, 241), rnd.randrange(2, 90))
            rows += [
                {"keyword_id": kid, "article_id": a, "count": rnd.randrange(1, 4),
                 "observed_on": date(2026, 1 + a % 9, 1 + a % 27), "source_id": 1 + (a - 1) % 4}
                for a in ids
            ]
        s.bulk_insert_mappings(KeywordMention, rows)
        s.commit()
    sess = sessionmaker(bind=eng, future=True)()

    @event.listens_for(eng, "connect")
    def _q(dbapi, _rec):  # noqa: ANN001
        dbapi.execute("PRAGMA query_only=ON")

    return sess


def _scanned(db, tmp_path, *, heap_rows):
    maps = kls.ArticleMaps(db, lambda: None)
    src_articles = dict(db.execute(kls.text("SELECT source_id, COUNT(*) FROM articles GROUP BY source_id")).fetchall())
    ranker = kls.Ranker(0, 10**6, heap_rows=heap_rows, spill_dir=tmp_path, disk_check=None)
    kls.scan_keywords(db, maps, src_articles, ranker, check=lambda: None)
    return maps, ranker


@pytest.mark.parametrize("heap_rows", [10**9, 5], ids=["heaps", "spill"])
def test_the_carried_signature_equals_the_reread_one_key_order_included(tmp_path, heap_rows):
    db = _store(tmp_path)
    try:
        maps, ranker = _scanned(db, tmp_path, heap_rows=heap_rows)
        assert ranker.spilled == (heap_rows == 5)
        rows = [r for lg in ranker.totals() for r in ranker.rows(lg, sigs=True)]
        assert len(rows) == 60
        carried = kle.signatures_for(db, maps, rows, 6)
        reread = kle.fetch_signatures(db, maps, [r[0] for r in rows])
        assert {k: list(v.items()) for k, v in carried.items()} == {k: list(v.items()) for k, v in reread.items()}
        assert any(len(v) > 1 for v in carried.values()) and any(len(v) == 1 for v in carried.values())
        orphans = [r[0] for r in rows if r[5] is None]
        assert orphans and not any(k in carried for k in orphans)
    finally:
        db.close()
        ranker.close()


def test_signatures_for_reads_nothing_when_every_row_carried_one(tmp_path, monkeypatch):
    db = _store(tmp_path)
    try:
        maps, ranker = _scanned(db, tmp_path, heap_rows=10**9)
        rows = [r for lg in ranker.totals() for r in ranker.rows(lg, sigs=True)]
        monkeypatch.setattr(kle, "fetch_signatures", lambda *a, **k: pytest.fail("the mention rows were read"))
        assert kle.signatures_for(db, maps, rows, 6)
    finally:
        db.close()
        ranker.close()


def test_a_row_that_carried_nothing_is_read(tmp_path):
    r = kls.Ranker(0, 10, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    r.add("en", 3, 5, 2, None, None, "en")  # no counts: the pre-change call
    r.add("en", 4, 0, 0, None, None, None)  # an orphan carries the empty signature whatever else
    got = list(r.rows("en", sigs=True))
    assert got == [(3, 5, 2, None, None, "en", None), (4, 0, 0, None, None, None, None)]

    class _Maps:
        pass

    asked: list = []
    real = kle.fetch_signatures
    kle.fetch_signatures = lambda db, maps, kids: asked.append(list(kids)) or {3: {"en": 2}}
    try:
        assert kle.signatures_for(None, _Maps(), got, 6) == {3: {"en": 2}}
    finally:
        kle.fetch_signatures = real
    assert asked == [[3]], "only the row with no signature is read, never the orphan"


def test_pack_and_unpack_keep_the_order_the_scan_met_the_languages():
    names = ["?", "en", "fr", "de"]
    packed = kls.pack_signature({2: 5, 1: 9, 3: 1}, names)
    assert packed == ("fr", 5, "en", 9, "de", 1)
    assert list(kls.unpack_signature("en", 15, packed).items()) == [("fr", 5), ("en", 9), ("de", 1)]
    assert kls.pack_signature({1: 15}, names) == () and kls.unpack_signature("en", 15, ()) == {"en": 15}
    assert kls.unpack_signature(None, 0, None) == {} and kls.unpack_signature("en", 3, None) is None


def test_a_one_language_row_costs_one_row_and_a_wide_one_costs_more(tmp_path):
    r = kls.Ranker(0, 10**6, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    names = [f"l{i}" for i in range(20)]
    for kid in range(1, 101):
        r.add("l1", kid, 10, 5, None, None, "l1", {1: 5}, names)
    assert r._units == r._held == 100
    wide = dict.fromkeys(range(1, 11), 3)
    for kid in range(101, 111):
        r.add("l1", kid, 10, 30, None, None, "l1", wide, names)
    per_wide = kls._sig_units(kls.pack_signature(wide, names))
    assert per_wide >= 3 and r._held == 110 and r._units == 100 + 10 * per_wide


def test_the_budget_trips_earlier_for_wide_rows_than_for_narrow_ones(tmp_path):
    names = [f"l{i}" for i in range(20)]

    def rows_before_spill(counts):
        r = kls.Ranker(0, 10**6, heap_rows=200, spill_dir=tmp_path, disk_check=None)
        try:
            kid = 0
            while not r.spilled:
                kid += 1
                r.add("l1", kid, 10, sum(counts.values()), None, None, "l1", counts, names)
            return kid
        finally:
            r.close()

    narrow, wide = rows_before_spill({1: 5}), rows_before_spill(dict.fromkeys(range(1, 11), 3))
    assert narrow == 201 and wide < 100


def test_a_replaced_heap_row_swaps_its_cost_for_the_new_ones(tmp_path):
    names = [f"l{i}" for i in range(20)]
    r = kls.Ranker(0, 2, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    wide = dict.fromkeys(range(1, 11), 3)
    r.add("l1", 1, 1, 30, None, None, "l1", wide, names)
    r.add("l1", 2, 2, 30, None, None, "l1", wide, names)
    full = r._units
    r.add("l1", 3, 9, 5, None, None, "l1", {1: 5}, names)  # beats the lowest: replaces a wide row
    assert r._held == 2 and r._units == full - kls._sig_units(kls.pack_signature(wide, names)) + 1
    r.add("l1", 4, 0, 5, None, None, "l1", {1: 5}, names)  # cannot rank: nothing changes
    assert r._held == 2


def test_signature_constants_cover_the_measured_tuple_size():
    """SIG_BASE_BYTES + SIG_PAIR_BYTES * languages is a BOUND on a signature tuple's Python allocation."""
    names = [kls.sys.intern(f"lang{i}") for i in range(40)]
    for width in (2, 3, 5, 10, 20, 40):
        gc.collect()
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            held = [kls.pack_signature({i: 1000 + j * 7 + i for i in range(width)}, names) for j in range(2000)]
            per = (tracemalloc.get_traced_memory()[0] - base) / len(held)
        finally:
            tracemalloc.stop()
        assert per <= kls.SIG_BASE_BYTES + kls.SIG_PAIR_BYTES * width, (width, per)
        assert per >= (kls.SIG_BASE_BYTES + kls.SIG_PAIR_BYTES * width) * 0.4, (width, per)  # not sized far above


def test_the_ranker_budget_constants_the_plan_reads_are_unchanged():
    """The signature is priced by row units, not by moving the constants other tests and the plan pin."""
    assert (kls.ROW_BYTES, kls.HEAP_SHARE, kls.SPILL_ROW_BYTES) == (200, 0.10, 120)
    assert kls.memory_plan(64 * 2**30)["heap_rows"] == int(64 * 2**30 * 0.10 / 200)

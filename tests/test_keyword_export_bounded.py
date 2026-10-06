"""The keyword-log export holds a BATCH in memory, never the corpus (the "All keywords" crash).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-09-30: creating the "All keywords" zip from Diagnostics killed the app on
6-8 GB machines. The cause (measured on a synthetic 2 M-keyword database: 4.4 GB for the zip,
776 MB for the digest the bundle takes, ~5x that at the operator's 11 M keywords) was that the
export built a dict per keyword of the whole window, then the whole archive in a ``BytesIO`` up
to nine times while it trimmed to the byte cap. ``src/analytics/keyword_log_scan.py`` (the scan
and the ranking) and ``src/analytics/keyword_log_export.py`` (the archive) replace that.

What is pinned here, and why each line is not a restatement of the implementation:

* the scan and the ranking are compared with a PLAIN dict-based reference written from the
  documented rules, in both of the ranker's modes (heaps, and the SQLite spill that takes over
  when the rows would pass the budget) -- the two modes must be indistinguishable;
* the archive is identical whichever mode ranked it, and the cap arithmetic is disclosed
  (``in_archive + omitted == window``) however the window was cut;
* a refusal (memory short, disk short) leaves NO scratch file and says why, with numbers;
* what the export holds does not grow with the window (tracemalloc, not a guess);
* the constants that turn memory into a row budget are checked against a measurement.

The end-to-end contract (byte-identical json and shards, and a digest identical apart from the six
keys it gained, against the implementation this replaces) was checked by
``differential_keyword_export_normalised.py`` (shared under ``keyword-export/``, a copy of
``differential_keyword_export.py`` that sets those six keys aside) on random databases; it is not
repeated here because it needs the old code.
"""

from __future__ import annotations

import asyncio
import errno
import gc
import io
import json
import os
import random
import sqlite3
import tempfile
import tracemalloc
import types
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import keyword_log_export as kle
from src.analytics import keyword_log_scan as kls
from src.database.models import Base

LANGS = ["en", "fr", "de", None, "", "zh"]


# --------------------------------------------------------------------------- fixtures


def _build(path: Path, seed: int, *, articles: int, keywords: int, with_boilerplate: bool = True):
    """A small corpus with the shapes that decide ordering: orphans (most keywords), heavy ties
    on mentions, NULL and empty languages, mentions naming an article that does not exist, NULL
    dates, and one boilerplate keyword (90 % of it in one source that is 25 % of ... itself)."""
    rnd = random.Random(seed)
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path)
    n_src = 6
    con.executemany(
        "INSERT INTO sources(id,name,domain,status) VALUES (?,?,?,'unqualified')",
        [(i + 1, f"s{i}", f"s{i}.test") for i in range(n_src)],
    )
    arts = [
        (i + 1, f"u{i}", f"u{i}", rnd.randint(1, n_src), "t", "x", rnd.choice(LANGS), f"h{i:063d}")
        for i in range(articles)
    ]
    con.executemany(
        "INSERT INTO articles(id,url,canonical_url,source_id,title,content,language,hash)"
        " VALUES (?,?,?,?,?,?,?,?)",
        arts,
    )
    kws = []
    for i in range(keywords):
        ent = rnd.random() < 0.2
        term = f"Term{i}"
        kws.append(
            (i + 1, term, term.lower(), rnd.choice(LANGS), int(ent),
             rnd.choice(["person", "org"]) if ent else None)
        )
    con.executemany(
        "INSERT INTO keywords(id,term,normalized_term,language,is_entity,entity_type)"
        " VALUES (?,?,?,?,?,?)",
        kws,
    )
    pool = rnd.sample(range(1, keywords + 1), max(2, keywords // 4))
    seen, rows = set(), []
    for kid in pool:
        for _ in range(rnd.choice([1, 1, 2, 3, 6, 15])):
            aid = rnd.randint(1, articles) if rnd.random() > 0.02 else articles + rnd.randint(1, 9)
            if (kid, aid) in seen:
                continue
            seen.add((kid, aid))
            d = None if rnd.random() < 0.1 else f"2026-0{rnd.randint(1, 9)}-{rnd.randint(10, 28)}"
            rows.append((kid, aid, rnd.choice([1, 1, 2, 2, 3]), d, rnd.randint(1, n_src)))
    if with_boilerplate:
        # Source 99 has 30 articles; the keyword below is in 27 of them and nowhere else.
        con.execute("INSERT INTO sources(id,name,domain,status) VALUES (99,'wire','w.test','unqualified')")
        base = articles + 100
        con.executemany(
            "INSERT INTO articles(id,url,canonical_url,source_id,title,content,language,hash)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(base + j, f"w{j}", f"w{j}", 99, "t", "x", "en", f"w{j:063d}") for j in range(30)],
        )
        kid = keywords + 1
        con.execute(
            "INSERT INTO keywords(id,term,normalized_term,language,is_entity) VALUES (?,?,?,?,0)",
            (kid, "Boilerplate", "boilerplate", "en"),
        )
        rows += [(kid, base + j, 1, "2026-05-01", 99) for j in range(27)]
    con.executemany(
        "INSERT INTO keyword_mentions(keyword_id,article_id,count,observed_on,source_id)"
        " VALUES (?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    root = tmp_path_factory.mktemp("kw-export")
    out = {}
    for seed, (a, k) in enumerate([(80, 500), (150, 900), (40, 200)]):
        p = root / f"d{seed}.db"
        _build(p, seed, articles=a, keywords=k)
        out[seed] = p
    return out


def _session(path: Path):
    eng = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _q(dbapi, _rec):  # noqa: ANN001
        dbapi.execute("PRAGMA query_only=ON")

    return sessionmaker(bind=eng, future=True)()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """The export's scratch folder is ``<data dir>/diagnostics``: point it at tmp."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    d = tmp_path / "diagnostics"
    d.mkdir(exist_ok=True)
    return d


def _leftovers(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.startswith((kls.SPILL_PREFIX, kle.ZIP_TMP_PREFIX)))


# --------------------------------------------------------------------------- the reference


def _reference(path: Path):
    """The documented rules, written the plain way: dicts, sorts, no cleverness."""
    con = sqlite3.connect(path)
    art = {aid: (lg or "?", sid) for aid, lg, sid in con.execute("SELECT id, language, source_id FROM articles")}
    src_total = Counter(sid for _lg, sid in art.values() if sid is not None)
    per_kw: dict[int, list] = {}
    for kid, aid, cnt, obs in con.execute(
        "SELECT keyword_id, article_id, count, observed_on FROM keyword_mentions ORDER BY keyword_id, article_id"
    ):
        per_kw.setdefault(kid, []).append((aid, cnt, obs))
    ranked: dict[str, list] = {}
    suspects = []
    for kid, ms in per_kw.items():
        langs = Counter(art.get(aid, ("?", None))[0] for aid, _c, _o in ms)
        dom = min(langs, key=lambda lg: (-langs[lg], lg))
        m = sum(c or 0 for _a, c, _o in ms)
        dates = [o for _a, _c, o in ms if o is not None]
        first, last = (min(dates), max(dates)) if dates else (None, None)
        ranked.setdefault(dom, []).append((1, m, -kid, len(ms), first, last, dom))
        srcs = Counter(art[aid][1] for aid, _c, _o in ms if aid in art and art[aid][1] is not None)
        n_src = sum(srcs.values())
        if n_src >= 10:
            top_src, top_n = max(srcs.items(), key=lambda kv: kv[1])
            if src_total[top_src] >= 10 and top_n / n_src >= 0.9 and top_n / src_total[top_src] >= 0.25:
                suspects.append(
                    {
                        "keyword_id": kid, "source_id": top_src, "articles_with_keyword": n_src,
                        "in_this_source": top_n, "source_article_total": src_total[top_src],
                        "share_of_keyword": round(top_n / n_src, 3),
                        "share_of_source": round(top_n / src_total[top_src], 3),
                    }
                )
    total = 0
    for kid, lg in con.execute("SELECT id, language FROM keywords"):
        total += 1
        if kid not in per_kw:
            ranked.setdefault(lg or "?", []).append((0, 0, -kid, 0, None, None, None))
    con.close()
    suspects.sort(key=lambda r: (r["share_of_source"], r["in_this_source"], -r["keyword_id"]), reverse=True)
    for lg in ranked:
        ranked[lg].sort(reverse=True)
    return ranked, suspects[:200], len(suspects), total


def _scan(path: Path, lo: int, hi: int, *, heap_rows: int, spill_dir: Path):
    db = _session(path)
    try:
        maps = kls.ArticleMaps(db, lambda: None)
        src_articles = dict(db.execute(kls.text("SELECT source_id, COUNT(*) FROM articles GROUP BY source_id")).fetchall())
        ranker = kls.Ranker(lo, hi, heap_rows=heap_rows, spill_dir=spill_dir, disk_check=None)
        stats = kls.scan_keywords(db, maps, src_articles, ranker, check=lambda: None)
        rows = {lg: list(ranker.rows(lg)) for lg in ranker.totals()}
        return ranker, stats, rows
    finally:
        db.close()


def _expected_rows(ranked: dict[str, list], lo: int, hi: int) -> dict[str, list]:
    return {
        lg: [(-it[2], it[1], it[3], it[4], it[5], it[6]) for it in items[lo:hi]]
        for lg, items in ranked.items()
    }


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("window", [(0, 5), (0, 100_000), (3, 40)])
@pytest.mark.parametrize("mode", ["heap", "spill"])
def test_the_ranking_is_the_documented_one_in_both_modes(dbs, tmp_path, seed, window, mode):
    lo, hi = window
    ranked, suspects, suspects_total, total = _reference(dbs[seed])
    ranker, stats, rows = _scan(
        dbs[seed], lo, hi, heap_rows=(10**9 if mode == "heap" else 10), spill_dir=tmp_path
    )
    try:
        assert ranker.spilled is (mode == "spill")
        assert dict(ranker.totals()) == {lg: len(v) for lg, v in ranked.items()}
        assert rows == _expected_rows(ranked, lo, hi)
        assert {lg: ranker.taken(lg) for lg in rows} == {lg: len(v) for lg, v in rows.items()}
        assert stats.keywords_total == total
        assert stats.board.total == suspects_total
        assert stats.board.top() == suspects
    finally:
        ranker.close()
    assert _leftovers(tmp_path) == []  # a spill file never outlives its ranker


def test_the_boilerplate_keyword_is_actually_a_suspect(dbs):
    """The reference above would agree with an empty board on both sides; make sure the corpus
    really exercises the suspect test."""
    _r, suspects, total_suspects, _t = _reference(dbs[0])
    assert total_suspects >= 1 and suspects[0]["articles_with_keyword"] == 27


def test_rank_order_puts_orphans_last_and_breaks_ties_by_id(tmp_path):
    r = kls.Ranker(0, 100, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    r.add("en", 7, 0, 0, None, None, None)  # orphan
    r.add("en", 3, 5, 2, "2026-01-01", "2026-01-02", "en")
    r.add("en", 2, 5, 9, "2026-01-01", "2026-01-02", "en")  # same mentions, lower id: first
    r.add("en", 1, 0, 0, None, None, None)  # orphan, lower id: before 7
    assert [row[0] for row in r.rows("en")] == [2, 3, 1, 7]


def test_a_window_clamped_after_the_scan_never_widens(tmp_path):
    r = kls.Ranker(0, 10, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    for kid in range(1, 30):
        r.add("en", kid, 30 - kid, 1, None, None, "en")
    assert r.taken("en") == 10
    r.clamp(4)
    assert r.taken("en") == 4 and len(list(r.rows("en"))) == 4
    r.clamp(50)
    assert r.taken("en") == 4


def test_the_spill_starts_only_past_the_budget_and_a_refusing_disk_stops_it_first(tmp_path):
    r = kls.Ranker(0, 10**6, heap_rows=10, spill_dir=tmp_path, disk_check=None)
    for kid in range(1, 11):
        r.add("en", kid, 1, 1, None, None, "en")
    assert not r.spilled and _leftovers(tmp_path) == []
    r.add("en", 11, 1, 1, None, None, "en")
    assert r.spilled and len(_leftovers(tmp_path)) == 1
    r.close()
    assert _leftovers(tmp_path) == []

    def refuse(_need: int) -> None:
        raise kls.ExportRefused("no room", status=507)

    r2 = kls.Ranker(0, 10**6, heap_rows=3, spill_dir=tmp_path, disk_check=refuse)
    with pytest.raises(kls.ExportRefused):
        for kid in range(1, 10):
            r2.add("en", kid, 1, 1, None, None, "en")
    r2.close()
    assert _leftovers(tmp_path) == []  # refused BEFORE a file existed


def _window_reference(rows: list[tuple], lo: int, hi: int) -> list[int]:
    """The documented order (mention-bearing by mentions desc then id asc, orphans by id asc)."""
    ordered = sorted(rows, key=lambda r: (0 if r[2] is None else 1, r[1], -r[0]), reverse=True)
    return [r[0] for r in ordered[lo:hi]]


def test_the_spill_holds_twice_the_window_per_language_never_the_keyword_table(tmp_path):
    """A window of 5 over 30 languages wrote EVERY keyword to disk once the ranking had spilled
    (1.2-1.7 GB at 14.65 M keywords, against a check sized for the rows held at the switch). The
    rows beyond a language's window are pruned, and a row that cannot rank inside it is never
    written; what the window reads back is what the heaps would have kept."""
    rnd = random.Random(3)
    r = kls.Ranker(0, 5, heap_rows=100, spill_dir=tmp_path, disk_check=None)
    by_lang: dict[str, list[tuple]] = {}
    n_lang, per = 30, 2_000
    for i in range(n_lang * per):
        lg = f"l{i % n_lang}"
        kid = i + 1
        orphan = rnd.random() < 0.4
        m = 0 if orphan else rnd.choice([1, 1, 2, 3, 50, rnd.randrange(1, 10_000)])
        row = (kid, m, None if orphan else "en")
        by_lang.setdefault(lg, []).append(row)
        r.add(lg, kid, m, 1, None, None, None if orphan else "en")
    try:
        assert r.spilled
        r._flush()
        assert r._con is not None
        on_disk = r._con.execute("SELECT COUNT(*) FROM kw").fetchone()[0]
        assert on_disk <= n_lang * 2 * 5, on_disk  # two windows per language, not 60,000 rows
        for lg, rows in by_lang.items():
            assert [row[0] for row in r.rows(lg)] == _window_reference(rows, 0, 5), lg
            assert r.totals()[lg] == per  # what was SEEN is still counted whole
    finally:
        r.close()
    assert _leftovers(tmp_path) == []


def test_a_window_that_starts_past_zero_still_reads_the_same_after_pruning(tmp_path):
    rnd = random.Random(4)
    r = kls.Ranker(7, 20, heap_rows=10, spill_dir=tmp_path, disk_check=None)
    rows = []
    for kid in range(1, 4_001):
        m = rnd.randrange(0, 40)  # heavy ties
        rows.append((kid, m, None if m == 0 else "en"))
        r.add("en", kid, m, 1, None, None, None if m == 0 else "en")
    try:
        assert r.spilled
        assert [row[0] for row in r.rows("en")] == _window_reference(rows, 7, 20)
    finally:
        r.close()


def test_the_floor_and_the_prune_hold_when_ids_arrive_out_of_order(tmp_path):
    """Production feeds ids out of order: the orphan pass reads ``SELECT id, language FROM
    keywords`` off a covering index that orders by language and then id, and a NULL and an empty
    language both land in "?", so inside "?" the ids arrive 4, 8, 12, then 1, 5, 9. The floor's
    tie-break (a row that ties on mentions ranks by LOWER id) was only ever fed ascending ids
    here. Heavy ties and shuffled ids exercise that tie-break against the reference window; they
    do NOT catch a floor one id too high (that needs a row landing exactly at the cut, which
    shuffled ids rarely produce): the directed test below pins it."""
    for seed in range(8):
        rnd = random.Random(700 + seed)
        lo, hi = (0, 5) if seed % 2 == 0 else (2, 9)
        r = kls.Ranker(lo, hi, heap_rows=8, spill_dir=tmp_path, disk_check=None)
        kids = list(range(1, 1_501))
        rnd.shuffle(kids)
        by_lang: dict[str, list[tuple]] = {}
        for kid in kids:
            lg = rnd.choice(["?", "?", "en"])
            orphan = rnd.random() < 0.35
            m = 0 if orphan else rnd.choice([1, 1, 1, 2, 2, 3])
            by_lang.setdefault(lg, []).append((kid, m, None if orphan else "en"))
            r.add(lg, kid, m, 1, None, None, None if orphan else "en")
        try:
            assert r.spilled
            for lg, rows in by_lang.items():
                assert [row[0] for row in r.rows(lg)] == _window_reference(rows, lo, hi), (seed, lg)
        finally:
            r.close()
    assert _leftovers(tmp_path) == []


def test_a_window_that_ends_before_it_starts_is_empty_in_both_modes(tmp_path):
    """SQLite reads a NEGATIVE limit as "no limit", so spill mode used to return everything after
    ``lo`` where heap mode's slice [lo:hi] is empty. The route cannot reach it (the window never
    shrinks below one), but the two modes are one behaviour. The spill holds up to 2 x hi rows
    between prunes, so a window of [4, 3) over five rows on disk is the smallest case where an
    unclamped limit has a row to wrongly return."""
    for heap_rows in (10**9, 2):
        r = kls.Ranker(4, 3, heap_rows=heap_rows, spill_dir=tmp_path, disk_check=None)
        for kid in range(1, 6):
            r.add("en", kid, 9 - kid, 1, None, None, "en")
        try:
            assert r.spilled is (heap_rows == 2)
            assert list(r.rows("en")) == []
        finally:
            r.close()


def test_a_row_ranking_just_ahead_of_the_cut_is_kept_after_a_prune(tmp_path):
    """Directed, because random order almost never produces it: after a prune the floor is the
    key of the row at the cut, and a row that TIES on mentions with a LOWER id ranks ahead of the
    cut and must still be written. Ids 10..60 (all tied) force the first prune with 30 at the cut;
    id 29 arrives afterwards and belongs in the window. A floor one id too high drops it."""
    r = kls.Ranker(0, 3, heap_rows=2, spill_dir=tmp_path, disk_check=None)
    for kid in (10, 20, 30, 40, 50, 60, 29):
        r.add("en", kid, 5, 1, None, None, "en")
    try:
        assert r.spilled and "en" in r._floor, "the prune must have run for this to test anything"
        assert [row[0] for row in r.rows("en")] == [10, 20, 29]
    finally:
        r.close()


def test_a_row_at_or_below_the_floor_is_never_written_after_a_prune(tmp_path):
    """The floor is what keeps the on-disk bound: once a language has been pruned, a row that
    does not beat the cut is outside its window for good, so it must not reach the buffer (it
    would be written and pruned again). The directed case from above, then rows that tie on
    mentions with a HIGHER id than the cut's, one with fewer mentions and an orphan."""
    r = kls.Ranker(0, 3, heap_rows=2, spill_dir=tmp_path, disk_check=None)
    for kid in (10, 20, 30, 40, 50, 60):
        r.add("en", kid, 5, 1, None, None, "en")
    try:
        assert r.spilled and "en" in r._floor, "the prune must have run for this to test anything"
        buffered, on_disk = list(r._buf), r._on_disk["en"]
        for kid, m in ((70, 5), (35, 5), (31, 4), (5, 0)):
            r.add("en", kid, m, 1, None, None, "en" if m else None)
        assert r._buf == buffered and r._on_disk["en"] == on_disk
        assert r._seen["en"] == 10, "a row that cannot rank is still COUNTED, only never written"
        r.add("en", 29, 5, 1, None, None, "en")  # beats the cut: this one is written
        assert len(r._buf) == len(buffered) + 1 and r._on_disk["en"] == on_disk + 1
        assert [row[0] for row in r.rows("en")] == [10, 20, 29]
    finally:
        r.close()


def test_the_disk_is_watched_while_the_ranking_spills_not_only_before_it(tmp_path):
    flushes = {"n": 0}

    def watch() -> None:
        flushes["n"] += 1
        if flushes["n"] >= 3:
            raise kls.ExportRefused("the drive is full", status=507)

    r = kls.Ranker(0, 10**9, heap_rows=10, spill_dir=tmp_path, disk_check=None, disk_watch=watch)
    with pytest.raises(kls.ExportRefused) as err:
        for kid in range(1, 200_000):
            r.add("en", kid, 1, 1, None, None, "en")
    assert err.value.status == 507 and flushes["n"] == 3
    r.close()
    assert _leftovers(tmp_path) == []


def _enospc(*_a, **_k):
    raise OSError(errno.ENOSPC, "No space left on device")


def test_a_drive_with_no_room_for_the_scratch_file_is_a_507_for_the_spill_and_the_archive(
    tmp_path, monkeypatch
):
    """Creating the scratch file is the first write the export makes, and a drive with no room
    answers ENOSPC from the OS there, not from SQLite: that used to surface as a 500."""
    monkeypatch.setattr(tempfile, "mkstemp", _enospc)
    r = kls.Ranker(0, 10**9, heap_rows=3, spill_dir=tmp_path, disk_check=None)
    with pytest.raises(kls.ExportRefused) as err:
        for kid in range(1, 10):
            r.add("en", kid, 1, 1, None, None, "en")
    assert err.value.status == 507 and "ran out of room" in str(err.value)
    r.close()
    with pytest.raises(kls.ExportRefused) as err2:
        kle.ZipJob._path(types.SimpleNamespace(out_dir=tmp_path))
    assert err2.value.status == 507


_NO_ROOM_CASES = [
    pytest.param(errno.ENOSPC, "ran out of room", id="full"),
    pytest.param(getattr(errno, "EDQUOT", None), "quota", id="quota"),
    pytest.param(errno.EROFS, "read-only", id="read-only"),
]


@pytest.mark.parametrize(("code", "words"), _NO_ROOM_CASES)
def test_a_quota_and_a_read_only_drive_are_the_same_refusal_as_a_full_one(
    tmp_path, monkeypatch, code, words
):
    """Each of these is a fact about the operator's drive, with a way out, not a bug in the app:
    a 507 that says which. (EDQUOT does not exist on Windows; the case is skipped there.)"""
    if code is None:
        pytest.skip("this platform has no EDQUOT")

    def _refuse(*_a, **_k):
        raise OSError(code, "refused by the drive")

    monkeypatch.setattr(tempfile, "mkstemp", _refuse)
    with pytest.raises(kls.ExportRefused) as err:
        kls.scratch_file("p-", ".x", tmp_path)
    assert err.value.status == 507 and words in str(err.value)
    assert "the drive the export writes to" in str(err.value)
    text = str(err.value)
    # What the refusal says happened to the files is true of THAT drive: a read-only one cannot
    # delete anything, so it must not claim to have (the sentence that came back three times).
    if code == errno.EROFS:
        assert "removed its scratch file" not in text and "left nothing behind" not in text
        assert "swept at the start of each export" in text
    else:
        assert "removed any partial file" in text and "twelve hours" in text
    assert isinstance(err.value.__cause__, OSError), "the original error stays attached"


@pytest.mark.parametrize(
    ("message", "words"),
    [("database or disk is full", "ran out of room"),
     ("attempt to write a readonly database", "read-only")],
)
def test_sqlite_saying_the_drive_is_full_or_read_only_is_a_507(message, words):
    with pytest.raises(kls.ExportRefused) as err, kls._refuse_when_the_disk_is_full():
        raise sqlite3.OperationalError(message)
    assert err.value.status == 507 and words in str(err.value)
    # Any other SQLite error is raised as itself: it may be a bug, and a bug must stay visible.
    with pytest.raises(sqlite3.OperationalError, match="no such table"), kls._refuse_when_the_disk_is_full():
        raise sqlite3.OperationalError("no such table: kw")


def _io_error_on_write() -> sqlite3.OperationalError:
    """What SQLite's unix layer raises for a write that failed with an errno it has no word for
    (a quota, a drive remounted read-only): a bare ``disk I/O error`` with this extended code. Real
    failures read like this, which the hand-written messages above do not."""
    exc = sqlite3.OperationalError("disk I/O error")
    exc.sqlite_errorcode = kls._SQLITE_IOERR_WRITE
    exc.sqlite_errorname = "SQLITE_IOERR_WRITE"
    return exc


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="this platform has no statvfs")
def test_a_write_error_is_a_507_only_when_the_drive_itself_says_it_is_read_only(tmp_path, monkeypatch):
    real = os.statvfs

    def read_only(path):
        # Ignores the path on purpose: a guard that stops asking for a folder (``None``) must fail
        # here, and a fake that called the real ``statvfs`` on ``"None"`` would raise and say False.
        return types.SimpleNamespace(f_flag=os.ST_RDONLY)

    monkeypatch.setattr(os, "statvfs", read_only)
    with pytest.raises(kls.ExportRefused) as err, kls._refuse_when_the_disk_is_full(tmp_path):
        raise _io_error_on_write()
    assert err.value.status == 507 and "read-only" in str(err.value)
    # No folder named: nothing to ask the drive about, so nothing is renamed.
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"), kls._refuse_when_the_disk_is_full():
        raise _io_error_on_write()
    # A writable drive: the same bare error may be a failing disk or a quota SQLite cannot name.
    monkeypatch.setattr(os, "statvfs", real)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"), kls._refuse_when_the_disk_is_full(tmp_path):
        raise _io_error_on_write()
    # A different extended code on a read-only drive is not a write refusal: the plain IOERR, a
    # failed READ and a failed fsync are all "disk I/O error" too, and a drive that cannot be read
    # or synced is not one that is merely read-only.
    monkeypatch.setattr(os, "statvfs", read_only)
    for code in (
        sqlite3.SQLITE_IOERR, sqlite3.SQLITE_IOERR_READ, sqlite3.SQLITE_IOERR_FSYNC,
        kls._SQLITE_IOERR_WRITE + 1,
    ):
        other = sqlite3.OperationalError("disk I/O error")
        other.sqlite_errorcode = code
        with pytest.raises(sqlite3.OperationalError), kls._refuse_when_the_disk_is_full(tmp_path):
            raise other


def test_a_drive_that_cannot_be_asked_is_not_called_read_only(tmp_path, monkeypatch):
    """Nothing is guessed: no ``statvfs`` on the platform, no ``ST_RDONLY`` flag, or a folder the
    call cannot read all say False, and only the flag set on a real answer says True."""
    monkeypatch.setattr(os, "statvfs", lambda path: types.SimpleNamespace(f_flag=1), raising=False)
    monkeypatch.setattr(os, "ST_RDONLY", 1, raising=False)
    assert kls._drive_is_read_only(tmp_path) is True
    monkeypatch.setattr(os, "statvfs", lambda path: types.SimpleNamespace(f_flag=0), raising=False)
    assert kls._drive_is_read_only(tmp_path) is False

    def cannot_read(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "statvfs", cannot_read, raising=False)
    assert kls._drive_is_read_only(tmp_path / "gone") is False
    monkeypatch.delattr(os, "statvfs", raising=False)
    assert kls._drive_is_read_only(tmp_path) is False
    monkeypatch.setattr(os, "statvfs", lambda path: types.SimpleNamespace(f_flag=1), raising=False)
    monkeypatch.delattr(os, "ST_RDONLY", raising=False)
    assert kls._drive_is_read_only(tmp_path) is False


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="this platform has no statvfs")
@pytest.mark.parametrize("where", ["to_spill", "flush", "prune"])
def test_every_write_the_ranker_makes_asks_its_own_drive_whether_it_is_read_only(
    tmp_path, monkeypatch, where
):
    """The three places the ranker writes its spill each name the spill's folder to the refusal;
    one that stopped naming it would raise SQLite's bare ``disk I/O error`` as a 500."""
    r = kls.Ranker(0, 3, heap_rows=2, spill_dir=tmp_path, disk_check=None)
    # Read-only only for the SPILL'S folder: a site that asked about another one (the ranker's
    # fallback temp folder, say) must not be refused.
    monkeypatch.setattr(
        os, "statvfs",
        lambda path: types.SimpleNamespace(f_flag=os.ST_RDONLY if path == str(tmp_path) else 0),
    )
    try:
        if where == "to_spill":
            def fail(*args, **kwargs):
                raise _io_error_on_write()

            monkeypatch.setattr(kls.sqlite3, "connect", fail)
            with pytest.raises(kls.ExportRefused) as err:
                for kid in (10, 20, 30):
                    r.add("en", kid, 5, 1, None, None, "en")
        else:
            for kid in (10, 20, 30, 40):
                r.add("en", kid, 5, 1, None, None, "en")
            assert r.spilled, "the spill must exist for this to test anything"
            r._flush()  # empty the buffer: `_prune` flushes first, which would hit the flush site

            class _Failing:
                def execute(self, *args, **kwargs):
                    raise _io_error_on_write()

                executemany = execute

                def close(self):
                    pass

            real_con, r._con = r._con, _Failing()
            try:
                with pytest.raises(kls.ExportRefused) as err:
                    if where == "flush":
                        r._buf = [(-5, "en", 99, 1, 1, None, None, None)]
                        r._flush()
                    else:
                        r._prune("en")
            finally:
                r._buf, r._con = [], real_con
        assert err.value.status == 507 and "read-only" in str(err.value)
    finally:
        r.close()


@pytest.mark.parametrize(("code", "words"), _NO_ROOM_CASES)
def test_the_drive_filling_in_the_middle_of_the_archive_is_a_507_and_leaves_nothing(
    dbs, data_dir, monkeypatch, code, words
):
    """The between-batches watch is a guard, not a guarantee: a write can fail first. That used to
    be a 500 (and the same for a quota or a read-only drive)."""
    if code is None:
        pytest.skip("this platform has no EDQUOT")
    real = zipfile.ZipFile.writestr
    wrote = {"n": 0}

    def _fails_on_the_summary(self, name, *a, **k):
        if name == "summary.json":
            wrote["n"] += 1
            raise OSError(code, "refused by the drive")
        return real(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", _fails_on_the_summary)
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    db.close()
    assert wrote["n"] == 1, "the write that failed is one the archive really makes"
    assert err.value.status_code == 507 and words in str(err.value.detail)
    assert _leftovers(data_dir) == [], "the partial archive is removed"


def test_an_error_creating_the_scratch_file_that_is_not_a_full_drive_is_not_renamed(tmp_path, monkeypatch):
    def denied(*_a, **_k):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(tempfile, "mkstemp", denied)
    with pytest.raises(PermissionError):
        kls.scratch_file("p-", ".x", tmp_path)


def test_the_disk_watch_says_what_the_export_was_doing_when_it_stopped(tmp_path, monkeypatch):
    import collections

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(kle.shutil, "disk_usage", lambda _p: Usage(10**12, 10**12 - 1000, 1000))
    with pytest.raises(kls.ExportRefused) as archive:
        kle.disk_watch_for(tmp_path)()
    assert "stopped writing the archive and removed it" in str(archive.value)
    assert "for whatever else writes to it" in str(archive.value), "the reserve sentence"
    with pytest.raises(kls.ExportRefused) as spill:
        kle.disk_watch_for(tmp_path, stopped="stopped ranking and removed its scratch file")()
    assert "stopped ranking and removed its scratch file" in str(spill.value)
    assert "writing the archive" not in str(spill.value)
    assert spill.value.status == 507


def test_with_no_data_folder_the_archive_is_watched_on_the_temp_folders_drive(
    dbs, tmp_path, monkeypatch
):
    """The archive goes to the OS temp folder when there is no data folder, and that drive is the
    one to watch. It was watched through the data folder, which is None in exactly this case: no
    watch at all. Every drive reads as at its reserve below and the up-front check is off, so only
    the between-batches watch can stop the archive; that the temp folder's own path was asked
    about is what shows it was watched there."""
    import collections

    import src.api.diagnostics.keywords as kw_mod

    Usage = collections.namedtuple("Usage", "total used free")
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setattr(kw_mod, "export_dir", lambda: None)
    monkeypatch.setattr(kw_mod, "zip_disk_preflight", lambda *_a: None)
    watched: list[str] = []

    def _usage(path):
        watched.append(str(path))
        return Usage(10**12, 10**12 - 1000, 1000)

    monkeypatch.setattr(kle.shutil, "disk_usage", _usage)
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    db.close()
    assert err.value.status_code == 507 and "the drive the export writes to" in str(err.value.detail)
    assert str(temp) in watched, "the watch looked at the temp folder's drive"
    assert sorted(p.name for p in temp.iterdir()) == [], "the partial archive is removed"


def test_with_no_data_folder_the_temp_folders_stale_scratch_is_swept_too(dbs, tmp_path, monkeypatch):
    """The OS temp folder is the last resort for the spill, and what a killed export left there
    (only this export's own prefixes, and only once it is stale) is swept like the data folder's."""
    import os
    import time

    import src.api.diagnostics.keywords as kw_mod

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(kw_mod, "export_dir", lambda: None)
    stale = tmp_path / f"{kls.SPILL_PREFIX}9-9.sqlite"
    other = tmp_path / "somebody-elses.tmp"
    for p in (stale, other):
        p.write_bytes(b"x")
    long_ago = time.time() - 13 * 3600
    os.utime(stale, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    db = _session(dbs[0])
    try:
        _call(db, fmt="json", digest=True, per_lang=5000, max_mb=None)
    finally:
        db.close()
    assert not stale.exists() and other.exists()


class _FullDiskConnection:
    """A connection that writes like a drive with no room left (SQLITE_FULL)."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql, *args):
        return self._real.execute(sql, *args)

    def executemany(self, *_a):
        raise sqlite3.OperationalError("database or disk is full")

    def close(self) -> None:
        self._real.close()


def test_a_full_disk_reported_by_sqlite_is_a_507_not_a_server_error(tmp_path):
    r = kls.Ranker(0, 10**9, heap_rows=3, spill_dir=tmp_path, disk_check=None)
    for kid in range(1, 5):
        r.add("en", kid, 1, 1, None, None, "en")
    assert r.spilled
    r._con = _FullDiskConnection(r._con)  # type: ignore[assignment]
    with pytest.raises(kls.ExportRefused) as err:
        for kid in range(5, 100_000):
            r.add("en", kid, 1, 1, None, None, "en")
    assert err.value.status == 507 and "ran out of room" in str(err.value)
    r.close()
    assert _leftovers(tmp_path) == []


def test_an_error_that_is_not_a_full_disk_is_not_renamed(tmp_path):
    class Broken(_FullDiskConnection):
        def executemany(self, *_a):
            raise sqlite3.OperationalError("no such table: kw")

    r = kls.Ranker(0, 10**9, heap_rows=3, spill_dir=tmp_path, disk_check=None)
    for kid in range(1, 5):
        r.add("en", kid, 1, 1, None, None, "en")
    r._con = Broken(r._con)  # type: ignore[assignment]
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        for kid in range(5, 100_000):
            r.add("en", kid, 1, 1, None, None, "en")
    r.close()


def test_the_up_front_check_is_sized_from_the_keywords_there_are(tmp_path):
    """The check at the switch used the rows HELD then (a few MB); it now sizes the file from
    every keyword the table can hold, and from the languages' two windows when those are fewer."""
    asked: list[int] = []
    r = kls.Ranker(0, 10**9, heap_rows=5, spill_dir=tmp_path, disk_check=asked.append,
                   expected_rows=1_000_000)
    for kid in range(1, 8):
        r.add("en", kid, 1, 1, None, None, "en")
    r.close()
    assert asked == [1_000_000 * kls.SPILL_ROW_BYTES]

    asked.clear()
    r = kls.Ranker(0, 5, heap_rows=3, spill_dir=tmp_path, disk_check=asked.append,
                   expected_rows=1_000_000)
    for kid in range(1, 8):
        r.add("en", kid, 1, 1, None, None, "en")
    r.close()
    # the switch comes with 4 rows held, one language, a window of 5: two windows = 10 rows
    assert asked == [10 * kls.SPILL_ROW_BYTES]


def test_a_ranker_told_no_folder_spills_to_the_temp_folder_instead_of_growing(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    r = kls.Ranker(0, 10**9, heap_rows=5, spill_dir=None, disk_check=None)
    for kid in range(1, 20):
        r.add("en", kid, 1, 1, None, None, "en")
    try:
        assert r.spilled and len(_leftovers(tmp_path)) == 1
    finally:
        r.close()
    assert _leftovers(tmp_path) == []


def test_a_failed_spill_setup_leaves_neither_a_file_nor_an_open_connection(tmp_path, monkeypatch):
    closed: list[int] = []

    class Proxy:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a):
            if sql.startswith("CREATE INDEX"):
                raise sqlite3.OperationalError("database or disk is full")
            return self._real.execute(sql, *a)

        def close(self):
            closed.append(1)
            self._real.close()

    real_connect = sqlite3.connect
    monkeypatch.setattr(kls.sqlite3, "connect", lambda *a, **k: Proxy(real_connect(*a, **k)))
    r = kls.Ranker(0, 10**9, heap_rows=2, spill_dir=tmp_path, disk_check=None)
    with pytest.raises(kls.ExportRefused):
        for kid in range(1, 10):
            r.add("en", kid, 1, 1, None, None, "en")
    assert closed == [1] and _leftovers(tmp_path) == []
    r.close()


def test_scratch_names_cannot_collide_even_in_the_same_millisecond(tmp_path, monkeypatch):
    """Names used to be pid + millisecond: two exports in one millisecond shared a file (one got
    "database is locked", or one deleted the other's archive once it had been sent)."""
    import time
    from types import SimpleNamespace

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    rankers = [kls.Ranker(0, 10**9, heap_rows=2, spill_dir=tmp_path, disk_check=None) for _ in range(2)]
    for r in rankers:
        for kid in range(1, 6):
            r.add("en", kid, 1, 1, None, None, "en")
    assert rankers[0]._path != rankers[1]._path and len(_leftovers(tmp_path)) == 2
    rankers[0].close()
    assert len(_leftovers(tmp_path)) == 1  # closing one never removes the other's
    rankers[1].close()
    assert _leftovers(tmp_path) == []

    fake = SimpleNamespace(out_dir=tmp_path)
    a, b = kle.ZipJob._path(fake), kle.ZipJob._path(fake)  # type: ignore[arg-type]
    assert a != b and a.exists() and b.exists()
    kle.unlink_quietly(a)
    assert b.exists()
    kle.unlink_quietly(b)


def test_closing_a_ranker_drops_the_rows_its_heaps_hold(tmp_path):
    """The heap form keeps a copy of every row of the window until it is read out. The grouping
    that follows is the peak of the digest, so the copy must be gone by then: the export closes the
    ranker before it, and a closed ranker holds nothing and gives nothing back."""
    r = kls.Ranker(0, 10**9, heap_rows=10**9, spill_dir=tmp_path, disk_check=None)
    for kid in range(1, 40):
        r.add("en", kid, kid, 1, None, None, "en")
    assert len(list(r.rows("en"))) == 39 and not r.spilled
    r.close()
    assert list(r.rows("en")) == []
    assert r.taken("en") == 39  # what was seen stays known: pages and totals are read after it


def test_memory_plan_sizes_from_what_is_available_and_never_guesses_when_unread():
    floor = kls.memory_plan(None)
    assert floor["heap_rows"] == kls.MIN_HEAP_ROWS and floor["batch"] == 800
    assert kls.memory_plan(0)["heap_rows"] == kls.MIN_HEAP_ROWS
    small = kls.memory_plan(128 * 2**20)
    big = kls.memory_plan(64 * 2**30)
    assert small["heap_rows"] == kls.MIN_HEAP_ROWS  # the floor protects the default export
    assert big["heap_rows"] == int(64 * 2**30 * kls.HEAP_SHARE / kls.ROW_BYTES)
    assert big["batch"] > small["batch"]
    assert floor["family_rows"] == kls.MIN_FAMILY_ROWS and small["family_rows"] == kls.MIN_FAMILY_ROWS
    assert big["family_rows"] == int(64 * 2**30 * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES)


def test_row_budget_constant_matches_the_measured_row_size():
    """ROW_BYTES is what turns 'a share of available memory' into a row count; it is measured
    here (a mention-bearing row is the big one), and fails if it drifts by more than 25 %."""
    rnd = random.Random(1)
    dates = [f"2026-0{m}-1{d}" for m in range(1, 10) for d in range(10)]
    n = 40_000
    gc.collect()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        r = kls.Ranker(0, 10**9, heap_rows=10**9, spill_dir=None, disk_check=None)
        for kid in range(1, n + 1):
            r.add("en", kid, rnd.randrange(1, 5000), rnd.randrange(1, 900),
                  rnd.choice(dates), rnd.choice(dates), "en")
        per_row = (tracemalloc.get_traced_memory()[0] - base) / n
    finally:
        tracemalloc.stop()
    assert abs(per_row - kls.ROW_BYTES) / kls.ROW_BYTES < 0.25, per_row


def _grouping_peak_per_keyword(shape: str) -> float:
    """tracemalloc's peak above the entries, per keyword, while ``build_families`` runs over 20,000
    keywords of one shape, plus the 500 bytes the entries' own ``fam`` items hold (they are built
    before tracing starts)."""
    from src.analytics.families import build_families

    rnd = random.Random(3)
    if shape == "short":
        vocab = [f"w{i}" for i in range(5000)]
        phrase_share, phrase_lengths = 0.33, [2, 3]
    else:  # Cyrillic words of four to eleven letters, three in five of the terms two to four tokens
        letters = "абвгдежзиклмнопрстуфхцчшщыэюя"
        vocab = ["".join(rnd.choice(letters) for _ in range(rnd.randint(4, 11))) for _ in range(20_000)]
        phrase_share, phrase_lengths = 0.6, [2, 3, 4]

    def sizes() -> int:
        return rnd.choice(phrase_lengths) if rnd.random() < phrase_share else 1

    n = 20_000
    fam = []
    for i in range(n):
        norm = " ".join(rnd.choice(vocab) for _ in range(sizes()))
        fam.append((
            kls.order_key(i, i % 500, True),
            {"term": norm.title(), "normalized": norm, "kind": rnd.choice(["person", "org", "term"]),
             "mentions": i % 500, "articles": i % 90},
        ))
    gc.collect()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        families = build_families([it for _k, it in fam], {})
        peak_extra = tracemalloc.get_traced_memory()[1] - base
        del families
    finally:
        tracemalloc.stop()
    return peak_extra / n + 500


@pytest.mark.parametrize("shape", ["short", "cyrillic-phrases"])
def test_family_row_budget_constant_covers_the_grouping_on_both_term_shapes(shape):
    """FAMILY_ROW_BYTES turns a share of available memory into how many keywords the families may
    be grouped over. tracemalloc misses the allocator's overhead, so what it reads is a LOWER bound
    on the resident cost: the constant must sit at or above it for the short single-script terms
    AND for phrase-heavy non-Latin ones (the shape that costs most per keyword), and not absurdly
    far above the worst."""
    per_keyword = _grouping_peak_per_keyword(shape)
    assert per_keyword <= kls.FAMILY_ROW_BYTES, per_keyword
    if shape != "short":
        assert per_keyword >= kls.FAMILY_ROW_BYTES * 0.6, per_keyword


#: The grouping's PEAK RESIDENT rise per keyword, measured out of process on 2026-10-06 over terms
#: shaped like the field's: Cyrillic words of four to eleven letters, three in five of the terms two
#: to four tokens. 2,069 / 2,134 / 2,228 bytes at 200,000 / 100,000 / 50,000 keywords (the small
#: size carries the most of the process's own fixed growth, so it is the worst); Latin phrases of the
#: same shape read 2,027 and single-token terms 1,483. The worst is the figure the constant must
#: cover, and moving the constant means measuring again on purpose.
_MEASURED_FAMILY_PEAK_BYTES = 2_228


def test_family_row_constant_is_the_measured_worst_shape_plus_its_margin():
    """Two-sided, and by value, as the entry constant is. The margin sits HERE because this is the
    constant that scales with the length of a term; a constant of 2,000 (the value before this was
    measured on phrase-heavy non-Latin terms) passed the tracemalloc test and priced the component
    the digest gate now leans on 10 per cent short of its worst measured shape."""
    assert kls.FAMILY_ROW_BYTES == 2_500
    assert kls.FAMILY_ROW_BYTES >= _MEASURED_FAMILY_PEAK_BYTES * 1.10
    assert kls.FAMILY_ROW_BYTES <= _MEASURED_FAMILY_PEAK_BYTES * 1.15


def _digest_peak(tmp_path, monkeypatch, *, keywords: int, seed: int) -> tuple[int, int]:
    """(peak Python allocation, entries exported) of the bundle's digest over one corpus."""
    from src.api.diagnostics.keywords import keyword_log

    tmp_path = tmp_path / f"run{keywords}"
    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def digest(db) -> bytes:
        return _drain_body(keyword_log(db=db, digest=True, fmt="json", per_lang=5000, page=1, max_mb=None))

    warm = tmp_path / "warm.db"
    _build(warm, 9, articles=300, keywords=3_000, with_boilerplate=False)
    db = _session(warm)
    digest(db)  # lazy tables a first export loads are not this export's own memory
    db.close()

    p = tmp_path / f"entry{keywords}.db"
    _build(p, seed, articles=300, keywords=keywords, with_boilerplate=False)
    db = _session(p)
    try:
        gc.collect()
        tracemalloc.start()
        try:
            body = digest(db)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        exported = json.loads(body)["data"]["corpus"]["keywords_exported"]
    finally:
        db.close()
    return peak, exported


@pytest.fixture(scope="module")
def digest_peaks(tmp_path_factory):
    """The two measured digest runs (12,000 and 30,000 keywords), made once for the two tests that
    fit a slope and an intercept through them: each run builds a database and traces a digest, so
    measuring them twice would have cost two more database builds for no extra evidence."""
    with pytest.MonkeyPatch.context() as mp:
        base = tmp_path_factory.mktemp("digest_peaks")
        return (
            _digest_peak(base, mp, keywords=12_000, seed=9),
            _digest_peak(base, mp, keywords=30_000, seed=10),
        )


def test_export_entry_constant_matches_the_measured_size(digest_peaks):
    """EXPORT_ENTRY_BYTES turns an instance's keyword count into the memory the digest needs, which
    the bundle gate compares with the machine (R27). Measured here on the digest path, the one the
    bundle runs, as the SLOPE between two corpus sizes (so the fixed part does not hide in it): the
    constant must cover the peak per exported entry, and must not sit so far above it that the
    gate refuses machines that could run the export. This is the LOWER bound: tracemalloc misses the
    allocator's overhead, so the window is wide on purpose; the resident size at 100k-410k entries,
    measured out of process, is what pins the value (the test below).

    At these sizes the grouping holds the whole window (its budget is 50,000 keywords at least), so
    the slope is the entry's own cost PLUS the grouping's: the two constants together."""
    (small_peak, small_n), (big_peak, big_n) = digest_peaks
    assert small_n > 8_000 and big_n > small_n * 1.5
    slope = (big_peak - small_peak) / (big_n - small_n)
    covered = kls.EXPORT_ENTRY_BYTES + kls.FAMILY_ROW_BYTES
    assert slope <= covered, slope
    assert slope >= covered * 0.5, slope


# The RESIDENT-size measurements the two constants rest on (peak RSS of the digest in its own
# process, synthetic databases of 21, 41 and 82 languages x 5,000 exported keywords, 2026-10-06,
# with the grouping held at 50,000 keywords: +145.7 / +192.0 / +272.8 MiB at 105,000 / 205,000 /
# 410,000 entries, a slope of 413-485 bytes per entry; the intercept, 38.8 MiB, is the earlier fit
# on the code before the digest read its keywords in batches and is still the larger figure).
# tracemalloc cannot see the allocator's overhead, the SQLite page cache or the interpreter, so it
# can only ever be a LOWER bound on these; the constants are pinned against the measurement itself,
# and moving one means measuring again, not editing a number.
_MEASURED_RSS_SLOPE_BYTES = 485
_MEASURED_RSS_INTERCEPT_BYTES = int(38.8 * 2**20)


def test_export_entry_constant_is_the_measured_resident_slope_plus_its_margin():
    """Two-sided, and by value. It must cover the slope that was measured (or the gate admits a
    machine the export then kills), and it may not drift far above it (or the gate refuses machines
    that could run the export). The margin is the ten per cent the constant's comment states."""
    assert kls.EXPORT_ENTRY_BYTES == 500
    assert kls.EXPORT_ENTRY_BYTES >= _MEASURED_RSS_SLOPE_BYTES
    assert kls.EXPORT_ENTRY_BYTES <= _MEASURED_RSS_SLOPE_BYTES * 1.15


def test_export_fixed_constant_covers_the_measured_intercept():
    """The 38 MiB the resident size showed at the three sizes is what EXPORT_FIXED_BYTES must
    cover, with a margin the comment calls 1.6x: at least the measured intercept, at most twice it.
    (A constant of 1 MiB, or zero, used to pass the tracemalloc test below: that one reads about
    zero, because the export's own structures all scale with the entries.)"""
    assert kls.EXPORT_FIXED_BYTES == 60 * 2**20
    assert kls.EXPORT_FIXED_BYTES >= _MEASURED_RSS_INTERCEPT_BYTES
    assert kls.EXPORT_FIXED_BYTES <= 2 * _MEASURED_RSS_INTERCEPT_BYTES


def test_no_python_structure_that_grows_with_the_corpus_hides_in_the_fixed_constant(digest_peaks):
    """The part of the export's memory that does not grow with the corpus (EXPORT_FIXED_BYTES) is
    the intercept of the same two-size fit. On the Python-allocation basis it is about zero (the
    export's own structures all scale with the entries); the 38 MiB the RESIDENT size shows is the
    SQLite page cache, the allocator's arenas and the interpreter, which tracemalloc cannot see and
    which the test above pins. What this test keeps is the half it can see: no Python structure
    that grows with the corpus hides in the constant."""
    (small_peak, small_n), (big_peak, big_n) = digest_peaks
    slope = (big_peak - small_peak) / (big_n - small_n)
    intercept = small_peak - slope * small_n
    assert intercept <= kls.EXPORT_FIXED_BYTES, intercept


def test_spill_row_constant_covers_the_measured_file_size(tmp_path):
    """SPILL_ROW_BYTES sizes the free-space check. Measured as the spill file's size per row with
    the rank index in place, on rows shaped like mention-bearing keywords with real-looking dates."""
    import os

    rnd = random.Random(2)
    dates = [f"2026-0{m}-1{d}" for m in range(1, 10) for d in range(10)]
    r = kls.Ranker(0, 10**9, heap_rows=10, spill_dir=tmp_path, disk_check=None)
    n = 60_000
    for kid in range(1, n + 1):
        r.add(f"l{kid % 40}", kid, rnd.randrange(1, 5000), rnd.randrange(1, 900),
              rnd.choice(dates), rnd.choice(dates), "en")
    try:
        r._flush()
        per_row = os.path.getsize(r._path) / n
    finally:
        r.close()
    assert per_row <= kls.SPILL_ROW_BYTES, per_row
    assert per_row >= kls.SPILL_ROW_BYTES / 3, per_row  # not sized to refuse a drive that has room


def _counted(path: Path):
    """A session that records every SQL statement it runs."""
    eng = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    seen: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _rec(_c, _cur, statement, *_a):  # noqa: ANN001
        seen.append(statement)

    return sessionmaker(bind=eng, future=True)(), seen


def test_the_estimate_is_read_from_the_instances_counts_and_never_scans_the_mentions(dbs):
    con = sqlite3.connect(dbs[1])
    n_art = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    max_kid = con.execute("SELECT MAX(id) FROM keywords").fetchone()[0]
    n_lang = con.execute("SELECT COUNT(DISTINCT language) FROM articles").fetchone()[0]
    con.close()
    db, seen = _counted(dbs[1])
    est = kls.estimate_export_need(db, per_language=5000)
    db.close()
    assert est["articles"] == n_art and est["keyword_id_bound"] == max_kid
    assert est["languages"] == n_lang + 1  # the "?" an article without a language falls in
    assert est["exportable_keywords"] == min(max_kid, est["languages"] * 5000)
    assert est["need_mb"] >= kls.EXPORT_FIXED_BYTES / 2**20
    assert seen and not any("keyword_mentions" in q for q in seen), seen


def test_the_estimate_grows_with_the_keywords_until_the_window_bounds_it(tmp_path):
    needs = {}
    for k in (500, 4_000):
        p = tmp_path / f"est{k}.db"
        _build(p, 2, articles=120, keywords=k, with_boilerplate=False)
        db = _session(p)
        needs[k] = (
            kls.estimate_export_need(db, per_language=5000),
            kls.estimate_export_need(db, per_language=10),
        )
        db.close()
    assert needs[4_000][0]["need_mb"] > needs[500][0]["need_mb"]
    # a window of 10 per language holds at most languages x 10 entries, whatever the table holds
    for k in needs:
        small = needs[k][1]
        assert small["exportable_keywords"] == min(k, small["languages"] * 10)
        assert small["need_mb"] < needs[k][0]["need_mb"] or k == 500


def test_sparse_article_ids_do_not_size_the_estimate_from_the_largest_id(tmp_path):
    """Three articles with ids near a billion: a flat array over the id range would be 12 GB. The
    scan uses two dicts for ids this sparse (see ArticleMaps), and the estimate must agree."""
    p = tmp_path / "sparse.db"
    _build(p, 4, articles=3, keywords=50, with_boilerplate=False)
    con = sqlite3.connect(p)
    con.execute("UPDATE articles SET id = id + 900000000")
    con.execute("UPDATE keyword_mentions SET article_id = article_id + 900000000")
    con.commit()
    con.close()
    db = _session(p)
    est = kls.estimate_export_need(db, per_language=5000)
    db.close()
    assert est["need_mb"] < 100, est


def test_fit_window_is_the_largest_equal_window_and_keeps_every_language():
    counts = {"en": 1000, "fr": 50, "de": 7}
    assert kle.fit_window(counts, 10_000) is None
    for ceiling in (20, 100, 500, 1057 - 1):
        c = kle.fit_window(counts, ceiling)
        assert c is not None
        assert sum(min(n, c) for n in counts.values()) <= max(ceiling, 3)
        assert sum(min(n, c + 1) for n in counts.values()) > ceiling or c >= max(counts.values())
    assert kle.fit_window(counts, 1) == 1  # a language is never dropped


def test_resolve_max_bytes_treats_zero_as_no_cap_and_a_sentinel_as_left_out():
    assert kle.resolve_max_bytes("zip", 0, 999) is None
    assert kle.resolve_max_bytes("zip", 0.0, 999) is None
    assert kle.resolve_max_bytes("zip", 2, 999) == 2 * 1024 * 1024
    assert kle.resolve_max_bytes("zip", None, 999) == 999
    assert kle.resolve_max_bytes("zip", object(), 999) == 999  # a direct call's Query() default
    assert kle.resolve_max_bytes("json", 0, 999) is None  # the JSON stream has no byte cap


def test_stale_scratch_is_swept_and_a_live_one_is_not(tmp_path):
    import os
    import time

    old = tmp_path / f"{kle.ZIP_TMP_PREFIX}1-1.zip"
    fresh = tmp_path / f"{kls.SPILL_PREFIX}2-2.sqlite"
    other = tmp_path / "keep-me.txt"
    for p in (old, fresh, other):
        p.write_bytes(b"x")
    long_ago = time.time() - 13 * 3600
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    kle.sweep_stale_scratch(tmp_path)
    assert not old.exists() and fresh.exists() and other.exists()


# --------------------------------------------------------------------------- the route


def _zip(path_or_resp) -> dict[str, bytes]:
    path = Path(path_or_resp.path)
    try:
        z = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
        return {n: z.read(n) for n in z.namelist()}
    finally:
        kle.unlink_quietly(path)


def _call(db, **kw):
    from src.api.diagnostics.keywords import keyword_log

    kw.setdefault("digest", False)
    kw.setdefault("fmt", "zip")
    kw.setdefault("per_lang", 1_000_000)
    kw.setdefault("page", 1)
    kw.setdefault("max_mb", 0)
    return keyword_log(db=db, **kw)


def _drain_body(resp) -> bytes:
    async def _go() -> bytes:
        return b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])

    return asyncio.run(_go())


def _same_archive(a: dict[str, bytes], b: dict[str, bytes]) -> None:
    assert sorted(a) == sorted(b)
    for name in a:
        if name == "manifest.json":
            ma, mb = json.loads(a[name]), json.loads(b[name])
            for m in (ma, mb):
                m.pop("generated_at", None)
                m.pop("ranking_spilled_to_disk", None)
            assert ma == mb
        elif name == "summary.json":
            sa, sb = json.loads(a[name]), json.loads(b[name])
            for s in (sa, sb):
                s.pop("generated_at", None)
                # the budget is the machine's (it differs between the two runs by construction)
                s["data"]["families_provenance"].pop("basis_budget_keywords", None)
            assert sa == sb
        else:
            assert a[name] == b[name], name


def test_the_archive_is_the_same_whether_the_ranking_stayed_in_memory_or_went_to_disk(
    dbs, data_dir, monkeypatch
):
    db = _session(dbs[1])
    heap = _zip(_call(db))
    assert json.loads(heap["manifest.json"])["ranking_spilled_to_disk"] is False
    monkeypatch.setattr(kls, "memory_plan", lambda _avail: {"heap_rows": 30, "batch": 7, "family_rows": 10**9})
    import src.api.diagnostics.keywords as kw_mod

    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)
    spill = _zip(_call(db))
    assert json.loads(spill["manifest.json"])["ranking_spilled_to_disk"] is True
    _same_archive(heap, spill)
    assert _leftovers(data_dir) == []
    db.close()


def test_no_cap_writes_the_whole_window_and_says_so(dbs, data_dir):
    db = _session(dbs[0])
    members = _zip(_call(db))
    man = json.loads(members["manifest.json"])
    assert man["max_bytes"] is None and man["keywords_omitted_to_fit"] == 0
    assert man["keywords_in_archive"] == man["keywords_total_corpus"] and man["has_more"] is False
    assert "window_clamped_to_fit_cap" not in man
    shard_total = sum(
        json.loads(v)["count"] for n, v in members.items() if n.startswith("keywords/")
    )
    assert shard_total == man["keywords_in_archive"]
    db.close()


def test_a_byte_cap_trims_and_every_keyword_is_accounted_for(dbs, data_dir):
    """The disclosure arithmetic: in the archive + omitted to fit == the window that was asked
    for, however the window was cut (before anything was built, or by the trim loop after)."""
    db = _session(dbs[0])
    asked = json.loads(_zip(_call(db))["manifest.json"])["keywords_in_archive"]
    for mb in (0.002, 0.02, 0.2):
        members = _zip(_call(db, max_mb=mb))
        man = json.loads(members["manifest.json"])
        assert man["max_bytes"] == max(256, int(mb * 1024 * 1024))
        assert man["keywords_in_archive"] + man["keywords_omitted_to_fit"] == asked, mb
        assert sum(m["omitted_to_fit"] for m in man["languages"]) == man["keywords_omitted_to_fit"]
    db.close()


def test_the_trim_loop_keeps_going_until_the_archive_fits(tmp_path):
    """Not "at most eight rebuilds": a cap many rounds away is still reached. A stand-in archive
    with deflate's real shape (a fixed part the trim cannot touch plus a part per kept keyword)
    needs ten rounds to get from 1,000 keywords to the 5 that fit under a cap 200 bytes above
    the fixed part, so a loop of one round, or of the eight the old code allowed, fails here."""

    class Job:
        max_bytes = 5_200

        def __init__(self) -> None:
            self.writes: list[tuple[dict, dict]] = []

        def write(self, keep, omitted):
            self.writes.append((dict(keep), dict(omitted)))
            path = tmp_path / f"a{len(self.writes)}.zip"
            path.write_bytes(b"x" * (5_000 + 40 * sum(keep.values())))
            return path

    job = Job()
    path = kle.finish_zip(job, {"en": 600, "fr": 400}, {})  # type: ignore[arg-type]
    assert path.stat().st_size <= Job.max_bytes
    assert len(job.writes) > 9  # one build plus ten trims: more than the old eight-round guard
    keep, omitted = job.writes[-1]
    assert sum(keep.values()) + sum(omitted.values()) == 1_000  # every dropped keyword is counted
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # each earlier archive was removed


def test_a_cap_several_rounds_away_is_reached_end_to_end(dbs, data_dir, monkeypatch):
    """The real writer, not a stand-in: a cap at 60 % of the whole archive is reached by trimming
    every language's tail over several rebuilds, and every dropped keyword is counted. (The
    summary is computed once over the first round's window and is never trimmed, so a cap below
    it cannot be met: that case is the next test.)"""
    db = _session(dbs[1])
    full = _call(db)
    whole = Path(full.path).stat().st_size
    kle.unlink_quietly(Path(full.path))
    # A cap no archive can meet trims every language to one keyword and stops: what is left is the
    # summary (and manifest) of the window, the part the trim cannot touch. A cap halfway between
    # that and the whole archive is reachable, and a few rebuilds away.
    unreachable = _call(db, max_mb=whole * 0.3 / 2**20)
    floor = Path(unreachable.path).stat().st_size
    kle.unlink_quietly(Path(unreachable.path))
    cap = floor + (whole - floor) // 2
    assert floor < cap < whole

    writes: list[int] = []
    real_write = kle.ZipJob.write

    def counting(self, keep, omitted):
        writes.append(sum(keep.values()))
        return real_write(self, keep, omitted)

    monkeypatch.setattr(kle.ZipJob, "write", counting)
    resp = _call(db, max_mb=cap / 2**20)
    size = Path(resp.path).stat().st_size
    man = json.loads(_zip(resp)["manifest.json"])
    assert size <= man["max_bytes"] <= cap, (size, man["max_bytes"], cap)
    assert man["keywords_omitted_to_fit"] > 0 and len(writes) >= 3, writes
    assert writes == sorted(writes, reverse=True) and len(set(writes)) == len(writes)  # each round smaller
    db.close()


def test_a_summary_larger_than_the_cap_ends_with_one_keyword_per_language_and_says_so(dbs, data_dir):
    """The cap is not a guarantee: summary.json is never trimmed. The loop must STOP (not spin)
    once nothing is left to drop, and the archive is returned over the cap, every dropped keyword
    still counted."""
    db = _session(dbs[1])
    asked = json.loads(_zip(_call(db))["manifest.json"])["keywords_in_archive"]
    resp = _call(db, max_mb=0.000001)  # floored at 256 bytes: smaller than any summary
    size = Path(resp.path).stat().st_size
    members = _zip(resp)
    man = json.loads(members["manifest.json"])
    assert size > man["max_bytes"] == 256
    assert all(m["keywords"] == 1 for m in man["languages"])
    assert man["keywords_in_archive"] + man["keywords_omitted_to_fit"] == asked
    assert "never trimmed" in man["note"]
    db.close()


def test_a_window_far_beyond_the_cap_is_cut_up_front_and_disclosed(dbs, data_dir):
    db = _session(dbs[1])
    man = json.loads(_zip(_call(db, max_mb=0.001))["manifest.json"])
    note = man["window_clamped_to_fit_cap"]
    assert note["asked_per_lang"] == 1_000_000 and note["exported_per_language_max"] >= 1
    assert "max_mb=0" in note["why"]
    db.close()


def test_families_are_grouped_over_the_whole_window_unless_memory_says_otherwise(
    dbs, data_dir, monkeypatch
):
    """The limit on the families' basis is the machine's memory, never a fixed number, and the
    summary says which case it is in and what the limit protects."""
    import src.api.diagnostics.keywords as kw_mod

    db = _session(dbs[1])
    prov = json.loads(_zip(_call(db))["summary.json"])["data"]["families_provenance"]
    assert prov["basis_is_whole_window"] is True and prov["basis_per_language"] is None
    assert "WHOLE window" in prov["note"] and "memory" in prov["note"]

    monkeypatch.setattr(
        kls, "memory_plan", lambda _a: {"heap_rows": 10**9, "batch": 800, "family_rows": 60}
    )
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)
    prov = json.loads(_zip(_call(db))["summary.json"])["data"]["families_provenance"]
    assert prov["basis_is_whole_window"] is False
    assert 1 <= prov["basis_keywords"] <= 60 and prov["basis_budget_keywords"] == 60
    assert prov["basis_per_language"] >= 1 and "budget" in prov["note"]
    db.close()


def test_a_direct_call_with_every_default_still_answers(dbs, data_dir):
    """src/api/diagnostics/performance.py calls ``keyword_log(db=db)``: every parameter then
    arrives as a ``Query()`` sentinel, including the new ``max_mb``."""
    from src.api.diagnostics.keywords import keyword_log

    db = _session(dbs[2])
    doc = json.loads(_drain_body(keyword_log(db=db)))
    assert doc["kind"] == "keyword-diagnostics"
    db.close()


def test_an_empty_corpus_exports_an_empty_archive_and_empty_streams(tmp_path, data_dir):
    path = tmp_path / "empty.db"
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    db = _session(path)
    man = json.loads(_zip(_call(db))["manifest.json"])
    assert man["keywords_in_archive"] == 0 and man["languages"] == [] and man["has_more"] is False
    for digest in (False, True):
        doc = json.loads(_drain_body(_call(db, fmt="json", digest=digest, per_lang=5000, max_mb=None)))
        assert doc["data"]["corpus"]["keywords_exported"] == 0
    assert _leftovers(data_dir) == []
    db.close()


def test_the_json_stream_writes_the_families_exactly_as_one_dumps_would(tmp_path, data_dir):
    """The families are written a slice at a time (one dumps of all of them built a second copy
    of them on the largest instance); the bytes are the ones ``json.dumps`` gives."""
    p = tmp_path / "fam.db"
    _build(p, 2, articles=200, keywords=3_000)
    db = _session(p)
    body = _drain_body(_call(db, fmt="json", digest=False, per_lang=5000, max_mb=None)).decode()
    doc = json.loads(body)
    assert len(doc["data"]["families"]) > 1000  # more than one slice, so the joins are exercised
    assert ', "families": ' + json.dumps(doc["data"]["families"], separators=(",", ":")) in body
    db.close()


def test_the_json_stream_with_no_families_still_writes_an_empty_list(tmp_path, data_dir):
    path = tmp_path / "nofam.db"
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    db = _session(path)
    body = _drain_body(_call(db, fmt="json", digest=False, per_lang=5000, max_mb=None)).decode()
    assert ', "families": []' in body and json.loads(body)["data"]["families"] == []
    db.close()


@pytest.mark.parametrize("digest", [False, True])
def test_memory_running_out_after_the_scan_stops_the_json_and_digest_forms_with_a_503(
    dbs, data_dir, monkeypatch, digest
):
    """The phase that holds every survivor, its metadata and the families at once (about a
    gigabyte on the largest instance) was outside the memory stop: only the gate guarded it. The
    stop is read between its steps and answers 503 with the numbers."""
    import src.api.diagnostics.keywords as kw_mod
    from src.database.maintenance import MemoryShort

    state = {"after_scan": False, "checks_after": 0}
    real = kw_mod.build_families

    def families(items, overrides):
        state["after_scan"] = True
        return real(items, overrides)

    def stop(*, started=None):
        if state["after_scan"]:
            state["checks_after"] += 1
            raise MemoryShort("only 40 MB of memory is available, the floor is 300 MB")

    monkeypatch.setattr(kw_mod, "build_families", families)
    monkeypatch.setattr(kw_mod, "raise_if_memory_short", stop)
    db = _session(dbs[1])
    with pytest.raises(HTTPException) as err:
        _call(db, fmt="json", digest=digest, per_lang=5000, max_mb=None)
    assert err.value.status_code == 503 and "MB" in str(err.value.detail)
    assert state["checks_after"] == 1 and _leftovers(data_dir) == []
    db.close()


def test_the_survivor_phase_reads_the_memory_stop_as_it_goes_not_only_at_its_ends(
    tmp_path, data_dir, monkeypatch
):
    """Counted INSIDE the survivor loop only: between the first entry built and the families'
    grouping. The scan and the metadata batches read the stop too (every 800 survivors), so a
    count over the whole request would pass with the loop's own check deleted -- which is the
    loop that holds about a gigabyte at the largest instance's size."""
    import src.api.diagnostics.keywords as kw_mod

    p = tmp_path / "many.db"
    _build(p, 9, articles=200, keywords=9_000, with_boilerplate=False)
    state = {"in_loop": False, "reads_in_loop": 0, "entries": 0}
    real_entry, real_families = kw_mod.entry_for, kw_mod.build_families

    def entry(*a, **k):
        state["in_loop"] = True
        state["entries"] += 1
        return real_entry(*a, **k)

    def families(items, overrides):
        state["in_loop"] = False
        return real_families(items, overrides)

    def stop(*, started=None):
        if state["in_loop"]:
            state["reads_in_loop"] += 1

    monkeypatch.setattr(kw_mod, "entry_for", entry)
    monkeypatch.setattr(kw_mod, "build_families", families)
    monkeypatch.setattr(kw_mod, "raise_if_memory_short", stop)
    db = _session(p)
    doc = json.loads(_drain_body(_call(db, fmt="json", digest=True, per_lang=5000, max_mb=None)))
    survivors = doc["data"]["corpus"]["keywords_exported"]
    assert survivors > 4_000 and state["entries"] >= survivors
    # one read at the start of every block of 2,000 survivors: ceil(n / 2,000)
    assert state["reads_in_loop"] == -(-survivors // 2_000), state
    db.close()


@pytest.mark.parametrize(
    "headers",
    [
        [(b"range", b"bytes=99999999-")],  # unsatisfiable: Starlette answers 416 and skips its background task
        [(b"range", b"bytes=abc")],  # malformed: 400
        [(b"range", b"bytes=0-9")],  # partial: 206
        [],
    ],
)
def test_the_scratch_archive_is_deleted_whatever_the_request_asked_for(dbs, data_dir, headers):
    resp = _call(_session(dbs[0]))
    path = Path(resp.path)
    assert path.exists()
    sent: list[dict] = []

    async def _send() -> None:
        async def receive() -> dict:
            return {"type": "http.disconnect"}

        async def send(m: dict) -> None:
            sent.append(m)

        await resp({"type": "http", "method": "GET", "headers": headers}, receive, send)

    asyncio.run(_send())
    assert not path.exists() and _leftovers(data_dir) == []


def test_the_digest_and_the_json_stream_keep_their_shape(dbs, data_dir):
    db = _session(dbs[1])

    def body(**kw) -> dict:
        return json.loads(_drain_body(_call(db, **kw)))

    full = body(fmt="json", digest=False, per_lang=5000, max_mb=None)
    dig = body(fmt="json", digest=True, per_lang=5000, max_mb=None)
    kws = full["data"]["keywords"]
    assert kws and all("language_signature" in k for k in kws)
    # the global order: mention-bearing by mentions desc, then orphans by id -- no orphan
    # precedes a keyword with mentions
    seen_orphan = False
    for k in kws:
        if k["mentions"] == 0:
            seen_orphan = True
        else:
            assert not seen_orphan
    assert [k["mentions"] for k in kws if k["mentions"]] == sorted(
        (k["mentions"] for k in kws if k["mentions"]), reverse=True
    )
    dig_prov = dig["data"]["keywords_digest"]
    assert dig_prov["shown"] <= dig_prov["total"] == len(kws)
    assert list(full["data"]["corpus"]["exported_per_language"])  # order pinned by the differential run
    db.close()


# --------------------------------------------------------------------------- refusals


def test_a_machine_already_at_its_floor_is_refused_with_numbers_and_leaves_nothing(
    dbs, data_dir, monkeypatch
):
    import src.database.maintenance as mt

    monkeypatch.setattr(mt, "_available_mb", lambda: 40.0)
    monkeypatch.setattr(mt, "_read_memory_floor_mb", lambda: 300.0)
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    assert err.value.status_code == 503 and "MB" in str(err.value.detail)
    # Said as a refusal to START, not as a stop after some seconds of work: nothing had run.
    assert "did not start this read" in str(err.value.detail)
    assert _leftovers(data_dir) == []
    db.close()


def test_memory_running_out_mid_archive_stops_it_and_removes_the_partial_file(
    dbs, data_dir, monkeypatch
):
    import src.database.maintenance as mt

    calls = {"n": 0}

    def shrinking() -> float:
        calls["n"] += 1
        return 4000.0 if calls["n"] <= 4 else 30.0

    monkeypatch.setattr(mt, "_available_mb", shrinking)
    monkeypatch.setattr(mt, "_read_memory_floor_mb", lambda: 300.0)
    db = _session(dbs[1])
    with pytest.raises(HTTPException) as err:
        _call(db)
    assert err.value.status_code == 503
    assert calls["n"] > 4  # it got going before the machine ran short
    assert _leftovers(data_dir) == []
    db.close()


def test_a_full_disk_stops_the_archive_with_507_and_removes_it(dbs, data_dir, monkeypatch):
    """The between-batches watch, the backstop: the up-front check is turned off here so the
    archive actually starts, and the drive is already at its reserve."""
    import collections

    import src.api.diagnostics.keywords as kw_mod

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(kw_mod, "zip_disk_preflight", lambda *_a: None)
    monkeypatch.setattr(kle.shutil, "disk_usage", lambda _p: Usage(10**12, 10**12 - 1000, 1000))
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    assert err.value.status_code == 507 and "GiB" in str(err.value.detail)
    assert _leftovers(data_dir) == []
    db.close()


def test_an_archive_the_drive_cannot_take_is_refused_before_a_byte_of_it_is_written(
    dbs, data_dir, monkeypatch
):
    """Expected output = the window's keywords x a conservative zipped entry + the fixed members.
    The drive below has the reserve and 1 GiB to spare; the archive is expected to need far more,
    so nothing is written and the refusal says how much was needed and how much is free."""
    import collections

    Usage = collections.namedtuple("Usage", "total used free")
    reserve = 10**12 // 100 * 1  # 1 % of a 1 TB drive: the export keeps this free
    monkeypatch.setattr(kle.shutil, "disk_usage", lambda _p: Usage(10**12, 0, reserve + 2**30))
    monkeypatch.setattr(kle, "ZIP_BYTES_PER_ENTRY", 10**7)  # 10 MB an entry -> a huge archive
    wrote: list[int] = []
    monkeypatch.setattr(kle.ZipJob, "write", lambda *_a, **_k: wrote.append(1))
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    assert err.value.status_code == 507 and "GiB" in str(err.value.detail)
    assert "free" in str(err.value.detail)
    assert wrote == [] and _leftovers(data_dir) == []
    db.close()


def test_the_expected_archive_size_is_bounded_by_the_cap_when_there_is_one():
    assert kle.expected_zip_bytes(0, None) == kle.ZIP_FIXED_BYTES
    assert kle.expected_zip_bytes(1_000_000, None) == kle.ZIP_FIXED_BYTES + 1_000_000 * kle.ZIP_BYTES_PER_ENTRY
    cap = 9 * 2**20
    assert kle.expected_zip_bytes(10**9, cap) == cap + kle.ZIP_FIXED_BYTES
    assert kle.expected_zip_bytes(10, cap) == kle.ZIP_FIXED_BYTES + 10 * kle.ZIP_BYTES_PER_ENTRY


def test_the_zipped_entry_constant_covers_the_measured_size(tmp_path, monkeypatch):
    """ZIP_BYTES_PER_ENTRY is what the disk check multiplies by. Measured on keywords whose terms
    are random letters (about as incompressible as a term list gets): it must cover the archive
    per entry and not be so high that a drive with plenty of room is refused."""
    import string

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    p = tmp_path / "zipped.db"
    _build(p, 6, articles=800, keywords=20_000, with_boilerplate=False)
    rnd = random.Random(11)
    words = ["".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(5, 14)))
             for _ in range(20_000)]
    con = sqlite3.connect(p)
    con.executemany("UPDATE keywords SET term=?, normalized_term=? WHERE id=?",
                    [(w.title(), w, i + 1) for i, w in enumerate(words)])
    con.commit()
    con.close()
    db = _session(p)
    try:
        resp = _call(db)
        size = Path(resp.path).stat().st_size
        members = _zip(resp)
    finally:
        db.close()
    entries = json.loads(members["manifest.json"])["keywords_in_archive"]
    assert entries > 15_000
    per_entry = size / entries
    assert per_entry <= kle.ZIP_BYTES_PER_ENTRY, per_entry
    assert per_entry * 10 >= kle.ZIP_BYTES_PER_ENTRY, per_entry


def test_a_spill_the_disk_cannot_take_is_refused_before_the_file_exists(dbs, data_dir, monkeypatch):
    import collections

    import src.api.diagnostics.keywords as kw_mod

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(kls, "memory_plan", lambda _a: {"heap_rows": 20, "batch": 7, "family_rows": 10**9})
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)
    monkeypatch.setattr(kle.shutil, "disk_usage", lambda _p: Usage(10**12, 10**12 - 1000, 1000))
    db = _session(dbs[0])
    with pytest.raises(HTTPException) as err:
        _call(db)
    assert err.value.status_code == 507
    assert "whatever else writes" in err.value.detail, "the reserve sentence"
    assert _leftovers(data_dir) == []
    db.close()


# --------------------------------------------------------------------------- memory


def _peak_python_bytes(fn) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_what_the_zip_holds_does_not_grow_with_the_window(tmp_path_factory, monkeypatch):
    """THE property the fix is for: 6x the keywords must not cost 6x the memory. The ranking is
    forced onto disk (the mode a small machine is in), so what remains is what the archive
    itself holds -- one batch, the article arrays, the digests -- and tracemalloc sees every
    Python allocation of it. (The old builder measured ~2 KB per keyword here.)"""
    import src.api.diagnostics.keywords as kw_mod

    root = tmp_path_factory.mktemp("kw-flat")
    monkeypatch.setenv("OO_DATA_DIR", str(root))
    # The families are grouped over what fits a memory budget (production: a tenth of the
    # memory available at the start, 2.5 KB per keyword: FAMILY_ROW_BYTES); both windows below are LARGER than
    # the budget used here, so what is held has reached its bound.
    monkeypatch.setattr(
        kls, "memory_plan", lambda _a: {"heap_rows": 500, "batch": 800, "family_rows": 900}
    )
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)
    def one(n: int) -> int:
        p = root / f"flat{n}.db"
        _build(p, 5, articles=300, keywords=n, with_boilerplate=False)
        db = _session(p)

        def run() -> None:
            resp = _call(db)
            kle.unlink_quietly(Path(resp.path))

        try:
            return _peak_python_bytes(run)
        finally:
            db.close()

    # A warm-up run first: the first export of a process loads lazy tables (the ring and
    # stop-word data) that are not this export's own memory and would swamp the small window.
    one(2_000)
    small, big = one(4_000), one(24_000)
    peaks = {4_000: small, 24_000: big}
    # 6x the keywords; allow the digests and the window's own bookkeeping to grow a little, but
    # nowhere near linearly (the old builder was ~2 KB per keyword = +60 MB for this step).
    assert big < small * 1.5 + 2_000_000, peaks
    assert big < 10_000_000, peaks


def test_the_old_builders_per_keyword_cost_would_have_failed_that_bound():
    """A calibration of the bound above, not a test of the code: 24,000 entry dicts of the shape
    the old builder held for EVERY keyword of the window weigh far more than the bound allows, so
    the bound is tight enough to have caught the defect it guards against."""
    def hold() -> None:
        entries = [
            {"term": f"term{i}", "normalized": f"term{i}", "kind": "term", "language": "en",
             "mentions": i, "articles": i, "first_seen": "2026-01-01", "last_seen": "2026-01-02",
             "hidden": False, "language_signature": {"en": i}, "language_mismatch": False}
            for i in range(24_000)
        ]
        json.dumps(entries)

    assert _peak_python_bytes(hold) > 12_000_000


# --------------------------------------------------------------------------- the response


def test_the_scratch_archive_is_deleted_once_it_has_been_sent(dbs, data_dir):
    resp = _call(_session(dbs[0]))
    path = Path(resp.path)
    assert path.exists() and path.parent == data_dir
    assert resp.media_type == "application/zip" and "oo-keyword-log-" in resp.headers["content-disposition"]

    async def _send() -> None:
        async def receive() -> dict:
            return {"type": "http.disconnect"}

        async def send(_m: dict) -> None:
            return None

        await resp({"type": "http", "method": "GET", "headers": []}, receive, send)

    asyncio.run(_send())
    assert not path.exists() and _leftovers(data_dir) == []


# --------------------------------------------------------------------------- the digest's memory


def _digest_doc(db, **kw) -> dict:
    doc = json.loads(_drain_body(_call(db, fmt="json", digest=True, per_lang=5000, max_mb=None, **kw)))
    doc.pop("generated_at", None)
    return doc


def _with_plan(monkeypatch, **override):
    """The route's memory plan with some of its numbers set, as a machine of that size would."""
    from src.api.diagnostics import keywords as route

    real = route.memory_plan
    monkeypatch.setattr(route, "memory_plan", lambda available: {**real(available), **override})


def test_the_digest_reads_metadata_one_batch_at_a_time_and_says_the_same_whatever_the_batch(
    dbs, data_dir, monkeypatch
):
    """The digest used to fetch every survivor's metadata and signature before it built an entry,
    so its resident size grew with the window by the metadata of every keyword (1,057 MiB at 82
    languages x 5,000). It now asks for a batch, builds that batch's entries, feeds the digests and
    lets the metadata go. The document is the same whatever the batch is."""
    from src.api.diagnostics import keywords as route

    # The budget the digest reports is a tenth of the memory available when it starts: hold the
    # reading still, or two runs differ by what the machine did between them.
    monkeypatch.setattr(route, "available_bytes_now", lambda: 8 * 2**30)
    db = _session(dbs[1])
    whole = _digest_doc(db)
    survivors = whole["data"]["corpus"]["keywords_exported"]
    assert survivors > 300, survivors  # several batches of 100, or the test says nothing

    asked: list[int] = []
    real = route.fetch_meta
    monkeypatch.setattr(route, "fetch_meta", lambda d, ids: (asked.append(len(ids)), real(d, ids))[1])
    _with_plan(monkeypatch, batch=100)
    small_batches = _digest_doc(db)

    assert max(asked) <= 100 and len(asked) >= survivors // 100, (max(asked), len(asked))
    assert small_batches == whole
    db.close()


def test_the_digests_sample_is_the_highest_mentions_with_ties_in_window_order(dbs, data_dir):
    """The 100 keywords the digest prints are chosen while the window is read in batches, by a
    bounded heap. A stable sort of the whole window, highest first, is what it replaced, and the
    window has heavy ties on mentions, so the tie order is what could differ."""
    db = _session(dbs[1])
    full = json.loads(_drain_body(_call(db, fmt="json", digest=False, per_lang=5000, max_mb=None)))
    dig = _digest_doc(db)
    window = full["data"]["keywords"]
    assert len(window) > 300 and len({k["mentions"] for k in window[:100]}) < 100  # ties inside the top
    expected = sorted(window, key=lambda k: k["mentions"], reverse=True)[:100]
    assert dig["data"]["keywords"] == expected
    assert dig["data"]["keywords_digest"]["total"] == len(window)
    db.close()


def test_a_machine_that_cannot_group_the_window_groups_a_prefix_and_says_so(dbs, data_dir, monkeypatch):
    """The families' grouping is the digest's largest working set (2.5 KB per keyword it
    groups: FAMILY_ROW_BYTES), so it is sized from the memory available when the export starts, as the archive's is.
    Everything else the digest says covers the whole window either way, and the provenance names
    what the grouping was given."""
    db = _session(dbs[1])
    whole = _digest_doc(db)["data"]
    prov = whole["families_provenance"]
    assert prov["basis_is_whole_window"] is True and prov["basis_per_language"] is None
    assert prov["basis_keywords"] == whole["corpus"]["keywords_exported"]
    assert "first " not in prov["note"]  # the note is the one it has always been

    _with_plan(monkeypatch, family_rows=60)
    cut = _digest_doc(db)["data"]
    cprov = cut["families_provenance"]
    assert cprov["basis_is_whole_window"] is False
    assert 1 <= cprov["basis_per_language"] < max(whole["corpus"]["exported_per_language"].values())
    assert 0 < cprov["basis_keywords"] <= 60 and cprov["basis_budget_keywords"] == 60
    assert f"first {cprov['basis_per_language']} keywords of each language" in cprov["note"]
    assert cut["families_summary"]["total_families"] < whole["families_summary"]["total_families"]
    # what the grouping was NOT given is still read in full
    for key in ("corpus", "keywords", "keywords_digest", "stopword_candidates", "ring_candidates",
                "per_source_concentration"):
        assert cut[key] == whole[key], key
    db.close()

@pytest.fixture(scope="module")
def hidden_db(tmp_path_factory):
    """The first fixture corpus plus, in four of its languages, three keywords the digest hides (a
    stop-word, a number, a short word) mentioned in that language's articles only and often enough
    to outrank everything else there: they sit at the front of that language's window, so a basis
    cut that counted positions wrongly, or that fed hidden keywords to the grouping, would show."""
    root = tmp_path_factory.mktemp("kw-hidden")
    path = root / "hidden.db"
    _build(path, 1, articles=150, keywords=900)
    con = sqlite3.connect(path)
    kid = con.execute("SELECT MAX(id) FROM keywords").fetchone()[0]
    mentions = []
    for lang in ("en", "fr", "de", "zh"):
        in_lang = [r[0] for r in con.execute("SELECT id FROM articles WHERE language=?", (lang,))]
        assert len(in_lang) > 10, lang
        for term in ("the", "2026", "of"):
            kid += 1
            con.execute(
                "INSERT INTO keywords(id,term,normalized_term,language,is_entity) VALUES (?,?,?,?,0)",
                (kid, term, term, lang),
            )
            mentions += [(kid, aid, 3, "2026-05-01", 1) for aid in in_lang]
    con.executemany(
        "INSERT INTO keyword_mentions(keyword_id,article_id,count,observed_on,source_id)"
        " VALUES (?,?,?,?,?)",
        mentions,
    )
    con.commit()
    con.close()
    return path


def _window_of(db) -> list[dict]:
    """The keywords the window holds, in the order the export writes them (each language's own order)."""
    full = json.loads(_drain_body(_call(db, fmt="json", digest=False, per_lang=5000, max_mb=None)))
    return full["data"]["keywords"]


def _window_language(entry: dict) -> str:
    """The language whose window an entry sits in: the DOMINANT language of the articles that
    mention it (ties: the code ascending), and its stored language only when nothing mentions it
    ("?" when that is empty too), as the scan decides it."""
    sig = entry["language_signature"]
    if sig:
        return min(sig, key=lambda lg: (-sig[lg], lg))
    return entry["language"] or "?"


def test_a_cut_hands_the_grouping_each_languages_own_first_keywords_hidden_ones_counted_in_place(
    hidden_db, data_dir, monkeypatch
):
    """WHICH keywords the grouping is given when the machine cannot hold the window. The prefix is
    each language's own (never a global mentions-ranked cut, the shape that anglicised the export);
    a keyword the digest hides takes its place in the prefix and is counted there, and is never fed
    to the grouping; and the note states the budget it was cut to."""
    from src.api.diagnostics import keywords as route

    db = _session(hidden_db)
    window = _window_of(db)
    assert sum(k["hidden"] for k in window) >= 12 and len({_window_language(k) for k in window}) >= 5

    seen: dict[str, list] = {}
    real = route.build_families
    monkeypatch.setattr(route, "build_families", lambda items, ov: (seen.update(items=list(items)), real(items, ov))[1])
    _with_plan(monkeypatch, family_rows=200)
    cut = _digest_doc(db)["data"]
    prov = cut["families_provenance"]
    c = prov["basis_per_language"]
    assert c is not None and 3 < c < 150, c

    position: dict = {}
    taken, expected = 0, []
    for k in window:
        lg = _window_language(k)
        i = position[lg] = position.get(lg, -1) + 1
        if i < c:
            taken += 1  # a hidden keyword counts in the position and in the basis
            if not k["hidden"]:
                expected.append({f: k[f] for f in ("term", "normalized", "kind", "mentions", "articles")})
    assert seen["items"] == expected
    assert not any(it["normalized"] in ("the", "2026", "of") for it in seen["items"])
    assert prov["basis_keywords"] == taken > len(expected)
    assert prov["basis_budget_keywords"] == 200 and taken <= 200
    assert f"({taken} keywords in all, the largest set that fits the 200-keyword budget)" in prov["note"]
    # the next prefix up would not have fit: the cut is the LARGEST that does
    sizes = Counter(_window_language(k) for k in window)
    assert sum(min(c + 1, n) for n in sizes.values()) > 200
    db.close()


def test_when_the_families_cover_a_prefix_no_text_says_they_cover_the_window(hidden_db, data_dir, monkeypatch):
    """A claim written for one regime must be conditional on the regime that decides it. With the
    whole window grouped, the notes say every family is counted and nothing dropped; with a prefix
    they must say what the summary covers, in the provenance AND in the summary itself (a reader
    of that block alone must not need the provenance to know)."""
    db = _session(hidden_db)
    whole = _digest_doc(db)["data"]
    assert "Every family is still counted in families_summary" in whole["families_provenance"]["selection_bias"]
    assert "Nothing is DROPPED" in whole["families_provenance"]["note"]
    assert whole["families_summary"]["basis_is_whole_window"] is True
    assert whole["families_summary"]["basis_per_language"] is None
    assert whole["families_summary"]["method"].startswith("Computed over ALL families before")
    assert whole["families_summary"]["total_families"] == whole["families_provenance"]["total"]

    _with_plan(monkeypatch, family_rows=200)
    cut = _digest_doc(db)["data"]
    prov, summ = cut["families_provenance"], cut["families_summary"]
    c = prov["basis_per_language"]
    first = f"first {c} keywords of each language's window"
    assert first in prov["selection_bias"] and first in summ["method"]
    for text in (prov["selection_bias"], prov["note"], summ["method"]):
        assert "Every family is still counted" not in text and "Nothing is DROPPED" not in text, text
        assert not text.startswith("Computed over ALL families before"), text
    assert "in no family" in prov["selection_bias"] and "in no family" in summ["method"]
    assert "among the families the grouping was given" in summ["conflated"]["method"]
    assert summ["basis_is_whole_window"] is False and summ["basis_per_language"] == c
    assert summ["total_families"] == prov["total"] < whole["families_summary"]["total_families"]
    # the budget the note states is the one in force, as a number a reader can check
    assert f"{prov['basis_budget_keywords']}-keyword budget" in prov["note"]
    assert "or 50000 keywords when that is more" in prov["note"]
    db.close()


def test_the_whole_window_families_and_summary_are_what_the_entries_give(hidden_db, data_dir, monkeypatch):
    """The digest's families, with the whole window grouped, are ``build_families`` over exactly
    the non-hidden entries of the window, and its summary is the summary over those families, with
    the two flags the summary now carries: a reference built here from the plain JSON export, not
    the digest compared with itself under another batch size."""
    from src.analytics.families import build_families
    from src.api.diagnostics.keywords import _families_summary, _keyword_zip_families_cap

    db = _session(hidden_db)
    window = _window_of(db)
    items = [{f: k[f] for f in ("term", "normalized", "kind", "mentions", "articles")}
             for k in window if not k["hidden"]]
    fams = build_families(items, {})
    cap = _keyword_zip_families_cap()
    assert len(fams) > 300 and (not cap or len(fams) <= cap)  # none is cut from the printed list
    dig = _digest_doc(db)["data"]
    assert dig["families"] == [f.to_dict() for f in fams]
    flags = {k: dig["families_summary"].pop(k) for k in ("basis_is_whole_window", "basis_per_language")}
    assert flags == {"basis_is_whole_window": True, "basis_per_language": None}
    assert dig["families_summary"] == json.loads(json.dumps(_families_summary(f.to_dict() for f in fams)))
    db.close()


class _InstanceCounts:
    """A session that answers the estimate's three counting statements with a chosen instance's
    numbers: bundle 091717's (1.83 M articles, 14.65 M keywords, 82 languages) cannot be built in
    a test, and the arithmetic over its counts is what the gate decides from."""

    def __init__(self, *, articles=1_830_000, max_kid=14_650_000, languages=81):
        self._answers = {  # most specific first: the language count also reads FROM articles
            "DISTINCT language": languages,
            "FROM keywords": max_kid,
            "FROM articles": (articles, 1, articles),
        }

    def execute(self, stmt):
        sql = str(stmt)
        for needle, value in self._answers.items():
            if needle in sql:
                return types.SimpleNamespace(one=lambda v=value: v, scalar=lambda v=value: v)
        raise AssertionError(sql)


def test_the_digests_need_follows_the_memory_it_may_group_over_and_stops_there():
    mib = 2**20
    need = {
        free: kls.estimate_export_need(_InstanceCounts(), per_language=5000, available_bytes=free * mib)
        for free in (425, 1_500, 4_000, 15_000, 64_000)
    }
    # 82 languages x 5,000 = 410,000 entries, grouped over a tenth of what is free at 2.5 KB each
    assert need[1_500]["exportable_keywords"] == 410_000
    assert need[1_500]["grouped_keywords"] == int(1_500 * mib * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES)
    # the floor: a machine with almost nothing free still groups what the default window needs
    assert need[425]["grouped_keywords"] == kls.MIN_FAMILY_ROWS
    # ...which is where a tenth of what is free stops being the larger figure (1.25 GB at 2.5 KB)
    assert 1_170 * mib * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES < kls.MIN_FAMILY_ROWS
    assert 1_500 * mib * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES > kls.MIN_FAMILY_ROWS
    # it grows with the machine's free memory until the window is grouped whole, then stops
    values = [need[f]["need_mb"] for f in sorted(need)]
    assert values == sorted(values)
    assert values[0] < values[1] < values[2] < values[3]  # strictly, while the grouping grows
    # ...and each extra grouped keyword is priced at the family row's bytes, no more and no less
    grown = need[4_000]["grouped_keywords"] - need[1_500]["grouped_keywords"]
    assert need[4_000]["need_mb"] - need[1_500]["need_mb"] == pytest.approx(
        grown * kls.FAMILY_ROW_BYTES / mib, rel=1e-6
    )
    assert need[15_000]["grouped_keywords"] == need[64_000]["grouped_keywords"] == 410_000
    assert need[15_000]["need_mb"] == need[64_000]["need_mb"]
    # an unmeasured machine gets the floor, as the route's own plan does
    assert (
        kls.estimate_export_need(_InstanceCounts(), per_language=5000, available_bytes=None)[
            "grouped_keywords"
        ]
        == kls.MIN_FAMILY_ROWS
    )


@pytest.mark.parametrize(
    "free_mib, total_mib, runs",
    [
        (1_170, 5_921, True),   # OOS-12 on 2026-10-05: 1,170 free of 5,921; the gate said 1,062 + 256 > 1,170
        (1_075, 4_033, True),   # hP on 2026-10-06
        (2_280, 6_773, True),   # bundle 091717's lower reading (6,773 MiB of RAM in all)
        (425, 5_921, False),    # OOS-11: the machine really had nothing left
    ],
)
def test_the_gate_admits_the_machines_that_can_run_the_digest_and_declines_the_ones_that_cannot(
    monkeypatch, free_mib, total_mib, runs
):
    """Three machines whose 2026-10-05/06 bundles say 'declined-ram' (two of the four that did: OOS-12
    and hP; OOS-10's reading is not in the repository) with bundle 091717's own reading, and the
    one where the decline was right (OOS-11). The numbers are theirs; the instance's counts are
    091717's, the largest seen."""
    import src.database.maintenance as mt
    from src.api.diagnostics import bundle

    monkeypatch.setattr(mt, "_available_mb", lambda: float(free_mib))
    monkeypatch.setattr(mt, "_read_memory_floor_mb", lambda: 256.0)
    reading: dict = {}
    why = bundle.ram_declined_reason(
        "keyword-log-digest.json", total_mb=float(total_mib), db=_InstanceCounts(),
        available_mb=float(free_mib), reading=reading,
    )
    assert (why is None) is runs, (why, reading)
    assert reading["need_basis"] == "estimated"
    assert reading["need_counts"]["grouped_keywords"] == int(
        max(kls.MIN_FAMILY_ROWS, free_mib * 2**20 * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES)
    )


def test_the_gate_prices_the_need_and_decides_on_one_reading_of_the_memory_available(monkeypatch):
    """The need depends on the memory available (the grouping is sized from it), and the decision
    compares the need with the memory available: two reads of a quantity that moves can price one
    figure and judge another. The gate reads once and hands the reading to the estimator, whether
    it read it itself (a slow count between two reads once gave two answers through the
    quarter-second cache) or was given one."""
    import src.database.maintenance as mt
    from src.api.diagnostics import bundle

    readings = iter([3_000.0, 400.0, 400.0, 400.0])
    calls: list[float] = []
    monkeypatch.setattr(mt, "_available_mb", lambda: (calls.append(1.0), next(readings))[1])
    monkeypatch.setattr(mt, "_read_memory_floor_mb", lambda: 256.0)
    reading: dict = {}
    why = bundle.ram_declined_reason(
        "keyword-log-digest.json", total_mb=16_000.0, db=_InstanceCounts(), reading=reading
    )
    assert len(calls) == 1, calls
    assert why is None and reading["available_mb"] == 3_000.0
    assert reading["need_counts"]["grouped_keywords"] == int(3_000 * 2**20 * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES)

    # a caller's own reading is the one both halves use, and the machine is not asked at all
    monkeypatch.setattr(mt, "_available_mb", lambda: pytest.fail("the gate read the machine again"))
    reading = {}
    bundle.ram_declined_reason(
        "keyword-log-digest.json", total_mb=16_000.0, db=_InstanceCounts(), available_mb=1_500.0,
        reading=reading,
    )
    assert reading["available_mb"] == 1_500.0
    assert reading["need_counts"]["grouped_keywords"] == int(1_500 * 2**20 * kls.FAMILY_SHARE / kls.FAMILY_ROW_BYTES)


def test_the_summary_over_light_facts_says_what_the_summary_over_whole_families_says():
    """``_family_facts`` replaced ``Family.to_dict`` as the summary's input, so that a summary over
    400,000 families holds seven fields each and not every variant of every family. The summary
    must not notice: the same numbers, over families in no particular order (the quantiles read a
    sorted list, and a summary that forgot to sort would report the order it was handed)."""
    from src.analytics.families import Family
    from src.api.diagnostics.keywords import _families_summary, _family_facts

    def fam(name, mentions, variants, *, conflated=(), manual=False):
        return Family(
            canonical=name.title(), normalized=name, kind="concept", mentions=mentions,
            articles=3, manual=manual, conflated_by=list(conflated),
            members=[{"term": f"{name}{i}", "normalized": f"{name}{i}", "mentions": 1} for i in range(variants)],
        )

    families = [
        fam("delta", 40, 5), fam("alpha", 7, 1, conflated=["lemma"]), fam("echo", 90, 3, manual=True),
        fam("bravo", 12, 2), fam("golf", 3, 7, conflated=["lemma"]), fam("charlie", 55, 1), fam("foxtrot", 21, 4),
    ]
    light = _families_summary(_family_facts(f) for f in families)
    whole = _families_summary(f.to_dict() for f in families)
    assert light == whole
    # the figures themselves, so that two summaries wrong in the same way do not agree
    assert light["total_families"] == 7
    assert light["manual_overrides"] == 1
    assert (light["variants"]["min"], light["variants"]["median"], light["variants"]["max"]) == (1, 3, 7)
    assert light["variants"]["sum"] == 23
    assert light["single_member_families"] == 2
    assert (light["mentions"]["min"], light["mentions"]["median"], light["mentions"]["max"]) == (3, 21, 90)
    # a conflated family keeps its variant count and its provenance, rarest first
    assert [(c["normalized"], c["mentions"], c["variants"], c["conflated_by"]) for c in light["conflated"]["families"]] == [
        ("golf", 3, 7, ["lemma"]),
        ("alpha", 7, 1, ["lemma"]),
    ]
    assert _family_facts(families[1]) == {
        "term": "Alpha", "normalized": "alpha", "kind": "concept", "mentions": 7,
        "variants": 1, "manual": False, "conflated_by": ["lemma"],
    }

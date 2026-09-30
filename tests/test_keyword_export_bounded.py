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

The end-to-end contract (byte-identical json, digest and shards against the implementation this
replaces) was checked by ``differential_keyword_export.py`` (shared under
``keyword-export/``) on random databases; it is not repeated here because it needs the old code.
"""

from __future__ import annotations

import asyncio
import gc
import io
import json
import random
import sqlite3
import tracemalloc
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


def test_family_row_budget_constant_matches_the_measured_size():
    """FAMILY_ROW_BYTES turns a share of available memory into how many keywords the families
    may be grouped over. Measured here on a mixed basis (a third multi-token phrases); the
    budget must cover the peak while grouping and must not be absurdly far above it."""
    from src.analytics.families import build_families

    rnd = random.Random(3)
    vocab = [f"w{i}" for i in range(5000)]
    n = 20_000
    fam = []
    for i in range(n):
        toks = [rnd.choice(vocab) for _ in range(rnd.choice([2, 3]) if rnd.random() < 0.33 else 1)]
        norm = " ".join(toks)
        fam.append((
            kls.order_key(i, i % 500, True),
            {"term": norm.title(), "normalized": norm, "kind": rnd.choice(["person", "org", "term"]),
             "mentions": i % 500, "articles": i % 90},
        ))
    gc.collect()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0] - 0
        families = build_families([it for _k, it in fam], {})
        peak_extra = tracemalloc.get_traced_memory()[1] - base
        del families
    finally:
        tracemalloc.stop()
    per_entry = peak_extra / n
    # (what `fam` itself holds is ~0.5 KB per entry and is measured before tracing starts; the
    # constant covers both, so compare it with grouping's own peak plus that)
    assert per_entry + 500 <= kls.FAMILY_ROW_BYTES * 1.25, per_entry
    assert per_entry + 500 >= kls.FAMILY_ROW_BYTES * 0.4, per_entry


def test_export_entry_constant_matches_the_measured_size(tmp_path, monkeypatch):
    """EXPORT_ENTRY_BYTES turns an instance's keyword count into the memory the digest needs, which
    the bundle gate compares with the machine (R27). Measured here on the digest path, the one the
    bundle runs: the constant must cover the peak per exported entry, and must not sit so far above
    it that the gate refuses machines that could run the export."""
    from src.api.diagnostics.keywords import keyword_log

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def digest(db) -> bytes:
        return _drain_body(keyword_log(db=db, digest=True, fmt="json", per_lang=5000, page=1, max_mb=None))

    warm = tmp_path / "warm.db"
    _build(warm, 9, articles=300, keywords=3_000, with_boilerplate=False)
    db = _session(warm)
    digest(db)  # lazy tables a first export loads are not this export's own memory
    db.close()

    p = tmp_path / "entry.db"
    _build(p, 9, articles=300, keywords=15_000, with_boilerplate=False)
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
    assert exported > 10_000
    per_entry = peak / exported
    assert per_entry <= kls.EXPORT_ENTRY_BYTES, per_entry
    assert per_entry >= kls.EXPORT_ENTRY_BYTES * 0.5, per_entry


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


def test_the_trim_loop_keeps_going_until_the_archive_fits(dbs, data_dir):
    """Not "at most eight rebuilds": a cap a few rounds away is still reached."""
    db = _session(dbs[1])
    full = _zip(_call(db))
    whole = sum(len(v) for v in full.values())
    cap_mb = max(0.0005, whole / 2**20 / 50)
    resp = _call(db, max_mb=cap_mb)
    size = Path(resp.path).stat().st_size
    cap = max(256, int(cap_mb * 2**20))
    members = _zip(resp)
    summary = len(members["summary.json"]) + len(members["manifest.json"])
    man = json.loads(members["manifest.json"])
    assert man["keywords_omitted_to_fit"] > 0
    assert size <= cap or summary > cap * 0.5, (size, cap, summary)
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
    # memory available at the start, ~2 KB per keyword); both windows below are LARGER than
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
    """Keeps the bound above honest: 24,000 entry dicts of the shape the old builder held for
    EVERY keyword of the window weigh far more than the bound allows."""
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

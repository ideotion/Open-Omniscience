"""A merge's memory and per-statement work do not scale with the corpus.

TWO SEPARATE MECHANISMS, and it matters which one does what -- a fix credited to
the wrong half is a fabricated pass waiting to happen.

  * ``PRAGMA temp_store=FILE`` is what fixes the MEASURED memory. The bundled
    sqlcipher3 is compiled ``SQLITE_TEMP_STORE=2`` (its ``compile_options`` say
    so; the stdlib says ``TEMP_STORE=1``), so statement journals, temp tables and
    transient indexes all default to RAM, and none of it is bounded by
    ``cache_size``. Measured on that engine -- one ``INSERT..SELECT``, encrypted,
    FTS trigger live, 256 MiB cache:

        rows     temp_store=MEMORY   temp_store=FILE
        100,000  +663 MB             +0 MB   (13.4s vs 7.6s)
        200,000  +377 MB  (→1,138)   +0 MB   (21.5s vs 23.3s)
        400,000  +735 MB  (→1,980)   +0 MB   (41.6s vs 45.5s)

    ~5 KB of RAM per row inserted, linear, no time penalty for moving it to disk.
    The 2026-08-05 field import inserted 1,358,765 articles in ONE statement and
    held 5,937 MB resident for the whole run.

  * WINDOWING is what bounds the work any single statement must hold -- the temp
    FILE the pragma just created, the rows in flight, the distance a Stop has to
    travel, and the interval between two honest progress readings. It is also
    insurance: the field RSS trace jumped 845 → 5,937 MB in ninety seconds and
    then held byte-stable for twenty-two hours, which a journal growing per
    inserted row does not explain. That plateau is still unexplained, so the
    corpus-independence must not rest on the one allocation we managed to name.

WHAT THIS DOES NOT FIX, stated because the temptation to claim it is strong: on
the machine that produced those numbers, memory was never the constraint --
``mem_avail`` sat steady around 4,300 MB for all twenty-two hours, and the OOM
that followed came from a diagnostics bundle reading a 1.6 GB journal, not from
the merge. So this makes a large import possible on a SMALL-RAM machine, where
5.9 GB is fatal; it is not an explanation of why that particular run was slow.
(The field artifact's own ``import_scale`` note reports a much smaller machine
than ``mem_avail`` implies. The two cannot both be right and nothing here
depends on either, so no machine size is asserted.)

So the memory test below asserts the PRAGMA, and the windowing tests assert
BOUNDED WORK -- neither claims the other's property.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import merge as merge_mod  # noqa: E402
from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}


def _corpus(path: Path, *, articles: int, first_hash: int = 0) -> None:
    """A plaintext corpus with ``articles`` rows on one source."""
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
        for i in range(first_hash, first_hash + articles):
            s.add(Article(
                url=f"https://wire.example/{i}", canonical_url=f"https://wire.example/{i}",
                source_id=src.id, title=f"t{i}", content=f"body {i}", hash=f"h{i:08d}",
                language="en", created_at=now,
            ))
        s.commit()
    engine.dispose()


def _spy_windows(monkeypatch) -> list[tuple[str, tuple]]:
    """Record every (table, window-params) an insert actually ran with."""
    seen: list[tuple[str, tuple]] = []
    real = merge_mod._insert_window

    def spy(con, batch_id, table, sql, params=()):  # noqa: ANN001
        seen.append((table, tuple(params)))
        return real(con, batch_id, table, sql, params)

    monkeypatch.setattr(merge_mod, "_insert_window", spy)
    return seen


def _pin_window(monkeypatch, ids: int) -> None:
    """Force the window to exactly ``ids``, via the clamp rather than the budget.

    The real width is derived from a sampled average row size, so pinning
    ``_MERGE_WINDOW_BYTES`` would make every test's step depend on the fixture's
    exact row bytes -- a number nobody reading the test can see. Collapsing the
    floor and ceiling onto one value makes the step deterministic and leaves the
    byte derivation itself to the test that is actually about it.
    """
    monkeypatch.setattr(merge_mod, "_MERGE_WINDOW_MIN_IDS", ids)
    monkeypatch.setattr(merge_mod, "_MERGE_WINDOW_MAX_IDS", ids)


def _hashes(path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            return {r[0] for r in c.execute(text("SELECT hash FROM articles")).all()}
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  temp_store -- the measured memory fix
# --------------------------------------------------------------------------- #
def test_the_merge_puts_temp_storage_on_disk(tmp_path, monkeypatch) -> None:
    """Behavioural, not a source grep: the merge's OWN connection must be told.

    A source-level check would pass on the comment that explains the setting,
    and a check of the app's pooled engine would test the wrong connection
    entirely -- the merge opens its own via the raw ``connect`` factory
    precisely so the app's tuning does not reach it.
    """
    seen: list[str] = []
    import src.database.connect as connect_mod

    real_connect = connect_mod.connect

    def spy_connect(*a, **kw):  # noqa: ANN001, ANN202
        con = real_connect(*a, **kw)
        # The merge installs its own trace callback per step (see _step_watch),
        # which replaces this one -- fine: every PRAGMA runs before step 1.
        con.set_trace_callback(seen.append)
        return con

    monkeypatch.setattr(connect_mod, "connect", spy_connect)

    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=2)
    _corpus(staged, articles=2, first_hash=100)
    merge_corpus(staged, working, _BATCH_META)

    pragmas = [s for s in seen if "temp_store" in s.lower()]
    assert pragmas, (
        "the merge never set temp_store, so on the shipped sqlcipher3 build "
        "(compiled TEMP_STORE=2) every statement journal is held in RAM -- ~5 KB "
        "per row inserted, unbounded by cache_size"
    )
    assert any("file" in s.lower() for s in pragmas), pragmas


def test_the_shipped_driver_really_does_default_temp_storage_to_memory() -> None:
    """The premise of the fix above, asserted rather than remembered.

    If a future sqlcipher3 wheel is compiled TEMP_STORE=1 this becomes redundant
    rather than wrong -- but silently losing the premise is how a setting gets
    "cleaned up" years later by someone who cannot see why it was needed.
    """
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    con = sqlcipher3.connect(":memory:")
    try:
        opts = [r[0] for r in con.execute("PRAGMA compile_options")]
    finally:
        con.close()
    temp = [o for o in opts if o.startswith("TEMP_STORE=")]
    assert temp == ["TEMP_STORE=2"], (
        f"expected the bundled build to default temp storage to memory, got {temp or opts[:5]}"
    )


# --------------------------------------------------------------------------- #
#  the window is denominated in BYTES, not rows
# --------------------------------------------------------------------------- #
def test_a_window_is_sized_by_bytes_so_bigger_rows_get_fewer_of_them(tmp_path) -> None:
    """THE unit question, and the first cut of this got it wrong.

    A fixed row count bounds rows; the cost is bytes. Measured on the shipped
    engine, the SAME 20,000 rows cost 178 MB at a 2 KB body and 947 MB at a
    32 KB one -- so a row-count window means something different on every
    corpus, and on the 2026-08-05 field artifact (~22 KB/article) the original
    20,000-id window would have carried ~800 MB, five times what its own
    comment claimed.

    Asserts the RELATIONSHIP rather than a number: a corpus of larger rows must
    get proportionally fewer ids per window. A constant would satisfy `>=`, so
    the comparison is strict -- the recorded clamped-monotonicity trap.
    """
    import sqlite3

    def measure(body_bytes: int) -> int:
        p = tmp_path / f"src{body_bytes}.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, content TEXT)")
        con.executemany(
            "INSERT INTO articles (id, content) VALUES (?, ?)",
            [(i, "x" * body_bytes) for i in range(1, 401)],
        )
        con.commit()
        con.close()
        host = sqlite3.connect(":memory:")
        try:
            host.execute("ATTACH DATABASE ? AS inc", (str(p),))
            return merge_mod._window_ids_for(host, "articles", 0, 400)
        finally:
            host.close()

    small, large = measure(100), measure(10_000)
    assert small > large, (
        f"a 100-byte-row corpus got {small} ids/window and a 10 KB-row corpus got "
        f"{large} -- the window is not tracking bytes"
    )


def test_the_window_is_clamped_at_both_ends(tmp_path) -> None:
    """Neither degenerate direction is acceptable.

    Rows so large that a window is one row would pay per-statement overhead on
    every row; rows so small that a window spans millions would coarsen stop
    latency and resume granularity back to where they started -- the other two
    things a window buys besides memory.
    """
    import sqlite3

    p = tmp_path / "tiny.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (id, v) VALUES (?, ?)", [(i, "x") for i in range(1, 51)])
    con.commit()
    con.close()

    host = sqlite3.connect(":memory:")
    try:
        host.execute("ATTACH DATABASE ? AS inc", (str(p),))
        n = merge_mod._window_ids_for(host, "t", 0, 50)
    finally:
        host.close()
    assert n == merge_mod._MERGE_WINDOW_MAX_IDS, (
        f"one-byte rows should hit the ceiling, got {n}"
    )
    assert merge_mod._MERGE_WINDOW_MIN_IDS >= 1


def test_row_size_is_measured_in_bytes_not_characters(tmp_path) -> None:
    """A non-ASCII corpus must not get a wider window than an ASCII one.

    ``LENGTH()`` on TEXT counts CHARACTERS. Most of this corpus is not Latin
    script, so counting characters would under-count every multi-byte row --
    widening the window exactly where rows are biggest, which is the inverse of
    what the sizing is for.
    """
    import sqlite3

    def avg(ch: str) -> float:
        p = tmp_path / f"s{ord(ch)}.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        con.executemany("INSERT INTO t (id, v) VALUES (?, ?)", [(i, ch * 100) for i in range(1, 31)])
        con.commit()
        con.close()
        host = sqlite3.connect(":memory:")
        try:
            host.execute("ATTACH DATABASE ? AS inc", (str(p),))
            return merge_mod._avg_row_bytes(host, "t", 0, 30)
        finally:
            host.close()

    ascii_bytes, cjk_bytes = avg("a"), avg("中")
    assert cjk_bytes > ascii_bytes * 2, (
        f"100 CJK characters measured {cjk_bytes:.0f} bytes against {ascii_bytes:.0f} for "
        "100 ASCII ones -- LENGTH is counting characters, not bytes"
    )


# --------------------------------------------------------------------------- #
#  windowing -- bounded work per statement
# --------------------------------------------------------------------------- #
def test_a_large_article_merge_runs_in_bounded_windows(tmp_path, monkeypatch) -> None:
    """THE regression. One statement must not carry a whole corpus.

    Mutation check: dropping ``src="articles"`` from ``_merge_articles`` makes
    this one window and fails.
    """
    _pin_window(monkeypatch, 25)
    seen = _spy_windows(monkeypatch)

    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=1)
    _corpus(staged, articles=200, first_hash=1000)
    merge_corpus(staged, working, _BATCH_META)

    windows = [p for t, p in seen if t == "articles"]
    assert len(windows) >= 8, f"200 articles at a 25-id window ran in {len(windows)} statements"
    for lo, hi in windows:
        assert hi - lo <= 25, f"window {lo}..{hi} exceeds the bound"


def test_windowing_loses_no_article(tmp_path, monkeypatch) -> None:
    """The negative-space twin. A bound that drops rows is worse than no bound.

    Bounded-and-wrong is the failure mode a memory test cannot see, so it is
    pinned separately from the bound itself.
    """
    _pin_window(monkeypatch, 7)
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=120, first_hash=500)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["articles"]["new"] == 120, counts["articles"]
    got = _hashes(working)
    assert len(got) == 123
    for i in range(500, 620):
        assert f"h{i:08d}" in got, f"window boundary dropped article {i}"


def test_a_source_smaller_than_one_window_runs_a_single_statement(tmp_path, monkeypatch) -> None:
    """Opting a small table in must be a no-op, not a behaviour change."""
    _pin_window(monkeypatch, 10_000)
    seen = _spy_windows(monkeypatch)

    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=1)
    _corpus(staged, articles=5, first_hash=90)
    merge_corpus(staged, working, _BATCH_META)

    assert len([1 for t, _ in seen if t == "articles"]) == 1


def test_a_windowed_insert_without_its_marker_is_refused() -> None:
    """Forgetting the marker would run the WHOLE-corpus statement once per window.

    Quadratic and silent -- the result would still be correct, so nothing else
    would ever notice. It has to be loud at the call, not a fallback.
    """
    with pytest.raises(ValueError, match="WINDOW"):
        merge_mod._insert_tracked(
            None, 1, "articles", "INSERT INTO articles SELECT * FROM inc.articles i",
            src="articles",
        )


def test_negative_source_ids_are_not_skipped(tmp_path, monkeypatch) -> None:
    """SQLite rowids may be negative when inserted explicitly.

    A window floor hardcoded at 0 would silently drop every such row -- and a
    dropped article is invisible: the report would just say fewer were new.
    """
    _pin_window(monkeypatch, 5)
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=1)
    _corpus(staged, articles=20, first_hash=700)

    engine = create_engine(f"sqlite:///{staged}", future=True)
    with engine.begin() as c:
        c.execute(text("UPDATE articles SET id = -50 WHERE hash = :h"), {"h": "h00000700"})
    engine.dispose()

    merge_corpus(staged, working, _BATCH_META)
    assert "h00000700" in _hashes(working), "the article at a negative id was skipped"


def test_windowing_changes_nothing_about_the_result(tmp_path, monkeypatch) -> None:
    """THE equivalence check: a windowed merge and a one-shot merge agree exactly.

    The other guards say the window is bounded and that no article is lost.
    Neither would notice a window that changed a source_id remap, wrote
    provenance for the wrong rows, or reordered an id map -- and "the numbers
    still add up" is exactly how a merge bug hides. So: merge the SAME staged
    corpus twice, once in many windows and once in one statement, and compare
    every table the merge writes, row for row.

    ``imported_at`` is excluded because the two runs happen at different
    instants; everything else must match, ``merged_rows`` included, since a
    provenance row pointing at the wrong id is a silent corruption of the only
    record of what an import brought in.
    """
    tables = ("articles", "sources", "keywords", "merged_rows")

    def snapshot(path: Path) -> dict[str, list]:
        engine = create_engine(f"sqlite:///{path}", future=True)
        try:
            out = {}
            with engine.connect() as c:
                for t in tables:
                    rows = c.execute(text(f"SELECT * FROM {t}")).all()  # noqa: S608
                    out[t] = sorted(tuple("" if v is None else str(v) for v in r) for r in rows)
            return out
        finally:
            engine.dispose()

    staged = tmp_path / "staged.db"
    _corpus(staged, articles=150, first_hash=2000)

    # ONE working copy, byte-copied -- not two built the same way. Two builds
    # differ in their own rows' created_at, which would show up as a diff that
    # has nothing to do with the merge. Copying makes any remaining difference
    # attributable, and keeps the timestamp columns IN the comparison rather
    # than excluding them, which could hide a real one.
    windowed, oneshot = tmp_path / "a.db", tmp_path / "b.db"
    _corpus(windowed, articles=4)
    shutil.copyfile(windowed, oneshot)

    _pin_window(monkeypatch, 11)          # ~14 windows over 150 articles
    counts_w, _ = merge_corpus(staged, windowed, _BATCH_META)
    monkeypatch.undo()
    _pin_window(monkeypatch, 10_000_000)  # one statement
    counts_1, _ = merge_corpus(staged, oneshot, _BATCH_META)

    assert counts_w == counts_1, "the two runs disagree about what they merged"
    a, b = snapshot(windowed), snapshot(oneshot)
    for t in tables:
        assert a[t] == b[t], f"{t} differs between a windowed and a one-shot merge"
    assert len(a["articles"]) == 154


# --------------------------------------------------------------------------- #
#  the status stamp that mid-merge commits made load-bearing
# --------------------------------------------------------------------------- #
def test_a_completed_merge_is_stamped_merged(tmp_path) -> None:
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=1)
    _corpus(staged, articles=3, first_hash=300)
    merge_corpus(staged, working, _BATCH_META)

    engine = create_engine(f"sqlite:///{working}", future=True)
    try:
        with engine.connect() as c:
            rows = c.execute(text("SELECT status FROM merge_batches")).all()
    finally:
        engine.dispose()
    assert [r[0] for r in rows] == [merge_mod._STATUS_MERGED]


def test_an_interrupted_merge_is_not_stamped_merged(tmp_path, monkeypatch) -> None:
    """The reason the stamp exists at all.

    Windowed steps COMMIT mid-merge, so a killed import can leave a half-merged
    working copy carrying a batch row. If that row said "merged", the
    already-merged skip would treat the artifact as done and strand every row
    the merge never reached -- a silent partial import, which is the exact
    shape of the dropped-column bugs this module has been bitten by twice.

    THE WINDOW MUST BE SMALL ENOUGH TO FORCE A MID-MERGE COMMIT. The first draft
    of this test used the production window over three articles, so the merge
    took the single-shot path, never committed, and the rollback wiped
    ``merge_batches`` -- leaving the assertion to range over an EMPTY list. It
    passed against the mutation it exists to catch. Hence both the small window
    and the non-empty assertion below: a guard that cannot see its own subject
    is worse than none.
    """
    _pin_window(monkeypatch, 10)
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=1)
    _corpus(staged, articles=60, first_hash=400)

    def boom(con, batch_id, results):  # noqa: ANN001
        raise RuntimeError("killed after the articles step committed")

    monkeypatch.setattr(merge_mod, "_merge_keywords", boom)
    with pytest.raises(RuntimeError):
        merge_corpus(staged, working, _BATCH_META)

    engine = create_engine(f"sqlite:///{working}", future=True)
    try:
        with engine.connect() as c:
            rows = c.execute(text("SELECT status FROM merge_batches")).all()
    finally:
        engine.dispose()
    assert rows, (
        "no batch row survived, so this asserts nothing -- the merge did not "
        "commit mid-way and the whole point of the stamp is untested"
    )
    assert all(r[0] != merge_mod._STATUS_MERGED for r in rows), (
        f"a half-merged working copy is stamped as complete: {rows}"
    )

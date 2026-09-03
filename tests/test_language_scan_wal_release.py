"""
S4.2 (2026-09-02 crash analysis): the language-signature scan releases the WAL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``reconcile_keyword_language`` ran one ``yield_per(20000)`` scan over every
mention (~9.3 M in the field) from the background re-index job. A single streamed
scan holds one WAL read-mark for its whole duration, and that is what starves
``PRAGMA wal_checkpoint`` -- so the WAL grew for as long as the job ran.

The registry's empirical finding is the load-bearing one and is re-asserted here
rather than trusted: a bare ``commit()`` with the cursor still open does NOT
release the read-mark. Only closing the cursor does. So the guard is written
against the CHECKPOINT, not against the number of statements issued -- a fix that
committed diligently and never closed would satisfy any statement-count
assertion while changing nothing about the WAL.

The result half matters as much: the scan now sees a moving corpus rather than one
snapshot, so the signature it computes must still be the same one.
"""

from __future__ import annotations


from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import sessionmaker

from src.analytics.store import reconcile_keyword_language
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _corpus(tmp_path, *, articles=60, langs=("en", "fr")):
    eng = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    with eng.begin() as c:
        c.execute(text("PRAGMA journal_mode=WAL"))
    s.add(Source(name="s", domain="s.example"))
    s.add(Keyword(term="k", normalized_term="k", language=None))
    s.flush()
    rows = []
    for i in range(1, articles + 1):
        s.add(Article(
            title=f"a{i}", url=f"https://s.example/{i}",
            canonical_url=f"https://s.example/{i}", source_id=1,
            hash=f"h{i}", content=f"body {i}",
            language=langs[0] if i % 5 else langs[1],
        ))
    s.flush()
    for i in range(1, articles + 1):
        rows.append({"keyword_id": 1, "article_id": i, "count": 1})
    s.execute(insert(KeywordMention), rows)
    s.commit()
    return eng, s


def test_the_scan_closes_its_cursor_between_chunks(tmp_path, monkeypatch):
    """Asserted against the CHECKPOINT, because that is the only thing that can
    tell a closed cursor from a committed-but-open one."""
    from src.analytics import store
    from src.scheduler.hygiene import checkpoint_wal

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_WAL_CHECKPOINT_BUSY_MS", raising=False)
    monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", 5)  # force many chunks
    eng, s = _corpus(tmp_path, articles=60)

    busy_seen: list[int] = []
    real_commit = s.commit
    calls = {"n": 0}

    def _spy() -> None:
        # BETWEEN chunks: the loop closes its cursor and then commits, so this is
        # the first moment the read-mark can be free. Hooking `execute` instead
        # (the first version of this test) fires while the Result is still open,
        # which is busy=1 under any implementation and proves nothing.
        real_commit()
        calls["n"] += 1
        if calls["n"] == 3:
            rec = checkpoint_wal(engine=eng, force=True)
            if rec is not None and rec.get("busy") is not None:
                busy_seen.append(int(rec["busy"]))

    monkeypatch.setattr(s, "commit", _spy)
    reconcile_keyword_language(s)
    s.close()

    assert busy_seen, "no checkpoint was attempted during the scan — nothing was measured"
    assert busy_seen[-1] == 0, (
        "a checkpoint attempted mid-scan still found the WAL pinned, so the scan is "
        "holding its read-mark across chunks"
    )


def test_the_signature_it_computes_is_unchanged_by_the_chunking(tmp_path, monkeypatch):
    """The result half. Chunking changes what the scan SEES (many snapshots rather
    than one), so the vote it lands on must be asserted, not assumed."""
    from src.analytics import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    eng, s = _corpus(tmp_path, articles=60)  # 48 en / 12 fr -> a clear en majority
    monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", 7)
    out = reconcile_keyword_language(s)
    lang = s.execute(text("SELECT language FROM keywords WHERE id=1")).scalar()
    s.close()
    assert out["relanguaged"] == 1
    assert out["null_to_lang"] == 1
    assert lang == "en", f"the majority vote landed on {lang!r}"


def _sparse_corpus(root):
    """MANY keywords with FEW mentions each, on purpose.

    The first version of the agreement test used one keyword with a clear
    majority, and a mutation that advanced the cursor one row too far (skipping a
    row per chunk) passed it: with a single keyword and a lopsided vote, losing
    rows changes no field of the output. Here every keyword's presence in the
    tally depends on its own handful of rows, so ANY skipped row moves
    `keywords_with_signature`.
    """
    root.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{root / 'c.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    with eng.begin() as c:
        c.execute(text("PRAGMA journal_mode=WAL"))
    s.add(Source(name="s", domain="s.example"))
    # ONE mention per keyword: a keyword's presence in the tally then depends on
    # exactly one row, which is what makes a single skipped row visible. With
    # three each, a cursor that skips one row per chunk still left every
    # keyword above the floor and the mutation passed.
    n_kw, per_kw = 24, 1
    for i in range(1, n_kw + 1):
        s.add(Keyword(term=f"k{i}", normalized_term=f"k{i}", language=None))
    s.flush()
    aid = 0
    rows = []
    for k in range(1, n_kw + 1):
        for _ in range(per_kw):
            aid += 1
            s.add(Article(
                title=f"a{aid}", url=f"https://s.example/{aid}",
                canonical_url=f"https://s.example/{aid}", source_id=1,
                hash=f"h{aid}", content=f"body {aid}", language="en",
            ))
            rows.append({"keyword_id": k, "article_id": aid, "count": 1})
    s.flush()
    s.execute(insert(KeywordMention), rows)
    s.commit()
    return eng, s, n_kw


def test_one_chunk_and_many_chunks_agree(tmp_path, monkeypatch):
    """Anti-vacuity: the chunk size must not change the answer, which is the
    property that makes the loop a refactor rather than a behaviour change."""
    from src.analytics import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def _run(chunk):
        eng, s, n_kw = _sparse_corpus(tmp_path / f"c{chunk}")
        monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", chunk)
        out = reconcile_keyword_language(s, min_articles=1)
        s.close()
        return out, n_kw

    big, n_kw = _run(1000)   # one chunk, i.e. the old single scan
    small, _ = _run(5)       # many chunks
    assert big == small, f"the chunk size changed the tally: {big} vs {small}"
    # And the tally is one a skipped row would move: every keyword is in it.
    assert big["keywords_with_signature"] == n_kw, (
        f"the scan saw {big['keywords_with_signature']} of {n_kw} keywords, so the "
        "fixture cannot detect a row the keyset skipped"
    )


def test_the_scan_is_savepoint_aware(tmp_path, monkeypatch):
    """A store helper that commits internally breaks a caller-owned savepoint --
    the recorded lesson. Neither caller nests this today; the guard is what keeps
    that true if one starts to."""
    from src.analytics import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    eng, s = _corpus(tmp_path, articles=30)
    monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", 4)
    with s.begin_nested():
        out = reconcile_keyword_language(s)
        # The savepoint must still be usable: a commit would have closed it.
        assert s.in_nested_transaction(), "the helper committed out from under its caller"
    s.commit()
    s.close()
    assert out["keywords_with_signature"] == 1


def test_read_snapshot_is_deliberately_left_holding_one_snapshot():
    """The brief lists read_snapshot as a reader to bound. It is not one: its whole
    purpose is that an export's two keyword_mentions passes see the SAME view, and
    the module says so. Bounding it would break a documented correctness property,
    so the decision is recorded here rather than left to the next reader."""
    import inspect

    from src.database import read_snapshot

    src = inspect.getsource(read_snapshot)
    assert "BEGIN" in src
    assert "SAME consistent view" in src or "same consistent view" in src.lower(), (
        "read_snapshot no longer documents why it holds one snapshot — if that "
        "requirement is gone, this reader becomes boundable and this test is the "
        "place to decide that deliberately"
    )

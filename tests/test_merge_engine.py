"""
Direct unit tests for the additive backup-merge engine (audit PR F).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The merge engine is otherwise exercised only through the subprocess torture
harness (tests/test_db_reliability_torture.py). These tests call
``src.backup.merge.merge_corpus`` DIRECTLY on tiny plaintext SQLite corpora so the
three load-bearing behaviours are pinned in isolation and fast:

  * FK remap — an incoming article's ``source_id`` is rewritten to the LOCAL
    source matched by domain (never the incoming row's id);
  * bit-level dedup — same hash AND same content bytes = duplicate (skipped);
  * conflict — same hash, different content = conflict: LOCAL kept, BOTH reported.

Restore is additive-only: nothing in the working copy is ever overwritten.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, Base, Source

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.0.9",
    "alembic_rev": "head",
    "manifest": None,
}


def _build_corpus(path: Path, sources: list[dict], articles: list[dict]) -> dict:
    """Create a plaintext SQLite corpus with the full schema; return {natural_key: id}.

    ``sources`` rows are dicts with at least ``domain`` (+ optional ``name``);
    ``articles`` rows reference a source by ``domain`` and carry hash/content/etc.
    """
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    ids: dict = {}
    with sessionmaker(bind=engine, future=True)() as s:
        dom_to_id: dict[str, int] = {}
        for spec in sources:
            src = Source(name=spec.get("name", spec["domain"]), domain=spec["domain"])
            s.add(src)
            s.flush()
            dom_to_id[spec["domain"]] = src.id
            ids[f"source:{spec['domain']}"] = src.id
        for spec in articles:
            a = Article(
                url=spec["url"],
                canonical_url=spec.get("canonical_url", spec["url"]),
                source_id=dom_to_id[spec["source_domain"]],
                title=spec.get("title", spec["hash"]),
                content=spec["content"],
                hash=spec["hash"],
                language="en",
                created_at=now,
            )
            s.add(a)
            s.flush()
            ids[f"article:{spec['hash']}"] = a.id
        s.commit()
    engine.dispose()
    return ids


def _article_rows(path: Path) -> list[dict]:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            rows = c.execute(
                text("SELECT hash, content, title, source_id FROM articles ORDER BY hash")
            ).all()
        return [dict(hash=r[0], content=r[1], title=r[2], source_id=r[3]) for r in rows]
    finally:
        engine.dispose()


def test_fk_remap_source_id_by_domain(tmp_path):
    """An incoming article's source_id is remapped to the LOCAL source (matched on
    domain), not carried over as the incoming row's id."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    local_ids = _build_corpus(working, [{"domain": "wire.example", "name": "Wire A"}], [])
    # In the staged corpus, force the wire.example source to a DIFFERENT id (2) by
    # inserting a filler source first, then attach the incoming article to it.
    _build_corpus(
        staged,
        [{"domain": "filler.example"}, {"domain": "wire.example", "name": "Wire B"}],
        [{"url": "https://wire.example/x", "source_domain": "wire.example",
          "hash": "hWIRE", "content": "incoming body"}],
    )

    counts, batch_id = merge_corpus(staged, working, _BATCH_META)

    assert counts["sources"]["new"] == 1  # filler.example is new
    assert counts["sources"]["duplicate"] == 1  # wire.example already present
    assert counts["sources"]["conflict"] == 1  # same domain, different name -> reported
    assert counts["articles"]["new"] == 1
    # The merged article points at the LOCAL wire.example source id, not the
    # incoming id (which was 2 in the staged DB).
    merged = [a for a in _article_rows(working) if a["hash"] == "hWIRE"]
    assert len(merged) == 1
    assert merged[0]["source_id"] == local_ids["source:wire.example"], (
        "FK remap failed: article kept the incoming source_id instead of the local one"
    )


def test_bit_level_dedup_identical_article(tmp_path):
    """Same hash AND identical content bytes = duplicate (skipped, not re-inserted)."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    art = {"url": "https://s.example/a", "source_domain": "s.example",
           "hash": "hSAME", "content": "identical body bytes"}
    _build_corpus(working, [{"domain": "s.example"}], [art])
    _build_corpus(staged, [{"domain": "s.example"}], [dict(art)])

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["articles"]["duplicate"] == 1
    assert counts["articles"]["new"] == 0
    assert counts["articles"]["conflict"] == 0
    assert len(_article_rows(working)) == 1  # nothing added


def test_conflict_same_hash_diff_content_keeps_local_reports_both(tmp_path):
    """Same hash, different content = conflict: the LOCAL row is kept and BOTH
    values are surfaced (never averaged, never overwritten)."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_corpus(
        working, [{"domain": "s.example"}],
        [{"url": "https://s.example/a", "source_domain": "s.example", "hash": "hX",
          "title": "Local", "content": "LOCAL CONTENT"}],
    )
    _build_corpus(
        staged, [{"domain": "s.example"}],
        [{"url": "https://s.example/a", "source_domain": "s.example", "hash": "hX",
          "title": "Incoming", "content": "INCOMING CONTENT"}],
    )

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["articles"]["conflict"] == 1
    assert counts["articles"]["new"] == 0
    assert counts["articles"]["duplicate"] == 0
    # Both values reported; local kept.
    conflicts = counts["articles"]["conflicts"]
    assert conflicts and conflicts[0]["hash"] == "hX"
    assert conflicts[0]["incoming_title"] == "Incoming"
    assert conflicts[0]["kept"] == "local"
    # The working copy still holds the LOCAL content (never overwritten).
    rows = _article_rows(working)
    assert len(rows) == 1 and rows[0]["content"] == "LOCAL CONTENT"


def test_new_rows_recorded_in_merged_rows_provenance(tmp_path):
    """Every inserted row is tracked in merged_rows under its batch_id (provenance)."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_corpus(working, [{"domain": "a.example"}], [])
    _build_corpus(
        staged, [{"domain": "a.example"}],
        [{"url": "https://a.example/1", "source_domain": "a.example",
          "hash": "hNEW", "content": "new body"}],
    )

    counts, batch_id = merge_corpus(staged, working, _BATCH_META)
    assert counts["articles"]["new"] == 1

    engine = create_engine(f"sqlite:///{working}", future=True)
    try:
        with engine.connect() as c:
            tracked = c.execute(
                text("SELECT COUNT(*) FROM merged_rows WHERE batch_id = :b AND table_name = 'articles'"),
                {"b": batch_id},
            ).scalar()
    finally:
        engine.dispose()
    assert tracked == 1, "the merged article must be recorded in merged_rows provenance"

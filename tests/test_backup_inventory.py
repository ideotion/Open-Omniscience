"""
Tests for the unified-backup inventory (what's available + sizes).

In-memory SQLite -> runs in CI. Blob totals are monkeypatched (the real ones read
the live download dirs).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup import inventory as inv
from src.database.models import Article, ArticleMentionedDate, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db):
    db.add(Source(name="S", domain="s.test"))
    db.flush()
    for i in range(2):
        a = Article(
            url=f"https://s.test/{i}",
            canonical_url=f"https://s.test/{i}",
            source_id=1,
            title="T",
            content="x",
            hash=f"h{i}",
            language="en",
        )
        db.add(a)
        db.flush()
        db.add(ArticleMentionedDate(article_id=a.id, mentioned_on=datetime.now(UTC).date()))
    db.commit()


def test_corpus_breakdown_counts_include_dates(db, monkeypatch):
    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 12345)
    _seed(db)
    out = inv.backup_inventory(db)
    assert out["corpus"]["always"] is True
    assert out["corpus"]["bytes"] == 12345
    b = out["corpus"]["breakdown"]
    assert b["articles"] == 2
    assert b["sources"] == 1
    assert b["dates"] == 2  # "dates, amongst else" are visibly inside the corpus


def test_blob_categories_are_mapped_and_default_zero(db, monkeypatch):
    monkeypatch.setattr(
        inv,
        "_blob_totals",
        lambda: {"models": {"count": 3, "bytes": 900}, "osm_regions": {"count": 1, "bytes": 500}},
    )
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    assert (out["models"]["count"], out["models"]["bytes"]) == (3, 900)
    assert (out["maps"]["count"], out["maps"]["bytes"]) == (1, 500)  # osm_regions -> maps
    assert (out["wiki"]["count"], out["wiki"]["bytes"]) == (0, 0)  # absent -> zero


def test_the_models_member_sizes_BOTH_stores_because_one_tick_exports_both(db, monkeypatch):
    """The size shown before an export must be the size the export would write.

    One "LLM models" tick has always exported the Ollama store AND the Hugging Face
    cache, but the figure beside it counted only the first — so a 40 GB HF cache was
    invisible at exactly the moment Q219 = a exists to make it visible.
    """
    monkeypatch.setattr(
        inv,
        "_blob_totals",
        lambda: {
            "models": {"count": 3, "bytes": 900},
            "hf_models": {"count": 1, "bytes": 50_000},
        },
    )
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    assert out["models"]["bytes"] == 50_900, "the HF cache must be inside the number"
    assert out["models"]["count"] == 4
    # Both stores stay NAMED, so "which of these is the big one" is still answerable.
    assert out["models"]["breakdown"]["hf_models"]["bytes"] == 50_000
    assert out["models"]["breakdown"]["models"]["bytes"] == 900


def test_every_member_names_the_categories_its_tick_exports(db, monkeypatch):
    """Q219's hook: ONE list drives the rows, their sizes and what a tick writes.

    The categories a member declares are the ones its size sums over AND the ones the
    export sends — a member whose two are out of step is exactly how the understated
    models figure happened, so the shape is pinned rather than the spelling.
    """
    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    keys = [m["key"] for m in out["members"]]
    assert keys == ["models", "maps", "wiki", "lanes"], keys
    for m in out["members"]:
        assert m["label"], "a member needs an English label for the locale files to key on"
        # HOW a member is written is now a VALUE, not an inference from the shape of
        # its categories. The folder backup copies files byte for byte, which is right
        # for a finished download and wrong for a live encrypted database — so the
        # lane member declares ``snapshot`` and carries no folder categories, and a
        # caller reads the field instead of guessing from an empty list.
        assert m["via"] in ("folder", "snapshot"), m
        if m["via"] == "folder":
            assert m["categories"], f"{m['key']} exports nothing"
            assert set(m["breakdown"]) == set(m["categories"]), (
                f"{m['key']}'s size is summed over a different set than it exports"
            )
        else:
            assert m["categories"] == [], f"{m['key']} is snapshotted and names folder categories"


def test_a_member_that_cannot_be_exported_yet_says_SO_and_says_WHY(db, monkeypatch):
    """A disabled row with no explanation reads as a bug.

    The lane member exists so its size is visible; its export format is S04-04's, and
    until then the honest state is "present, not covered here" with the reason beside
    it — never a tick that quietly writes nothing.
    """
    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    lanes = out["lanes"]
    assert lanes["exportable"] is False
    assert lanes["not_exportable_reason"], "a member is disabled with no reason given"
    for m in out["members"]:
        if not m.get("exportable", True):
            assert m.get("not_exportable_reason"), f"{m['key']} is disabled silently"


def test_an_ABSENT_lane_is_left_out_rather_than_reported_as_zero_bytes(db, monkeypatch):
    """``None`` and ``0`` are different facts about a store.

    A lane the operator has never opened must not appear in a backup dialog as an
    empty one — that is a row about a thing that does not exist.
    """
    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    out = inv.backup_inventory(db)
    assert out["lanes"]["breakdown"] == {}, out["lanes"]
    assert out["lanes"]["count"] == 0
    assert out["lanes"]["bytes"] == 0


def test_no_session_still_returns_blob_inventory(monkeypatch):
    monkeypatch.setattr(inv, "_blob_totals", lambda: {"wiki_dumps": {"count": 2, "bytes": 7}})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 42)
    out = inv.backup_inventory(None)
    assert (out["wiki"]["count"], out["wiki"]["bytes"]) == (2, 7)
    assert out["corpus"]["bytes"] == 42
    assert "breakdown" not in out["corpus"]  # no session -> no counts, no crash


def test_a_PRESENT_lane_reports_the_size_of_the_FILE_not_a_placeholder(db, monkeypatch, tmp_path):
    """The point of the member: an operator sees how much lane data they hold.

    Read from the lane store's own size reader, which counts the WAL and SHM sidecars
    alongside the main file — because those bytes are on the operator's disk and a
    figure that omitted them would understate the stick they need.
    """
    from src.versioned import store as lane_store

    monkeypatch.setattr(inv, "_blob_totals", lambda: {})
    monkeypatch.setattr(inv, "_db_bytes", lambda: 0)
    lane_store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        lane_store.create_lane("wiki")
        out = inv.backup_inventory(db)
        lanes = out["lanes"]
        assert set(lanes["breakdown"]) == {"wiki"}, lanes["breakdown"]
        assert lanes["count"] == 1
        assert lanes["bytes"] == lane_store.lane_file_bytes("wiki")
        assert lanes["bytes"] > 0
        # ...and the other two lanes stay absent rather than appearing at zero.
        assert "law" not in lanes["breakdown"]
    finally:
        lane_store.dispose_all()

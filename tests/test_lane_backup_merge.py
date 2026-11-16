"""Living sources in a backup: the wiki lane's additive merge (R729).

Two "machines" are two data directories. Machine B's lane is snapshotted the way the
export does it (``connect.snapshot_preserving``) and merged into machine A's live lane.
Every rule of R729 that this build implements is pinned here, plus the two properties the
ruling names for every store: a re-import changes nothing, and a failure leaves the lane
as it was.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.backup import lane_merge
from src.versioned import store
from src.versioned.models import (
    VersionedBaseline,
    VersionedChange,
    VersionedCursor,
    VersionedEntity,
    VersionedEntityFact,
    VersionedRevision,
)
from src.wiki.lane_models import WikiWalkPage, WikiWarmPage

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _at(h: int) -> datetime:
    return T0 + timedelta(hours=h)


@pytest.fixture
def machines(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    def use(which: Path) -> None:
        monkeypatch.setenv("OO_DATA_DIR", str(which))
        store.create_lane("wiki")

    yield a, b, use
    store.dispose_all()


def _entity(s, ext: str, **kw) -> VersionedEntity:
    e = VersionedEntity(external_id=ext, first_seen_at=_at(0), **kw)
    s.add(e)
    s.flush()
    return e


def _rev(s, e, ref: str, text: str, h: int) -> VersionedRevision:
    r = VersionedRevision(
        entity_id=e.id, revision_ref=ref, observed_at=_at(h), content_hash=f"h{ref}",
        content=text, byte_size=len(text), diff_method="unified", article_id=999,
    )
    s.add(r)
    s.flush()
    return r


def _seed_b(b, use, tmp_path) -> Path:
    use(b)
    with store.lane_session("wiki") as s:
        shared = _entity(s, "en:1", title=None, watching=True)
        s.add(VersionedBaseline(entity_id=shared.id, revision_ref="b-base", content_hash="x", content="B base", byte_size=6))
        r = _rev(s, shared, "r2", "two", 2)
        s.add(VersionedChange(entity_id=shared.id, external_id="en:1", change_ref="c2", feed="en", change_kind="edit", ingested_revision_id=r.id))
        s.add(VersionedEntityFact(entity_id=shared.id, name="length", value_json="200", observed_at=_at(5)))
        s.add(VersionedEntityFact(entity_id=shared.id, name="qid", value_json='"Q1"', observed_at=_at(1)))
        only_b = _entity(s, "en:2", title="Only B", qid="Q2", watching=True, last_checked_at=_at(3))
        _rev(s, only_b, "r9", "nine", 3)
        _entity(s, "en:3", title="Only B unfollowed", watching=False)
        s.add(VersionedCursor(feed="en", token="B-token"))
        s.add(WikiWalkPage(edition="en", page_id=10, title="New title", walked_at=_at(9), pass_no=7))
        s.add(WikiWalkPage(edition="en", page_id=11, title="Only B walk", walked_at=_at(1), pass_no=7))
        s.add(WikiWarmPage(edition="en", page_id=20, wanted_at=_at(0), wanted_revid=40, latest_revid=40, latest_text="w40", latest_bytes=3, previous_revid=30, previous_text="w30", previous_bytes=3))
        s.commit()
    snap = tmp_path / "snap" / "wiki.db"
    entry = lane_merge.snapshot_lane_for_backup("wiki", snap)
    assert entry["name"] == "lanes/wiki.db"
    store.dispose_lane("wiki")
    return snap


def _seed_a(a, use) -> None:
    use(a)
    with store.lane_session("wiki") as s:
        shared = _entity(s, "en:1", title="Local title", watching=False, pinned=True)
        s.add(VersionedBaseline(entity_id=shared.id, revision_ref="a-base", content_hash="y", content="A base", byte_size=6))
        _rev(s, shared, "r2", "two (local copy)", 2)
        s.add(VersionedEntityFact(entity_id=shared.id, name="length", value_json="100", observed_at=_at(4)))
        s.add(VersionedEntityFact(entity_id=shared.id, name="qid", value_json='"Q1-local"', observed_at=_at(1)))
        s.add(VersionedCursor(feed="en", token="A-token"))
        s.add(WikiWalkPage(edition="en", page_id=10, title="Old title", walked_at=_at(2), pass_no=3))
        s.add(WikiWarmPage(edition="en", page_id=20, wanted_at=_at(0), wanted_revid=35, latest_revid=35, latest_text="w35", latest_bytes=3, previous_revid=10, previous_text="w10", previous_bytes=3))
        s.commit()


def _snapshot_state() -> dict:
    with store.lane_session("wiki") as s:
        out = {}
        for model in (VersionedEntity, VersionedRevision, VersionedBaseline, VersionedChange, VersionedEntityFact, WikiWalkPage, WikiWarmPage, VersionedCursor):
            out[model.__tablename__] = s.execute(select(func.count()).select_from(model)).scalar_one()
        out["warm"] = [(w.latest_revid, w.previous_revid, w.due_since) for w in s.execute(select(WikiWarmPage)).scalars()]
        out["facts"] = sorted((f.name, f.value_json) for f in s.execute(select(VersionedEntityFact)).scalars())
        return out


def test_merge_follows_r729_and_is_idempotent(machines, tmp_path):
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)

    rep = lane_merge.merge_staged_lanes(snap.parent.parent, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    assert rep["lanes"] == [] or rep["lanes"][0]["state"] != "merged"  # wrong layout: name is lanes/wiki.db
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "wiki.db")

    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    (lane,) = rep["lanes"]
    assert lane["state"] == "merged", lane
    # L1: en:2 is new and followed, en:3 new and not followed.
    assert lane["newly_followed"] == 1 and rep["newly_followed"] == 1
    assert lane["warm_texts_dropped"] == 2  # w30 and w10 lose to w40 and w35 (Q710)

    with store.lane_session("wiki") as s:
        ents = {e.external_id: e for e in s.execute(select(VersionedEntity)).scalars()}
        assert set(ents) == {"en:1", "en:2", "en:3"}
        # Local flags and values stay; nothing here is replaced.
        assert ents["en:1"].watching is False and ents["en:1"].pinned is True
        assert ents["en:1"].title == "Local title"
        # A page this machine never asked about says so.
        assert ents["en:2"].last_checked_at is None and ents["en:2"].qid == "Q2"
        revs = {(r.entity_id, r.revision_ref): r for r in s.execute(select(VersionedRevision)).scalars()}
        shared_id = ents["en:1"].id
        assert revs[(shared_id, "r2")].content == "two (local copy)"  # never updated
        assert (ents["en:2"].id, "r9") in revs and revs[(ents["en:2"].id, "r9")].article_id is None
        # L3: B's different baseline survives as a revision.
        assert revs[(shared_id, "b-base")].content == "B base"
        base = s.execute(select(VersionedBaseline).where(VersionedBaseline.entity_id == shared_id)).scalar_one()
        assert base.revision_ref == "a-base"
        ch = s.execute(select(VersionedChange)).scalar_one()
        assert ch.entity_id == shared_id and ch.ingested_revision_id == revs[(shared_id, "r2")].id
        facts = {f.name: f.value_json for f in s.execute(select(VersionedEntityFact)).scalars()}
        assert facts["length"] == "200"  # L2: later reading wins
        assert facts["qid"] == '"Q1-local"'  # L2: equal timestamp keeps the local one
        # L5: the cursor stays this machine's own.
        assert [c.token for c in s.execute(select(VersionedCursor)).scalars()] == ["A-token"]
        walk = {w.page_id: w for w in s.execute(select(WikiWalkPage)).scalars()}
        assert walk[10].title == "New title" and walk[10].pass_no == 3
        assert walk[11].pass_no == 0
        warm = s.execute(select(WikiWarmPage)).scalar_one()
        assert (warm.latest_revid, warm.previous_revid) == (40, 35)
        assert (warm.latest_text, warm.previous_text) == ("w40", "w35")
        assert warm.wanted_revid == 40 and warm.due_since is None

    before = _snapshot_state()
    again = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    assert again["lanes"][0]["state"] == "merged"
    assert again["newly_followed"] == 0
    assert again["lanes"][0]["warm_texts_dropped"] == 0  # nothing changed, so nothing was dropped
    assert all(v.get("inserted", 0) == 0 and v.get("updated", 0) == 0 and v.get("filled", 0) == 0 and v.get("kept_as_revision", 0) == 0
               for v in again["lanes"][0]["tables"].values())
    assert _snapshot_state() == before


def test_a_failure_rolls_the_lane_back(machines, tmp_path, monkeypatch):
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _snapshot_state()

    def boom(conn, out):
        raise RuntimeError("injected")

    monkeypatch.setitem(lane_merge._STEPS, "wiki", (lane_merge._merge_shared, lane_merge._merge_walk, boom))
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "wiki.db")
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    assert rep["lanes"][0]["state"] == "failed"
    assert "injected" not in rep["lanes"][0]["reason"]  # the class only, never the words
    assert _snapshot_state() == before


def test_members_are_chosen_by_kind_never_by_name(tmp_path):
    assert lane_merge.valid_member({"name": "lanes/wiki.db", "kind": "wiki"}) == "wiki"
    assert lane_merge.valid_member({"name": "../corpus.db", "kind": "wiki"}) is None
    assert lane_merge.valid_member({"name": "lanes/x.db", "kind": "x"}) is None
    rep = lane_merge.merge_staged_lanes(tmp_path, [{"name": "lanes/osm.db", "kind": "osm"}, "junk"], [])
    states = [x["state"] for x in rep["lanes"]]
    assert states == ["not-merged", "ignored"]


def test_an_encrypted_member_needs_its_key(machines, tmp_path, monkeypatch):
    a, b, use = machines
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", "machine pass", raising=False)
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "wiki.db")
    from src.database.connect import is_encrypted_file

    assert is_encrypted_file(staging / "lanes" / "wiki.db") is True
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], ["wrong one"])
    assert rep["lanes"][0]["state"] == "failed"
    assert "wrong one" not in str(rep)
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], ["wrong one", "machine pass"])
    assert rep["lanes"][0]["state"] == "merged", rep
    assert rep["newly_followed"] == 1


def test_round_trip_through_the_volume_set(machines, tmp_path):
    """Export with ``include_lanes`` -> read the set back -> merge: the lane rides as an
    ordinary encrypted member, the manifest names it, and the import merges it. A set
    written without it carries no ``lane_members`` key at all (its manifest is unchanged)."""
    import sqlite3

    from src.backup.stream_backup import (
        CorpusSource,
        _no_freeze,
        read_stream_backup,
        write_stream_backup,
    )
    from src.backup.volumes import load_manifest

    a, b, use = machines
    use(b)
    with store.lane_session("wiki") as s:
        e = _entity(s, "en:42", title="Carried", watching=True)
        _rev(s, e, "r1", "text one", 1)
        s.commit()
    corpus = tmp_path / "corpus.db"
    con = sqlite3.connect(corpus)
    con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT)")
    con.commit()
    con.close()
    src = CorpusSource(path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze)

    plain = tmp_path / "plain"
    write_stream_backup(plain, "pw", corpus_source=src, side_members=[], volume_size=65536)
    assert "lane_members" not in load_manifest(plain)

    dest = tmp_path / "dest"
    write_stream_backup(dest, "pw", corpus_source=src, side_members=[], volume_size=65536, include_lanes=True)
    m = load_manifest(dest)
    assert [x["name"] for x in m["lane_members"]] == ["lanes/wiki.db"]
    assert any(mm["name"] == "lanes/wiki.db" and mm["role"] == "lane" for mm in m["members"])

    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st", include_merge_budget=False)
    assert staged.hash_failures == []
    assert [x["kind"] for x in staged.lane_members] == ["wiki"]
    store.dispose_lane("wiki")
    use(a)
    rep = lane_merge.merge_staged_lanes(staged.staging_dir, staged.lane_members, ["pw"])
    assert rep["lanes"][0]["state"] == "merged", rep
    with store.lane_session("wiki") as s:
        assert s.execute(select(VersionedEntity.title)).scalar_one() == "Carried"
        assert s.execute(select(VersionedRevision.content)).scalar_one() == "text one"


def test_the_import_report_says_what_the_living_sources_added(tmp_path, monkeypatch):
    """R729 L1: the newly followed pages are stated where the outcome is read -- in the
    report's markdown and in the listing the "Last import" line is drawn from."""
    from src.backup import import_reports

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    living = {
        "lanes": [
            {"kind": "wiki", "state": "merged", "seconds": 0.4, "newly_followed": 3, "warm_texts_dropped": 2,
             "tables": {"versioned_entities": {"inserted": 4, "filled": 1}}},
            {"kind": "osm", "state": "not-merged", "reason": "this build cannot merge this lane yet; the backup still carries it"},
        ],
        "newly_followed": 3,
        "method": lane_merge.METHOD,
    }
    path = import_reports.persist_import_report("restore", {"outcome": "committed"})
    import_reports.annotate_import_report(path, {"living_sources": living})
    md = import_reports.render_import_report_markdown({"outcome": "committed", "living_sources": living})
    assert "## Living sources" in md and "3 pages are newly followed" in md
    assert "Maps (OpenStreetMap): not merged" in md and "2 older page texts were not kept" in md
    (row,) = import_reports.list_import_reports()
    assert row["newly_followed"] == 3
    assert "lanes_owed" not in row  # a not-merged lane of another kind is not owed

    held = lane_merge.deferred_report([{"name": "lanes/wiki.db", "kind": "wiki"}])
    path2 = import_reports.persist_import_report("restore", {"outcome": "committed"})
    import_reports.annotate_import_report(path2, {"living_sources": held})
    rows = {r["filename"]: r for r in import_reports.list_import_reports()}
    assert rows[path2.name]["lanes_owed"] == 1
    md = import_reports.render_import_report_markdown({"outcome": "committed", "living_sources": held})
    assert "importing this backup again merges them" in md and "when the group is saved" in md


def test_the_export_request_records_the_living_sources_and_a_resume_keeps_them(tmp_path):
    from src.backup.export_folder import (
        read_export_request,
        update_export_phase,
        write_export_request,
    )

    d = tmp_path / "OpenOmniscience_Backup_x"
    d.mkdir()
    write_export_request(d, corpus=True, categories=[], phase="volumes", lanes=True)
    assert read_export_request(d)["lanes"] is True
    update_export_phase(d, "done")
    assert read_export_request(d)["lanes"] is True
    write_export_request(d, corpus=False, categories=["wiki_dumps"], phase="folder", lanes=True)
    assert read_export_request(d)["lanes"] is False  # never without the corpus artifact


def test_a_hostile_member_is_refused_before_anything_is_read(machines, tmp_path):
    """Security read 1 on PR 2036: the member is untrusted input inside a keyed connection.

    A non-integer page size, a member without the lane stamp, a stamp naming another kind,
    and a view or a virtual table under a name the merge reads are each refused with a fixed
    sentence that never echoes what the member said, and the lane is left as it was.
    """
    import sqlite3

    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _snapshot_state()
    entry = {"name": "lanes/wiki.db", "kind": "wiki"}

    for bad in ("x", [1], 4096.0, True):
        rep = lane_merge.merge_staged_lanes(tmp_path, [dict(entry, sqlcipher=True, page_size=bad)], [None])
        assert rep["lanes"][0]["state"] == "not-merged", bad

    def staged(edit) -> Path:
        staging = tmp_path / f"st-{edit.__name__}"
        (staging / "lanes").mkdir(parents=True)
        dest = staging / "lanes" / "wiki.db"
        shutil.copy2(snap, dest)
        con = sqlite3.connect(dest)
        edit(con)
        con.commit()
        con.close()
        return staging

    def no_stamp(con):
        con.execute("DROP TABLE lane_meta")

    def other_kind(con):
        con.execute("UPDATE lane_meta SET kind = '[click me](http://x.test) " + "y" * 5000 + "'")

    def view(con):
        con.execute("DROP TABLE wiki_walk_pages")
        con.execute("CREATE VIEW wiki_walk_pages AS SELECT 1 AS page_id")

    def virtual(con):
        con.execute("DROP TABLE wiki_walk_pages")
        con.execute("CREATE VIRTUAL TABLE wiki_walk_pages USING fts5(title)")

    for edit in (no_stamp, other_kind, view, virtual):
        rep = lane_merge.merge_staged_lanes(staged(edit), [entry], [None])
        (lane,) = rep["lanes"]
        assert lane["state"] == "failed", (edit.__name__, lane)
        assert "click me" not in lane["reason"] and len(lane["reason"]) <= 300, edit.__name__
    assert _snapshot_state() == before


def test_lanes_that_did_not_merge_are_owed_until_they_do(tmp_path, monkeypatch):
    """Correctness read on PR 2036: a failed or held lane merge must not be skipped for good.

    The corpus of an artifact is skipped on its second import; when its lanes did not merge,
    the digest is remembered so that import runs again, and forgotten once they merge.
    """
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    store.dispose_all()
    entry = {"name": "lanes/wiki.db", "kind": "wiki"}
    assert lane_merge.lanes_pending("d1") is False
    held = lane_merge.deferred_report([entry, "junk"])
    assert [x["state"] for x in held["lanes"]] == ["deferred"] and held["newly_followed"] == 0
    lane_merge.record_lane_outcome("d1", held)
    assert lane_merge.lanes_pending("d1") is True
    lane_merge.record_lane_outcome("d2", {"lanes": [{"kind": "wiki", "state": "failed", "reason": "x"}]})
    lane_merge.record_lane_outcome("d3", {"lanes": [], "error": "boom"})
    lane_merge.record_lane_outcome("d4", {"lanes": [{"kind": "osm", "state": "not-merged"}]})
    assert [lane_merge.lanes_pending(d) for d in ("d2", "d3", "d4")] == [True, True, False]
    lane_merge.record_lane_outcome("d1", {"lanes": [{"kind": "wiki", "state": "merged"}]})
    assert lane_merge.lanes_pending("d1") is False and lane_merge.lanes_pending("d2") is True
    raw = (tmp_path / "lane_merge_pending.json").read_text(encoding="utf-8")
    assert "boom" not in raw  # digests and kinds only
    # An erase destroys it with the rest of the app's files (R715), its lock and temps too.
    from src.safety.data_scope import is_app_owned

    for name in ("lane_merge_pending.json", "lane_merge_pending.json.lock", "lane_merge_pending.json.tmp.12.34"):
        assert is_app_owned(name), name


def test_the_restore_defers_lanes_while_the_queue_holds_the_corpus():
    """The lanes of a held item are not written to the live store (source-level pin)."""
    src = (Path(__file__).resolve().parents[1] / "src" / "backup" / "volume_job.py").read_text(encoding="utf-8")
    block = src[src.index("R729: the living-source stores"):]
    block = block[: block.index("with self._lock:")]
    assert block.index('report.get("held")') < block.index("merge_staged_lanes(")
    assert "deferred_report(lane_members)" in block and "record_lane_outcome(_digest" in block
    assert "lanes_pending(_digest)" in src


def test_owed_lanes_survive_a_kill_and_stop_after_three_attempts(tmp_path, monkeypatch):
    """Security read 2 on PR 2036: owed before the merge starts; never a full restore forever."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    store.dispose_all()
    entry = {"name": "lanes/wiki.db", "kind": "wiki"}
    failed = {"lanes": [{"kind": "wiki", "state": "failed", "reason": "x"}]}
    lane_merge.mark_lanes_owed("k", [entry])  # ...and the process dies here
    assert lane_merge.lanes_pending("k") is True
    lane_merge.record_lane_outcome("k", failed)
    lane_merge.mark_lanes_owed("k", [entry])
    lane_merge.record_lane_outcome("k", failed)
    assert lane_merge.lanes_pending("k") is True
    lane_merge.mark_lanes_owed("k", [entry])
    lane_merge.record_lane_outcome("k", failed)
    assert lane_merge.lanes_pending("k") is False  # third attempt used: skipped like any merged backup
    # A deferred lane uses up no attempt.
    for _ in range(5):
        lane_merge.record_lane_outcome("h", lane_merge.deferred_report([entry]))
    assert lane_merge.lanes_pending("h") is True
    lane_merge.mark_lanes_owed("other", [{"name": "lanes/osm.db", "kind": "osm"}])
    assert lane_merge.lanes_pending("other") is False  # a lane this build cannot merge is never owed


def test_a_backup_cannot_win_with_numbers_no_real_reading_reaches(machines, tmp_path):
    """Security read 2 on PR 2036: future timestamps and unreachable revision ids never win."""
    import sqlite3

    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    dest = staging / "lanes" / "wiki.db"
    shutil.copy2(snap, dest)
    con = sqlite3.connect(dest)
    con.execute("UPDATE versioned_entity_facts SET observed_at = '9999-01-01 00:00:00.000000', value_json = '\"FAKE\"'")
    con.execute("UPDATE wiki_walk_pages SET walked_at = '9999-01-01 00:00:00.000000', title = 'FAKE'")
    con.execute(
        "UPDATE wiki_warm_pages SET latest_revid = 1000000000000001, previous_revid = 1000000000000000, "
        "wanted_revid = 1000000000000001, latest_text = 'FAKE', previous_text = 'FAKE2'"
    )
    con.commit()
    con.close()
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    (lane,) = rep["lanes"]
    assert lane["state"] == "merged", lane
    assert lane["tables"]["wiki_warm_pages"]["texts_refused"] == 2
    with store.lane_session("wiki") as s:
        facts = {f.name: f.value_json for f in s.execute(select(VersionedEntityFact)).scalars()}
        assert "FAKE" not in facts["length"] and "FAKE" not in facts["qid"]
        walk = {w.page_id: w for w in s.execute(select(WikiWalkPage)).scalars()}
        assert walk[10].title == "Old title"
        assert walk[11].walked_at.year < 9999  # an absent page is stored, at the horizon at most
        warm = s.execute(select(WikiWarmPage)).scalar_one()
        assert (warm.latest_text, warm.previous_text) == ("w35", "w10")
        assert warm.wanted_revid == 35


def test_a_plaintext_lane_beside_an_encrypted_corpus_is_never_copied_out_in_the_clear(tmp_path, monkeypatch):
    """Security read 2 on PR 2036: the snapshot is staged inside the destination folder."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.dispose_all()
    try:
        store.create_lane("wiki")
        monkeypatch.setattr(store, "_corpus_is_encrypted", lambda: True)
        dest = tmp_path / "out" / "lanes" / "wiki.db"
        with pytest.raises(store.PlaintextLaneRefused):
            lane_merge.snapshot_lane_for_backup("wiki", dest)
        assert not dest.exists()
    finally:
        store.dispose_all()


def test_a_timestamp_this_build_cannot_read_refuses_the_member(machines, tmp_path):
    """Final read on PR 2036: a malformed timestamp would be committed and break every read."""
    import sqlite3

    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _snapshot_state()
    for i, stmt in enumerate(
        (
            "UPDATE versioned_entities SET first_seen_at = 5",
            "UPDATE wiki_walk_pages SET walked_at = '1999-13-45 00:00:00.000000'",
        )
    ):
        staging = tmp_path / f"bad{i}"
        (staging / "lanes").mkdir(parents=True)
        dest = staging / "lanes" / "wiki.db"
        shutil.copy2(snap, dest)
        con = sqlite3.connect(dest)
        con.execute(stmt)
        con.commit()
        con.close()
        rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
        assert rep["lanes"][0]["state"] == "failed", (stmt, rep)
        assert "timestamp" in rep["lanes"][0]["reason"]
    assert _snapshot_state() == before


def test_the_merge_keeps_the_pages_with_text_count_equal_to_the_rows(machines, tmp_path):
    """Final read on PR 2036: wiki_warm_editions.pages_with_text counts rows; the merge adds rows."""
    from src.wiki.lane_models import WikiWarmEdition

    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    use(a)  # this computer has never run WARM
    store.create_lane("wiki")
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "wiki.db")
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/wiki.db", "kind": "wiki"}], [None])
    assert rep["lanes"][0]["state"] == "merged", rep
    with store.lane_session("wiki") as s:
        (ed,) = s.execute(select(WikiWarmEdition)).scalars()
        assert (ed.edition, ed.pages_with_text, ed.texts_fetched) == ("en", 1, 0)


def test_held_lanes_merge_when_the_import_group_commits(machines, tmp_path, monkeypatch):
    """R729 amendment (coordinator 2026-11-16): the mass-import path holds corpora on a
    working copy; their lanes wait beside it and merge when the group commits, never before."""
    from src.backup import import_queue
    from src.backup.import_queue import ImportQueueManager, _CheckpointGroup

    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "wiki.db")
    entry = {"name": "lanes/wiki.db", "kind": "wiki", "sqlcipher": True}
    group_dir = tmp_path / ".restore-group"
    # A plaintext member is never kept beside the working copy: it stays owed.
    assert lane_merge.hold_lane_members(staging, [dict(entry, sqlcipher=False)], group_dir, "dg") is None
    held = lane_merge.hold_lane_members(staging, [entry], group_dir, "dg")
    assert held and Path(held["dir"]).is_relative_to(group_dir)
    shutil.rmtree(staging)  # the item's staging is gone by the time its group commits
    lane_merge.record_lane_outcome("dg", lane_merge.deferred_report([entry]))
    assert lane_merge.lanes_pending("dg")

    before = _snapshot_state()
    mgr = ImportQueueManager(state_path=tmp_path / "queue.json")
    item = {"id": "i1", "summary": {"report": {"held": True, "living_sources": {"lanes": []}}}}
    mgr._items = [item]
    monkeypatch.setattr(import_queue, "log_failure", lambda *a, **k: None)
    # Discarded group: nothing merges, the lanes stay owed.
    mgr._merge_held_lanes(_CheckpointGroup(dir=group_dir))
    assert _snapshot_state() == before
    group = _CheckpointGroup(dir=group_dir)
    group.held_lanes.append(("i1", held))
    mgr._merge_held_lanes(group)
    living = item["summary"]["report"]["living_sources"]
    assert living["lanes"][0]["state"] == "merged", living
    assert _snapshot_state() != before
    assert not lane_merge.lanes_pending("dg")

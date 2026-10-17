"""The curated stamp writes through one UPDATE per chunk and one INSERT, and leaves exactly the rows the ORM form left.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

``stamp_curated_catalog`` used to set three attributes per row through the ORM and ``add`` one attempt row each: on a first
install of the shipped catalogue (6,616 rows) that is 6,616 INSERT statements and about a second. The write is now ORM-enabled bulk DML: one
``UPDATE sources ... WHERE id IN (chunk) AND status = 'unqualified'`` per chunk and ONE executemany INSERT of the attempt rows.
What these tests pin is what a quicker write could get wrong:

* the statement shape (red without: one INSERT per row again);
* the rows are the SAME as the ORM form leaves, column for column, including a mix a careless rewrite would bend (a measured
  disqualification, a row already qualified, an unqualified row that carries a judging attempt, a sibling of a refused outlet, a
  row out of scope), and the counts are the same;
* the UPDATE sets the three columns the stamp owns and no other (so ``feed_key`` and ``rss_url`` are untouched: the mapper event
  that derives ``feed_key`` does not fire for a bulk UPDATE, so the stamp repairs a stored key that disagrees with its own ``rss_url`` itself, for the rows it stamps, as the ORM form did through that event);
* a row another writer moved off ``unqualified`` after the scan is neither overwritten nor given an attempt row;
* the session-level hooks that gate and mark writes (``do_orm_execute``) still see both statements, because the single-writer
  gate takes its window from them;
* a stamp that finds nothing to write opens no write window it does not close.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import src.catalog.qualification as Q
from src.catalog.provenance_scope import curated_catalogue_domains, is_curated_tags
from src.catalog.qualification import (
    CURATED_CRITERIA_VERSION,
    JUDGING_VERDICTS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_CURATED,
    stamp_curated_catalog,
)
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
_CURATED = "news,via:curated"


def _reference_orm_stamp(session, *, now):
    """The stamp as it was written before the batched write: the same scan and decisions, the ORM write. Kept HERE as the reference
    the batched form is compared against; it is not used by the app."""
    domains = curated_catalogue_domains()
    counts = {"curated": 0, "stamped": 0, "already_qualified": 0, "disqualified": 0, "kept_local": 0, "outlet_disqualified": 0}
    pending, refused = [], set()
    for sid, domain, tags, status in session.query(Source.id, Source.domain, Source.tags, Source.status):
        outlet = str(domain or "").strip().lower()
        if status == STATUS_DISQUALIFIED:
            refused.add(outlet)
        if not (is_curated_tags(tags) or outlet in domains):
            continue
        counts["curated"] += 1
        if status == STATUS_QUALIFIED:
            counts["already_qualified"] += 1
        elif status == STATUS_DISQUALIFIED:
            counts["disqualified"] += 1
        elif status == STATUS_UNQUALIFIED:
            pending.append((int(sid), outlet))
    ids = [sid for sid, outlet in pending if outlet not in refused]
    counts["outlet_disqualified"] = len(pending) - len(ids)
    judged = {
        int(sid) for (sid,) in session.query(SourceQualificationAttempt.source_id)
        .filter(SourceQualificationAttempt.verdict.in_(JUDGING_VERDICTS)).distinct()
    }
    to_stamp = [sid for sid in ids if sid not in judged]
    counts["kept_local"] = len(ids) - len(to_stamp)
    stamped = []
    for chunk in Q._id_chunks(to_stamp):
        for source in session.query(Source).filter(Source.id.in_(chunk)):
            source.status = STATUS_QUALIFIED
            source.qualified_at = now
            source.qualification_criteria_version = CURATED_CRITERIA_VERSION
            stamped.append(source)
    for source in stamped:
        session.add(SourceQualificationAttempt(source_id=source.id, attempted_at=now, verdict=VERDICT_CURATED,
                                               criteria_version=CURATED_CRITERIA_VERSION))
    if stamped:
        session.commit()
    counts["stamped"] = len(stamped)
    return counts


def _store(n_unqualified: int = 5):
    """A store with every case the stamp decides: `n_unqualified` curated rows waiting, plus one of each kind it must leave."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True, autoflush=False)()
    rows = [Source(name=f"Curated {i}", domain=f"curated{i}.example", rss_url=f"https://curated{i}.example/feed",
                   tags=_CURATED, status=STATUS_UNQUALIFIED, enabled=True) for i in range(n_unqualified)]
    rows += [
        Source(name="Measured bad", domain="bad.example", rss_url="https://bad.example/a", tags=_CURATED, status=STATUS_DISQUALIFIED),
        Source(name="Sibling of bad", domain="bad.example", rss_url="https://bad.example/b", tags=_CURATED, status=STATUS_UNQUALIFIED),
        Source(name="Already", domain="already.example", rss_url="https://already.example/a", tags=_CURATED, status=STATUS_QUALIFIED,
               qualified_at=NOW, qualification_criteria_version="earlier"),
        Source(name="Judged", domain="judged.example", rss_url="https://judged.example/a", tags=_CURATED, status=STATUS_UNQUALIFIED),
        Source(name="Typed", domain="typed.example", rss_url="https://typed.example/a", tags="news", status=STATUS_UNQUALIFIED),
        Source(name="Feedless", domain="feedless.example", rss_url=None, tags=_CURATED, status=STATUS_UNQUALIFIED),
    ]
    session.add_all(rows)
    session.commit()
    judged = session.query(Source).filter_by(domain="judged.example").one()
    session.add(SourceQualificationAttempt(source_id=judged.id, attempted_at=NOW, verdict=STATUS_QUALIFIED, criteria_version="t"))
    session.commit()
    return session


def _all_columns(session):
    """Every column of every sources row and attempt row, sorted: nothing the two forms could differ in is left out."""
    src_cols = [c.key for c in Source.__table__.columns]
    att_cols = [c.key for c in SourceQualificationAttempt.__table__.columns if c.key != "id"]
    sources = sorted(tuple(repr(getattr(r, k)) for k in src_cols) for r in session.query(Source))
    attempts = sorted(tuple(repr(getattr(r, k)) for k in att_cols) for r in session.query(SourceQualificationAttempt))
    return sources, attempts


def _spy(session):
    stmts: list[tuple[str, bool]] = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda conn, cur, statement, params, ctx, many: stmts.append((statement, many)))
    return stmts


def test_the_rows_and_counts_are_exactly_what_the_orm_form_left():
    ref, new = _store(), _store()
    ref_counts = _reference_orm_stamp(ref, now=NOW)
    new_counts = stamp_curated_catalog(new, now=NOW)
    assert new_counts == ref_counts
    assert new_counts["stamped"] == 6 and new_counts["outlet_disqualified"] == 1 and new_counts["kept_local"] == 1   # 5 waiting + the feed-less row
    assert _all_columns(new) == _all_columns(ref)
    # and a second call stamps nothing and writes nothing, as before
    stmts = _spy(new)
    assert stamp_curated_catalog(new, now=NOW)["stamped"] == 0
    assert [s for s, _ in stmts if not s.lstrip().upper().startswith("SELECT")] == []


def test_a_first_install_is_one_update_per_chunk_and_one_insert():
    n = 2 * Q._ID_CHUNK + 50          # rows to stamp: three chunks (the store adds one feed-less row to the n it is asked for)
    session = _store(n - 1)
    stmts = _spy(session)
    out = stamp_curated_catalog(session, now=NOW)
    assert out["stamped"] == n
    updates = [s for s, _ in stmts if s.lstrip().upper().startswith("UPDATE SOURCES")]
    inserts = [(s, many) for s, many in stmts if s.lstrip().upper().startswith("INSERT INTO SOURCE_QUALIFICATION_ATTEMPTS")]
    assert len(updates) == 3, len(updates)
    assert len(inserts) == 1 and inserts[0][1] is True, inserts      # ONE executemany, not one INSERT per row
    assert session.query(SourceQualificationAttempt).filter_by(verdict=VERDICT_CURATED).count() == n


def test_the_update_sets_the_three_columns_the_stamp_owns_and_only_those():
    session = _store()
    stmts = _spy(session)
    stamp_curated_catalog(session, now=NOW)
    update = next(s for s, _ in stmts if s.lstrip().upper().startswith("UPDATE SOURCES"))
    set_clause = update.split("SET", 1)[1].split("WHERE", 1)[0]
    written = {part.split("=")[0].strip() for part in set_clause.split(",")}
    assert written == {"status", "qualified_at", "qualification_criteria_version"}, written
    assert "status = ?" in update.split("WHERE", 1)[1]                # the guard: only a row still unqualified
    # a row's feed identity is untouched
    row = session.query(Source).filter_by(domain="curated0.example").one()
    assert row.rss_url == "https://curated0.example/feed" and row.feed_key


def test_a_row_another_writer_moved_after_the_scan_is_not_overwritten_or_given_an_attempt(monkeypatch):
    session = _store()
    raced = session.query(Source).filter_by(domain="curated2.example").one()
    raced_id = raced.id
    real_chunks = Q._id_chunks

    def racing_chunks(ids, size=Q._ID_CHUNK):
        # after the scan, before the write: someone else measures the row disqualified
        session.execute(Source.__table__.update().where(Source.id == raced_id).values(status=STATUS_DISQUALIFIED))
        yield from real_chunks(ids, size)

    monkeypatch.setattr(Q, "_id_chunks", racing_chunks)
    out = stamp_curated_catalog(session, now=NOW)
    session.expire_all()
    row = session.get(Source, raced_id)
    assert row.status == STATUS_DISQUALIFIED and row.qualified_at is None
    assert session.query(SourceQualificationAttempt).filter_by(source_id=raced_id).count() == 0
    assert out["stamped"] == 5                                          # the other five (four waiting + the feed-less row)
    assert session.query(SourceQualificationAttempt).filter_by(verdict=VERDICT_CURATED).count() == 5


def test_the_session_hooks_that_gate_a_write_see_both_statements():
    """The single-writer gate and the write marker take their window from ``do_orm_execute``; a bulk statement run through
    ``session.execute`` on a mapped table must still reach them (it is an ORM-enabled DML), or the writes would slip past the gate."""
    session = _store()
    seen: list[tuple[bool, bool]] = []
    event.listen(session, "do_orm_execute", lambda state: seen.append((state.is_update, state.is_insert)))
    stamp_curated_catalog(session, now=NOW)
    assert (True, False) in seen and (False, True) in seen, seen


def test_a_stamp_that_finds_nothing_to_write_opens_no_write_window():
    session = _store(0)
    # every curated row that could be stamped is already decided: nothing pending
    session.query(Source).filter(Source.status == STATUS_UNQUALIFIED).update({"status": STATUS_QUALIFIED}, synchronize_session=False)
    session.commit()
    stmts = _spy(session)
    assert stamp_curated_catalog(session, now=NOW)["stamped"] == 0
    assert [s for s, _ in stmts if not s.lstrip().upper().startswith("SELECT")] == []
    assert not session.in_transaction() or not session.dirty


@pytest.mark.parametrize("n", [1, 399, 400, 401, 402])
def test_the_chunk_edges_stamp_every_row_once(n):
    session = _store(n - 1)       # the store adds one feed-less row to stamp, so n rows are stamped in all
    out = stamp_curated_catalog(session, now=NOW)
    assert out["stamped"] == n
    assert session.query(SourceQualificationAttempt).filter_by(verdict=VERDICT_CURATED).count() == n


def _blank_every_feed_key(session):
    """Export's probe shape: rows that carry a feed but a blank key (a raw write that bypassed the ``before_update`` mapper event)."""
    # one row per domain (the key is part of the unique pair, so two blank siblings could not coexist)
    session.execute(Source.__table__.update().where(Source.name != "Sibling of bad").values(feed_key=""))
    session.commit()


def test_a_blank_feed_key_is_healed_for_the_rows_stamped_exactly_as_the_orm_form_did():
    """The ORM stamp rewrote ``feed_key`` from ``rss_url`` on every row it touched (the mapper event); a bulk UPDATE fires none, so the
    batched stamp heals those rows itself. Rows it does NOT stamp (a judged row, a sibling of a refused outlet) keep their key as
    they did, and every column of both tables is the same as the ORM form leaves."""
    ref, new = _store(), _store()
    for s in (ref, new):
        _blank_every_feed_key(s)
    _reference_orm_stamp(ref, now=NOW)
    stamp_curated_catalog(new, now=NOW)
    healed = {r.name: r.feed_key for r in new.query(Source)}
    assert healed["Curated 0"] and healed["Curated 0"] == next(r.feed_key for r in ref.query(Source).filter_by(name="Curated 0"))
    assert healed["Judged"] == "" and healed["Measured bad"] == ""          # not stamped, not touched (as before)
    assert _all_columns(new) == _all_columns(ref)


def test_a_healthy_store_issues_no_feed_key_write():
    session = _store()
    stmts = _spy(session)
    stamp_curated_catalog(session, now=NOW)
    writes = [(s, many) for s, many in stmts if s.lstrip().upper().startswith("UPDATE SOURCES")]
    assert len(writes) == 1 and not any(many for _, many in writes), writes     # the one chunk UPDATE; no executemany heal
    assert not any("feed_key" in s.split("WHERE", 1)[0] for s, _ in writes)


def test_the_heal_derives_the_key_from_the_feed_the_row_holds_when_it_is_stamped(tmp_path, monkeypatch):
    """The independent read found the heal used the ``rss_url`` the SCAN read: another writer's feed edit committed between the scan
    and the first UPDATE (the scan opens no write window) was then undone in ``feed_key``, which the ORM form never did because it
    re-loaded each row. Red without the re-read: ``feed_key`` kept the key of the OLD url."""
    from src.database.feed_key import feed_key

    engine = create_engine(f"sqlite:///{tmp_path}/race.db", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True, autoflush=False)
    session = maker()
    session.add(Source(name="X", domain="x.example", rss_url="https://x.example/a", tags=_CURATED, status=STATUS_UNQUALIFIED))
    session.commit()
    session.execute(Source.__table__.update().values(feed_key=""))     # a stored key that disagrees: a raw write bypassed the event
    session.commit()
    real_chunks = Q._id_chunks

    def racing_chunks(ids, size=Q._ID_CHUNK):
        other = maker()
        row = other.query(Source).one()
        row.rss_url = "https://x.example/b"                            # an ORM edit: the event derives the right key for it
        other.commit()
        other.close()
        yield from real_chunks(ids, size)

    monkeypatch.setattr(Q, "_id_chunks", racing_chunks)
    assert stamp_curated_catalog(session, now=NOW)["stamped"] == 1
    session.expire_all()
    row = session.query(Source).one()
    assert row.rss_url == "https://x.example/b"
    assert row.feed_key == feed_key("https://x.example/b"), "the heal wrote the key of the url the scan saw"

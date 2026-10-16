"""The alpha-2 -> alpha-3 migration of a store: app-stopped, verified, resumable, and honest about what it leaves.

Every store here is a scratch file built for the test; no real data is read or written.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.backup import country_migration as cm
from src.database import country_form as cf

ROOT = Path(__file__).resolve().parents[1]


def _new_store(path: Path, *, articles: int = 60, sources: int = 4) -> Path:
    """A scratch alpha-2 store with every country-bearing table populated."""
    from src.database.models import Base

    eng = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path)
    spell = ["fr", "FR", "de", "us", "gb", "uk", "eu", "int", "WLD", "zz", None, "FRA", "fra"]
    for i in range(sources):
        con.execute(
            "INSERT INTO sources (name, domain, rss_url, country, language, source_type, reliability_score, rate_limit_ms, enabled, priority) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"s{i}", f"s{i}.example", f"http://s{i}.example/rss", spell[i], "en", "news", 0.5, 1000, 1, 1),
        )
    for i in range(articles):
        con.execute(
            "INSERT INTO articles (url, canonical_url, source_id, title, content, hash, country) VALUES (?,?,?,?,?,?,?)",
            (f"http://a/{i}", f"http://a/{i}", 1, f"t{i}", f"c{i}", f"h{i}", spell[i % len(spell)]),
        )
    # sparse rowids on purpose: the sweep walks rowid windows, not row positions
    con.execute("DELETE FROM articles WHERE id % 7 = 3")
    for i, j in enumerate((("fr", "u1"), ("de", "u2"), ("uk", "u3"), ("int", "u4"))):
        con.execute("INSERT INTO law_documents (jurisdiction, title, url, country) VALUES (?,?,?,?)", (j[0], f"d{i}", j[1], j[0]))
    con.execute("INSERT INTO places (id, name, country, country_alpha3) VALUES ('p1', 'Paris', 'fr', 'FRA')")
    con.execute("INSERT INTO places (id, name, country, country_alpha3) VALUES ('p2', 'Nowhere', NULL, NULL)")
    con.commit()
    con.close()
    return path


def _column(path: Path, table: str, column: str) -> dict:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute(f'SELECT "{column}", COUNT(*) FROM "{table}" GROUP BY "{column}"').fetchall())
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _small_windows(monkeypatch):
    monkeypatch.setattr(cm, "BATCH_ROWIDS", 9)  # many windows, so the cursor and the per-window commit are exercised


def test_the_run_converts_what_has_an_alpha3_and_keeps_everything_else_as_stored(tmp_path):
    db = _new_store(tmp_path / "s.db")
    before = _column(db, "articles", "country")
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "done", rep.message
    after = _column(db, "articles", "country")
    assert sum(after.values()) == sum(before.values())  # no row lost or added
    assert after.get(None) == before.get(None)  # NULL stays NULL
    for kept in ("uk", "eu", "int", "WLD", "zz"):  # no ISO meaning: exactly as stored (R100)
        assert after.get(kept) == before.get(kept), kept
    assert not {"fr", "FR", "fra", "de", "us", "gb"} & set(after), "a convertible spelling is still there"
    assert after["FRA"] == before.get("fr", 0) + before.get("FR", 0) + before.get("FRA", 0) + before.get("fra", 0)
    assert _column(db, "places", "country") == {None: 1, "FRA": 1}
    assert _column(db, "places", "country_alpha3") == {None: 1, "FRA": 1}  # the other column is not touched
    assert cf.read_form(sqlite3.connect(db)) == "alpha3"
    assert all(b["balanced"] for b in rep.balance.values())


def test_what_has_no_iso_meaning_is_counted_and_listed_by_table_and_column(tmp_path):
    db = _new_store(tmp_path / "s.db")
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert set(rep.unmapped["articles.country"]) >= {"uk", "eu", "int", "WLD", "zz"}
    assert rep.unmapped["law_documents.jurisdiction"] == {"int": 1, "uk": 1}
    assert rep.unmapped["law_documents.country"] == {"int": 1, "uk": 1}
    assert "places.country" not in rep.unmapped  # nothing unmapped there: not listed with an empty entry
    assert all(isinstance(n, int) and n > 0 for vals in rep.unmapped.values() for n in vals.values())


def test_a_second_run_changes_nothing(tmp_path):
    db = _new_store(tmp_path / "s.db")
    cm.migrate(db, backup_dir=tmp_path / "bk")
    snap = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    rep = cm.migrate(db, backup_dir=tmp_path / "bk2")
    assert rep.state == "already-done"
    assert snap == {t: _column(db, t, c) for t, c in cm.migration_columns()}
    assert not (tmp_path / "bk2").exists(), "a finished store takes no second safety copy"


def test_the_safety_copy_is_taken_first_verified_and_holds_the_old_form(tmp_path):
    db = _new_store(tmp_path / "s.db")
    live_before = {t: _column(db, t, "country") for t in ("articles",)}
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    copy = Path(rep.backup["path"])
    assert copy.exists() and rep.backup["quick_check"] == "ok"
    con = sqlite3.connect(copy)
    try:
        assert dict(con.execute("SELECT country, COUNT(*) FROM articles GROUP BY country").fetchall()) == live_before["articles"]
        assert cf.read_form(con) == "alpha2"
    finally:
        con.close()
    assert rep.backup["tables"]["articles"] == sum(live_before["articles"].values())


def test_no_free_space_for_the_copy_refuses_before_any_row_moves(tmp_path, monkeypatch):
    db = _new_store(tmp_path / "s.db")
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    monkeypatch.setattr(cm, "_free_bytes", lambda _d: 10)
    with pytest.raises(cm.MigrationRefused, match="not enough free space"):
        cm.migrate(db, backup_dir=tmp_path / "bk")
    assert before == {t: _column(db, t, c) for t, c in cm.migration_columns()}
    assert cf.read_form(sqlite3.connect(db)) == "alpha2"


def test_a_collision_in_a_unique_index_refuses_before_any_row_moves(tmp_path):
    db = _new_store(tmp_path / "s.db")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO law_documents (jurisdiction, title, url, country) VALUES ('FRA', 'dup', 'u1', 'FRA')")  # fr+u1 exists
    con.commit()
    con.close()
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "refused" and rep.collisions
    hit = rep.collisions[0]
    assert (hit["table"], hit["column"], hit["becomes"], hit["others"], hit["rows"]) == ("law_documents", "jurisdiction", "FRA", ["u1"], 2)
    assert before == {t: _column(db, t, c) for t, c in cm.migration_columns()}, "a refused run changed a row"
    assert not (tmp_path / "bk").exists()


def test_two_spellings_of_one_country_that_would_collide_are_found_too(tmp_path):
    db = _new_store(tmp_path / "s.db")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO law_documents (jurisdiction, title, url, country) VALUES ('FR', 'dup', 'u1', 'FR')")  # fr+u1 and FR+u1
    con.commit()
    con.close()
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "refused" and rep.collisions[0]["rows"] == 2


def test_the_old_unscoped_search_trigger_is_refused_not_paid_for_per_row(tmp_path):
    db = _new_store(tmp_path / "s.db")
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER IF EXISTS article_fts_au")
    con.execute("CREATE TRIGGER article_fts_au AFTER UPDATE ON articles BEGIN SELECT 1; END")
    con.commit()
    con.close()
    with pytest.raises(cm.MigrationRefused, match="unscoped"):
        cm.migrate(db, backup_dir=tmp_path / "bk")
    assert cf.read_form(sqlite3.connect(db)) == "alpha2"


def test_the_run_holds_the_file_and_a_holder_stops_the_run(tmp_path):
    db = _new_store(tmp_path / "s.db")
    holder = sqlite3.connect(db)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("SELECT COUNT(*) FROM articles").fetchall()
    holder.execute("BEGIN")
    holder.execute("SELECT COUNT(*) FROM articles").fetchall()  # a reader inside a transaction: the app, idle
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    with pytest.raises(cm.AppStillRunning):
        cm.migrate(db, backup_dir=tmp_path / "bk")
    holder.close()
    assert before == {t: _column(db, t, c) for t, c in cm.migration_columns()}
    seen: list[str] = []

    def during(event: dict) -> None:
        if event["phase"] == "sweep" and not seen:
            try:
                other = sqlite3.connect(db, timeout=0.2)
                other.execute("INSERT INTO sources (name, domain, rss_url) VALUES ('x','x','x')")
                other.commit()
                seen.append("WROTE")
            except sqlite3.OperationalError as exc:
                seen.append("refused" if "locked" in str(exc) else str(exc))

    cm.migrate(db, backup_dir=tmp_path / "bk", progress=during)
    assert seen == ["refused"], "a second program could write while the migration ran"


def test_estimate_reads_the_plan_and_changes_nothing_with_the_file_open(tmp_path):
    db = _new_store(tmp_path / "s.db")
    other = sqlite3.connect(db)
    other.execute("SELECT 1 FROM articles LIMIT 1").fetchall()
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    rep = cm.migrate(db, estimate_only=True, backup_dir=tmp_path / "bk")
    other.close()
    assert rep.plan["to_rewrite"] > 0 and rep.estimate["rows_to_rewrite"] == rep.plan["to_rewrite"]
    assert before == {t: _column(db, t, c) for t, c in cm.migration_columns()}
    assert not (tmp_path / "bk").exists() and cf.read_form(sqlite3.connect(db)) == "alpha2"


def test_the_estimate_is_shown_first_and_a_no_leaves_the_store_untouched(tmp_path):
    db = _new_store(tmp_path / "s.db")
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    shown: list[dict] = []
    rep = cm.migrate(db, backup_dir=tmp_path / "bk", confirm=lambda plan, est: shown.append(est) or False)
    assert rep.state == "declined" and shown and shown[0]["rows_to_rewrite"] > 0
    assert shown[0]["rate_rows_per_s"] and "rolled back" in shown[0]["basis"]
    assert before == {t: _column(db, t, c) for t, c in cm.migration_columns()}, "the timing window was not rolled back"
    assert not (tmp_path / "bk").exists()


# ---- killed mid-run: every way to die leaves a store the next run finishes ---------------------------------- #
_CHILD = textwrap.dedent(
    """
    import os, sys, sqlite3
    from pathlib import Path
    from src.backup import country_migration as cm
    cm.BATCH_ROWIDS = 9
    db, bk, mode, n = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    calls = {"n": 0}
    if mode == "inside-window":
        real = cm._sweep_window
        def dying(con, cp, lo, hi):
            out = real(con, cp, lo, hi)          # the UPDATE ran ...
            calls["n"] += 1
            if calls["n"] == n:
                os._exit(9)                      # ... and the process dies before the window COMMITs
            return out
        cm._sweep_window = dying
        cm.migrate(db, backup_dir=bk)
    elif mode == "in-final-transaction":
        from src.database import country_form as cf
        real_write = cf.write_form
        def dying_write(con, form, *, by):
            real_write(con, form, by=by)         # the marker was written ...
            os._exit(9)                          # ... and the process dies before the final COMMIT
        cf.write_form = dying_write
        cm.migrate(db, backup_dir=bk)
    else:
        def after_commit(event):
            if event["phase"] == "sweep":
                calls["n"] += 1
                if calls["n"] == n:
                    os._exit(9)                  # dies between windows
        cm.migrate(db, backup_dir=bk, progress=after_commit)
    """
)


def _kill_child(db: Path, bk: Path, mode: str, n: int) -> None:
    done = subprocess.run([sys.executable, "-c", _CHILD, str(db), str(bk), mode, str(n)], cwd=ROOT,
                          env={**os.environ, "OO_DB_PLAINTEXT": "1"}, capture_output=True, text=True, timeout=240)
    assert done.returncode == 9, done.stdout + done.stderr


@pytest.mark.parametrize("mode", ["inside-window", "between-windows"])
def test_a_run_killed_mid_way_is_finished_by_the_next_one_and_ends_exactly_as_an_unbroken_run(tmp_path, mode):
    ref = _new_store(tmp_path / "ref.db")
    cm.migrate(ref, backup_dir=tmp_path / "bk-ref")
    want = {t: _column(ref, t, c) for t, c in cm.migration_columns()}

    db = _new_store(tmp_path / "s.db")
    _kill_child(db, tmp_path / "bk", mode, 3)
    mid = _column(db, "articles", "country")
    assert cf.read_form(sqlite3.connect(db)) == "alpha2", "a half-done run must not claim alpha-3"
    assert "FRA" in mid and ("fr" in mid or "FR" in mid), "the kill came too early or too late to leave a half-done store"
    copy = next((tmp_path / "bk").glob("*.db"))
    stamp = copy.stat().st_mtime_ns
    with sqlite3.connect(db) as c:
        assert json.loads(c.execute("SELECT value FROM app_state WHERE key = ?", (cm.JOURNAL_KEY,)).fetchone()[0])["state"] == "running"

    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "done", rep.message
    assert want == {t: _column(db, t, c) for t, c in cm.migration_columns()}
    assert all(b["balanced"] for b in rep.balance.values())
    assert copy.stat().st_mtime_ns == stamp and len(list((tmp_path / "bk").glob("*.db"))) == 1, "the safety copy was taken again, half-migrated"
    assert cf.read_form(sqlite3.connect(db)) == "alpha3"


def test_a_window_killed_before_its_commit_leaves_none_of_its_rows_converted(tmp_path):
    db = _new_store(tmp_path / "s.db", articles=200)
    before = _column(db, "articles", "country")
    _kill_child(db, tmp_path / "bk", "inside-window", 1)  # dies in the very first window, after its UPDATE ran
    assert _column(db, "articles", "country") == before, "an uncommitted window was applied"


def test_a_run_killed_inside_its_last_transaction_converted_no_alternate_and_the_next_run_finishes(tmp_path):
    """The alternates' codes and the marker change in ONE transaction: a kill after both statements and before the COMMIT
    must leave the store as the sweep left it, so the resume converts them and flips the marker, never one without the other."""
    db = _new_store(tmp_path / "s.db")
    con = sqlite3.connect(db)
    ident = '{"jurisdiction":"fr","document_url":"u","model":"m"}'
    con.execute(
        "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
        " VALUES (1, 'law_revision_summaries', ?, 1, '{\"summary\":\"s\"}', '{}', 'o', 'pending', '2026-09-01')", (ident,))
    con.commit()
    con.close()
    _kill_child(db, tmp_path / "bk", "in-final-transaction", 0)
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT identity FROM metadata_alternates").fetchone()[0] == ident, "an uncommitted alternate was converted"
        assert cf.read_form(con) == "alpha2", "the marker flipped without its commit"
        assert json.loads(con.execute("SELECT value FROM app_state WHERE key = ?", (cm.JOURNAL_KEY,)).fetchone()[0])["state"] == "running"
    finally:
        con.close()
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "done", rep.message
    con = sqlite3.connect(db)
    try:
        assert json.loads(con.execute("SELECT identity FROM metadata_alternates").fetchone()[0])["jurisdiction"] == "FRA"
        assert cf.read_form(con) == "alpha3"
    finally:
        con.close()


def test_stopping_between_windows_is_resumable(tmp_path):
    db = _new_store(tmp_path / "s.db")
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 3

    rep = cm.migrate(db, backup_dir=tmp_path / "bk", should_stop=stop)
    assert rep.state == "interrupted" and cf.read_form(sqlite3.connect(db)) == "alpha2"
    assert cm.migrate(db, backup_dir=tmp_path / "bk").state == "done"


def test_a_resume_whose_safety_copy_is_gone_refuses_rather_than_copy_a_half_migrated_store(tmp_path):
    db = _new_store(tmp_path / "s.db")
    _kill_child(db, tmp_path / "bk", "between-windows", 3)
    for f in (tmp_path / "bk").glob("*.db"):
        f.unlink()
    with pytest.raises(cm.MigrationRefused, match="safety copy is gone"):
        cm.migrate(db, backup_dir=tmp_path / "bk")


def test_a_store_that_says_alpha3_but_holds_alpha2_is_not_called_done(tmp_path):
    db = _new_store(tmp_path / "s.db")
    con = sqlite3.connect(db)
    cf.write_form(con, "alpha3", by="test")
    con.commit()
    con.close()
    with pytest.raises(cm.MigrationRefused, match="still holds alpha-2"):
        cm.migrate(db, backup_dir=tmp_path / "bk")


# ---- the read of the B1 head -------------------------------------------------------------------------------------- #
def _boot_init_db(data: Path) -> subprocess.CompletedProcess:
    """What every start path does first: ``init_db()`` on the store under ``data``."""
    env = {**os.environ, "OO_DATA_DIR": str(data), "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1", "OO_AUTOSEED": "0"}
    env.pop("DATABASE_URL", None)
    return subprocess.run([sys.executable, "-c", "from src.database.session import init_db; init_db(); print('booted')"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)


def test_an_interrupted_run_stops_the_app_from_booting_or_writing_until_it_is_finished(tmp_path, monkeypatch):
    """Committed windows hold alpha-3 while the marker says alpha-2: an equality filter on `fr` would miss them, a restore keyed
    on the value would duplicate a law document, and one app write would make the run unfinishable. So nothing starts on it."""
    from src.config import kv_store

    data = tmp_path / "state"
    data.mkdir()
    db = _new_store(data / "open_omniscience.db")
    before = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 3

    assert cm.migrate(db, backup_dir=tmp_path / "bk", should_stop=stop).state == "interrupted"
    half = {t: _column(db, t, c) for t, c in cm.migration_columns()}
    assert half != before, "the stop came before any window: the test would prove nothing"

    booted = _boot_init_db(data)
    assert booted.returncode != 0 and "booted" not in booted.stdout
    assert "migrate-countries" in booted.stderr and "interrupted" in booted.stderr, booted.stderr[-1500:]
    with sqlite3.connect(db) as jc:
        saved = json.loads(jc.execute("SELECT value FROM app_state WHERE key = ?", (cm.JOURNAL_KEY,)).fetchone()[0])["backup"]["path"]
    assert saved in booted.stderr, "the refusal does not say where the safety copy is"
    assert {t: _column(db, t, c) for t, c in cm.migration_columns()} == half, "the refused boot still touched the store"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    kv_store.kv_invalidate()
    with pytest.raises(cf.MigrationUnfinished):
        cf.store_form()
    with pytest.raises(cf.StoreFormUnreadable):  # every caller that already fails closed on an unreadable form does here too
        cf.CountryCode(8).process_bind_param("fr", None)
    with cf.writing_in("alpha2"):
        assert cf.store_form() == "alpha2", "a block that fills a side file is not the live store"

    assert cm.migrate(db, backup_dir=tmp_path / "bk").state == "done"
    kv_store.kv_invalidate()
    assert cf.store_form() == "alpha3"
    assert _boot_init_db(data).stdout.strip().endswith("booted")


def test_the_diagnostics_card_says_a_run_is_unfinished_instead_of_a_form(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    def unfinished():
        raise cf.MigrationUnfinished(cf.unfinished_message("interrupted"))

    with TestClient(app) as client:
        monkeypatch.setattr(cf, "store_form", unfinished)
        body = client.get("/api/diagnostics/country-form").json()
    assert body["form"] is None and body["readable"] is False and body["unfinished"] is True
    assert "migrate-countries" in body["note"]


def test_two_stores_migrated_into_one_backup_folder_each_keep_their_own_safety_copy(tmp_path):
    import hashlib

    a = _new_store(tmp_path / "a.db", articles=51)
    b = _new_store(tmp_path / "b.db", articles=8)
    shared = tmp_path / "shared"
    ra = cm.migrate(a, backup_dir=shared)
    copy_a = Path(ra.backup["path"])
    digest = hashlib.sha256(copy_a.read_bytes()).hexdigest()
    rb = cm.migrate(b, backup_dir=shared)
    assert ra.state == rb.state == "done"
    assert Path(rb.backup["path"]) != copy_a and len(list(shared.glob("*.pre-country-form-*.db"))) == 2
    assert hashlib.sha256(copy_a.read_bytes()).hexdigest() == digest, "another store's only safety copy was replaced"


def test_the_name_of_a_safety_copy_tells_two_stores_with_one_file_name_apart(tmp_path):
    one, two = tmp_path / "x" / "open_omniscience.db", tmp_path / "y" / "open_omniscience.db"
    assert cm.backup_name(one, "T") != cm.backup_name(two, "T")
    assert cm.backup_name(one, "T") == cm.backup_name(one, "T"), "a resume must be able to name the same file"
    assert cm.backup_name(one, "T").startswith("open_omniscience.pre-country-form-T-") and cm.backup_name(one, "T").endswith(".db")


def _live(db):
    from src.database.connect import connect

    return connect(db, check_same_thread=False)


def test_a_safety_copy_is_never_written_over_a_file_that_is_there(tmp_path):
    import hashlib

    a = _new_store(tmp_path / "a.db", articles=12)
    taken = tmp_path / "bk" / "taken.db"
    taken.parent.mkdir()
    taken.write_bytes(b"somebody's only copy")
    digest = hashlib.sha256(taken.read_bytes()).hexdigest()
    con = _live(a)
    try:
        with pytest.raises(cm.MigrationRefused, match="already a file"):
            cm.take_verified_backup(con, a, taken)
    finally:
        con.close()
    assert hashlib.sha256(taken.read_bytes()).hexdigest() == digest and not list(taken.parent.glob("*.partial"))


def test_a_file_that_appears_between_the_check_and_the_publish_is_not_replaced(tmp_path, monkeypatch):
    """The name was free when it was checked and is taken by the time the copy is published: the hard link fails rather than
    replace it (a plain rename would have)."""
    a = _new_store(tmp_path / "a.db", articles=12)
    dest = tmp_path / "bk" / "late.db"
    real = os.link

    def late(src, dst, *args, **kwargs):
        if Path(dst) == dest:
            dest.write_bytes(b"theirs")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(cm.os, "link", late)
    con = _live(a)
    try:
        with pytest.raises(cm.MigrationRefused, match="already a file"):
            cm.take_verified_backup(con, a, dest)
    finally:
        con.close()
    assert dest.read_bytes() == b"theirs" and not list(dest.parent.glob("*.partial"))


def test_a_file_system_without_hard_links_still_publishes_the_copy_and_still_refuses_a_taken_name(tmp_path, monkeypatch):
    import errno

    a = _new_store(tmp_path / "a.db", articles=12)
    real = os.link
    state = {"mode": "nolinks"}
    dest = tmp_path / "bk" / "plain.db"

    def link(src, dst, *args, **kwargs):
        if Path(dst) != dest:
            return real(src, dst, *args, **kwargs)
        if state["mode"] == "taken":
            dest.write_bytes(b"theirs")
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(cm.os, "link", link)
    con = _live(a)
    try:
        info = cm.take_verified_backup(con, a, dest)
        assert Path(info.path) == dest and dest.stat().st_size > 100 and not list(dest.parent.glob("*.partial"))
        dest.unlink()
        state["mode"] = "taken"
        with pytest.raises(cm.MigrationRefused, match="already a file"):
            cm.take_verified_backup(con, a, dest)
    finally:
        con.close()
    assert dest.read_bytes() == b"theirs" and not list(dest.parent.glob("*.partial"))


def test_a_place_that_cannot_be_examined_is_refused_by_class_and_never_read_as_free(tmp_path):
    a = _new_store(tmp_path / "a.db", articles=12)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder should be", encoding="utf-8")
    con = _live(a)
    try:
        with pytest.raises(cm.MigrationRefused) as caught:
            cm.take_verified_backup(con, a, blocker / "x.db")
    finally:
        con.close()
    assert "could not be examined (NotADirectoryError)" in str(caught.value) and "Nothing was changed" in str(caught.value)
    assert caught.value.__suppress_context__ and caught.value.__cause__ is None, "the OS error's text would reach the operator"
    assert cf.read_form(sqlite3.connect(a)) == "alpha2"


def test_a_relative_backup_folder_is_journalled_as_an_absolute_path(tmp_path, monkeypatch):
    db = _new_store(tmp_path / "s.db")
    monkeypatch.chdir(tmp_path)
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 2

    asked: list[Path] = []
    real = cm.take_verified_backup
    monkeypatch.setattr(cm, "take_verified_backup", lambda con, db_path, dest: asked.append(dest) or real(con, db_path, dest))
    rep = cm.migrate(db, backup_dir=Path("relbk"), should_stop=stop)
    assert rep.state == "interrupted" and Path(rep.backup["path"]).is_absolute()
    assert asked and asked[0].is_absolute(), "the folder was handed on relative: only the copy's own resolve saved the journal"
    monkeypatch.setattr(cm, "take_verified_backup", real)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cm.migrate(db, backup_dir=Path("relbk")).state == "done", "a resume from another folder lost its own safety copy"


def test_a_copy_asked_for_by_a_relative_path_reports_an_absolute_one(tmp_path, monkeypatch):
    db = _new_store(tmp_path / "s.db", articles=12)
    monkeypatch.chdir(tmp_path)
    con = _live(db)
    try:
        info = cm.take_verified_backup(con, db, Path("rel") / "copy.db")
    finally:
        con.close()
    assert Path(info.path).is_absolute() and Path(info.path).exists()


def test_a_copy_killed_midway_leaves_no_file_with_the_safety_copys_name(tmp_path, monkeypatch):
    from src.database import connect as dbc

    db = _new_store(tmp_path / "s.db")

    def killed(_con, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"SQLite format 3\x00 truncated")
        raise KeyboardInterrupt  # what a kill looks like to the code that is left: nothing cleans up after it

    monkeypatch.setattr(dbc, "snapshot_open_connection", killed)
    with pytest.raises(KeyboardInterrupt):
        cm.migrate(db, backup_dir=tmp_path / "bk")
    assert not list((tmp_path / "bk").glob("*.pre-country-form-*.db")), "a truncated file wears the name an operator would restore from"
    monkeypatch.undo()
    assert cm.migrate(db, backup_dir=tmp_path / "bk").state == "done"
    assert len(list((tmp_path / "bk").glob("*.pre-country-form-*.db"))) == 1


def test_a_store_the_app_creates_is_alpha3_even_when_the_settings_table_exists_first(tmp_path):
    """``app_state`` alone is not a corpus: a setting written before the first boot reaches ``init_db`` must not make the new
    store look like somebody's pre-existing alpha-2 corpus."""
    data = tmp_path / "state"
    data.mkdir()
    con = sqlite3.connect(data / "open_omniscience.db")
    con.execute('CREATE TABLE "app_state" (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)')
    con.execute("INSERT INTO app_state VALUES ('some.setting', '{}', NULL)")
    con.commit()
    con.close()
    assert _boot_init_db(data).stdout.strip().endswith("booted")
    con = sqlite3.connect(data / "open_omniscience.db")
    try:
        assert cf.read_form(con) == "alpha3"
    finally:
        con.close()


# ---- the encrypted path --------------------------------------------------------------------------------------- #
def test_an_encrypted_store_is_migrated_under_its_key_and_its_safety_copy_stays_ciphertext(tmp_path, monkeypatch):
    from src.database import connect as dbc

    if not dbc.have_driver():
        pytest.skip("no SQLCipher driver in this environment")
    plain = _new_store(tmp_path / "plain.db")
    enc = dbc.reencrypt_plain_to(plain, tmp_path / "enc.db", "correct horse battery staple")
    monkeypatch.setattr(dbc, "_passphrase", "correct horse battery staple")
    assert dbc.is_encrypted_file(enc)
    rep = cm.migrate(enc, backup_dir=tmp_path / "bk")
    assert rep.state == "done", rep.message
    copy = Path(rep.backup["path"])
    assert dbc.is_encrypted_file(copy), "the safety copy of an encrypted store must be encrypted"
    con = dbc.connect(enc, check_same_thread=False)
    try:
        assert cf.read_form(con) == "alpha3"
        assert con.execute("SELECT COUNT(*) FROM articles WHERE country IN ('fr','FR')").fetchone()[0] == 0
    finally:
        con.close()
    back = dbc.connect(copy, check_same_thread=False)
    try:
        assert back.execute("SELECT COUNT(*) FROM articles WHERE country = 'fr'").fetchone()[0] > 0
        assert cf.read_form(back) == "alpha2"
    finally:
        back.close()
    assert "correct horse" not in json.dumps(rep.__dict__, default=str)


# ---- one list of columns ---------------------------------------------------------------------------------------- #
def test_the_migration_covers_exactly_the_typed_columns_and_every_registered_one():
    from src.backup.country_codes import COUNTRY_COLUMNS, COUNTRY_COLUMNS_EXEMPT

    typed = set(cm.migration_columns())
    registered = {(t, c) for t, cols in COUNTRY_COLUMNS.items() for c in cols}
    assert registered <= typed, f"a column the restore normalises is not migrated: {sorted(registered - typed)}"
    extra = typed - registered
    assert not extra, f"a typed column nobody classified: {sorted(extra)}"
    exempt = {tuple(k.split(".", 1)) for k in COUNTRY_COLUMNS_EXEMPT}
    assert not (typed & exempt), "an exempt column is typed and would be rewritten"


# ---- the column type ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("form, stored", [("alpha2", {"fr": "fr", "FR": "FR", "FRA": "FRA", "uk": "uk"}),
                                          ("alpha3", {"fr": "FRA", "FR": "FRA", "FRA": "FRA", "uk": "uk", "WLD": "WLD", "": "", "xx": "xx"})])
def test_a_value_is_written_in_the_form_the_store_holds(monkeypatch, form, stored):
    monkeypatch.setattr(cf, "store_form", lambda: form)
    t = cf.CountryCode(8)
    for given, want in stored.items():
        assert t.process_bind_param(given, None) == want, (form, given)
    assert t.process_bind_param(None, None) is None


def test_a_value_is_read_back_as_alpha2_and_what_has_no_meaning_is_not_touched():
    t = cf.CountryCode(8)
    assert [t.process_result_value(v, None) for v in ("FRA", "fra", "fr", "uk", "int", "eu", "WLD", None, "")] == [
        "fr", "fr", "fr", "uk", "int", "eu", "WLD", None, ""]


def test_an_unreadable_store_form_stops_a_write_instead_of_assuming_alpha2(monkeypatch):
    from src.config import kv_store

    def boom(_k):
        raise kv_store.KvReadError("OperationalError")

    monkeypatch.setattr(kv_store, "kv_get_json_checked", boom)
    with pytest.raises(cf.StoreFormUnreadable):
        cf.CountryCode(8).process_bind_param("fr", None)


def _cli(data_dir: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "OO_DATA_DIR": str(data_dir), "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1", "OO_AUTOSEED": "0"}
    env.pop("DATABASE_URL", None)
    code = "import sys; sys.argv = ['open-omniscience', *sys.argv[1:]]; from src.api.main import main; main()"
    return subprocess.run([sys.executable, "-c", code, "migrate-countries", *args], cwd=ROOT, env=env, input=stdin,
                          capture_output=True, text=True, timeout=240)


def test_the_console_command_estimates_asks_and_migrates_the_store_it_is_pointed_at(tmp_path):
    data = tmp_path / "state"
    data.mkdir()
    db = _new_store(data / "open_omniscience.db")
    est = _cli(data, "--estimate", "--backup-dir", str(tmp_path / "bk"))
    assert est.returncode == 0, est.stderr[-1500:]
    assert "Rows to rewrite" in est.stdout and cf.read_form(sqlite3.connect(db)) == "alpha2"
    declined = _cli(data, "--backup-dir", str(tmp_path / "bk"), stdin="no\n")
    assert cf.read_form(sqlite3.connect(db)) == "alpha2" and not (tmp_path / "bk").exists(), declined.stdout[-800:]
    done = _cli(data, "--yes", "--backup-dir", str(tmp_path / "bk"))
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-1500:]
    assert cf.read_form(sqlite3.connect(db)) == "alpha3" and _column(db, "law_documents", "jurisdiction")["FRA"] == 1
    assert any((tmp_path / "bk").iterdir()), "the safety copy must exist"


def _add_alternates(db: Path) -> None:
    con = sqlite3.connect(db)
    for ident in ('{"jurisdiction":"fr","document_url":"u1","model":"m"}', '{"jurisdiction":"uk","document_url":"u2","model":"m"}'):
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
            " VALUES (1, 'law_revision_summaries', ?, 1, '{\"summary\":\"s\"}', '{}', 'o', 'pending', '2026-09-01')", (ident,))
    con.commit()
    con.close()


def test_a_code_with_no_alpha3_inside_a_recorded_difference_is_left_and_named_in_the_report(tmp_path):
    db = _new_store(tmp_path / "s.db")
    _add_alternates(db)
    rep = cm.migrate(db, backup_dir=tmp_path / "bk")
    assert rep.state == "done", rep.message
    assert rep.alternates["converted"] == 1
    assert rep.alternates["left_as_stored"] == {"law_revision_summaries.identity.jurisdiction": {"uk": 1}}
    con = sqlite3.connect(db)
    try:
        idents = sorted(json.loads(r[0])["jurisdiction"] for r in con.execute("SELECT identity FROM metadata_alternates"))
    finally:
        con.close()
    assert idents == ["FRA", "uk"], "R100: what has no ISO meaning stays exactly as stored"


def test_the_console_command_names_what_it_left_inside_recorded_differences(tmp_path):
    data = tmp_path / "state"
    data.mkdir()
    db = _new_store(data / "open_omniscience.db")
    _add_alternates(db)
    done = _cli(data, "--yes", "--backup-dir", str(tmp_path / "bk"))
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-1500:]
    assert "Left exactly as stored inside recorded differences" in done.stdout
    assert "law_revision_summaries.identity.jurisdiction: 'uk' x1" in done.stdout


def test_the_diagnostics_card_reads_the_form_and_the_estimate_and_starts_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/diagnostics/country-form")
        assert r.status_code == 200, r.text
        body = r.json()
        # a store the app created is stamped alpha-3 at birth, and says it was not migrated
        assert body["form"] == "alpha3" and body["readable"] and body["migrated"] is False
        assert body["command"] == "open-omniscience migrate-countries"
        est = client.get("/api/diagnostics/country-form?estimate=true").json()
        assert est["estimate"] is not None and ("rows_to_rewrite" in est["estimate"] or "refused" in est["estimate"])
        monkeypatch.setattr(cf, "store_form", lambda: (_ for _ in ()).throw(cf.StoreFormUnreadable("x")))
        down = client.get("/api/diagnostics/country-form").json()
        assert down["readable"] is False and down["form"] is None, "an unreadable form is never reported as alpha-2"


def test_the_diagnostics_page_wires_the_card_to_the_route():
    html = (ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "static" / "app-diagnostics.js").read_text(encoding="utf-8")
    assert 'id="country-form-out"' in html and html.count("loadCountryForm(this,") == 2
    assert "/api/diagnostics/country-form" in js and "_countryFormTicket" in js


def test_a_listing_ordered_by_country_comes_back_in_the_same_order_in_both_forms(tmp_path):
    """AUS sorts before AUT where `at` sorts before `au`: ordering by the stored text would reorder an alpha-3 store's
    listings, a payload change B1 promises not to make (the order is the Python side's alpha-2 in either form)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from src.database.models import Source

    orders = {}
    for form in ("alpha2", "alpha3"):
        eng = create_engine(f"sqlite:///{tmp_path / (form + '.db')}", future=True)
        Source.metadata.create_all(eng)
        with cf.writing_in(form), Session(eng) as s:
            for i, cc in enumerate(["au", "at", "ch", "cn", "gb", "uk", None, "de"]):
                s.add(Source(name=f"s{i}", domain=f"s{i}.example", country=cc))
            s.commit()
            orders[form] = [r.country for r in s.execute(select(Source).order_by(cf.alpha2_order(Source.country), Source.id)).scalars()]
        eng.dispose()
    assert orders["alpha2"] == orders["alpha3"] == [None, "at", "au", "ch", "cn", "de", "gb", "uk"]
    keys = [cf.order_key(v, i) for i, v in enumerate(["b", None, "a"])]
    assert [k[2] for k in sorted(keys)] == [1, 2, 0], "NULL first, then the value, as ORDER BY does"


# --------------------------------------------------------------------------- #
#  Folded from the coordinator's read of the B1 fold (CHECK-2 lows 1, 4, 5), carried by B2
# --------------------------------------------------------------------------- #
def test_a_dangling_link_where_the_journalled_copy_was_is_not_a_copy(tmp_path):
    """LOW 1. The journal check asks "is the copy still THERE", and a link to nowhere is not a copy: followed (``stat``) it
    reads absent, so the resume refuses ("its safety copy is gone") instead of going on to report a verified copy that is
    not there. The no-replace check asks "is this NAME taken", and there a dangling link IS taken (``lstat``)."""
    link = tmp_path / "copy.db"
    os.symlink(tmp_path / "nowhere.db", link)
    assert cm._path_exists(link, follow=True) is False
    assert cm._path_exists(link) is True


def test_a_resume_whose_journalled_copy_is_a_dangling_link_refuses(tmp_path):
    db = _new_store(tmp_path / "s.db")
    _kill_child(db, tmp_path / "bk", "between-windows", 3)
    for f in list((tmp_path / "bk").glob("*.db")):
        f.unlink()
        os.symlink(tmp_path / "nowhere.db", f)
    with pytest.raises(cm.MigrationRefused, match="safety copy is gone"):
        cm.migrate(db, backup_dir=tmp_path / "bk")


def test_the_refusal_for_a_resume_does_not_tell_the_operator_to_pass_a_backup_folder(tmp_path, monkeypatch):
    """The journal check's own advice: a resume has no ``--backup-dir`` to change."""

    def broken(path, *args, **kwargs):
        raise PermissionError(13, "no")

    monkeypatch.setattr(cm.os, "stat", broken)
    with pytest.raises(cm.MigrationRefused) as caught:
        cm._path_exists(tmp_path / "x", follow=True, hint="Put the safety copy back where the journal says it was.")
    assert "PermissionError" in str(caught.value) and "Put the safety copy back" in str(caught.value)
    assert "--backup-dir" not in str(caught.value) and caught.value.__cause__ is None


class _RaisingCon:
    """A connection whose catalogue read fails the way a damaged or locked file's does."""

    def execute(self, *args, **kwargs):
        raise sqlite3.DatabaseError("disk I/O error")


def test_unreadable_is_not_absent_for_the_journal_and_the_form_marker():
    """LOW 5. Both readers ask the schema whether ``app_state`` exists; a read that FAILS must raise, not answer "no journal" or
    "alpha-2" (which would let a half-migrated store be opened as a finished one)."""
    with pytest.raises(sqlite3.DatabaseError):
        cm.read_journal(_RaisingCon())
    with pytest.raises(sqlite3.DatabaseError):
        cf.read_form_in(_RaisingCon(), "main")


def test_a_copy_that_cannot_be_published_under_its_final_name_is_refused_by_class_and_leaves_no_partial(tmp_path, monkeypatch):
    """LOW 5 (the cosmetic half): on a file system with no hard links the fallback renames; when that rename fails the half-named
    file is removed and the operator gets the class, not a raw traceback."""
    import errno

    a = _new_store(tmp_path / "a.db", articles=12)
    dest = tmp_path / "bk" / "plain.db"

    def no_link(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, "no hard links here")

    def no_replace(src, dst, *args, **kwargs):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(cm.os, "link", no_link)
    monkeypatch.setattr(cm.os, "replace", no_replace)
    con = _live(a)
    try:
        with pytest.raises(cm.MigrationRefused) as caught:
            cm.take_verified_backup(con, a, dest)
    finally:
        con.close()
    assert "OSError" in str(caught.value) and "cross-device" not in str(caught.value)
    assert caught.value.__cause__ is None and not dest.exists() and not list(dest.parent.glob("*.partial"))


def test_the_unfinished_message_says_how_to_put_the_safety_copy_back():
    """LOW 4. "Can be put back" with no step is an instruction nobody can follow: there is no restore command for a raw copy."""
    text = cf.unfinished_message("interrupted", "/tmp/x/copy.db")
    assert "/tmp/x/copy.db" in text
    assert "copy that file over the store file" in text and "-wal and -shm" in text

"""The -wal reading must be taken before anything can destroy it (S0.1 + S0.4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT THESE GUARD (2026-09-02). ``wal_state_before_open`` was called from the
unlock timer, which runs AFTER ``unlock()`` has already verified the passphrase with
its own ``connect()``/``close()``. SQLite checkpoints and unlinks the -wal on the last
close, so on an encrypted store the probe answered ``absent`` whatever the previous
session had left — and three places read that ``absent`` as "the previous shutdown was
clean". The only field that appeared to answer "did the last session end cleanly" was
an artifact of its own measurement order.

The fix moves the load-bearing reading to ``record_session_start()``, which the lifespan
calls at boot before any connection can exist. That placement also covers the case a
reorder INSIDE ``unlock()`` cannot: a wrong-passphrase attempt opens a connection too,
so every retry after the first would still have been blind.

Isolation: every test points OO_DATA_DIR at tmp_path and resets the module's boot
capture — never the shared process data dir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from src.monitoring import forensics, session_hwm


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(forensics, "_WAL_AT_BOOT", None)
    session_hwm.reset_for_tests()
    return tmp_path


def _leave_a_wal(db_path) -> int:
    """Write a WAL-mode store in a SUBPROCESS that dies without closing, so a real
    -wal survives. Returns its size. This is the portable mechanism pin — no
    sqlcipher3, no app, just SQLite's own behaviour."""
    code = (
        "import sqlite3,sys,os\n"
        f"c=sqlite3.connect({str(db_path)!r})\n"
        "c.execute('PRAGMA journal_mode=WAL')\n"
        "c.execute('CREATE TABLE t(x)')\n"
        "c.executemany('INSERT INTO t VALUES(?)',[(i,) for i in range(4000)])\n"
        "c.commit()\n"
        "os._exit(0)\n"  # never closes: the -wal is left on disk
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    return os.path.getsize(str(db_path) + "-wal")


def test_a_crashed_store_leaves_a_wal_and_a_verify_read_destroys_it(dd):
    """The premise the whole slice rests on, MEASURED rather than assumed — and it is
    narrower than "one connect/close": Python's sqlite3 opens the file lazily, so a
    bare connect+close leaves the -wal alone. It is a connection that TOUCHES the
    database that checkpoints and unlinks it on close.

    That distinction is not academic: the production verify runs
    ``SELECT 1 FROM sqlite_master LIMIT 1`` (src/database/connect.py) precisely to
    prove the key works, so the real path is squarely in the destructive case. Both
    halves are pinned here so a future reader does not "simplify" the fixture into a
    bare connect and watch this pass for the wrong reason."""
    import sqlite3

    db = dd / "open_omniscience.db"
    size = _leave_a_wal(db)
    assert size > 0, "the subprocess should have left a -wal"
    assert forensics.wal_state_before_open()["state"] == "present"

    # A bare connect+close does NOT destroy it (lazy open) ...
    sqlite3.connect(str(db)).close()
    assert (dd / "open_omniscience.db-wal").exists()

    # ... but the read the passphrase verify actually performs does.
    con = sqlite3.connect(str(db))
    con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    con.close()
    assert not (dd / "open_omniscience.db-wal").exists()
    assert forensics.wal_state_before_open()["state"] == "absent"


def _verify_read(db) -> None:
    """Exactly what the production passphrase verify does to the store."""
    import sqlite3

    con = sqlite3.connect(str(db))
    con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    con.close()


def test_the_boot_read_captures_a_present_wal_before_anything_opens_the_store(dd):
    db = dd / "open_omniscience.db"
    size = _leave_a_wal(db)

    forensics.record_session_start()

    got = forensics.wal_at_boot()
    assert got is not None
    assert got["state"] == "present"
    assert got["bytes"] == size > 0
    # and it is persisted, so the next export carries it even after a probe
    persisted = json.loads((dd / "session_state.json").read_text(encoding="utf-8"))
    assert persisted["wal_at_boot"]["state"] == "present"


def test_a_later_probe_cannot_overwrite_the_boot_reading(dd):
    """MUTATION TARGET. Read the boot value AFTER a connection has destroyed the
    evidence: the reported state must still be the boot one. Restore the old order
    (take the reading in the unlock timer) and this is `absent`."""
    db = dd / "open_omniscience.db"
    _leave_a_wal(db)
    forensics.record_session_start()

    _verify_read(db)  # the verify connection
    assert forensics.wal_state_before_open()["state"] == "absent"  # the artifact
    assert forensics.wal_at_boot()["state"] == "present"  # the fact

    rep = forensics.previous_session_report()
    assert rep["wal_at_boot"]["state"] == "present"


def test_the_boot_read_happens_before_the_state_file_is_touched(dd):
    """Call-ORDER guard (cheap, always runs). The probe must come first: anything
    between it and a database open is where a future edit would reintroduce the bug."""
    order: list[str] = []
    real_probe = forensics.wal_state_before_open
    real_write = forensics._write_state

    def probe():
        order.append("probe")
        return real_probe()

    def write(state):
        order.append("write")
        return real_write(state)

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(forensics, "wal_state_before_open", probe)
        monkey.setattr(forensics, "_write_state", write)
        forensics.record_session_start()
    finally:
        monkey.undo()
    assert order and order[0] == "probe", f"probe must run first, got {order}"


def test_a_clean_close_still_reads_absent_the_fix_never_manufactures_a_present(dd):
    """NEGATIVE TWIN. The fix moves WHEN the reading is taken; it must not invent one.
    A genuinely clean close leaves no -wal and the boot read must say so."""
    import sqlite3

    db = dd / "open_omniscience.db"
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()  # clean: SQLite checkpoints and removes the -wal
    assert not (dd / "open_omniscience.db-wal").exists()

    forensics.record_session_start()
    got = forensics.wal_at_boot()
    assert got["state"] == "absent"
    assert got["bytes"] == 0


def test_absent_no_longer_claims_the_previous_shutdown_was_clean(dd):
    """The honesty half. 'absent' is produced equally by a clean close, a
    wrong-passphrase attempt and an earlier probe, so the reason text must not
    assert a clean shutdown."""
    reason = forensics.wal_state_before_open()["reason"].lower()
    assert "clean shutdown checkpoints and removes it" not in reason
    assert "nothing can be concluded" in reason


def test_the_unlock_timer_takes_no_reading_of_its_own(dd):
    """The timer must use the caller's reading. A timer that probes for itself is
    probing after the verify connection — the original defect."""
    from src.api.unlock import _forensic_timer

    calls: list[str] = []
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            forensics,
            "wal_state_before_open",
            lambda: calls.append("probe") or {"bytes": 1, "state": "present", "reason": "x"},
        )
        t = _forensic_timer(wal_state={"bytes": 4096, "state": "present", "reason": "handed in"})
    finally:
        monkey.undo()
    assert calls == [], "the timer must not probe; the caller hands the reading in"
    assert t._wal == 4096

    # and with nothing handed in it says so rather than reporting a zero or a clean boot
    t2 = _forensic_timer()
    assert t2._wal is None
    assert t2._wal_state["state"] == "not-measured"


def test_the_verify_phase_is_reported_and_the_total_reproduces_it(dd):
    """S0.1(c). The field's S3 boot spent 24.7 s outside every timed phase, inside the
    verify connect/close. It must appear as its own phase AND be inside the total —
    a phase list that does not add up to its own total is worse than none."""
    from src.api.unlock import _forensic_timer

    t = _forensic_timer(wal_state={"bytes": 0, "state": "absent", "reason": "x"})
    t.add_phase("passphrase verify + WAL recovery + checkpoint-on-close", 24_700.0)
    t.phase("init_db")
    forensics.record_session_start()
    t.finish()

    rec = forensics.session_forensics()["last_unlock"]
    names = [p["phase"] for p in rec["phases"]]
    assert any("passphrase verify" in n for n in names)
    listed = sum(p["ms"] for p in rec["phases"])
    assert rec["synchronous_total_ms"] >= 24_700.0
    # the total must not be smaller than the phases it lists
    assert rec["synchronous_total_ms"] + 0.5 >= listed


# --------------------------------------------------------------------------- #
#  S0.4 — the previous session's OWN numbers
# --------------------------------------------------------------------------- #


def test_previous_peaks_come_from_the_previous_session_not_this_one(dd):
    # session 1 records its peaks and dies
    session_hwm.capture_previous()
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            session_hwm,
            "_readings",
            lambda: {"rss_mb": 6767.0, "avail_mb": 94.0, "swap_used_mb": 3100.0},
        )
        session_hwm.observe(phase="collecting (pass p1)")
        session_hwm.flush()
    finally:
        monkey.undo()

    # session 2 boots and immediately reports much smaller numbers
    session_hwm.reset_for_tests()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    session_hwm.capture_previous()
    monkey2 = pytest.MonkeyPatch()
    try:
        monkey2.setattr(
            session_hwm, "_readings", lambda: {"rss_mb": 120.0, "avail_mb": 3000.0}
        )
        session_hwm.observe(phase="idle")
    finally:
        monkey2.undo()

    peaks = session_hwm.previous()
    assert peaks["rss_max_mb"] == 6767.0, "the CRASHED session's peak, not this one's"
    assert peaks["avail_min_mb"] == 94.0
    assert peaks["swap_used_max_mb"] == 3100.0
    assert peaks["phase"] == "collecting (pass p1)"


def test_an_unmeasurable_field_is_omitted_never_written_as_zero(dd):
    """MUTATION TARGET. `rss_max_mb: 0` reads as 'the process used no memory', the
    opposite of unmeasured. Write a 0 for an unreadable field and this reddens."""
    session_hwm.capture_previous()
    monkey = pytest.MonkeyPatch()
    try:
        # psutil present but swap unreadable: two fields measured, one absent
        monkey.setattr(session_hwm, "_readings", lambda: {"rss_mb": 500.0, "avail_mb": 900.0})
        session_hwm.observe(phase="collecting")
        session_hwm.flush()
    finally:
        monkey.undo()
    marks = session_hwm.current()
    assert marks["rss_max_mb"] == 500.0
    assert "swap_used_max_mb" not in marks, "an unmeasured field is ABSENT, never 0"

    # and with NO readings at all, no mark is invented
    session_hwm.reset_for_tests()
    session_hwm.capture_previous()
    monkey2 = pytest.MonkeyPatch()
    try:
        monkey2.setattr(session_hwm, "_readings", dict)
        session_hwm.observe(phase="collecting")
    finally:
        monkey2.undo()
    marks2 = session_hwm.current()
    assert "rss_max_mb" not in marks2 and "avail_min_mb" not in marks2


def test_the_report_states_that_collect_perf_may_belong_to_this_session(dd):
    """The attribution the absence of which produced an OOM inference from the wrong
    process's numbers."""
    forensics.record_session_start()
    (dd / "collect_perf.jsonl").write_text(
        json.dumps({"ts": "t2", "rss_mb": 10599.8, "mem_avail_mb": 42.0}) + "\n",
        encoding="utf-8",
    )
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unclean-end"
    assert "attribution" in rep["last_collector_sample"]
    assert "not the previous one" in rep["last_collector_sample"]["attribution"].lower()
    assert "previous_session_peaks" in rep


def test_absent_peaks_are_stated_not_silently_dropped(dd):
    forensics.record_session_start()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    session_hwm.reset_for_tests()
    rep = forensics.previous_session_report()
    peaks = rep["previous_session_peaks"]
    assert peaks["available"] is False
    assert "unmeasured" in peaks["reason"]


def test_render_text_prints_the_boot_wal_and_the_previous_peaks(dd):
    """S0.4's own note: a fix invisible in the .txt the maintainer sends is not a fix."""
    db = dd / "open_omniscience.db"
    _leave_a_wal(db)
    session_hwm.capture_previous()
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(session_hwm, "_readings", lambda: {"rss_mb": 2112.0, "avail_mb": 88.0})
        session_hwm.observe(phase="pass tail: hygiene:checkpoint")
        session_hwm.flush()
    finally:
        monkey.undo()
    session_hwm.reset_for_tests()
    forensics.record_session_start()  # session 1 (running)
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()  # session 2 sees an unclean end
    session_hwm.capture_previous()

    txt = forensics.render_text()
    assert "-wal at this boot: present" in txt
    assert "peak RSS: 2112.0 MB" in txt
    assert "minimum available memory: 88.0 MB" in txt
    assert "peak swap used: not measured" in txt  # omitted, stated, never 0
    assert "pass tail: hygiene:checkpoint" in txt

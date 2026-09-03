"""Session forensics + data-dir inventory (the 2026-07-09 automate-the-asks slice).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards the three automated answers: (1) the data-dir inventory names the disk
usage and detects orphaned plaintext backup staging; (2) the clean-shutdown
sentinel yields an honest previous-session verdict (unclean-end + the collector's
last RSS = the OOM inference, labelled an inference); (3) the unlock timing record
round-trips. Isolation: every test monkeypatches OO_DATA_DIR to tmp_path — never
the shared process data dir, never SessionLocal.
"""

from __future__ import annotations

import json

import pytest

from src.monitoring import forensics


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # reset the module's boot-capture so each test sees a fresh boot
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    return tmp_path


def _no_score_keys(obj, path=""):
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(w in lk for w in ("score", "ranking", "rating")):
                bad.append(f"{path}.{k}")
            bad += _no_score_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += _no_score_keys(v, f"{path}[{i}]")
    return bad


def test_inventory_sizes_db_wal_and_orphaned_staging(dd):
    (dd / "open_omniscience.db").write_bytes(b"x" * 5000)
    (dd / "open_omniscience.db-wal").write_bytes(b"w" * 3000)
    (dd / "wiki_dumps").mkdir()
    (dd / "wiki_dumps" / "en.bz2").write_bytes(b"d" * 700)
    # a crashed backup's staging dir WITH a plaintext corpus snapshot inside
    stag = dd / ".bak-build-deadbeef"
    stag.mkdir()
    (stag / "corpus.db").write_bytes(b"p" * 9000)
    # a crashed restore staging without one, and a folder-backup part temp
    (dd / ".restore-cafef00d").mkdir()
    (dd / "region.pbf.oopart").write_bytes(b"t" * 100)

    inv = forensics.data_dir_inventory()
    t = inv["totals"]
    assert t["db_bytes"] == 5000 and t["wal_bytes"] == 3000
    assert t["orphaned_staging_bytes"] == 9100  # bak-build 9000 + oopart 100
    assert t["total_bytes"] == 5000 + 3000 + 700 + 9000 + 100
    names = {s["name"]: s for s in inv["suspect_staging"]}
    assert names[".bak-build-deadbeef"]["plaintext_snapshot"] is True
    assert names[".restore-cafef00d"]["plaintext_snapshot"] is False
    assert "region.pbf.oopart" in names
    # the plaintext hazard is stated in the method, and no score-like key anywhere
    assert "plaintext" in inv["method"].lower()
    assert _no_score_keys(inv) == []


def test_inventory_never_follows_a_symlink_out_of_the_data_dir(dd, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "huge.bin").write_bytes(b"z" * 50_000)
    (dd / "open_omniscience.db").write_bytes(b"x" * 10)
    try:
        (dd / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this filesystem")
    inv = forensics.data_dir_inventory()
    # the outside tree is a pointer, not data held here — its bytes never counted
    assert inv["totals"]["total_bytes"] == 10


def test_inventory_on_an_empty_or_recreated_data_dir_never_raises(dd):
    # data_dir() self-creates (src/paths.py), so a removed dir comes back empty —
    # the inventory must return an honest empty result, never raise.
    import shutil

    shutil.rmtree(dd)
    inv = forensics.data_dir_inventory()
    assert inv["entries"] == [] and inv["suspect_staging"] == []
    assert inv["totals"]["total_bytes"] == 0


def test_sentinel_reports_an_unclean_end_with_the_last_rss_sample(dd):
    # session 1 boots and DIES (no clean shutdown); the collector recorded RSS
    forensics.record_session_start()
    (dd / "collect_perf.jsonl").write_text(
        json.dumps({"ts": "t1", "rss_mb": 100.0}) + "\n"
        + json.dumps({"ts": "t2", "rss_mb": 10599.8, "mem_avail_mb": 42.0,
                      "elapsed_s": 77885.3, "pass_id": "p"}) + "\n",
        encoding="utf-8",
    )
    # session 2 boots: the module re-reads the sentinel as a fresh boot
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unclean-end"
    assert rep["last_collector_sample"]["rss_mb"] == 10599.8
    # the OOM wording is an INFERENCE, stated as such — never asserted as fact
    assert "inference" in rep["method"].lower()
    assert _no_score_keys(rep) == []


def test_sentinel_reports_a_clean_end_without_the_oom_block(dd):
    forensics.record_session_start()
    forensics.record_clean_shutdown()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "clean"
    assert "last_collector_sample" not in rep  # no OOM inference on a clean end


def test_first_boot_reports_unknown_not_a_guess(dd):
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unknown"


def test_unlock_timing_round_trips_and_survives_the_next_boot(dd):
    forensics.record_session_start()
    forensics.record_unlock_timing(
        {"wal_bytes_before_open": 12345, "phases": [{"phase": "init_db", "ms": 981000.0}],
         "synchronous_total_ms": 981007.1}
    )
    got = forensics.session_forensics()["last_unlock"]
    assert got["wal_bytes_before_open"] == 12345
    assert got["phases"][0]["ms"] == 981000.0
    # a NEW boot carries the record forward so the next export still has it
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    assert forensics.session_forensics()["last_unlock"]["wal_bytes_before_open"] == 12345


def test_wal_bytes_before_open(dd):
    assert forensics.wal_bytes_before_open() is None  # honest None, never 0-guess
    (dd / "open_omniscience.db-wal").write_bytes(b"w" * 777)
    assert forensics.wal_bytes_before_open() == 777


def test_wal_state_before_open_separates_absent_from_unreadable(dd):
    """Three states, because 'no WAL' and 'could not read the WAL' are different
    facts and the P0.4 bar turns on which one happened.

    UPDATED DELIBERATELY 2026-09-02 (S0.1), not by reflex. This test used to assert
    that the 'absent' reason says "a clean shutdown checkpoints and removes it". That
    reading was false and load-bearing: ANY connection that touches the store
    checkpoints and unlinks the -wal on close -- including the passphrase-verify
    connection the unlock route opens before this probe ran, and including one opened
    by a WRONG-passphrase attempt. So 'absent' was produced on an encrypted store
    whatever had happened, and three places read it as evidence of a clean shutdown.
    The three states survive (they answer "what did this timing cover"); the clean-
    shutdown CLAIM is gone, and the forensic reading about the previous session is now
    taken at boot (record_session_start -> wal_at_boot), which is what
    tests/test_forensics_wal_at_boot.py guards.
    """
    absent = forensics.wal_state_before_open()
    assert absent["state"] == "absent"
    assert absent["bytes"] == 0  # a real measurement: nothing to replay
    assert "nothing can be concluded" in absent["reason"].lower()
    assert "clean shutdown checkpoints and removes it" not in absent["reason"]

    (dd / "open_omniscience.db-wal").write_bytes(b"w" * 777)
    present = forensics.wal_state_before_open()
    assert present == {"bytes": 777, "state": "present", "reason": present["reason"]}
    assert present["state"] == "present" and present["bytes"] == 777

    # The third state stays honestly unmeasured -- never coerced to 0, which would
    # claim there was no WAL when we simply could not look.
    import pathlib

    orig = pathlib.Path.stat

    def _boom(self, *a, **kw):
        # Targeted: only the -wal read fails, so the rest of pathlib keeps working.
        if self.name.endswith("-wal"):
            raise PermissionError("nope")
        return orig(self, *a, **kw)

    try:
        pathlib.Path.stat = _boom  # type: ignore[method-assign]
        unreadable = forensics.wal_state_before_open()
    finally:
        pathlib.Path.stat = orig  # type: ignore[method-assign]
    assert unreadable["state"] == "unreadable"
    assert unreadable["bytes"] is None


def test_endpoint_and_bundle_are_wired():
    # Source-level wiring guard (the composed-route lesson): the endpoint exists on
    # the diagnostics router, the debug bundle carries the block, and /all ships the
    # member — so the automation actually rides the exports the maintainer clicks.
    from pathlib import Path

    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    # Match the PATH, not the whole decorator line: it also carries response_model=None
    # (the handler returns a dict or a text Response), and an exact-line anchor would
    # break on any future kwarg while proving nothing more.
    assert '@router.get("/session-forensics"' in src
    # S8: every debug-bundle member is now individually guarded + budgeted via _member.
    assert '"session_forensics": _member("session_forensics", _session_forensics)' in src
    assert '"session-forensics.json", lambda: session_forensics_report(download=False)' in src
    assert '("session-forensics.txt", lambda: _session_forensics_text())' in src
    main = Path("src/api/main.py").read_text(encoding="utf-8")
    assert "record_session_start" in main and "record_clean_shutdown" in main
    unlock = Path("src/api/unlock.py").read_text(encoding="utf-8")
    assert "wal_bytes_before_open" in unlock and "record_unlock_timing" in unlock


# --------------------------------------------------------------------------- #
#  The text rendering (2026-08-23 field ask): a file an operator can send
# --------------------------------------------------------------------------- #
def test_render_text_states_every_absence_in_words(dd):
    """On a machine with no history there is nothing to report — and the renderer must
    SAY that rather than emit blanks or zeros, which is the whole convention it
    inherits from the expedition log."""
    out = forensics.render_text()
    assert out.startswith("# Open Omniscience — Session Forensics")
    assert "no unlock has been recorded" in out
    assert "orphaned backup/restore staging: none found" in out


def test_render_text_flags_orphaned_plaintext_staging_loudly(dd, monkeypatch):
    """An orphaned staging tree from an ENCRYPTED corpus holds a PLAINTEXT copy, so it
    is an at-rest-encryption finding. It must not read as a housekeeping line."""
    payload = forensics.session_forensics()
    payload["inventory"]["suspect_staging"] = [{"name": ".restore-abc", "bytes": 2 * 1024**3}]
    payload["inventory"]["totals"]["orphaned_staging_bytes"] = 2 * 1024**3
    out = forensics.render_text(payload)
    assert "ORPHANED STAGING" in out and "PLAINTEXT" in out and ".restore-abc" in out


def test_render_text_never_prints_an_unmeasured_size_as_zero(dd):
    """`0 B` and "we could not measure it" are different facts; collapsing them is the
    sentinel-sharing defect this project keeps paying for."""
    payload = forensics.session_forensics()
    payload["inventory"]["totals"]["wal_bytes"] = None
    assert "not measured" in forensics.render_text(payload)


def test_the_text_member_is_verbatim_and_the_json_member_is_still_json():
    """BEHAVIOURAL, not a source grep: `download` defaults to `Query(False)`, which is a
    truthy sentinel OBJECT when the route is called directly the way the bundle calls
    it — so a source-level check of the member list would pass while
    session-forensics.json quietly contained the TEXT."""
    from src.api.diagnostics import (
        _member_bytes,
        _session_forensics_text,
        session_forensics_report,
    )

    txt = _member_bytes(_session_forensics_text())
    assert txt.startswith(b"# Open Omniscience"), "the .txt member must be verbatim text"

    jsn = _member_bytes(session_forensics_report(download=False))
    assert jsn.startswith(b"{"), "the .json member must still be JSON, not the rendering"
    assert b"inventory" in jsn

    # ...and the trap itself, so the reason for the explicit argument cannot rot away.
    import inspect

    default = inspect.signature(session_forensics_report).parameters["download"].default
    assert bool(default) is True, (
        "Query(False) is expected to be a TRUTHY sentinel — this test exists because "
        "of that; if it ever becomes falsy the explicit download=False is still right, "
        "but this rationale needs rewriting rather than deleting."
    )


def test_the_download_is_a_dated_plain_text_attachment():
    from src.api.diagnostics import session_forensics_report

    r = session_forensics_report(download=True)
    assert r.media_type == "text/plain; charset=utf-8"
    cd = r.headers.get("content-disposition") or ""
    assert cd.startswith("attachment;") and cd.endswith('.txt"')
    assert r.body.startswith(b"# Open Omniscience")

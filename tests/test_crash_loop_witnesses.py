"""A crash loop must not erase its own evidence (findings D and E of instance 091717, 2026-10-01).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IS GUARDED. One instance had 9 unclean ends in 5 hours and the bundle explained only the
latest, for three reasons that had one shape (the app kept one session's evidence and reset it at
each boot):

  D. the crash trace of every EARLIER unclean end stayed on the machine: the bundle read the trace of
     the previous session's pid only, so two SIGABRT stacks were on disk and in no bundle;
  E. ``previous_peaks`` was null on 9 of 9 unclean ends (only the pre-ledger seed wrote it), and no
     boot record carried a build id, so an UPDATE read like a CRASH.

The negative space is the point: an absent trace says WHY by what the session ended by (a SIGKILL
leaves none, a SIGABRT without one is a gap); a pid reused after a reboot is never matched to the
wrong session; the marks are never dropped for size; marks of one session are never written onto
another's end; an install with no git says so instead of writing an empty head.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest

from src.monitoring import build_marker as bm
from src.monitoring import chronology as ch
from src.monitoring import exit_evidence as ee
from src.monitoring import forensics, session_hwm
from src.monitoring import session_history as sh

T0 = 1_700_000_000.0
BOOT_A = "11111111-aaaa-bbbb-cccc-000000000001"
BOOT_B = "22222222-aaaa-bbbb-cccc-000000000002"
HEADER = "=== open-omniscience session pid={pid} boot={boot} started={started} ==="


@pytest.fixture
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    bm.reset_process_markers_for_tests()
    (tmp_path / "data" / "diagnostics").mkdir(parents=True)
    yield tmp_path / "data"
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    bm.reset_process_markers_for_tests()


def _trace_log(dd: Path, body: str, name: str = "crash_trace.log") -> None:
    (dd / "diagnostics" / name).write_text(body, encoding="utf-8")


def _start(n: int) -> str:
    """When session ``n`` began, as its boot record says it."""
    return f"2026-09-30T{n % 24:02d}:00:00Z"


def _armed(n: int) -> str:
    """When session ``n`` armed its trace: first thing in ``_serve``, seconds before its boot record."""
    return f"2026-09-30T{(n % 24) - 1 if n % 24 else 0:02d}:59:40+00:00"


def _session(n: int, *, pid: int, boot: str = BOOT_A, clean=False, signal: str | None = "SIGKILL", exit_=None):
    """One session's boot and end ledger records."""
    sid = f"s{n:03d}"
    start = _start(n)
    end: dict = {"kind": "end", "session_id": sid, "at": f"2026-09-30T{n % 24:02d}:30:00Z", "clean": clean}
    if signal:
        end["exit"] = {"signal": signal, "status": 134 if signal == "SIGABRT" else 137, "kind": "crashed"}
    if exit_ is not None:
        end["exit"] = exit_
    return [
        {"kind": "boot", "session_id": sid, "at": start, "pid": pid, "machine_boot_id": boot},
        end,
    ]


def _header(pid: int, n: int, boot: str = BOOT_A) -> str:
    return HEADER.format(pid=pid, boot=boot, started=_armed(n))


def _trace(pid: int, n_lines: int, n: int, boot: str = BOOT_A, width: int = 100) -> str:
    """The log text of session ``n``'s crash: its header, then a fatal error and one thread's frames."""
    body = ["Fatal Python error: Aborted", "", "Thread 0x00007f (most recent call first):"]
    body += [f'  File "/app/src/x.py", line {i} in f{i}'.ljust(width, " ") for i in range(n_lines - 3)]
    return "\n" + _header(pid, n, boot) + "\n" + "\n".join(body) + "\n"


# --------------------------------------------------------------------------- #
#  D. the stack of every unclean end
# --------------------------------------------------------------------------- #
def test_every_earlier_unclean_end_reports_its_own_trace_and_the_previous_session_is_left_to_its_own_entry(dd):
    recs = []
    for n in range(1, 13):
        recs += _session(n, pid=1000 + n, signal="SIGABRT")
    recs += _session(13, pid=2000, clean=True, signal=None)         # a clean end is never listed
    recs += _session(14, pid=3000, signal="SIGKILL")                # the previous session
    log = "".join(_trace(1000 + n, 100, n) for n in range(1, 13)) + _trace(3000, 100, 14)
    _trace_log(dd, log)
    out = ee.earlier_unclean_ends({"pid": 3000, "boot_id": BOOT_A, "started_at": _start(14)}, records=recs)
    assert out["unclean_ends_in_ledger"] == 12 and out["shown"] == ee.EARLIER_ENDS_LIMIT == 10
    assert out["older_not_shown"] == 2
    pids = [r["pid"] for r in out["sessions"]]
    assert pids == [1012, 1011, 1010, 1009, 1008, 1007, 1006, 1005, 1004, 1003], "newest first, 10 only"
    assert 3000 not in pids and 2000 not in pids
    for row in out["sessions"]:
        t = row["trace"]
        assert t["summary"] == "Fatal Python error: Aborted"
        assert len(t["lines"]) == ee.EARLIER_TRACE_LINES == 60 and t["lines_total"] == 100
        assert "why_no_trace" not in row


def test_a_session_with_no_trace_says_why_by_what_it_ended_by(dd):
    recs = []
    recs += _session(1, pid=11, signal="SIGKILL")
    recs += _session(2, pid=12, signal="SIGABRT")                    # no header anywhere for pid 12
    recs += _session(3, pid=13, signal="SIGSEGV")                    # a header with nothing under it
    recs += _session(4, pid=14, signal="SIGTERM")
    recs += _session(5, pid=15, signal=None)
    _trace_log(dd, "\n" + _header(13, 3) + "\n\n" + _header(99, 3) + "\n")
    out = ee.earlier_unclean_ends(None, records=recs)
    why = {r["pid"]: r["why_no_trace"] for r in out["sessions"]}
    assert "a SIGKILL leaves no trace" in why[11]
    assert "SIGABRT, which leaves a trace, and the trace log holds no header" in why[12]
    assert "rotated away" in why[12] and "OO_CRASH_TRACE=0" in why[12]
    assert "SIGSEGV and the trace log holds this session's header with nothing under it" in why[13]
    assert "not a fault signal" in why[14]
    assert "launcher recorded no exit" in why[15] and "holds nothing for its pid" in why[15]
    assert all("status" not in r for r in out["sessions"]), "no exit seen, no status shown"
    assert all(r["trace"] is None for r in out["sessions"])


def test_a_pid_reused_at_another_boot_is_never_this_sessions_trace(dd):
    recs = _session(1, pid=500, boot=BOOT_A, signal="SIGABRT")
    _trace_log(dd, _trace(500, 20, 1, boot=BOOT_B))                  # the same pid, after a reboot
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert row["trace"] is None and "no header for this pid and boot" in row["why_no_trace"]
    _trace_log(dd, _trace(500, 20, 1, boot=BOOT_A))
    assert ee.earlier_unclean_ends(None, records=recs)["sessions"][0]["trace"] is not None


def test_the_rotated_generation_is_read_and_named(dd):
    recs = _session(1, pid=500, signal="SIGABRT")
    _trace_log(dd, _trace(900, 5, 1), "crash_trace.log")
    _trace_log(dd, _trace(500, 20, 1), "crash_trace.log.1")
    out = ee.earlier_unclean_ends(None, records=recs)
    assert out["sessions"][0]["trace"]["source"] == "crash_trace.log.1", "a file name, never the person's path"
    assert out["trace_log"]["bytes"] and out["trace_log"]["rotated_bytes"]


def test_a_session_whose_boot_record_was_compacted_away_is_named_not_dropped(dd):
    recs = [{"kind": "end", "session_id": "gone", "at": "2026-09-30T01:00:00Z", "clean": False}]
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert row["pid"] is None and "no longer holds this session's boot record" in row["why_no_trace"]


def test_the_signal_falls_back_to_the_launcher_record_when_the_end_line_has_none(dd):
    recs = _session(1, pid=77, signal=None)
    (dd / "diagnostics" / "launcher_exits.jsonl").write_text(
        json.dumps({"pid": 77, "boot_id": BOOT_A, "status": 134, "signal": "SIGABRT", "at": "x"}) + "\n", encoding="utf-8")
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert row["signal"] == "SIGABRT" and "SIGABRT" in row["why_no_trace"]


def test_the_member_stays_far_inside_one_r115_part_on_a_crash_loop(dd):
    """10 ends of 60 lines is what keeps the member small: about 60 KB, against a 1,000,000-byte part."""
    recs = []
    for n in range(1, 40):
        recs += _session(n, pid=100 + n, signal="SIGABRT")
    _trace_log(dd, "".join(_trace(100 + n, 4000, n, width=140) for n in range(1, 40)))
    out = ee.earlier_unclean_ends(None, records=recs)
    size = len(json.dumps(out))
    assert out["shown"] == 10 and size < 150_000, size
    assert size < 1_000_000 / 6, "a tenth of one part, with room for the member's neighbours"


def test_the_text_report_lists_each_session_with_its_trace_or_its_reason(dd):
    recs = _session(1, pid=11, signal="SIGABRT") + _session(2, pid=12, signal="SIGKILL")
    _trace_log(dd, _trace(11, 30, 1))
    text = "\n".join(forensics._render_earlier_ends(ee.earlier_unclean_ends(None, records=recs)))
    assert "earlier unclean ends in the session ledger: 2" in text
    assert "pid 11" in text and "trace: Fatal Python error: Aborted" in text
    assert "pid 12" in text and "no trace: a SIGKILL leaves no trace" in text
    assert forensics._render_earlier_ends(None) == []
    assert "unavailable" in forensics._render_earlier_ends({"available": False, "reason": "r"})[0]


def test_the_previous_session_report_carries_the_earlier_ends_for_every_verdict(dd, monkeypatch):
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", True)
    monkeypatch.setattr(forensics, "kernel_evidence", lambda: {"verdict": "not-applicable"})
    sh.ledger_path().parent.mkdir(parents=True, exist_ok=True)
    for rec in _session(1, pid=61, signal="SIGABRT"):
        sh._append(rec)
    _trace_log(dd, _trace(61, 10, 1))
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unknown", "no sentinel: the earlier ends are still reported"
    assert rep["earlier_unclean_ends"]["sessions"][0]["trace"]["summary"] == "Fatal Python error: Aborted"


# --------------------------------------------------------------------------- #
#  E1. the peaks of every unclean end
# --------------------------------------------------------------------------- #
def _snap(i: int, *, threads: int = 10, frames: int = 4, width: int = 70) -> dict:
    return {
        "at": f"2026-09-30T21:{i:02d}:00+00:00", "why": "memory short", "avail_mb": 900.0 - i, "rss_mb": 3000.0 + i,
        "swap_used_mb": 1000.0, "memory": {"rss_anon_mb": 1.0},
        "threads": [{"name": f"oo-thread-{t}", "tid": t, "cpu_s": float(100 - t),
                     "stack": [f"src/mod{f}.py:{t} fn".ljust(width, "x") for f in range(frames)]}
                    for t in range(threads)] + [{"name": "sampler", "sampler": True, "stack": ["src/s.py:1 s"]}],
    }


def _hwm(n_snaps: int = 3, **kw) -> dict:
    return {
        "pid": 1, "started_at": "2026-09-30T20:00:00+00:00", "last_ts": "2026-09-30T21:59:00+00:00",
        "rss_max_mb": 3817.0, "rss_max_at": "2026-09-30T21:08:38+00:00",
        "avail_min_mb": 995.7, "avail_min_at": "2026-09-30T21:08:43+00:00",
        "swap_used_max_mb": 1024.0, "swap_used_max_at": "2026-09-30T21:03:00+00:00", "phase": "export",
        "at_peak": {"rss_anon_mb": 3437.3, "heap_free_held_mb": 988.7},
        "heap_at_peak": {"rss_anon_mb": 3000.0, "heap_free_held_mb": 700.0},
        "pressure_taken": n_snaps, "pressure": [_snap(i, **kw) for i in range(n_snaps)],
    }


def _size(x) -> int:
    return len(json.dumps(x, separators=(",", ":"), default=str).encode("utf-8"))


def test_a_record_that_fits_is_written_whole_without_a_truncated_flag():
    peaks = sh._end_peaks(_hwm(1, threads=3, frames=2))
    assert "truncated" not in peaks and _size(peaks) <= sh.END_PEAKS_MAX_BYTES
    assert [t["name"] for t in peaks["pressure"][0]["threads"]] == ["oo-thread-0", "oo-thread-1", "oo-thread-2"]
    assert "last_ts" not in peaks, "the liveness stamp is the end's own time, not a mark"
    assert peaks["rss_max_at"] and peaks["avail_min_at"] and peaks["phase"] == "export"
    assert peaks["heap_at_peak"] and "memory" not in peaks["pressure"][0]


def test_a_stack_frame_is_cut_to_its_width_so_one_long_line_cannot_take_a_snapshot_with_it():
    peaks = sh._end_peaks(_hwm(1, threads=2, frames=2, width=600))
    frames = [f for t in peaks["pressure"][0]["threads"] for f in t["stack"]]
    assert frames and all(len(f) <= 120 for f in frames)


def test_the_sampler_thread_is_left_out_and_heap_at_peak_is_not_repeated_when_it_is_the_same_reading():
    h = _hwm(1, threads=2, frames=1)
    h["heap_at_peak"] = dict(h["at_peak"])
    peaks = sh._end_peaks(h)
    assert "heap_at_peak" not in peaks
    assert all(not t.get("sampler") and t["name"] != "sampler" for t in peaks["pressure"][0]["threads"])


def test_over_the_cap_frames_go_first_one_notch_at_a_time_and_the_line_says_so(monkeypatch):
    """The 2026-09-30 shape: three snapshots of ten threads at four frames weigh just over 4 KB."""
    fixture = _hwm(3, width=24)
    with monkeypatch.context() as m:
        m.setattr(sh, "END_PEAKS_MAX_BYTES", 10**9)
        whole = sh._end_peaks(fixture)
    assert _size(whole) > sh.END_PEAKS_MAX_BYTES and "truncated" not in whole, "the fixture needs a notch"
    peaks = sh._end_peaks(fixture)
    assert _size(peaks) <= sh.END_PEAKS_MAX_BYTES
    assert peaks["truncated"] == ["frames"], "only as much as the line needed"
    depths = {len(t["stack"]) for s in peaks["pressure"] for t in s["threads"]}
    assert len(peaks["pressure"]) == 3 and depths == {sh.END_PEAKS_FRAMES - 1}, "one notch (4 -> 3), not a jump to 1"
    assert len(peaks["pressure"][0]["threads"]) == sh.END_PEAKS_THREADS == 8


def test_further_over_the_threads_thin_before_any_snapshot_goes_and_the_marks_never_do():
    """The sidecar keeps at most 8 snapshots; forty busy threads each is far past the cap."""
    heavy = sh._end_peaks(_hwm(8, threads=40, frames=4, width=110))
    assert _size(heavy) <= sh.END_PEAKS_MAX_BYTES
    assert heavy["truncated"][:2] == ["frames", "threads"] and "snapshots" not in heavy["truncated"]
    for key in ("rss_max_mb", "rss_max_at", "avail_min_mb", "avail_min_at", "swap_used_max_mb", "phase", "pressure_taken"):
        assert key in heavy, key
    assert heavy["pressure_taken"] == 8 and len(heavy["pressure"]) == 8, "every snapshot kept, thinner"


def test_past_that_the_older_snapshots_go_and_the_newest_stays_it_is_the_one_nearest_the_death():
    many = sh._end_peaks(_hwm(60, threads=40, frames=4, width=110))     # more than the sidecar keeps: defensive
    assert _size(many) <= sh.END_PEAKS_MAX_BYTES
    assert "snapshots" in many["truncated"] and many["pressure_taken"] == 60
    assert [s["at"] for s in many["pressure"]] == ["2026-09-30T21:59:00+00:00"]
    for key in ("rss_max_mb", "avail_min_mb", "swap_used_max_mb", "phase"):
        assert key in many, key


def test_the_context_goes_before_the_marks_even_when_nothing_else_fits():
    h = _hwm(2)
    h["at_peak"] = {"blob": "x" * 6000}
    h["heap_at_peak"] = {"blob": "y" * 6000}
    peaks = sh._end_peaks(h)
    assert _size(peaks) <= sh.END_PEAKS_MAX_BYTES
    assert "heap_at_peak" in peaks["truncated"] and "at_peak" in peaks["truncated"]
    assert peaks["rss_max_mb"] == 3817.0 and peaks["avail_min_at"]


def test_no_record_is_no_peaks_and_never_an_empty_dict():
    assert sh._end_peaks(None) is None and sh._end_peaks({}) is None


def _sidecar(dd: Path, pid: int, rss: float = 3500.0) -> None:
    (dd).mkdir(parents=True, exist_ok=True)
    (dd / "session_hwm.json").write_text(json.dumps({
        "pid": pid, "started_at": "2023-11-14T10:00:00+00:00", "last_ts": "2023-11-14T20:00:05+00:00",
        "rss_max_mb": rss, "avail_min_mb": 76.0, "phase": "collect"}), encoding="utf-8")
    session_hwm.reset_for_tests()


def _boot(monkeypatch, epoch: float, prev_state=None):
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: epoch)
    return sh.record_boot(prev_state)


def test_a_dead_session_closed_by_the_next_boot_carries_its_peaks_and_a_clean_one_does_not(dd, monkeypatch):
    me = os.getpid()
    _boot(monkeypatch, T0)                                           # the session that will die
    _sidecar(dd, me)
    _boot(monkeypatch, T0 + 600, {"state": "running", "pid": me, "started_at": ch._iso(T0)})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["clean"] is False and end["previous_peaks"]["rss_max_mb"] == 3500.0
    assert end["previous_peaks"]["avail_min_mb"] == 76.0 and end["previous_peaks"]["phase"] == "collect"
    # a session that ended cleanly through the sentinel carries none
    sh.ledger_path().unlink()
    _boot(monkeypatch, T0 + 1200)
    _sidecar(dd, me)
    _boot(monkeypatch, T0 + 1800, {"state": "clean", "pid": me, "started_at": ch._iso(T0 + 1200),
                                   "ended_at": ch._iso(T0 + 1700)})
    end2 = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end2["clean"] is True and "previous_peaks" not in end2


def test_marks_are_never_written_onto_another_sessions_end(dd, monkeypatch):
    """The sidecar names pid X and so does the sentinel, but the ledger's last boot is another process:
    the ledger missed a boot, and X's marks must not become that process's."""
    me = os.getpid()
    _boot(monkeypatch, T0)                                           # the ledger's last boot is ``me``
    _sidecar(dd, me + 50)
    _boot(monkeypatch, T0 + 600, {"state": "running", "pid": me + 50, "started_at": ch._iso(T0)})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["clean"] is False and "previous_peaks" not in end
    # and a sidecar of a different process than the sentinel's is not read either
    sh.ledger_path().unlink()
    _boot(monkeypatch, T0 + 1200)
    _sidecar(dd, me + 7)
    _boot(monkeypatch, T0 + 1800, {"state": "running", "pid": me, "started_at": ch._iso(T0 + 1200)})
    assert "previous_peaks" not in [r for r in sh.read_records() if r["kind"] == "end"][0]


def test_the_chronology_shows_the_peaks_of_an_old_end(dd, monkeypatch):
    me = os.getpid()
    _boot(monkeypatch, T0)
    _sidecar(dd, me)
    _boot(monkeypatch, T0 + 600, {"state": "running", "pid": me, "started_at": ch._iso(T0)})
    events = ch.chronology(anchor="install", now=T0 + 900)["events"]
    ends = [e for e in events if e["kind"] == "end-unclean"]
    assert ends and ends[0]["detail"]["previous_peaks"]["rss_max_mb"] == 3500.0


# --------------------------------------------------------------------------- #
#  E2. the build the session ran
# --------------------------------------------------------------------------- #
SHA1 = "a" * 40
SHA2 = "b" * 40


def _git(root: Path, head: str, *, loose: dict | None = None, packed: str | None = None) -> Path:
    g = root / ".git"
    g.mkdir(parents=True)
    (g / "HEAD").write_text(head + "\n", encoding="utf-8")
    for ref, sha in (loose or {}).items():
        (g / ref).parent.mkdir(parents=True, exist_ok=True)
        (g / ref).write_text(sha + "\n", encoding="utf-8")
    if packed is not None:
        (g / "packed-refs").write_text(packed, encoding="utf-8")
    return g


def test_a_loose_ref_is_followed(tmp_path):
    _git(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": SHA1})
    assert bm.read_git_head(tmp_path) == {"git_head": SHA1, "git_ref": "refs/heads/main"}


def test_packed_refs_are_followed_and_peeled_lines_and_comments_are_skipped(tmp_path):
    packed = f"# pack-refs with: peeled fully-peeled sorted\n{SHA2} refs/heads/other\n{SHA1} refs/heads/main\n^{SHA2}\n"
    _git(tmp_path, "ref: refs/heads/main", packed=packed)
    assert bm.read_git_head(tmp_path) == {"git_head": SHA1, "git_ref": "refs/heads/main"}


def test_a_loose_ref_wins_over_packed_refs_as_git_resolves_them(tmp_path):
    _git(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": SHA2}, packed=f"{SHA1} refs/heads/main\n")
    assert bm.read_git_head(tmp_path)["git_head"] == SHA2


def test_a_detached_head_names_the_commit_itself(tmp_path):
    _git(tmp_path, SHA1)
    assert bm.read_git_head(tmp_path) == {"git_head": SHA1, "git_ref": None}


def test_a_linked_worktree_reads_its_own_head_and_the_shared_refs(tmp_path):
    common = tmp_path / "main" / ".git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "feature").write_text(SHA2 + "\n", encoding="utf-8")
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
    assert bm.read_git_head(wt) == {"git_head": SHA2, "git_ref": "refs/heads/feature"}


def test_where_the_head_cannot_be_read_the_record_says_why_and_never_invents_one(tmp_path):
    none = bm.read_git_head(tmp_path)
    assert none["git_head"] is None and "not a git checkout" in none["reason"]
    _git(tmp_path / "a", "ref: refs/heads/gone")
    r = bm.read_git_head(tmp_path / "a")
    assert r["git_head"] is None and r["git_ref"] == "refs/heads/gone"
    assert "no packed-refs to look in" in r["reason"]
    _git(tmp_path / "b", "ref: refs/heads/gone", packed=f"{SHA1} refs/heads/main\n")
    assert "neither a loose ref nor listed in packed-refs" in bm.read_git_head(tmp_path / "b")["reason"]
    _git(tmp_path / "c", "garbage")
    assert "neither a commit nor a ref" in bm.read_git_head(tmp_path / "c")["reason"]
    _git(tmp_path / "d", "ref: refs/heads/../../etc/passwd")
    d = bm.read_git_head(tmp_path / "d")
    assert d["git_head"] is None and "form this reader does not follow" in d["reason"], "never walks out of .git"
    _git(tmp_path / "e", "ref: refs/heads/main", loose={"refs/heads/main": "not-a-sha"})
    assert bm.read_git_head(tmp_path / "e")["git_head"] is None, "a loose ref that is not a commit id is not one"


def test_the_migrations_fingerprint_moves_when_a_script_is_added_and_not_otherwise(tmp_path):
    v = tmp_path / "migrations" / "versions"
    v.mkdir(parents=True)
    (v / "aaa_one.py").write_text("x", encoding="utf-8")
    (v / "bbb_two.py").write_text("x", encoding="utf-8")
    first = bm.migrations_marker(tmp_path)
    assert first["count"] == 2 and re.fullmatch(r"[0-9a-f]{12}", first["fingerprint"])
    (v / "aaa_one.py").write_text("changed contents", encoding="utf-8")
    assert bm.migrations_marker(tmp_path) == first, "a listing of NAMES: an edit in place is not a new script"
    (v / "ccc_three.py").write_text("x", encoding="utf-8")
    third = bm.migrations_marker(tmp_path)
    assert third["count"] == 3 and third["fingerprint"] != first["fingerprint"]
    empty = bm.migrations_marker(tmp_path / "nowhere")
    assert empty["count"] == 0 and empty["fingerprint"] is None and "no migration scripts" in empty["reason"]


def test_changed_between_says_what_moved_and_unknown_is_never_unchanged():
    a = {"git_head": SHA1, "migrations": {"count": 3, "fingerprint": "aaaaaaaaaaaa"}}
    assert bm.changed_between(a, dict(a)) == []
    assert bm.changed_between(a, {**a, "git_head": SHA2}) == ["git_head"]
    assert bm.changed_between(a, {**a, "migrations": {"count": 4, "fingerprint": "bbbbbbbbbbbb"}}) == ["migrations"]
    assert bm.changed_between(None, a) is None and bm.changed_between(a, None) is None
    no_git = {"git_head": None, "reason": "r", "migrations": {"count": 3, "fingerprint": "aaaaaaaaaaaa"}}
    assert bm.changed_between(no_git, dict(no_git)) == [], "two installs with no head did not 'change' it"


def test_a_marker_one_boot_could_not_read_is_not_a_change_and_is_not_unchanged_either(monkeypatch):
    """A head unreadable on one boot (a None beside a commit) says nothing about whether the code
    moved: counting it would put a crash that followed an unreadable boot under 'updated', and
    reading it as '[]' would put it under 'unchanged'. It is unknown (None) unless another marker
    DID move, which is reported whatever the rest say."""
    known = {"git_head": SHA1, "migrations": {"count": 3, "fingerprint": "aaaaaaaaaaaa"}}
    unreadable = {"git_head": None, "reason": "r", "migrations": {"count": None, "reason": "r"}}
    assert bm.changed_between(known, unreadable) is None and bm.changed_between(unreadable, known) is None
    assert bm.changed_between(known, {"git_head": SHA2, "migrations": {"count": None, "reason": "r"}}) == ["git_head"]
    # only the head is unreadable on one boot, and the migrations did not move: still unknown
    assert bm.changed_between(known, {**known, "git_head": None, "reason": "r"}) is None
    # only the migrations are unreadable on one boot, and the head did not move: still unknown
    assert bm.changed_between(known, {"git_head": SHA1, "migrations": {"count": None, "reason": "r"}}) is None
    # one marker unreadable on ONE boot, the other moved: the move is reported
    assert bm.changed_between(known, {"git_head": None, "migrations": {"count": 4, "fingerprint": "bbbbbbbbbbbb"}}) == ["migrations"]
    # nothing readable on either boot: nothing could be compared, so nothing is said
    assert bm.changed_between(unreadable, dict(unreadable)) is None


@pytest.mark.parametrize("odd", ["a string", 5, ["x"], None])
def test_a_migrations_value_that_is_not_a_mapping_does_not_raise(odd):
    a = {"git_head": SHA1, "migrations": odd}
    assert bm.changed_between(a, {"git_head": SHA2, "migrations": odd}) == ["git_head"]
    assert bm.changed_between({"git_head": SHA1, "migrations": {"fingerprint": "f"}}, a) is None


def test_the_process_markers_are_taken_once_and_kept_for_the_life_of_the_process(monkeypatch):
    calls = []
    monkeypatch.setattr(bm, "code_markers", lambda root=None: calls.append(1) or {"git_head": SHA1})
    bm.reset_process_markers_for_tests()
    assert bm.process_markers() == {"git_head": SHA1}
    monkeypatch.setattr(bm, "code_markers", lambda root=None: calls.append(2) or {"git_head": SHA2})
    assert bm.process_markers() == {"git_head": SHA1} and calls == [1], "a later read would name code that is not running"
    bm.reset_process_markers_for_tests()


def test_the_marker_makes_no_subprocess_and_no_alembic_load_on_the_boot_path():
    """The alembic head costs 0.2 to 0.4 s measured and this runs before unlock."""
    tree = ast.parse(Path(bm.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"subprocess", "alembic", "sqlalchemy", "requests", "httpx", "socket"}, imported
    assert "src.database" not in Path(bm.__file__).read_text(encoding="utf-8").replace("src.database.migrate.schema_head", "")


def test_every_boot_record_carries_the_code_block_and_the_chronology_reads_an_update(dd, monkeypatch):
    rec = _boot(monkeypatch, T0)
    code = rec["code"]
    assert code["migrations"]["count"] > 0 and re.fullmatch(r"[0-9a-f]{12}", code["migrations"]["fingerprint"])
    assert code["git_head"] is None or re.fullmatch(r"[0-9a-f]{40,64}", code["git_head"])
    if code["git_head"] is None:
        assert code["reason"]
    # two boots of one build: nothing moved; then a boot of a changed build
    _boot(monkeypatch, T0 + 100, {"state": "clean", "pid": 1, "started_at": ch._iso(T0), "ended_at": ch._iso(T0 + 90)})
    monkeypatch.setattr(sh, "_code_markers", lambda: {
        **code, "migrations": {"count": code["migrations"]["count"] + 1, "fingerprint": "ffffffffffff"}})
    _boot(monkeypatch, T0 + 200, {"state": "clean", "pid": 1, "started_at": ch._iso(T0 + 100), "ended_at": ch._iso(T0 + 190)})
    boots = [e for e in ch.chronology(anchor="install", now=T0 + 300)["events"] if e["kind"] == "boot"]
    assert [b["detail"]["code_changed_since_previous_boot"] for b in boots] == [None, [], ["migrations"]]
    assert boots[2]["detail"]["code"]["migrations"]["fingerprint"] == "ffffffffffff"


def test_a_boot_record_from_before_the_block_is_unknown_not_unchanged(dd, monkeypatch):
    sh.ledger_path().parent.mkdir(parents=True, exist_ok=True)
    sh._append({"kind": "boot", "session_id": "old", "at": ch._iso(T0), "pid": 1})
    sh._append({"kind": "end", "session_id": "old", "at": ch._iso(T0 + 50), "clean": True})
    _boot(monkeypatch, T0 + 100, {"state": "clean", "pid": 1, "started_at": ch._iso(T0), "ended_at": ch._iso(T0 + 50)})
    boots = [e for e in ch.chronology(anchor="install", now=T0 + 300)["events"] if e["kind"] == "boot"]
    assert boots[0]["detail"]["code_changed_since_previous_boot"] is None
    assert boots[1]["detail"]["code_changed_since_previous_boot"] is None, "the old boot has no block to compare with"


def test_a_failing_marker_never_breaks_a_boot(dd, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(bm, "read_git_head", boom)
    monkeypatch.setattr(bm, "migrations_marker", boom)
    code = bm.code_markers()
    assert code["git_head"] is None and "RuntimeError" in code["reason"]
    assert code["migrations"]["count"] is None
    assert "method" not in code, "said once by the chronology, not on every boot record"


def test_the_ledger_helper_swallows_a_marker_that_raises(monkeypatch):
    import src.monitoring.build_marker as mod

    mod.reset_process_markers_for_tests()
    monkeypatch.setattr(mod, "code_markers", lambda root=None: (_ for _ in ()).throw(RuntimeError("x")))
    assert sh._code_markers() is None
    mod.reset_process_markers_for_tests()


def test_the_code_blocks_method_is_said_once_by_the_chronology_not_on_every_boot(dd, monkeypatch):
    rec = _boot(monkeypatch, T0)
    assert "method" not in rec["code"]
    doc = ch.chronology(anchor="install", now=T0 + 300)
    assert doc["summary"]["code_markers_method"] == bm.METHOD and "no subprocess" in bm.METHOD


# --------------------------------------------------------------------------- #
#  the member's own bound: the one member that grows with the ledger
# --------------------------------------------------------------------------- #
def _chronology_doc(n: int, peak_chars: int = 1300) -> dict:
    """A chronology of ``n`` sessions, each with a boot, an unclean end carrying ``previous_peaks`` and the
    gap before the next: the shape ``chronology()`` returns, built without a ledger."""
    sessions = [
        {"session_id": f"s{i}", "started_at": ch._iso(T0 + i * 3600), "ended_at": ch._iso(T0 + i * 3600 + 3000),
         "clean": False, "current": i == n - 1}
        for i in range(n)
    ]
    events: list[dict] = []
    for i, s in enumerate(sessions):
        events.append({"at": s["started_at"], "kind": "boot", "label": "boot", "session_id": s["session_id"],
                       "detail": {"pid": i, "code": {"git_head": "a" * 40}}})
        events.append({"at": s["ended_at"], "kind": "end-unclean", "label": "end unclean", "session_id": s["session_id"],
                       "detail": {"basis": "b", "previous_peaks": {"at_peak": {"stack": "y" * peak_chars}}}})
    events.append({"at": None, "kind": "end-unknown", "label": "end unknown", "session_id": "s0", "detail": {}})
    events.append({"at": None, "kind": "end-unknown", "label": "end unknown", "session_id": f"s{n - 1}", "detail": {}})
    gaps = [{"from": sessions[i]["ended_at"], "to": sessions[i + 1]["started_at"], "seconds": 600, "basis": "no record",
             "machine": "same boot"} for i in range(n - 1)]
    return {"schema": "oo-chronology-1", "generated_at": ch._iso(T0), "current_session": {"session_id": f"s{n - 1}"},
            "sessions": sessions, "events": events, "gaps": gaps, "release_run": None,
            "summary": {"restarts": n - 1, "method": "m"}, "ledger": {"records": 2 * n}}


def test_a_chronology_that_fits_is_the_whole_chronology():
    doc = _chronology_doc(20)
    assert ch.bounded_for_member(doc) is doc and "cut" not in doc


def test_the_stacks_of_the_older_ends_go_first_and_no_session_is_dropped_for_them():
    doc = _chronology_doc(100)
    bound = ch._doc_bytes(doc) - 40_000  # over by less than the stacks of the older ends hold
    out = ch.bounded_for_member(doc, bound)
    assert ch._doc_bytes(out) <= bound and len(out["sessions"]) == 100 and len(out["events"]) == len(doc["events"])
    kept = [e for e in out["events"] if (e["detail"].get("previous_peaks") or {}).get("at_peak")]
    omitted = [e for e in out["events"] if (e["detail"].get("previous_peaks") or {}) == {"omitted_for_size": True}]
    assert len(kept) == ch.CHRONOLOGY_KEEP_PEAKS and len(omitted) == 90
    assert [e["session_id"] for e in kept] == [f"s{i}" for i in range(90, 100)], "the NEWEST ends keep their stacks"
    assert out["cut"]["sessions_dropped"] == 0 and out["cut"]["stacks_omitted_for_size"] == 90
    assert "200 records" in out["cut"]["why"] and "WHOLE" in out["cut"]["why"]
    assert doc["events"][1]["detail"]["previous_peaks"]["at_peak"], "the document it was given is not changed"


def test_the_oldest_sessions_go_by_one_time_cut_for_sessions_events_and_gaps():
    doc = _chronology_doc(300)
    bound = 150_000
    out = ch.bounded_for_member(doc, bound)
    k = out["cut"]["sessions_dropped"]
    assert 0 < k < 299 and ch._doc_bytes(out) <= bound and "over_budget_bytes" not in out["cut"]
    assert out["sessions"][0]["session_id"] == f"s{k}" and out["sessions"][-1]["current"] is True
    first = out["sessions"][0]["started_at"]
    assert out["cut"]["older_than"] == first
    assert all(e["at"] >= first for e in out["events"] if e["at"] is not None)
    assert all(g["to"] >= first for g in out["gaps"])
    # an event with no time stays only with a session that is kept
    assert [e["session_id"] for e in out["events"] if e["at"] is None] == ["s299"]
    # the fewest sessions: the copy is within one session's rows of the bound, so one fewer would not fit
    assert bound - ch._doc_bytes(out) < 2_000, ch._doc_bytes(out)
    # the summary and the ledger counts are of the whole ledger, and say so
    assert out["summary"] == doc["summary"] and out["ledger"] == doc["ledger"] and "WHOLE" in out["cut"]["why"]
    assert len(doc["sessions"]) == 300, "the document it was given is not cut"


def test_a_bound_that_cannot_be_met_keeps_the_newest_session_and_says_so():
    doc = _chronology_doc(10)
    out = ch.bounded_for_member(doc, 500)
    assert [s["session_id"] for s in out["sessions"]] == ["s9"] and out["cut"]["over_budget_bytes"] > 500
    one = _chronology_doc(1)
    out = ch.bounded_for_member(one, 500)
    assert len(out["sessions"]) == 1 and out["cut"]["sessions_dropped"] == 0 and out["cut"]["over_budget_bytes"] > 500


def test_the_bundle_member_is_held_to_its_bound_and_the_route_keeps_the_whole_ledger(dd, monkeypatch):
    from src.api.diagnostics import bundle as b

    whole = _chronology_doc(1500, peak_chars=2600)  # a real end carries up to 4 KB of marks (END_PEAKS_MAX_BYTES)
    assert ch._doc_bytes(whole) > ch.CHRONOLOGY_MEMBER_BYTES * 2.5, "the ledger's full size is what the bound is for"
    monkeypatch.setattr(ch, "chronology", lambda **kw: whole)
    member = b._chronology_member()
    assert ch._doc_bytes(member) <= ch.CHRONOLOGY_MEMBER_BYTES
    # the stacks of the older ends are most of its size: thinning them keeps every session of a full ledger
    assert member["cut"]["stacks_omitted_for_size"] == 1500 - ch.CHRONOLOGY_KEEP_PEAKS and len(member["sessions"]) == 1500
    assert member["sessions"][-1]["session_id"] == "s1499"
    assert len(whole["sessions"]) == 1500 and "cut" not in whole

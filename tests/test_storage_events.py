"""The events behind the instant: the storage-events journal and the sites that write it (WAL's members of the one Diagnostics zip).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/monitoring/storage_events.py`` keeps the last few holds of the write gate, guard engagements, checkpoints, store opens and pool
timeouts in a small file, so the zip of the next start can say what the one before it did. The three conditions of its go (the
coordinator, 2026-10-13) are what this file pins:

1. a cap limits what is KEPT, never what is COUNTED: each kind carries a running total and a dropped count, across restarts, and
   the slot shows both;
2. the passphrase rule holds on every field: a planted marker reaches neither the file, the member nor the slot's answer, through
   the journal API and through each real site;
3. it is best effort: a journal that cannot write, or cannot even record, never blocks or raises into the gate, the guard, a
   checkpoint, an unlock or the pool.

Every site test drives the REAL gate, guard, checkpoint, unlock timer or pool rather than a lookalike. The journal's file is the
test's own (``tmp_path``); nothing here writes the suite's shared data directory.
"""

from __future__ import annotations

import copy
import errno
import json
import sqlite3
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from src.monitoring import storage_events as se

MARKER = "MARKER-passphrase-4711-correct-horse"


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """A journal whose file is ``tmp_path``'s and whose background writer runs at test speed."""
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    from src.database import writer

    # The watchdog tests set the module's "hold the journal was last opened for"; restored to what it was after each test.
    monkeypatch.setattr(writer, "_JOURNALED_HOLD", None)
    se.reset_for_tests()
    yield path
    se.reset_for_tests()


@pytest.fixture()
def guard_on(monkeypatch):
    """conftest.py switches the storage guard off for the suite; the tests that feed one injected readings switch it on."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")


@pytest.fixture()
def held_passphrase(monkeypatch):
    """The process holds a passphrase, as an unlocked session does (the scrub reads the store module's global)."""
    import src.database.connect as connect_mod

    monkeypatch.setattr(connect_mod, "_passphrase", MARKER)
    return MARKER


def _member(budget: int = 10_000_000) -> dict:
    return se.diagnostics_member(budget)


def _events(kind: str) -> list[dict]:
    return _member()["kinds"][kind]["events"]


def _file_total(path, kind: str) -> int:
    """The total the file holds for ``kind``; -1 while it is missing or half-written (a poll must not raise)."""
    try:
        total = json.loads(path.read_text(encoding="utf-8"))["kinds"][kind]["total"]
        return total if isinstance(total, int) else -1
    except Exception:  # noqa: BLE001 - a poll reads a file another thread is replacing; whatever it saw is "not yet"
        return -1


def _on_journal_replace(monkeypatch, journal, fn):
    """Make ``fn(tmp, dest)`` the ``os.replace`` of the journal's file ONLY. ``os`` is process-wide, so another thread's replace must
    neither be counted by a test nor broken by it."""
    real = se.os.replace

    def routed(a, b):
        return fn(a, b) if str(b) == str(journal) else real(a, b)

    monkeypatch.setattr(se.os, "replace", routed)


def _wait_until(pred, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


# --------------------------------------------------------------------------- #
#  1. A cap limits what is kept, never what is counted
# --------------------------------------------------------------------------- #
def test_a_recorded_event_is_in_the_member_with_its_kind_total_kept_and_dropped(journal):
    se.record("gate_hold", {"holder": "writer", "seconds": 61.0})
    k = _member()["kinds"]["gate_hold"]
    assert (k["keep"], k["total"], k["kept"], k["dropped"]) == (20, 1, 1, 0)
    assert k["events"][0]["holder"] == "writer" and k["events"][0]["session"] == "this"
    assert "proc" not in k["events"][0], "the process token is the journal's, not the zip's"


def test_the_cap_keeps_the_newest_and_counts_the_rest(journal):
    for n in range(25):
        se.record("gate_hold", {"n": n})
    k = _member()["kinds"]["gate_hold"]
    assert (k["total"], k["kept"], k["dropped"]) == (25, 20, 5)
    assert [e["n"] for e in k["events"]] == list(range(5, 25)), "the OLDEST go, in order"


def test_every_kind_has_its_own_cap_and_an_unknown_kind_is_refused(journal):
    for kind, cap in se.KEEP.items():
        for n in range(cap + 3):
            se.record(kind, {"n": n})
    m = _member()["kinds"]
    for kind, cap in se.KEEP.items():
        assert (m[kind]["keep"], m[kind]["kept"], m[kind]["total"], m[kind]["dropped"]) == (cap, cap, cap + 3, 3), kind
    se.record("not_a_kind", {"n": 1})
    assert "not_a_kind" not in _member()["kinds"]


def test_totals_and_dropped_counts_survive_a_restart(journal):
    for n in range(25):
        se.record("gate_hold", {"n": n})
    se.record("guard", {"kind": "wal"})
    se.flush()
    se.reset_for_tests(keep_file=True)  # the process ends: memory gone, the file stays
    m = _member()
    assert m["file"]["read_at_first_use"] == "ok"
    k = m["kinds"]["gate_hold"]
    assert (k["total"], k["kept"], k["dropped"]) == (25, 20, 5)
    assert all(e["session"] == "this" for e in k["events"]), "same process token here; the next test changes it"
    se.record("gate_hold", {"n": 25})
    k = _member()["kinds"]["gate_hold"]
    assert (k["total"], k["kept"], k["dropped"]) == (26, 20, 6), "the count goes on from the file's, not from zero"
    assert m["since"] == _member()["since"], "'since' is the first event ever, not this start"


def test_events_of_an_earlier_process_say_so(journal, monkeypatch):
    se.record("checkpoint", {"trigger": "boundary"})
    se.flush()
    se.reset_for_tests(keep_file=True)
    monkeypatch.setattr(se, "_PROC", "another-process")
    se.record("checkpoint", {"trigger": "guard"})
    sessions = {e["trigger"]: e["session"] for e in _events("checkpoint")}
    assert sessions == {"boundary": "earlier", "guard": "this"}


def test_an_event_still_open_when_its_process_ended_is_closed_as_not_recorded(journal, monkeypatch):
    se.record("gate_hold", {"holder": "writer", "seconds": 31.0}, key=("hold", 1))
    se.flush()
    se.reset_for_tests(keep_file=True)
    monkeypatch.setattr(se, "_PROC", "the-next-process")
    (e,) = _events("gate_hold")
    assert e["open"] is False and e["session"] == "earlier"
    assert "its end was not recorded" in e["ended"], "never left open, never given an invented end"
    assert "ended_at" not in e, "no end time is made up"


def test_an_open_event_is_updated_and_ended_by_its_key(journal):
    se.record("guard", {"kind": "wal"}, key="guard")
    assert se.update("guard", "guard", {"peak": 5}) is True
    (e,) = _events("guard")
    assert e["open"] is True and e["peak"] == 5
    assert se.end("guard", "guard", {"seconds": 12.0, "ended_by": "measurement"}) is True
    (e,) = _events("guard")
    assert e["open"] is False and e["seconds"] == 12.0 and "ended_at" in e
    assert _member()["kinds"]["guard"]["total"] == 1, "closing an event does not count a second one"
    assert se.end("guard", "guard") is False and se.update("guard", "guard", {"x": 1}) is False, "already ended"
    assert se.end("guard", "never-opened") is False


def test_an_open_event_pushed_out_by_newer_ones_is_no_longer_addressable(journal):
    se.record("guard", {"kind": "wal"}, key="old")
    for n in range(10):
        se.record("guard", {"n": n})
    assert se.update("guard", "old", {"x": 1}) is False and se.end("guard", "old") is False
    assert _member()["kinds"]["guard"]["dropped"] == 1


def test_a_damaged_or_alien_file_is_not_read_back_and_the_member_says_so(journal):
    journal.write_text("{not json", encoding="utf-8")
    assert _member()["file"]["read_at_first_use"].startswith("unreadable (JSONDecodeError")
    se.reset_for_tests(keep_file=True)
    journal.write_text(json.dumps({"schema": "something-else", "kinds": {}}), encoding="utf-8")
    assert _member()["file"]["read_at_first_use"] == "unreadable (not this journal)"
    se.reset_for_tests(keep_file=True)
    journal.write_bytes(b" " * (se.MAX_FILE_BYTES + 1))
    assert "larger than" in _member()["file"]["read_at_first_use"]
    se.record("gate_hold", {"n": 1})  # and recording goes on from an empty journal
    assert _member()["kinds"]["gate_hold"]["total"] == 1


def test_a_missing_file_reads_as_missing_and_the_first_event_starts_the_count(journal):
    assert _member()["file"]["read_at_first_use"] == "missing"
    assert _member()["since"] is None
    se.record("open", {"via": "boot"})
    assert _member()["since"] is not None


def test_recording_does_no_disk_io_and_the_file_is_read_by_the_writer_or_the_member(journal, monkeypatch):
    """The measured site can hold the gate's lock or the guard's: a recording must not wait on a disk, so it never reads the file. The
    background writer reads it before its first write and the member before it answers."""
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 30.0)  # the writer must not reach its read while the assertions run, whatever the load
    reads: list[int] = []
    real = se._read_file
    monkeypatch.setattr(se, "_read_file", lambda: (reads.append(1), real())[1])
    se.record("gate_hold", {"n": 1}, key="k")
    se.update("gate_hold", "k", {"n": 2})
    se.end("gate_hold", "k")
    se.note_checkpoint("boundary", passive=(0, 1, 1), truncate=(0, 1, 1), seconds=0.1)
    se.note_open("boot", total_ms=1.0)
    se.note_pool_timeout(waited_s=1.0)
    assert reads == [], "no recording read the file"
    _member()
    assert reads == [1], "the member read it, once"
    _member()
    assert reads == [1]


def test_the_writer_extends_the_history_in_the_file_and_never_replaces_it(journal):
    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-01T00:00:00+00:00", "kinds": {
            "guard": {"total": 7, "events": [{"at": f"2026-10-01T00:00:0{i}+00:00", "proc": "old", "kind": "wal"} for i in range(3)]}}}),
        encoding="utf-8",
    )
    se.record("guard", {"kind": "disk"})  # nothing has read the file yet: the writer must, before it writes
    assert _wait_until(lambda: json.loads(journal.read_text(encoding="utf-8"))["kinds"]["guard"]["total"] == 8)
    data = json.loads(journal.read_text(encoding="utf-8"))
    assert data["since"] == "2026-10-01T00:00:00+00:00" and len(data["kinds"]["guard"]["events"]) == 4


def test_the_background_writer_writes_the_file_without_a_flush(journal):
    se.record("pool_timeout", {"waited_s": 30.0})
    assert _wait_until(journal.exists), "the writer thread wrote the file by itself"
    data = json.loads(journal.read_text(encoding="utf-8"))
    assert data["schema"] == se.SCHEMA and data["kinds"]["pool_timeout"]["total"] == 1


def test_a_burst_of_events_is_one_write_not_one_each(journal, monkeypatch):
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.3)
    replaced: list[int] = []
    real = se.os.replace
    _on_journal_replace(monkeypatch, journal, lambda a, b: (replaced.append(1), real(a, b))[1])
    for n in range(40):
        se.record("checkpoint", {"n": n})
    assert _wait_until(lambda: replaced, timeout=3.0)
    time.sleep(0.5)
    assert len(replaced) <= 2, f"40 events cost {len(replaced)} writes"


# --------------------------------------------------------------------------- #
#  What a hook may hand over: bounded JSON, never a repr
# --------------------------------------------------------------------------- #
def test_clean_bounds_every_value():
    long = "x" * 1000
    out = se._clean({"s": long, "l": list(range(100)), "d": {str(i): i for i in range(100)}, "f": float("nan"), "i": float("inf")})
    assert len(out["s"]) == se.STR_CHARS and out["s"].endswith("…")
    assert len(out["l"]) == se.LIST_ITEMS and len(out["d"]) == se.DICT_KEYS
    assert out["f"] is None and out["i"] is None, "a float JSON cannot carry is None, not NaN"
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    assert se._clean(deep) == {"a": {"b": {"c": {"d": "(dict)"}}}}, "past the depth it is the type's name"
    assert se._clean(1.23456789) == 1.235


def test_a_value_that_is_not_json_is_its_types_name_never_its_repr():
    class Secretive:
        def __repr__(self) -> str:
            return f"Secretive({MARKER})"

    out = se._clean({"obj": Secretive(), "exc": ValueError(MARKER), "bytes": MARKER.encode(), "set": {MARKER}})
    assert out == {"obj": "(Secretive)", "exc": "(ValueError)", "bytes": "(bytes)", "set": "(set)"}
    assert MARKER not in json.dumps(out)


def test_an_event_that_is_too_big_loses_its_largest_fields_and_says_which(journal):
    """One field cannot eat the member's measured budget, and a big field cannot turn the whole event into a stub: the largest goes
    first, the rest (what says what happened) stays, and the names of what went are in the event."""
    big = {"rows": [{f"k{i}": "y" * se.STR_CHARS for i in range(se.DICT_KEYS)} for _ in range(se.LIST_ITEMS)]}
    assert len(json.dumps(se._clean(big))) > se.MAX_EVENT_BYTES, "the fixture really is over the cap"
    se.record("checkpoint", {**big, "trigger": "boundary", "outcome": "done", "seconds": 0.5})
    (e,) = _events("checkpoint")
    assert e["fields_dropped"] == ["rows"] and e["oversize_bytes"] > se.MAX_EVENT_BYTES
    assert "rows" not in e
    assert (e["trigger"], e["outcome"], e["seconds"]) == ("boundary", "done", 0.5), "what says what happened is kept"
    assert se._size({k: v for k, v in e.items() if k != "session"}) <= se.MAX_EVENT_BYTES


def test_an_event_of_many_big_fields_drops_them_largest_first_until_it_fits(journal):
    fields = {f"f{i}": "z" * se.STR_CHARS for i in range(20)}
    fields["big"] = ["w" * se.STR_CHARS] * se.LIST_ITEMS
    se.record("guard", fields)
    (e,) = _events("guard")
    assert e["fields_dropped"][0] == "big", "the largest field is the first to go"
    assert se._size({k: v for k, v in e.items() if k != "session"}) <= se.MAX_EVENT_BYTES


def test_a_checkpoint_keeps_at_most_three_of_its_reader_holders_and_the_full_count(journal):
    holders = [{"thread": f"t{i}", "endpoint": "GET /x", "age_s": 1.0 + i} for i in range(8)]
    se.note_checkpoint("boundary", passive=(0, 1, 1), truncate=(0, 1, 1), seconds=0.1,
                       readers={"n": 8, "oldest_thread": "t0", "holders": holders})
    (e,) = _events("checkpoint")
    assert e["readers"]["n"] == 8 and [h["thread"] for h in e["readers"]["holders"]] == ["t0", "t1", "t2"]


def test_the_fields_the_journal_owns_cannot_be_overwritten_by_a_hook(journal):
    se.record("guard", {"at": "yesterday", "proc": "x", "open": True, "ended": "fine", "ended_at": "then", "session": "earlier", "kind": "wal"})
    (e,) = _events("guard")
    assert e["at"] != "yesterday" and e["session"] == "this" and e["kind"] == "wal"
    assert not ({"open", "ended", "ended_at"} & set(e)), "a hook cannot forge an end or leave an event open"
    se.record("guard", {"kind": "wal"}, key="k")
    se.update("guard", "k", {"open": False, "ended": "forged"})
    (_, e) = _events("guard")
    assert e["open"] is True and "ended" not in e


# --------------------------------------------------------------------------- #
#  The member: fits its budget by dropping the oldest of the largest kind, and says how many
# --------------------------------------------------------------------------- #
def test_over_its_budget_the_member_drops_the_oldest_of_the_largest_kind_and_counts_it(journal):
    for n in range(20):
        se.record("gate_hold", {"n": n, "route": "r" * 100})
    for n in range(10):
        se.record("guard", {"n": n})
    full = _member()
    size = len(json.dumps(full))
    budget = size - 1500
    cut = se.diagnostics_member(budget)
    assert len(json.dumps(cut, separators=(",", ":"))) <= budget
    gone = cut["dropped_to_fit"]
    assert gone and set(gone) == {"gate_hold"}, "the largest kind pays first"
    k = cut["kinds"]["gate_hold"]
    assert (k["total"], k["dropped"]) == (20, 0), "the cap's own counts never change by the cut"
    assert k["kept"] + gone["gate_hold"] == 20 and k["events"][0]["n"] == gone["gate_hold"], "the OLDEST went"
    assert cut["kinds"]["guard"]["kept"] == 10


def test_below_its_fixed_part_the_member_says_so_and_does_not_raise(journal):
    se.record("guard", {"n": 1})
    out = se.diagnostics_member(10)
    assert "omitted" in out and out["needs_at_least_bytes"] > 0


def test_the_member_always_carries_its_method_its_caveat_and_the_state_of_its_file(journal):
    m = _member()
    assert m["schema"] == se.SCHEMA and m["method"] and m["caveat"]
    assert set(m["kinds"]) == set(se.KEEP)
    f = m["file"]
    assert {"read_at_first_use", "last_write_ok_at", "write_failures", "last_write_failure", "internal_failures"} <= set(f)
    assert "score" not in json.dumps(m).lower(), "counts and names, never a verdict"


# --------------------------------------------------------------------------- #
#  The slot's budget is a measurement at full retention
# --------------------------------------------------------------------------- #
_NAME = "n" * 400  # past the cut
# The page reading with every field either source can carry, all at once (src/monitoring/page_reading.py ``compact``; the real readings
# carry one of ``pages_in_header`` / ``pages_in_database``, one of ``wal_bytes`` / ``wal_error``, and only the unlock's carries ``refused_attempts_before``): the widest numbers
# a 64 KiB-page store could produce, so this is larger than any reading, and the ``open`` event's budget is measured on it.
_PAGES_AT_THE_WIDEST = {
    "source": "engine-pragma", "state": "read", "pages_in_file": 123_456_789, "pages_in_header": 123_000_000, "pages_in_database": 123_000_000,
    "difference": 456_789, "page_size": 65536, "header_valid": True, "trailing_bytes": 65535, "file_bytes": 8_090_000_000_000,
    "wal_bytes": 22_345_678_901, "wal_error": "NotADirectoryError ENOTDIR", "refused_attempts_before": 999,
}


#: What the gate writes as a hold's ``seconds_by`` (``writer._SPENT_KINDS`` and ``between_statements``), each at the widest a day-long hold gives.
_SECONDS_BY_KEYS = ("insert", "savepoint", "other_statement", "commit", "between_statements")

_WIDEST_CLASS = "Module." + "E" * (se._CLASS_NAME_MAX - len("Module."))  # 80 characters, the most the journal lets through


def _fill_runs() -> None:
    """Each run kind to its cap with the WIDEST event the hooks can write: every measured field present at a large value, the longest
    class name the journal accepts, the longest refusal sentence, the backup's summary failure beside its end and the seconds of a run
    of more than a day. The last event of each kind is then checked to carry every key the sink knows, so a hook parameter that is
    renamed (the sink drops what it does not know) shrinks this measurement visibly and not silently."""
    assert len(_WIDEST_CLASS) == se._CLASS_NAME_MAX
    longest = max(se.RUN_REFUSALS, key=lambda k: len(se.RUN_REFUSALS[k]))
    every_key = set(se._RUN_NUMBERS) | set(se._RUN_FLAGS) | set(se._RUN_CLASSES) | {"verify", "error", "reason", "outcome", "seconds", "via"}
    widest_via = max(se.RUN_VIA, key=len)
    for what, kind in se.RUN_KINDS.items():
        for _ in range(se.KEEP[kind] + 4):
            note = se.run_started(what, via=widest_via)
            assert note is not None
            note.started = time.monotonic() - 99_999.999  # more than a day, the widest the seconds can be written
            se.run_free_space(note, "dest_free_bytes" if what == "export" else "data_free_bytes", "/")
            se.run_facts(note, dest_free_bytes=123_456_789_012_345, data_free_bytes=123_456_789_012_345, summary_error=_WIDEST_CLASS)
            se.run_ended(note, "ended-without-a-recorded-outcome", failure=_WIDEST_CLASS, reason=longest, volumes=1234, bytes=123_456_789_012_345,
                         gate_held_s=1234.567, snapshot_s=1234.567, snapshot_bytes=123_456_789_012_345, engine_wall_s=12345.678,
                         articles_merged=12_345_678, reindexed=12_345_678, verify="unavailable", set_ok=False,
                         files=12_345_678, files_done=12_345_678, resumed_from=12_345_678, copied=12_345_678, skipped=12_345_678,
                         restored=12_345_678, checked=12_345_678, mismatches=12_345_678)
        last = se._STATE[kind]["events"][-1]
        assert every_key <= set(last), f"{kind}: the widest run lost {sorted(every_key - set(last))}"
        assert last["error"] == _WIDEST_CLASS and last["seconds"] >= 99_999.0


def _fill_like_the_hooks(long_names: bool) -> None:
    """Every kind to its cap with the events the hooks write, names at the cut or ordinary."""

    def nm(text: str) -> str:
        return (text + _NAME)[: se.STR_CHARS] if long_names else text

    frames = [nm(f) for f in ("src.analytics.keyword_rollup:rebuild_segment_batches:412", "src.database.maintenance:run_in_write_window:1893", "src.database.writer:write_lock:540")]
    for i in range(se.KEEP["gate_hold"] + 5):
        se.record(
            "gate_hold",
            {"holder": nm("oo-collector-worker-17"), "seconds": 61.5 + i, "waiters": 7, "queued": 3,
             "route": nm("POST /api/keywords/reindex/{job_id}/resume"), "frames": frames},
            key=("hold", i),
        )
        # The widest a long hold's record gets: the phase and its sample counts (a day of 15 s samples in each of the four), and what the
        # holder thread did over the hold and the machine's memory at its end, each at ten digits.
        se.update("gate_hold", ("hold", i), {"phase": "pool-wait", "phase_samples": {"pool-wait": 5760, "execute": 5760, "commit": 5760, "python": 5760}})
        se.end("gate_hold", ("hold", i), {"seconds": 62.0 + i, "route": nm("POST /api/keywords/reindex/{job_id}/resume"),
                                           "cpu_ms": 86_400_000.0, "nvcsw": 9_999_999_999, "nivcsw": 9_999_999_999, "majflt": 9_999_999_999,
                                           "inblock": 9_999_999_999, "mem_available_mb": 999_999, "swap_used_mb": 999_999,
                                           "seconds_by": dict.fromkeys(_SECONDS_BY_KEYS, 86_400.0)})
    for _ in range(se.KEEP["guard"] + 4):
        se.record("guard", {"kind": "wal", "since": "2026-10-13T12:00:00+00:00", "wal_bytes_at_trip": 12_345_678_901,
                            "disk_free_bytes_at_trip": 9_876_543_210, "corpus_bytes_at_trip": 98_765_432_101,
                            "wal_high_bytes": 8_589_934_592, "disk_reserve_bytes": 21_474_836_480}, key="guard")
        se.end("guard", "guard", {"seconds": 1234.5, "peak_wal_bytes": 22_345_678_901, "wal_bytes_at_end": 1_234_567,
                                  "disk_free_bytes_at_end": 9_000_000_000,
                                  "ended_by": "retry after the hold lapsed (free space unreadable)"})
    # The shape ``hygiene._reader_snapshot`` hands every checkpoint (not only the busy ones): the full count, the oldest, and up to
    # PIN_HOLDERS_MAX (8) holders, of which the journal keeps READER_HOLDERS.
    readers = {
        "n": 9, "oldest_age_s": 812.4, "oldest_thread": nm("AnyIO worker thread"), "oldest_endpoint": nm("GET /api/articles/{id}/view"),
        "holders": [{"thread": nm(f"AnyIO worker thread {k}"), "endpoint": nm("GET /api/articles/{id}/view"), "age_s": 812.4 - k} for k in range(8)],
    }
    for i in range(30):
        se.note_checkpoint("boundary", passive=(0, 1000, 1000), truncate=(1, 5000, 4000) if i % 2 else (0, 0, 0),
                           seconds=7.1 if i % 2 else 0.04, wal_before=123_456_789, wal_after=0, readers=readers)
    phases = [{"phase": n, "ms": 123.4} for n in ("key", "header", "integrity_probe", "checkpoint", "init_db", "schema_gate",
                                                  "verify", "wal_replay", "pool_warm", "indexes")]
    steps = [{"step": f"ensure_something_{k}", "ms": 400.5 - k} for k in range(40)]
    for _ in range(se.KEEP["open"] + 4):
        se.note_open("unlock", total_ms=4321.0, phases=phases, wal_bytes_before=987_654_321, pages=_PAGES_AT_THE_WIDEST,
                     init_db={"total_ms": 1500.5, "process_call": 2, "earlier_complete_calls": 0, "complete": True, "steps": steps})
    _fill_runs()
    for _ in range(se.KEEP["pool_timeout"] + 4):
        se.note_pool_timeout(
            waited_s=30.0, thread=nm("AnyIO worker thread"), route=nm("GET /api/analytics/keywords/{id}/trend"), collector=False,
            pool_size=8, overflow=64, timeout_s=30.0, checked_out=72,
            holders=[{"thread": nm(f"oo-collector-worker-{k}"), "endpoint": nm("POST /api/collect/run"), "age_s": 600.1 + k,
                      "collector": True, "pool": "corpus"} for k in range(3)])


@pytest.mark.parametrize("long_names", [False, True], ids=["ordinary-names", "every-name-at-the-cut"])
def test_the_storage_events_budget_holds_a_full_journal(journal, long_names):
    """WHAT THE SLOT'S NUMBER PROTECTS (``diagnostics_slots.SLOTS``): the budget is the size measured here, at full retention of
    every kind, with the events the hooks write. Measured 78,634 bytes with ordinary names and 123,344 with every name at the cut, 1,494 of which are the keep rule's (``picked_by`` on the 50 events of the four split kinds, and the method sentence and ``keep_rule`` lines) (a byte or two either way: every event carries the process id; the run kinds carry the figures of the legacy restore, the newsletter import and the folder modes),
    the checkpoints carrying the reader snapshot ``hygiene`` hands every one (not only the busy ones); the row says 125,000. A kind that grows an event past the budget fails here, before it reaches a zip.

    THE SPLIT OF A HOLD'S SECONDS (``seconds_by``, build (a) of 17 Oct) is the part that gives way. With all twenty holds carrying it (125 bytes each at its widest, a day-long hold) and its sentence in the method (a few hundred bytes), the same journals measure 81,453 bytes with ordinary names and 126,163 with every name at the cut, over the row by 1,163; the member built at the row's budget (124,990 bytes) takes the split off the shortest holds until it fits and keeps it on the other 6, counting the 14 it cut. Ordinary names keep all twenty."""
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    _fill_like_the_hooks(long_names)
    m = se.diagnostics_member(10**9)
    for kind, cap in se.KEEP.items():
        assert m["kinds"][kind]["kept"] == min(cap, m["kinds"][kind]["total"]), kind
    assert m["kinds"]["gate_hold"]["kept"] == 20 and m["kinds"]["checkpoint_notable"]["kept"] == 10, "full retention"
    size = len(json.dumps(m, separators=(",", ":")))
    assert size >= 20_000, "the fixture still resembles the real events"
    # The split of a hold's seconds (``seconds_by``) is the part that gives way: at the widest names the journal with all twenty splits is
    # over the row, so the member built at the row's budget cuts the splits from the shortest holds (never an event) until it fits.
    at_budget = se.diagnostics_member(slot.budget_bytes)
    assert len(json.dumps(at_budget, separators=(",", ":"))) <= slot.budget_bytes, f"{size} bytes with every split, the row says {slot.budget_bytes}"
    assert at_budget["dropped_to_fit"] == {}, "no event is dropped to fit: only splits are"
    assert at_budget["kinds"]["gate_hold"]["kept"] == 20
    if not long_names:
        assert size <= slot.budget_bytes and "seconds_by_omitted_to_fit" not in at_budget["kinds"]["gate_hold"], "ordinary names: every hold keeps its split"
    assert len(json.dumps(m["kinds"]["gate_hold"]["events"][0])) < se.MAX_EVENT_BYTES


def _carrying(member: dict) -> list[dict]:
    return [e for e in member["kinds"]["gate_hold"]["events"] if "omitted" not in e["seconds_by"]]


def test_the_split_stays_on_as_many_of_the_longest_holds_as_the_free_bytes_allow(journal):
    """The count is computed from the budget, never fixed: with every name at the cut the member is over the row by the splits, and
    the shortest holds give theirs up first. Four properties, each one a way the rule is wrong: it fits; the holds that keep it are the
    longest; it is MAXIMAL (putting one more back overflows); and each hold without one says why, counted."""
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    _fill_like_the_hooks(True)
    m = se.diagnostics_member(slot.budget_bytes)
    holds = m["kinds"]["gate_hold"]["events"]
    cut = [e for e in holds if e["seconds_by"].get("omitted") == se.OMITTED_TO_FIT]
    kept = _carrying(m)
    assert kept and cut, "the widest journal is over the row by the splits: some are kept and some are cut"
    assert len(kept) + len(cut) == 20 == len(holds), "every hold is still there; the others carry a reason"
    assert m["kinds"]["gate_hold"]["seconds_by_omitted_to_fit"] == len(cut)
    assert min(e["seconds"] for e in kept) >= max(e["seconds"] for e in cut), "the longest holds keep the split"
    # Maximal: give the longest cut hold its split back (and take the counter down by one) and the member no longer fits.
    back = copy.deepcopy(m)
    longest_cut = max((e for e in back["kinds"]["gate_hold"]["events"] if e["seconds_by"].get("omitted")), key=lambda e: e["seconds"])
    longest_cut["seconds_by"] = dict.fromkeys(_SECONDS_BY_KEYS, 86_400.0)
    back["kinds"]["gate_hold"]["seconds_by_omitted_to_fit"] -= 1
    if not back["kinds"]["gate_hold"]["seconds_by_omitted_to_fit"]:
        del back["kinds"]["gate_hold"]["seconds_by_omitted_to_fit"]
    assert len(json.dumps(back, separators=(",", ":"), ensure_ascii=False).encode()) > slot.budget_bytes, "one more split would have fitted: the count is not the most the free bytes allow"
    # The count follows the budget: a bigger budget keeps more, an unlimited one keeps all twenty.
    assert len(_carrying(se.diagnostics_member(slot.budget_bytes + 1_000))) > len(kept)
    assert len(_carrying(se.diagnostics_member(10**9))) == 20


def test_a_hold_without_a_split_says_why_and_never_shows_zeros(journal):
    se.record("gate_hold", {"holder": "old", "seconds": 40.0}, key=("hold", 1))  # written by a build without the field
    se.record("gate_hold", {"holder": "new", "seconds": 50.0, "seconds_by": dict.fromkeys(_SECONDS_BY_KEYS, 1.5)}, key=("hold", 2))
    holds = {e["holder"]: e for e in _events("gate_hold")}
    assert holds["old"]["seconds_by"] == {"omitted": se.OMITTED_UNKNOWN}
    assert holds["new"]["seconds_by"] == dict.fromkeys(_SECONDS_BY_KEYS, 1.5)
    assert "insert" not in holds["old"]["seconds_by"], "an unmeasured split is a reason, not zeros"


def test_a_cut_split_is_the_members_only_the_file_keeps_it(journal):
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    _fill_like_the_hooks(True)
    se.diagnostics_member(slot.budget_bytes)
    se.flush()
    on_disk = json.loads(journal.read_text(encoding="utf-8"))["kinds"]["gate_hold"]["events"]
    assert len(on_disk) == 20 and all(isinstance(e["seconds_by"], dict) and "omitted" not in e["seconds_by"] for e in on_disk), "building the member cut nothing in the journal"
    assert len(_carrying(se.diagnostics_member(10**9))) == 20


def test_the_hard_ceiling_is_the_event_cap_times_the_largest_event_and_still_fits_one_part():
    ceiling = sum(se.KEEP.values()) * se.MAX_EVENT_BYTES
    # 300,000 is the 100 events of the nine kinds at the largest size one may be; the first number here (250,000) was the ceiling of the
    # six kinds that existed then. What protects the zip is the next line, which does not move.
    assert ceiling <= 300_000, ceiling
    assert ceiling < 4_000_000 // 10, "even a journal of worst-case events is a small part of the zip's 4 MB"


def test_the_slot_is_registered_for_the_database_area_and_resolves():
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    assert slot.target == "src.monitoring.storage_events:diagnostics_member" and slot.owner == "WAL"
    assert slots.area_of("storage-events.json") == "database"
    assert slots.resolve(slot) is se.diagnostics_member and slots.module_in_build(slot)


# --------------------------------------------------------------------------- #
#  2. The passphrase rule: a planted marker reaches neither the file, the member nor the slot
# --------------------------------------------------------------------------- #
def _no_marker_anywhere(journal_path) -> None:
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    se.flush()
    on_disk = journal_path.read_text(encoding="utf-8")
    member = json.dumps(se.diagnostics_member(10**9))
    through_the_slot = json.dumps(slots.thunk(slot)())
    for where, text in (("the journal file", on_disk), ("the member", member), ("the slot's answer", through_the_slot)):
        assert MARKER not in text, f"the held passphrase reached {where}"
        assert MARKER.split("-")[1] not in text.replace("MARKER", ""), f"a piece of the passphrase reached {where}"


def test_a_planted_passphrase_is_taken_out_of_every_field_of_every_kind(journal, held_passphrase):
    se.record("gate_hold", {"holder": f"worker-{MARKER}", "route": f"GET /{MARKER}", "frames": [f"m:{MARKER}:1"], MARKER: 1})
    se.record("guard", {"kind": MARKER, "ended_by": f"after {MARKER}"}, key="guard")
    se.update("guard", "guard", {"note": MARKER})
    se.end("guard", "guard", {"ended_by": MARKER})
    se.note_checkpoint(MARKER, outcome="failed", error=f"OperationalError {MARKER}", readers=[{"thread": MARKER, "endpoint": MARKER}],
                       extra={MARKER: MARKER})
    se.note_open(MARKER, phases=[{"phase": MARKER, "ms": 1}], init_db={"steps": [{"step": MARKER, "ms": 3}], "complete": True})
    se.note_pool_timeout(thread=MARKER, route=MARKER, holders=[{"thread": MARKER, "endpoint": MARKER, "age_s": 1}])
    assert _member()["kinds"]["gate_hold"]["total"] == 1, "the events were recorded, only the secret is gone"
    _no_marker_anywhere(journal)


def test_a_passphrase_the_process_holds_is_scrubbed_in_a_file_written_before_it_was_set(journal, monkeypatch):
    """The file is read back at the next start, which may hold a different passphrase than the one that wrote it; the member is
    scrubbed again on its way out, so a value an earlier process wrote is not a way around the rule."""
    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-13T10:00:00+00:00", "kinds": {
            "gate_hold": {"total": 1, "events": [{"at": "2026-10-13T10:00:00+00:00", "proc": "old", "holder": f"w-{MARKER}"}]}}}),
        encoding="utf-8",
    )
    import src.database.connect as connect_mod

    monkeypatch.setattr(connect_mod, "_passphrase", MARKER)
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    assert MARKER not in json.dumps(slots.thunk(slot)()), "the slot's net scrubs what the file held"


def test_a_checkpoint_that_fails_on_a_message_with_the_passphrase_records_the_class_only(journal, held_passphrase, tmp_path):
    from src.scheduler import hygiene

    eng = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)

    def boom(*_a, **_k):
        raise RuntimeError(f"cannot open {tmp_path}/c.db with key {MARKER}")

    eng.raw_connection = boom  # type: ignore[method-assign]
    errors: list[str] = []
    assert hygiene.checkpoint_wal(engine=eng, force=True, errors=errors) is None
    (e,) = _events("checkpoint")
    assert (e["outcome"], e["error"], e["trigger"]) == ("failed", "RuntimeError", "forced")
    assert "c.db" not in json.dumps(_member()), "no path out of an exception message"
    _no_marker_anywhere(journal)
    eng.dispose()


def test_a_write_gate_hold_by_a_thread_named_with_the_passphrase_is_scrubbed(journal, held_passphrase, monkeypatch):
    from src.database import writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    taken, let_go = threading.Event(), threading.Event()

    def hold():
        gate.acquire()
        taken.set()
        let_go.wait(5)
        gate.release()

    t = threading.Thread(target=hold, name=f"worker-{MARKER}", daemon=True)
    t.start()
    assert taken.wait(3)
    time.sleep(0.1)
    writer.watchdog_tick(gate, None)
    let_go.set()
    t.join(5)
    assert _member()["kinds"]["gate_hold"]["total"] == 1
    _no_marker_anywhere(journal)


# --------------------------------------------------------------------------- #
#  3. Best effort: a journal that cannot write, or cannot record, never reaches the site
# --------------------------------------------------------------------------- #
def test_a_journal_that_cannot_write_counts_the_failure_by_class_and_keeps_serving(journal, monkeypatch):
    def full_disk(_a, _b):
        raise OSError(errno.ENOSPC, f"No space left on device: '{journal}' {MARKER}")

    _on_journal_replace(monkeypatch, journal, full_disk)
    se.record("guard", {"kind": "disk"})
    se.flush()  # the synchronous path raises nothing either
    assert _wait_until(lambda: _member()["file"]["write_failures"] >= 1)
    f = _member()["file"]
    assert f["last_write_failure"] == "OSError ENOSPC", "the class and the errno's NAME, never the message with its path"
    assert _member()["kinds"]["guard"]["total"] == 1, "the in-memory record still serves the live zip"
    assert not list(journal.parent.glob("*.tmp")), "no half-written temporary file is left on a full disk"


def test_the_background_writer_outlives_a_failed_write(journal, monkeypatch):
    calls = {"n": 0}
    real = se.os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.EIO, "I/O error")
        return real(a, b)

    _on_journal_replace(monkeypatch, journal, flaky)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: _member()["file"]["write_failures"] == 1)
    se.record("guard", {"n": 2})
    assert _wait_until(journal.exists), "the next change is written by the same thread"
    assert _member()["file"]["last_write_ok_at"] is not None


def _records_promptly(n: int = 300) -> float:
    """Record ``n`` events of every shape a site records and return the seconds it took (the assertion is the caller's)."""
    started = time.monotonic()
    for i in range(n):
        se.record("gate_hold", {"n": i}, key=f"k{i % 5}")
        se.update("gate_hold", f"k{i % 5}", {"m": i})
        se.end("gate_hold", f"k{i % 5}")
        se.note_pool_timeout(waited_s=1.0)
    return time.monotonic() - started


def test_a_recording_never_waits_for_a_write_that_is_stuck_on_the_disk(journal, monkeypatch):
    """The coordinator's (a): the measured sites take only the short lock for the dict update. The writer copies under the lock and
    writes outside it, so a write that hangs (a full or failing drive, which is when the guard engages) holds nothing a site needs."""
    entered, release = threading.Event(), threading.Event()
    real = se.os.replace

    def stuck(a, b):
        entered.set()
        release.wait(10)
        return real(a, b)

    _on_journal_replace(monkeypatch, journal, stuck)
    se.record("guard", {"n": 0})
    assert entered.wait(3), "the writer is now inside the disk write"
    took = _records_promptly()
    assert took < 2.0, f"1,200 recordings took {took:.2f}s while the write was stuck"
    assert _member()["kinds"]["gate_hold"]["total"] == 300, "the member answers from memory while the write is stuck"
    release.set()
    assert _wait_until(lambda: _file_total(journal, "gate_hold") == 300)


def test_a_recording_never_waits_for_the_writers_first_read_of_the_file(journal, monkeypatch):
    """The same condition for the other disk touch: the writer reads the file before its first write, and a hung read holds no lock
    a recording takes."""
    entered, release = threading.Event(), threading.Event()
    real = se._read_file

    def stuck():
        entered.set()
        release.wait(10)
        return real()

    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-01T00:00:00+00:00", "kinds": {"guard": {"total": 4, "events": []}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(se, "_read_file", stuck)
    se.record("guard", {"n": 0})
    assert entered.wait(3), "the writer is now inside its read of the file"
    took = _records_promptly()
    assert took < 2.0, f"1,200 recordings took {took:.2f}s while the read was stuck"
    release.set()
    assert _wait_until(lambda: _file_total(journal, "guard") == 5), "the history the file held is extended, not replaced"


def test_a_writer_that_dies_is_counted_once_kept_by_class_and_replaced_by_the_next_change(journal, monkeypatch):
    """The coordinator's (c): a writer that ends from something that is not an Exception takes nothing down with it, says so once
    (by class, never the message), and the next change starts a new one."""

    class Died(BaseException):
        pass

    def die(*_a, **_k):
        raise Died(f"the thread was killed {MARKER}")

    real = se._write
    monkeypatch.setattr(se, "_write", die)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._WRITER_DEATHS == 1), "the death is counted"
    assert _wait_until(lambda: se._THREAD is not None and not se._THREAD.is_alive())
    assert se._WRITER_DEATHS == 1, "once"
    out = _member()
    assert out["file"]["writer_deaths"] == 1 and out["file"]["last_internal_failure"] == "the writer thread ended: Died"
    assert MARKER not in json.dumps(out)
    assert not journal.exists()
    monkeypatch.setattr(se, "_write", real)
    se.record("guard", {"n": 2})
    assert _wait_until(journal.exists), "a new writer was started by the next change"
    assert json.loads(journal.read_text(encoding="utf-8"))["kinds"]["guard"]["total"] == 2
    assert _member()["file"]["writer_deaths"] == 1


def test_a_flush_writes_what_the_writer_has_not_written_and_a_second_one_writes_nothing(journal, monkeypatch):
    """The coordinator's (b): the clean stop's last write. The writer is a second behind by design, so the last events of a session
    would be lost without it; a flush of what is already in the file is not a second write."""
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 30.0)
    replaced: list[int] = []
    real = se.os.replace
    _on_journal_replace(monkeypatch, journal, lambda a, b: (replaced.append(1), real(a, b))[1])
    se.record("guard", {"kind": "disk"}, key="e1")
    se.end("guard", "e1", {"ended_by": "release"})
    assert not journal.exists(), "the writer is still inside its delay"
    se.flush()
    data = json.loads(journal.read_text(encoding="utf-8"))
    assert data["kinds"]["guard"]["total"] == 1 and data["kinds"]["guard"]["events"][0]["ended_by"] == "release"
    se.flush()
    assert len(replaced) == 1, "the second flush found everything in the file"


def test_a_flush_after_the_writer_has_written_is_not_a_second_write(journal, monkeypatch):
    replaced: list[int] = []
    real = se.os.replace
    _on_journal_replace(monkeypatch, journal, lambda a, b: (replaced.append(1), real(a, b))[1])
    se.record("guard", {"n": 1})
    assert _wait_until(journal.exists)
    assert _wait_until(lambda: se._WRITTEN_VERSION == se._VERSION)
    se.flush()
    assert len(replaced) == 1


def test_a_flush_of_a_journal_that_recorded_nothing_leaves_the_file_as_it_is(journal):
    journal.write_text("{not this journal", encoding="utf-8")
    se.flush()
    assert journal.read_text(encoding="utf-8") == "{not this journal"


def test_a_flush_retries_a_write_the_writer_could_not_make(journal, monkeypatch):
    """A failed write leaves the version unwritten, so the clean stop tries again; it does not conclude the file is current."""
    real = se.os.replace

    def full_disk(_a, _b):
        raise OSError(errno.ENOSPC, "No space left on device")

    _on_journal_replace(monkeypatch, journal, full_disk)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._WRITE_FAILURES >= 1)
    monkeypatch.setattr(se.os, "replace", real)
    se.flush()
    assert json.loads(journal.read_text(encoding="utf-8"))["kinds"]["guard"]["total"] == 1


def test_the_final_flush_is_registered_for_the_interpreters_end_and_runs_in_the_lifespan_before_the_clean_stamp(journal, monkeypatch):
    registered: list = []
    monkeypatch.setattr(se.atexit, "register", registered.append)
    monkeypatch.setattr(se, "_ATEXIT", False)
    se.record("guard", {"n": 1})
    assert registered == [se.flush], "atexit covers a stop that is not the lifespan's"
    import inspect

    import src.api.main as main

    src = inspect.getsource(main.lifespan)
    i_dispose, i_flush, i_stamp = src.index("dispose_engine()"), src.index("_storage_events.flush()"), src.index("record_clean_shutdown()")
    assert i_dispose < i_flush < i_stamp, "the journal's last write comes after the store is disposed and before the clean-stop stamp"


@pytest.mark.parametrize(
    "broken", ["_build", "_clean", "_read_file", "_mark_dirty_locked", "_snapshot_locked", "_combined_locked"]
)
def test_no_public_function_raises_whatever_breaks_inside(journal, monkeypatch, broken):
    """Each internal is made to raise; every function a site calls still returns, and the failure is counted."""

    def boom(*_a, **_k):
        raise RuntimeError(f"internal failure {MARKER}")

    monkeypatch.setattr(se, broken, boom)
    se.record("gate_hold", {"n": 1}, key="k")
    se.update("gate_hold", "k", {"n": 2})
    se.end("gate_hold", "k", {"n": 3})
    se.note_checkpoint("boundary", passive=(0, 1, 1), truncate=(0, 1, 1), seconds=1.0)
    se.note_open("unlock", total_ms=1.0, phases=[{"phase": "a", "ms": 1}], init_db={"steps": []})
    se.note_pool_timeout(waited_s=1.0, holders=[{"thread": "t"}])
    se.flush()
    out = se.diagnostics_member(100_000)
    assert isinstance(out, dict)
    assert MARKER not in json.dumps(out), "the failure is recorded by class, never by message"


def test_garbage_handed_to_the_builders_does_not_raise(journal):
    se.note_checkpoint("boundary", passive="not a row", truncate=(1, 2), seconds="slow", wal_before=object(), readers=object())
    se.note_open("unlock", phases="nope", init_db=["not", "a", "record"])
    se.note_open("boot", init_db={"steps": [{"ms": "x"}, "y", None]})
    se.note_pool_timeout(holders=object(), waited_s="soon")
    assert _member()["kinds"]["checkpoint"]["total"] == 1 and _member()["kinds"]["open"]["total"] == 2


def test_a_site_carries_on_when_the_journal_cannot_write_gate_guard_checkpoint_and_pool(journal, guard_on, monkeypatch, tmp_path):
    """The condition itself (the coordinator's third): the journal's write FAILS, as it does on the full or hung drive that is exactly
    when the guard engages, and the measured sites still do their work and return what they always returned."""
    from src.database import writer
    from src.scheduler import hygiene
    from src.scheduler.storage_guard import GIB, StorageGuard

    def full_disk(_a, _b):
        raise OSError(errno.ENOSPC, f"No space left on device {MARKER}")

    _on_journal_replace(monkeypatch, journal, full_disk)

    # the write gate: a long hold is journaled, released, and the gate is usable again
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.01)
    gate = writer.WriterGate()
    gate.acquire()
    time.sleep(0.03)
    writer.watchdog_tick(gate, None)
    gate.release()
    assert gate.acquire(timeout=1.0) is True
    gate.release()

    # the storage guard: it trips and it releases, with its accounting intact
    clock = _Clock()
    g = StorageGuard(clock=clock, trip_after=2, resume_after=2)
    feed = {"corpus_bytes": 10 * GIB, "disk_free_bytes": 300 * GIB, "disk_total_bytes": 500 * GIB}
    for _ in range(2):
        g.observe(wal_bytes=3 * GIB, **feed)
    assert g.engaged is True
    clock.advance(30.0)
    for _ in range(2):
        g.observe(wal_bytes=0, **feed)
    assert g.engaged is False and g.state()["engagements"] == 1

    # a checkpoint: the record it returns is the normal one
    eng, _db = _wal_engine(tmp_path)
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    rec = hygiene.checkpoint_wal(engine=eng, force=True)
    assert rec is not None and rec["busy"] == 0 and rec["wal_bytes_after"] == 0
    eng.dispose()

    # the pool: the timeout it raises is still its own
    pool_eng = _pool_engine(timeout=0.05)
    held = pool_eng.raw_connection()
    with pytest.raises(PoolTimeoutError):
        pool_eng.raw_connection()
    held.close()
    pool_eng.dispose()

    se.flush()
    f = _member()["file"]
    assert f["write_failures"] >= 1 and f["last_write_failure"] == "OSError ENOSPC", "the failure is counted, by class and errno"
    kinds = _member()["kinds"]
    assert kinds["gate_hold"]["total"] == 1 and kinds["guard"]["total"] == 1 and kinds["checkpoint"]["total"] == 1
    assert kinds["pool_timeout"]["total"] == 1, "and every event is still in memory for the live zip"
    assert MARKER not in json.dumps(_member())


# --------------------------------------------------------------------------- #
#  The sites: the write gate
# --------------------------------------------------------------------------- #
class _Holder:
    """Holds a gate from a NAMED thread until told to let go."""

    def __init__(self, gate, name: str = "field-writer") -> None:
        self.gate = gate
        self.taken = threading.Event()
        self.let_go = threading.Event()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        self.gate.acquire()
        self.taken.set()
        self.let_go.wait(10)
        self.gate.release()

    def __enter__(self):
        self.thread.start()
        assert self.taken.wait(3)
        return self

    def __exit__(self, *_exc) -> None:
        self.let_go.set()
        self.thread.join(5)
        assert not self.thread.is_alive()


def test_a_long_hold_is_opened_by_the_watchdog_updated_on_each_sample_and_closed_at_release(journal, monkeypatch):
    from src.database import writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    with _Holder(gate, "field-writer"):
        time.sleep(0.1)
        warned = writer.watchdog_tick(gate, None)
        (e,) = _events("gate_hold")
        assert e["open"] is True and e["holder"] == "field-writer", "held, and not yet released: the record says so"
        assert e["frames"] is not None and isinstance(e["frames"], list), "the frames the watchdog saw"
        first_seconds = e["seconds"]
        time.sleep(0.05)
        writer.watchdog_tick(gate, warned)
        (e,) = _events("gate_hold")
        assert e["seconds"] > first_seconds and _member()["kinds"]["gate_hold"]["total"] == 1, "updated, not a second entry"
    (e,) = _events("gate_hold")
    assert e["open"] is False and "ended_at" in e and e["seconds"] >= 0.1
    assert e["holder"] == "field-writer"


def test_a_hold_the_watchdog_never_saw_is_recorded_whole_at_release_and_says_so(journal, monkeypatch):
    from src.database import writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    gate = writer.WriterGate()
    with _Holder(gate, "quick-sampler-miss"):
        time.sleep(0.08)  # no watchdog_tick: the 15-second sample missed it
    (e,) = _events("gate_hold")
    assert e["sampled_while_held"] is False and e["holder"] == "quick-sampler-miss" and e["seconds"] >= 0.05
    assert "frames" not in e, "no stack was captured while it lasted, and none is invented"


def test_a_short_hold_is_not_journaled(journal):
    from src.database import writer

    gate = writer.WriterGate()
    with _Holder(gate):
        time.sleep(0.02)
    assert _member()["kinds"]["gate_hold"]["total"] == 0, "a hold under HOLD_RECORD_S is a slow batch, not an event"
    assert writer.HOLD_RECORD_S == 30.0, "the threshold the plan and the docs state"


def test_the_per_holder_table_counts_holds_and_seconds_and_is_bounded():
    from src.database import writer

    gate = writer.WriterGate()
    for name in ("alpha", "beta", "alpha"):
        with _Holder(gate, name):
            time.sleep(0.01)
    by = {r["holder"]: r for r in gate.stats()["by_holder"]}
    assert by["alpha"]["holds"] == 2 and by["beta"]["holds"] == 1
    assert by["alpha"]["held_s"] >= 0.02 and by["alpha"]["longest_s"] <= by["alpha"]["held_s"]
    assert gate.stats()["by_holder"][0]["holder"] == "alpha", "most seconds held first"
    for i in range(writer._HOLDER_NAMES_MAX + 6):
        with _Holder(gate, f"pool-worker-{i}"):
            pass
    rows = gate.stats()["by_holder"]
    assert len(rows) <= writer._HOLDER_NAMES_MAX + 1 and writer._OTHER_HOLDERS in {r["holder"] for r in rows}, "past the bound they are summed, not listed"
    assert sum(r["holds"] for r in rows) == 3 + writer._HOLDER_NAMES_MAX + 6, "and none is lost from the count"


def test_the_write_gate_report_points_at_the_journal_and_carries_the_pool_as_configured(monkeypatch):
    from src.api.diagnostics import write_gate_report

    monkeypatch.setenv("OO_DB_POOL_TIMEOUT", "45")
    out = write_gate_report()
    assert out["history_in"] == "storage-events.json"
    cfg = out["pool_config"]
    assert cfg["pool_size"] >= 1 and cfg["max_overflow"] is not None and cfg["timeout_s"] is not None
    assert "pool_timeout" in cfg["set_by_the_operator"], "an operator's variable is named as theirs"
    assert "by_holder" in out["gate"]


# --------------------------------------------------------------------------- #
#  The sites: the storage guard
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def test_a_guard_engagement_is_opened_at_the_trip_and_closed_at_the_release(journal, guard_on):
    from src.scheduler.storage_guard import GIB, StorageGuard

    clock = _Clock()
    g = StorageGuard(clock=clock, trip_after=2, resume_after=2)
    feed = {"corpus_bytes": 10 * GIB, "disk_free_bytes": 300 * GIB, "disk_total_bytes": 500 * GIB}
    for _ in range(2):
        g.observe(wal_bytes=3 * GIB, **feed)
    (e,) = _events("guard")
    assert e["open"] is True and e["kind"] == "wal" and e["wal_bytes_at_trip"] == 3 * GIB
    assert e["wal_high_bytes"] and e["disk_reserve_bytes"], "the numbers that tripped it"
    clock.advance(120.0)
    for _ in range(2):
        g.observe(wal_bytes=0, **feed)
    (e,) = _events("guard")
    assert e["open"] is False and e["ended_by"] == "measurement"
    assert e["seconds"] >= 120.0 and e["peak_wal_bytes"] >= 3 * GIB and e["wal_bytes_at_end"] == 0
    assert _member()["kinds"]["guard"]["total"] == 1


def test_an_engagement_ended_by_an_explicit_start_says_so(journal, guard_on):
    from src.scheduler.storage_guard import GIB, StorageGuard

    g = StorageGuard(clock=_Clock(), trip_after=1, resume_after=1)
    g.observe(wal_bytes=3 * GIB, corpus_bytes=10 * GIB, disk_free_bytes=300 * GIB, disk_total_bytes=500 * GIB)
    assert g.engaged is True
    g.reset()
    (e,) = _events("guard")
    assert e["open"] is False and "explicit start" in e["ended_by"]


# --------------------------------------------------------------------------- #
#  The sites: every checkpoint, under who asked
# --------------------------------------------------------------------------- #
def _wal_engine(tmp_path, name="ckpt.db"):
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)
    with eng.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(50):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng, db


@pytest.fixture()
def ckpt(monkeypatch):
    from src.scheduler import hygiene

    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    return hygiene.checkpoint_wal


def test_the_boundary_checkpoint_is_journaled_with_its_rows_seconds_and_log_before_and_after(journal, ckpt, tmp_path):
    eng, _db = _wal_engine(tmp_path)
    assert ckpt(engine=eng) is not None
    (e,) = _events("checkpoint")
    assert (e["trigger"], e["outcome"]) == ("boundary", "done")
    assert e["passive"][0] == 0 and e["truncate"][0] == 0 and e["wal_bytes_before"] > 0 and e["wal_bytes_after"] == 0
    assert e["seconds"] >= 0
    assert _member()["kinds"]["checkpoint_notable"]["total"] == 0, "a plain drained checkpoint is not notable"
    eng.dispose()


def test_a_forced_checkpoint_is_the_restores_and_a_guard_drain_is_the_guards(journal, ckpt, tmp_path):
    eng, _db = _wal_engine(tmp_path)
    ckpt(engine=eng, force=True)
    with se.checkpoint_trigger("guard"):
        assert se.current_trigger() == "guard"
        ckpt(engine=eng, force=True)
    assert se.current_trigger() == "boundary", "the context ends with the block"
    assert [e["trigger"] for e in _events("checkpoint")] == ["forced", "guard"]
    eng.dispose()


def test_a_checkpoint_pinned_by_a_reader_is_also_kept_among_the_notable_ones(journal, ckpt, tmp_path):
    eng, db = _wal_engine(tmp_path)
    reader = sqlite3.connect(str(db))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM t").fetchone()
    with eng.connect() as c:  # new frames after the reader's snapshot
        c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    try:
        rec = ckpt(engine=eng, force=True, busy_timeout_ms=0)
        assert rec is not None and rec["busy"] == 1
    finally:
        reader.close()
    (n,) = _events("checkpoint_notable")
    assert n["why"] == "a reader pinned the log" and n["truncate"][0] == 1
    assert _member()["kinds"]["checkpoint"]["total"] == 1
    eng.dispose()


def test_a_checkpoint_refused_by_a_busy_gate_is_recorded_as_skipped(journal, ckpt, tmp_path):
    from src.database import writer

    eng, _db = _wal_engine(tmp_path)
    with _Holder(writer.write_gate, "busy-writer"):
        rec = ckpt(engine=eng, force=True, gate_timeout_s=0.05)
    assert rec is not None and rec["skipped"] == "gate busy"
    (e,) = _events("checkpoint")
    assert e["outcome"] == "skipped" and e["error"] == "WriteGateBusy" and e["seconds"] == 0.05
    assert _events("checkpoint_notable")[0]["why"] == "refused or failed"
    eng.dispose()


def test_a_slow_checkpoint_is_notable_whatever_its_rows_say(journal):
    se.note_checkpoint("boundary", passive=(0, 9, 9), truncate=(0, 0, 0), seconds=se.NOTABLE_CHECKPOINT_S + 0.1)
    se.note_checkpoint("boundary", passive=(0, 9, 9), truncate=(0, 0, 0), seconds=0.1)
    assert [e["why"] for e in _events("checkpoint_notable")] == ["slow"]
    assert _member()["kinds"]["checkpoint"]["total"] == 2


def test_notable_checkpoints_reach_back_past_the_ten_newest_plain_ones(journal):
    se.note_checkpoint("boundary", passive=(0, 9, 9), truncate=(1, 9, 4), seconds=0.1)
    for _ in range(40):
        se.note_checkpoint("boundary", passive=(0, 0, 0), truncate=(0, 0, 0), seconds=0.01)
    assert len(_events("checkpoint")) == 10 and not any(e["truncate"][0] == 1 for e in _events("checkpoint"))
    assert [e["truncate"][0] for e in _events("checkpoint_notable")] == [1], "the pinned one is still there"


def test_the_backup_drain_is_one_event_not_one_per_retry(journal, monkeypatch, tmp_path):
    from src.backup import stream_backup

    rows = iter([(0, 5, 5), (1, 9, 4), (1, 9, 4), (0, 0, 0)])
    monkeypatch.setattr(stream_backup, "_wal_row", lambda mode: next(rows))
    monkeypatch.setattr(stream_backup, "_wal_complete", lambda _p, row: row == (0, 0, 0) or (row == (0, 5, 5) and False))
    monkeypatch.setattr(stream_backup.time, "sleep", lambda _s: None)
    assert stream_backup._drain_wal(tmp_path / "x.db") is None
    (e,) = _events("checkpoint")
    assert e["trigger"] == "backup" and e["truncate_tries"] == 3 and e["truncate"] == [0, 0, 0] and e["passive"] == [0, 5, 5]


def test_the_snapshot_truncate_is_journaled(journal, tmp_path):
    from src.database import connect as connect_mod

    src = tmp_path / "live.db"
    con = sqlite3.connect(str(src))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    if not connect_mod._quiesced_file_copy(src, tmp_path / "copy.db"):
        pytest.skip("the quiesced copy refuses on this build (gate off or a reader); the codec path journals nothing")
    (e,) = _events("checkpoint")
    assert e["trigger"] == "snapshot" and e["truncate"][0] == 0 and e["seconds"] >= 0


# --------------------------------------------------------------------------- #
#  The sites: opening the store
# --------------------------------------------------------------------------- #
def test_an_unlock_is_journaled_with_its_phases_the_log_at_open_and_the_slowest_init_db_steps(journal, monkeypatch, tmp_path):
    from src.api.unlock import _forensic_timer
    from src.database import init_steps
    from src.monitoring import forensics

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)

    @init_steps.recorded
    def body():
        init_steps.step("create_all")
        init_steps.step("ensure_fts")

    body()
    t = _forensic_timer(wal_state={"bytes": 123_456, "state": "present", "reason": "x"})
    t.phase("passphrase verify")
    t.note_init_db()
    forensics.record_session_start()
    t.finish()
    (e,) = _events("open")
    assert e["via"] == "unlock" and e["wal_bytes_before_open"] == 123_456
    assert e["phases"] and e["phases"][0][0] == "passphrase verify"
    assert e["init_db"]["complete"] is True and len(e["init_db"]["slowest"]) == 2
    last = forensics.session_forensics()["last_unlock"]
    assert e["total_ms"] == last["synchronous_total_ms"], "the journal and the unlock record say the same number"


def test_a_boot_that_opened_the_store_is_journaled_and_one_that_raised_is_not(journal, monkeypatch):
    from src.api import main as main_mod
    from src.database import init_steps

    complete = {"steps": [{"step": "create_all", "ms": 5.0}, {"step": "ensure_fts", "ms": 9.0}], "total_ms": 14.0,
                "process_call": 1, "earlier_complete_calls": 0, "complete": True}
    failed = {"steps": [{"step": "create_all", "ms": 1.0}], "total_ms": 1.0, "process_call": 1, "complete": False}
    monkeypatch.setattr(init_steps, "first_record", lambda: complete)
    monkeypatch.setattr(init_steps, "last_record", lambda: complete)
    main_mod._note_boot_init_db()
    (e,) = _events("open")
    assert e["via"] == "boot" and e["init_db"]["slowest"][0] == ["ensure_fts", 9.0]
    monkeypatch.setattr(init_steps, "first_record", lambda: None)
    monkeypatch.setattr(init_steps, "last_record", lambda: failed)
    main_mod._note_boot_init_db()
    assert _member()["kinds"]["open"]["total"] == 1, "a call that raised opened nothing and keeps no line"


# --------------------------------------------------------------------------- #
#  The sites: the pool's checkout timeout
# --------------------------------------------------------------------------- #
def _pool_engine(timeout: float = 0.1):
    from src.database.pool_reserve import ReservingQueuePool

    return create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(":memory:", check_same_thread=False),
        poolclass=ReservingQueuePool, pool_size=1, max_overflow=0, pool_timeout=timeout,
    )


def test_a_pool_timeout_is_journaled_with_who_held_the_connections_and_the_error_is_unchanged(journal):
    from src.database import pool_watch

    eng = _pool_engine(timeout=0.1)
    pool_watch.register(eng, label="events-test")
    taken, let_go = threading.Event(), threading.Event()
    held = []

    def hold():
        held.append(eng.raw_connection())
        taken.set()
        let_go.wait(5)
        held[0].close()

    t = threading.Thread(target=hold, name="the-holder", daemon=True)
    t.start()
    assert taken.wait(3)
    began = time.monotonic()
    with pytest.raises(PoolTimeoutError) as raised:
        eng.raw_connection()
    waited = time.monotonic() - began
    let_go.set()
    t.join(5)
    assert "timed out" in str(raised.value), "the pool's own error, not ours"
    (e,) = _events("pool_timeout")
    assert e["pool_size"] == 1 and e["overflow"] == 0 and e["timeout_s"] == 0.1 and e["collector"] is False
    assert waited - 0.05 <= e["waited_s"] <= waited + 0.5
    assert e["thread"] == threading.current_thread().name
    assert [h["thread"] for h in e["holders"]] == ["the-holder"] and e["holders"][0]["age_s"] >= 0
    assert e["checked_out"] == 1
    eng.dispose()


def test_a_collector_refused_by_the_reservation_is_journaled_too(journal):
    from src.database.pool_reserve import collector_role

    eng = _pool_engine(timeout=0.1)
    taken, let_go = threading.Event(), threading.Event()
    held = []

    def hold():
        with collector_role():
            held.append(eng.raw_connection())
        taken.set()
        let_go.wait(5)
        held[0].close()

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    assert taken.wait(3)
    with collector_role(), pytest.raises(PoolTimeoutError, match="last 4 connections"):
        eng.raw_connection()
    let_go.set()
    t.join(5)
    (e,) = _events("pool_timeout")
    assert e["collector"] is True
    eng.dispose()


def test_a_checkout_that_succeeds_journals_nothing(journal):
    eng = _pool_engine()
    conn = eng.raw_connection()
    conn.close()
    assert _member()["kinds"]["pool_timeout"]["total"] == 0
    eng.dispose()


def test_a_journal_that_fails_inside_the_pool_hook_leaves_the_pools_error_alone(journal, monkeypatch):
    def boom(**_k):
        raise RuntimeError("the journal is down")

    monkeypatch.setattr(se, "note_pool_timeout", boom)
    eng = _pool_engine(timeout=0.05)
    held = eng.raw_connection()
    with pytest.raises(PoolTimeoutError):
        eng.raw_connection()
    held.close()
    eng.dispose()


# --------------------------------------------------------------------------- #
#  The independent read's findings
# --------------------------------------------------------------------------- #
def test_a_thread_named_with_the_passphrase_is_scrubbed_in_the_gate_stats_the_report_and_the_contention_member(journal, held_passphrase):
    """B1: ``by_holder`` (and ``holder`` / ``max_hold_holder``) went into ``contention.json`` as the thread's name, which a request can
    choose (``oo-osm-{code}``); a dict KEY is not scrubbed by the bundle's net, so the name is scrubbed where it is read, and
    ``by_holder`` is rows whose names are values."""
    from src.api.diagnostics import bundle, write_gate_report
    from src.database import writer

    name = f"oo-osm-{MARKER}"
    gate = writer.WriterGate()
    with _Holder(gate, name):
        held = gate.stats()
        assert MARKER not in json.dumps(held) and held["holder"] is not None, "the holder in flight is scrubbed"
    after = gate.stats()
    assert MARKER not in json.dumps(after) and after["max_hold_holder"] is not None
    assert isinstance(after["by_holder"], list) and after["by_holder"][0]["holds"] == 1
    # And through the real gate, the report that serves it, and the member the bundle writes.
    done = threading.Event()

    def take_once():
        with writer.write_lock():
            pass
        done.set()

    t = threading.Thread(target=take_once, name=name, daemon=True)
    t.start()
    assert done.wait(5)
    t.join(5)
    assert MARKER not in json.dumps(write_gate_report(), default=str)
    assert MARKER.encode() not in bundle._member_bytes(bundle._contention_member())


def test_the_gate_stats_scrub_the_names_after_the_lock_is_released(monkeypatch):
    """``served_cache.change_probe`` reads the stats two or three times per cached read: the scrub is not work to do under the lock
    the writers queue on. The probe asks, from ANOTHER thread, whether the gate's condition is free at the moment each name is scrubbed."""
    from src.database import writer

    gate = writer.WriterGate()
    free_at_scrub: list[bool] = []

    def probe(name):
        answer: list[bool] = []

        def ask():
            got = gate._cond.acquire(blocking=False)
            if got:
                gate._cond.release()
            answer.append(got)

        t = threading.Thread(target=ask, daemon=True)
        t.start()
        t.join(5)
        free_at_scrub.append(answer == [True])
        return name

    monkeypatch.setattr(writer, "_scrubbed_name", probe)
    with _Holder(gate, "a-holder"):
        gate.stats()
    after = gate.stats()
    assert after["by_holder"][0]["holder"] == "a-holder" and after["max_hold_holder"] == "a-holder"
    assert len(free_at_scrub) >= 5 and all(free_at_scrub), "every name was scrubbed with the gate's lock free"


def _marker_named_pool_holder(eng, name: str):
    """A thread called ``name`` that invalidates one pooled connection (the pool watch records who held it) and then holds another
    until told to let go. Returns ``(thread, let_go)``."""
    taken, let_go = threading.Event(), threading.Event()

    def run():
        first = eng.raw_connection()
        first.invalidate()
        first.close()
        held = eng.raw_connection()
        taken.set()
        let_go.wait(10)
        held.close()

    t = threading.Thread(target=run, name=name, daemon=True)
    t.start()
    assert taken.wait(5)
    return t, let_go


def test_a_thread_holding_a_pooled_connection_and_named_with_the_passphrase_is_scrubbed_in_every_pool_reader(
    journal, held_passphrase, caplog
):
    """The coordinator's check of 05cc79399: ``contention.json`` carried raw holder thread names from the pool watch
    (``pool[].thread``, ``invalidations.recent[].held_by.thread`` / ``by_thread``, the stall record's ``holders[].thread``), the same
    class as B1 through a thread that holds a CONNECTION rather than the gate. The name is scrubbed where the pool watch hands it out,
    in the line it logs, and again by the member's net."""
    import logging

    from src.api.diagnostics import bundle, write_gate_report
    from src.database import pool_watch
    from src.monitoring import stall_forensics as sf

    sf._reset_for_tests()
    name = f"oo-osm-{MARKER}"
    eng = _pool_engine(timeout=2.0)
    pool_watch.register(eng, label="events-test")
    caplog.set_level(logging.DEBUG, logger="src.database.pool_watch")
    t, let_go = _marker_named_pool_holder(eng, name)
    try:
        rows = pool_watch.checked_out()
        assert len(rows) == 1 and rows[0]["thread"].startswith("oo-osm-") and MARKER not in rows[0]["thread"]
        recent = pool_watch.invalidations()["recent"]
        assert len(recent) == 1
        assert recent[0]["held_by"]["thread"].startswith("oo-osm-") and recent[0]["by_thread"].startswith("oo-osm-")
        assert MARKER not in json.dumps(pool_watch.invalidations(), default=str)
        # The stall record files who held the pool at the moment, and the report serves it.
        filed = sf.note_stall("GET /api/x", 200, 10_000_000.0)
        assert filed is not None and filed["evidence"]["pool"]["holders"][0]["thread"].startswith("oo-osm-")
        assert MARKER not in json.dumps(sf.report(limit=200), default=str)
        assert MARKER not in json.dumps(write_gate_report(), default=str)
        member = bundle._member_bytes(bundle._contention_member())
        assert MARKER.encode() not in member and b"oo-osm-" in member, "the name is there, the passphrase is not"
        assert "pool connection invalidated: held by oo-osm-" in caplog.text, "positive control: the line WAS logged (a throttled line passes the next check vacuously)"
        assert MARKER not in caplog.text, "the line logged for the invalidation"
    finally:
        let_go.set()
        t.join(5)
        eng.dispose()
        sf._reset_for_tests()


def test_the_contention_member_scrubs_a_name_the_readers_did_not(held_passphrase, monkeypatch):
    """The net under the member: a reader that hands out a raw name (a stall filed before the passphrase was set, a future field)
    still cannot put the passphrase into ``contention.json``."""
    from src.api.diagnostics import bundle

    leaky = {"gate": {"by_holder": [{"holder": f"oo-osm-{MARKER}"}]}, "pool": [{"thread": f"oo-osm-{MARKER}"}]}
    monkeypatch.setattr(bundle, "write_gate_report", lambda: leaky)
    member = bundle._member_bytes(bundle._contention_member())
    assert MARKER.encode() not in member and b"oo-osm-" in member


def test_a_hold_that_ended_while_the_watchdog_was_still_sampling_it_leaves_one_closed_entry_and_nothing_open(journal, monkeypatch):
    """M1: the watchdog reads the holder, then spends time on the gate's stats, the route and the frames before it records; the holder's
    release can come in between. The late sample must not open a second entry, which would stay open for ever and read like a kill in
    the middle of a hold."""
    from src.database import writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    started = 4242.5
    writer._note_hold_end("late-holder", 61.0, started)  # the release came first: nothing was open, so it is written whole
    writer._note_long_hold(writer.WriterGate(), "late-holder", started, None, 61.0)  # then the late first sample
    k = _member()["kinds"]["gate_hold"]
    assert k["total"] == 1 and k["events"][0].get("sampled_while_held") is False
    assert not [e for e in k["events"] if e.get("open")], "no entry is left open for a hold that is over"


def test_a_late_sample_after_the_entry_was_opened_and_closed_does_not_open_it_again(journal, monkeypatch):
    from src.database import writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    gate = writer.WriterGate()
    started = 777.25
    writer._note_long_hold(gate, "h", started, None, 40.0)  # the first sample opens it
    writer._note_hold_end("h", 61.0, started)  # the release closes it
    writer._note_long_hold(gate, "h", started, None, 41.0)  # a sample that was already computing: update() finds it closed
    k = _member()["kinds"]["gate_hold"]
    assert k["total"] == 1 and k["events"][0]["open"] is False and k["events"][0]["seconds"] == 61.0


def test_a_tombstone_refuses_a_later_opener_of_the_same_key_and_is_bounded(journal):
    se.record("gate_hold", {"n": 1}, key="k1")
    assert se.end("gate_hold", "k1", tombstone=True) is True
    se.record("gate_hold", {"n": 2}, key="k1")
    assert _member()["kinds"]["gate_hold"]["total"] == 1, "the key is spent"
    se.record("gate_hold", {"n": 3}, key="other")
    assert _member()["kinds"]["gate_hold"]["total"] == 2, "other keys are untouched"
    assert se.end("gate_hold", "never-opened", tombstone=True) is False
    se.record("gate_hold", {"n": 4}, key="never-opened")
    assert _member()["kinds"]["gate_hold"]["total"] == 2, "a closer that found nothing also spends its key"
    for i in range(se.ENDED_KEYS_MAX + 5):
        se.end("gate_hold", f"spent-{i}", tombstone=True)
    assert len(se._ENDED) <= se.ENDED_KEYS_MAX
    se.record("gate_hold", {"n": 5}, key="k1")  # long since forgotten: the bound protects memory, not a key a hold could offer again
    assert _member()["kinds"]["gate_hold"]["total"] == 3


@pytest.mark.parametrize(
    "content",
    [
        '{"schema": "oo-storage-events-1", "kinds": {"guard": {"total": 3, "events": 5}}}',
        '{"schema": "oo-storage-events-1", "kinds": {"guard": {"total": "x", "events": [1, "a", {"at": 3}]}}}',
        '{"schema": "oo-storage-events-1", "kinds": []}',
        "[" * 100_000 + "]" * 100_000,
        '{"schema": "oo-storage-events-1", "kinds": {"guard": "no"}}',
    ],
    ids=["events-not-a-list", "events-of-the-wrong-shape", "kinds-not-a-dict", "nested-too-deep", "kind-not-a-dict"],
)
def test_a_file_in_a_shape_ours_never_wrote_is_not_read_back_and_is_replaced_by_the_next_write(journal, content):
    """L1: external damage or version skew must not disable the journal across restarts (the first read raising left it with no
    history and a writer that looped on the error)."""
    journal.write_text(content, encoding="utf-8")
    m = _member()
    assert "error" not in m, m
    assert m["file"]["read_at_first_use"].startswith("unreadable") or m["file"]["read_at_first_use"] == "ok"
    se.record("guard", {"kind": "wal"})
    assert _wait_until(lambda: _file_total(journal, "guard") >= 1), "the damaged file is replaced by a journal of ours"
    assert se._INTERNAL_FAILURES == 0


def test_a_failed_write_is_tried_again_without_another_change(journal, monkeypatch):
    """L3: a transient failure (a scanner holding the file on Windows) must not leave the last event in memory only until the next
    change: the last event of a quiet period is the one that matters."""
    calls = {"n": 0}
    real = se.os.replace

    def fails_twice(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(errno.EACCES, f"locked by a scanner {MARKER}")
        return real(a, b)

    _on_journal_replace(monkeypatch, journal, fails_twice)
    se.record("guard", {"kind": "disk"})
    assert _wait_until(lambda: _file_total(journal, "guard") == 1), "written by the retry, with no second change"
    assert se._WRITE_FAILURES == 2 and calls["n"] == 3
    assert MARKER not in json.dumps(_member()), "the failures are kept by class and errno name"
    assert _member()["file"]["last_write_failure"] == "PermissionError EACCES"


def test_a_persistent_write_failure_backs_off_instead_of_writing_every_delay(journal, monkeypatch):
    calls = {"n": 0}

    def always(_a, _b):
        calls["n"] += 1
        raise OSError(errno.ENOSPC, "No space left on device")

    _on_journal_replace(monkeypatch, journal, always)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.05)
    se.record("guard", {"kind": "disk"})
    time.sleep(1.0)
    # delays 0.05 (coalesce) then 0.1, 0.2, 0.4 plus the 0.05 coalescing before each: well under one attempt per 0.05 s
    assert 2 <= calls["n"] <= 6, f"{calls['n']} attempts in a second"


def test_a_data_directory_that_cannot_be_resolved_at_the_write_is_a_failed_write_not_a_dead_writer(journal, monkeypatch):
    """L3: ``_path()`` is ``data_dir() / name`` and can raise (a missing data volume); at the write it is inside the guarded block, so
    it is counted as the write failure it is."""
    _member()  # the file is read (it is missing) while the volume is there

    def gone():
        raise RuntimeError(f"the data volume is not mounted {MARKER}")

    monkeypatch.setattr(se, "_path", gone)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._WRITE_FAILURES >= 1)
    assert se._INTERNAL_FAILURES == 0 and _member()["file"]["last_write_failure"] == "RuntimeError"
    assert MARKER not in json.dumps(_member())


def test_a_data_directory_that_cannot_be_resolved_at_the_read_leaves_the_history_unread_and_is_tried_again(journal, monkeypatch):
    """Low 2: no file was read, so none is assumed empty: nothing is written, the failure is counted by class, and the writer asks again."""
    state = {"gone": True}

    def maybe_gone():
        if state["gone"]:
            raise RuntimeError(f"the data volume is not mounted {MARKER}")
        return journal

    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-01T00:00:00+00:00", "kinds": {"guard": {"total": 6, "events": []}}}),
        encoding="utf-8",
    )
    before = journal.read_bytes()
    monkeypatch.setattr(se, "_path", maybe_gone)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._READ_FAILURES >= 2), "the writer asked again"
    assert se._WRITE_FAILURES == 0 and se._INTERNAL_FAILURES == 0 and se._THREAD is not None and se._THREAD.is_alive()
    f = _member()["file"]
    assert f["history_loaded"] is False and f["last_read_failure"] == "unreadable (RuntimeError)" and f["read_failures"] >= 2
    assert MARKER not in json.dumps(_member())
    state["gone"] = False
    assert _wait_until(lambda: _file_total(journal, "guard") == 7), "the history the file held is extended once the volume is back"
    assert before != journal.read_bytes() and _member()["file"]["history_loaded"] is True


def test_a_read_that_fails_with_an_io_error_is_looked_at_again_before_the_file_is_called_unreadable(journal, monkeypatch):
    """L3: a transient read error must not start the journal empty over the file's history."""
    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-01T00:00:00+00:00", "kinds": {"guard": {"total": 6, "events": []}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(se, "READ_RETRY_S", 0.001)
    real_path = journal

    class Flaky:
        reads = 0

        def stat(self):
            return real_path.stat()

        def read_text(self, **kw):
            Flaky.reads += 1
            if Flaky.reads <= 2:
                raise OSError(errno.EIO, f"I/O error {MARKER}")
            return real_path.read_text(encoding="utf-8")

    monkeypatch.setattr(se, "_path", lambda: Flaky())
    assert _member()["kinds"]["guard"]["total"] == 6 and Flaky.reads == 3
    assert MARKER not in json.dumps(_member())


def test_a_read_that_keeps_failing_is_called_unreadable_by_class_after_three_looks(journal, monkeypatch):
    class Broken:
        looks = 0

        def stat(self):
            Broken.looks += 1
            raise PermissionError(errno.EACCES, f"denied {MARKER}")

    monkeypatch.setattr(se, "READ_RETRY_S", 0.001)
    monkeypatch.setattr(se, "_path", lambda: Broken())
    assert _member()["file"]["read_at_first_use"] == "unreadable (PermissionError EACCES)" and Broken.looks == se.READ_ATTEMPTS


def _unreadable_for_now(monkeypatch, journal):
    """``journal`` reads with an I/O error (EIO) while the returned flag is set, and normally once it is cleared. Only this one file is
    affected (``Path.read_text`` is the class's, so the patch is routed by path); ``stat`` and the writes are the real ones."""
    import pathlib

    flag = {"broken": True, "reads": 0}
    real = pathlib.Path.read_text

    def read_text(self, *a, **k):
        if flag["broken"] and self == journal:
            flag["reads"] += 1
            raise OSError(errno.EIO, f"I/O error {MARKER}")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(se, "READ_RETRY_S", 0.001)
    return flag


def test_a_file_that_stays_unreadable_is_never_written_over_and_is_read_again_when_it_can_be(journal, monkeypatch):
    """Low 2 (the coordinator's check of 05cc79399): three looks at a persistent I/O error used to leave the journal 'loaded' and empty,
    so the next write replaced a history that was only unreadable for now. It stays unloaded, the writer retries with backoff, and
    neither the writer nor ``flush()`` writes until the file has been read."""
    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-01T00:00:00+00:00", "kinds": {"guard": {"total": 6, "events": []}}}),
        encoding="utf-8",
    )
    before = journal.read_bytes()
    flag = _unreadable_for_now(monkeypatch, journal)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._READ_FAILURES >= 3), "the writer asks again, with a longer wait each time"
    se.flush()  # the clean stop: it must not overwrite either
    assert journal.read_bytes() == before, "the file is exactly as it was"
    assert se._WRITE_FAILURES == 0 and se._WRITTEN_VERSION == 0 and se._INTERNAL_FAILURES == 0
    f = _member()["file"]
    assert f["history_loaded"] is False and f["last_read_failure"] == "unreadable (OSError EIO)" and f["read_at_first_use"] == f["last_read_failure"]
    assert MARKER not in json.dumps(_member()) and flag["reads"] >= 3 * se.READ_ATTEMPTS
    flag["broken"] = False  # the disk recovers
    assert _wait_until(lambda: _file_total(journal, "guard") == 7), "the next attempt reads the history and extends it"
    m = _member()
    assert m["file"]["history_loaded"] is True and m["file"]["read_at_first_use"] == "ok" and m["kinds"]["guard"]["total"] == 7
    assert m["file"]["read_failures"] >= 3, "the failures stay counted"


def test_a_file_that_is_damaged_is_known_to_be_damaged_and_the_next_write_replaces_it(journal):
    """The other side of Low 2: damaged JSON, a file that is not this journal and an oversize one are READ (and found unusable), so the
    journal starts empty and the next write replaces them. Only a file that could not be read at all is kept."""
    for name, body in (
        ("damaged", b"{not json"),
        ("alien", json.dumps({"schema": "something-else", "kinds": {}}).encode()),
        ("oversize", b" " * (se.MAX_FILE_BYTES + 1)),
    ):
        se.reset_for_tests(keep_file=True)
        journal.write_bytes(body)
        se.record("guard", {"n": 1})
        se.flush()
        assert _file_total(journal, "guard") == 1, f"the {name} file was replaced"
        assert _member()["file"]["history_loaded"] is True and se._READ_FAILURES == 0


def test_the_pools_own_error_is_the_one_raised_after_the_journal_has_its_record(journal):
    """The hook re-raises the very exception object the pool raised, not a copy (a copy would lose its traceback and its identity)."""
    eng = _pool_engine()
    boom = PoolTimeoutError("QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 0.10")

    def raising():
        raise boom

    eng.pool._connect_reserving = raising
    with pytest.raises(PoolTimeoutError) as raised:
        eng.pool.connect()
    assert raised.value is boom
    assert _member()["kinds"]["pool_timeout"]["total"] == 1
    eng.dispose()


def test_a_pool_timeout_counts_its_own_pools_checkouts_and_names_only_its_own_holders(journal):
    """L5: ``checked_out()`` lists every watched pool; the count beside ``pool_size`` is this pool's, and the holders are the rows this
    pool's label owns."""
    from src.database import pool_watch

    mine, other = _pool_engine(timeout=0.1), _pool_engine(timeout=0.1)
    pool_watch.register(mine, label="events-mine")
    pool_watch.register(other, label="events-other")
    theirs = other.raw_connection()
    taken, let_go = threading.Event(), threading.Event()
    held = []

    def hold():
        held.append(mine.raw_connection())
        taken.set()
        let_go.wait(5)
        held[0].close()

    t = threading.Thread(target=hold, name="mine-holder", daemon=True)
    t.start()
    assert taken.wait(3)
    with pytest.raises(PoolTimeoutError):
        mine.raw_connection()
    let_go.set()
    t.join(5)
    theirs.close()
    (e,) = _events("pool_timeout")
    assert e["checked_out"] == 1 and e["pool_size"] == 1, "this pool's own count, whatever else is watched"
    assert [h["thread"] for h in e["holders"]] == ["mine-holder"], "the other pool's checkout is not this pool's holder"
    mine.dispose()
    other.dispose()


def test_a_backup_whose_truncate_raised_is_journaled_as_failed_not_done(journal, monkeypatch, tmp_path):
    """L6, through the real ``_drain_wal`` (the coordinator's check of 05cc79399: calling ``_journal_drain(failed=True)`` directly left
    the test green with ``failed=row is None`` gone): ``_wal_row`` swallows the exception and answers None, and the journal used to
    say ``done``. A TRUNCATE that ANSWERED, with frames still in the log, is a checkpoint that ran: ``done``."""
    from src.backup import stream_backup

    db = tmp_path / "x.db"
    db.write_bytes(b"x")
    rows = iter([(0, 5, 5)])  # PASSIVE answers; every TRUNCATE after it raises (swallowed into None)
    monkeypatch.setattr(stream_backup, "_wal_row", lambda mode: next(rows, None))
    monkeypatch.setattr(stream_backup, "_wal_complete", lambda _db, row: False)
    monkeypatch.setattr(stream_backup, "_CHECKPOINT_WAIT_S", 5.0)
    monkeypatch.setattr(stream_backup.time, "sleep", lambda _s: None)
    assert stream_backup._drain_wal(db) == tmp_path / "x.db-wal", "the main file alone is not a complete image"
    (e,) = _events("checkpoint")
    assert e["trigger"] == "backup" and e["outcome"] == "failed" and e["error"] == "the TRUNCATE gave no row"
    assert e["passive"] == [0, 5, 5] and e["truncate_tries"] == 1
    assert _member()["kinds"]["checkpoint_notable"]["total"] == 1, "a failed checkpoint is kept among the notable ones"
    # The other end: the TRUNCATE answered (a reader still pins frames) and the wait is over: it ran, so it is not 'failed'.
    rows = iter([(0, 5, 5), (1, 9, 4)])
    monkeypatch.setattr(stream_backup, "_wal_row", lambda mode: next(rows, None))
    monkeypatch.setattr(stream_backup, "_CHECKPOINT_WAIT_S", 0.0)
    assert stream_backup._drain_wal(db) == tmp_path / "x.db-wal"
    last = _events("checkpoint")[-1]
    assert last["outcome"] == "done" and "error" not in last and last["truncate"] == [1, 9, 4]


def test_the_process_token_is_unique_even_for_two_starts_in_the_same_second():
    assert se._PROC.count("-") == 1 and int(se._PROC.split("-")[1]) > 10**15, "nanoseconds, not whole seconds"


def test_an_update_the_size_cap_refused_does_not_cost_a_write(journal, monkeypatch):
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 30.0)
    se.record("gate_hold", {"n": 1}, key="k")
    version = se._VERSION
    se.update("gate_hold", "k", {f"f{i}": "x" * se.STR_CHARS for i in range(24)})
    assert version == se._VERSION, "nothing was merged, so nothing is dirty"


def test_the_gate_report_keeps_the_sampled_route_when_the_release_finds_none(journal, monkeypatch):
    from src.database import pool_watch, writer

    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.0)
    monkeypatch.setattr(pool_watch, "endpoint_template", lambda: None)
    se.record("gate_hold", {"holder": "h", "route": "POST /api/x", "seconds": 40.0}, key=("hold", 1.5))
    writer._note_hold_end("h", 61.0, 1.5)
    (e,) = _events("gate_hold")
    assert e["route"] == "POST /api/x" and e["seconds"] == 61.0 and e["open"] is False


def test_a_reset_never_resolves_the_data_directory_again_whether_or_not_the_journal_was_touched(journal, monkeypatch):
    """On a marked drive that has gone missing, resolving the data directory is itself a signal to the volume monitor, which pauses
    collection for the rest of the process: the suite's isolation fixture runs this reset after EVERY test, so neither a test that
    merely walked past (the data-volume tests) nor one that wrote the journal while the folder was still there may cause it. The reset
    removes the files the journal remembers it touched (the coordinator's low 4 on #1384: the touched case still resolved)."""
    se.record("gate_hold", {"n": 1}, key="k")
    se.flush()
    assert journal.exists()
    resolved: list[int] = []

    def gone():
        resolved.append(1)
        raise OSError(errno.ENOENT, "the folder went away")

    monkeypatch.setattr(se, "_path", gone)
    se.reset_for_tests()
    assert resolved == [] and not journal.exists(), "removed by the path it used, with no new resolution"
    se.reset_for_tests()  # an untouched journal as well
    assert resolved == []


def test_a_file_the_journal_could_not_read_is_removed_by_the_reset_like_any_other_it_touched(journal, monkeypatch):
    """The coordinator's low 5 on #1384, decided: a read the I/O error outlasted names the file, so a reset removes it (a test's planted
    file must not outlive the test and be read as an earlier process's by the next). Production never resets."""
    journal.write_text(
        json.dumps({"schema": se.SCHEMA, "since": "2026-10-13T00:00:00+00:00", "kinds": {"guard": {"total": 1, "events": []}}}),
        encoding="utf-8",
    )
    _unreadable_for_now(monkeypatch, journal)
    se.record("guard", {"n": 1})
    assert _wait_until(lambda: se._READ_FAILURES >= 1)
    assert journal.exists()
    se.reset_for_tests()
    assert not journal.exists()


def test_a_reset_of_a_journal_that_was_written_removes_its_file(journal):
    se.record("gate_hold", {"n": 1}, key="k")
    se.flush()
    assert journal.exists()
    se.reset_for_tests()
    assert not journal.exists()


# --------------------------------------------------------------------------- #
#  The journal writer's wait loops keep their jump back inside the ``with`` (R161)
# --------------------------------------------------------------------------- #
def _uncovered_back_edges(fn) -> list[int]:
    """Line numbers of the ``JUMP_BACKWARD`` instructions in ``fn`` (and the functions nested in it) that no exception-table entry covers.
    The same reading as ``tests/test_gates_survive_an_interrupt.py``: on CPython 3.13 the jump back of ``while <wanted>:`` under
    ``with lock:`` is outside the ``with``'s entry, so an exception raised there skips the release."""
    import dis
    import inspect
    import types

    def walk(code):
        yield code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from walk(const)

    out: list[int] = []
    for code in walk(inspect.unwrap(fn).__code__):
        ranges = [(e.start, e.end) for e in dis.Bytecode(code).exception_entries]
        for ins in dis.get_instructions(code):
            if ins.opname == "JUMP_BACKWARD" and not any(start <= ins.offset < end for start, end in ranges):
                out.append(ins.positions.lineno if ins.positions else -1)
    return out


def _loop_as_it_was(lock, cond, held):
    with lock:
        while held():
            cond.wait()


def _loop_as_it_is(lock, cond, held):
    with lock:
        while True:
            if not held():
                break
            cond.wait()


def test_the_reading_sees_the_old_loop_shape_as_uncovered_and_the_new_one_as_covered():
    """The canary the next test rests on: if this Python covers the old shape too, the next test passes for any loop and says so here."""
    assert _uncovered_back_edges(_loop_as_it_was), (
        "this Python covers the jump back of `while cond:` inside a `with` too: the loop form of R161 is no longer needed here, and "
        "the next test measures nothing"
    )
    assert not _uncovered_back_edges(_loop_as_it_is)


def test_no_wait_loop_of_the_journal_writer_leaves_its_jump_back_outside_the_with():
    bad = {name: _uncovered_back_edges(fn) for name, fn in {"_wait_out": se._wait_out, "_wait_until_dirty": se._wait_until_dirty}.items()}
    assert not any(bad.values()), f"a wait loop's jump back is outside the with (lines): {bad}"


def test_wait_out_returns_at_the_deadline_and_never_leaves_the_condition_held():
    start = time.monotonic()
    se._wait_out(se._GENERATION, 0.05)
    assert 0.04 <= time.monotonic() - start < 1.0
    assert se._COND.acquire(timeout=1.0), "the condition's lock was left held by the wait"
    se._COND.release()


def test_wait_out_returns_at_once_when_a_reset_made_its_generation_old():
    stale = se._GENERATION
    se.reset_for_tests()
    start = time.monotonic()
    se._wait_out(stale, 30.0)
    assert time.monotonic() - start < 1.0, "a wait for a generation that was reset must not run to its deadline"


def test_a_reset_ends_a_wait_out_in_progress(journal):
    box: list[float] = []
    gen = se._GENERATION
    t = threading.Thread(target=lambda: (se._wait_out(gen, 30.0), box.append(time.monotonic())), daemon=True)
    began = time.monotonic()
    t.start()
    time.sleep(0.1)
    se.reset_for_tests()
    t.join(timeout=5.0)
    assert not t.is_alive() and box and box[0] - began < 5.0, "the reset did not wake the wait"


def test_wait_until_dirty_returns_when_a_change_is_waiting_and_leaves_the_condition_free(journal):
    box: list[int] = []
    t = threading.Thread(target=lambda: box.append(se._wait_until_dirty()), daemon=True)
    t.start()
    time.sleep(0.1)
    assert t.is_alive() and not box, "nothing was waiting to be written, so the wait must not have returned"
    se.record("guard", {"n": 1})
    t.join(timeout=5.0)
    assert box == [se._GENERATION]
    assert se._COND.acquire(timeout=1.0)
    se._COND.release()

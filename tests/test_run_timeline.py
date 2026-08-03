"""The run-timeline analyser, pinned against the field run it was built to explain.

The 2026-08-03 import was reported as "3h30 for 650 MB, aborted". Its journal already
held every number needed to correct that; extracting them took an afternoon of
hand-arithmetic. The fixtures below are that run's REAL shape, and the assertions are
the numbers that afternoon produced -- so the analyser is checked against a known
answer rather than against itself.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.monitoring.run_timeline import analyse_run, latest_run_timeline

# The field run's own top-level stages (values verbatim from the journal). Note the
# THREE shapes that must be told apart: real top-level stages, "stage_a:*" which has
# no parent, and the two nested kinds that must not be summed twice.
_FIELD_STAGES = {
    "stage_a:verify_and_parity_recover": 4.422,
    "stage_a:reassemble": 7.218,
    "stage_a:prepare_corpus_files": 24.449,
    "stage_a:finalize": 0.025,
    "prepare_staged:validate": 17.328,   # nested: parent "prepare_staged" IS recorded
    "prepare_staged:upgrade": 0.194,
    "prepare_staged": 17.588,
    "snapshot_working_copy": 0.552,
    "merge_step:articles": 17.015,       # nested: rolls up into "merge"
    "merge_step:keywords": 7.987,
    "merge": 36.83,
    "verify": 9.107,
    "swap": 0.313,
    "corpus_epoch_bump": 7.473,
    "event_mirror_refresh": 0.281,
    "corpus_delta_before": 0.018,
    "pre_restore_snapshot": 0.645,
    "side_files_and_custody": 9.12,
    "report_json_write": 0.228,
    "corpus_delta_after": 0.042,
}


def _field_summary() -> dict:
    return {
        "run_id": "imp-20260803T025011Z-85b41b",
        "kind": "import",
        "complete": False,
        "outcome": "incomplete",
        "died_in_stage": "reindex",
        "stages": _FIELD_STAGES,
        "last_beat": {"el_s": 11006.9},
    }


def _field_beats() -> list[dict]:
    """The re-index: healthy progress to 9,000, then frozen there.

    Child CPU is measured on only SOME beats, exactly as the real walk behaves -- that
    is what the partial-denominator assertion below is about.
    """
    beats: list[dict] = []
    el = 130.0
    for done in range(200, 9001, 200):          # the healthy stretch
        el += 55.0
        beats.append({"el_s": el, "phase": "reindexing", "counter": "reindex",
                      "done": done, "total": 21778, "d_cpu_s": 45.0})
    # ...then 2 h 20 m at exactly 9,000, four children busy at ~0.57 cores.
    for i in range(560):
        el += 15.0
        b = {"el_s": el, "phase": "reindexing", "counter": "reindex",
             "done": 9000, "total": 21778, "d_cpu_s": 7.96,
             "gate": {"held": False, "waiters": 0}}
        if i % 4 == 0:                           # only some beats measure children
            b["kids_n"] = 4
            b["d_kids_cpu_s"] = 8.5
        beats.append(b)
    return beats


def test_it_reproduces_the_hand_computed_stage_total():
    """118.3 s, the number an afternoon of arithmetic produced.

    The load-bearing part is which entries get summed. A naive "any colon means a
    sub-stage" rule silently drops the four ``stage_a:*`` entries -- they have no
    parent stage at all -- and under-reports by 36 s. ``prepare_staged:validate``
    (parent recorded) and ``merge_step:articles`` (rolls into ``merge``) must both be
    excluded, by two different rules.
    """
    r = analyse_run(_field_summary(), _field_beats())
    assert r["stages_top_level_s"] == 118.3


def test_the_headline_is_that_the_run_hung_rather_than_ran_slow():
    """The whole point. 98.9% of the elapsed time is inside a stage that never
    finished, and the operator experienced that as "the import is slow"."""
    r = analyse_run(_field_summary(), _field_beats())
    assert r["unaccounted_s"] > 10_000
    assert r["unaccounted_share"] > 0.98
    assert r["died_in_stage"] == "reindex"
    assert "reindex" in r["unaccounted_note"]


def test_a_stall_reports_that_the_workers_were_BUSY_not_deadlocked():
    """THE distinction the field run turned on, and the one nothing could make at the
    time. Both readings are "no progress"; only one is a deadlock, and they need
    opposite fixes. Four children at 0.57 cores says pathological work."""
    r = analyse_run(_field_summary(), _field_beats())
    worst = r["longest_stall"]
    assert worst["stuck_at"] == 9000
    assert worst["seconds"] > 8000
    assert worst["children_seen"] == 4
    assert worst["child_cores"] > 0.5, "diluting this across unmeasured beats hides it"
    assert "BUSY" in worst["reading"]
    assert worst["write_gate_held_in_any_beat"] is False


def test_the_child_rate_is_not_diluted_across_beats_that_never_measured():
    """The partial-denominator trap, in its second shape.

    Summing child CPU and dividing by the FULL window turns a real 0.57 cores into
    0.12 -- understating precisely the signal that separates busy from wedged. The
    rate is over the beats that measured, and says how many those were.
    """
    r = analyse_run(_field_summary(), _field_beats())
    worst = r["longest_stall"]
    assert worst["child_cores"] > 0.5
    assert worst["child_samples"] < worst["beats"], "this fixture measures only some beats"
    assert "child_partial" in worst, "a partial denominator must be disclosed"


def test_a_phase_with_no_counter_is_never_called_stalled():
    """``prepare_staged`` is 54% of a large import and publishes only a phase name.
    Reporting "not moving" for ninety minutes of healthy work is the fabricated
    verdict the beat schema exists to prevent, and the rule holds one level up."""
    beats = [
        {"el_s": 100.0 + 15 * i, "phase": "reassembling", "counter": "none-in-this-phase"}
        for i in range(200)
    ]
    r = analyse_run({"run_id": "x", "stages": {}, "last_beat": {"el_s": 3100.0}}, beats)
    assert r["stalls"] == []
    assert "stalls_none" in r


def test_a_healthy_run_reports_no_stall():
    """The negative-space twin: a run that genuinely progressed must not be flagged,
    or the detector cries wolf on every import and is switched off."""
    beats = [
        {"el_s": 100.0 + 15 * i, "phase": "reindexing", "counter": "reindex",
         "done": 200 * i, "d_cpu_s": 14.0}
        for i in range(200)
    ]
    r = analyse_run({"run_id": "x", "stages": {"merge": 10.0}, "last_beat": {"el_s": 3100.0}}, beats)
    assert r["stalls"] == []


def test_stalls_need_the_raw_beats_and_say_so_when_absent():
    """Absence of a stall analysis must not read as absence of stalls."""
    r = analyse_run(_field_summary(), None)
    assert "stalls" not in r
    assert "stalls_unavailable" in r


def test_an_unreadable_journal_is_not_reported_as_no_runs(monkeypatch):
    """"could not read" and "nothing to report" must never look alike."""
    import src.backup.runlog as runlog

    def _boom(**_kw):
        raise OSError("no space left on device")

    monkeypatch.setattr(runlog, "raw_runs", _boom)
    out = latest_run_timeline()
    assert out["available"] is False
    assert "no space left" in out["reason"]


def test_it_is_a_diagnostics_bundle_member():
    """The 2026-07-17 ruling: all-diagnostics must comprise ALL diagnostics. A tool
    that only exists behind a URL nobody visits does not help the next field report."""
    import inspect

    from src.api import diagnostics

    src = inspect.getsource(diagnostics._all_diagnostics_members)
    assert "run-timeline.json" in src

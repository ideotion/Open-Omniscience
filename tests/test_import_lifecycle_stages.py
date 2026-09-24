"""The import lifecycle: four stages, the three statements, one API path (`S04-02`).

Implements the 2026-09-15 rulings Q202 (four stages as four rows with their own
progress), Q203 (the three statements at the moments ruled), Q204/Q205 (stage 4 inside
the experience, auto-resumed at boot), Q214 (``import-queue/*`` is the one path) and
Q216 ⛔ (K = 3, whose own discriminator lives in ``test_import_checkpoint.py``).

WHAT THESE GUARDS ARE ABOUT. A stage row is a MEASUREMENT or it is an absence with a
reason -- never a percentage of work nobody counted, and never a zero where the honest
answer is "we could not read it". Most of what is asserted below is that negative
space, because the positive space passes on its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from src.backup.import_queue import (
    STAGE_MERGE_SWAP,
    STAGE_REINDEX,
    STAGE_SEARCH_INDEX,
    STAGE_VERIFY_STAGE,
    STAGE_WALKING_KINDS,
    ImportQueueManager,
    _refusal_of,
    stage_for_phase,
)

_REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
#  1. The phase -> stage map, and the gap where a phase is unknown
# --------------------------------------------------------------------------- #
def test_every_phase_the_restore_can_emit_has_a_stage():
    """DERIVED FROM THE TREE, never from a list someone remembered.

    The phases a restore publishes are ``_RESTORE_MANAGER_PHASES`` plus every stage in
    ``restore_stage_plan`` (run through ``_stage_phase_name``) plus the queue's own
    tail phase. A map written from memory goes silently blind the day a stage is added
    -- and a phase with no stage renders as an absence, so the failure would be a row
    that stops advancing rather than an error anyone sees.
    """
    from src.backup.merge import restore_stage_plan
    from src.backup.volume_job import _RESTORE_MANAGER_PHASES, _stage_phase_name

    emitted = set(_RESTORE_MANAGER_PHASES) | {"tuning"}
    for stage in restore_stage_plan(commit=True, reindex_imported=True):
        emitted.add(_stage_phase_name(stage))
    for stage in restore_stage_plan(commit=True, hold_after_merge=True):
        emitted.add(_stage_phase_name(stage))
    unmapped = sorted(p for p in emitted if stage_for_phase(p) is None)
    assert not unmapped, f"these phases render as an absent stage: {unmapped}"
    # ANTI-VACUITY: the derivation must actually have found phases, or the loop above
    # proves nothing (an empty set has no unmapped members).
    assert len(emitted) >= 12, f"only {len(emitted)} phases derived -- the derivation broke"


def test_an_unknown_phase_is_an_absence_and_never_stage_one():
    """The ``.get(key, 0)`` family, at the level of a stage number. A row that advanced
    on an unrecognised string would be reporting a measurement nobody made."""
    for phase in ("", None, "done", "cancelled", "refused", "skipped-already-merged",
                  "a-phase-nobody-has-written-yet"):
        assert stage_for_phase(phase) is None, phase


def test_the_four_stages_are_in_the_order_the_dialog_draws_them():
    assert (STAGE_VERIFY_STAGE, STAGE_MERGE_SWAP, STAGE_SEARCH_INDEX, STAGE_REINDEX) == (1, 2, 3, 4)


# --------------------------------------------------------------------------- #
#  2. The stage ROWS count item states, which are unambiguous
# --------------------------------------------------------------------------- #
def _rows(items, *, live=None, tuning_done=False, run_state="running"):
    return {r["key"]: r for r in ImportQueueManager._stage_rows(items, live, tuning_done, run_state)}


def _item(state, kind="corpus", **kw):
    return {"kind": kind, "state": state, **kw}


def test_a_staged_item_has_not_passed_the_swap():
    """THE LOAD-BEARING ONE at K = 3. ``staged`` means the merge landed in a working
    copy nothing has swapped in, so counting it under "merge and save" would claim the
    corpus change its own label denies -- and the three statements are keyed off this
    number, so the claim would propagate into "the import files can be removed"."""
    rows = _rows([_item("staged"), _item("staged")])
    assert rows["verify_stage"]["done"] == 2, "a staged item HAS passed verify+stage"
    assert rows["merge_swap"]["done"] == 0, "nothing has been swapped in"
    assert rows["merge_swap"]["total"] == 2


def test_a_committed_item_has_passed_both_stages():
    rows = _rows([_item("done"), _item("staged")])
    assert rows["verify_stage"]["done"] == 2
    assert rows["merge_swap"]["done"] == 1


def test_a_failed_item_is_reported_and_never_shrinks_the_denominator():
    """Anti-capping, one row down: a denominator quietly reduced to make a row read
    complete is the same defect as a displayed figure that is secretly a cap."""
    rows = _rows([_item("done"), _item("error"), _item("cancelled")])
    assert rows["merge_swap"]["total"] == 3, "the operator queued three"
    assert rows["merge_swap"]["done"] == 1
    assert rows["merge_swap"]["failed"] == 2


def test_a_kind_that_does_not_walk_the_stages_is_not_in_the_denominator():
    """A large-data copy and a newsletter import are real work with their own progress
    and no artifact to verify, working copy to merge or swap to commit. Counting them
    would make the stage rows describe a population they do not measure."""
    rows = _rows([_item("done"), _item("done", kind="blobs"), _item("done", kind="newsletters")])
    assert rows["verify_stage"]["total"] == 1
    assert set(STAGE_WALKING_KINDS) == {"corpus", "legacy"}


def test_the_running_row_is_the_one_the_live_phase_belongs_to():
    rows = _rows([_item("running")], live={"progress": {"phase": "merging"}})
    assert rows["merge_swap"]["state"] == "running"
    assert rows["verify_stage"]["state"] == "pending"
    assert rows["merge_swap"]["phase"] == "merging"


def test_a_straddling_phase_is_labelled_as_such_rather_than_resolved():
    """`S04-02` §6 says the mapping of a phase that straddles two stages is NOT this
    slice's to decide. Nothing rests on it -- the rows count item states -- and the
    payload SAYS which phases are ambiguous rather than implying the boundary is
    settled. Both directions are pinned: an unambiguous phase must not be flagged."""
    ambiguous = _rows([_item("running")], live={"progress": {"phase": "quarantine_scan"}})
    assert ambiguous["merge_swap"]["phase_stage_is_exact"] is False
    exact = _rows([_item("running")], live={"progress": {"phase": "swap"}})
    assert exact["merge_swap"]["phase_stage_is_exact"] is True


def test_the_search_index_stage_publishes_no_progress_and_says_why():
    """SQLite reports neither a percentage nor an ETA for an FTS5 'optimize', so a bar
    over it would be invented. ``measured: false`` plus a reason is the whole contract
    the renderer keys on."""
    row = _rows([_item("done")])["search_index"]
    assert row["measured"] is False
    assert row["reason"] and "no progress" in row["reason"]
    assert row["state"] == "pending" and row["done"] == 0
    assert _rows([_item("done")], tuning_done=True)["search_index"]["state"] == "done"


def test_a_stopped_run_never_reaches_its_own_last_stage():
    """Ruling item 15 makes Stop immediate and the tuning pass is skipped by it, so a
    stopped run must not read as complete."""
    row = _rows([_item("done")], run_state="stopped")["search_index"]
    assert row["skipped"] is True and row["state"] != "done"
    assert _rows([_item("done")], tuning_done=True, run_state="stopped")["search_index"]["skipped"] is False


def test_stage_four_reports_no_number_of_its_own_and_names_who_owns_it():
    """The re-index outlives the run and has its own durable cursor, so a figure the
    queue published here would be stale the moment the dialog closed. The ENDPOINT is
    named instead -- which is also what makes the dialog's single poll chain able to
    fill the row without a second chain."""
    row = _rows([_item("done")])["reindex"]
    assert row["measured"] is False
    assert row["state"] == "external"
    assert row["reads"] == "/api/backup/reindex-backlog/resume/status"
    assert "done" not in row and "total" not in row, "the queue must not publish a count it does not own"


def test_an_empty_run_has_no_stage_rows_claiming_completeness():
    rows = _rows([])
    assert rows["verify_stage"]["total"] == 0
    assert rows["verify_stage"]["state"] != "done", "zero of zero is not a finished import"


# --------------------------------------------------------------------------- #
#  3. The per-item stage, and whether it applies at all
# --------------------------------------------------------------------------- #
def test_the_item_says_whether_the_stages_apply_before_it_says_where_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._items = [
        {"id": "0-corpus", "kind": "corpus", "state": "running", "stage_reached": 2},
        {"id": "1-blobs", "kind": "blobs", "state": "running", "stage_reached": None},
    ]
    items = {it["id"]: it for it in mgr.status()["items"]}
    assert items["0-corpus"]["stage_applicable"] is True
    assert items["0-corpus"]["stage"] == 2
    assert items["1-blobs"]["stage_applicable"] is False
    assert items["1-blobs"]["stage"] is None


def test_the_recorded_stage_is_a_high_water_mark_not_the_latest_poll(tmp_path, monkeypatch):
    """run_restore's stages are ordered, but a reader polling once a second sees
    whichever one is in flight; a cheap post-swap step reporting late must not send the
    row backwards. ``max`` is the mechanism, and the mutation that drops it makes the
    second assertion fail by name."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._items = [{"id": "0-corpus", "kind": "corpus", "state": "running", "stage_reached": None}]
    mgr._cursor = 0
    mgr._note_stage({"progress": {"phase": "verifying"}})
    assert mgr._items[0]["stage_reached"] == STAGE_VERIFY_STAGE
    mgr._note_stage({"progress": {"phase": "swap"}})
    assert mgr._items[0]["stage_reached"] == STAGE_MERGE_SWAP
    mgr._note_stage({"progress": {"phase": "verifying"}})
    assert mgr._items[0]["stage_reached"] == STAGE_MERGE_SWAP, "a stage row must not go backwards"


def test_a_stage_note_for_a_non_walking_kind_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._items = [{"id": "0-blobs", "kind": "blobs", "state": "running", "stage_reached": None}]
    mgr._cursor = 0
    mgr._note_stage({"progress": {"phase": "merging"}})
    assert mgr._items[0]["stage_reached"] is None


# --------------------------------------------------------------------------- #
#  4. Q214: the options that moved, and the one the corpus path refuses
# --------------------------------------------------------------------------- #
def test_the_corpus_path_refuses_a_selective_restore_it_cannot_honour(tmp_path, monkeypatch):
    """An accepted-and-discarded control tells an operator their choice took effect
    when it did not -- the same family as a settings key present in the store and the
    writer but absent from the request model (2026-09-16). The volume path stages
    inside the volume manager and has no seam the newsletter filter can edit, so it
    refuses BY NAME and points at the path that can."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    with pytest.raises(ValueError) as exc:
        mgr._run_corpus({"path": str(tmp_path), "include_newsletters": False})
    assert "include_newsletters=false is not available" in str(exc.value)
    assert "legacy" in str(exc.value), "the refusal must name the path that CAN honour it"


def _stop_and_join(mgr) -> None:
    """stop() signals the worker and returns; the worker then calls
    start_reindex_drain() on its way out. Join it, so that call lands in the
    test that started it and never in a later test that patches the same name
    (the boot-resume opt-out test below failed on CI exactly that way)."""
    mgr.stop()
    if mgr._thread is not None:
        mgr._thread.join(timeout=10)
        assert not mgr._thread.is_alive(), "the import worker outlived its test"


def _no_real_drain(monkeypatch) -> None:
    import src.backup.volume_job as vj

    monkeypatch.setattr(vj, "start_reindex_drain", lambda: (False, "stubbed in test"))


def test_the_queue_item_declares_both_moved_options(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    _no_real_drain(monkeypatch)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    st = mgr.start(
        [{"kind": "legacy", "path": str(tmp_path / "x.oobak"),
          "allow_unverified": True, "include_newsletters": False}],
        passphrase="pw",
    )
    _stop_and_join(mgr)
    it = st["items"][0]
    assert it["allow_unverified"] is True
    assert it["include_newsletters"] is False


def test_the_defaults_reproduce_todays_behaviour_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    _no_real_drain(monkeypatch)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    st = mgr.start([{"kind": "legacy", "path": str(tmp_path / "x.oobak")}], passphrase="pw")
    _stop_and_join(mgr)
    it = st["items"][0]
    assert it["allow_unverified"] is False
    assert it["include_newsletters"] is True


# --------------------------------------------------------------------------- #
#  5. Q201/Q222: what the report listing can honestly say
# --------------------------------------------------------------------------- #
def _write_report(tmp_path, monkeypatch, payload, name="restore"):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    from src.backup.import_reports import persist_import_report

    return persist_import_report(name, payload)


def test_a_committed_report_lists_its_article_count_as_merged(tmp_path, monkeypatch):
    from src.backup.import_reports import list_import_reports

    _write_report(tmp_path, monkeypatch, {"plan": {"articles": {"new": 12340, "duplicate": 7}}})
    row = list_import_reports()[0]
    assert row["articles"] == 12340
    assert row["articles_basis"] == "merged"
    assert row["duplicates"] == 7


def test_an_aborted_report_labels_its_figure_as_planned(tmp_path, monkeypatch):
    """A run that did not complete still carries a plan -- it is computed before the
    commit point -- so publishing the number without its basis is how "686,896 new
    articles" comes to head a run that committed nothing."""
    from src.backup.import_reports import list_import_reports

    _write_report(tmp_path, monkeypatch,
                  {"outcome": "killed", "plan": {"articles": {"new": 686896}}})
    row = list_import_reports()[0]
    assert row["articles"] == 686896
    assert row["articles_basis"] == "planned"
    assert row["outcome"] == "killed"


def test_an_unreadable_report_has_NO_article_figure_rather_than_a_zero(tmp_path, monkeypatch):
    """0 says "this import added nothing". The truth is "we could not read it", and
    the two are different facts."""
    from src.backup.import_reports import list_import_reports

    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    d = tmp_path / "import_reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "restore-20260916T000000Z-abcd.json").write_text("{ this is not json", encoding="utf-8")
    row = list_import_reports()[0]
    assert row["outcome"] == "unknown"
    assert "articles" not in row
    assert "articles_basis" not in row


def test_a_report_with_no_article_figure_omits_it(tmp_path, monkeypatch):
    from src.backup.import_reports import list_import_reports

    _write_report(tmp_path, monkeypatch, {"plan": {"sources": {"new": 4}}})
    row = list_import_reports()[0]
    assert row["outcome"] == "ok"
    assert "articles" not in row


def test_a_newsletter_tally_supplies_the_headline_when_there_is_no_plan(tmp_path, monkeypatch):
    from src.backup.import_reports import list_import_reports

    _write_report(tmp_path, monkeypatch, {"tally": {"new": 55}}, name="newsletters")
    row = list_import_reports()[0]
    assert row["articles"] == 55 and row["articles_basis"] == "merged"


# --------------------------------------------------------------------------- #
#  6. Q205: the boot auto-resume
# --------------------------------------------------------------------------- #
def test_the_boot_resume_starts_the_drain(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.delenv("OO_REINDEX_AUTORESUME", raising=False)
    import src.backup.volume_job as vj
    from src.api.main import _resume_reindex_backlog_at_boot

    monkeypatch.setattr(vj, "start_reindex_drain", lambda: (calls.append("start") or (True, None)))
    _resume_reindex_backlog_at_boot(42)
    for _ in range(200):
        if calls:
            break
        import time as _t

        _t.sleep(0.01)
    assert calls == ["start"], "boot must start the drain, not only log the backlog"


def test_the_boot_resume_declines_under_its_own_opt_out(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.setenv("OO_REINDEX_AUTORESUME", "0")
    import src.backup.volume_job as vj
    from src.api.main import _resume_reindex_backlog_at_boot

    monkeypatch.setattr(vj, "start_reindex_drain", lambda: (calls.append("start") or (True, None)))
    _resume_reindex_backlog_at_boot(42)
    import time as _t

    _t.sleep(0.15)
    assert calls == [], "OO_REINDEX_AUTORESUME=0 must decline it"


def test_the_boot_resume_is_inert_under_the_suites_own_gate(monkeypatch):
    """Adding an ACTION to a production path makes it a side effect of every test that
    drives that path. ``conftest`` sets ``OO_NO_SCHEDULER=1`` session-wide, exactly as
    it does for the other boot-time background work, and this pins that the gate is
    read here rather than only in the caller."""
    calls: list[str] = []
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.delenv("OO_REINDEX_AUTORESUME", raising=False)
    import src.backup.volume_job as vj
    from src.api.main import _resume_reindex_backlog_at_boot

    monkeypatch.setattr(vj, "start_reindex_drain", lambda: (calls.append("start") or (True, None)))
    _resume_reindex_backlog_at_boot(42)
    import time as _t

    _t.sleep(0.15)
    assert calls == []


def test_the_boot_resume_never_blocks_the_boot(monkeypatch):
    """The drain is the heaviest writer this process runs. A boot that waited on it
    would make a large backlog an app that will not start -- the recorded shape where
    the worse the incident, the more likely the boot path is what pays for it."""
    import threading
    import time as _t

    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.delenv("OO_REINDEX_AUTORESUME", raising=False)
    import src.backup.volume_job as vj
    from src.api.main import _resume_reindex_backlog_at_boot

    gate = threading.Event()
    # ALWAYS the tuple. `gate.wait(5) or (True, None)` returned the bare `True` once the
    # gate was set -- which it is, below -- so the boot thread this leaves behind raised
    # "cannot unpack non-iterable bool object" into whichever test ran next (macOS CI
    # captured it in the setup log of the kill-and-boot test, 2026-09-24).
    monkeypatch.setattr(vj, "start_reindex_drain", lambda: (gate.wait(5), (True, None))[1])
    t0 = _t.monotonic()
    _resume_reindex_backlog_at_boot(1)
    elapsed = _t.monotonic() - t0
    gate.set()
    assert elapsed < 1.0, f"the boot call blocked for {elapsed:.2f}s on the drain"


# --------------------------------------------------------------------------- #
#  7. The gate's test (2): a kill between stages 3 and 4, then a boot
# --------------------------------------------------------------------------- #
_KILL_AND_BOOT = r'''
import json, os, signal, sys, time
sys.path.insert(0, %(repo)r)

def merge_then_die(artifact, passphrase):
    from src.backup.artifact import read_artifact
    from src.backup.merge import reindex_backlog, run_restore
    from src.database.session import init_db
    init_db()
    staged = read_artifact(open(artifact, "rb").read(), passphrase=passphrase)
    # reindex_imported=False is the DEFERRED path every committing restore takes, so
    # the batch is left stamped `merged` -- the durable cursor stage 4 resumes from.
    run_restore(staged, commit=True, reindex_imported=False)
    bk = reindex_backlog()
    print(json.dumps({"pending_before_kill": bk.get("articles_pending")}), flush=True)
    # THE KILL, between stage 3 and stage 4: SIGKILL runs no shutdown path at all, so
    # nothing here can flush a state a clean exit would have written.
    os.kill(os.getpid(), signal.SIGKILL)

def boot_and_drain():
    from src.backup.merge import reindex_backlog
    from src.database.session import init_db
    init_db()
    before = reindex_backlog()
    from src.api.main import _resume_reindex_backlog_at_boot
    _resume_reindex_backlog_at_boot(int(before.get("articles_pending") or 0))
    from src.api.backup_v2 import _REINDEX_RESUME_JOB
    deadline = time.time() + 120
    started = False
    seen = []
    # ANY state past "idle" proves the drain started IN THIS PROCESS (the job object is
    # fresh here). Watching for "running" alone raced: a drain that starts and finishes
    # between two 0.1 s polls goes idle -> done unseen, and read as never started --
    # macOS CI on PR #1147 (7adcfec6) and on PR #1171 (d0ce56e2). A terminal state also
    # ends the wait. This is the patch OPEN_QUEUE.md filed for it under #1147, after
    # measuring the real boot path: a ~224 ms `running` window against a 100 ms sampler.
    while time.time() < deadline:
        state = _REINDEX_RESUME_JOB.status().get("state")
        if not seen or seen[-1] != state:
            seen.append(state)
        if state and state != "idle":
            started = True
        if state in ("done", "cancelled", "error"):
            break
        time.sleep(0.1)
    after = reindex_backlog()
    print(json.dumps({
        "started": started,
        "states": seen,
        "pending_before_boot": before.get("articles_pending"),
        "pending_after": after.get("articles_pending"),
    }), flush=True)

if sys.argv[1] == "merge-then-die":
    merge_then_die(sys.argv[2], sys.argv[3])
else:
    boot_and_drain()
'''


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL; the POSIX torture harness shape")
def test_a_kill_between_stages_three_and_four_resumes_on_the_next_boot(tmp_path):
    """THE GATE'S TEST (2), driven end to end in subprocesses.

    An import that is killed after its swap but before the re-index finishes leaves a
    batch stamped ``merged``: the corpus is safe, and those articles carry NO keywords
    until the re-index completes. Before Q205 the next boot only LOGGED that, so the
    operator who closed the app because the dialog told them it was safe had no way to
    get the work finished except by finding a button. This proves the boot picks it up.

    Three processes, because the property is about what survives a process: one builds,
    one merges and SIGKILLs itself, one boots. A SIGKILL runs no shutdown path, so the
    pending backlog the third process reads can only have come from the database.
    """
    script = tmp_path / "kill_and_boot.py"
    script.write_text(_KILL_AND_BOOT % {"repo": str(_REPO)}, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    art = tmp_path / "incoming.oobak.ooenc"

    def _env(d: Path, **extra: str) -> dict:
        e = {**os.environ, "OO_DATA_DIR": str(d), "OO_DB_PLAINTEXT": "1",
             "PYTHONPATH": str(_REPO), **extra}
        e.pop("OO_REINDEX_AUTORESUME", None)
        return e

    helper = str(_REPO / "tests" / "torture_helper.py")
    # The INCOMING corpus is built in its own data dir with its own content tag, so
    # merging it into the target is a real import rather than a self-merge -- which
    # would add nothing and leave no backlog for stage 4 to resume.
    build = subprocess.run(
        [sys.executable, helper, "build", "B", "--tag", "K",
         "--artifact", str(art), "--passphrase", "kill-pw"],
        capture_output=True, text=True, env=_env(src_dir, OO_NO_SCHEDULER="1"), timeout=300,
    )
    assert build.returncode == 0, build.stderr[-2000:]
    seed = subprocess.run(
        [sys.executable, helper, "build", "A"],
        capture_output=True, text=True, env=_env(data, OO_NO_SCHEDULER="1"), timeout=300,
    )
    assert seed.returncode == 0, seed.stderr[-2000:]
    env = _env(data, OO_NO_SCHEDULER="0")

    merged = subprocess.run(
        [sys.executable, str(script), "merge-then-die", str(art), "kill-pw"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    # -SIGKILL is the point: the process must NOT have exited cleanly.
    assert merged.returncode == -signal.SIGKILL, (merged.returncode, merged.stderr[-2000:])
    pending = json.loads(merged.stdout.strip().splitlines()[-1])["pending_before_kill"]
    assert pending and pending > 0, "the fixture must leave real work for stage 4"

    booted = subprocess.run(
        [sys.executable, str(script), "boot"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert booted.returncode == 0, booted.stderr[-3000:]
    out = json.loads(booted.stdout.strip().splitlines()[-1])
    assert out["pending_before_boot"] == pending, "the kill's backlog must survive the restart"
    assert out["started"] is True, (
        f"boot must START the drain, not merely report the backlog (states seen: {out['states']})"
    )
    assert out["pending_after"] == 0, (
        f"the resume left {out['pending_after']} article(s) un-re-indexed"
    )


# --------------------------------------------------------------------------- #
#  7. The adversarial pass, 2026-09-16: four findings, hand-verified, fixed here
# --------------------------------------------------------------------------- #
def test_a_refused_restore_is_never_reported_as_done():
    """THE INVERTED PICTURE. A post-merge verification refusal returns NORMALLY from
    ``run_restore`` -- it is a well-formed answer, not a crash -- with ``refused`` set
    and ``committed: False``. Every layer above read "the job finished" as "the import
    worked": ``volume_job`` recorded state ``done`` with ``held`` False (a refused
    report returns before the branch that sets ``held``), and the queue wrote ``done``.

    In a K-group that inverted the whole reading: ``_after_item`` discards the group,
    so the two GOOD backups read ``discarded`` while the CORRUPT one read ``done``. An
    operator trusting that label deletes the only copy of the one backup that failed.
    """
    corpus = {"held": False, "report": {"committed": False, "refused": "post-merge verification failed"}}
    assert _refusal_of(corpus) == "post-merge verification failed"
    # THE LEGACY SHAPE TOO: restore_legacy_path returns the report ITSELF, and that path
    # has no group bookkeeping to catch it, so it was the half with no guard at all.
    assert _refusal_of({"committed": False, "refused": "bad archive"}) == "bad archive"
    # A committed report, a held one and a junk one are all NOT refusals.
    assert _refusal_of({"held": True, "report": {"held": True}}) is None
    assert _refusal_of({"held": False, "report": {"committed": True}}) is None
    assert _refusal_of({}) is None and _refusal_of(None) is None  # type: ignore[arg-type]


def test_a_refusal_is_not_read_out_of_committed_alone():
    """``committed: False`` is ALSO what a preview returns. The queue has no preview
    path today, and reading "not committed" as "refused" would make one wrong the day
    it grows one -- so the key is ``refused`` and nothing else."""
    assert _refusal_of({"held": False, "report": {"committed": False}}) is None


def test_an_interrupted_item_is_counted_as_failed_not_left_uncounted():
    """A killed run's own item comes back as ``interrupted``. It was in neither the
    done set nor the failed set, so a dead run's rows read exactly like a live run's
    with one item still to go."""
    rows = _rows([_item("done"), _item("interrupted")], run_state="interrupted")
    assert rows["verify_stage"]["failed"] == 1
    assert rows["merge_swap"]["failed"] == 1


def test_no_item_is_counted_both_as_passed_and_as_failed():
    """A discarded item can carry ``stage_reached >= 2`` -- it really did verify and
    merge before the group was thrown away -- and counting it under both made
    ``done + failed`` exceed ``total``, which is not a picture a reader can resolve."""
    items = [
        _item("discarded", stage_reached=STAGE_MERGE_SWAP),
        _item("discarded", stage_reached=STAGE_MERGE_SWAP),
        _item("error", stage_reached=STAGE_MERGE_SWAP),
    ]
    for row in (_rows(items)["verify_stage"], _rows(items)["merge_swap"]):
        assert row["done"] + row["failed"] <= row["total"], row
    assert _rows(items)["verify_stage"]["done"] == 0
    assert _rows(items)["verify_stage"]["failed"] == 3
    # ...and the denominator still does not shrink.
    assert _rows(items)["verify_stage"]["total"] == 3


def test_a_run_that_ended_does_not_report_its_stages_as_still_pending():
    """``pending`` is a claim about the FUTURE -- "not yet". After an interrupted,
    stopped, failed or cancelled run there is no future without the operator starting a
    new import, so a row that is neither running nor done must name which ending it
    was."""
    # Reported in the ITEM-state vocabulary, so the dialog labels it with the four
    # strings it already ships x12 instead of growing four more for the same words.
    for run_state, expected in (
        ("interrupted", "interrupted"),
        ("stopped", "stopped"),
        ("error", "error"),
        ("cancelled", "cancelled"),
        ("running", "pending"),   # the live case is unchanged
        ("idle", "pending"),      # an unknown run state falls back, never invents
    ):
        rows = _rows([_item("queued"), _item("queued")], run_state=run_state)
        assert rows["verify_stage"]["state"] == expected, run_state


def test_the_refusal_is_wired_into_the_queue_loop_not_only_available_to_it(tmp_path):
    """THE WIRING, not the helper. The first version of this guard tested `_refusal_of`
    alone and a mutation that disabled the branch USING it survived the matrix -- a
    helper that is correct and unreached is exactly the shape of the defect it was
    written for.

    Drives the real `_drive` loop with the sub-managers stubbed out, which is the only
    way to observe the state the loop actually writes.
    """
    q = ImportQueueManager(state_path=tmp_path / "q.json")
    q._items = [
        {"id": "0-corpus", "kind": "corpus", "path": "/a", "label": "good", "state": "queued"},
        {"id": "1-corpus", "kind": "corpus", "path": "/b", "label": "corrupt", "state": "queued"},
        {"id": "2-legacy", "kind": "legacy", "path": "/c", "label": "old", "state": "queued"},
    ]
    outcomes = {
        "0-corpus": {"held": False, "report": {"committed": True}},
        # the corpus shape: run_restore's report, wrapped by volume_job
        "1-corpus": {"held": False, "report": {"committed": False, "refused": "checksum mismatch"}},
        # the legacy shape: the report itself, with no group bookkeeping behind it
        "2-legacy": {"committed": False, "refused": "archive truncated"},
    }
    q._run_item = lambda item, hold=False: outcomes[item["id"]]  # type: ignore[method-assign]
    q._drive()

    assert [it["state"] for it in q._items] == ["done", "error", "error"]
    assert q._items[1]["error"] == "checksum mismatch"
    assert q._items[2]["error"] == "archive truncated"
    # ...and the stage row agrees: one swapped, two failed, the denominator intact.
    rows = _rows(q._items, run_state="done")
    assert (rows["merge_swap"]["done"], rows["merge_swap"]["failed"],
            rows["merge_swap"]["total"]) == (1, 2, 3)


def test_a_skipped_backup_counts_as_reaching_the_corpus_and_agrees_with_the_payload():
    """An item is SKIPPED because the backup is already in the corpus -- found by digest
    before anything is staged -- which is the same fact the row reports for `done`.

    Counting only `done` broke the ORDINARY finished run, not an exotic one: the field
    log records 8 of 18 imports adding zero articles, so a skip is the common case, and a
    run that ended with one read `2 of 3` with `failed: 0` and a state of `pending` --
    "more is coming" about a run that was over.
    """
    items = [_item("done"), _item("skipped"), _item("done")]
    rows = _rows(items, run_state="done")
    for key in ("verify_stage", "merge_swap"):
        assert (rows[key]["done"], rows[key]["failed"], rows[key]["total"]) == (3, 0, 3), key
        assert rows[key]["state"] == "done", key
    # ...and it agrees with the payload's own committed count, which has always been
    # ("done", "skipped"). Two facts about one thing, in one response, must not differ.
    assert rows["merge_swap"]["done"] == sum(
        1 for it in items if it["state"] in ("done", "skipped")
    )
    # A STAGED item is still not counted: nothing has swapped it in.
    staged = _rows([_item("done"), _item("staged")], run_state="running")
    assert staged["merge_swap"]["done"] == 1

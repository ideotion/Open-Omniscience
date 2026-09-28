"""What the import queue RECORDS about a run -- never what it merges.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-09-26 click-through walk of the Import dialog (row I of RELEASE_0.4_GATE,
batch B1) found four defects that live in the queue's record rather than in its
merge. Every test here pins one of them, and every one of them also asserts the
NEGATIVE SPACE: the item states, the item summaries and the reports the merge
produced are exactly what they were, because a record that could change what a run
says it imported would be the defect this module exists to prevent.

* **I4** -- a run killed in its TAIL (stage 3, the search-index merge, after every
  item had recorded its outcome) booted as "interrupted -- start it again", right
  after the dialog had said "Safe to close".
* **I5** -- the checkpoint sentence read the LAST run's captured K, so an operator who
  set K = 1 was still told "once every 3 backups".
* **I7** -- a HELD backup (K > 1) left no persisted import report: its merge reached
  the corpus through a later backup's swap, and ``run_restore`` persists only on its
  own commit path. The history of a four-backup import listed two.
* **I10** -- stage 3's outcome was memory-only, so a restart read a search-index merge
  that had run as "not started".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.backup import import_queue as iq
from src.backup.import_queue import ImportQueueManager
from src.backup.import_reports import (
    list_import_reports,
    persist_import_report,
    read_import_report,
    render_import_report_markdown,
)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.delenv("OO_IMPORT_CHECKPOINT_K", raising=False)
    yield tmp_path


def _items(n: int, kind: str = "corpus") -> list[dict]:
    return [
        {"id": f"{i}-{kind}", "kind": kind, "path": f"/backups/b{i}", "label": f"backup-{i}",
         "state": "queued", "started_at": None, "ended_at": None, "error": None,
         "summary": None}
        for i in range(n)
    ]


def _rows(q: ImportQueueManager) -> dict:
    return {r["key"]: r for r in q.status()["stages"]}


# --------------------------------------------------------------------------- #
#  I4: a run killed in its tail is a finished run, not an interrupted one
# --------------------------------------------------------------------------- #
def _drive_until_stage_three(tmp_path: Path, outcomes: dict) -> tuple[ImportQueueManager, bytes]:
    """Drive the REAL ``_drive`` loop with the sub-managers stubbed, and capture the
    state file at the moment stage 3 begins -- exactly what a kill during the
    search-index merge leaves on disk."""
    state = tmp_path / "import_queue.json"
    q = ImportQueueManager(state_path=state)
    q._items = _items(len(outcomes))
    q._state = "running"   # what start() records before the thread runs _drive
    q._run_id = "run-i4"
    q._run_item = lambda item, hold=False: outcomes[item["id"]]  # type: ignore[method-assign]
    q._decide_hold = lambda idx, item: False  # type: ignore[method-assign]
    seen: dict[str, bytes] = {}

    def killed_in_stage_three() -> None:
        seen["on_disk"] = state.read_bytes()

    q._tune_after_run = killed_in_stage_three  # type: ignore[method-assign]
    q._drive()
    return q, seen["on_disk"]


def _boot(tmp_path: Path, on_disk: bytes) -> ImportQueueManager:
    booted = tmp_path / "booted.json"
    booted.write_bytes(on_disk)
    return ImportQueueManager(state_path=booted)


def test_a_run_killed_in_stage_three_boots_as_finished_not_interrupted(tmp_path):
    outcomes = {
        "0-corpus": {"held": False, "report": {"committed": True, "plan": {"articles": {"new": 1200}}}},
        "1-corpus": {"held": False, "report": {"committed": True, "plan": {"articles": {"new": 1200}}}},
    }
    _, on_disk = _drive_until_stage_three(tmp_path, outcomes)
    raw = json.loads(on_disk)
    assert raw["state"] == "running", "the precondition: the kill lands before the last save"

    q = _boot(tmp_path, on_disk)
    st = q.status()
    assert st["state"] == "done", (
        "every backup had recorded its outcome and was in the corpus; 'interrupted -- start "
        "it again' asks the operator to redo an import that landed"
    )
    rows = _rows(q)
    assert rows["merge_swap"]["state"] == "done"
    # ...and the one thing that DID not finish is said, not called done.
    assert rows["search_index"]["state"] == "interrupted"
    assert rows["search_index"]["done"] == 0


def test_the_boot_changes_no_item_and_no_summary(tmp_path):
    """The recorded half of the data-safety rule: the boot's verdict is DERIVED from
    what the items recorded, and rewrites none of it."""
    outcomes = {
        "0-corpus": {"held": False, "report": {"committed": True, "batch_id": "b0"}},
        "1-corpus": {"held": False, "report": {"committed": False, "refused": "checksum mismatch"}},
    }
    _, on_disk = _drive_until_stage_three(tmp_path, outcomes)
    recorded = json.loads(on_disk)["items"]
    q = _boot(tmp_path, on_disk)
    assert q._items == recorded, "the items are exactly what the run recorded"
    assert [it["state"] for it in q._items] == ["done", "error"]
    # An error item makes it the run's own "error" verdict, the one _drive would write.
    assert q.status()["state"] == "error"


def test_a_kill_with_an_item_still_running_is_still_interrupted(tmp_path):
    """The twin: an item that never recorded its outcome IS lost work."""
    state = tmp_path / "q.json"
    state.write_text(json.dumps({
        "state": "running",
        "items": [
            {"id": "0", "kind": "corpus", "state": "done"},
            {"id": "1", "kind": "corpus", "state": "running"},
            {"id": "2", "kind": "corpus", "state": "queued"},
        ],
    }), encoding="utf-8")
    q = ImportQueueManager(state_path=state)
    assert q.status()["state"] == "interrupted"
    # Unchanged from before I4: only the item in flight is relabelled.
    assert [it["state"] for it in q._items] == ["done", "interrupted", "queued"]


def test_a_kill_with_a_staged_group_is_still_interrupted_and_discarded(tmp_path):
    state = tmp_path / "q.json"
    state.write_text(json.dumps({
        "state": "running",
        "items": [
            {"id": "0", "kind": "corpus", "state": "staged"},
            {"id": "1", "kind": "corpus", "state": "done"},
        ],
    }), encoding="utf-8")
    q = ImportQueueManager(state_path=state)
    assert q.status()["state"] == "interrupted"
    assert q._items[0]["state"] == "discarded"


# --------------------------------------------------------------------------- #
#  I10: stage 3's outcome survives a restart
# --------------------------------------------------------------------------- #
def test_stage_three_is_persisted_with_the_run(tmp_path):
    state = tmp_path / "q.json"
    q = ImportQueueManager(state_path=state)
    q._items = [{"id": "0", "kind": "corpus", "state": "done"}]
    q._state = "done"
    q._tuning_done = True
    q._tuned = {"fts_optimize": True, "pragma_optimize": False}
    q._run_id = "run-i10"
    q._save()

    back = ImportQueueManager(state_path=state)
    assert back._tuning_done is True
    assert back._tuned == {"fts_optimize": True, "pragma_optimize": False}
    assert back._run_id == "run-i10"
    assert _rows(back)["search_index"]["state"] == "done", "a merge that RAN is not 'not started'"


def test_a_state_file_written_before_the_flag_still_loads(tmp_path):
    """Backward compatible: no ``tuning_done`` key. A run recorded done or error reached
    its tail (the flag is set before that save); a stopped one skipped it."""
    for state_name, expected in (("done", True), ("error", True), ("stopped", False)):
        state = tmp_path / f"old-{state_name}.json"
        state.write_text(json.dumps({
            "state": state_name,
            "items": [{"id": "0", "kind": "corpus", "state": "done"}],
            "cursor": -1, "started_at": 1.0, "ended_at": 2.0,
        }), encoding="utf-8")
        q = ImportQueueManager(state_path=state)
        assert q._tuning_done is expected, state_name
        assert q._run_id is None and q._tuned is None
    assert _rows(ImportQueueManager(state_path=tmp_path / "old-done.json"))[
        "search_index"]["state"] == "done"


def test_a_malformed_optional_key_is_ignored_rather_than_trusted(tmp_path):
    state = tmp_path / "q.json"
    state.write_text(json.dumps({
        "state": "done", "items": [{"id": "0", "kind": "corpus", "state": "done"}],
        "tuning_done": "yes", "tuned": ["not", "a", "dict"], "run_id": 7,
    }), encoding="utf-8")
    q = ImportQueueManager(state_path=state)
    assert q._tuning_done is True, "a non-bool flag falls back to the state's own answer"
    assert q._tuned is None and q._run_id is None


# --------------------------------------------------------------------------- #
#  I5: an idle queue reports the K the NEXT run will use
# --------------------------------------------------------------------------- #
def test_an_idle_queue_reports_the_setting_not_the_last_runs_k(tmp_path, monkeypatch):
    import src.config.app_settings as app_settings

    monkeypatch.setattr(app_settings, "_settings_path", lambda: tmp_path / "app_settings.json")
    monkeypatch.setattr(app_settings, "_kv_enabled", lambda: False, raising=False)
    app_settings.save_settings({"import_checkpoint_k": 1})

    q = ImportQueueManager(state_path=tmp_path / "q.json")
    q._items = [{"id": "0", "kind": "corpus", "state": "done"}]
    q._state = "done"
    q._checkpoint_k = 3   # what the LAST run captured
    st = q.status()
    assert st["checkpoint"]["k"] == 1, "the operator set 1 and was told 'every 3 backups'"
    assert "as soon as it finishes" in st["checkpoint"]["note"]

    # ...while a run in flight keeps the K it started with (a group is never split).
    q._state = "running"
    assert q.status()["checkpoint"]["k"] == 3


# --------------------------------------------------------------------------- #
#  I7: every backup of a run leaves its own report, named and grouped
# --------------------------------------------------------------------------- #
def _held_report(i: int, working: Path) -> dict:
    return {
        "held": True, "committed": False, "batch_id": f"batch-{i}",
        "working_copy": str(working),
        "plan": {"articles": {"new": 1200, "duplicate": 0, "conflict": 0}},
        "held_note": "merged into the import's working copy and verified, but NOT yet written",
    }


def _group_of_three(tmp_path: Path) -> tuple[ImportQueueManager, dict]:
    """Two held backups and the one whose swap commits them, exactly as ``_drive``
    leaves them just before the committing item's ``_after_item``."""
    q = ImportQueueManager(state_path=tmp_path / "q.json")
    q._items = _items(4)
    q._run_id = "run-i7"
    gdir = tmp_path / ".restore-group-test"
    gdir.mkdir()
    (gdir / "working.db").write_bytes(b"not really a database")
    q._group = iq._CheckpointGroup(dir=gdir)
    for i in range(2):
        rep = _held_report(i, gdir / "working.db")
        q._items[i]["state"] = "staged"
        q._items[i]["summary"] = {"report": rep, "held": True, "state": "done"}
        q._group.item_ids.append(q._items[i]["id"])
    # The committing backup: run_restore has already persisted its own report.
    own = {"committed": True, "batch_id": "batch-2",
           "plan": {"articles": {"new": 1200, "duplicate": 0, "conflict": 0}}}
    own["persisted_report_path"] = str(persist_import_report("restore", own, run_id="batch-2"))
    summary = {"report": own, "held": False, "state": "done"}
    q._items[2]["state"] = "done"
    q._items[2]["summary"] = summary
    return q, summary


def test_a_held_backup_leaves_its_own_report_when_its_checkpoint_lands(tmp_path):
    q, summary = _group_of_three(tmp_path)
    q._after_item(q._items[2], summary)

    listed = list_import_reports()
    assert len(listed) == 3, "a three-backup group is three backups in the history"
    assert {r["run_id"] for r in listed} == {"run-i7"}, "one run, stamped on every report"
    assert [r["label"] for r in listed][0] == "backup-2", (
        "the committing backup's report stays the newest -- the order they landed"
    )
    assert sorted(r["label"] for r in listed) == ["backup-0", "backup-1", "backup-2"]
    # Each counts only what ITS backup added, so the run's reports sum without a
    # double count, and each is a MERGED figure: the checkpoint did land.
    assert [r.get("articles") for r in listed] == [1200, 1200, 1200]
    assert {r.get("articles_basis") for r in listed} == {"merged"}

    held = [read_import_report(r["filename"]) for r in listed if r["label"] == "backup-0"][0]
    assert held["committed"] is True
    assert held["committed_at_checkpoint"] == {"by_item": "backup-2"}
    assert "working_copy" not in held, "the swap consumed it; a dead path is not a record"
    assert "NOT yet written" not in held["held_note"], "a landed checkpoint is past tense"
    assert held["import_run"]["position"] == 1 and held["import_run"]["items_total"] == 4
    assert held["import_run"]["path"] == "/backups/b0"


def test_recording_the_reports_changes_no_state_and_no_summary(tmp_path, monkeypatch):
    """THE DATA-SAFETY HALF. The same group, committed once with the record and once
    with every report write failing: the item states, the summaries the merge
    produced and the group's own bookkeeping are identical."""
    a = tmp_path / "a"
    a.mkdir()
    monkeypatch.setattr("src.paths.data_dir", lambda: a)
    q, summary = _group_of_three(a)
    before = copy.deepcopy([it["summary"] for it in q._items])
    q._after_item(q._items[2], summary)
    states_with_record = [it["state"] for it in q._items]
    assert [it["summary"] for it in q._items[:2]] == before[:2], (
        "the held reports are written from COPIES; the merge's own report is untouched"
    )
    assert q._items[2]["summary"]["report"].get("import_run") is None

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("src.backup.import_reports.persist_import_report", boom)
    monkeypatch.setattr("src.backup.import_reports.annotate_import_report", boom)
    b = tmp_path / "b"
    b.mkdir()
    monkeypatch.setattr("src.paths.data_dir", lambda: b)
    q2, summary2 = _group_of_three_without_persist(b)
    q2._after_item(q2._items[2], summary2)
    assert [it["state"] for it in q2._items] == states_with_record == [
        "done", "done", "done", "queued"
    ]
    assert q2._group is None, "the checkpoint committed exactly as it would have"


def _group_of_three_without_persist(tmp_path: Path) -> tuple[ImportQueueManager, dict]:
    """``_group_of_three`` for a run whose report writes fail: the committing report
    was never persisted, so it carries no path."""
    q = ImportQueueManager(state_path=tmp_path / "q.json")
    q._items = _items(4)
    q._run_id = "run-i7b"
    gdir = tmp_path / ".restore-group-test"
    gdir.mkdir()
    q._group = iq._CheckpointGroup(dir=gdir)
    for i in range(2):
        q._items[i]["state"] = "staged"
        q._items[i]["summary"] = {"report": _held_report(i, gdir / "working.db"), "held": True}
        q._group.item_ids.append(q._items[i]["id"])
    summary = {"report": {"committed": True, "batch_id": "batch-2",
                          "persisted_report_path": str(tmp_path / "missing.json")},
               "held": False}
    q._items[2]["state"] = "done"
    q._items[2]["summary"] = summary
    return q, summary


def test_a_discarded_group_leaves_no_report_claiming_it_landed(tmp_path):
    q, _ = _group_of_three(tmp_path)
    q._discard_group("a later backup failed")
    labels = [r.get("label") for r in list_import_reports()]
    assert "backup-0" not in labels and "backup-1" not in labels, (
        "a report is written when a checkpoint LANDS; a discarded merge never did"
    )


def test_annotating_a_report_is_additive_only(tmp_path):
    from src.backup.import_reports import annotate_import_report

    p = persist_import_report("restore", {"plan": {"articles": {"new": 5}}, "import_run": "keep"})
    annotate_import_report(p, {"import_run": {"id": "x"}, "plan": {}, "extra": 1})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["import_run"] == "keep", "an existing key is never overwritten"
    assert data["plan"] == {"articles": {"new": 5}}, "nothing the restore measured changes"
    assert data["extra"] == 1


def test_the_markdown_names_the_backup_and_the_checkpoint_that_saved_it():
    md = render_import_report_markdown({
        "kind": "restore",
        "import_run": {"id": "r", "label": "backup-0", "path": "/backups/b0",
                       "position": 1, "items_total": 4},
        "committed_at_checkpoint": {"by_item": "backup-2"},
        "plan": {"articles": {"new": 1200, "duplicate": 0, "conflict": 0}},
    })
    assert "Source: `backup-0` (`/backups/b0`)" in md
    assert "Item 1 of the 4 in one import" in md
    assert "checkpoint that saved `backup-2`" in md


def test_a_report_without_the_stamp_renders_and_lists_exactly_as_before():
    md = render_import_report_markdown({"kind": "restore", "plan": {}})
    assert "Source:" not in md and "checkpoint that saved" not in md
    persist_import_report("restore", {"plan": {"articles": {"new": 3}}})
    (row,) = list_import_reports()
    assert "run_id" not in row and "label" not in row

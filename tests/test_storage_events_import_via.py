"""The storage-events journal's ``run_import`` also keeps the single-file restore of a legacy backup and the folder import of newsletter
files, told apart from the volume restore by a ``via`` key of a fixed table (WAL, 2026-10-16).

``run_import`` began as the volume restore. Two other ways to import ran for hours with no durable record of their own (a legacy backup
restored from a path, a folder of ``.eml`` files imported by a background job): a process killed in the middle of either left only the
lines the run journal had flushed, and a start that was refused left nothing. They record into the SAME kind (every restore is an
``import`` here; the run journal calls the newsletter one ``newsletter-import``), so a reader keeps one list of imports and tells them
apart by ``via``.

What this file pins:

1. ``via`` is one of four fixed keys; anything else is not recorded (a path or a folder name can never become the value);
2. every end of the legacy restore and of the newsletter import is its own outcome, with the CLASS of the failure and none of its words
   (the legacy restore holds a passphrase: the marker below must reach neither the journal file, the member, nor the slot's answer);
3. a start that is refused is a closed record with its fixed sentence and its ``via``;
4. the volume restore says ``volume-set``, so no import is recorded without one;
5. the hooks in the two new files hand over a class name, a key of a table and a named fact (the scan over the sources is in
   ``tests/test_storage_events_runs.py``, extended to these files).
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import backup_v2
from src.backup.merge import MergeError, RestoreAborted, RestoreRefused
from src.backup.volume_job import VolumeBackupManager
from src.database.models import Base
from src.ingest import import_job
from src.ingest.import_job import NewsletterImportManager
from src.monitoring import storage_events as se
from tests.test_storage_events_runs import (
    _events,
    _finish,
    _nothing_secret_anywhere,
    _only,
    raise_is_recorded_by_a_wrapper,
)

ROOT = Path(__file__).resolve().parents[1]
MARKER = "MARKER-passphrase-4711-correct-horse"
PASS = "hunter2-the-typed-passphrase"


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    se.reset_for_tests()
    yield path
    se.reset_for_tests()


# --------------------------------------------------------------------------- #
#  1. The table
# --------------------------------------------------------------------------- #
def test_via_is_one_of_four_fixed_keys():
    assert frozenset({"volume-set", "single-file", "newsletter-eml", "folder"}) == se.RUN_VIA


@pytest.mark.parametrize("via", sorted(se.RUN_VIA))
def test_a_key_of_the_table_is_recorded_as_it_is(journal, via):
    se.run_ended(se.run_started("import", via=via), "ok")
    assert _only("run_import")["via"] == via


@pytest.mark.parametrize(
    "value", [f"/home/someone/{MARKER}", "C:\\Users\\someone\\inbox", "single-file; drop", "", "VOLUME-SET", None, 7, b"single-file", ["single-file"]]
)
def test_a_value_outside_the_table_is_not_recorded_and_is_never_the_text(journal, value):
    se.run_ended(se.run_started("import", via=value), "ok")
    se.run_refused("import", "not-a-folder", via=value)
    for event in _events("run_import"):
        assert "via" not in event, event
    _nothing_secret_anywhere(journal, MARKER, "someone")


def test_every_refusal_key_the_new_paths_use_has_a_fixed_sentence():
    for key in ("not-a-file", "memory", "import-running"):
        assert key in se.RUN_REFUSALS and "{" not in se.RUN_REFUSALS[key], key


def test_the_member_says_what_via_is():
    for word in ("via", "volume-set", "single-file", "newsletter-eml", "folder"):
        assert word in se._METHOD, word


def test_the_new_counts_are_kept_as_numbers_only(journal):
    note = se.run_started("import", via="newsletter-eml", files=12, resumed_from=3)
    se.run_ended(note, "paused", files_done=7.0)
    event = _only("run_import")
    assert (event["files"], event["resumed_from"], event["files_done"]) == (12, 3, 7.0)
    note = se.run_started("import", files=MARKER, resumed_from=True, files_done=float("nan"))
    se.run_ended(note, "ok")
    last = _events("run_import")[-1]
    assert not ({"files", "resumed_from", "files_done"} & set(last)), last
    _nothing_secret_anywhere(journal, MARKER)


# --------------------------------------------------------------------------- #
#  2. The legacy single-file restore
# --------------------------------------------------------------------------- #
@pytest.fixture()
def legacy(tmp_path, monkeypatch):
    """A legacy backup file whose staging and merge are stubbed, so a test chooses how the merge ends."""
    monkeypatch.setattr(backup_v2, "read_artifact", lambda data, passphrase=None: SimpleNamespace(corpus_path=tmp_path / "c.db"))
    monkeypatch.setattr(backup_v2, "cleanup_staging", lambda staged: None)
    monkeypatch.setattr(backup_v2, "check_memory_before_staging", lambda: None)
    monkeypatch.setattr("src.backup.volume_job.defer_reindex", lambda: False)  # no backlog read: the merge itself is stubbed
    path = tmp_path / "old.bak"
    path.write_bytes(b"read_artifact is stubbed")
    return path


def test_a_legacy_restore_that_merges_ends_ok_via_single_file_with_its_figures(journal, legacy, monkeypatch):
    monkeypatch.setattr(backup_v2, "run_restore", lambda *a, **k: {"articles_merged": 7, "reindexed": 3})
    report = backup_v2.restore_legacy_path(str(legacy), PASS)
    assert report == {"articles_merged": 7, "reindexed": 3}, "the report is handed back as it was"
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["open"]) == ("single-file", "ok", False)
    assert (event["articles_merged"], event["reindexed"]) == (7, 3)
    assert isinstance(event["data_free_bytes"], int) and event["seconds"] >= 0
    _nothing_secret_anywhere(journal, PASS, str(legacy))


def test_the_legacy_restore_is_written_open_while_it_runs_so_a_kill_leaves_started_never_ended(journal, legacy, monkeypatch):
    seen: list[dict] = []

    def merging(*a, **k):
        seen.append(dict(_events("run_import")[-1]))
        return {}

    monkeypatch.setattr(backup_v2, "run_restore", merging)
    backup_v2.restore_legacy_path(str(legacy), PASS)
    assert seen and seen[0]["open"] is True and seen[0]["via"] == "single-file" and "outcome" not in seen[0]
    assert "data_free_bytes" in seen[0], "the free bytes were read before the merge began"


@pytest.mark.parametrize(
    ("raises", "outcome", "error", "status"),
    [
        (MergeError, "refused", "MergeError", 400),
        (RestoreRefused, "refused", "RestoreRefused", 400),
        (RestoreAborted, "stopped-by-operator", "RestoreAborted", 500),
        (ValueError, "error", "ValueError", 500),
    ],
)
def test_each_end_of_the_legacy_merge_has_its_own_outcome_and_never_its_words(journal, legacy, monkeypatch, raises, outcome, error, status):
    def merging(*a, **k):
        raise raises(f"the merge could not open the corpus with {PASS} {MARKER} at {legacy}")

    monkeypatch.setattr(backup_v2, "run_restore", merging)
    with pytest.raises(HTTPException) as caught:
        backup_v2.restore_legacy_path(str(legacy), PASS)
    assert caught.value.status_code == status, "the response is what it was before the record existed"
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["error"]) == ("single-file", outcome, error)
    _nothing_secret_anywhere(journal, PASS, MARKER, str(legacy), "could not open")


def test_a_path_that_is_not_a_file_is_a_refusal_with_its_sentence_and_not_its_path(journal, tmp_path):
    with pytest.raises(HTTPException) as caught:
        backup_v2.restore_legacy_path(str(tmp_path / f"no-such-{MARKER}"), PASS)
    assert caught.value.status_code == 400
    event = _only("run_import")
    assert (event["outcome"], event["ran"], event["via"]) == ("refused", False, "single-file")
    assert event["reason"] == se.RUN_REFUSALS["not-a-file"] and "open" not in event
    _nothing_secret_anywhere(journal, PASS, MARKER, str(tmp_path))


def test_a_machine_that_cannot_hold_the_merge_is_refused_before_anything_is_read(journal, legacy, monkeypatch):
    def refuse():
        raise MergeError(f"needs 9 GiB for {MARKER}")

    monkeypatch.setattr(backup_v2, "check_memory_before_staging", refuse)
    monkeypatch.setattr(backup_v2, "run_restore", lambda *a, **k: pytest.fail("the merge must not start"))
    with pytest.raises(HTTPException) as caught:
        backup_v2.restore_legacy_path(str(legacy), PASS)
    assert caught.value.status_code == 400
    event = _only("run_import")
    assert (event["outcome"], event["error"], event["reason"]) == ("refused", "MergeError", se.RUN_REFUSALS["memory"])
    assert event["open"] is False
    _nothing_secret_anywhere(journal, PASS, MARKER, "9 GiB")


def test_a_file_that_cannot_be_read_is_an_error_with_the_class(journal, legacy, monkeypatch):
    def unreadable(self):
        raise PermissionError(f"{MARKER} {self}")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    with pytest.raises(HTTPException):
        backup_v2.restore_legacy_path(str(legacy), PASS)
    event = _only("run_import")
    assert (event["outcome"], event["error"]) == ("error", "PermissionError")
    _nothing_secret_anywhere(journal, PASS, MARKER, str(legacy))


def test_a_file_that_cannot_be_opened_as_a_backup_is_an_error_not_a_run_left_open(journal, legacy, monkeypatch):
    from src.backup.artifact import ArtifactError

    def not_a_backup(data, passphrase=None):
        raise ArtifactError(f"wrong passphrase {PASS} for {MARKER}")

    monkeypatch.setattr(backup_v2, "read_artifact", not_a_backup)
    with pytest.raises(HTTPException) as caught:
        backup_v2.restore_legacy_path(str(legacy), PASS)
    assert caught.value.status_code == 400
    event = _only("run_import")
    assert (event["outcome"], event["error"], event["open"]) == ("error", "HTTPException", False)
    _nothing_secret_anywhere(journal, PASS, MARKER)


def test_an_exit_no_branch_names_still_closes_the_legacy_run(journal, legacy, monkeypatch):
    class Unhandled(BaseException):
        pass

    def selection(staged, *, include_newsletters):
        raise Unhandled

    monkeypatch.setattr(backup_v2, "_apply_restore_selection", selection)
    with pytest.raises(Unhandled):
        backup_v2.restore_legacy_path(str(legacy), PASS)
    assert _only("run_import")["outcome"] == "ended-without-a-recorded-outcome"


# --------------------------------------------------------------------------- #
#  3. The newsletter folder import
# --------------------------------------------------------------------------- #
@pytest.fixture()
def nl(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    folder = tmp_path / f"inbox-{MARKER}"
    folder.mkdir()
    for i in range(5):
        (folder / f"{i}.eml").write_bytes(
            (
                f"From: N <n@x.test>\nSubject: S{i}\nMessage-ID: <m{i}@x.test>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
                f"Content-Type: text/plain; charset=utf-8\n\nunique newsletter body number {i} about elections\n"
            ).encode()
        )
    return SimpleNamespace(folder=folder, Session=Session, tmp=tmp_path)


def _mgr(tmp_path) -> NewsletterImportManager:
    return NewsletterImportManager(state_path=tmp_path / "import_state.json")


def _wait(mgr: NewsletterImportManager, seconds: float = 10.0) -> None:
    if mgr._thread is not None:
        mgr._thread.join(seconds)
        assert not mgr._thread.is_alive(), "the import thread must have ended"


def test_a_folder_import_that_finishes_is_an_ok_import_via_newsletter_eml(journal, nl):
    mgr = _mgr(nl.tmp)
    mgr.start(str(nl.folder), _session_factory=nl.Session)
    _wait(mgr)
    assert mgr.status()["state"] == "done"
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["open"]) == ("newsletter-eml", "ok", False)
    assert (event["files"], event["files_done"], event["resumed_from"]) == (5, 5, 0)
    assert isinstance(event["data_free_bytes"], int)
    _nothing_secret_anywhere(journal, MARKER, str(nl.folder))


def test_a_resumed_import_says_where_it_resumed_from(journal, nl):
    mgr = _mgr(nl.tmp)
    mgr.start(str(nl.folder), _session_factory=nl.Session, _cursor=3)
    _wait(mgr)
    event = _only("run_import")
    assert (event["resumed_from"], event["files"], event["files_done"], event["outcome"]) == (3, 5, 5, "ok")


def test_the_import_is_written_open_while_it_runs(journal, nl, monkeypatch):
    seen: list[dict] = []
    real = import_job.ingest_emails

    def watching(session, source, raws):
        seen.append(dict(_events("run_import")[-1]))
        return real(session, source, raws)

    monkeypatch.setattr(import_job, "ingest_emails", watching)
    mgr = _mgr(nl.tmp)
    mgr.start(str(nl.folder), _session_factory=nl.Session)
    _wait(mgr)
    assert seen and seen[0]["open"] is True and seen[0]["via"] == "newsletter-eml" and "outcome" not in seen[0]
    assert "data_free_bytes" in seen[0]


@pytest.mark.parametrize(("action", "outcome"), [("pause", "paused"), ("cancel", "cancelled")])
def test_a_paused_import_and_a_cancelled_one_are_two_different_outcomes(journal, nl, monkeypatch, action, outcome):
    mgr = _mgr(nl.tmp)
    real = import_job.ingest_emails

    def stopping(session, source, raws):
        getattr(mgr, action)()
        return real(session, source, raws)

    monkeypatch.setattr(import_job, "ingest_emails", stopping)
    mgr.start(str(nl.folder), _session_factory=nl.Session)
    _wait(mgr)
    event = _only("run_import")
    assert (event["via"], event["outcome"]) == ("newsletter-eml", outcome)
    assert event["files_done"] == 5


def test_an_import_that_fails_leaves_the_class_and_none_of_the_words(journal, nl, monkeypatch):
    def failing(session, source, raws):
        raise ValueError(f"{MARKER} could not parse {nl.folder}")

    monkeypatch.setattr(import_job, "ingest_emails", failing)
    mgr = _mgr(nl.tmp)
    mgr.start(str(nl.folder), _session_factory=nl.Session)
    _wait(mgr)
    assert mgr.status()["state"] == "error"
    event = _only("run_import")
    assert (event["via"], event["outcome"], event["error"], event["open"]) == ("newsletter-eml", "error", "ValueError", False)
    _nothing_secret_anywhere(journal, MARKER, str(nl.folder), "could not parse")


def test_a_folder_that_is_not_a_folder_is_a_refusal_with_its_sentence(journal, tmp_path):
    mgr = _mgr(tmp_path)
    with pytest.raises(ValueError):
        mgr.start(str(tmp_path / f"missing-{MARKER}"))
    event = _only("run_import")
    assert (event["outcome"], event["ran"], event["via"]) == ("refused", False, "newsletter-eml")
    assert event["reason"] == se.RUN_REFUSALS["not-a-folder"]
    _nothing_secret_anywhere(journal, MARKER, str(tmp_path))


def test_a_start_while_an_import_runs_is_a_refusal_and_the_run_in_flight_still_ends_ok(journal, nl, monkeypatch):
    hold, entered = threading.Event(), threading.Event()
    real = import_job.ingest_emails

    def slow(session, source, raws):
        entered.set()
        assert hold.wait(10)
        return real(session, source, raws)

    monkeypatch.setattr(import_job, "ingest_emails", slow)
    mgr = _mgr(nl.tmp)
    mgr.start(str(nl.folder), _session_factory=nl.Session)
    assert entered.wait(10)
    with pytest.raises(RuntimeError):
        mgr.start(str(nl.folder), _session_factory=nl.Session)
    hold.set()
    _wait(mgr)
    refused = [e for e in _events("run_import") if e["outcome"] == "refused"]
    assert len(refused) == 1 and refused[0]["reason"] == se.RUN_REFUSALS["import-running"] and refused[0]["via"] == "newsletter-eml"
    assert [e["outcome"] for e in _events("run_import")].count("ok") == 1


# --------------------------------------------------------------------------- #
#  4. The volume restore says so too
# --------------------------------------------------------------------------- #
def test_the_volume_restore_is_recorded_via_volume_set(journal, tmp_path):
    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw", _restore_fn=lambda src, pw: {"articles_merged": 1})
    assert _finish(mgr)["state"] == "done"
    event = _only("run_import")
    assert (event["via"], event["outcome"]) == ("volume-set", "ok")


def test_a_refused_volume_start_says_volume_set_whichever_kind_asked(journal, tmp_path):
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_restore(str(tmp_path / "missing"), "pw")
    assert _only("run_import")["via"] == "volume-set"
    with pytest.raises(ValueError):
        mgr.start_backup(str(tmp_path), "")
    assert _only("run_export")["via"] == "volume-set", "a backup says it too: the folder backup shares the kind"
    with pytest.raises(ValueError):
        mgr.start_verify(str(tmp_path / "missing"), "pw")
    assert _only("run_verify")["via"] == "volume-set"


def test_a_volume_backup_and_verify_that_run_say_volume_set_too(journal, tmp_path):
    from tests.test_storage_events_runs import _ok_backup

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "dest"), "pw", verify_after_write=False, _backup_fn=_ok_backup)
    assert _finish(mgr)["state"] == "done"
    assert _only("run_export")["via"] == "volume-set"
    mgr.start_verify(str(tmp_path), None, _verify_fn=lambda src, pw: {"ok": True})
    assert _finish(mgr)["state"] == "done"
    assert _only("run_verify")["via"] == "volume-set"


# --------------------------------------------------------------------------- #
#  5. The sources
# --------------------------------------------------------------------------- #
def _function(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    (fn,) = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name]
    return fn


def _is_record(stmt: ast.stmt, names: set[str]) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and stmt.value.func.attr in names
    )


def _each_raise_follows_a_record(fn: ast.FunctionDef, names: set[str]) -> int:
    """Every ``raise`` is preceded, in the SAME block, by a call that records the run's end or refusal; returns how many raises there were."""
    raises = 0
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if isinstance(stmt, ast.Raise):
                    raises += 1
                    recorded = any(_is_record(earlier, names) for earlier in block[:i]) or raise_is_recorded_by_a_wrapper(fn, stmt)
                    assert recorded, f"{fn.name}:{stmt.lineno}: a raise with no record before it"
    return raises


def _has_the_finally_net(fn: ast.FunctionDef) -> bool:
    return any(
        isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "run_ended"
        and len(c.args) == 2
        and isinstance(c.args[1], ast.Constant)
        and c.args[1].value == "ended-without-a-recorded-outcome"
        for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        for stmt in t.finalbody
        for c in ast.walk(stmt)
    )


def test_the_legacy_restore_and_the_import_worker_close_their_run_in_a_finally_net():
    assert _has_the_finally_net(_function("src/api/backup_v2.py", "restore_legacy_path"))
    assert _has_the_finally_net(_function("src/ingest/import_job.py", "_run"))


def test_every_raise_of_the_two_starts_follows_a_record():
    assert _each_raise_follows_a_record(_function("src/ingest/import_job.py", "start"), {"run_refused"}) == 2
    assert _each_raise_follows_a_record(_function("src/api/backup_v2.py", "restore_legacy_path"), {"run_refused", "run_ended"}) >= 6


def test_the_new_hooks_are_called_through_the_modules_journal_and_hand_over_no_text():
    assert backup_v2.storage_events is se and import_job.storage_events is se
    for rel in ("src/api/backup_v2.py", "src/ingest/import_job.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"run_started", "run_ended", "run_refused", "run_free_space", "run_facts"}):
            for kw in call.keywords:
                assert kw.arg in {"failure", "reason", "via", "articles_merged", "reindexed", "files", "files_done", "resumed_from"}, f"{rel}:{call.lineno}: {kw.arg}"


# --------------------------------------------------------------------------- #
#  6. A start that cannot even look at its path (the Opus read, L1)
# --------------------------------------------------------------------------- #
from tests.test_storage_events_runs import _unreadable  # noqa: E402


def test_a_legacy_restore_whose_path_the_system_cannot_examine_is_a_refusal_and_still_raises_the_oserror(journal, tmp_path, monkeypatch):
    _unreadable(monkeypatch, "is_file")
    with pytest.raises(OSError) as caught:
        backup_v2.restore_legacy_path(str(tmp_path / f"UNREADABLE-{MARKER}"), PASS)
    assert not isinstance(caught.value, HTTPException), "the error is the one it was before the record existed"
    event = _only("run_import")
    assert (event["outcome"], event["ran"], event["via"], event["error"]) == ("refused", False, "single-file", "OSError")
    assert event["reason"] == se.RUN_REFUSALS["path-unreadable"]
    _nothing_secret_anywhere(journal, PASS, MARKER, "UNREADABLE", str(tmp_path))


def test_a_newsletter_import_whose_folder_the_system_cannot_examine_is_a_refusal_and_so_is_one_it_cannot_list(journal, tmp_path, monkeypatch):
    mgr = _mgr(tmp_path)
    with monkeypatch.context() as unreadable:  # not ``monkeypatch.undo()``: that would also undo the journal fixture's patches
        _unreadable(unreadable, "is_dir")
        with pytest.raises(OSError):
            mgr.start(str(tmp_path / f"UNREADABLE-{MARKER}"))
    event = _only("run_import")
    assert (event["outcome"], event["ran"], event["via"], event["error"]) == ("refused", False, "newsletter-eml", "OSError")
    assert event["reason"] == se.RUN_REFUSALS["path-unreadable"]

    folder = tmp_path / "inbox"
    folder.mkdir()
    monkeypatch.setattr(import_job, "_eml_files", lambda p: (_ for _ in ()).throw(PermissionError(f"{MARKER} {p}")))
    with pytest.raises(PermissionError):
        _mgr(tmp_path).start(str(folder))
    last = _events("run_import")[-1]
    assert (last["outcome"], last["via"], last["error"]) == ("refused", "newsletter-eml", "PermissionError")
    assert last["reason"] == se.RUN_REFUSALS["path-unreadable"]
    _nothing_secret_anywhere(journal, MARKER, "UNREADABLE", str(tmp_path))


def test_a_volume_start_whose_folder_the_system_cannot_examine_is_a_refusal_of_the_kind_that_asked(journal, tmp_path, monkeypatch):
    mgr = VolumeBackupManager()
    _unreadable(monkeypatch, "is_dir")
    bad = str(tmp_path / f"UNREADABLE-{MARKER}")
    for kind, start in (
        ("run_import", lambda: mgr.start_restore(bad, "pw")),
        ("run_verify", lambda: mgr.start_verify(bad, "pw")),
    ):
        with pytest.raises(OSError):
            start()
        event = _only(kind)
        assert (event["outcome"], event["via"], event["error"]) == ("refused", "volume-set", "OSError"), kind
        assert event["reason"] == se.RUN_REFUSALS["path-unreadable"]
    # a backup makes its folder first, so the stat that fails is the one after it
    with pytest.raises(OSError):
        mgr.start_backup(bad, "pw")
    event = _only("run_export")
    assert (event["outcome"], event["via"]) == ("refused", "volume-set")
    _nothing_secret_anywhere(journal, MARKER, "UNREADABLE", str(tmp_path))


def test_the_legacy_restore_names_a_stop_and_a_merge_refusal_differently_from_the_run_journal_and_says_so(journal, legacy, monkeypatch):
    """The Opus read, L4: the storage record sees the failure before the run journal does, and the member says where that differs."""
    from src.backup import runlog

    ended: list[tuple] = []
    real_end = runlog.end
    monkeypatch.setattr(runlog, "end", lambda outcome, **k: ended.append((outcome, k.get("cls"))) or real_end(outcome, **k))
    for raises, here, there in ((MergeError, "refused", "error"), (RestoreAborted, "stopped-by-operator", "error")):
        monkeypatch.setattr(backup_v2, "run_restore", lambda *a, _r=raises, **k: (_ for _ in ()).throw(_r("stop")))
        ended.clear()
        with pytest.raises(HTTPException):
            backup_v2.restore_legacy_path(str(legacy), PASS)
        assert _events("run_import")[-1]["outcome"] == here
        assert ended and ended[0][0] == there, "the run journal records the same failure as an error (its first end; the net after it is a no-op)"
    for fragment in ("merge check", "stopped-by-operator", "'error' there"):
        assert fragment in se._METHOD, fragment

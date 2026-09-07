"""The import CHECKPOINT INTERVAL K — one verify + snapshot + swap per K backups.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-08-08 queue entry's item (b). An eighteen-backup import today pays, PER
ITEM, a full working-copy snapshot of the corpus, a whole-file ``quick_check`` +
``foreign_key_check`` over it, and an atomic swap. K > 1 carries one working copy
across K consecutive backups and pays those once.

WHAT THESE TESTS ARE ABOUT, in order of how much they matter:

1. **The default changes nothing.** K is a DURABILITY choice and the ledger records
   it as needing a maintainer ruling, so the shipped default is 1 and the whole
   mechanism must be unreachable there. Several tests exist only to say so.
2. **A held item never touches the live corpus.** That is the property the whole
   design rests on, and it is asserted against the REAL engine through the torture
   helper's subprocess — a byte comparison of the live database file, not a claim
   about which branch ran.
3. **Everything that can go wrong discards the group.** A failure, a refusal, a
   Stop and a process restart each have their own test, because each reaches the
   discard by a different route and "the items are reported as imported" is the one
   answer none of them may give.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.backup import import_queue as iq
from src.backup.import_queue import (
    CHECKPOINT_K_DEFAULT,
    CHECKPOINT_K_MAX,
    ImportQueueManager,
    import_checkpoint_k,
)

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"


# --------------------------------------------------------------------------- #
#  1. The default is one, and at one nothing below it exists
# --------------------------------------------------------------------------- #
def test_the_shipped_default_is_one_backup_per_checkpoint(monkeypatch, tmp_path):
    """K = 1 is today's behaviour: every backup written to the corpus as it finishes.

    The recommendation on record is 3 and the choice is the maintainer's; shipping
    3 as the default would make a durability trade nobody ruled on, for everyone.
    """
    monkeypatch.delenv("OO_IMPORT_CHECKPOINT_K", raising=False)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    assert CHECKPOINT_K_DEFAULT == 1
    assert import_checkpoint_k() == 1


def test_the_env_override_wins_and_a_nonsense_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("OO_IMPORT_CHECKPOINT_K", "3")
    assert import_checkpoint_k() == 3
    for bad in ("0", "-2", "not-a-number", str(CHECKPOINT_K_MAX + 1), ""):
        monkeypatch.setenv("OO_IMPORT_CHECKPOINT_K", bad)
        if bad == "":
            continue  # empty falls through to the stored setting, covered below
        assert import_checkpoint_k() == CHECKPOINT_K_DEFAULT, bad


def test_the_stored_setting_is_read_when_no_env_override_is_set(monkeypatch, tmp_path):
    monkeypatch.delenv("OO_IMPORT_CHECKPOINT_K", raising=False)
    import src.config.app_settings as app_settings

    monkeypatch.setattr(app_settings, "_settings_path", lambda: tmp_path / "app_settings.json")
    monkeypatch.setattr(app_settings, "_kv_enabled", lambda: False, raising=False)
    app_settings.save_settings({"import_checkpoint_k": 4})
    assert import_checkpoint_k() == 4


def test_the_two_ceilings_are_the_same_number():
    """``app_settings`` carries the ceiling as a literal so the settings path never
    imports the merge stack. A copy that could drift is worse than an import, so
    the copy is pinned here instead."""
    from src.config.app_settings import _CHECKPOINT_K_MAX

    assert _CHECKPOINT_K_MAX == CHECKPOINT_K_MAX


def test_the_setting_refuses_a_value_outside_the_range_rather_than_clamping(monkeypatch, tmp_path):
    """Silently turning a 30 into a 24 would hand the operator a durability window
    they did not choose while telling them nothing."""
    import src.config.app_settings as app_settings
    from src.config.app_settings import AppSettingsError

    monkeypatch.setattr(app_settings, "_settings_path", lambda: tmp_path / "app_settings.json")
    monkeypatch.setattr(app_settings, "_kv_enabled", lambda: False, raising=False)
    for bad in (0, -1, CHECKPOINT_K_MAX + 1, "three", True):
        with pytest.raises(AppSettingsError):
            app_settings.save_settings({"import_checkpoint_k": bad})
    # ...and the whole legal range is accepted, so the refusal is about the bound
    # and not about the field being unwritable.
    for good in (1, 3, CHECKPOINT_K_MAX):
        assert app_settings.save_settings({"import_checkpoint_k": good}).import_checkpoint_k == good


def _queue(tmp_path, items, k):
    q = ImportQueueManager(state_path=tmp_path / "queue.json")
    q._items = [
        {"id": f"{i}-{it['kind']}", "kind": it["kind"], "path": it.get("path", f"/a/{i}"),
         "label": it.get("label", f"item{i}"), "state": "queued", "started_at": None,
         "ended_at": None, "error": None, "summary": None, "force": it.get("force", False)}
        for i, it in enumerate(items)
    ]
    q._checkpoint_k = k
    return q


def test_at_k_one_no_item_is_ever_held(tmp_path):
    """The load-bearing default guard. Every other test in this file describes
    behaviour that must be unreachable on the shipped configuration."""
    q = _queue(tmp_path, [{"kind": "corpus"}] * 5, k=1)
    assert [q._decide_hold(i, it) for i, it in enumerate(q._items)] == [False] * 5
    assert q._group is None


def test_at_k_one_the_queue_passes_no_working_copy_and_opens_no_group(tmp_path, monkeypatch):
    """Byte-identity of the default path, asserted at the seam rather than inferred:
    the arguments the queue hands the restore manager are exactly the ones it handed
    before the checkpoint existed."""
    seen: list[dict] = []

    class _Mgr:
        def start_restore(self, path, passphrase, **kw):
            seen.append(kw)

        def status(self):
            return {"state": "done", "summary": {"report": {"committed": True}}}

        def cancel(self):
            pass

    monkeypatch.setattr("src.backup.volume_job.get_volume_manager", lambda: _Mgr())
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    q = _queue(tmp_path, [{"kind": "corpus"}, {"kind": "corpus"}], k=1)
    for i, it in enumerate(q._items):
        q._run_corpus(it, hold=q._decide_hold(i, it))
    assert [kw["working_copy"] for kw in seen] == [None, None]
    assert [kw["hold_after_merge"] for kw in seen] == [False, False]
    assert not list(tmp_path.glob(".restore-group-*")), "no group directory at K = 1"


# --------------------------------------------------------------------------- #
#  2. The hold decision
# --------------------------------------------------------------------------- #
def _no_lookahead(monkeypatch, answer=True):
    monkeypatch.setattr(ImportQueueManager, "_another_item_will_merge", lambda self, idx: answer)


def test_the_k_th_item_of_a_group_commits_it(tmp_path, monkeypatch):
    _no_lookahead(monkeypatch)
    q = _queue(tmp_path, [{"kind": "corpus"}] * 5, k=3)
    assert q._decide_hold(0, q._items[0]) is True
    q._group = iq._CheckpointGroup(dir=tmp_path / "g")
    q._group.item_ids.append("0-corpus")
    assert q._decide_hold(1, q._items[1]) is True
    q._group.item_ids.append("1-corpus")
    # The third item of a K = 3 group is the one that swaps.
    assert q._decide_hold(2, q._items[2]) is False


def test_a_non_corpus_item_neither_holds_nor_lets_the_item_before_it_hold(tmp_path):
    """A newsletter import reads the LIVE corpus to screen its .eml articles against
    it, so a group must be committed before one runs — not merely 'eventually'."""
    q = _queue(tmp_path, [{"kind": "corpus"}, {"kind": "newsletters"}, {"kind": "corpus"}], k=5)
    assert q._decide_hold(0, q._items[0]) is False
    assert q._decide_hold(1, q._items[1]) is False


def test_an_item_whose_successors_are_all_already_merged_never_holds(tmp_path, monkeypatch):
    """THE STRANDED-GROUP CASE. An artifact this corpus already carries is answered
    from one small JSON read and never opens a working copy — so if every remaining
    corpus item is a repeat, holding this one would leave the group with nothing
    left to commit it and the merge would be thrown away at the end of the run."""
    monkeypatch.setattr("src.backup.merge.artifact_source_digest", lambda p: f"digest-{p}")
    monkeypatch.setattr("src.backup.merge.find_completed_import", lambda d: {"batch_id": 7})
    q = _queue(tmp_path, [{"kind": "corpus"}] * 3, k=3)
    assert q._decide_hold(0, q._items[0]) is False


def test_an_item_with_a_mergeable_successor_does_hold(tmp_path, monkeypatch):
    """The negative-space twin of the test above: a lookahead that answered 'no'
    unconditionally would satisfy it while disabling the feature entirely."""
    monkeypatch.setattr("src.backup.merge.artifact_source_digest", lambda p: f"digest-{p}")
    monkeypatch.setattr("src.backup.merge.find_completed_import", lambda d: None)
    q = _queue(tmp_path, [{"kind": "corpus"}] * 3, k=3)
    assert q._decide_hold(0, q._items[0]) is True


def test_an_unreadable_digest_reads_as_will_merge(tmp_path, monkeypatch):
    """Same direction as the skip itself: an artifact whose digest cannot be read
    never matches the already-merged check either, so it WILL merge. The two answers
    have to agree or the lookahead predicts something the item then does not do."""
    monkeypatch.setattr("src.backup.merge.artifact_source_digest", lambda p: None)
    monkeypatch.setattr("src.backup.merge.find_completed_import", lambda d: {"batch_id": 1})
    q = _queue(tmp_path, [{"kind": "corpus"}] * 3, k=3)
    assert q._decide_hold(0, q._items[0]) is True


def test_an_artifact_already_in_the_open_group_does_not_count_as_a_successor(
    tmp_path, monkeypatch
):
    """The group's own digests answer the question the live corpus cannot yet: a
    repeat of something already merged INTO the working copy will be skipped, so it
    is not a successor that can commit the group."""
    monkeypatch.setattr("src.backup.merge.artifact_source_digest", lambda p: "same")
    monkeypatch.setattr("src.backup.merge.find_completed_import", lambda d: None)
    q = _queue(tmp_path, [{"kind": "corpus"}] * 3, k=3)
    q._group = iq._CheckpointGroup(dir=tmp_path / "g", digests={"same"})
    assert q._decide_hold(0, q._items[0]) is False


# --------------------------------------------------------------------------- #
#  3. The group's lifecycle: everything that can go wrong discards it
# --------------------------------------------------------------------------- #
def _with_open_group(tmp_path, n_staged=2):
    q = _queue(tmp_path, [{"kind": "corpus"}] * 3, k=3)
    gdir = tmp_path / ".restore-group-test"
    gdir.mkdir()
    (gdir / "working.db").write_bytes(b"not really a database")
    q._group = iq._CheckpointGroup(dir=gdir)
    for i in range(n_staged):
        q._items[i]["state"] = "staged"
        q._group.item_ids.append(q._items[i]["id"])
    return q, gdir


def test_a_committed_item_turns_every_staged_item_of_its_group_into_an_import(tmp_path):
    q, gdir = _with_open_group(tmp_path)
    q._after_item(q._items[2], {"held": False, "report": {"committed": True}})
    assert [it["state"] for it in q._items[:2]] == ["done", "done"]
    assert q._group is None
    assert not gdir.exists(), "the swap consumed the working copy; the directory goes"


def test_a_failing_item_discards_the_group_and_names_what_went_with_it(tmp_path):
    """A windowed merge step COMMITS mid-merge, so a failure can leave a half-merged
    artifact in the shared copy — and a half-merged copy must never become the live
    corpus. Discarding costs the group's other merges: that is the durability half
    of K, and it is reported rather than left to be noticed."""
    q, gdir = _with_open_group(tmp_path)
    q._discard_group("the import of item2 failed")
    assert [it["state"] for it in q._items[:2]] == ["discarded", "discarded"]
    for it in q._items[:2]:
        assert "failed" in it["discarded_reason"]
    assert q._group is None and not gdir.exists()


def test_a_refused_verification_discards_the_group_rather_than_carrying_it_on(tmp_path):
    q, gdir = _with_open_group(tmp_path)
    q._after_item(
        q._items[2], {"held": False, "report": {"committed": False, "refused": "verification"}}
    )
    assert [it["state"] for it in q._items[:2]] == ["discarded", "discarded"]
    assert not gdir.exists()


def test_a_skipped_already_merged_item_leaves_the_group_exactly_as_it_was(tmp_path):
    """A skip merges nothing, so it neither commits the group nor taints it — the
    two failure directions this must not fall into."""
    q, gdir = _with_open_group(tmp_path)
    q._after_item(q._items[2], {"held": False, "report": {}})
    assert [it["state"] for it in q._items[:2]] == ["staged", "staged"]
    assert q._group is not None and gdir.exists()


def test_a_process_restart_reports_staged_items_as_discarded_never_as_imported(tmp_path):
    """The working copy does not survive the process, so on the next boot a staged
    item did not import. Leaving it 'staged' would show work in flight forever;
    calling it 'done' would claim an import that never reached the corpus."""
    state = tmp_path / "queue.json"
    state.write_text(json.dumps({
        "state": "done",
        "items": [
            {"id": "0-corpus", "kind": "corpus", "path": "/a", "label": "one", "state": "staged"},
            {"id": "1-corpus", "kind": "corpus", "path": "/b", "label": "two", "state": "done"},
        ],
        "cursor": -1, "started_at": 1.0, "ended_at": 2.0,
    }), encoding="utf-8")
    q = ImportQueueManager(state_path=state)
    assert [it["state"] for it in q._items] == ["discarded", "done"]
    assert "did not survive" in q._items[0]["discarded_reason"]


def test_status_reports_committed_and_staged_as_two_different_numbers(tmp_path):
    q, _ = _with_open_group(tmp_path)
    q._items[2]["state"] = "done"
    st = q.status()
    assert st["items_staged"] == 2
    assert st["items_committed"] == 1
    # The queue really has walked past all three, and that is a different fact from
    # what reached the corpus -- so the bar's numerator and the durability count are
    # allowed to disagree, and both are published.
    assert st["items_done"] == 3
    assert st["checkpoint"]["k"] == 3
    assert st["checkpoint"]["open_group_items"] == 2
    assert "discards" in st["checkpoint"]["note"]


def test_at_k_one_the_checkpoint_note_promises_nothing_about_losing_work(tmp_path):
    q = _queue(tmp_path, [{"kind": "corpus"}], k=1)
    st = q.status()
    assert st["items_staged"] == 0
    assert st["checkpoint"]["k"] == 1
    assert "discards" not in st["checkpoint"]["note"]
    assert "as soon as it finishes" in st["checkpoint"]["note"]


# --------------------------------------------------------------------------- #
#  4. The real engine: what a held restore does and does not do
# --------------------------------------------------------------------------- #
def _helper(data_dir: Path, *args: str) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=300,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _live_digest(data_dir: Path) -> str:
    return hashlib.sha256((data_dir / "open_omniscience.db").read_bytes()).hexdigest()


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_a_held_restore_leaves_the_live_corpus_byte_identical(tmp_path):
    """THE PROPERTY THE WHOLE DESIGN RESTS ON, asserted as bytes rather than as a
    claim about which branch ran: a held item merges into the carried working copy
    and the live database file is not touched at all."""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-k").get("artifact")
    _helper(a, "build", "A")

    before = _live_digest(a)
    group = tmp_path / "group"
    group.mkdir()
    working = group / "working.db"
    rep = _helper(
        a, "merge", str(art), "--passphrase", "pw-k", "--commit",
        "--working-copy", str(working), "--hold",
    )["report"]

    assert rep["held"] is True
    assert rep["committed"] is False
    assert _live_digest(a) == before, "a held item must not write to the live corpus"
    assert working.exists(), "the working copy is left for the checkpoint to carry"
    # The merge really happened -- into the copy. Without this the test would pass
    # against a hold that simply did nothing.
    assert rep["plan"]["articles"]["new"] >= 1
    assert rep["verification"]["merge_ok"] is True
    assert "file_checks_deferred" in rep["verification"]
    assert "quick_check" not in rep["verification"], (
        "the whole-file walk belongs to the checkpoint, not to every item"
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_a_checkpoint_commits_every_merge_the_group_carries(tmp_path):
    """Two artifacts, one working copy, ONE swap — and both artifacts' unique
    articles are in the corpus afterwards. A group that committed only the last
    item's merge would pass every per-item assertion and lose the rest."""
    a = tmp_path / "A"
    a.mkdir()
    arts = []
    for tag in ("P", "Q"):
        d = tmp_path / f"src{tag}"
        d.mkdir()
        art = tmp_path / f"corpus{tag}.oobak.ooenc"
        assert _helper(
            d, "build", "B", "--tag", tag, "--artifact", str(art), "--passphrase", "pw-k"
        ).get("artifact")
        arts.append(art)
    _helper(a, "build", "A")

    group = tmp_path / "group"
    group.mkdir()
    working = group / "working.db"

    held = _helper(
        a, "merge", str(arts[0]), "--passphrase", "pw-k", "--commit",
        "--working-copy", str(working), "--hold",
    )["report"]
    assert held["held"] is True
    committed = _helper(
        a, "merge", str(arts[1]), "--passphrase", "pw-k", "--commit",
        "--working-copy", str(working),
    )["report"]
    assert committed["committed"] is True
    assert committed.get("held") is None

    # BOTH artifacts' unique articles are in the corpus. `unique-to-P` came from the
    # HELD merge, so this is the assertion that a group commits everything it carries.
    for tag in ("P", "Q"):
        # Quoted as a PHRASE: FTS5 splits `unique-to-P` on the hyphen and reads the
        # bare `to` as a column name, which fails with a message about columns and
        # nothing about the corpus.
        found = _helper(a, "fts-find", f'"unique-to-{tag}"')["matches"]
        assert found >= 1, f"the {tag} merge did not reach the corpus"


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_carrying_a_working_copy_skips_the_whole_corpus_snapshot(tmp_path):
    """The saving itself, measured rather than asserted: the second item of a group
    records a ``snapshot_working_copy`` stage that copied nothing, while the first
    one really copied the corpus. A carry that silently re-snapshotted would keep
    every other test in this file green and buy nothing."""
    a = tmp_path / "A"
    a.mkdir()
    arts = []
    for tag in ("P", "Q"):
        d = tmp_path / f"src{tag}"
        d.mkdir()
        art = tmp_path / f"corpus{tag}.oobak.ooenc"
        _helper(d, "build", "B", "--tag", tag, "--artifact", str(art), "--passphrase", "pw-k")
        arts.append(art)
    _helper(a, "build", "A")

    group = tmp_path / "group"
    group.mkdir()
    working = group / "working.db"
    live_before = _live_digest(a)
    for art in arts:
        rep = _helper(
            a, "merge", str(art), "--passphrase", "pw-k", "--commit",
            "--working-copy", str(working), "--hold",
        )["report"]
        assert rep["held"] is True

    # THE DISCRIMINATOR IS THE CONTENT, NOT THE CLOCK. A first draft asserted that
    # the second item's `snapshot_working_copy` stage was FASTER than the first's,
    # and the mutation that re-snapshots unconditionally SURVIVED it: on a fixture
    # this small both numbers are noise, and the recorded lesson is that a probe's
    # scale is part of the lookalike. What a re-snapshot really does is throw the
    # first merge away and start again from the live corpus -- so the exact,
    # load-independent question is how many merges the carried copy holds.
    con = sqlite3.connect(f"file:{working}?mode=ro", uri=True)
    try:
        batches = con.execute("SELECT COUNT(*) FROM merge_batches").fetchone()[0]
        bodies = con.execute(
            "SELECT COUNT(*) FROM articles WHERE content LIKE 'unique-to-%'"
        ).fetchone()[0]
    finally:
        con.close()
    assert batches == 2, f"the carried copy holds {batches} merge(s), not both"
    assert bodies >= 2, "both artifacts' unique articles must be in the carried copy"
    # ...and the live corpus has still never been written to, which is what makes
    # the two merges above a GROUP rather than two imports that happen to share a
    # path. Bytes, so it cannot be satisfied by a snapshot that copied it back.
    assert _live_digest(a) == live_before


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_a_held_item_still_merges_its_side_files(tmp_path):
    """Side files merge into the data dir, not into the corpus, and the item's
    staging tree is gone by the time a checkpoint runs — so deferring them would
    drop them. They run for a held item too, and this is what says so."""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-k")
    _helper(a, "build", "A")

    rep = _helper(
        a, "merge", str(art), "--passphrase", "pw-k", "--commit",
        "--working-copy", str(tmp_path / "working.db"), "--hold",
    )["report"]
    assert "side_files" in rep, "a held item must still merge its side files"
    # The calendar feed store is the one side file the fixture makes differ between
    # A and B, so a merge that reached it really did something.
    merged = json.loads((a / "calendar_feed_imports.json").read_text("utf-8"))
    assert "fp-B" in json.dumps(merged), "B's own calendar entry did not arrive"


# --------------------------------------------------------------------------- #
#  5. The verification split
# --------------------------------------------------------------------------- #
def test_verify_copy_still_composes_both_halves():
    """The split must not change what a single-artifact restore checks. Asserted
    against the SOURCE of verify_copy rather than a fixture, because the claim is
    about which checks are in the conjunction — a fixture that passes proves only
    that the ones which ran were happy."""
    import inspect

    from src.backup.merge import verify_copy, verify_file, verify_merge

    body = inspect.getsource(verify_copy)
    assert "verify_file(" in body and "verify_merge(" in body
    assert 'v["ok"] = bool(v["file_ok"] and v["merge_ok"])' in body
    # ...and the two halves really do carry the checks they are named for, so the
    # conjunction above is not over two empty verdicts.
    file_body = inspect.getsource(verify_file)
    assert "PRAGMA quick_check" in file_body and "PRAGMA foreign_key_check" in file_body
    merge_body = inspect.getsource(verify_merge)
    assert "sampled_content_mismatches" in merge_body and "fts_trigger_present" in merge_body
    assert "quick_check" not in merge_body, (
        "the whole-file walk must live in exactly one of the two halves"
    )


# --------------------------------------------------------------------------- #
#  6. The two wirings a carried copy makes load-bearing
# --------------------------------------------------------------------------- #
def test_the_queue_hands_the_restore_the_digests_already_in_the_open_group(tmp_path, monkeypatch):
    """``find_completed_import`` reads the LIVE corpus, which does not yet contain a
    group's earlier merges — so without this the already-merged skip silently stops
    working the moment K > 1, for exactly the duplicate-artifact case the field log
    says is 8 of 18 imports."""
    seen: list[dict] = []

    class _Mgr:
        def start_restore(self, path, passphrase, **kw):
            seen.append(kw)

        def status(self):
            return {"state": "done", "summary": {"report": {}, "held": True, "source_digest": "d2"}}

        def cancel(self):
            pass

    monkeypatch.setattr("src.backup.volume_job.get_volume_manager", lambda: _Mgr())
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    q = _queue(tmp_path, [{"kind": "corpus"}] * 2, k=3)
    q._group = iq._CheckpointGroup(dir=tmp_path / "g", digests={"d1"})
    q._run_corpus(q._items[0], hold=True)
    assert seen[0]["already_merged_digests"] == frozenset({"d1"})
    assert seen[0]["working_copy"] == q._group.working


def test_a_digest_already_in_the_group_is_skipped_by_the_restore_manager(tmp_path, monkeypatch):
    """The other end of the same wiring, driven through the manager's real skip
    branch — and the skip SAYS which of the two questions answered it, because
    "already in your corpus" survives a kill and "already in this run's working
    copy" does not."""
    from src.backup.volume_job import VolumeBackupManager

    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.backup.merge.artifact_source_digest", lambda p: "d1")
    monkeypatch.setattr("src.backup.merge.find_completed_import", lambda d: None)
    src_dir = tmp_path / "artifact"
    src_dir.mkdir()

    mgr = VolumeBackupManager()
    mgr._run_restore(
        src_dir, "pw", False, None, None, already_merged_digests=frozenset({"d1"})
    )
    summary = mgr.status()["summary"]
    assert summary["skipped"] == "already-merged"
    assert summary["in_open_checkpoint_group"] is True

    # NEGATIVE-SPACE TWIN: a digest that is NOT in the group is not skipped, or the
    # "fix" would be a restore that never runs.
    mgr2 = VolumeBackupManager()
    mgr2._run_restore(
        src_dir, "pw", False, None, None, already_merged_digests=frozenset({"other"})
    )
    assert (mgr2.status()["summary"] or {}).get("skipped") != "already-merged"


def test_a_held_item_does_not_hand_off_a_reindex_backlog():
    """A held item's articles are in the working copy, not the live store, so a
    hand-off there reports the PREVIOUS state as this item's and starts a drain over
    articles that are not there.

    Asserted from the parse tree rather than as text: the comment above the call
    necessarily names ``held`` too, so a substring search is satisfied by the
    explanation of the rule instead of the rule.
    """
    import ast
    import inspect

    from src.backup import volume_job

    tree = ast.parse(inspect.getsource(volume_job))
    guards: list[ast.If] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = [
            c for c in ast.walk(node)
            if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "hand_off_reindex"
        ]
        if calls:
            guards.append(node)
    assert len(guards) == 1, f"expected exactly one guarded hand-off, found {len(guards)}"
    names = {n.id for n in ast.walk(guards[0].test) if isinstance(n, ast.Name)}
    consts = {
        c.value for c in ast.walk(guards[0].test)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    }
    assert "defer_reindex" in names or "defer_reindex" in consts
    assert "held" in consts, "the hand-off must be gated on the item not being held"


def test_a_fault_in_the_hold_decision_never_costs_the_import(tmp_path, monkeypatch):
    """The hold decision is a THROUGHPUT choice made outside the per-item try, so a
    fault in it would abort the whole run with the item still queued. It falls back
    to False — commit this item on its own, which is the behaviour at K = 1."""
    ran: list[str] = []

    def _boom(self, idx, item):
        raise RuntimeError("the lookahead exploded")

    monkeypatch.setattr(ImportQueueManager, "_decide_hold", _boom)
    monkeypatch.setattr(ImportQueueManager, "_tune_after_run", lambda self: None)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    q = _queue(tmp_path, [{"kind": "corpus"}] * 2, k=3)

    def _run(item, *, hold=False):
        ran.append(f"{item['id']}:{hold}")
        return {"report": {"committed": True}}

    monkeypatch.setattr(q, "_run_corpus", _run)
    q._drive()
    assert ran == ["0-corpus:False", "1-corpus:False"], ran
    assert [it["state"] for it in q._items] == ["done", "done"]

"""Row 97: a backup whose manifest the restore always refuses is refused when the run starts, not inside it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A manifest that lists a volume twice, points at a link or names an unsafe path can never import, whatever the
passphrase. Found inside a run, that backup fails there and the backups staged in its checkpoint group are discarded
with it. So the queue asks ``backup_manifest_refusal`` of every backup first and refuses the start, naming each such
backup and why. Pinned here: the three refusals, the sets it must never refuse (intact, missing volume, no manifest,
another kind), and that a refused start starts nothing and holds no key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.backup.stream_backup import STREAM_KIND, backup_manifest_refusal


def _set(folder: Path, names: list[str], members: list[list[str]] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        p = folder / n
        if not p.exists() and not p.is_symlink() and "/" not in n:
            p.write_bytes(b"x" * 64)
    m = {
        "kind": STREAM_KIND,
        "volumes": [{"name": n, "sha256": "0" * 64} for n in names],
        "members": [{"name": "corpus.db", "volumes": vs} for vs in (members or [list(dict.fromkeys(names))])],
    }
    (folder / "volumes.json").write_text(json.dumps(m), encoding="utf-8")
    return folder


def test_an_intact_set_is_not_refused(tmp_path):
    assert backup_manifest_refusal(_set(tmp_path / "ok", ["v0001.ooenc", "v0002.ooenc"])) is None


def test_a_volume_listed_twice_is_refused_by_name(tmp_path):
    reason = backup_manifest_refusal(_set(tmp_path / "dup", ["v0001.ooenc", "v0001.ooenc"]))
    assert reason and "more than once" in reason


def test_a_volume_listed_in_two_members_is_refused(tmp_path):
    reason = backup_manifest_refusal(_set(tmp_path / "two", ["v0001.ooenc"], members=[["v0001.ooenc"], ["v0001.ooenc"]]))
    assert reason and "more than once" in reason


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
def test_a_volume_that_is_a_link_is_refused(tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    folder = tmp_path / "link"
    folder.mkdir()
    (folder / "v0001.ooenc").symlink_to(outside)
    reason = backup_manifest_refusal(_set(folder, ["v0001.ooenc"]))
    assert reason and "link" in reason


def test_an_unsafe_volume_name_is_refused(tmp_path):
    reason = backup_manifest_refusal(_set(tmp_path / "unsafe", ["../v0001.ooenc"]))
    assert reason and "unsafe" in reason


def test_what_the_restore_may_still_read_gives_no_verdict(tmp_path):
    """A missing volume is parity's to recover; no manifest or another kind is the restore's to report."""
    missing = _set(tmp_path / "missing", ["v0001.ooenc", "v0002.ooenc"])
    (missing / "v0002.ooenc").unlink()
    assert backup_manifest_refusal(missing) is None
    assert backup_manifest_refusal(tmp_path / "nowhere") is None
    other = tmp_path / "other"
    other.mkdir()
    (other / "volumes.json").write_text(json.dumps({"kind": "oo-volumes-1", "volumes": [{"name": "a"}, {"name": "a"}]}), encoding="utf-8")
    assert backup_manifest_refusal(other) is None
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "volumes.json").write_text("{not json", encoding="utf-8")
    assert backup_manifest_refusal(junk) is None


def test_the_start_is_refused_naming_each_backup_and_nothing_runs(tmp_path, monkeypatch):
    import src.backup.stream_backup as SB
    from src.backup.import_queue import ImportQueueManager

    asked: list[str] = []
    monkeypatch.setattr(SB, "backup_passphrase_check", lambda p, k: asked.append(p) or ("none", None))
    good = _set(tmp_path / "good", ["v0001.ooenc"])
    bad = _set(tmp_path / "bad", ["v0001.ooenc", "v0001.ooenc"])
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    with pytest.raises(ValueError, match=r"cannot be imported: second \(.*more than once.*\)") as err:
        mgr.start(
            [{"kind": "corpus", "path": str(good)}, {"kind": "corpus", "path": str(bad), "label": "second",
                                                      "passphrase": "own words"}],
            passphrase="shared words",
        )
    assert "own words" not in str(err.value) and "shared words" not in str(err.value)
    assert "Nothing was started" in str(err.value)
    assert asked == []  # refused before any passphrase is tried
    assert mgr.status()["state"] == "idle" and mgr._secrets() == ()


def test_a_start_with_only_readable_backups_goes_on_to_the_passphrase_check(tmp_path, monkeypatch):
    import src.backup.stream_backup as SB
    from src.backup.import_queue import ImportQueueManager

    monkeypatch.setattr(SB, "backup_passphrase_check", lambda p, k: ("wrong", None))
    good = _set(tmp_path / "good", ["v0001.ooenc"])
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    with pytest.raises(ValueError, match="Wrong passphrase"):
        mgr.start([{"kind": "corpus", "path": str(good)}, {"kind": "legacy", "path": str(tmp_path / "x.zip")}],
                  passphrase="w")


def test_an_already_merged_backup_never_stops_the_start(tmp_path, monkeypatch):
    """The planner's ruling on the second read of #2061: the run skips an already-merged backup without reading it, so a
    manifest the checks of today would refuse (one merged by an older build) must not refuse a batch over a backup that is
    never read again. Only a backup still to be read can stop the start; ``force`` reads it again, so it is checked."""
    import src.backup.lane_merge as LM
    import src.backup.merge as MG
    import src.backup.stream_backup as SB
    from src.backup.import_queue import ImportQueueManager

    monkeypatch.setattr(SB, "backup_passphrase_check", lambda p, k: ("none", None))
    merged = _set(tmp_path / "merged", ["v0001.ooenc", "v0001.ooenc"])
    monkeypatch.setattr(MG, "artifact_source_digest", lambda p: "d" * 64 if Path(p) == merged else None)
    monkeypatch.setattr(MG, "find_completed_import", lambda d: {"batch_id": 7, "imported_at": "x"} if d else None)
    monkeypatch.setattr(LM, "lanes_pending", lambda d: False)
    assert ImportQueueManager._already_merged(str(merged)) is True
    started = []
    monkeypatch.setattr(ImportQueueManager, "_refuse_wrong_backup_passphrases", staticmethod(lambda items, p: started.append(1) or (_ for _ in ()).throw(RuntimeError("past the manifest check"))))
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    with pytest.raises(RuntimeError, match="past the manifest check"):
        mgr.start([{"kind": "corpus", "path": str(merged)}], passphrase="w")
    with pytest.raises(ValueError, match="cannot be imported"):
        mgr.start([{"kind": "corpus", "path": str(merged), "force": True}], passphrase="w")
    monkeypatch.setattr(LM, "lanes_pending", lambda d: True)  # its living sources are still owed: the run reads it again
    assert ImportQueueManager._already_merged(str(merged)) is False


def test_a_question_that_cannot_be_answered_is_not_already_merged(tmp_path, monkeypatch):
    import src.backup.merge as MG
    from src.backup.import_queue import ImportQueueManager

    monkeypatch.setattr(MG, "artifact_source_digest", lambda p: (_ for _ in ()).throw(OSError("unreadable")))
    assert ImportQueueManager._already_merged(str(tmp_path)) is False

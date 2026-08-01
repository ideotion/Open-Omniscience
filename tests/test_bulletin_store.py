"""
Persisted Bulletin editions, and their round trip through the encrypted backup.

The property that matters most here is the one the import-report path got wrong:
a member EXPORTED with no restore-side handler is carried by the artifact and
silently dropped on the floor. The manifest says it travelled; nothing says it
did not land. So these tests pin BOTH directions, and pin them for the import
reports too — the same loop now serves both.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.bulletin import store
from src.bulletin.period import resolve_period

_P = resolve_period("weekly", end=date(2026, 8, 1))  # covers through 2026-07-31


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    return tmp_path


# -- naming ----------------------------------------------------------------- #


def test_the_filename_is_the_period_it_covers_not_when_it_was_generated():
    """An edition IS its period. Naming it by generation time would file a Monday
    re-render of last week under Monday, and sort two re-runs of one week apart."""
    name = store.edition_filename(_P, edition_id="deadbeef")
    assert name == "20260731-OOS-weekly-deadbeef.json"


def test_two_runs_over_the_same_period_are_two_files():
    """A re-run is a new edition of the same period. Which one you kept is not a
    question the filename should answer by deleting the other."""
    a = store.persist_edition({"layer": "A"}, _P)
    b = store.persist_edition({"layer": "A"}, _P)
    assert a != b
    assert len(store.list_editions()) == 2


def test_the_cadence_travels_in_the_name():
    assert "-monthly-" in store.edition_filename(
        resolve_period("monthly", end=date(2026, 8, 1))
    )


# -- persistence ------------------------------------------------------------ #


def test_an_edition_round_trips_and_is_stamped_a_draft():
    """Automation reaches a DRAFT and stops — the operator is the byline."""
    p = store.persist_edition({"layer": "A", "masthead": {"articles": 7}}, _P)
    back = store.read_edition(p.name)
    assert back["masthead"]["articles"] == 7
    assert back["state"] == "draft"
    assert back["schema"] == "oo-bulletin-edition-1"
    assert back["filename"] == p.name and back["edition_id"]


def test_the_write_is_atomic_and_leaves_no_partial_behind():
    store.persist_edition({"layer": "A"}, _P)
    assert list(store.editions_dir().glob("*.oopart")) == []


def test_a_stale_partial_write_is_swept():
    """A temp file only its own `finally` can reclaim is an orphan the moment the
    process is killed rather than returning."""
    import os
    import time

    d = store.editions_dir()
    d.mkdir(parents=True, exist_ok=True)
    orphan = d / "old.json.oopart"
    orphan.write_text("half", encoding="utf-8")
    old = time.time() - (7 * 3600)
    os.utime(orphan, (old, old))
    store.persist_edition({"layer": "A"}, _P)
    assert not orphan.exists()


def test_a_fresh_install_lists_nothing_rather_than_erroring():
    assert store.list_editions() == []


def test_the_listing_carries_the_period_and_cadence():
    store.persist_edition({"layer": "A"}, _P)
    row = store.list_editions()[0]
    assert row["covers_through"] == "2026-07-31"
    assert row["cadence"] == "weekly"


def test_a_file_that_does_not_match_the_scheme_is_listed_with_the_mismatch_stated():
    """A hidden file in a directory the operator believes they can see is worse
    than an odd row."""
    d = store.editions_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "handwritten.json").write_text("{}", encoding="utf-8")
    row = next(r for r in store.list_editions() if r["filename"] == "handwritten.json")
    assert row["name_unrecognised"] is True


# -- the traversal guard ---------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    ["../../etc/passwd", "sub/dir.json", "..\\win.json", "", "..", "a/../../b.json"],
)
def test_a_traversal_attempting_name_is_refused_before_the_filesystem_is_touched(bad):
    assert store.safe_edition_path(bad) is None
    with pytest.raises(FileNotFoundError):
        store.read_edition(bad)
    assert store.delete_edition(bad) is False


def test_an_unknown_name_raises_rather_than_returning_another_files_contents():
    store.persist_edition({"layer": "A"}, _P)
    with pytest.raises(FileNotFoundError):
        store.read_edition("20260731-OOS-weekly-00000000.json")


def test_delete_removes_exactly_the_named_edition():
    keep = store.persist_edition({"layer": "A", "n": 1}, _P)
    drop = store.persist_edition({"layer": "A", "n": 2}, _P)
    assert store.delete_edition(drop.name) is True
    assert [r["filename"] for r in store.list_editions()] == [keep.name]


# -- the backup round trip -------------------------------------------------- #


def test_editions_are_collected_into_the_backup_artifact(tmp_path, monkeypatch):
    """Drives the REAL _collect_members. Only the DB-snapshot seam is stubbed —
    a helper that re-implemented the inventory would prove nothing about the
    function that actually builds a backup."""
    from src.backup import artifact

    monkeypatch.setattr("src.backup.sqlite_backup.live_db_path", lambda: tmp_path / "live.db")
    monkeypatch.setattr(
        artifact, "snapshot_sqlite", lambda _src, dest: Path(dest).write_bytes(b"")
    )
    store.persist_edition({"layer": "A"}, _P)

    out = tmp_path / "stage"
    out.mkdir()
    members = artifact._collect_members(False, out)
    rows = [m for m in members if m.role == "bulletin"]
    assert len(rows) == 1, "the edition did not reach the artifact"
    assert rows[0].name.startswith("bulletin/editions/")
    assert rows[0].name.endswith(".json")


def test_the_export_side_names_a_role_the_restore_side_actually_handles():
    """THE bug this pins: a member exported with no handler is carried and dropped.
    Read both sources rather than trusting that the wiring is symmetric."""
    art = Path("src/backup/artifact.py").read_text(encoding="utf-8")
    mrg = Path("src/backup/merge.py").read_text(encoding="utf-8")
    exported = {'"bulletin"', '"import_reports"'}
    for role in exported:
        assert role in art, f"{role} is not collected on the export side"
        assert role in mrg, f"{role} is exported with NO restore-side handler"


class _Staged:
    """The minimum of StagedArtifact that merge_side_files touches."""

    def __init__(self, members):
        self._m = members
        self.origin_fingerprint = "f" * 40
        self.signature_state = "verified"

    def member_paths(self, role):
        return list(self._m.get(role, []))


def test_a_restored_edition_lands_on_disk(tmp_path, monkeypatch):
    from src.backup import merge

    monkeypatch.setattr("src.backup.merge.data_dir", lambda: tmp_path)
    incoming = tmp_path / "incoming.json"
    incoming.write_text(json.dumps({"layer": "A", "from": "backup"}), encoding="utf-8")
    staged = _Staged(
        {"bulletin": [("bulletin/editions/20260731-OOS-weekly-abcdef01.json", incoming)]}
    )
    report = merge.merge_side_files(staged)
    landed = tmp_path / "bulletin/editions/20260731-OOS-weekly-abcdef01.json"
    assert landed.is_file()
    assert json.loads(landed.read_text(encoding="utf-8"))["from"] == "backup"
    assert report["documents"]["bulletin"]["restored"] == 1


def test_import_reports_now_restore_too(tmp_path, monkeypatch):
    """The recorded gap, closed by the same loop: they were exported and silently
    never restored."""
    from src.backup import merge

    monkeypatch.setattr("src.backup.merge.data_dir", lambda: tmp_path)
    incoming = tmp_path / "r.json"
    incoming.write_text('{"kind": "restore"}', encoding="utf-8")
    staged = _Staged({"import_reports": [("import_reports/restore-x-1.json", incoming)]})
    report = merge.merge_side_files(staged)
    assert (tmp_path / "import_reports/restore-x-1.json").is_file()
    assert report["documents"]["import_reports"]["restored"] == 1


def test_a_local_edition_is_never_overwritten_by_an_imported_one(tmp_path, monkeypatch):
    """An additive restore must not rewrite the user's own record to import history."""
    from src.backup import merge

    monkeypatch.setattr("src.backup.merge.data_dir", lambda: tmp_path)
    local = tmp_path / "bulletin/editions/20260731-OOS-weekly-abcdef01.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text('{"mine": true}', encoding="utf-8")
    incoming = tmp_path / "incoming.json"
    incoming.write_text('{"mine": false}', encoding="utf-8")
    staged = _Staged({"bulletin": [(str(local.relative_to(tmp_path)), incoming)]})
    report = merge.merge_side_files(staged)
    assert json.loads(local.read_text(encoding="utf-8"))["mine"] is True
    assert report["documents"]["bulletin"]["kept_local"] == 1


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/cron.d/evil.json",
        "/etc/passwd",
        "bulletin/editions/../../../../tmp/evil.json",
        "keys/signing.key",
    ],
)
def test_a_hostile_member_name_is_refused_and_written_nowhere(hostile, tmp_path, monkeypatch):
    """Member names become filesystem paths. Every name-to-path field runs through
    a guard, not only the ones that motivated the rule."""
    from src.backup import merge

    monkeypatch.setattr("src.backup.merge.data_dir", lambda: tmp_path)
    incoming = tmp_path / "payload.json"
    incoming.write_text('{"evil": true}', encoding="utf-8")
    staged = _Staged({"bulletin": [(hostile, incoming)]})
    report = merge.merge_side_files(staged)
    assert report["documents"]["bulletin"]["restored"] == 0
    assert report["documents"]["bulletin"]["refused"]
    assert not (tmp_path / "keys").exists()

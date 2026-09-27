"""The dated export folder, verify-after-write, and BACKUP_SUMMARY.md (S04-03, row J).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Data-safety slice, so the negative space carries the weight: an existing folder is
never written into, a corrupt set never reads "verified", a cancelled verification
never deletes a complete backup, and an unmeasured figure never renders as zero. The
positive path passes on its own.

Rulings: R4, R5; Q208 = a, Q209 = a, Q210 = a, Q211 = a, Q212 = c, Q213 = c, Q218 = a.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.backup.export_folder import (
    BACKUP_FOLDER_TOKEN,
    ExportFolderError,
    allocate_export_folder,
    folder_name,
    is_export_folder_name,
)
from src.backup.export_summary import (
    SUMMARY_NAME,
    export_facts,
    render_summary_markdown,
    write_backup_summary,
)
from src.backup.stream_backup import CorpusSource, MemberFile, _no_freeze, write_stream_backup
from src.backup.volumes import MANIFEST_NAME, VolumeStopped, verify_volume_set

_PASS = "a-test-passphrase"


# --------------------------------------------------------------------------- #
#  S1 — the dated folder (R5 amended by Q212; Q210, Q211, Q213)
# --------------------------------------------------------------------------- #
def test_the_folder_name_is_the_ruled_shape_with_the_token_spelled_out():
    when = datetime(2026, 9, 12, 10, 45)
    assert folder_name(when) == "202609121045_OpenOmniscience_Backup"
    # Q211 = a: an ordinal, not " (2)" and not added seconds.
    assert folder_name(when, ordinal=2) == "202609121045_OpenOmniscience_Backup_2"
    assert folder_name(when, ordinal=3).endswith("_Backup_3")
    # Q212 = c amended R5's literal token: "OOS" must not survive in the backup folder.
    assert BACKUP_FOLDER_TOKEN == "OpenOmniscience"
    assert "OOS" not in folder_name(when)
    assert is_export_folder_name(folder_name(when))
    assert not is_export_folder_name("202609121045_OOS_Backup")


def test_the_timestamp_is_the_operators_LOCAL_clock_not_utc(monkeypatch):
    """Q210 = a. A folder made at 10:45 on the operator's clock reads 10:45.

    Pinned against a fixed offset rather than the sandbox's own zone, so the test says
    something on a UTC runner: a UTC formatter would render 08:45 here.
    """
    import src.backup.export_folder as ef

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:  # a UTC-reading implementation takes this branch
                return datetime(2026, 9, 12, 8, 45)
            return datetime(2026, 9, 12, 10, 45)

    monkeypatch.setattr(ef, "datetime", _FixedDatetime)
    assert folder_name() == "202609121045_OpenOmniscience_Backup"


def test_a_second_export_in_the_same_minute_never_touches_the_first(tmp_path):
    """The negative space of Q211/Q213: no overwrite, ever."""
    when = datetime(2026, 9, 12, 10, 45)
    first = allocate_export_folder(tmp_path, now=when)
    # Something valuable already in it — a real export's manifest.
    (first / MANIFEST_NAME).write_text('{"kind": "oo-volumes-2"}', encoding="utf-8")
    payload = (first / MANIFEST_NAME).read_bytes()

    second = allocate_export_folder(tmp_path, now=when)
    third = allocate_export_folder(tmp_path, now=when)

    assert first.name == "202609121045_OpenOmniscience_Backup"
    assert second.name == "202609121045_OpenOmniscience_Backup_2"
    assert third.name == "202609121045_OpenOmniscience_Backup_3"
    assert first != second != third
    # The first folder's bytes are exactly as they were.
    assert (first / MANIFEST_NAME).read_bytes() == payload
    # And the new folders are genuinely empty — nothing adopted, nothing reused.
    assert list(second.iterdir()) == [] and list(third.iterdir()) == []


def test_a_destination_that_already_holds_a_set_is_never_reused(tmp_path):
    """Q213 = c: always a full new backup. A hand-made folder with the ruled name — the
    shape an operator's own second export would take — is stepped over, not entered."""
    when = datetime(2026, 9, 12, 10, 45)
    squatter = tmp_path / folder_name(when)
    squatter.mkdir()
    (squatter / MANIFEST_NAME).write_text('{"kind": "oo-volumes-2", "volumes": []}', encoding="utf-8")
    (squatter / "vol-00001.ooenc").write_bytes(b"precious")

    got = allocate_export_folder(tmp_path, now=when)
    assert got != squatter
    assert (squatter / "vol-00001.ooenc").read_bytes() == b"precious"
    assert list(got.iterdir()) == []


def test_a_file_occupying_the_name_is_stepped_over_not_clobbered(tmp_path):
    when = datetime(2026, 9, 12, 10, 45)
    blocker = tmp_path / folder_name(when)
    blocker.write_text("not a folder", encoding="utf-8")
    got = allocate_export_folder(tmp_path, now=when)
    assert got.name.endswith("_Backup_2")
    assert blocker.read_text(encoding="utf-8") == "not a folder"


def test_an_unusable_destination_is_a_named_refusal(tmp_path):
    blocked = tmp_path / "a-file"
    blocked.write_text("x", encoding="utf-8")
    with pytest.raises(ExportFolderError):
        allocate_export_folder(blocked / "under-a-file")


# --------------------------------------------------------------------------- #
#  A real export, used by everything below
# --------------------------------------------------------------------------- #
def _corpus(tmp_path: Path) -> Path:
    p = tmp_path / "corpus.db"
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE articles (id INTEGER PRIMARY KEY, hash TEXT, title TEXT, content TEXT);
        CREATE UNIQUE INDEX ix_articles_hash ON articles(hash);
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE wiki_pages (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE law_documents (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, term TEXT);
        CREATE TABLE alembic_version (version_num TEXT);
        INSERT INTO alembic_version VALUES ('f4c2a1b9d7e0');
        """
    )
    con.executemany(
        "INSERT INTO articles VALUES (?,?,?,?)",
        [(i, f"h{i:06d}", f"t{i}", "x" * 600) for i in range(300)],
    )
    con.executemany("INSERT INTO sources VALUES (?,?)", [(i, f"s{i}") for i in range(9)])
    con.executemany("INSERT INTO wiki_pages VALUES (?,?)", [(i, f"w{i}") for i in range(5)])
    # MORE rows than `articles`, deliberately: with articles also the largest table the
    # articles-first rule is indistinguishable from a plain largest-first sort, and a
    # mutation that deletes the rule passes. (A surviving mutant said so.)
    con.executemany(
        "INSERT INTO keyword_mentions VALUES (?,?)", [(i, f"k{i}") for i in range(900)]
    )
    con.commit()
    con.close()
    return p


def _export(tmp_path: Path, dest: Path) -> dict:
    src = CorpusSource(
        path=_corpus(tmp_path), member_name="corpus.db", encrypted=False, freeze=_no_freeze
    )
    side = tmp_path / "state.json"
    side.write_text('{"a": 1}', encoding="utf-8")
    return write_stream_backup(
        dest,
        _PASS,
        corpus_source=src,
        side_members=[MemberFile("state.json", "state", side)],
        volume_size=128 * 1024,
    )


def _status(dest: Path, summary: dict, verify: dict) -> dict:
    """The volume job's status shape, built from a REAL export's real summary."""
    from src.backup.volume_job import _envelope_facts

    kept = {k: v for k, v in summary.items() if k != "envelope"}
    kept["facts"] = _envelope_facts(summary.get("envelope"))
    kept["verify"] = verify
    return {"mode": "backup", "state": "done", "dest": str(dest), "summary": kept}


@pytest.fixture()
def exported(tmp_path):
    dest = allocate_export_folder(tmp_path / "drive")
    summary = _export(tmp_path, dest)
    return dest, summary


# --------------------------------------------------------------------------- #
#  S2 — verify after write (Q218 = a)
# --------------------------------------------------------------------------- #
def test_a_clean_set_verifies(exported):
    dest, _ = exported
    res = verify_volume_set(dest)
    assert res["ok"] is True and res["bad"] == []
    assert res["checked"] == res["total"] > 0


def test_a_truncated_volume_is_named_and_the_panel_does_not_read_verified(exported):
    dest, summary = exported
    victim = sorted(dest.glob("*.ooenc"))[0]
    data = victim.read_bytes()
    victim.write_bytes(data[: len(data) // 2])  # the drive kept less than we wrote

    res = verify_volume_set(dest)
    assert res["ok"] is False
    assert victim.name in res["bad"]
    assert res["missing"] == []  # truncated, not absent — different facts

    facts = export_facts(
        dest,
        volume_status=_status(dest, summary, {"state": "failed", "bad": res["bad"], "total": res["total"]}),
    )
    md = render_summary_markdown(facts)
    assert "NOT verified" in md and victim.name in md
    assert "Verified — all" not in md


def test_a_single_flipped_BIT_is_caught(exported):
    """The failure this pass exists for: a drive that accepted the write and stored
    something else. The size is unchanged, so only a checksum can see it."""
    dest, _ = exported
    victim = sorted(dest.glob("*.ooenc"))[0]
    data = bytearray(victim.read_bytes())
    at = len(data) // 2
    before = data[at]
    data[at] ^= 0b0000_0001
    assert data[at] != before
    victim.write_bytes(bytes(data))
    assert victim.stat().st_size == len(data)  # same size — a size check would pass

    res = verify_volume_set(dest)
    assert res["ok"] is False and victim.name in res["bad"]


def test_a_missing_volume_is_reported_as_missing_not_merely_bad(exported):
    dest, _ = exported
    victim = sorted(dest.glob("*.ooenc"))[0]
    victim.unlink()
    res = verify_volume_set(dest)
    assert victim.name in res["bad"] and victim.name in res["missing"]


def test_verify_reports_progress_and_can_be_stopped_without_finishing(exported):
    dest, _ = exported
    seen: list[dict] = []
    with pytest.raises(VolumeStopped):
        verify_volume_set(dest, progress_cb=seen.append, should_stop=lambda: len(seen) >= 1)
    assert seen and seen[0]["volumes_total"] >= 1
    assert seen[0]["volumes_verified"] == 1


def test_a_cancelled_verification_leaves_the_COMPLETE_backup_on_the_drive(tmp_path):
    """The worst thing this feature could do. A Stop during the re-read reaches the
    manager's shared stop Event — the SAME one whose cancel path deletes a partial
    set. The volumes are written and the manifest is signed by then, so a cancelled
    verification must report "not read back" and delete nothing."""
    from src.backup.volume_job import VolumeBackupManager

    dest = allocate_export_folder(tmp_path / "drive")
    summary = _export(tmp_path, dest)
    before = {p.name for p in dest.iterdir()}
    assert any(n.endswith(".ooenc") for n in before)

    mgr = VolumeBackupManager()
    mgr._stop.set()  # a Stop already requested when the verify begins
    verdict = mgr._verify_after_write(dest, True)

    assert verdict["state"] == "stopped"
    assert "not read back" in verdict["reason"]
    assert {p.name for p in dest.iterdir()} == before, "a cancelled re-read deleted files"
    assert (dest / MANIFEST_NAME).exists()
    assert summary["volumes"] > 0


def test_verify_off_is_its_own_state_and_never_reads_verified(tmp_path):
    from src.backup.volume_job import VolumeBackupManager

    dest = allocate_export_folder(tmp_path / "drive")
    _export(tmp_path, dest)
    verdict = VolumeBackupManager()._verify_after_write(dest, False)
    assert verdict["state"] == "off"
    assert "turned off" in verdict["reason"]
    assert verdict["method"] is None


def test_an_unreadable_set_is_unavailable_not_verified_and_not_failed(tmp_path):
    """Three not-verified cases that a single boolean would flatten into one."""
    from src.backup.volume_job import VolumeBackupManager

    empty = allocate_export_folder(tmp_path / "drive")  # no manifest: nothing to re-read
    verdict = VolumeBackupManager()._verify_after_write(empty, True)
    assert verdict["state"] == "unavailable"
    assert "could not be re-read" in verdict["reason"]


def test_the_default_is_ON_at_every_layer(tmp_path):
    """Q218 = a says default ON. A caller that never saw the dialog gets the ruled
    behaviour, not the cheaper one — so the default is asserted where it is DECIDED."""
    import inspect

    from src.api.backup_v2 import VolumeBackupBody
    from src.backup.volume_job import VolumeBackupManager

    assert VolumeBackupBody.model_fields["verify_after_write"].default is True
    sig = inspect.signature(VolumeBackupManager.start_backup)
    assert sig.parameters["verify_after_write"].default is True


# --------------------------------------------------------------------------- #
#  S3 — the completion panel and BACKUP_SUMMARY.md (R4; Q208, Q209)
# --------------------------------------------------------------------------- #
def test_the_summary_file_and_volumes_json_agree_on_every_shared_figure(exported):
    """The gate row's "closes when" clause, as a test."""
    dest, summary = exported
    verify = verify_volume_set(dest)
    facts = export_facts(
        dest,
        volume_status=_status(
            dest, summary, {"state": "verified", "total": verify["total"], "bad": []}
        ),
    )
    path = write_backup_summary(dest, facts)
    assert path.name == SUMMARY_NAME and path.parent == dest

    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    md = path.read_text(encoding="utf-8")

    # volume count
    assert str(len(manifest["volumes"])) in md
    assert facts["volumes"]["count"] == len(manifest["volumes"])
    # bytes on the drive, summed from the manifest itself
    on_drive = sum(int(v["bytes"]) for v in manifest["volumes"]) + sum(
        int(p["bytes"]) for p in (manifest.get("parity") or {}).get("volumes") or []
    )
    assert facts["volumes"]["bytes"] == on_drive
    # content bytes
    assert facts["volumes"]["plaintext_bytes"] == manifest["plaintext_bytes"]
    # the container kind
    assert facts["schema"]["container"] == manifest["kind"]
    # and the destination the panel names is the folder the file is in
    assert facts["destination"] == str(dest)
    assert dest.name in md


def test_articles_lead_the_per_table_counts(exported):
    dest, summary = exported
    facts = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    names = [r["name"] for r in facts["tables"]]
    rows = {r["name"]: r["rows"] for r in facts["tables"]}
    # The rule has to BEAT the count, or it is not doing anything: keyword_mentions has
    # three times the rows and still sorts second.
    assert rows["keyword_mentions"] > rows["articles"]
    assert names[0] == "articles", names[:4]
    assert names[1] == "keyword_mentions", names[:4]
    assert rows["articles"] == 300 and rows["sources"] == 9
    # An EMPTY table is carried, not dropped: "this backup holds no law documents" is a
    # fact a reader of a five-year-old drive may need.
    assert rows["law_documents"] == 0
    md = render_summary_markdown(facts)
    assert md.index("| `articles` |") < md.index("| `keyword_mentions` |")


def test_an_unmeasured_elapsed_says_so_and_never_renders_as_zero(exported):
    """A None that means "unmeasured" must never render as 0 — they are different facts.

    Asserted on the FORMATTER as well as on the document: the document's own branch for
    an absent files timing does not reach the formatter, so a formatter that turned a
    None into 0.0 s would have gone unnoticed there (a surviving mutant said so, and
    `corpus_s` DOES reach it).
    """
    from src.backup.export_summary import _seconds

    assert _seconds(None) == "—"
    assert "0" not in _seconds(None)

    dest, summary = exported
    facts = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    assert facts["elapsed"]["files_s"] is None
    assert facts["elapsed"]["files_s_reason"]
    md = render_summary_markdown(facts)
    assert "**Elapsed (files):** 0" not in md
    assert "not recorded" in md or "no large-data files" in md

    # And the corpus span, which does reach the formatter, when it is unmeasured.
    blank = dict(facts, elapsed={**facts["elapsed"], "corpus_s": None})
    line = [x for x in render_summary_markdown(blank).splitlines() if "Elapsed (corpus)" in x][0]
    assert "0" not in line, line


def test_a_status_for_a_DIFFERENT_folder_is_ignored_rather_than_reported(tmp_path):
    """Reporting another job's numbers under this folder's name is the data-safety bug
    the corpus gate upstream already refuses; the summary must refuse it too."""
    mine = allocate_export_folder(tmp_path / "drive")
    other = allocate_export_folder(tmp_path / "drive")
    summary = _export(tmp_path, other)
    facts = export_facts(mine, volume_status=_status(other, summary, {"state": "verified"}))
    assert facts["corpus_included"] is False
    assert facts["tables"] == []
    assert facts["verify"]["state"] == "unknown"


def test_a_still_running_job_is_not_reported_as_a_finished_export(tmp_path):
    dest = allocate_export_folder(tmp_path / "drive")
    summary = _export(tmp_path, dest)
    st = _status(dest, summary, {"state": "verified"})
    st["state"] = "running"
    facts = export_facts(dest, volume_status=st)
    # None of the running job's own figures are reported. (The folder DOES hold a
    # finished volume set here -- the fixture wrote one -- so the corpus is reported as
    # present, from volumes.json, with its measurements "not held" rather than as
    # "no corpus": the 2026-09-26 click-through, J1.)
    assert facts["corpus_facts"] == "not_held"
    assert facts["tables"] == []
    assert facts["volumes"]["plaintext_bytes"] is None
    assert facts["verify"]["state"] != "verified"


def test_the_summary_carries_the_ruled_fields(exported):
    """Q208 = a's list, each one present in the file that Q209 = a puts on the drive."""
    dest, summary = exported
    facts = export_facts(
        dest, volume_status=_status(dest, summary, {"state": "verified", "total": 3, "bad": []})
    )
    md = render_summary_markdown(facts)
    for needle in (
        "Encrypted volumes",       # volumes
        "on the drive",            # total bytes
        "| `articles` |",          # per-table counts, articles first
        "Elapsed (corpus)",        # elapsed
        "Destination",             # destination path
        "Corpus at rest",          # encryption state
        "Backup schema",           # schema version
        "Database schema",         # the alembic revision
        "App version",             # app version
        "Attribution",             # the licence lines that apply
    ):
        assert needle in md, needle
    assert facts["app_version"], "the app version must be a real value, not a blank"
    assert facts["schema"]["alembic_rev"] == "f4c2a1b9d7e0"


def test_the_summary_is_written_atomically_and_leaves_no_partial(exported):
    dest, summary = exported
    facts = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    write_backup_summary(dest, facts)
    write_backup_summary(dest, facts)  # a rewrite must not leave a temp behind
    assert not list(dest.glob("*.oopart"))
    assert (dest / SUMMARY_NAME).exists()


# --------------------------------------------------------------------------- #
#  The other half of the loop: an export must still be findable and readable
# --------------------------------------------------------------------------- #
def test_the_dated_folder_is_discoverable_from_the_drive_AND_from_itself(tmp_path):
    """Moving the set one folder deeper could have hidden it from the import.

    It does the opposite, which is worth pinning rather than assuming: pointing the
    import at the DRIVE now finds each export as its own restorable backup, where
    before three exports into one directory were one folder overwritten three times.
    """
    from src.backup.import_scan import scan_import_folder

    drive = tmp_path / "drive"
    when = datetime(2026, 9, 12, 10, 45)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = allocate_export_folder(drive, now=when)
    _export(a, first)
    second = allocate_export_folder(drive, now=when)
    _export(b, second)

    from_drive = scan_import_folder(str(drive))["found"]["corpus"]
    assert {Path(c["path"]).name for c in from_drive} == {first.name, second.name}
    assert all(c["manifest"] == MANIFEST_NAME and c["volumes"] > 0 for c in from_drive)

    from_folder = scan_import_folder(str(first))["found"]["corpus"]
    assert [Path(c["path"]).name for c in from_folder] == [first.name]


def test_a_folder_written_by_the_export_reads_back_byte_for_byte(tmp_path):
    """The round trip at fixture scale: what the export wrote is what comes back.

    The REMOVABLE-DRIVE half of this is the operator's (a second read of every byte off
    real hardware is not measurable here) — but "the set this folder shape produces is
    readable at all" is measurable, and is the half that a folder-layout change could
    break silently.
    """
    from src.backup.stream_backup import read_stream_backup

    dest = allocate_export_folder(tmp_path / "drive")
    corpus = _corpus(tmp_path)
    before = corpus.read_bytes()
    src = CorpusSource(path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze)
    write_stream_backup(dest, _PASS, corpus_source=src, side_members=[], volume_size=128 * 1024)

    staged = read_stream_backup(dest, _PASS, tmp_path / "staging")
    out = Path(staged.staging_dir) / "corpus.db" if hasattr(staged, "staging_dir") else None
    assert out is not None and out.exists(), staged
    assert out.read_bytes() == before, "the corpus did not survive the round trip"


# --------------------------------------------------------------------------- #
#  The 2026-09-26 delegated click-through, row J
#  (docs/audit/delegated-clickthrough-2026-09-26/defects.csv, J1 J2 J4 J5 J6 J7)
# --------------------------------------------------------------------------- #
_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
_LANGS = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")


def _job_fn(tmp_path: Path, tag: str):
    """The volume manager's backup seam, running the REAL stream writer on a fixture."""
    work = tmp_path / tag
    work.mkdir()

    def fn(dest, pw, *, include_newsletters, parity_fraction, should_stop, progress_cb, include_blobs):
        src = CorpusSource(
            path=_corpus(work), member_name="corpus.db", encrypted=False, freeze=_no_freeze
        )
        side = work / "state.json"
        side.write_text('{"a": 1}', encoding="utf-8")
        return write_stream_backup(
            dest,
            pw,
            corpus_source=src,
            side_members=[MemberFile("state.json", "state", side)],
            volume_size=128 * 1024,
            should_stop=should_stop,
            progress_cb=progress_cb,
        )

    return fn


def _run_to_done(mgr, timeout: float = 60.0) -> dict:
    import time

    t0 = time.time()
    while mgr.status()["running"] and time.time() - t0 < timeout:
        time.sleep(0.02)
    st = mgr.status()
    assert st["state"] == "done", st
    return st


def test_a_folder_holding_a_set_is_never_reported_as_holding_no_corpus(tmp_path):
    """J1: "Encrypted volumes: none — no corpus was selected" for a folder with four
    volumes in it. Whether the corpus is IN the folder is read off the folder; only the
    export's own measurements depend on what this process still remembers."""
    mine = allocate_export_folder(tmp_path / "drive")
    _export(tmp_path, mine)
    other = allocate_export_folder(tmp_path / "drive")
    b = tmp_path / "b"
    b.mkdir()
    summary = _export(b, other)
    facts = export_facts(mine, volume_status=_status(other, summary, {"state": "verified"}))
    manifest = json.loads((mine / MANIFEST_NAME).read_text(encoding="utf-8"))

    assert facts["corpus_included"] is True
    assert facts["corpus_facts"] == "not_held"
    assert facts["volumes"]["count"] == len(manifest["volumes"])
    assert facts["tables"] == [], "another export's counts were reported under this folder"
    assert facts["verify"]["state"] == "not_held"
    md = render_summary_markdown(facts)
    assert "no corpus was selected" not in md
    assert "NOT verified" not in md, "an unknown verdict was written as an alarm"


def test_an_export_s_facts_survive_a_later_export_to_another_folder(tmp_path, monkeypatch):
    """J1 end to end through the endpoint the reopened panel reads: export A, then a
    corpus-only export B. The manager's live status is B's, and A's facts used to be
    refused as "another job's" -- so A read back as holding no corpus at all."""
    import src.backup.volume_job as vj
    from src.api.backup_v2 import export_summary_read

    mgr = vj.VolumeBackupManager()
    monkeypatch.setattr(vj, "_MANAGER", mgr)
    a = allocate_export_folder(tmp_path / "drive")
    mgr.start_backup(str(a), _PASS, _backup_fn=_job_fn(tmp_path, "a"))
    _run_to_done(mgr)
    b = allocate_export_folder(tmp_path / "drive")
    mgr.start_backup(str(b), _PASS, _backup_fn=_job_fn(tmp_path, "b"))
    assert _run_to_done(mgr)["dest"] == str(b)

    facts = export_summary_read(str(a))
    assert facts["corpus_included"] is True and facts.get("corpus_facts") == "measured"
    assert {r["name"]: r["rows"] for r in facts["tables"]}["articles"] == 300
    assert facts["verify"]["state"] == "verified"
    assert facts["destination"] == str(a)


def test_the_job_writes_BACKUP_SUMMARY_md_itself_before_it_reports_done(tmp_path, monkeypatch):
    """J2: the file used to be written only by the page, at the end of its own run --
    a reload mid-export left a complete, verified backup with no summary beside it."""
    import src.backup.volume_job as vj
    from src.api.backup_v2 import export_summary_read

    mgr = vj.VolumeBackupManager()
    monkeypatch.setattr(vj, "_MANAGER", mgr)
    dest = allocate_export_folder(tmp_path / "drive")
    mgr.start_backup(str(dest), _PASS, _backup_fn=_job_fn(tmp_path, "a"))
    _run_to_done(mgr)

    written = dest / SUMMARY_NAME
    assert written.is_file(), "no BACKUP_SUMMARY.md without the page's POST"
    md = written.read_text(encoding="utf-8")
    assert "Verified — all" in md, "the file does not carry the verify verdict"
    assert "| `articles` | 300 |" in md
    # The same renderer the page's POST uses: identical but for the time it was written.
    again = render_summary_markdown(export_facts(dest, volume_status=mgr.status()))

    def strip(s: str) -> list[str]:
        return [x for x in s.splitlines() if not x.startswith("- **Written:**")]

    assert strip(md) == strip(again)
    # …and the endpoint the reopened panel reads now says where it is.
    assert export_summary_read(str(dest)).get("summary_path") == str(written)


def test_the_job_never_writes_a_summary_outside_a_dated_export_folder(tmp_path):
    """The older volume-backup dialog writes into whatever folder the operator names; a
    file appearing there would be a change nobody asked for."""
    from src.backup.volume_job import VolumeBackupManager

    mgr = VolumeBackupManager()
    legacy = tmp_path / "my-backups"
    mgr.start_backup(str(legacy), _PASS, _backup_fn=_job_fn(tmp_path, "a"))
    _run_to_done(mgr)
    assert (legacy / MANIFEST_NAME).exists()
    assert not (legacy / SUMMARY_NAME).exists()


def test_the_large_data_phase_rewrites_the_summary_with_both_halves(tmp_path, monkeypatch):
    """J2, second writer: the copy completes after the corpus phase, so ITS rewrite is
    the one left on the drive -- and it must still carry the corpus half, even when the
    volume manager has run another export since."""
    import src.backup.volume_job as vj
    from src.backup.folder_backup import BackupItem, FolderBackupManager

    mgr = vj.VolumeBackupManager()
    monkeypatch.setattr(vj, "_MANAGER", mgr)
    dest = allocate_export_folder(tmp_path / "drive")
    mgr.start_backup(str(dest), _PASS, _backup_fn=_job_fn(tmp_path, "a"))
    _run_to_done(mgr)
    other = allocate_export_folder(tmp_path / "drive")
    mgr.start_backup(str(other), _PASS, _backup_fn=_job_fn(tmp_path, "b"))
    _run_to_done(mgr)

    blob = tmp_path / "weights.bin"
    blob.write_bytes(b"w" * 4096)
    fmgr = FolderBackupManager()
    fmgr.start(str(dest), ["models"], _items=[BackupItem("models", "m/weights.bin", blob, 4096)])
    _run_to_done(fmgr)

    md = (dest / SUMMARY_NAME).read_text(encoding="utf-8")
    assert "`models`: 1 files" in md, "the copied files are not in the rewritten summary"
    assert "| `articles` | 300 |" in md, "the rewrite dropped the corpus half"
    assert "Verified — all" in md


def test_a_rewrite_that_no_longer_holds_the_corpus_facts_keeps_the_file_that_does(exported):
    dest, summary = exported
    good = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified", "total": 3}))
    path = write_backup_summary(dest, good)
    before = path.read_text(encoding="utf-8")
    thin = export_facts(dest, volume_status=None)
    assert thin.get("corpus_facts") == "not_held"
    write_backup_summary(dest, thin)
    assert path.read_text(encoding="utf-8") == before, "a complete summary was replaced by dashes"


def test_the_first_export_carries_the_key_that_signs_it(tmp_path, monkeypatch):
    """J4: on an install with no evidence key yet, the key was created by the envelope
    AFTER the side members were collected -- the first export had one volume fewer than
    every later one and did not carry the identity that signed it."""
    data = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    assert not (data / "keys").exists()
    dest = allocate_export_folder(tmp_path / "drive")
    src = CorpusSource(
        path=_corpus(tmp_path), member_name="corpus.db", encrypted=False, freeze=_no_freeze
    )
    summary = write_stream_backup(dest, _PASS, corpus_source=src, volume_size=128 * 1024)
    names = [m["name"] for m in summary["envelope"]["manifest"]["members"]]
    assert "keys/evidence_ed25519.pem" in names, names
    assert summary["envelope"]["manifest"]["keys_included"] is True


def test_a_plaintext_corpus_is_not_called_unencrypted_inside_encrypted_volumes(exported):
    """J5: "Corpus at rest in this backup: no", directly above "The corpus and every
    member of the artifact are encrypted". The flag is the database FILE's SQLCipher
    state; the volumes around it are always encrypted."""
    dest, summary = exported  # the fixture's corpus source is a plaintext SQLite file
    facts = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    assert facts["encryption"]["corpus_encrypted"] is False
    md = render_summary_markdown(facts)
    line = [x for x in md.splitlines() if "Corpus at rest" in x][0]
    assert not line.rstrip().endswith("no"), line
    assert "not separately encrypted" in line and "volumes" in line, line


def test_the_re_read_is_announced_before_the_first_volume_is_hashed(exported, monkeypatch):
    """J6: verify_volume_set reports after each volume, so the whole read of the first
    one used to go on reading "Writing parity…"."""
    import src.backup.volumes as volumes_mod
    from src.backup.volume_job import VolumeBackupManager

    dest, _ = exported
    mgr = VolumeBackupManager()
    mgr._on_prog({"phase": "parity", "volumes_written": 3})
    seen: dict = {}
    real = volumes_mod.verify_volume_set

    def spy(*a, **k):
        seen["phase"] = mgr.status()["progress"].get("phase")
        return real(*a, **k)

    monkeypatch.setattr(volumes_mod, "verify_volume_set", spy)
    assert mgr._verify_after_write(dest, True)["state"] == "verified"
    assert seen["phase"] == "verifying"


def test_every_server_sentence_the_panel_translates_is_keyed_in_all_12_locales(exported):
    """J7: the Elapsed and Encryption hovers are English sentences the server sends and
    the panel looks up with t(). The i18n gate reads literal t("...") calls only, so it
    cannot see these -- this is the gate for them. A caveat ships x12.

    The Licences lines joined them (2026-09-26 click-through, J-licences): every line
    the attribution registry can emit is looked up with t() too, so every one of them is
    listed here -- read off the registry itself, so a line added later is gated the day
    it is added rather than the day someone notices it in French."""
    from src.backup.attribution import _REGISTRY

    dest, summary = exported
    no_files = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    (dest / "oo-folder-backup.json").write_text(
        json.dumps({"categories": {"models": [{"category": "models", "rel": "a", "size": 1}]}}),
        encoding="utf-8",
    )
    with_files = export_facts(dest, volume_status=_status(dest, summary, {"state": "verified"}))
    licence_lines = {text_fn() for _key, text_fn, _because in _REGISTRY}  # type: ignore[operator]
    assert len(licence_lines) == len(_REGISTRY) >= 4, licence_lines
    sentences = {
        no_files["elapsed"]["files_s_reason"],
        with_files["elapsed"]["files_s_reason"],
        no_files["encryption"]["note"],
    } | licence_lines
    assert len(sentences) == 3 + len(_REGISTRY), sentences
    maps = {
        lang: json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in _LANGS
    }
    for s in sentences:
        for lang, m in maps.items():
            assert s in m, f"{lang}.json has no key for the hover {s!r}"
            if lang != "en":
                assert m[s] != s, f"{lang}.json leaves the hover {s!r} in English"

"""R780: a file a folder restore brings back that the backup's CURRENT manifest does not list is counted
apart, per category, in the scan and in the result -- apart from "not content-verified".

The manifest is signed with a key it carries itself (tamper-evidence only), so it proves nothing about
where a file came from: an unlisted file keeps restoring, and the words say what it MAY be (left by an
earlier or interrupted backup pass), never that it is foreign or that a listed one is authentic.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup.folder_backup import MANIFEST_NAME, BackupItem, restore_folder_backup, write_folder_backup
from src.backup.import_scan import SCAN_UNLISTED, scan_import_folder
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]
LINE = "Restored, but not listed in this backup's current manifest; they may come from an earlier or interrupted backup pass"
PART = "({n} not in the manifest)"


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _targets(tmp: Path) -> dict[str, Path]:
    return {c: tmp / "live" / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")}


def _item(tmp: Path, cat: str, rel: str, data: bytes) -> BackupItem:
    p = _touch(tmp / "live-src" / cat / rel, data)
    return BackupItem(cat, rel, p, len(data))


def test_a_file_left_by_an_earlier_pass_restores_and_is_counted_unlisted(tmp_path):
    """The stale-file case: removed from the live folder, still on the backup, gone from the manifest."""
    bk = tmp_path / "scan" / "bk"
    a, b = _item(tmp_path, "wiki_dumps", "a.bz2", b"aaa"), _item(tmp_path, "wiki_dumps", "b.bz2", b"bb")
    write_folder_backup(bk, [a, b])
    write_folder_backup(bk, [a])  # b was deleted from the live folder; the backup keeps the file
    assert (bk / "wiki_dumps" / "b.bz2").is_file()
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored"] == 2
    assert got["restored_unlisted"] == {"wiki_dumps": 1}
    assert (tmp_path / "live" / "wiki_dumps" / "b.bz2").read_bytes() == b"bb"  # still restored


def test_a_fully_listed_backup_has_no_unlisted_count(tmp_path):
    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a"), _item(tmp_path, "osm_regions", "fr.pbf", b"f")])
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored"] == 2 and got["restored_unlisted"] == {}


def test_a_file_dropped_in_by_hand_is_counted_per_category_and_apart_from_unverified(tmp_path):
    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a")])
    _touch(bk / "osm_regions" / "x.pbf", b"x")
    _touch(bk / "models" / "blobs" / "sha256-z", b"z")
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored"] == 3
    assert got["restored_unlisted"] == {"osm_regions": 1, "models": 1}
    # An unlisted file has no recorded checksum either, so it is also not content-verified.
    assert got["restored_unverified"] == 2


def test_no_readable_manifest_counts_every_file_unlisted(tmp_path):
    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a"), _item(tmp_path, "osm_regions", "fr.pbf", b"f")])
    (bk / MANIFEST_NAME).write_text("{ not json", encoding="utf-8")
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored"] == 2 and got["restored_unlisted"] == {"wiki_dumps": 1, "osm_regions": 1}


def test_a_manifest_entry_without_a_checksum_still_counts_as_listed(tmp_path):
    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a")])
    m = json.loads((bk / MANIFEST_NAME).read_text(encoding="utf-8"))
    for e in m["categories"]["wiki_dumps"]:
        e.pop("sha256", None)
    (bk / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored_unlisted"] == {} and got["restored_unverified"] == 1


def test_the_scan_counts_unlisted_like_the_restore(tmp_path):
    bk = tmp_path / "scan" / "bk"
    a, b = _item(tmp_path, "wiki_dumps", "a.bz2", b"aaa"), _item(tmp_path, "wiki_dumps", "b.bz2", b"bb")
    write_folder_backup(bk, [a, b])
    write_folder_backup(bk, [a])
    w = scan_import_folder(tmp_path / "scan")["found"]["blobs"]["wiki"]
    assert w["count"] == 2 and w["unlisted"] == 1 and w["unlisted_reason"] == SCAN_UNLISTED
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert sum(got["restored_unlisted"].values()) == w["unlisted"]


def test_the_scan_of_a_fully_listed_backup_says_nothing_about_it(tmp_path):
    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a")])
    w = scan_import_folder(tmp_path / "scan")["found"]["blobs"]["wiki"]
    assert "unlisted" not in w and "unlisted_reason" not in w


def test_the_words_never_claim_proof_of_origin():
    """The manifest signs itself; nothing new may call it proof of where a file came from."""
    texts = [SCAN_UNLISTED, LINE]
    for f in [ROOT / "docs" / "USER_MANUAL.md", *sorted((ROOT / "docs" / "i18n").glob("*/USER_MANUAL.md"))]:
        s = f.read_text(encoding="utf-8")
        i = s.find("current manifest")
        if i != -1:
            texts.append(s[i - 400:i + 600])
    for s in texts:
        low = s.lower()
        assert "proof" not in low and "proves" not in low
    en = (ROOT / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8")
    assert "a count of zero does not mean the files are genuine" in en
    assert "anyone who can write to this backup folder could also have placed them there" in SCAN_UNLISTED.lower()


def test_the_new_strings_are_keys_in_all_twelve_catalogues():
    files = sorted((ROOT / "src/static/locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        cat = json.loads(f.read_text(encoding="utf-8"))
        for k in (SCAN_UNLISTED, LINE, PART):
            assert cat.get(k), f"{f.name}: missing {k!r}"
        assert "{n}" in cat[PART], f"{f.name}: the count placeholder is lost"


def test_the_help_says_it_in_every_language():
    """Each manual quotes the result line exactly as the app shows it in that language."""
    manuals = {"en": ROOT / "docs" / "USER_MANUAL.md"}
    manuals.update({p.parent.name: p for p in (ROOT / "docs" / "i18n").glob("*/USER_MANUAL.md")})
    assert len(manuals) == 12
    for code, f in manuals.items():
        cat = json.loads((ROOT / "src/static/locales" / f"{code}.json").read_text(encoding="utf-8"))
        assert cat[LINE] in f.read_text(encoding="utf-8"), f"{code}: the Help does not quote the result line"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_result_line_and_the_checklist_row_node():
    r = subprocess.run(["node", str(ROOT / "tests" / "restore_unlisted_r780_node_test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


# The manifest itself is untrusted: every reader takes it through one hardened reader.
def test_the_manifest_reader_refuses_what_is_not_a_small_regular_json_file(tmp_path, monkeypatch):
    import os

    from src.backup import manifest_file
    from src.backup.manifest_file import read_manifest_json

    good = tmp_path / "good.json"
    good.write_text('{"categories": {}}', encoding="utf-8")
    assert read_manifest_json(good) == {"categories": {}}
    assert read_manifest_json(tmp_path / "missing.json") is None
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 200_000, encoding="utf-8")
    assert read_manifest_json(deep) is None  # RecursionError, not a crash
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe{")
    assert read_manifest_json(bad) is None
    monkeypatch.setattr(manifest_file, "MANIFEST_MAX_BYTES", 8)
    assert read_manifest_json(good) is None  # too large
    monkeypatch.undo()
    if hasattr(os, "symlink") and os.name != "nt":
        ln = tmp_path / "ln.json"
        ln.symlink_to(good)
        assert read_manifest_json(ln) is None  # a link is never followed
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo.json"
        os.mkfifo(fifo)
        assert read_manifest_json(fifo) is None  # a pipe never blocks the reader


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="needs named pipes")
def test_a_manifest_that_is_a_pipe_does_not_hang_the_scan_or_the_restore(tmp_path):
    import os

    bk = tmp_path / "scan" / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a")])
    (bk / MANIFEST_NAME).unlink()
    os.mkfifo(bk / MANIFEST_NAME)
    got = restore_folder_backup(bk, targets=_targets(tmp_path))
    assert got["restored"] == 1 and got["restored_unlisted"] == {"wiki_dumps": 1}


def test_every_manifest_reader_goes_through_the_hardened_reader():
    for f in ("src/backup/folder_backup.py", "src/backup/import_scan.py"):
        s = (ROOT / f).read_text(encoding="utf-8")
        assert "read_manifest_json(" in s
        assert "MANIFEST_NAME).read_text(" not in s and "p.read_text(" not in python_function_source(s, "_manifest_listing")


def test_a_manifest_size_that_is_not_a_number_does_not_stop_the_scan(tmp_path):
    from src.backup.import_scan import _read_folder_manifest

    m = tmp_path / MANIFEST_NAME
    m.write_text(json.dumps({"categories": {"wiki_dumps": [{"rel": "a", "size": "x"}, {"rel": "b", "size": None},
                                                            {"rel": "c", "size": [1]}, {"rel": "d", "size": 5}]}}),
                 encoding="utf-8")
    assert _read_folder_manifest(m) == {"wiki_dumps": (4, 5)}


def test_verify_names_a_manifest_that_is_there_but_refused(tmp_path):
    from src.backup.folder_backup import verify_folder_backup

    bk = tmp_path / "bk"
    write_folder_backup(bk, [_item(tmp_path, "wiki_dumps", "a.bz2", b"a")])
    (bk / MANIFEST_NAME).write_text("[" * 200_000, encoding="utf-8")
    got = verify_folder_backup(bk)
    assert got["ok"] is False and got["manifest_found"] is False and "was refused" in got["reason"]
    (bk / MANIFEST_NAME).unlink()
    assert "no finalized manifest" in verify_folder_backup(bk)["reason"]

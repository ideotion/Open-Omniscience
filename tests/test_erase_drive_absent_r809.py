"""
Row 381 (R809): a marked data drive that is not there when the erase runs is a FAILURE: nothing on it is checked or erased,
the result is never "removed" and never clean, what was erased elsewhere is said apart, and nothing reassures. A drive that goes
away during the erase is "partially erased / could not check". The same holds in the CLI, with a non-zero exit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src import paths
from src.safety import crypto_erase, data_volume

S1 = "The data drive was not present. Nothing on it was checked or erased. The data on that drive still exists."
S3 = "The data drive disconnected during the erase: it was only partially erased, and what was left on it could not be checked."


@pytest.fixture
def marked(tmp_path, monkeypatch):
    """A data folder the first-launch step put on a marked drive (OO_DATA_DIR + OO_DATA_VOLUME_ID), and a columnar store the
    override keeps OUTSIDE it, on the internal disk."""
    data = tmp_path / "drive" / "OOS data"
    outside = tmp_path / "internal" / "columnar"
    outside.mkdir(parents=True)
    for name in crypto_erase._DUCK_FILES:
        (outside / name).write_bytes(b"D" * 8192)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv(data_volume.ENV_ID, "a1b2c3d4e5f60718")
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(outside))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(paths, "_memo", None)
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: pytest.fail("the id of a drive not there is kept"))
    return data, outside


def _app_files(data: Path, marker_id: str | None) -> dict[Path, bytes]:
    data.mkdir(parents=True)
    files = {data / "open_omniscience.db": os.urandom(8192), data / "keys" / "custody_ed25519.pem": b"PRIVATE",
             data / "wiki_dumps" / "part.xml": b"x" * 100}
    for p, b in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    if marker_id is not None:
        (data / data_volume.MARKER_NAME).write_text(json.dumps({"id": marker_id}), encoding="utf-8")
    return files


def test_a_drive_not_there_is_a_failure_and_nothing_is_made(marked):
    data, outside = marked
    out = crypto_erase.quick_crypto_erase(confirm=True)
    assert out["drive_absent"] is True and out["removed"] is False, out
    assert out["limit"] == S1, "the sentence alone: no reassurance of any kind"
    assert "unrecoverable" not in out["limit"]
    assert not data.exists() and not data.parent.exists(), "nothing is made where the drive should be"
    # what was erased elsewhere is counted apart, and is real
    assert out["files_seen"] == len(crypto_erase._DUCK_FILES) and not any((outside / n).exists() for n in crypto_erase._DUCK_FILES)
    assert crypto_erase.settle_removed(out) is False and out["removed"] is False, "never measured as removed"


def test_a_different_drive_at_the_path_is_never_touched(marked):
    data, _outside = marked
    files = _app_files(data, marker_id="ffffffffffffffff")  # another drive's marker
    out = crypto_erase.quick_crypto_erase(confirm=True)
    assert out["drive_absent"] is True and out["removed"] is False and out["limit"] == S1, out
    for p, b in files.items():
        assert p.read_bytes() == b, f"{p.name} on the other drive is byte-identical"
    assert out["keys_destroyed"] == [] and out["headers_destroyed"] == []


def test_the_marked_drive_there_is_erased_as_before(marked, monkeypatch):
    data, _outside = marked
    forgot = []
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: forgot.append(1))
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    out = crypto_erase.quick_crypto_erase(confirm=True)
    assert out["drive_absent"] is False and out["drive_lost"] is False and out["removed"] is True, out
    assert not data.exists() and forgot == [1]


def test_a_drive_that_goes_away_during_the_erase_is_partial_and_unchecked(marked, monkeypatch):
    data, _outside = marked
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: None)
    monkeypatch.setattr(crypto_erase, "_drive_lost", lambda anchor: anchor is not None)
    out = crypto_erase.quick_crypto_erase(confirm=True)
    assert out["drive_lost"] is True and out["removed"] is False and out["unlisted_folders"] >= 1, out
    assert out["limit"].startswith(S3) and "permanently unrecoverable" not in out["limit"]
    assert crypto_erase.settle_removed(out) is False


def test_the_device_check_itself(tmp_path):
    folder = tmp_path / "d" / "OOS data"
    folder.mkdir(parents=True)
    anchor = crypto_erase._drive_anchor(folder)
    assert anchor is not None and anchor[0] == folder.parent
    assert crypto_erase._drive_lost(anchor) is False
    assert crypto_erase._drive_lost((anchor[0], anchor[1] + 1)) is True, "another device at its place"
    assert crypto_erase._drive_lost((tmp_path / "gone", anchor[1])) is True, "gone"


def test_an_unanswerable_drive_question_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(data_volume, "watched", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert crypto_erase._drive_state(tmp_path) == "absent"


def test_the_cli_says_failed_and_exits_2_never_a_traceback(monkeypatch, capsys):
    import src.safety as safety
    from src.api import main

    monkeypatch.setattr(paths, "data_dir", lambda: pytest.fail("data_dir() raises when the drive is not there"))
    monkeypatch.setattr(safety, "panic_wipe", lambda confirm: {"drive_absent": True, "drive_lost": False, "limit": S1,
                                                               "files_wiped": 2, "files_seen": 2, "data_dir": "x"})
    with pytest.raises(SystemExit) as e:
        main._panic_cli(force=True)
    assert e.value.code == 2
    text = capsys.readouterr().out
    assert "ERASE FAILED" in text and S1 in text and "Files erased outside the data drive: 2 of 2." in text
    assert "Wiped" not in text and "unrecoverable" not in text


def test_the_cli_exits_1_when_the_drive_went_away(monkeypatch, capsys):
    import src.safety as safety
    from src.api import main

    monkeypatch.setattr(safety, "panic_wipe", lambda confirm: {"drive_absent": False, "drive_lost": True, "limit": S3,
                                                               "files_wiped": 1, "files_seen": 3, "data_dir": "x",
                                                               "scope": "data-folder", "removed": False, "other_holder": "none"})
    with pytest.raises(SystemExit) as e:
        main._panic_cli(force=True)
    assert e.value.code == 1
    text = capsys.readouterr().out
    assert S3 in text and "could not be removed" not in text


def test_the_panic_page_says_failed_and_offers_no_overwrite():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert 'const driveAbsent = r.drive_absent === true;' in js and "!driveAbsent && !driveLost" in js
    assert 'driveAbsent ? "erase failed"' in js
    assert '"Files erased outside the data drive: {done} of {total}."' in js
    assert S1 in js and S3 in js
    assert '(driveAbsent ? "" : `<div class="hint" style="margin-top:8px">${esc(rec)}`' in js

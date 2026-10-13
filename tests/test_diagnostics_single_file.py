"""The Diagnostics archive is handed over as ONE file when it fits one (R119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R119 (2026-10-06): one Diagnostics button, one zip, "or several, so long as they weigh less than 4 MB
each". The numbered scheme of R115 stays for an archive above the cap; below it, splitting is pure cost
(seconds to a minute, a second copy of the archive on a drive that may be nearly full, and a manifest zip
and a ``volumes-readme.json`` for a person to handle). What must not regress:

1. an archive that fits is answered with ITSELF, named ``oo-diagnostics-<stamp>.zip``, in the listing
   shape the page already saves (``files`` + ``download_base``), with no volume written;
2. the cap is "at most": an archive of exactly the cap is one file, one byte more is split;
3. a numbered set left from an earlier, larger archive does not outlive the answer that replaced it, and
   is not removed by halves;
4. only the NEWEST finished archive is served under the published name, and nothing else is reachable
   through it.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import diagnostics as d
from src.api import diagnostics_volumes as dv
from src.api.diagnostics import bundle as bundle_mod

STAMP = "20261006-120000"
ARCHIVE = f"oo-all-diagnostics-{STAMP}.zip"
PUBLISHED = f"oo-diagnostics-{STAMP}.zip"


@pytest.fixture
def diag_dir(tmp_path, monkeypatch):
    root = tmp_path / "diagnostics"
    root.mkdir()
    monkeypatch.setattr(bundle_mod, "_all_diagnostics_dir", lambda: root)
    return root


def _archive(path: Path, *, random_bytes: int = 200_000) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"kind": "all-diagnostics"}))
        z.writestr("vitals.json", json.dumps([{"n": n, "v": "x" * 30} for n in range(2000)]))
        z.writestr("random.bin", os.urandom(random_bytes))
    return path


def _listing() -> dict:
    return json.loads(bytes(d.all_diagnostics_volumes().body))


def test_an_archive_within_the_cap_is_answered_with_itself(diag_dir):
    src = _archive(diag_dir / ARCHIVE)
    listing = _listing()
    assert listing["single_file"] is True and listing["volume_count"] == 0
    assert listing["source"] == ARCHIVE
    (only,) = listing["files"]
    assert only["name"] == PUBLISHED and only["kind"] == "archive"
    assert only["bytes"] == src.stat().st_size <= dv.volume_max_bytes()
    assert only["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert listing["download_base"] == "/api/diagnostics/all-job/volumes/"
    assert listing["part_count"] == 1 and listing["part_max_bytes"] == 4_000_000


def test_no_volume_manifest_zip_or_readme_is_written_for_a_single_file(diag_dir):
    _archive(diag_dir / ARCHIVE)
    _listing()
    volumes = d._all_diagnostics_volumes_dir()
    assert list(volumes.iterdir()) == [], "a split that is not needed must not be made"
    assert not list(diag_dir.glob("volumes-build-*"))


def test_the_published_name_serves_the_archive_byte_for_byte(diag_dir):
    src = _archive(diag_dir / ARCHIVE)
    resp = d.all_diagnostics_volume_download(PUBLISHED)
    assert Path(resp.path) == src
    assert Path(resp.path).read_bytes() == src.read_bytes()
    assert resp.media_type == "application/zip"
    assert PUBLISHED in resp.headers["content-disposition"]


@pytest.mark.parametrize("extra", [0, 1])
def test_the_cap_is_at_most_so_an_archive_of_exactly_the_cap_is_one_file(diag_dir, monkeypatch, extra):
    src = _archive(diag_dir / ARCHIVE)
    monkeypatch.setattr(dv, "UPLOAD_PART_BYTES", src.stat().st_size - extra)
    listing = _listing()
    if extra == 0:
        assert listing["single_file"] is True
    else:
        assert listing["kind"] == dv.VOLUME_KIND and "single_file" not in listing
        assert listing["volume_count"] >= 2 and listing["files"][0]["kind"] == "manifest"


def test_above_the_real_cap_the_numbered_scheme_is_the_answer_and_every_file_is_within_it(diag_dir):
    _archive(diag_dir / ARCHIVE, random_bytes=9_000_000)  # about 9 MB that does not compress
    assert dv.volume_max_bytes() == 4_000_000
    listing = _listing()
    assert "single_file" not in listing and listing["volume_count"] >= 3
    kinds = [f["kind"] for f in listing["files"]]
    assert kinds[0] == "manifest" and set(kinds[1:]) == {"part"}
    assert all(f["bytes"] <= 4_000_000 for f in listing["files"])
    for f in listing["files"]:
        resp = d.all_diagnostics_volume_download(f["name"])
        assert Path(resp.path).stat().st_size == f["bytes"]


def test_a_numbered_set_of_an_earlier_larger_archive_goes_when_a_smaller_one_answers(diag_dir, monkeypatch):
    big = _archive(diag_dir / "oo-all-diagnostics-20261005-090000.zip", random_bytes=900_000)
    monkeypatch.setattr(dv, "UPLOAD_PART_BYTES", 300_000)
    first = _listing()
    volumes = d._all_diagnostics_volumes_dir()
    assert first["volume_count"] >= 3 and any(volumes.iterdir())
    big.unlink()
    _archive(diag_dir / ARCHIVE, random_bytes=1_000)
    monkeypatch.setattr(dv, "UPLOAD_PART_BYTES", 4_000_000)
    assert _listing()["single_file"] is True
    assert list(volumes.iterdir()) == [], "the old bundle's parts must not sit beside the new one"
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volume_download(first["files"][1]["name"])
    assert exc.value.status_code == 404


def test_a_set_whose_sidecar_cannot_be_removed_keeps_every_file_it_names(diag_dir, monkeypatch):
    big = _archive(diag_dir / "oo-all-diagnostics-20261005-090000.zip", random_bytes=900_000)
    monkeypatch.setattr(dv, "UPLOAD_PART_BYTES", 300_000)
    first = _listing()
    big.unlink()
    _archive(diag_dir / ARCHIVE, random_bytes=1_000)
    monkeypatch.setattr(dv, "UPLOAD_PART_BYTES", 4_000_000)
    volumes = d._all_diagnostics_volumes_dir()
    real_unlink = Path.unlink

    def refuses_the_sidecar(self, *a, **kw):
        if self.name == dv.MANIFEST_NAME:
            raise PermissionError("in use")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", refuses_the_sidecar)
    assert _listing()["single_file"] is True
    monkeypatch.undo()
    names = {p.name for p in volumes.iterdir()}
    assert {f["name"] for f in first["files"]} | {dv.MANIFEST_NAME} <= names


def test_only_the_newest_finished_archive_is_served_under_the_published_name(diag_dir):
    older = _archive(diag_dir / "oo-all-diagnostics-20261005-090000.zip")
    os.utime(older, (1, 1))
    _archive(diag_dir / ARCHIVE)
    assert d.all_diagnostics_volume_download(PUBLISHED)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volume_download("oo-diagnostics-20261005-090000.zip")
    assert exc.value.status_code == 404


@pytest.mark.parametrize("bad", ["../../etc/passwd", "oo-diagnostics-x.zip", ARCHIVE, "manifest.json", ""])
def test_no_other_name_is_reachable_through_the_archive_path(diag_dir, bad):
    _archive(diag_dir / ARCHIVE)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volume_download(bad)
    assert exc.value.status_code == 404


def test_a_part_file_is_never_taken_for_the_archive(diag_dir):
    (diag_dir / (ARCHIVE + ".part")).write_bytes(b"PK")
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 404


def test_the_published_name_drops_the_word_all_and_nothing_else():
    f = bundle_mod._published_archive_name
    assert f(Path("oo-all-diagnostics-20261006-120000.zip")) == "oo-diagnostics-20261006-120000.zip"
    assert f(Path("something-else.zip")) == "something-else.zip"

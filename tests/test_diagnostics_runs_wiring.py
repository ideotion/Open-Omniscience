"""The runs record is wired where it must be: the build worker, every download route, the bundle.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The recorder itself is tested in ``test_diagnostics_runs.py``. Here: that a build writes its
``begin`` line before it does anything else and an ``end`` line however it ends (done, cancelled, a
raised exception, a ``BaseException``), that a failed record never fails the run, that every route
that serves a zip records its sending (and none is left sending a bare ``FileResponse``), and that
the member, the route and the coverage map all carry it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.api import diagnostics as d
from src.api.diagnostics import bundle as b
from src.api.diagnostics import keyword_parts as kp
from src.monitoring import diagnostics_runs as r


class _Ctx:
    def __init__(self, stop: bool = False) -> None:
        self._stop = stop

    @property
    def stopping(self) -> bool:
        return self._stop

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        pass


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    r.reset_for_tests()
    yield tmp_path
    r.reset_for_tests()


@pytest.fixture
def tiny_build(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(b, "_all_diagnostics_members", lambda db: [("a.json", lambda: {"x": 1}), ("b.json", lambda: {"y": 2})])
    monkeypatch.setattr(b, "_all_diagnostics_dir", lambda: out)
    return out


def _runs():
    return r.diagnostics_member()["runs"]


def test_a_finished_build_is_recorded_as_done_with_its_size_and_member_outcomes(tiny_build):
    res = d._all_diagnostics_worker(_Ctx())
    (run,) = _runs()
    assert run["state"] == "done" and run["file"] == res["filename"] and run["profile"] == "full"
    assert run["bytes"] == res["bytes"] > 0
    assert run["members"].get("ok", 0) >= 2 and run["seconds"] is not None


def test_the_begin_line_is_on_disk_before_the_build_does_anything(monkeypatch):
    seen: list[list[dict]] = []

    def build(ctx, profile, fname, mode="thorough"):
        seen.append(r._read_lines())
        return {"path": "x", "bytes": 5, "members": [], "filename": fname}

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    d._all_diagnostics_worker(_Ctx(), "light")
    (lines,) = seen
    assert [(x["k"], x["ev"], x["profile"]) for x in lines] == [("run", "begin", "light")]  # begun, not yet ended
    (run,) = _runs()
    assert run["state"] == "done" and run["profile"] == "light"


def test_a_cancelled_build_is_recorded_as_cancelled(tiny_build):
    d._all_diagnostics_worker(_Ctx(stop=True))
    (run,) = _runs()
    assert run["state"] == "cancelled"


def test_a_build_that_raises_is_recorded_as_failed_with_its_reason_and_still_raises(monkeypatch):
    def build(ctx, profile, fname, mode="thorough"):
        raise RuntimeError("the disk\nexploded")

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    with pytest.raises(RuntimeError):
        d._all_diagnostics_worker(_Ctx())
    (run,) = _runs()
    assert run["state"] == "failed" and run["error"] == "RuntimeError: the disk exploded"


def test_a_failure_that_names_the_passphrase_or_the_persons_folder_is_recorded_without_either(monkeypatch, _data):
    """The failure's words enter a record that ships in the zip: the passphrase (every form) is taken
    out where the text is made, the key statement and the folders where the record keeps it."""
    from src.database import connect as _connect

    secret = "correct horse's battery"
    monkeypatch.setattr(_connect, "_passphrase", secret)
    home = str(Path.home())

    def build(ctx, profile, fname, mode="thorough"):
        raise RuntimeError(
            f"cannot open {home}/oo/data.db: PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}' and {secret!r}"
        )

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    with pytest.raises(RuntimeError):
        d._all_diagnostics_worker(_Ctx())
    text = json.dumps(r.diagnostics_member())
    for leaked in ("correct horse", "battery", home):
        assert leaked not in text, leaked
    (run,) = _runs()
    assert run["state"] == "failed" and run["error"].startswith("RuntimeError: ")


def test_a_failure_whose_text_cannot_be_checked_for_the_passphrase_is_withheld(monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setattr(secret_scrub, "_redacted", lambda text, forms: text)  # the scrub removes nothing
    monkeypatch.setenv("OO_DB_PASSPHRASE", "pa55-phrase")

    def build(ctx, profile, fname, mode="thorough"):
        raise RuntimeError("context pa55-phrase")

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    with pytest.raises(RuntimeError):
        d._all_diagnostics_worker(_Ctx())
    (run,) = _runs()
    assert "pa55-phrase" not in run["error"] and "withheld" in run["error"]


def test_a_long_failure_is_scrubbed_whole_and_cut_last_by_the_record(monkeypatch, _data):
    """The build hands the record the failure's text uncut: the passphrase, and a key statement's literal,
    that begin before the 300th character and end after it leave no part of themselves behind."""
    from src.database import connect as _connect

    secret = "correct horse's battery"
    monkeypatch.setattr(_connect, "_passphrase", secret)

    def failing(message: str):
        def build(ctx, profile, fname, mode="thorough"):
            raise RuntimeError(message)

        monkeypatch.setattr(b, "_all_diagnostics_build", build)
        with pytest.raises(RuntimeError):
            d._all_diagnostics_worker(_Ctx())
        return _runs()[0]["error"]

    lead = len("RuntimeError: ")
    # the passphrase opens 20 characters before the record's 300th, so a cut first keeps "correct horse's batt"
    across_passphrase = failing("x" * (r.ERROR_CHARS - lead - 25) + f" key {secret} then the rest of the text")
    # the literal opens 30 characters before the message's own 300th and closes after it: a cut of the MESSAGE
    # to 300 characters (what ``_all_diag_err_str`` makes) leaves ``'k3y-zzzz`` with no closing quote, which no
    # statement pattern recognises
    across_literal = failing("x" * (r.ERROR_CHARS - 44) + " PRAGMA key = 'k3y-" + "z" * 60 + "' then the rest")
    for fragment in ("correc", "horse", "battery"):
        assert fragment not in across_passphrase, fragment
    assert "k3y-" not in across_literal and "zzzz" not in across_literal
    assert len(across_passphrase) <= r.ERROR_CHARS and len(across_literal) <= r.ERROR_CHARS


def test_the_build_hands_the_record_the_failure_uncut_for_the_record_to_cut_last(monkeypatch):
    """Pinned at the seam: a text cut here would defeat the one scrub of the record, which cuts last. The failure is
    written by ``exc_line`` (``secret_scrub.exception_text`` with no limit), so it arrives scrubbed of the passphrase
    and whole."""
    long_text = "y" * 5000
    handed: dict = {}

    def keep(run, **kwargs):
        handed.update(kwargs)
        return True

    def build(ctx, profile, fname, mode="thorough"):
        raise RuntimeError(long_text)

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    monkeypatch.setattr(b._diag_runs, "end_run", keep)
    with pytest.raises(RuntimeError):
        d._all_diagnostics_worker(_Ctx())
    assert handed["error"] == "RuntimeError: " + long_text and len(handed["error"]) > r.ERROR_CHARS

    class Broken(Exception):
        def __str__(self):
            raise ValueError("no text")

    assert r.exc_line(Broken()) == "Broken: its text is withheld"


def test_a_unicode_error_that_fails_the_build_is_recorded_as_fixed_words(monkeypatch):
    """A ``UnicodeError``'s message names a character and its offset, which is a piece of a key: the record gets the class and
    fixed words (``exc_line``), not the exception's own text."""
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    def build(ctx, profile, fname, mode="thorough"):
        raise UnicodeEncodeError("ascii", "caf\u00e9", 3, 4, "ordinal not in range(128)")

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    with pytest.raises(UnicodeEncodeError):
        d._all_diagnostics_worker(_Ctx())
    (run,) = _runs()
    assert run["state"] == "failed" and UNICODE_WITHHELD in run["error"]
    assert "xe9" not in run["error"] and "position" not in run["error"]


def test_a_base_exception_ends_the_record_too_and_is_not_swallowed(monkeypatch):
    class _Killed(BaseException):
        pass

    def build(ctx, profile, fname, mode="thorough"):
        raise _Killed("stopped from outside")

    monkeypatch.setattr(b, "_all_diagnostics_build", build)
    with pytest.raises(_Killed):
        d._all_diagnostics_worker(_Ctx())
    (run,) = _runs()
    assert run["state"] == "failed" and run["error"].startswith("_Killed")


def test_a_record_that_cannot_be_written_never_fails_the_build(tiny_build, _data):
    (_data / "data").mkdir(parents=True, exist_ok=True)
    (_data / "data" / "diagnostics").write_text("a file where the folder should be", encoding="utf-8")
    res = d._all_diagnostics_worker(_Ctx())
    assert Path(res["path"]).exists() and res["bytes"] > 0


# --- every route that serves a zip records its sending ---------------------------------------------
def _send(resp):
    """Run a response through the server, as a client would, and return what it sent."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_api_route("/f", lambda: resp)
    return TestClient(app).get("/f")


def _serves():
    return r.diagnostics_member()["serves"]


def test_the_archive_download_records_its_sending(monkeypatch, tmp_path):
    archive = tmp_path / "oo-all-diagnostics-1.zip"
    archive.write_bytes(b"PK" + b"0" * 900)
    monkeypatch.setattr(b._ALL_DIAG_JOB, "status", lambda: {"state": "done", "result": {"path": str(archive), "filename": archive.name}})
    resp = d.all_diagnostics_job_download()
    assert _serves()[0]["sent_all"] is None  # begun, the last byte not yet sent
    assert _send(resp).status_code == 200
    (row,) = _serves()
    assert row["file"] == archive.name and row["bytes"] == 902 and row["sent_all"] is True


def test_the_archive_on_disk_fallback_records_its_sending(monkeypatch, tmp_path):
    archive = tmp_path / "oo-all-diagnostics-2.zip"
    archive.write_bytes(b"PK")
    monkeypatch.setattr(b._ALL_DIAG_JOB, "status", lambda: {"state": "idle", "result": None})
    monkeypatch.setattr(b, "_newest_all_diagnostics_archive", lambda: archive)
    _send(d.all_diagnostics_job_download())
    (row,) = _serves()
    assert row["file"] == archive.name and row["sent_all"] is True


def test_a_volume_download_records_its_sending(monkeypatch, tmp_path):
    from src.api import diagnostics_volumes as dvol

    out = tmp_path / "vols"
    out.mkdir()
    (out / "set-part-1.zip").write_bytes(b"PK" + b"1" * 50)
    monkeypatch.setattr(b, "_all_diagnostics_volumes_dir", lambda: out)
    monkeypatch.setattr(dvol, "load_manifest", lambda _p: {"volumes": [{"name": "set-part-1.zip"}], "manifest_files": []})
    _send(d.all_diagnostics_volume_download("set-part-1.zip"))
    (row,) = _serves()
    assert row["file"] == "set-part-1.zip" and row["sent_all"] is True


def test_a_keyword_part_download_records_its_sending(monkeypatch, tmp_path):
    root = tmp_path / "parts"
    folder = root / "oo-keyword-parts-abc123"
    folder.mkdir(parents=True)
    (folder / "part-0001.zip").write_bytes(b"PK" + b"2" * 80)
    (folder / "set.json").write_text(json.dumps({"files": [{"name": "part-0001.zip"}]}), encoding="utf-8")
    monkeypatch.setattr(kp, "_parts_root", lambda: root)
    _send(d.keyword_part_download("oo-keyword-parts-abc123", "part-0001.zip"))
    (row,) = _serves()
    assert row["file"] == "part-0001.zip" and row["bytes"] == 82 and row["sent_all"] is True


#: Every site of the diagnostics package that answers with a zip WITHOUT recording its sending, and why.
#: The runs member says the same in its ``method`` text (``test_diagnostics_runs``): a new route that
#: serves a zip is either recorded, through ``served_file_response``, or listed here AND there.
_UNRECORDED_ZIP_SITES = {
    "bundle.py": 1,    # the synchronous GET /all: it builds in the request and answers with the bytes
    "keywords.py": 1,  # the keyword log's scratch zip, deleted once sent
    "sources.py": 1,   # the temporary source-quality zip, answered with the bytes
}


def test_no_site_that_serves_a_zip_goes_unrecorded_without_being_listed():
    """Negative space, anchored to the sources (never to the shared app's routes): any module of the
    diagnostics package that names ``application/zip`` is a zip route, and each such site is one the
    record covers or one this list names. The first guard looked for a bare ``FileResponse(`` in two
    modules and so could not see a zip served as ``Response(content=...)`` or by a subclass."""
    from tests.diagnostics_source import diagnostics_parts

    parts = dict(diagnostics_parts())
    found: dict[str, int] = {}
    for name, text in sorted(parts.items()):
        # The quoted literal in either spelling (a docstring or comment names it in backticks or bare, which
        # is not a site; a constant that a response takes its media type from is one, and so is a call
        # that writes the keyword with a space or single quotes).
        count = len(re.findall(r"""["']application/zip["']""", text))
        if count:
            found[name] = count
    recorded = {"bundle.py", "keyword_parts.py"}
    for name in recorded:
        text = parts[name]
        assert "served_file_response(" in text, name
        assert "FileResponse(" not in text.replace("-> FileResponse", "").replace("served_file_response(", ""), name
    assert found == _UNRECORDED_ZIP_SITES, (
        "a diagnostics route that serves a zip must record its sending (served_file_response) or be "
        f"listed in _UNRECORDED_ZIP_SITES and in the runs member's method text; found {found}"
    )


# --- the member, the route, the map ------------------------------------------------------------------
def test_the_bundle_carries_the_runs_in_every_profile():
    names = [name for name, _fn in b._all_diagnostics_members(None)]
    assert names.count("runs.json") == 1
    assert "runs.json" not in b._LIGHT_DECLINED  # a light run keeps it: it reads a small file


def test_the_route_is_registered_and_classified():
    paths = [getattr(x, "path", "") for x in d.router.routes]
    assert "/api/diagnostics/runs" in paths
    assert b._DIAG_COVERAGE_MAP["/runs"] == "runs.json"
    report = b._diagnostics_coverage_report()
    assert report["available"] is True
    assert "/runs" not in report["unclassified"] and "runs.json" not in report["missing_bundle_members"]
    assert report["complete"] is True, report


def test_the_route_and_the_member_serve_the_same_document(tiny_build):
    d._all_diagnostics_worker(_Ctx())
    served = d.diagnostics_runs_report()
    from src.api import diagnostics_slots as slots

    member = dict(slots.members())["runs.json"]()  # the slot's own producer
    assert served["schema"] == member["schema"] == r.SCHEMA
    assert [x["id"] for x in served["runs"]] == [x["id"] for x in member["runs"]]

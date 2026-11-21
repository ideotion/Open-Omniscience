"""Row 265 (0.6 gate row A): each climate fetch leaves a trace, success or failure, and a script reads it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's real-host run of the six datasets has to be readable dataset by dataset: fetched, failed and why, or not
fetched yet. The failure goes into the unit's own fetch record (save_record, in the encrypted library), never a new store, as
one fixed token: a refusal by the person's own airplane mode is the kill switch (#14e), a robots refusal is robots. What the
Field data file must never hold is an address, a path, a unit or a GHCN station (R734/R736): the publisher's host, counts and
sums only. The read-back never prints a figure it was not given as 0.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import climate as climate_api
from src.database.models import Base
from src.ingest import (
    BlockedTarget,
    RobotsDisallowed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.airplane import AirplaneModeError
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.safety.fetcher import RedirectRefused
from src.safety.transport_watch import TransportStopped
from src.stats import climate
from src.stats.climate import DATASETS, FAILURE_REASONS, failure_reason
from src.stats.fetch import BodyTooLarge

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "climate_readback.py"
STATION = "USW00094728"
HOST_PATH = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"


def _script():
    spec = importlib.util.spec_from_file_location("oo_climate_readback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    mk = sessionmaker(bind=engine, future=True)

    @contextlib.contextmanager
    def scope():
        s = mk()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr("src.database.session.session_scope", scope)
    return mk


@pytest.fixture()
def client(maker):
    app = FastAPI()
    app.include_router(climate_api.router)
    return TestClient(app)


def _http(code: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = code
    resp.url = HOST_PATH
    return requests.HTTPError(f"{code} Client Error for url: {HOST_PATH}", response=resp)


def _chained(outer: Exception, inner: BaseException) -> Exception:
    try:
        try:
            raise inner
        except BaseException as e:
            raise outer from e
    except Exception as got:
        return got


# --- the reason tokens ------------------------------------------------------------------------ #
@pytest.mark.parametrize(
    ("exc", "token"),
    [
        (AirplaneModeError("airplane mode: refused data.giss.nasa.gov"), "kill_switch"),
        (RuntimeError(NETWORK_REFUSED), "kill_switch"),
        (_chained(requests.ConnectionError("pool"), AirplaneModeError("airplane")), "kill_switch"),
        (RobotsDisallowed(f"robots.txt disallows {HOST_PATH}"), "robots"),
        (RobotsUnavailable("robots.txt unreachable", cause="unreachable"), "robots_unreadable"),
        (RedirectRefused("too many redirects"), "redirect_refused"),
        (BlockedTarget("resolves to 10.0.0.1"), "redirect_refused"),
        (TransportStopped("protected"), "transport_stopped"),
        (BodyTooLarge("the body went past 10 bytes"), "too_large"),
        (_http(403), "http_403"),
        (_http(404), "http_404"),
        (_http(429), "http_429"),
        (_http(410), "http_4xx"),
        (_http(503), "http_5xx"),
        (requests.ConnectTimeout("timed out"), "timeout"),
        (requests.ConnectionError("Name or service not known"), "connect"),
        (ValueError("GISTEMP GLB: not the documented header"), "unreadable_answer"),
        (ValueError("GISTEMP GLB: the response is 9 characters, over the 5 the table's own shape allows"), "too_large"),
        (ValueError("USGS earthquakes: the response is 9 characters, over the 5 its declared 2 events allow"), "too_large"),
        (KeyError("x"), "other"),
    ],
)
def test_each_failure_maps_to_one_fixed_token(exc, token):
    assert token in FAILURE_REASONS
    assert failure_reason(exc) == token


def test_a_kill_switch_refusal_wins_over_whatever_wrapped_it():
    """#14e: a refusal by the person's own setting is named as such, never as the host's connection failure."""
    wrapped = _chained(requests.ConnectionError("Max retries exceeded"), RuntimeError(NETWORK_REFUSED))
    assert failure_reason(wrapped) == "kill_switch"


# --- the record: the unit's own, in the library ------------------------------------------------ #
def _ok(db, dataset="oni", param=None, figures=120, new=120, revised=0, at="2026-11-21T10:00:00+00:00"):
    climate.save_record(db, dataset, param, {"dataset": dataset, "param": param, "fetched_at": at,
                                             "requested_urls": [HOST_PATH], "figures": figures,
                                             "tally": {"new": new, "revised": revised, "unchanged": 0}, "diagnostics": {}})


def test_a_failure_joins_the_units_own_record_and_keeps_its_last_fetch(maker):
    with maker() as db:
        _ok(db, "gistemp", "GLB")
        climate.record_failure(db, "gistemp", "GLB", failure_reason(_http(404)))
        climate.record_failure(db, "nsidc", "N", f"404 for {HOST_PATH}")  # not a token: written as other
        climate.record_failure(db, "nope", None, "timeout")
        db.commit()
        rec = climate.load_record(db, "gistemp", "GLB")
        assert rec["fetched_at"] and rec["figures"] == 120, "the last successful fetch stays for the tab"
        assert set(rec["last_failure"]) == {"failed_at", "reason"} and rec["last_failure"]["reason"] == "http_404"
        assert climate.load_record(db, "nsidc", "N") == {"last_failure": {"failed_at": climate.load_record(db, "nsidc", "N")
                                                                          ["last_failure"]["failed_at"], "reason": "other"}}
        assert climate.load_record(db, "nope", None) is None


def test_a_later_success_clears_the_failure(maker):
    with maker() as db:
        climate.record_failure(db, "oni", None, "timeout")
        _ok(db)
        assert "last_failure" not in climate.load_record(db, "oni", None)


def test_outcomes_name_no_unit_and_count_stations(maker):
    with maker() as db:
        _ok(db, "ghcnd", STATION, figures=10, new=10)
        _ok(db, "ghcnd", "GME00127786", figures=5, new=2, revised=1, at="2026-11-21T11:00:00+00:00")
        climate.record_failure(db, "ghcnd", "ASN00086071", "robots")
        _ok(db, "gistemp", "GLB")
        db.commit()
        out = climate.fetch_outcomes(db)
    text = json.dumps(out)
    for leak in (STATION, "GME00127786", "ASN00086071", "GLB", "tabledata", "https://", "requested_urls", "param"):
        assert leak not in text, leak
    g = out["ghcnd"]
    assert g["unit_kind"] == "station" and g["units_offered"] is None and g["units_not_fetched_yet"] is None
    assert (g["units_fetched"], g["units_last_failed"], g["figures"], g["new"], g["revised"]) == (2, 1, 15, 12, 1)
    assert g["last_fetched_at"] == "2026-11-21T11:00:00+00:00" and g["reasons"] == {"robots": 1}
    assert g["host"] == DATASETS["ghcnd"].host and "/" not in g["host"]
    gi = out["gistemp"]
    assert gi["units_offered"] == len(DATASETS["gistemp"].params) and gi["units_not_fetched_yet"] == gi["units_offered"] - 1
    assert out["usgs"]["state"] == "not_fetched_yet" and out["usgs"]["figures"] is None and out["usgs"]["stored_rows"] is None


# --- the API ---------------------------------------------------------------------------------- #
def test_a_kill_switch_refusal_at_the_button_is_recorded_as_the_kill_switch(client, maker, monkeypatch):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    activate_kill_switch()
    try:
        r = client.post("/api/climate/fetch", json={"dataset": "ghcnd", "param": STATION, "consent": True})
    finally:
        clear_kill_switch()
    assert r.status_code == 409 and r.json()["detail"] == NETWORK_REFUSED
    with maker() as db:
        assert climate.load_record(db, "ghcnd", STATION)["last_failure"]["reason"] == "kill_switch"
    body = client.get("/api/climate/fetch-record").json()
    assert body["datasets"]["ghcnd"]["reasons"] == {"kill_switch": 1}
    assert STATION not in json.dumps(body)


def test_an_unconsented_click_or_a_running_job_records_nothing(client, maker, monkeypatch):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    activate_kill_switch()
    try:
        assert client.post("/api/climate/fetch", json={"dataset": "oni", "consent": False}).status_code == 409
        monkeypatch.setattr(climate_api._FETCH_JOB, "status", lambda: {"state": "running"})
        assert client.post("/api/climate/fetch", json={"dataset": "oni", "consent": True}).status_code == 409
    finally:
        clear_kill_switch()
    with maker() as db:
        assert climate.load_record(db, "oni", None) is None


def test_a_failing_job_records_its_token_and_still_fails(maker, monkeypatch):
    def boom(db, dataset, param, progress=None):
        raise RobotsDisallowed(f"robots.txt disallows {HOST_PATH}")

    monkeypatch.setattr(climate, "fetch_and_store", boom)

    class Ctx:
        def set_progress(self, **kw):
            pass

    with pytest.raises(RobotsDisallowed):
        climate_api._fetch_worker(Ctx(), dataset="gistemp", param="GLB")
    with maker() as db:
        assert climate.load_record(db, "gistemp", "GLB") == {"last_failure": {
            "failed_at": climate.load_record(db, "gistemp", "GLB")["last_failure"]["failed_at"], "reason": "robots"}}


def test_a_library_that_cannot_be_read_is_said_never_read_as_nothing_fetched(monkeypatch):
    @contextlib.contextmanager
    def locked():
        raise RuntimeError("locked")
        yield

    monkeypatch.setattr("src.database.session.session_scope", locked)
    app = FastAPI()
    app.include_router(climate_api.router)
    body = TestClient(app).get("/api/climate/fetch-record").json()
    assert body["measured"] is False and "datasets" not in body and body["reason"] == "library_unreadable"
    assert "were not read: the library could not be read (locked or unavailable)" in "\n".join(R.report(body))


def test_the_route_lists_every_dataset_and_stays_small(client, maker):
    with maker() as db:
        for i in range(2000):  # far more stations than anyone reads: the file stays a few kilobytes
            _ok(db, "ghcnd", f"USW{i:08d}", figures=10**6, new=10**6, revised=10**6)
        for name, ds in DATASETS.items():
            if ds.params:
                for p in ds.params:
                    climate.record_failure(db, name, p, "http_5xx")
        db.commit()
    r = client.get("/api/climate/fetch-record")
    body = r.json()
    assert body["schema"] == R.SCHEMA == climate_api.FETCH_RECORD_SCHEMA and body["measured"] is True
    assert body["datasets_listed"] == sorted(DATASETS) and sorted(body["datasets"]) == sorted(DATASETS)
    assert body["reasons"] == list(FAILURE_REASONS)
    assert len(r.content) < 20_000, len(r.content)  # the Field data limit is 200 KB
    assert not re.search(r"USW\d{8}", r.text)


def test_every_reason_token_has_words_in_the_script():
    assert set(R.REASON_WORDS) == set(FAILURE_REASONS)


def test_a_failure_only_record_shows_no_fetch_on_the_tab():
    js = (ROOT / "src" / "static" / "app-climate.js").read_text(encoding="utf-8")
    assert "const verb = (unit.last_fetch && unit.last_fetch.fetched_at) ||" in js, "a unit that only failed still offers Fetch"
    assert "if (!rec || (rec.last_failure && !rec.fetched_at)) return \"\";" in js


# --- the read-back ---------------------------------------------------------------------------- #
def _save(client, tmp_path) -> Path:
    out = tmp_path / "oo-field-20261121-1400-p8000-climate-fetches.json"
    out.write_bytes(client.get("/api/climate/fetch-record").content)
    return out


def _by(lines):
    return {ln.split(" ")[0]: ln for ln in lines}


def test_a_dataset_never_tried_reads_not_fetched_yet_with_no_figure(client, maker, tmp_path):
    with maker() as db:
        _ok(db)
        db.commit()
    lines = R.report(R.load(_save(client, tmp_path)))
    by = _by(lines)
    assert by["oni"] == (f"oni ({DATASETS['oni'].host}): 1 of 1 unit fetched, 0 not fetched yet · last fetch 2026-11-21 10:00 UTC"
                         " · 120 figures in the last fetches, 120 new, 0 revised · 0 values stored")
    for name in sorted(DATASETS):
        if name != "oni":
            assert by[name] == f"{name} ({DATASETS[name].host}): not fetched yet"
            assert not any(c.isdigit() for c in by[name].split("): ")[1])
    assert lines[-1] == f"totals: 1 fetched, 0 only failed, {len(DATASETS) - 1} not fetched yet"


def test_a_kill_switch_refusal_reads_as_the_kill_switch(client, tmp_path):
    activate_kill_switch()
    try:
        client.post("/api/climate/fetch", json={"dataset": "nsidc", "consent": True})
    finally:
        clear_kill_switch()
    by = _by(R.report(R.load(_save(client, tmp_path))))
    line = by["nsidc"]
    assert f"not fetched yet (0 of {len(DATASETS['nsidc'].params)} units)" in line
    assert "latest attempt failed for 1 unit" in line and "refused by airplane mode (the kill switch), no request sent (1)" in line
    assert "figures" not in line


def test_another_schema_is_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"schema": "oo-vertical-climate-1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected 'oo-field-climate-fetches-1'"):
        R.load(f)
    assert R.main([str(f)]) == 2


def test_a_piece_set_is_joined_and_a_missing_piece_is_named(client, maker, tmp_path):
    with maker() as db:
        climate.record_failure(db, "usgs", None, "timeout")
        db.commit()
    data = _save(client, tmp_path).read_bytes()
    p1 = tmp_path / "oo-field-x-climate-fetches-part-001-of-002.json"
    p2 = tmp_path / "oo-field-x-climate-fetches-part-002-of-002.json"
    p1.write_bytes(data[: len(data) // 2])
    p2.write_bytes(data[len(data) // 2:])
    assert R.load(p2)["datasets"]["usgs"]["reasons"] == {"timeout": 1}
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)

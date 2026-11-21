"""Row 265 (0.6 gate row A): each climate fetch leaves a trace, success or failure, and a script reads it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's real-host run of the six datasets has to be readable dataset by dataset: fetched, failed and why, or never
tried. What the record must never hold is an address, a host path, a unit or a station (R734/R736), or a server's own words:
a failure is one fixed token. A refusal by the person's own airplane mode is named as the kill switch (#14e), a robots
refusal as robots. The read-back never prints a figure it was not given as 0.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import climate as climate_api
from src.ingest import (
    BlockedTarget,
    RobotsDisallowed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.airplane import AirplaneModeError
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.monitoring import kpi as K
from src.safety.fetcher import RedirectRefused
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
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    return tmp_path


@pytest.fixture()
def client(isolated):
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
        (BodyTooLarge("the body went past 10 bytes"), "too_large"),
        (_http(403), "http_403"),
        (_http(404), "http_404"),
        (_http(429), "http_429"),
        (_http(410), "http_4xx"),
        (_http(503), "http_5xx"),
        (requests.ConnectTimeout("timed out"), "timeout"),
        (requests.ConnectionError("Name or service not known"), "connect"),
        (ValueError("GISTEMP GLB: not the documented header"), "unreadable_answer"),
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


# --- the record ------------------------------------------------------------------------------- #
def _file(tmp: Path) -> str:
    return (tmp / "vertical-climate.json").read_text(encoding="utf-8")


def test_a_failure_is_kept_as_a_token_and_time_only(isolated):
    K.record_climate_failure("ghcnd", failure_reason(_http(404)))
    raw = _file(isolated)
    rec = json.loads(raw)
    assert rec["failures"]["ghcnd"]["reason"] == "http_404"
    assert set(rec["failures"]["ghcnd"]) == {"failed_at", "reason"}
    for leak in (STATION, "nasa.gov", "http", "Client Error", "/gistemp/"):
        assert leak not in raw.replace('"http_404"', ""), leak


def test_a_token_outside_the_list_and_an_unknown_dataset_are_never_written(isolated):
    K.record_climate_failure("oni", f"404 for {HOST_PATH}")
    assert json.loads(_file(isolated))["failures"]["oni"]["reason"] == "other"
    assert K.record_climate_failure("nope", "timeout") is None
    assert "nope" not in _file(isolated)


def test_a_success_and_a_failure_keep_each_other(isolated):
    K.record_climate_failure("oni", "timeout")
    K.record_climate_fetch({"dataset": "oni", "param": None, "fetched_at": "2026-11-21T10:00:00+00:00", "figures": 5,
                            "tally": {"new": 5, "revised": 0}})
    K.record_climate_failure("gistemp", "robots")
    rec = K.read_climate_fetches()
    assert rec["datasets"]["oni"]["figures"] == 5
    assert rec["failures"]["oni"]["reason"] == "timeout" and rec["failures"]["gistemp"]["reason"] == "robots"


def test_a_failures_only_record_is_still_not_measured_for_k13(isolated, monkeypatch):
    """K13 counts first slices; a failure is not one, so the board's reading does not move."""
    K.record_climate_failure("oni", "kill_switch")
    assert K._climate_block()["state"] == "not-measured"


# --- the API ---------------------------------------------------------------------------------- #
def test_a_kill_switch_refusal_at_the_button_is_recorded_as_the_kill_switch(client, monkeypatch, isolated):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    activate_kill_switch()
    try:
        r = client.post("/api/climate/fetch", json={"dataset": "ghcnd", "param": STATION, "consent": True})
    finally:
        clear_kill_switch()
    assert r.status_code == 409
    body = client.get("/api/climate/fetch-record").json()
    assert body["failures"]["ghcnd"]["reason"] == "kill_switch"
    assert STATION not in _file(isolated) and STATION not in json.dumps(body)


def test_a_failing_job_records_its_token_and_still_fails(isolated, monkeypatch):
    @contextlib.contextmanager
    def scope():
        yield None

    def boom(db, dataset, param, progress=None):
        raise RobotsDisallowed(f"robots.txt disallows {HOST_PATH}")

    monkeypatch.setattr("src.database.session.session_scope", scope)
    monkeypatch.setattr(climate_api, "fetch_and_store", boom, raising=False)
    monkeypatch.setattr("src.stats.climate.fetch_and_store", boom)

    class Ctx:
        def set_progress(self, **kw):
            pass

    with pytest.raises(RobotsDisallowed):
        climate_api._fetch_worker(Ctx(), dataset="gistemp", param="GLB")
    rec = K.read_climate_fetches()
    assert rec["failures"]["gistemp"]["reason"] == "robots"
    assert "nasa.gov" not in _file(isolated)


def test_the_route_lists_every_dataset_and_stays_small(client, isolated):
    for name in DATASETS:
        K.record_climate_failure(name, "http_5xx")
        K.record_climate_fetch({"dataset": name, "fetched_at": "2026-11-21T10:00:00+00:00", "figures": 10**6,
                                "tally": {"new": 10**6, "revised": 10**6}})
    r = client.get("/api/climate/fetch-record")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == R.SCHEMA == climate_api.FETCH_RECORD_SCHEMA
    assert body["datasets_listed"] == sorted(DATASETS)
    assert body["reasons"] == list(FAILURE_REASONS)
    assert len(r.content) < 200_000 / 10  # the Field data limit, with an order of magnitude to spare


def test_every_reason_token_has_words_in_the_script():
    assert set(R.REASON_WORDS) == set(FAILURE_REASONS)


# --- the read-back ---------------------------------------------------------------------------- #
def _save(client, tmp_path) -> Path:
    out = tmp_path / "oo-field-20261121-1400-p8000-climate-fetches.json"
    out.write_bytes(client.get("/api/climate/fetch-record").content)
    return out


def test_a_dataset_never_tried_reads_never_tried_with_no_figure(client, tmp_path):
    K.record_climate_fetch({"dataset": "oni", "fetched_at": "2026-11-21T10:00:00+00:00", "figures": 120,
                            "tally": {"new": 120, "revised": 0}})
    lines = R.report(R.load(_save(client, tmp_path)))
    by = {ln.split(":")[0]: ln for ln in lines}
    assert by["oni"] == "oni: fetched 2026-11-21 10:00 UTC: 120 figures, 120 new, 0 revised"
    for name in sorted(DATASETS):
        if name != "oni":
            assert by[name] == f"{name}: never tried"
    assert lines[-1] == f"totals: 1 fetched at least once, 0 only failed, {len(DATASETS) - 1} never tried"


def test_a_kill_switch_refusal_reads_as_the_kill_switch(client, tmp_path):
    activate_kill_switch()
    try:
        client.post("/api/climate/fetch", json={"dataset": "nsidc", "consent": True})
    finally:
        clear_kill_switch()
    text = "\n".join(R.report(R.load(_save(client, tmp_path))))
    assert "nsidc: failed " in text and "refused by airplane mode (the kill switch), no request sent" in text
    assert "0 figures" not in text


def test_the_later_of_a_fetch_and_a_failure_leads():
    doc = {"schema": R.SCHEMA, "recorded_at": "2026-11-21T12:00:00+00:00", "datasets_listed": ["oni", "owid"],
           "fetches": {"oni": {"fetched_at": "2026-11-21T10:00:00+00:00", "figures": 3, "new": 0, "revised": 0},
                       "owid": {"fetched_at": "2026-11-21T09:00:00+00:00", "figures": None}},
           "failures": {"oni": {"failed_at": "2026-11-21T11:00:00+00:00", "reason": "http_429"},
                        "owid": {"failed_at": "2026-11-21T08:00:00+00:00", "reason": "connect"}}}
    by = {ln.split(":")[0]: ln for ln in R.report(doc)}
    assert by["oni"].startswith("oni: failed 2026-11-21 11:00 UTC: the host answered 429") and "earlier fetched" in by["oni"]
    assert by["owid"].startswith("owid: fetched 2026-11-21 09:00 UTC: figures not recorded") and "earlier failed" in by["owid"]


def test_another_schema_is_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"schema": "oo-vertical-climate-1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected 'oo-field-climate-fetches-1'"):
        R.load(f)
    assert R.main([str(f)]) == 2


def test_a_piece_set_is_joined_and_a_missing_piece_is_named(client, tmp_path):
    K.record_climate_failure("usgs", "timeout")
    data = _save(client, tmp_path).read_bytes()
    p1 = tmp_path / "oo-field-x-climate-fetches-part-001-of-002.json"
    p2 = tmp_path / "oo-field-x-climate-fetches-part-002-of-002.json"
    p1.write_bytes(data[: len(data) // 2])
    p2.write_bytes(data[len(data) // 2:])
    assert R.load(p2)["failures"]["usgs"]["reason"] == "timeout"
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)

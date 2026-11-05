"""The OSM daily-update job: the consent and kill-switch gates, one worker, real progress, how a run ends, and the task-manager row
(v0.6.0 B1, S06-01 S1, the job and consent layer).

Expected values are written out from the fixtures (the sequence numbers and the two change files), never computed by the job. No test
here opens a socket: the mirror is the apply tests' own stand-in, handed in through the job's ``source_for`` seam.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.osm import apply as A
from src.osm import ingest
from src.osm import update_job as U
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, Mirror, _extract, _osc
from tests.wallclock_helpers import HANG_GUARD_S, wait_until

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

DAY2 = _osc('<create><node id="40" version="1" timestamp="2025-01-12T00:00:00Z" lat="0.12" lon="0.12"><tag k="amenity" v="bench"/></node></create>')


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    U._reset_for_tests()
    yield path
    U.wait_idle(HANG_GUARD_S)
    U._reset_for_tests()


def _record(alpha3, alpha2, **kw):
    """A job record as the module keeps one, for tests that show how the task manager reads each state."""
    base = {"alpha3": alpha3, "alpha2": alpha2, "state": "queued", "queued_at": "2025-01-01T00:00:00+00:00", "started_at": None,
            "finished_at": None, "applied": 0, "owed": None, "outcome": None, "reason": None}
    return {**base, **kw}


def _mirror_for(mirror):
    seen = []

    def source_for(region):
        seen.append(region)
        return mirror

    source_for.seen = seen
    return source_for


def _off():
    return False


def _on():
    return True


def test_a_request_without_the_consent_is_refused_and_creates_no_job(cut):
    built = []
    with pytest.raises(U.UpdateRefused) as err:
        U.request_update("ZZ", consent=False, source_for=lambda r: built.append(r), kill_switch=_off)
    assert err.value.kind == "consent" and "online consent" in str(err.value)
    assert U.jobs() == [] and built == []


def test_the_kill_switch_is_a_named_refusal_not_a_job_that_starts_and_fails(cut):
    built = []
    with pytest.raises(U.UpdateRefused) as err:
        U.request_update("ZZ", consent=True, source_for=lambda r: built.append(r), kill_switch=_on)
    assert err.value.kind == "kill-switch" and str(err.value) == A.KILL_SWITCH_TEXT
    assert U.jobs() == [] and built == []


def test_a_code_that_is_not_a_country_is_a_value_error_before_any_gate(cut):
    with pytest.raises(ValueError):
        U.request_update("not a country", consent=True, kill_switch=_off)
    assert U.jobs() == []


def test_two_files_are_applied_by_the_worker_and_the_job_says_how_it_went(cut):
    mirror = Mirror(102, {101: DAY1, 102: DAY2})
    source_for = _mirror_for(mirror)
    queued = U.request_update("ZZ", consent=True, source_for=source_for, kill_switch=_off)
    assert queued["started"] is True and queued["alpha3"] == "ZZZ" and queued["alpha2"] == "ZZ" and "_args" not in queued
    assert U.wait_idle(HANG_GUARD_S)
    (job,) = U.jobs()
    assert (job["state"], job["outcome"], job["applied"], job["owed"]) == ("done", "applied", 2, 2)
    assert (job["from_sequence"], job["to_sequence"], job["owed_remaining"]) == (100, 102, None)
    assert source_for.seen == ["europe"], "the region comes from the cut's own extract name, not from the caller"
    assert job["started_at"] and job["finished_at"] and job["queued_at"]


def test_a_country_with_no_cut_is_queued_and_ends_not_ready_by_name(cut):
    U._reset_for_tests()
    U.request_update("FR", consent=True, source_for=_mirror_for(Mirror(1, {})), kill_switch=_off)
    assert U.wait_idle(HANG_GUARD_S)
    (job,) = U.jobs()
    assert job["state"] == "done" and job["outcome"] == "not-ready" and "finished cut" in job["reason"]


def test_a_second_request_for_a_country_already_running_starts_nothing_new(cut):
    gate = threading.Event()
    mirror = Mirror(101, {101: DAY1})
    mirror.after_each = lambda seq: gate.wait(3 * HANG_GUARD_S)
    try:
        U.request_update("ZZ", consent=True, source_for=_mirror_for(mirror), kill_switch=_off)
        assert wait_until(lambda: any(c[0] == "diff" for c in mirror.calls))
        again = U.request_update("ZZ", consent=True, source_for=_mirror_for(mirror), kill_switch=_off)
        assert again["started"] is False and again["state"] == "running"
        assert len(U.jobs()) == 1
    finally:
        gate.set()
    assert U.wait_idle(HANG_GUARD_S)


def test_one_worker_runs_one_country_at_a_time_in_the_order_asked(cut):
    started, release, order = [], threading.Event(), []

    def runner(alpha3, **kw):
        started.append(alpha3)
        order.append(("start", alpha3))
        if alpha3 == "ZZZ":
            release.wait(3 * HANG_GUARD_S)
        order.append(("end", alpha3))
        return SimpleNamespace(outcome="current", reason="x", from_sequence=1, to_sequence=1, owed_remaining=None)

    try:
        U.request_update("ZZ", consent=True, kill_switch=_off, run=runner)
        assert wait_until(lambda: started == ["ZZZ"])
        U.request_update("FR", consent=True, kill_switch=_off, run=runner)
        states = {j["alpha3"]: j["state"] for j in U.jobs()}
        assert states == {"ZZZ": "running", "FRA": "queued"} and [j["alpha3"] for j in U.jobs()] == ["ZZZ", "FRA"]
        assert started == ["ZZZ"], "the second country has not started while the first holds the worker"
    finally:
        release.set()
    assert U.wait_idle(HANG_GUARD_S)
    assert order == [("start", "ZZZ"), ("end", "ZZZ"), ("start", "FRA"), ("end", "FRA")]


def test_a_run_that_raises_ends_failed_with_the_class_and_none_of_its_words(cut):
    def runner(alpha3, **kw):
        raise RuntimeError("tag name=Secret Clinic Street 5")

    U.request_update("ZZ", consent=True, kill_switch=_off, run=runner)
    assert U.wait_idle(HANG_GUARD_S)
    (job,) = U.jobs()
    assert job["outcome"] == "failed" and "RuntimeError" in job["reason"] and "Secret" not in repr(job)


def test_the_worker_survives_a_failed_run_and_takes_the_next_job(cut):
    calls = []

    def runner(alpha3, **kw):
        calls.append(alpha3)
        if alpha3 == "ZZZ":
            raise ValueError("boom")
        return SimpleNamespace(outcome="current", reason=None, from_sequence=1, to_sequence=1, owed_remaining=None)

    U.request_update("ZZ", consent=True, kill_switch=_off, run=runner)
    U.request_update("FR", consent=True, kill_switch=_off, run=runner)
    assert U.wait_idle(HANG_GUARD_S)
    assert calls == ["ZZZ", "FRA"] and {j["alpha3"]: j["outcome"] for j in U.jobs()} == {"ZZZ": "failed", "FRA": "current"}


def test_a_worker_that_finished_does_not_strand_the_next_request(cut):
    U.request_update("ZZ", consent=True, source_for=_mirror_for(Mirror(100, {})), kill_switch=_off)
    assert U.wait_idle(HANG_GUARD_S)
    U.request_update("FR", consent=True, source_for=_mirror_for(Mirror(100, {})), kill_switch=_off)
    assert U.wait_idle(HANG_GUARD_S)
    assert {j["state"] for j in U.jobs()} == {"done"} and len(U.jobs()) == 2


def test_progress_is_reported_once_the_files_owed_are_known_and_after_each_file(cut, osm_lane_dir):
    seen = []
    A.update_country(
        "ZZ", Mirror(102, {101: DAY1, 102: DAY2}), workdir=osm_lane_dir / "w", kill_switch=_off, on_progress=lambda done, owed: seen.append((done, owed))
    )
    assert seen == [(0, 2), (1, 2), (2, 2)]


def test_a_progress_callback_that_raises_never_ends_the_update(cut, osm_lane_dir):
    def bad(done, owed):
        raise RuntimeError("display broke")

    report = A.update_country("ZZ", Mirror(102, {101: DAY1, 102: DAY2}), workdir=osm_lane_dir / "w", kill_switch=_off, on_progress=bad)
    assert report.outcome == "applied" and report.to_sequence == 102


def test_update_country_takes_exactly_one_source(cut, osm_lane_dir):
    with pytest.raises(TypeError):
        A.update_country("ZZ", workdir=osm_lane_dir / "w")
    with pytest.raises(TypeError):
        A.update_country("ZZ", Mirror(1, {}), source_for=lambda r: Mirror(1, {}), workdir=osm_lane_dir / "w")


# ---- the HTTP face and the task-manager row ---------------------------------------------------------------------------------------- #


@pytest.fixture
def client(cut, monkeypatch):
    from src.api.main import app

    monkeypatch.setattr(U, "_default_source_for", _mirror_for(Mirror(102, {101: DAY1, 102: DAY2})))
    with TestClient(app) as c:
        yield c


def test_the_route_refuses_without_the_consent_and_under_the_kill_switch(client, monkeypatch):
    r = client.post("/api/osm/countries/ZZ/update", json={})
    assert r.status_code == 400 and "online consent" in r.json()["detail"]
    import src.ingest as ingest_pkg

    monkeypatch.setattr(ingest_pkg, "kill_switch_active", _on)
    r = client.post("/api/osm/countries/ZZ/update", json={"consent": True})
    assert r.status_code == 409 and r.json()["detail"] == A.KILL_SWITCH_TEXT
    assert client.get("/api/osm/updates").json() == {"jobs": []}


def test_the_route_rejects_a_code_that_is_not_a_country(client):
    assert client.post("/api/osm/countries/not-a-country/update", json={"consent": True}).status_code == 400


def test_the_route_queues_the_job_and_the_task_manager_lists_it_with_how_it_ended(client, monkeypatch):
    import src.ingest as ingest_pkg

    monkeypatch.setattr(ingest_pkg, "kill_switch_active", _off)
    r = client.post("/api/osm/countries/ZZ/update", json={"consent": True})
    assert r.status_code == 200 and r.json()["started"] is True
    assert U.wait_idle(HANG_GUARD_S)
    row = next(j for j in client.get("/api/jobs").json()["jobs"] if j["kind"] == "osm-update")
    assert row["id"] == "osm-update:ZZZ" and row["state"] == "done" and row["actions"] == []
    assert row["progress"] == {"done": 2, "total": 2, "unit": "files"}
    assert row["detail"] == "Updated to the newest daily change file."
    assert row["label_i18n"] == "Updating {country} with the daily map files" and row["label_vars"] == {"country": row["label"].split(" ", 1)[1].rsplit(" with", 1)[0]}
    assert "rate" not in row and "eta_seconds" not in row, "no rate and no ETA: the size of a change file is read when it is fetched"
    assert client.get("/api/osm/updates").json()["jobs"][0]["outcome"] == "applied"


@pytest.mark.parametrize(
    ("outcome", "state"),
    [("applied", "done"), ("current", "done"), ("rebaseline_needed", "failed"), ("refused", "failed"), ("unavailable", "failed"), ("failed", "failed"),
     ("not-ready", "failed"), ("stopped", "failed"), ("superseded", "failed"), ("mirror-unreadable", "failed")],
)
def test_every_outcome_has_a_state_and_a_fixed_sentence(client, outcome, state):
    from src.api import jobs as J

    U._JOBS["ZZZ"] = _record("ZZZ", "ZZ", state="done", finished_at="2025-01-02T00:00:00+00:00", outcome=outcome, reason="free text from the run")
    (row,) = J._osm_update_jobs()
    assert row["state"] == state and row["detail"] == U.OUTCOME_SENTENCES[outcome] and "free text" not in repr(row)


def test_every_outcome_the_apply_module_can_give_has_a_sentence():

    assert set(A.OUTCOMES) <= set(U.OUTCOME_SENTENCES), sorted(set(A.OUTCOMES) - set(U.OUTCOME_SENTENCES))


def test_a_queued_and_a_running_job_show_their_state_without_a_detail_line(cut):
    from src.api import jobs as J

    U._JOBS["ZZZ"] = _record("ZZZ", "ZZ", state="running", applied=3, owed=9)
    U._JOBS["FRA"] = _record("FRA", "FR")
    U._QUEUE.append("FRA")
    rows = {r["id"]: r for r in J._osm_update_jobs()}
    assert rows["osm-update:ZZZ"]["state"] == "running" and rows["osm-update:ZZZ"]["progress"] == {"done": 3, "total": 9, "unit": "files"}
    assert rows["osm-update:FRA"]["state"] == "queued" and rows["osm-update:FRA"]["progress"] is None
    assert "detail" not in rows["osm-update:ZZZ"] and "detail" not in rows["osm-update:FRA"]

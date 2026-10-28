"""A Stop on the LAST Wikidata batch is the switch's, not that batch's refusal (R337; the lesson of R313/R320: a refusal on the last request is missed by an
error path that only the NEXT loop turn would have read).

``fetch_items`` checked the kill switch at the top of each batch, so a Stop during batch N was seen at batch N+1. On the last batch there is no N+1: the failure
was counted as ``refused``, the run ended ``done`` and the view showed a refused count with no airplane note. The failed batch now reads the switch itself.
A Stop is not an outcome (R320): no new tally key, the batch is not counted as refused, and it stays pending.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.ring_loader import RateGate
from src.database.models import Base
from src.entities import items as IT
from src.entities.wikidata_items import BATCH_MAX
from src.ingest import activate_kill_switch, clear_kill_switch


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


@pytest.fixture()
def factory():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)

    @contextmanager
    def _f():
        s = Sess()
        try:
            yield s
        finally:
            s.close()

    yield _f
    eng.dispose()


def _ids(url: str) -> list[str]:
    return url.split("ids=")[1].split("&")[0].split("%7C")


def _answer(url: str) -> dict:
    return {"entities": {q: {"id": q, "missing": ""} for q in _ids(url)}}


def _run(factory, getter, n_batches: int = 2) -> dict:
    clock = _Clock()
    qids = [f"Q{i}" for i in range(1, BATCH_MAX * n_batches + 1)]
    try:
        return IT.fetch_items(
            qids, session_factory=factory, get=getter, gate=RateGate(clock=clock, sleep=clock.sleep)
        )
    finally:
        clear_kill_switch()


def test_a_stop_on_the_last_batch_is_named_and_the_batch_stays_pending(factory):
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        if (
            calls["n"] == 2
        ):  # the LAST batch: the switch engages inside the request, the error is the raw one
            activate_kill_switch()
            raise ConnectionError(
                "HTTPSConnectionPool(host='www.wikidata.org', port=443): Max retries exceeded (airplane mode is engaged)"
            )
        return _answer(url)

    out = _run(factory, getter)
    assert out["stopped_by_airplane_mode"] is True
    assert out["refused"] == 0, "a Stop is not this batch's refusal"
    assert out["pending"] == BATCH_MAX and out["missing_on_wikidata"] == BATCH_MAX
    assert out["requested"] == out["missing_on_wikidata"] + out["pending"], (
        "the counts still add up to what was asked"
    )


def test_a_stop_on_an_earlier_batch_stops_the_run_at_that_batch(factory):
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        activate_kill_switch()
        raise OSError("connection cut")

    out = _run(factory, getter, n_batches=3)
    assert calls["n"] == 1, "the run does not go on asking after the switch engaged"
    assert (
        out["stopped_by_airplane_mode"] is True
        and out["refused"] == 0
        and out["pending"] == 3 * BATCH_MAX
    )


def test_the_control_an_earlier_refusal_then_a_good_last_batch_is_not_an_airplane_stop(factory):
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("boom")  # an ordinary failure, switch clear
        return _answer(url)

    out = _run(factory, getter)
    assert out["stopped_by_airplane_mode"] is False
    assert (
        out["refused"] == BATCH_MAX
        and out["missing_on_wikidata"] == BATCH_MAX
        and out["pending"] == 0
    )


def test_the_control_an_ordinary_failure_on_the_last_batch_is_still_that_batchs_refusal(factory):
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("boom")
        return _answer(url)

    out = _run(factory, getter)
    assert (
        out["stopped_by_airplane_mode"] is False
        and out["refused"] == BATCH_MAX
        and out["pending"] == 0
    )

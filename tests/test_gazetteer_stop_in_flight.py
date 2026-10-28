"""A Stop that lands inside a gazetteer Wikidata request is the switch's, not the batch's refusal (R353 item 2; the class of R320 and R337).

``_reraise_refusal`` names only the refusals the guarded path raises BEFORE a request (``NetworkBlocked``, ``TransportUnavailable``). A Stop inside the request
arrives as the raw transport error, so the failed batch was counted ``refused`` and fed ``refused_in_a_row``. The next turn of the loop would have read the
switch, but (a) on the last batch there is no next turn, and (b) when the cut batch was the third consecutive refusal the run ended as ``gave_up_after_refusals``
before it got there. The decision now reads the switch after the failed request.
"""

from __future__ import annotations

from src.analytics.ring_loader import RateGate
from src.entities import gazetteer_build as G

# The shape a Stop inside a proxied request really takes: requests' wrapper around the socket guard's error.
RAW_STOP = "request error for https://www.wikidata.org/w/api.php: ('Connection aborted.', AirplaneModeError('network kill switch engaged'))"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def _gate(clock: _Clock) -> RateGate:
    return RateGate(clock=clock, sleep=clock.sleep)


def _qids(batches: int) -> list[str]:
    return [f"Q{n}" for n in range(1, batches * G.BATCH_MAX + 1)]


def _ok(url: str) -> G.GetResult:
    ids = url.split("ids=")[1].split("&")[0].split("%7C")
    ent = {
        q: {"type": "item", "id": q, "labels": {"en": {"language": "en", "value": q}}} for q in ids
    }
    return G.GetResult(200, {"entities": ent})


def _run(qids, getter, switch):
    clock = _Clock()
    return G.fetch_wikidata(
        qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: switch["on"]
    )


def test_a_stop_inside_the_last_request_is_not_counted_as_that_batch_s_refusal():
    switch = {"on": False}

    def getter(url):
        switch["on"] = (
            True  # the Stop lands while this, the only (so the last) request is in flight
        )
        raise RuntimeError(RAW_STOP)

    items, rep = _run(_qids(1), getter, switch)
    assert rep["stopped_by_airplane_mode"] is True
    assert rep["refused"] == 0, "the Stop is not the server's refusal"
    assert rep["not_asked"] == rep["asked"] and rep["gave_up_after_refusals"] is False
    assert items == {}


def test_a_stop_inside_the_third_refused_batch_does_not_end_the_run_as_gave_up():
    switch = {"on": False}
    calls: list[str] = []

    def getter(url):
        calls.append(url)
        if len(calls) == G.CONSECUTIVE_REFUSED_MAX:
            switch["on"] = True
            raise RuntimeError(RAW_STOP)
        return G.GetResult(404, None)  # a real refusal by the server

    _items, rep = _run(_qids(5), getter, switch)
    assert len(calls) == G.CONSECUTIVE_REFUSED_MAX
    assert rep["stopped_by_airplane_mode"] is True and rep["gave_up_after_refusals"] is False
    assert rep["refused"] == G.BATCH_MAX * (G.CONSECUTIVE_REFUSED_MAX - 1), (
        "only the two batches the server really refused"
    )
    assert (
        rep["asked"] == rep["ok"] + rep["refused"] + rep["missing_on_wikidata"] + rep["not_asked"]
    )


def test_an_ordinary_transport_failure_with_the_switch_clear_is_still_a_refused_batch():
    switch = {"on": False}
    calls: list[str] = []

    def getter(url):
        calls.append(url)
        raise RuntimeError("Connection reset by peer")

    _items, rep = _run(_qids(5), getter, switch)
    assert rep["stopped_by_airplane_mode"] is False
    assert (
        rep["gave_up_after_refusals"] is True
        and rep["refused"] == G.BATCH_MAX * G.CONSECUTIVE_REFUSED_MAX
    )

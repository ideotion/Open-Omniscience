"""Field test 2026-11-14 row 72: the pageview top-up must not ask for an unpublished day every drain.

The service aggregates a day some time after it ends. Asked for yesterday before that, it
answers 404, and OOS-1 logged 114 such warnings because every drain asked again. A 404 for
the due day is now recorded as "not published yet" and asked again after a wait; any other
failure still raises, so the runner still reports it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.wiki import pageviews, service


class _HTTPError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"{status} error")
        self.response = SimpleNamespace(status_code=status)


def _not_published():
    return pageviews.NotPublishedYet("en day")


@pytest.fixture
def store(monkeypatch):
    kv: dict = {}
    import src.config.kv_store as kv_store

    monkeypatch.setattr(kv_store, "kv_get_json", lambda key: kv.get(key))
    monkeypatch.setattr(kv_store, "kv_set_json", lambda key, value: kv.__setitem__(key, value))
    monkeypatch.setattr(service, "_editions", lambda: ["en"])
    return kv


def _fetcher(monkeypatch, outcomes):
    calls: list = []

    def fake(session, edition, day, **_):
        calls.append((edition, day))
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(pageviews, "fetch_top", fake)
    return calls


def test_404_is_not_published_yet_and_waits(store, monkeypatch, caplog):
    calls = _fetcher(monkeypatch, [_not_published()])
    client = SimpleNamespace(session=object())
    with caplog.at_level(logging.DEBUG, logger="wiki.service"):
        assert service._refresh_one_pageview_top(client) is None
        # The next drain does not ask again: the wait has not passed.
        assert service._refresh_one_pageview_top(client) is None
    assert len(calls) == 1
    blob = store[next(iter(store))]
    want = pageviews.due_day(datetime.now(UTC))
    assert blob["waiting"]["day"] == want.isoformat()
    assert "day" not in blob, "a 404 must never stamp the day as fetched"
    infos = [r for r in caplog.records if "not published yet" in r.getMessage()]
    assert len(infos) == 1 and infos[0].levelno == logging.INFO
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_404_keeps_the_list_already_held(store, monkeypatch):
    from src.wiki.hotset import pageview_kv_key

    old = {"day": "2000-01-01", "titles": ["A"], "rows": [{"title": "A", "rank": 1, "views": 5}], "n": 1}
    store[pageview_kv_key("en")] = dict(old)
    _fetcher(monkeypatch, [_not_published()])
    service._refresh_one_pageview_top(SimpleNamespace(session=object()))
    blob = store[pageview_kv_key("en")]
    assert {k: blob[k] for k in old} == old


def test_asks_again_after_the_wait_and_clears_it(store, monkeypatch):
    from src.wiki.hotset import pageview_kv_key

    want = pageviews.due_day(datetime.now(UTC))
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    store[pageview_kv_key("en")] = {"waiting": {"day": want.isoformat(), "until": past}}
    calls = _fetcher(monkeypatch, [[{"title": "Hello", "rank": 1, "views": 9}]])
    assert service._refresh_one_pageview_top(SimpleNamespace(session=object())) == "en"
    assert len(calls) == 1
    blob = store[pageview_kv_key("en")]
    assert blob["day"] == want.isoformat() and "waiting" not in blob


def test_a_wait_for_another_day_does_not_block_a_new_day(store, monkeypatch):
    from src.wiki.hotset import pageview_kv_key

    future = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    store[pageview_kv_key("en")] = {"waiting": {"day": "2000-01-01", "until": future}}
    calls = _fetcher(monkeypatch, [[]])
    service._refresh_one_pageview_top(SimpleNamespace(session=object()))
    assert len(calls) == 1


@pytest.mark.parametrize("exc", [_HTTPError(404), _HTTPError(500), _HTTPError(403), TimeoutError("slow"), OSError("airplane")])
def test_other_failures_still_raise(store, monkeypatch, exc):
    _fetcher(monkeypatch, [exc])
    with pytest.raises(type(exc)):
        service._refresh_one_pageview_top(SimpleNamespace(session=object()))
    assert not any("waiting" in (v or {}) for v in store.values())


def test_waiting_until_ignores_unreadable_records():
    want = datetime(2026, 11, 15).date()
    assert pageviews.waiting_until(None, want) is None
    assert pageviews.waiting_until({"waiting": "x"}, want) is None
    assert pageviews.waiting_until({"waiting": {"day": "2026-11-15", "until": "nope"}}, want) is None
    got = pageviews.waiting_until({"waiting": {"day": "2026-11-15", "until": "2026-11-16T01:00:00+00:00"}}, want)
    assert got == datetime(2026, 11, 16, 1, tzinfo=UTC)


class _Response:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _HTTPError(self.status_code)

    def json(self) -> dict:
        return {"items": [{"articles": [{"article": "A_b", "rank": 1, "views": 3}]}]}


@pytest.mark.parametrize(("status", "raised"), [(404, pageviews.NotPublishedYet), (500, _HTTPError), (403, _HTTPError)])
def test_fetch_top_names_only_a_404_as_not_published(status, raised):
    session = SimpleNamespace(get=lambda url, timeout: _Response(status))
    with pytest.raises(raised):
        pageviews.fetch_top(session, "en", datetime(2026, 11, 15).date())


def test_fetch_top_still_parses_a_200():
    session = SimpleNamespace(get=lambda url, timeout: _Response(200))
    assert pageviews.fetch_top(session, "en", datetime(2026, 11, 15).date()) == [{"title": "A b", "rank": 1, "views": 3}]

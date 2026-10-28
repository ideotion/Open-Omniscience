"""A Stop is never a feed's failure in the calendar auto-import (R353 item 1; the shape of R320 and of the D2 defect fixed in #1584).

``auto_import_due_feeds`` filed every exception as the feed's own: ``failed += 1`` and ``state[fid] = now``. The stamp means "this feed was checked", so a feed
the person's Stop cut was skipped for ``min_interval_hours`` without ever being asked, and every feed after it in the batch went the same way. A Stop landing
inside the request arrives as the raw requests error (no sentence match recognises it, R298), so the decision reads the switch after the failed check.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.events import feeds as F
from src.ingest import activate_kill_switch, clear_kill_switch

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:x1\r\nDTSTART;VALUE=DATE:20260714\r\nSUMMARY:Bastille Day\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# The shape a Stop inside a proxied request really takes: requests' wrapper around the socket guard's error, nowhere near our refusal sentence at the start.
RAW_STOP = "request error for https://example.test/cal.ics: ('Connection aborted.', AirplaneModeError('network kill switch engaged'))"


@dataclass
class _Result:
    content: str


class _Fetcher:
    """Answers ``ics`` for the first ``good`` calls; the next call engages the Stop and fails as the transport does (when ``stop_at`` is set)."""

    def __init__(self, *, stop_at: int | None = None, fail: Exception | None = None):
        self.urls: list[str] = []
        self.stop_at = stop_at
        self.fail = fail

    def fetch(self, url, *, require_html=True):
        self.urls.append(url)
        if self.stop_at is not None and len(self.urls) == self.stop_at:
            activate_kill_switch()
            raise RuntimeError(RAW_STOP)
        if self.fail is not None:
            raise self.fail
        return _Result(content=ICS)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    yield
    clear_kill_switch()


def test_a_stop_inside_an_import_is_not_a_failure_and_is_not_stamped():
    f = _Fetcher(stop_at=3)
    r = F.auto_import_due_feeds(f, batch=5)
    assert len(f.urls) == 3, (
        "the batch must end at the feed the Stop cut, not walk the rest through refusals"
    )
    assert r["imported"] == 2
    assert r["failed"] == 0, "a Stop is not the feed's failure"
    stamped = F._load_json("calendar_autoimport.json")
    assert len(stamped) == 2, "only the two completed checks are stamped"
    cut_url = f.urls[2]
    clear_kill_switch()
    again = _Fetcher()
    F.auto_import_due_feeds(again, batch=1)
    assert again.urls == [cut_url], (
        "the feed the Stop cut is asked FIRST on the next pass, not skipped for the interval"
    )


def test_a_stop_engaged_before_the_batch_asks_no_feed_and_stamps_none():
    activate_kill_switch()
    f = _Fetcher()
    r = F.auto_import_due_feeds(f, batch=4)
    assert f.urls == []
    assert r["imported"] == 0 and r["failed"] == 0
    assert F._load_json("calendar_autoimport.json") == {}


def test_an_ordinary_failure_is_still_counted_and_stamped():
    f = _Fetcher(fail=RuntimeError("blocked"))
    r = F.auto_import_due_feeds(f, batch=3)
    assert r["failed"] == 3 and r["imported"] == 0
    assert len(F._load_json("calendar_autoimport.json")) == 3

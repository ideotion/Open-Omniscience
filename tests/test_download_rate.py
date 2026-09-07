"""PERF-09: owner-measured per-job download rate (and the ETA that rides on it).

Per-job rate/ETA were a stated, reasoned omission (``CLAUDE.md`` UI invariant
#20): "the owners report only bytes/percent, NOT a rate; an honest rate needs
owner-measured bytes-over-time in the manager -- never a client-side guess across
the adaptive poll". This is that measurement, and MOST OF THESE TESTS ARE ABOUT
WHAT IT REFUSES TO SAY, because every failure mode here is a number appearing
where there is no measurement:

  * an unmeasurable rate is ABSENT with a reason, never ``0`` (a 0 reads as
    "stalled", which is a different fact -- the recorded ``.get(key, 0)`` family);
  * a STALE rate is not a rate: samples are pruned against a fresh clock at READ
    time, so a download whose bytes stopped ages out of its own window instead of
    repeating its last healthy figure forever;
  * a PAUSE is not slowness: the window resets on start/resume;
  * an ETA needs a measured rate AND a real Content-Length, never a catalog
    estimate;
  * nothing is persisted, so after a restart a download is honestly unmeasured
    rather than reporting a rate for a transfer that is not running.

The clock is injected throughout, so every arithmetic assertion is EXACT rather
than a timing threshold that has to be calibrated (and would then be recalibrated
downward on the first slow CI runner).
"""

from __future__ import annotations

import json

import pytest

from src.ingest.download_rate import RateRegistry, RateSampler


class _Clock:
    """A hand-cranked monotonic clock, so rates are exact and never flaky."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += float(dt)


def _sampler(**kw):
    c = _Clock()
    return RateSampler(clock=c, **kw), c


# --------------------------------------------------------------------------- #
#  the negative space: what it refuses to publish
# --------------------------------------------------------------------------- #


def test_nothing_observed_is_absent_with_a_reason_never_a_zero_rate():
    s, _c = _sampler()
    snap = s.snapshot()
    assert snap["measured"] is False
    assert snap["reason"]
    # THE POINT: a 0 would read as "this download is stalled", which is a
    # different fact from "we have not measured anything yet".
    assert "bytes_per_s" not in snap
    assert "eta_seconds" not in snap


def test_a_window_shorter_than_the_floor_is_refused_and_says_how_short():
    s, c = _sampler()
    s.reset(0)
    c.advance(0.05)
    s.observe(1_000_000)  # a colossal apparent rate over 50 ms
    snap = s.snapshot()
    assert snap["measured"] is False
    assert "0.05" in snap["reason"] and "1" in snap["reason"]
    assert "bytes_per_s" not in snap


def test_a_real_measurement_is_exact_and_carries_its_method():
    s, c = _sampler()
    s.reset(0)
    for _ in range(4):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 2048)  # 2048 B per second, exactly
    snap = s.snapshot()
    assert snap["measured"] is True
    assert snap["bytes_per_s"] == pytest.approx(2048.0)
    assert snap["window_s"] == pytest.approx(4.0)
    assert snap["samples"] == 5
    assert "wall time" in snap["method"]


def test_a_STALLED_download_ages_out_instead_of_repeating_its_last_good_rate():
    """The discriminating case, and the reason pruning happens at READ time.

    If samples were pruned only when bytes arrive, a transfer whose bytes stopped
    would keep publishing its last healthy figure for as long as nobody sent it
    another byte -- an instrument that freezes while still reporting, which is
    worse than one that stops."""
    s, c = _sampler(window_s=10.0)
    s.reset(0)
    for _ in range(5):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 4096)
    assert s.snapshot()["measured"] is True  # healthy first

    c.advance(60.0)  # ...and then the server goes quiet
    snap = s.snapshot()
    assert snap["measured"] is False, snap
    assert "bytes_per_s" not in snap
    assert snap["idle_s"] == pytest.approx(60.0)
    assert "no bytes received" in snap["reason"]


def test_a_resume_is_not_charged_for_the_time_the_download_sat_paused():
    s, c = _sampler(window_s=1e9)  # a window long enough that only reset() can clear it
    s.reset(0)
    c.advance(2.0)
    s.observe(2048)
    c.advance(86_400.0)  # paused for a day

    s.reset(2048)  # resume: the partial file's bytes are a STARTING POINT
    c.advance(2.0)
    s.observe(2048 + 8192)
    snap = s.snapshot()
    assert snap["measured"] is True
    # 8192 B over 2 s. Charging the pause would give ~0.1 B/s; counting the
    # resumed-from bytes as fresh progress would give ~5 kB/s.
    assert snap["bytes_per_s"] == pytest.approx(4096.0)


def test_a_byte_count_that_goes_backwards_opens_a_FRESH_window(monkeypatch):
    """A restart (a 200 where a 206 was asked for) makes the cumulative count
    drop. Comparing only the window's FIRST and LAST sample cannot see that -- a
    restart in the MIDDLE leaves first < last, so the rate comes out positive,
    plausible and wrong. (This test caught exactly that in the first cut: it
    reported a measured 125 B/s over a window in which 10,000 bytes had arrived
    and then been discarded.)"""
    s, c = _sampler()
    s.reset(0)
    c.advance(2.0)
    s.observe(10_000)
    c.advance(2.0)
    s.observe(500)  # the file was re-opened and restarted mid-window

    snap = s.snapshot()
    assert snap["measured"] is False, snap
    assert "one sample" in snap["reason"], snap
    assert "bytes_per_s" not in snap

    # ...and the fresh window then measures the RESTARTED transfer correctly,
    # rather than being poisoned for good.
    c.advance(2.0)
    s.observe(500 + 4096)
    snap2 = s.snapshot()
    assert snap2["measured"] is True
    assert snap2["bytes_per_s"] == pytest.approx(2048.0), snap2


# --------------------------------------------------------------------------- #
#  the ETA needs BOTH halves
# --------------------------------------------------------------------------- #


def test_the_eta_needs_a_measured_rate_AND_a_real_total():
    s, c = _sampler()
    s.reset(0)
    for _ in range(4):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 1000)

    # no total (the server sent no Content-Length yet) -> no ETA
    assert "eta_seconds" not in s.snapshot(done_bytes=4000)
    assert "eta_seconds" not in s.snapshot(total_bytes=0, done_bytes=4000)
    # a real total -> an ETA derived from the MEASURED rate
    snap = s.snapshot(total_bytes=14_000, done_bytes=4000)
    assert snap["eta_seconds"] == pytest.approx(10.0)


def test_an_unmeasured_rate_never_produces_an_eta():
    s, c = _sampler()
    s.reset(0)
    c.advance(0.01)
    s.observe(999_999)
    snap = s.snapshot(total_bytes=10_000_000, done_bytes=999_999)
    assert snap["measured"] is False
    assert "eta_seconds" not in snap, "an ETA was published without a measured rate"


def test_a_finished_download_gets_no_eta_rather_than_zero():
    s, c = _sampler()
    s.reset(0)
    for _ in range(3):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 1000)
    snap = s.snapshot(total_bytes=3000, done_bytes=3000)
    assert snap["measured"] is True
    assert "eta_seconds" not in snap


# --------------------------------------------------------------------------- #
#  bounds, and the registry's third state
# --------------------------------------------------------------------------- #


def test_the_sample_buffer_is_bounded_and_reports_the_REAL_span_it_kept():
    """A cap that silently shortens the window must not silently misreport it:
    ``window_s`` is the span the retained samples actually cover."""
    s, c = _sampler(max_samples=4, window_s=1e9)
    s.reset(0)
    for _ in range(50):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 100)
    snap = s.snapshot()
    assert snap["samples"] <= 4
    assert snap["window_s"] == pytest.approx(3.0), snap
    assert snap["bytes_per_s"] == pytest.approx(100.0)


def test_an_unknown_key_is_a_THIRD_state_distinct_from_stalled_and_from_zero():
    r = RateRegistry()
    snap = r.snapshot("never-started")
    assert snap["measured"] is False
    assert "not measured in this session" in snap["reason"]
    assert "bytes_per_s" not in snap and "idle_s" not in snap


def test_forget_drops_a_deleted_download(monkeypatch):
    r = RateRegistry()
    r.start("k", 0)
    assert r.get("k") is not None
    r.forget("k")
    assert r.get("k") is None


def test_no_field_name_in_the_payload_trips_the_no_score_convention():
    """The house guard bans score/rating/ranking/grade as SUBSTRINGS of dict
    keys -- walk your own payload before pushing (``degraded`` contains
    ``grade``, which has bitten)."""
    s, c = _sampler()
    s.reset(0)
    for _ in range(3):
        c.advance(1.0)
        s.observe(int(c.t - 1000.0) * 100)
    banned = ("score", "rating", "ranking", "grade")
    for snap in (s.snapshot(total_bytes=1000, done_bytes=300), RateRegistry().snapshot("x")):
        for k in snap:
            assert not any(b in k.lower() for b in banned), k


# --------------------------------------------------------------------------- #
#  the WIRING -- a test of a helper is not a test of its wiring
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, *, status_code=200, length=0, chunks=()):
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = {"Content-Length": str(length)}

    def raise_for_status(self):
        return None

    def iter_content(self, _chunk):
        yield from self._chunks


def _drive_dump(tmp_path, clock):
    from src.wiki.dumps import DumpDownloadManager

    chunks = [b"x" * 1024] * 8

    def http_get(url, headers):
        return _FakeResp(status_code=200, length=8192, chunks=chunks)

    m = DumpDownloadManager(base_dir=tmp_path, http_get=http_get)
    m._rates = RateRegistry()
    # Advance the injected clock as each chunk lands, so the measurement is
    # exact; the production sampler uses time.monotonic.
    orig_start = m._rates.start

    def start(key, b=0):
        s = RateSampler(clock=clock)
        m._rates._by_key[key] = s
        s.reset(b)
        return _Ticking(s, clock)

    m._rates.start = start  # type: ignore[method-assign]
    assert orig_start
    entry = m._entry_for("en", "pages-articles")
    m._download(entry)
    return m


class _Ticking:
    """Wraps the sampler so each observed chunk advances the injected clock."""

    def __init__(self, inner, clock):
        self._inner, self._clock = inner, clock

    def observe(self, n):
        self._clock.advance(1.0)
        self._inner.observe(n)


def test_the_dump_manager_publishes_the_measurement_beside_its_byte_counts(tmp_path):
    c = _Clock()
    m = _drive_dump(tmp_path, c)
    rows = m.list()
    assert rows and "rate" in rows[0], rows
    r = rows[0]["rate"]
    assert r["measured"] is True, r
    assert r["bytes_per_s"] == pytest.approx(1024.0), r


def test_the_OSM_manager_publishes_it_too(tmp_path, monkeypatch):
    """BOTH managers, deliberately: these two download loops grew independently
    and this repo has already had a fix land on one and not the other (the model
    backup enumerator, the resume control). One shared registry is the mechanism;
    this is the guard that the mechanism is actually wired on both sides."""
    from src.geo import osm_downloads as osm

    c = _Clock()
    chunks = [b"y" * 512] * 6

    def http_get(url, headers):
        return _FakeResp(status_code=200, length=3072, chunks=chunks)

    m = osm.OsmDownloadManager(base_dir=tmp_path, http_get=http_get)

    def start(key, b=0):
        s = RateSampler(clock=c)
        m._rates._by_key[key] = s
        s.reset(b)
        return _Ticking(s, c)

    m._rates.start = start  # type: ignore[method-assign]
    entry = m._entry_for("monaco")
    m._download(entry)

    rows = [r for r in m.list() if r["key"] == entry.key]
    assert rows and "rate" in rows[0], rows
    assert rows[0]["rate"]["measured"] is True
    assert rows[0]["rate"]["bytes_per_s"] == pytest.approx(512.0)


def test_nothing_about_the_rate_is_persisted_across_a_restart(tmp_path):
    """A rate read back from a state file describes a transfer that is no longer
    happening. After a restart the download must be honestly UNMEASURED, not
    stale -- so the state file must not contain the measurement at all."""
    c = _Clock()
    m = _drive_dump(tmp_path, c)
    assert m.list()[0]["rate"]["measured"] is True

    # Walk the persisted KEYS. A substring scan of the serialised blob is the
    # recorded non-unique-needle trap and it fired here on the first run: pytest
    # names the tmp dir after the test, so the path itself contains "rate".
    raw = json.loads((tmp_path / "downloads.json").read_text("utf-8"))
    persisted_keys = set()
    for e in raw.get("entries", {}).values():
        persisted_keys.update(e)
    assert persisted_keys, "ANTI-VACUITY: nothing was persisted, so this proved nothing"
    for token in ("rate", "bytes_per_s", "eta_seconds", "idle_s"):
        assert not any(token in k for k in persisted_keys), (
            f"{token!r} reached the state file via {sorted(persisted_keys)}"
        )

    from src.wiki.dumps import DumpDownloadManager

    restarted = DumpDownloadManager(base_dir=tmp_path, http_get=lambda *a, **k: None)
    row = restarted.list()[0]
    assert row["downloaded_bytes"] == 8192  # the byte counts DO survive
    assert row["rate"]["measured"] is False
    assert "not measured in this session" in row["rate"]["reason"]

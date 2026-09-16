"""S04-13 S2 (Q1013 = a): the persisted per-host next-allowed-at, and its named deferral.

    "Persist a per-host next-allowed-at beside the robots cache; refuse an inline
    wait beyond a few minutes with a named deferral counted as its own bucket; the
    ride-along and trial fetch inherit both."

WHAT THIS IS FOR, measured rather than supposed. ``EthicalFetcher`` sleeps a host's
declared ``Crawl-delay`` before EVERY request, so one host costs ``delay x
requests`` with no ceiling: the 2026-09-10 candidate-kit run recorded single hosts
at 5409 s, 3621 s and 1829 s, and the pool could not finish until its slowest
member did.

THE HALF THAT IS EASY TO GET WRONG is not the refusal, it is what happens NEXT
pass. ``make_fetcher`` builds a brand-new fetcher per collection pass, so the
in-memory ``_last_request`` is discarded between passes -- a refusal with no
persisted stamp would re-ask a ``Crawl-delay: 3600`` host on every single pass,
which is louder than the impoliteness it replaced. Several of these tests exist
only to pin that a SECOND fetcher inherits the first one's promise.

The clock is real here (the stamps are wall-clock by design, because they cross
processes), but nothing asserts a duration: every assertion is about which branch
was taken and what was recorded, so there is no threshold to recalibrate.
"""

from __future__ import annotations

from pathlib import Path
from urllib.robotparser import RobotFileParser

import pytest

from src.ingest import (
    CrawlDelayDeferred,
    EthicalFetcher,
    FetchError,
    _crawl_delay_max_wait_s,
    _load_host_schedule,
)


def _robots(delay: int | None) -> RobotFileParser:
    lines = ["User-agent: *"]
    if delay is not None:
        lines.append(f"Crawl-delay: {delay}")
    rp = RobotFileParser()
    rp.parse(lines)
    return rp


def _fetcher(tmp_path: Path, *, delay: int | None, host: str = "slow.example") -> EthicalFetcher:
    f = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json")
    if delay is not None:
        f._robots[f"https://{host}"] = (_robots(delay), f._now() + 9999)
    return f


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #


def test_a_long_crawl_delay_is_refused_by_name_rather_than_slept(tmp_path):
    f = _fetcher(tmp_path, delay=3600)
    slept: list[float] = []
    f._sleep = slept.append

    f._respect_rate_limit("slow.example", "https://slow.example")  # first touch is free
    with pytest.raises(CrawlDelayDeferred) as exc:
        f._respect_rate_limit("slow.example", "https://slow.example")

    assert "Crawl-delay" in str(exc.value)
    assert "not before" in str(exc.value)
    assert exc.value.delay_s == 3600.0
    assert exc.value.netloc == "slow.example"
    assert not slept, "a refused wait must not ALSO be slept -- that is the cost being avoided"


def test_a_short_crawl_delay_is_still_slept_not_refused(tmp_path):
    """The negative-space twin. A refusal that fired on ordinary politeness would
    look conservative while quietly stopping the collector from fetching anything."""
    f = _fetcher(tmp_path, delay=2, host="ok.example")
    slept: list[float] = []
    f._sleep = slept.append

    f._respect_rate_limit("ok.example", "https://ok.example")
    f._last_request["ok.example"] = f._now()
    f._respect_rate_limit("ok.example", "https://ok.example")  # must NOT raise

    assert slept and slept[0] == pytest.approx(2.0, abs=0.1)


def test_the_cap_is_a_few_minutes_and_a_broken_override_falls_back_to_it():
    """A zero or negative ceiling would refuse EVERY host, including one whose
    politeness costs a second -- a misconfiguration must degrade to the default
    rather than to a silent total stop."""
    assert 60 <= _crawl_delay_max_wait_s() <= 600, "the cap should be 'a few minutes'"
    import os

    for bad in ("0", "-5", "not-a-number", ""):
        os.environ["OO_CRAWL_DELAY_MAX_WAIT"] = bad
        try:
            assert _crawl_delay_max_wait_s() == 180.0
        finally:
            os.environ.pop("OO_CRAWL_DELAY_MAX_WAIT", None)


# --------------------------------------------------------------------------- #
# The persistence, which is the half that makes the refusal mean anything
# --------------------------------------------------------------------------- #


def test_the_stamp_survives_the_per_pass_fetcher_rebuild(tmp_path):
    """THE acceptance property: a second pass does NOT re-fetch the host."""
    first = _fetcher(tmp_path, delay=3600)
    first._sleep = lambda _s: None
    first._respect_rate_limit("slow.example", "https://slow.example")

    # A brand-new fetcher, exactly as make_fetcher() builds one per pass -- and
    # deliberately with NO robots cache, which is the real state of a fresh pass.
    second = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json")
    # Stub the sleep even though a correct cap never reaches it. Without this the
    # test only finishes QUICKLY because the code is right: neuter the cap and it
    # sleeps 3600 REAL seconds instead of failing, which is a hang rather than a
    # red test. Found by the mutation matrix wedging on exactly that mutant, and
    # worth keeping -- a guard that hangs on the defect it exists to catch cannot
    # report it.
    second._sleep = lambda _s: None
    assert "slow.example" in second._host_schedule
    with pytest.raises(CrawlDelayDeferred) as exc:
        second._respect_rate_limit("slow.example", "https://slow.example")
    assert exc.value.delay_s == 3600.0, (
        "the refusal reported the courtesy interval it fell back to instead of the "
        "host's real declared delay -- a fabricated number inside the one sentence "
        "that explains why the fetch did not happen"
    )


def test_the_sidecar_never_re_decides_a_host_this_instance_already_holds_a_record_for(
    tmp_path,
):
    """ONE authority per host per instance -- the slice's own principle, applied here.

    Found by the timing suite, which had pinned this arithmetic since 0.0.8 and went
    red: a fetcher owing 8 s of a 10 s ``Crawl-delay`` slept 10. Both records were
    internally correct and they disagreed because they were read through different
    CLOCKS -- ``_last_request`` through the injected monotonic one that had been
    advanced 2 s, the sidecar through the real wall clock that had advanced 0.1 ms --
    and ``max()`` dutifully took the larger. In production the two frames tick
    together, so the second record was pure redundancy; it could only ever be wrong.

    So the assertion is not "the frames agree" (they did not, and a wall clock is
    free to step under NTP whatever we assert) but the structural property that
    removes the question: once ``_last_request`` holds an entry for a host, it
    decides, and the stamp is not consulted at all. Driven through the real method
    with a fake clock, because a source-level check could not tell the two apart.
    """
    f = _fetcher(tmp_path, delay=10, host="ten.example")
    slept: list[float] = []
    f._sleep = slept.append
    fake = [1000.0]
    f._now = lambda: fake[0]

    f._respect_rate_limit("ten.example", "https://ten.example")
    assert "ten.example" in f._host_schedule, "the declared delay was not stamped"

    f._last_request["ten.example"] = fake[0]
    fake[0] += 2.0  # two of the ten seconds have passed IN THIS INSTANCE'S CLOCK
    f._respect_rate_limit("ten.example", "https://ten.example")

    assert slept == [pytest.approx(8.0, abs=1e-9)], (
        "the wait was not the eight seconds this instance itself still owed -- a "
        "second record of the same constraint was consulted and won"
    )


def test_a_stamp_STILL_wins_when_it_knows_a_delay_this_instance_has_forgotten(tmp_path):
    """The negative-space twin, and the reason the narrowing above is a narrowing and
    not a removal.

    A robots verdict expires on its own TTL while a ``Crawl-delay: 3600`` stamp is
    still live, so an instance can hold a ``_last_request`` entry for a host whose
    declared delay it can no longer re-derive. Governed by ``_last_request`` alone it
    would fall back to the one-second courtesy interval and fetch a host that asked
    for an hour. The stamp carries the DECLARED delay precisely so it can speak up
    here, and it must outrank the fallback rather than defer to the fresher record.
    """
    f = _fetcher(tmp_path, delay=3600, host="hour.example")
    f._sleep = lambda _s: None
    f._respect_rate_limit("hour.example", "https://hour.example")

    # The TTL lapses: the robots verdict is gone, the stamp is not.
    f._robots.pop("https://hour.example", None)
    f._last_request["hour.example"] = f._now()
    assert "hour.example" in f._host_schedule

    with pytest.raises(CrawlDelayDeferred) as exc:
        f._respect_rate_limit("hour.example", "https://hour.example")
    assert exc.value.delay_s == 3600.0, (
        "the host's own declared hour was forgotten and the courtesy interval was "
        "used in its place"
    )


def test_a_lapsed_stamp_is_absent_so_the_host_becomes_fetchable_again(tmp_path):
    """A stamp lapses by TIME and by nothing else; once it has, it is simply gone."""
    path = tmp_path / "host_schedule.json"
    path.write_text('{"a.example": {"not_before": 1.0, "delay_s": 3600.0}}', "utf-8")
    assert _load_host_schedule(path) == {}, "a lapsed stamp must not be loaded"


def test_a_corrupt_sidecar_degrades_to_the_in_memory_interval(tmp_path):
    path = tmp_path / "host_schedule.json"
    path.write_text("{not json at all", "utf-8")
    assert _load_host_schedule(path) == {}
    path.write_text('{"a.example": {"delay_s": 5}}', "utf-8")  # no not_before
    assert _load_host_schedule(path) == {}


def test_only_a_declared_crawl_delay_is_persisted(tmp_path):
    """The one-second courtesy interval is not written down.

    It has always been shorter than the gap between two passes touching one host, so
    persisting it would add a file write per fetch to record a constraint that can
    never bind.
    """
    f = _fetcher(tmp_path, delay=None, host="plain.example")
    f._sleep = lambda _s: None
    f._respect_rate_limit("plain.example", "https://plain.example")
    f._last_request["plain.example"] = f._now()
    f._respect_rate_limit("plain.example", "https://plain.example")
    assert not (tmp_path / "host_schedule.json").exists()


def test_the_sidecar_sits_beside_the_robots_cache(tmp_path):
    """Both the ruling's words and the practical requirement: one injected path, so
    a fixture cannot redirect half the state and leave the rest in the real data
    directory."""
    f = EthicalFetcher(robots_cache_path=tmp_path / "sub" / "robots_cache.json")
    assert f._host_schedule_path.parent == f._robots_cache_path.parent
    assert f._host_schedule_path.name == "host_schedule.json"


# --------------------------------------------------------------------------- #
# The bucket. A deferral is not a failure of the source.
# --------------------------------------------------------------------------- #


def test_the_deferral_is_its_own_ingest_bucket_not_a_fetch_failure():
    from src.ingest.pipeline import IngestResult

    assert IngestResult.CRAWL_DELAY_DEFERRED.value == "crawl_delay_deferred"
    assert IngestResult.CRAWL_DELAY_DEFERRED is not IngestResult.FETCH_FAILED


def test_a_deferral_is_classified_before_the_FetchError_it_inherits_from():
    """ORDER is the whole mechanism. ``CrawlDelayDeferred`` IS a ``FetchError``, so a
    handler ordered the other way would file every deferral as a source failure with
    nothing to show it had happened -- and the qualification ladder would then be
    judging a host that was never judged."""
    from src.database.models import Source
    from src.ingest.pipeline import IngestResult, ingest_url

    class _Deferring:
        def fetch(self, *a, **kw):
            raise CrawlDelayDeferred(
                "Crawl-delay 3600 s: not before …",
                netloc="slow.example",
                delay_s=3600.0,
                not_before=0.0,
            )

    class _Empty:
        def filter_by(self, **kw):
            return self

        def first(self):
            return None

    class _Session:
        """An empty corpus. ``ingest_url`` legitimately runs a canonical-URL dedup
        query BEFORE it fetches, so refusing every query here would fail for a
        reason that has nothing to do with the deferral."""

        def query(self, *a, **kw):
            return _Empty()

    out = ingest_url(
        _Session(),
        Source(name="s", domain="slow.example"),
        "https://slow.example/a",
        fetcher=_Deferring(),
    )
    assert out.result is IngestResult.CRAWL_DELAY_DEFERRED, (
        f"a deferral was filed as {out.result.value!r} -- Q1013 requires its own "
        "bucket, never a failure of the source"
    )


def test_the_deferral_appears_in_every_tally_that_enumerates_the_enum():
    """The pass summary carries the bucket by construction, because all three tally
    builders enumerate ``IngestResult``. Pinned so a hand-written key list cannot be
    introduced later and silently drop it."""
    from src.ingest.pipeline import IngestResult

    tally = {r.value: 0 for r in IngestResult if r is not IngestResult.STAGED}
    assert "crawl_delay_deferred" in tally


def test_CrawlDelayDeferred_is_a_FetchError_so_existing_callers_still_catch_it():
    """Every caller that already handles ``FetchError`` keeps working; only the ones
    that want to COUNT it separately need the new branch."""
    assert issubclass(CrawlDelayDeferred, FetchError)


def test_the_trial_fetch_and_ride_along_inherit_by_construction():
    """Both reach the network through ``ingest_url``, so they inherit the bucket and
    the stamp with no code of their own -- asserted rather than assumed, because a
    guarantee that holds as a side effect of an unrelated mechanism is untested and
    the change that breaks it will look unrelated."""
    import inspect

    from src.catalog import qualification

    src = inspect.getsource(qualification.trial_fetch)
    assert "ingest_source" in src or "sitemap_trial_ingest" in src, (
        "trial_fetch stopped going through the shared ingest path; the deferral "
        "bucket and the persisted stamp no longer reach it"
    )


def test_a_deferred_host_gets_no_qualification_verdict_rather_than_a_bad_one():
    """The load-bearing half of "never a failure of the source", pinned.

    A host we declined to fetch out of politeness must not be JUDGED for it. The
    guarantee holds today as a side effect of a mechanism built for something else
    -- the 2026-07-23 no-evidence fix -- and the recorded rule is that a ruled
    guarantee resting on an unrelated mechanism is untested, and the change that
    breaks it will look unrelated. So it is asserted at the chokepoint:

      * a deferral stores no article, so the source is absent from
        ``per_source_metrics``;
      * ``run_qualification_pass`` splits on ``s.id not in per`` and routes the
        absent ones to ``log_no_evidence_attempts``;
      * ``no_evidence`` is an ATTEMPT-LOG-only verdict that never becomes a
        ``Source.status``, so the ladder neither advances nor resets.

    Reading the source rather than driving a whole pass, because the property is
    about which SET a source lands in; the pass itself needs a corpus, a fetcher and
    a network posture, none of which change the answer.
    """
    import inspect

    from src.catalog import qualification

    src = inspect.getsource(qualification.run_qualification_pass)
    assert "s.id not in per" in src, (
        "the no-evidence split is gone; a source that produced no evidence may now "
        "be judged on it"
    )
    assert "log_no_evidence_attempts" in src
    # The verdict must be in NEITHER set. The module's own comment says why: it
    # records that a judgement could not happen, so counting it either way would be
    # a lie in a different direction.
    assert qualification.VERDICT_NO_EVIDENCE == "no_evidence"
    for name in ("JUDGING_VERDICTS", "CLOCK_VERDICTS"):
        bucket = getattr(qualification, name)
        assert qualification.VERDICT_NO_EVIDENCE not in bucket, (
            f"no_evidence joined {name}; a host we declined to fetch out of "
            "politeness would then have that counted as a judgement about it"
        )

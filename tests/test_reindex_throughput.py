"""Why a 500,000-article re-index ran at ~2 articles per second.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-30, on an 8-core / 12 GB VM: every core at ~20%, none at 100%,
disk throughput near zero, and a post-merge re-index crawling at ~2 art/s. TWO causes,
both measured rather than argued.

1. THE WHEN/WHERE/WHO PASS RAN SERIALLY IN THE MAIN PROCESS. ``reindex_parallel``
   carefully offloaded keyword extraction + sentiment to a process pool and left
   dates/places/entities inline, asserting -- with no measurement -- that WWW "is not
   the dominant per-article cost". Measured on date/place-SPARSE generic prose (so it
   is not an artifact of date-dense synthetic text):

       body    extract_dates   extract_locations   serial   ceiling
       25 KB       143.9 ms             47.6 ms   191.5 ms   5.2 art/s
       40 KB       226.1 ms             71.7 ms   297.8 ms   3.4 art/s
       50 KB       278.7 ms             94.2 ms   373.0 ms   2.7 art/s

   ...against ~36 ms for the pooled half. The pool was parallelising the cheap part
   while the expensive part pinned one core -- which is also exactly why no core ever
   reached 100% (one CPU-bound thread migrating across eight) and why the disk was
   idle (regex over text in cache moves no bytes). End-to-end on a 4-core box, 32
   articles of 35 KB: 3.40 art/s before, 11.34 art/s after.

2. THE THROUGHPUT KNOBS WERE GATED ON THE WRONG PREDICATE. ``was_paused`` answers
   "did I stop a running collection loop", and it was standing in for "do I own the
   machine". It is False on a fresh install (nothing was running to stop) and False
   for every item of an import queue (the queue's window already paused it) -- both
   cases where the machine is owned MORE completely. So all-cores workers, the
   enlarged merge cache and the wide commit batch all silently reverted to their
   conservative defaults, the last of those to ONE COMMIT PER ARTICLE.
"""

from __future__ import annotations

from datetime import date

import pytest

import src.scheduler.runner as R
from src.analytics.reindex_parallel import (
    ArticleDerivatives,
    _extract_www,
    precompute_batch,
)

_TEXT = "The council met in Paris on 11 September 2024 to review the budget."


# --------------------------------------------------------------------------- #
#  1. when/where/who rides the pool
# --------------------------------------------------------------------------- #
def test_the_pure_www_extractor_returns_plain_picklable_data():
    """It runs in a WORKER PROCESS, so it may only ever touch the article's own text
    plus scalars -- never an ORM object, never a session."""
    out = _extract_www(_TEXT, "en", ("fr", "2024-09-01", None))
    assert out["dates"] and out["dates"][0]["date"] == "2024-09-11"
    assert any(p["name"] == "Paris" for p in out["places"])
    assert "entities" in out

    import pickle

    assert pickle.loads(pickle.dumps(out)) == out, "must survive the process boundary"


def test_no_context_means_no_www_work():
    """A task that does not ask for WWW must not pay for it -- that is what keeps
    every pre-existing caller byte-identical."""
    assert _extract_www(_TEXT, "en", None) is None


def test_a_failed_www_precompute_is_COUNTABLE_not_silent(monkeypatch):
    """This degrade is silent BY DESIGN -- correct results, quietly at the old speed --
    which makes it a perfect hiding place for the very bug it survives. It is not
    hypothetical: the first cut of this feature imported ``extract_entities`` from the
    wrong module, every call returned None, every article fell back to inline
    extraction, and NOTHING failed. A benchmark caught it; no test would have. So the
    failure now rides back as a marker and is counted."""
    import src.timemap.locextract as L

    def _boom(*a, **k):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(L, "extract_locations", _boom)
    out = _extract_www(_TEXT, "en", ("fr", "2024-09-01", None))
    assert out is not None and "__www_error__" in out, (
        "a failure must be distinguishable from 'not requested'"
    )


def test_the_store_treats_a_failure_marker_as_not_precomputed():
    """"Not precomputed" and "nothing found" are different facts. Conflating them
    would silently drop every date and place on the degraded path."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "analytics" / "store.py"
    body = src.read_text(encoding="utf-8")
    assert '__www_error__' in body and "_pw = {}" in body


def test_tasks_without_www_context_still_work_unchanged():
    """The sixth tuple element is OPTIONAL: five-element tasks are the pre-existing
    shape and must keep working exactly as they did, or every existing caller and
    its exact-equality assertions break."""
    from src.analytics.extract import BaselineExtractor

    tasks = [(i, f"climate policy report {i}", "t", "en", "en") for i in range(3)]
    out = precompute_batch(tasks, extractor=BaselineExtractor(), workers=0)
    assert set(out) == {0, 1, 2}
    assert all(isinstance(v, ArticleDerivatives) for v in out.values())
    assert all(v.www is None for v in out.values()), "no context asked, none computed"


def test_the_serial_path_leaves_www_to_the_caller():
    """Serial means one core, which is the situation pooled WWW exists to escape.
    Doing it here would move identical work from one place to another; the caller's
    inline path already handles ``www=None`` correctly."""
    from src.analytics.extract import BaselineExtractor

    tasks = [(i, _TEXT, "t", "en", "en", ("fr", "2024-09-01", None)) for i in range(3)]
    out = precompute_batch(tasks, extractor=BaselineExtractor(), workers=0)
    assert all(v.www is None for v in out.values())


def test_a_mixed_batch_does_not_raise():
    """A caller may legitimately have context for some articles and not others (an
    article with no usable anchor date). ``zip(*tasks)`` would raise on that ragged
    mix, which is why the dispatch reads the columns element-wise."""
    from src.analytics.extract import BaselineExtractor

    tasks = [
        (1, _TEXT, "t", "en", "en", ("fr", "2024-09-01", None)),
        (2, _TEXT, "t", "en", "en"),
    ]
    out = precompute_batch(tasks, extractor=BaselineExtractor(), workers=0)
    assert set(out) == {1, 2}


# --------------------------------------------------------------------------- #
#  2. ownership, not liveness
# --------------------------------------------------------------------------- #
class _FakeScheduler:
    def __init__(self, running: bool) -> None:
        self.running = running
        self._hold = False

    def hold_exclusive(self) -> None:
        self._hold = True

    def release_exclusive(self) -> None:
        self._hold = False

    def holds_exclusive(self) -> bool:
        return self._hold

    def stop(self, timeout: float = 10.0) -> bool:
        was, self.running = self.running, False
        return was

    def start(self) -> bool:
        self.running = True
        return True


@pytest.fixture()
def sched(monkeypatch):
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)

    def _make(running: bool):
        s = _FakeScheduler(running)
        monkeypatch.setattr(R, "get_scheduler", lambda: s)
        return s

    yield _make
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)


def test_a_fresh_install_owns_the_machine_even_though_it_paused_nothing(sched):
    """THE defect. Boot engages airplane mode and starts no scheduler, so ``stop()``
    returns False because there was nothing to stop -- and every throughput knob read
    that as "someone else might be collecting"."""
    sched(running=False)
    was_paused = R.pause_for_exclusive_operation()
    assert was_paused is False, "nothing was running to pause -- the old signal"
    assert R.owns_the_machine() is True, "...but the machine IS ours"


def test_every_item_of_a_queue_owns_the_machine(sched):
    """The second route to the same wrong answer: the queue's window already paused
    collection, so the per-item pause correctly declines to do it twice -- and the
    knobs read that decline as "not exclusive"."""
    sched(running=True)
    with R.exclusive_window():
        assert R.pause_for_exclusive_operation() is False
        assert R.owns_the_machine() is True


def test_ownership_is_false_when_nothing_is_running_exclusively(sched):
    """The direction that matters: a knob turned on while collection could still be
    scraping is exactly what the conservative defaults exist to prevent."""
    sched(running=True)
    assert R.owns_the_machine() is False


def test_ownership_is_released_with_the_operation(sched):
    s = sched(running=True)
    was = R.pause_for_exclusive_operation()
    assert R.owns_the_machine() is True
    R.resume_after_exclusive_operation(was)
    assert R.owns_the_machine() is False
    assert s.holds_exclusive() is False


def test_unknown_ownership_is_never_assumed_ownership(monkeypatch):
    """A scheduler we cannot reach must read as "not owned" -- the safe direction."""
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)

    def _boom():
        raise RuntimeError("no scheduler")

    monkeypatch.setattr(R, "get_scheduler", _boom)
    assert R.owns_the_machine() is False


def test_the_knobs_are_gated_on_ownership_not_on_was_paused():
    """Pinned against the source: the whole defect was one wrong predicate at this
    exact call site, and it is not visible from any behavioural test that does not
    run a real restore."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "volume_job.py"
    body = re.split(r"\n    def _run_restore\(", src.read_text(encoding="utf-8"))[1]
    body = body.split("\n    def ", 1)[0]
    assert "_owned = owns_the_machine()" in body
    for knob in ("all_cores_worker_count()", "import_cache_mb()", "import_reindex_commit_batch()"):
        assert f"{knob} if _owned else None" in body, f"{knob} still gated on liveness"
    assert "if was_paused else None" not in body


def test_run_restore_derives_the_knobs_for_callers_that_pass_none():
    """The legacy single-archive restore and the /v2/restore commit pass no knobs and
    never pause anything, so their re-index ran at one commit per article even on a
    completely idle machine. An explicit argument still wins -- a caller that says
    what it wants is never second-guessed."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
    body = re.split(r"\n(?:async )?def run_restore\(", src.read_text(encoding="utf-8"))[1]
    nxt = re.search(r"\n(?:async )?(?:def|class) ", body)  # run_restore may be the last def
    body = body[: nxt.start()] if nxt else body
    assert "_owned = exclusive or owns_the_machine()" in body
    assert "if reindex_commit_batch is None:" in body
    assert "if merge_cache_mb is None:" in body


def test_the_effective_knobs_are_reported_not_just_requested():
    """The field report was "~2 articles/sec", noticed by watching a bar: nothing
    surfaced that the commit batch had reverted to 1. Now the report says so."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
    body = re.split(r"\n(?:async )?def run_restore\(", src.read_text(encoding="utf-8"))[1]
    nxt = re.search(r"\n(?:async )?(?:def|class) ", body)
    body = body[: nxt.start()] if nxt else body
    for key in ("owned_the_machine", "workers", "merge_cache_mb", "commit_batch"):
        assert f'_rx_stats["{key}"]' in body


# --------------------------------------------------------------------------- #
#  the two halves meet
# --------------------------------------------------------------------------- #
def test_index_article_accepts_precomputed_www_and_stores_it(monkeypatch):
    """The STORE half must still run in the main process (savepoint, live-session
    error handling); only the EXTRACTION half moved."""
    import inspect

    from src.analytics.store import index_article

    sig = inspect.signature(index_article)
    assert "precomputed_www" in sig.parameters

    from src.timemap import datestore, whostore

    for fn in (
        datestore.store_for_article,
        whostore.store_places_for_article,
        whostore.store_entities_for_article,
    ):
        assert "precomputed" in inspect.signature(fn).parameters, fn.__name__


def test_a_precomputed_date_list_is_stored_without_re_extracting(monkeypatch):
    """The point of the whole change: the store must USE what the worker computed,
    not quietly redo it."""
    import src.timemap.datestore as D

    called: list[int] = []
    monkeypatch.setattr(D, "extract_dates", lambda *a, **k: called.append(1) or [])

    class _Art:
        id = 1
        content = _TEXT
        language = "en"
        published_at = None
        created_at = None

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    class _Sess:
        added: list = []

        def query(self, *a, **k):
            return _Q()

        def add(self, row):
            self.added.append(row)

        def in_nested_transaction(self):
            return True

        def flush(self):
            pass

    s = _Sess()
    n = D.store_for_article(
        s, _Art(), precomputed=[{"date": "2024-09-11", "precision": "day", "text": "x"}]
    )
    assert n == 1 and called == [], "the worker's result was used, not recomputed"
    assert s.added[0].mentioned_on == date(2024, 9, 11)


# --------------------------------------------------------------------------- #
#  R4: the merge page cache scales with AVAILABLE RAM
# --------------------------------------------------------------------------- #
def test_import_cache_scales_with_available_ram(monkeypatch):
    """Maintainer ask 2026-07-30, watching a 12 GB box sit at 30% RAM through an
    import: a FIXED 512 MiB merge cache is both too large for a 3 GB field
    machine and far too small for a 12 GB one. It now takes a share of
    MemAvailable, clamped so it is never worse than the fixed default it
    replaced and never absurd on a very large box."""
    import src.backup.merge as M

    monkeypatch.delenv("OO_IMPORT_CACHE_MB", raising=False)

    monkeypatch.setattr(M, "_available_ram_mb", lambda: 12000)
    assert M.import_cache_mb() == 3000, "a roomy box gets a proportionally bigger cache"

    # A small box is clamped UP to the old fixed default, never below it: this
    # change may not make any machine worse than what already shipped.
    monkeypatch.setattr(M, "_available_ram_mb", lambda: 1200)
    assert M.import_cache_mb() == M._IMPORT_CACHE_FLOOR_MB == 512

    # A very large box is clamped DOWN: past the ceiling the page cache is no
    # longer what limits the merge, and the same import is concurrently running
    # a process pool that needs the rest.
    monkeypatch.setattr(M, "_available_ram_mb", lambda: 256_000)
    assert M.import_cache_mb() == M._IMPORT_CACHE_CEIL_MB == 4096


def test_unreadable_ram_falls_back_to_the_fixed_default_never_a_guess(monkeypatch):
    """An unknown must stay an unknown. A machine whose /proc/meminfo cannot be
    read (non-Linux, restricted /proc) gets exactly the previous fixed default --
    never an invented figure derived from something else."""
    import src.backup.merge as M

    monkeypatch.delenv("OO_IMPORT_CACHE_MB", raising=False)
    monkeypatch.setattr(M, "_available_ram_mb", lambda: None)
    assert M.import_cache_mb() == 512
    monkeypatch.setattr(M, "_available_ram_mb", lambda: 0)
    assert M.import_cache_mb() == 512


def test_an_explicit_operator_override_is_never_second_guessed(monkeypatch):
    """In BOTH directions -- an operator who sets a small cache on a huge box is
    making a deliberate choice (leaving RAM for something else), and one who sets
    a large one on a small box has accepted the consequence. The scaling exists
    to pick a sane number when nobody said, not to overrule someone who did."""
    import src.backup.merge as M

    monkeypatch.setattr(M, "_available_ram_mb", lambda: 64_000)
    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "64")
    assert M.import_cache_mb() == 64, "small override on a huge box is honoured"

    monkeypatch.setattr(M, "_available_ram_mb", lambda: 900)
    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "8192")
    assert M.import_cache_mb() == 8192, "large override on a small box is honoured"

    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "not-a-number")
    assert M.import_cache_mb() == 512, "a junk override degrades to the scaled/floor path"


def test_available_ram_reads_MemAvailable_not_MemTotal(tmp_path, monkeypatch):
    """The kernel's own estimate of what a new allocation can actually get,
    which already discounts what is in use. MemTotal would ignore everything else
    running on the box -- exactly the wrong denominator for deciding how much a
    single import may claim."""
    import src.backup.merge as M

    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16461176 kB\nMemFree:          204800 kB\nMemAvailable:   10261176 kB\n",
        encoding="utf-8",
    )
    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda p, *a, **k: real_open(meminfo, *a, **k) if p == "/proc/meminfo" else real_open(p, *a, **k),
    )
    assert M._available_ram_mb() == 10261176 // 1024  # MemAvailable, not the 16 GB MemTotal


# --------------------------------------------------------------------------- #
#  R5: the city gazetteer is parsed ONCE per process, not once per article
# --------------------------------------------------------------------------- #
def test_extract_locations_does_not_reparse_the_gazetteer_per_article(monkeypatch):
    """``extract_locations`` called ``build_index(load_cities())`` inline, so every
    article re-read and re-parsed the whole gazetteer YAML.

    Measured 2026-07-30 at the size ``scripts/build_city_gazetteer.py`` produces
    with its DEFAULT ``--min-pop 100000`` (~4,500 cities): 1,358 ms per article of
    pure re-parsing, on top of the extraction itself. At 50,000 cities it was 17
    SECONDS per article. The shipped 21-city sample made this invisible in
    development -- there it is ~6 ms -- which is exactly why it survived.

    Safe to cache because the gazetteer is generated OFFLINE by a script and never
    written at runtime; ``locextract._patterns()`` and ``geocode._index()`` already
    assumed precisely that for the same data."""
    import src.catalog.cities as C
    import src.timemap.locextract as L

    C.cached_index.cache_clear()
    L._patterns.cache_clear()

    loads = []
    real_load = C.load_cities
    monkeypatch.setattr(C, "load_cities", lambda *a, **k: (loads.append(1), real_load(*a, **k))[1])

    text = "The meeting in Paris was followed by a visit to Berlin. " * 40
    for _ in range(5):
        L.extract_locations(text, source_country="fr")

    # Two cached entry points read it (the index and the pattern list) -- what must
    # NOT happen is a load per article.
    assert len(loads) <= 2, f"gazetteer re-parsed {len(loads)}x for 5 articles"

    C.cached_index.cache_clear()
    L._patterns.cache_clear()


def test_cached_index_matches_the_uncached_one_exactly(monkeypatch):
    """A cache that returns something different from what it replaced is a bug, not
    an optimisation. Same keys, same City objects."""
    import src.catalog.cities as C

    C.cached_index.cache_clear()
    direct = C.build_index(C.load_cities())
    cached = C.cached_index()
    assert set(cached) == set(direct) == {"pair", "name"}
    assert set(cached["name"]) == set(direct["name"])
    assert set(cached["pair"]) == set(direct["pair"])
    for k, v in direct["name"].items():
        assert (cached["name"][k].name, cached["name"][k].lat, cached["name"][k].lon) == (
            v.name, v.lat, v.lon,
        )
    C.cached_index.cache_clear()


def test_build_index_stays_available_for_callers_with_their_own_list():
    """The cache is only the DEFAULT-gazetteer path. A caller that supplies its own
    city list (tests, the SPARQL parser's output) must keep working unchanged --
    removing that would be losing a tool to gain a cache."""
    from src.catalog.cities import City, build_index, lookup

    idx = build_index([City(name="Nowhere", lat=1.0, lon=2.0, country="zz", population=5)])
    assert lookup(idx, "nowhere", "zz").lat == 1.0

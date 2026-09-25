"""The field defects outside the write path (2026-09-24, ``docs/audit/16_…`` §3.3-§3.6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Six all-diagnostics bundles from 4 GB field machines found these; each test below
reproduces the field shape first and pins the fix against it:

- SCHED-1  a resume that ran out of retries stranded a collector for five days;
- QUAL-1   a declined qualification pass was reported as "done [0/79977] starting…";
- RR-9     a politeness stamp written on a clock 12 hours fast deferred a host 7 hours;
- CUST-1   custody INGEST entries were skipped on a pool timeout and never written;
- FIX-1    the fixity audit re-hashed every row with the scraper's formula and reported
           hazard and law rows as corrupted;
- INT-1    the integrity sweep said "no drift" after its budget ran out and it had
           checked nothing;
- and the card-audit and bulletin loops, which reported one spent budget as a run of
  independent failures.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Keyword, KeywordMention, Source

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    # StaticPool: ONE connection for every thread, so a TestClient's worker thread sees
    # this same in-memory database rather than a fresh, empty one of its own.
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _scope_of(session):
    @contextmanager
    def _scope():
        yield session
        session.commit()

    return _scope


# --------------------------------------------------------------------------- #
#  SCHED-1 -- the pending resume
# --------------------------------------------------------------------------- #
class _Pass:
    """A lingering collection pass: a real thread that ends when told to."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, args=(30,), name="old-pass", daemon=True)
        self.thread.start()


class _Sched:
    """start() refuses while the old pass is alive, as the real one does."""

    def __init__(self, old: _Pass, *, hold: bool = False) -> None:
        self._thread = old.thread
        self.hold = hold
        self.starts = 0
        self.released = 0

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self.starts += 1
        self._thread = threading.Thread(target=lambda: None, name="new-loop")
        return True

    def holds_exclusive(self) -> bool:
        return self.hold

    def release_exclusive(self) -> None:
        self.released += 1


@pytest.fixture()
def sched1(monkeypatch, tmp_path):
    import src.scheduler.runner as runner

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "RESUME_POLL_S", 0.01)
    runner.cancel_pending_resume()
    yield runner
    runner.cancel_pending_resume()


def _wait_for(cond, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_a_resume_that_runs_out_of_retries_stays_pending_and_happens_when_the_pass_exits(sched1, monkeypatch):
    """Lenn: the pass took 39 minutes to wind down, the retries covered ~10, and
    collection stayed off for five days. Now the resume waits for the pass itself."""
    old = _Pass()
    fake = _Sched(old)
    monkeypatch.setattr(sched1, "get_scheduler", lambda: fake)
    sched1.resume_after_exclusive_operation(True, retries=1, retry_delay=0.0)
    pending = sched1.resume_pending()
    assert pending and pending["waiting_for"] == "old-pass" and "winding down" in pending["basis"]
    assert fake.released == 1, "the hold is released at once, pending or not"
    assert fake.starts == 0
    old.release.set()  # the old pass finally exits
    assert _wait_for(lambda: fake.starts == 1 and sched1.resume_pending() is None)


def test_a_pending_resume_never_overrides_airplane_mode(sched1, monkeypatch):
    from src.ingest import activate_kill_switch

    old = _Pass()
    fake = _Sched(old)
    monkeypatch.setattr(sched1, "get_scheduler", lambda: fake)
    sched1.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    activate_kill_switch()  # the operator went offline while it waited
    # The watcher can only end here by seeing airplane mode: the old pass is still
    # alive, so no start() can succeed. The pass is released only AFTER it has ended,
    # so no interleaving can let a start() slip between its checks.
    assert _wait_for(lambda: sched1.resume_pending() is None)
    old.release.set()
    time.sleep(0.05)
    assert fake.starts == 0


def test_a_pending_resume_waits_out_another_exclusive_operation(sched1, monkeypatch):
    old = _Pass()
    fake = _Sched(old, hold=True)
    monkeypatch.setattr(sched1, "get_scheduler", lambda: fake)
    sched1.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    old.release.set()
    time.sleep(0.1)
    assert fake.starts == 0 and sched1.resume_pending() is not None, "never during another exclusive hold"
    fake.hold = False
    assert _wait_for(lambda: fake.starts == 1 and sched1.resume_pending() is None)


def test_a_pending_resume_stands_down_when_collection_was_started_elsewhere(sched1, monkeypatch):
    old = _Pass()
    fake = _Sched(old)
    monkeypatch.setattr(sched1, "get_scheduler", lambda: fake)
    sched1.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    other = _Pass()
    fake._thread = other.thread  # the operator went online and a new loop started
    assert _wait_for(lambda: sched1.resume_pending() is None)
    assert fake.starts == 0
    other.release.set()
    old.release.set()


def test_shutdown_retires_a_pending_resume_before_it_stops_the_scheduler(sched1, monkeypatch):
    from tests.js_source_helper import python_function_source

    old = _Pass()
    fake = _Sched(old)
    monkeypatch.setattr(sched1, "get_scheduler", lambda: fake)
    sched1.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    watchers = [t for t in threading.enumerate() if t.name == "oo-resume-watch"]
    sched1.cancel_pending_resume()
    # A retired watcher leaves at its next look; the old pass is released only once it
    # has, so the check below cannot race a start() already past its generation check.
    for t in watchers:
        t.join(timeout=5)
    assert not any(t.is_alive() for t in watchers)
    old.release.set()
    time.sleep(0.05)
    assert fake.starts == 0 and sched1.resume_pending() is None
    body = python_function_source((_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"), "lifespan")
    assert body.index("cancel_pending_resume()") < body.index("get_scheduler().stop()")


def test_the_scheduler_status_carries_the_pending_resume(sched1):
    from src.scheduler.runner import BackgroundScheduler
    from src.scheduler.settings import SchedulerSettings

    st = BackgroundScheduler(settings_provider=lambda: SchedulerSettings()).status()
    assert "resume_pending" in st and st["resume_pending"] is None


def test_the_schedule_tab_shows_a_pending_resume():
    from tests.js_source_helper import function_source, read_static

    body = function_source(read_static("app-core.js"), "_renderSchedule")
    assert "a.resume_pending" in body and 't("Resume pending")' in body and "pendingHtml" in body


# --------------------------------------------------------------------------- #
#  QUAL-1 -- a declined pass is a named refusal
# --------------------------------------------------------------------------- #
class _Ctx:
    def __init__(self) -> None:
        self.progress: list[dict] = []

    @property
    def stopping(self) -> bool:
        return False

    def set_progress(self, **kw):
        self.progress.append(kw)


_DECLINE = {"enabled": True, "evaluated": 0, "skipped": "memory", "available_mb": 900.0,
            "need_mb": 1500.0, "override_env": "OO_ALLOW_BIG_SCANS",
            "reason": "this machine has 3924 MB of RAM with 900 MB available — total under the 4096 MB floor",
            "caveat": "an unmeasured machine is never refused"}


def test_a_declined_pass_is_a_named_refusal_never_complete(db, monkeypatch):
    """Asus: "done [0/79977] starting…". The pass declined below the floor and the job
    read its evaluated: 0 as an empty backlog."""
    import src.catalog.qualify_job as qj

    monkeypatch.setattr(qj, "qualification_pass", lambda *a, **k: dict(_DECLINE))
    ctx = _Ctx()
    out = qj.run_bulk_qualification(ctx, fetcher=object(), session_factory=_scope_of(db), batch_size=5)
    assert out["complete"] is False
    assert out["declined"]["override_env"] == "OO_ALLOW_BIG_SCANS" and "4096 MB floor" in out["declined"]["reason"]
    assert "declined on this machine" in out["paused_reason"] and "OO_ALLOW_BIG_SCANS=1" in out["paused_reason"]
    assert "declined" in ctx.progress[-1]["detail"], "the progress line no longer reads 'starting…'"


def test_the_arm_step_asks_the_floor_the_pass_asks(monkeypatch):
    """Two estimators, opposite answers: the arm step judged 1,257 MB of 1,621 safe on a
    machine where every pass declined. The floor's verdict now comes first."""
    import src.config.machine_floor as mf
    from src.monitoring import expedition

    monkeypatch.setattr(expedition, "_memory", lambda: {"available_mb": 8000})
    monkeypatch.setattr(expedition, "latest_recorded_articles", lambda s: 289_000)
    monkeypatch.setattr(mf, "scan_budget", lambda articles, **k: {"declines": True, "reason": "below the floor",
                                                                  "override_env": "OO_ALLOW_BIG_SCANS"})
    s = expedition.qualification_safety(None)
    assert s["safe"] is False and s["basis"] == "memory floor"
    assert "OO_ALLOW_BIG_SCANS=1" in s["reason"] and "NOT started" in s["reason"]
    monkeypatch.setattr(mf, "scan_budget", lambda articles, **k: {"declines": False})
    assert expedition.qualification_safety(None)["basis"] == "estimated", "above the floor, the estimate decides as before"


def test_the_sources_status_route_carries_the_floor(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import src.config.machine_floor as mf
    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    real = mf.machine_floor
    monkeypatch.setattr(mf, "machine_floor", lambda **k: {**real(total_mb=3924.0, available_mb=900.0),
                                                          "override_env": "OO_ALLOW_BIG_SCANS"})
    with TestClient(app) as c:
        body = c.get("/api/sources/qualify-bulk/status").json()
    assert body["floor"]["declines"] is True and body["floor"]["override_env"] == "OO_ALLOW_BIG_SCANS"
    assert "4096" in body["floor"]["reason"]


def test_the_sources_panel_says_qualification_is_declined():
    from tests.js_source_helper import function_source, read_static

    js = read_static("app-ai-tools.js")
    idle = function_source(js, "loadQualifyBulk")
    assert "st.floor" in idle and "fl.declines" in idle and "_qualDeclinedText(" in idle
    done = function_source(js, "qualifyBulkStart")
    assert "st.result.declined" in done
    helper = function_source(js, "_qualDeclinedText")
    assert "{env}=1" in helper and "below the memory floor" in helper


# --------------------------------------------------------------------------- #
#  RR-9 -- a stamp from a fast clock
# --------------------------------------------------------------------------- #
def test_a_stamp_written_on_a_clock_12_hours_fast_waits_only_its_own_delay(tmp_path):
    """The NUC: legislation.gov.uk refused 'not before 13:49Z' at 06:35Z. A stamp can
    never lie further ahead than its own delay; the rest is clock error."""
    from urllib.robotparser import RobotFileParser

    from src.ingest import EthicalFetcher

    f = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json")
    rp = RobotFileParser()
    rp.parse(["User-agent: *", "Crawl-delay: 10"])
    f._robots["https://slow.example"] = (rp, f._now() + 9999)
    f._host_schedule["slow.example"] = (time.time() + 7 * 3600, 10.0)
    slept: list[float] = []
    f._sleep = slept.append
    f._respect_rate_limit("slow.example", "https://slow.example")  # no CrawlDelayDeferred
    assert slept and 9.0 <= slept[0] <= 10.0 + 1e-6, slept


def test_a_legitimate_stamp_is_honoured_in_full():
    from src.ingest import _stamp_remaining

    assert 4.0 < _stamp_remaining(time.time() + 5, 10.0, 1.0) <= 5.0
    assert _stamp_remaining(time.time() - 5, 10.0, 1.0) == 0.0
    assert _stamp_remaining(time.time() + 7 * 3600, 10.0, 1.0) == 10.0


# --------------------------------------------------------------------------- #
#  FIX-1 -- each writer's own formula
# --------------------------------------------------------------------------- #
def _src(db, domain: str, source_type: str | None = None) -> Source:
    s = Source(name=domain, domain=domain, source_type=source_type)
    db.add(s)
    db.flush()
    return s


def _art(db, src: Source, url: str, content: str, h: str) -> Article:
    a = Article(url=url, canonical_url=url, source_id=src.id, title="t", content=content, hash=h,
                language="en", published_at=datetime.now(UTC), created_at=datetime.now(UTC))
    db.add(a)
    db.flush()
    return a


def _seed_writers(db) -> dict[str, Article]:
    from src.utils.url_utils import generate_content_hash

    raw = lambda t: hashlib.sha256(t.encode()).hexdigest()  # noqa: E731
    body = "M 4.6 - 12 km NE of Somewhere\nmagnitude 4.6"
    return {
        "scraped": _art(db, _src(db, "news.example"), "https://news.example/a", "a  b\n c", generate_content_hash("a  b\n c")),
        "law": _art(db, _src(db, "law.uk.local", "legal"), "https://www.legislation.gov.uk/ukpga/2018/12",
                    "  Section 1.  The Act  ", raw("  Section 1.  The Act  ")),
        "wiki": _art(db, _src(db, "en.wikipedia.org"), "https://en.wikipedia.org/wiki/X", "X  is  a  thing", raw("X  is  a  thing")),
        "stats": _art(db, _src(db, "statistics.oecd.local", "statistics"), "statistics://oecd/GDP/FRA",
                      "GDP  France", raw("GDP  France")),
        "hazard": _art(db, _src(db, "hazard.usgs.local", "hazard"), "hazard://usgs/us7000abcd", body,
                       hashlib.sha256(f"hazard://usgs/us7000abcd\n{body}".encode()).hexdigest()),
    }


def test_each_writer_is_rehashed_with_its_own_formula(db):
    """Asus and Lenn: 22 % and 29 % 'mismatched', every one a hazard or law row, none
    altered. Under their writers' own formulas they all match."""
    from src.verification.fixity import audit_fixity

    _seed_writers(db)
    r = audit_fixity(db)
    assert r["checked"] == 5 and r["mismatched"] == 0 and r["ok"] == 5, r["mismatches"]
    assert r["by_hash_kind"] == {"normalised": 1, "raw": 3, "url+content": 1}
    assert r["matched_other_kind"] == 0


def test_an_altered_row_is_still_a_mismatch_under_its_own_formula(db):
    from src.verification.fixity import audit_fixity

    rows = _seed_writers(db)
    rows["hazard"].content = rows["hazard"].content.replace("4.6", "7.9")
    rows["law"].content = rows["law"].content + " (amended)"
    db.flush()
    r = audit_fixity(db)
    assert r["mismatched"] == 2
    kinds = {m["url"]: m["hash_kind"] for m in r["mismatches"]}
    assert kinds == {"hazard://usgs/us7000abcd": "url+content", "https://www.legislation.gov.uk/ukpga/2018/12": "raw"}


def test_a_misclassified_writer_is_counted_apart_never_as_corruption(db):
    from src.verification.fixity import audit_fixity

    _art(db, _src(db, "blog.example"), "https://blog.example/p", "Two  spaces", hashlib.sha256(b"Two  spaces").hexdigest())
    r = audit_fixity(db)
    assert r["mismatched"] == 0 and r["matched_other_kind"] == 1
    assert r["matched_other_kind_examples"][0]["expected_kind"] == "normalised"
    assert r["matched_other_kind_examples"][0]["matched_kind"] == "raw"


def test_a_topical_type_never_decides_the_writer(db):
    """About two hundred seeded web sources are typed ``legal`` and one ``statistics``.
    Their pages are SCRAPED, so they hash under the scraper's formula and are plain ok --
    never counted as misclassified because a topic was read as a writer."""
    from src.utils.url_utils import generate_content_hash
    from src.verification.fixity import audit_fixity

    _art(db, _src(db, "gazette.example.gov", "legal"), "https://gazette.example.gov/n/1",
         "Decree  no. 1", generate_content_hash("Decree  no. 1"))
    _art(db, _src(db, "stats.example.gov", "statistics"), "https://stats.example.gov/r/1",
         "CPI  rose", generate_content_hash("CPI  rose"))
    r = audit_fixity(db)
    assert r["ok"] == 2 and r["mismatched"] == 0
    assert r["matched_other_kind"] == 0, r["matched_other_kind_examples"]
    assert r["by_hash_kind"]["normalised"] == 2


def test_the_audit_formulas_are_the_writers_formulas():
    """The audit mirrors four writers; if one of them changes its formula, this fails
    rather than the field reporting corruption again."""
    def src(p: str) -> str:
        return (_ROOT / "src" / p).read_text(encoding="utf-8")

    assert 'hashlib.sha256(f"{url}\\n{body}".encode()).hexdigest()' in src("hazards/ingest.py")
    assert "hashlib.sha256(text.encode()).hexdigest()" in src("law/corpus.py")
    assert "hashlib.sha256(plain.encode()).hexdigest()" in src("wiki/corpus.py")
    assert "hashlib.sha256(body.encode()).hexdigest()" in src("stats/series_corpus.py")
    assert 'return f"law.{j}.local"' in src("law/corpus.py")
    assert 'return f"hazard.{p}.local"' in src("hazards/ingest.py")
    assert 'return f"statistics.{a}.local"' in src("stats/series_corpus.py")


# --------------------------------------------------------------------------- #
#  INT-1 -- a verdict only from completed checks
# --------------------------------------------------------------------------- #
def _seed_keywords(s: Session, n: int) -> None:
    src = Source(name="S", domain="s.example")
    s.add(src)
    s.flush()
    a = Article(title="A", content="x", url="http://s.example/a", canonical_url="http://s.example/a",
                source_id=src.id, hash="h1")
    s.add(a)
    s.flush()
    s.add_all([Keyword(term=f"k{i}", normalized_term=f"k{i}") for i in range(n)])
    s.flush()
    s.commit()


def test_a_sweep_that_runs_out_of_budget_says_so_and_claims_no_verdict(monkeypatch):
    """Asus: drift false, timed_out false, every count null. The deadline's interrupt
    was swallowed per check, so the sweep never learned its budget had run out."""
    from src.monitoring.integrity import corpus_integrity

    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        _seed_keywords(s, 3000)
        monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "0.000001")
        r = corpus_integrity(s, sample=100)
    assert r["timed_out"] is True
    assert r["drift"] is None, "no check completed, so no verdict"
    assert "orphan_keywords" in r["incomplete_checks"]
    assert r["verdict"].startswith("not established")


def test_a_clean_complete_sweep_still_says_no_drift(monkeypatch):
    from src.monitoring.integrity import corpus_integrity

    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        a = Article(title="A", content="x", url="http://s.example/a", canonical_url="http://s.example/a",
                    source_id=src.id, hash="h1")
        s.add(a)
        s.flush()
        k = Keyword(term="alpha", normalized_term="alpha", mention_count=3, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3))
        s.commit()
        r = corpus_integrity(s, sample=100)
    assert r["timed_out"] is False and r["drift"] is False and r["verdict"] == "no drift"
    assert r["incomplete_checks"] == []


def test_a_non_interrupt_error_after_the_budget_is_still_a_degraded_read(monkeypatch):
    """Only the deadline's OWN interrupt is re-raised. A missing table after the budget has
    run out still degrades to a null count: re-raised, it would escape the deadline untyped
    (the deadline types only an interrupt) and turn the sweep into a 500."""
    import sqlite3

    from src.monitoring import integrity

    class _S:
        def __init__(self, msg: str) -> None:
            self.msg = msg

        def execute(self, *_a, **_k):
            raise sqlite3.OperationalError(self.msg)

    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: True)
    assert integrity._scalar(_S("no such table: keywords"), "SELECT 1") is None
    with pytest.raises(sqlite3.OperationalError):
        integrity._scalar(_S("interrupted"), "SELECT 1")
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: False)
    assert integrity._scalar(_S("interrupted"), "SELECT 1") is None, "no deadline: a degraded read"


# --------------------------------------------------------------------------- #
#  The card audit and the bulletin: one spent budget, not many failures
# --------------------------------------------------------------------------- #
@pytest.fixture
def clean_registry():
    from src.briefing import registry

    saved = list(registry._REGISTRY)
    registry._REGISTRY = []
    try:
        yield registry
    finally:
        registry._REGISTRY = saved


def test_the_card_audit_names_the_producers_the_budget_never_reached(clean_registry, monkeypatch):
    """Asus: 15 of 37 producers reported as independent 'errors' after one expiry."""
    from src.briefing.card_audit import observe_producers

    ran: list[str] = []
    for name in ("first", "second", "third"):
        clean_registry.register(name, lambda _s, n=name: ran.append(n) or [])
    calls = {"n": 0}

    def _expired(_session):
        calls["n"] += 1
        return calls["n"] > 1  # the budget runs out after the first producer

    monkeypatch.setattr(clean_registry, "_deadline_expired", _expired)
    out = {o.name: o.outcome for o in observe_producers(object())}
    assert out == {"first": "no-signal", "second": "skipped-budget", "third": "skipped-budget"}
    assert ran == ["first"], "a producer after the expiry is never run"


def test_a_budget_skip_is_never_counted_as_nondeterminism(monkeypatch):
    import src.briefing.card_audit as ca

    first = [ca.ProducerOutcome(name="p", outcome="ok"), ca.ProducerOutcome(name="q", outcome="no-signal")]
    second = [ca.ProducerOutcome(name="p", outcome="skipped-budget"), ca.ProducerOutcome(name="q", outcome="no-signal")]
    monkeypatch.setattr(ca, "observe_producers", lambda session: second)
    d = ca._determinism_check(object(), first)
    assert d["producer_outcome_changes"] == [], "ok -> skipped-budget is the budget, not the producer"
    assert d["not_compared_budget"] == ["p"]


def test_the_bulletin_reports_sections_after_the_budget_as_skipped(monkeypatch):
    import src.bulletin.sections as sec

    ran: list[str] = []
    fake = tuple((k, (lambda s, p, c, k=k: ran.append(k) or {"section": k, "ok": True})) for k in ("a", "b", "c"))
    monkeypatch.setattr(sec, "SECTIONS", fake)
    calls = {"n": 0}

    def _expired(_session):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(sec, "_deadline_expired", _expired)
    out = sec.build_sections(object(), period=None)
    assert [o["section"] for o in out] == ["a", "b", "c"], "every section is still listed"
    assert out[0] == {"section": "a", "ok": True}
    assert out[1]["skipped"] == "budget" and "budget was spent" in out[1]["error"]
    assert ran == ["a"]


# --------------------------------------------------------------------------- #
#  CUST-1 -- owed entries are written late, and gaps are counted
# --------------------------------------------------------------------------- #
@pytest.fixture()
def custody(monkeypatch, tmp_path, db):
    """An isolated data dir, plaintext stores, custody auto-log ON, and the app's
    session_scope pointed at the test database."""
    import src.database.session as dbs

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(dbs, "session_scope", _scope_of(db))
    from src.custody.settings import save_settings

    save_settings({"auto_log_on_ingest": True})
    return tmp_path / "data"


def _stored(db, n: int) -> list[Article]:
    src = _src(db, "c.example")
    arts = [_art(db, src, f"https://c.example/{i}", f"body {i}", f"hash-{i}") for i in range(n)]
    db.commit()
    return arts


def _entries(item_id: str):
    from src.custody.log import CustodyLog

    with CustodyLog() as log:
        return log.entries_for(item_id)


def test_a_failed_custody_write_is_queued_and_written_late_at_the_pass_end(custody, db, monkeypatch):
    """Lenn, Qubes: 8 to 19 skipped entries each, in logs covering one or two days,
    and nothing ever wrote them. The failure is now queued without the database, the
    per-article path never repays it, and the pass end records it, marked late."""
    from src.custody import pending
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    a, b = _stored(db, 2)
    real = CustodyLog.record

    def _boom(self, *args, **kw):
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    monkeypatch.setattr(CustodyLog, "record", _boom)
    _maybe_record_custody(a)  # never raises into ingestion
    queued = pending.read_pending()
    assert [q["article_id"] for q in queued] == [a.id] and "QueuePool" in queued[0]["error"]
    monkeypatch.setattr(CustodyLog, "record", real)
    _maybe_record_custody(b)
    assert [q["article_id"] for q in pending.read_pending()] == [a.id], (
        "the per-article path never repays: its read would compete for the exhausted pool")
    res = pending.drain_owed()
    assert res is not None and res["recorded"] == 1 and res["still_pending"] == 0
    assert pending.read_pending() == [] and not pending.pending_path().exists()
    late = [e for e in _entries(f"article:{a.id}") if e.action == "ingest"]
    assert len(late) == 1
    meta = late[0].metadata
    assert meta["late"] is True and meta["stored_by"] and meta["recorded_late_at"] and "QueuePool" in meta["late_reason"]
    assert late[0].item_hash == "hash-0", "the hash was read back from the stored row"
    assert [e.metadata.get("late") for e in _entries(f"article:{b.id}")] == [None]
    assert pending.late_count() == 1


def test_the_collection_pass_end_writes_what_is_owed(custody, db, monkeypatch):
    """The repayment runs in the pass tail, journalled like every other tail step, and the
    run report says what it wrote."""
    import src.scheduler.hygiene as hygiene
    from src.custody import pending
    from src.scheduler.runner import BackgroundScheduler
    from src.scheduler.settings import SchedulerSettings

    (a,) = _stored(db, 1)
    pending.note_failed(a.id, error="TimeoutError: pool")
    reports: list[dict] = []
    monkeypatch.setattr("src.scheduler.runlog.record_run", reports.append)
    monkeypatch.setattr(hygiene, "run_pass_hygiene", lambda: None)
    sched = BackgroundScheduler(run_once_fn=lambda: {"ok": True},
                                settings_provider=lambda: SchedulerSettings(continuous=False))
    sched._do_run()
    assert reports and reports[0]["custody_late"]["recorded"] == 1
    assert pending.read_pending() == []
    assert [e.metadata.get("late") for e in _entries(f"article:{a.id}")] == [True]


def test_the_pass_end_leaves_the_debt_alone_once_auto_log_is_off(custody, db):
    """Automatic custody writes happen only while automatic custody logging is on; after
    the operator switches it off, what is owed waits for the Chain of custody tab."""
    from src.custody import pending
    from src.custody.settings import save_settings

    (a,) = _stored(db, 1)
    pending.note_failed(a.id, error="TimeoutError: pool")
    save_settings({"auto_log_on_ingest": False})
    assert pending.drain_owed() is None
    assert [q["article_id"] for q in pending.read_pending()] == [a.id]
    assert pending.drain()["recorded"] == 1, "the tab's drain is the operator's act"


def test_a_drain_reads_the_owed_columns_in_one_query_not_one_per_entry(custody, db):
    from sqlalchemy import event

    from src.custody import pending

    arts = _stored(db, 30)
    for a in arts:
        pending.note_failed(a.id, error="TimeoutError: pool")
    reads: list[str] = []

    def _count(conn, cursor, statement, *a):
        if "FROM articles" in statement:
            reads.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        res = pending.drain(limit=100)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert res["recorded"] == 30
    assert len(reads) == 1, reads


def test_a_failed_column_read_is_tried_once_and_every_entry_stays_pending(custody, db, monkeypatch):
    """Under the pool exhaustion that created the debt, a drain must fail FAST: one read
    attempt for the whole batch, never one pool timeout per entry."""
    from src.custody import pending

    arts = _stored(db, 5)
    for a in arts:
        pending.note_failed(a.id, error="TimeoutError: pool")
    calls: list[list[int]] = []

    def _no_pool(ids, session_factory=None):
        calls.append(list(ids))
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    monkeypatch.setattr(pending, "_columns_for", _no_pool)
    res = pending.drain(limit=100)
    assert len(calls) == 1 and res["recorded"] == 0 and res["still_pending"] == 5
    assert "QueuePool" in res["read_error"]
    assert len(pending.read_pending()) == 5


def test_an_entry_queued_during_a_drain_survives_it(custody, db, monkeypatch):
    """The queue is re-read before the rewrite, so a failure that lands while a drain is
    writing is never erased by it."""
    from src.custody import pending
    from src.custody.log import CustodyLog

    a, b = _stored(db, 2)
    pending.note_failed(a.id, error="TimeoutError: pool")
    real = CustodyLog.record

    def _record_and_meanwhile_queue(self, *args, **kw):
        pending.note_failed(b.id, error="TimeoutError: pool (meanwhile)")
        return real(self, *args, **kw)

    monkeypatch.setattr(CustodyLog, "record", _record_and_meanwhile_queue)
    res = pending.drain(limit=10)
    assert res["recorded"] == 1 and res["still_pending"] == 1
    assert [q["article_id"] for q in pending.read_pending()] == [b.id]


def test_a_slow_drain_never_holds_up_a_failing_ingest(custody, db, monkeypatch):
    """A drain's read can wait out a pool timeout; queueing a NEW failure must not wait
    with it, because that is an ingest thread."""
    from src.custody import pending

    (a,) = _stored(db, 1)
    pending.note_failed(a.id, error="TimeoutError: pool")
    in_read, release = threading.Event(), threading.Event()
    real = pending._columns_for

    def _slow(ids, session_factory=None):
        in_read.set()
        release.wait(5)
        return real(ids, session_factory)

    monkeypatch.setattr(pending, "_columns_for", _slow)
    t = threading.Thread(target=pending.drain, kwargs={"limit": 10}, daemon=True)
    t.start()
    try:
        assert in_read.wait(5)
        t0 = time.monotonic()
        assert pending.note_failed(999, error="meanwhile")
        assert time.monotonic() - t0 < 1.0, "queueing never waits for a drain's read"
    finally:
        release.set()
        t.join(5)
    assert [q["article_id"] for q in pending.read_pending()] == [999]


def test_the_owed_id_is_taken_without_a_database_read(custody, db, monkeypatch):
    """The field failure was the RELOAD of an expired article on a busy pool, so the
    id must come from the identity map, never from the row."""
    from sqlalchemy.engine import Engine

    from src.custody import pending
    from src.ingest.pipeline import _maybe_record_custody

    (a,) = _stored(db, 1)
    aid = a.id
    # The pipeline's shape exactly: the commit ends the transaction (returning its
    # connection to the pool) and expires every column, so the next attribute read
    # must ask the engine for a connection -- the call that timed out in the field.
    db.commit()

    def _pool_exhausted(self, *args, **kw):
        # Where the field traceback ends: the session asks its engine for a connection
        # to reload the expired row, and the pool has none to give.
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    # The custody settings live in the main database's key-value table too, so an
    # exhausted pool also cuts that read off and it falls back to the config default --
    # ON in the field (Item-N), off in this suite's environment. Pinned ON here, which
    # is the field's state.
    from src.custody.settings import CustodySettings

    monkeypatch.setattr("src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=True))
    monkeypatch.setattr(Engine, "connect", _pool_exhausted)
    _maybe_record_custody(a)  # never raises into ingestion
    assert [q["article_id"] for q in pending.read_pending()] == [aid]


def test_the_gap_scan_counts_and_records_only_when_asked(custody, db):
    from src.custody import pending
    from src.custody.log import CustodyAction, CustodyLog

    arts = _stored(db, 10)
    with CustodyLog() as log:
        for i, a in enumerate(arts):
            if i not in (3, 6):
                log.record(f"article:{a.id}", a.hash, CustodyAction.INGEST)
    scan = pending.gap_scan()
    assert scan["since_article_id"] == arts[0].id and scan["missing"] == 2 and scan["complete"] is True
    assert scan["missing_ids"] == [arts[3].id, arts[6].id]
    assert pending.read_pending() == [], "counting records nothing"
    assert pending.queue_gaps(scan["missing_ids"]) == 2
    res = pending.drain()
    assert res["recorded"] == 2 and res["still_pending"] == 0
    assert pending.gap_scan()["missing"] == 0
    got = [e for e in _entries(f"article:{arts[3].id}") if e.action == "ingest"][0]
    assert got.metadata["found_by"] == "gap scan" and got.metadata["late"] is True


def test_the_custody_routes_carry_the_late_counts_and_reconcile(custody, db, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.custody import pending

    (a,) = _stored(db, 1)
    pending.note_failed(a.id, error="TimeoutError: pool")
    with TestClient(app) as c:
        s = c.get("/api/custody/settings").json()
        assert s["late"]["pending"] == 1 and s["late"]["recorded_late"] == 0
        r = c.post("/api/custody/reconcile", json={"scan": True}).json()
    assert r["drained"]["recorded"] == 1 and r["late"]["pending"] == 0 and r["late"]["recorded_late"] == 1
    assert r["scan"]["missing"] == 0 and "missing_ids" not in r["scan"]


def test_the_custody_tab_shows_the_late_entries_and_the_gap_check():
    from tests.js_source_helper import function_source, read_static

    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    tab = html[html.index('id="tab-custody"'):]
    tab = tab[:tab.index("</section>")]
    assert 'id="cust-late"' in tab and 'onclick="custodyGapCheck(this)"' in tab
    assert 'id="cust-gap-record"' in tab and 'onclick="custodyGapRecord(this)"' in tab
    js = read_static("app-ai-tools.js")
    assert "_renderCustodyLate(s.late)" in function_source(js, "loadCustody")
    assert '{ scan: true }' in function_source(js, "custodyGapCheck")
    assert "record_gaps: true" in function_source(js, "custodyGapRecord"), "recording is its own act"


def test_every_new_string_is_keyed_in_all_twelve_locales():
    keys = [
        "Resume pending",
        "waiting for the previous pass to finish (since {when})",
        "Qualification is declined on this machine: it is below the memory floor, so no candidate is judged.",
        "To run it anyway, restart the app with {env}=1.",
        "Check for missing ingest entries", "Record them, marked late",
        "The scan stopped at its time budget; run it again to continue.",
        "Recorded {n} entries, each marked late.",
    ]
    for loc in ("en", "fr", "de", "es", "pt", "ru", "ar", "bn", "hi", "id", "ja", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert k in data and str(data[k]).strip(), (loc, k)

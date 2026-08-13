"""
Tests for the B5 (2026-07-24 Session B) PROGRESSIVE keyword-triage sweep --
run_progressive_triage_job. Mirrors test_triage_job.py's fixture pattern (no
network, an in-memory sqlite db, a FakeCtx). Covers what the brief names
explicitly: cursor resume (across separate calls, simulating a process
restart), toggle stop/start, log append integrity across resumed calls, and
the EXPORT-ONLY no-trusted-index-writes contract re-pinned for the progressive
path too.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import triage_job as J
from src.database.models import Article, Base, Keyword, KeywordMention, Source


class FakeCtx:
    """A JobContext stand-in: cooperative stop + progress capture."""

    def __init__(self, stop_after: int | None = None) -> None:
        self._stop_after = stop_after
        self._calls = 0
        self.progress: list[tuple] = []

    @property
    def stopping(self) -> bool:
        self._calls += 1
        return self._stop_after is not None and self._calls > self._stop_after

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append((done, total, detail))


class FakeResult:
    def __init__(self, text: str):
        self.text = text
        self.total_duration = 500_000_000
        self.load_duration = 100_000_000
        self.prompt_eval_count = 20
        self.prompt_eval_duration = 50_000_000
        self.eval_count = 5
        self.eval_duration = 300_000_000


class FakeClient:
    """Answers every echoed keyword 'content', canaries 'junk' -- happy path."""

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        lines = []
        for ln in prompt.splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                term = ln[2:].split("  [")[0]
                verdict = "junk" if term in J.CANARY_EXPECTED else "content"
                lines.append(f"{term} :: {verdict} :: other")
        return FakeResult("\n".join(lines))


class RaisingClient:
    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("Ollama not reachable (simulated outage)")


class FlakyClient:
    """Raises LLMUnavailable on the first ``fail_times`` generate() calls, then
    delegates to a real FakeClient. Mirrors tests/test_ai_langdetect_resilience.py's
    ``_FlakyOllama`` (2026-07-26 field-remarks items 6/7, the retry-with-backoff fix)."""

    def __init__(self, *, fail_times: int):
        self._fail_times = fail_times
        self.calls = 0
        self._real = FakeClient()

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            from src.llm.ollama import LLMUnavailable

            raise LLMUnavailable("simulated transient outage")
        return self._real.generate(prompt, model=model, system=system, keep_alive=keep_alive)


class AlwaysRaisingHTTPErrorClient:
    """Raises the sibling LLMError (not LLMUnavailable) on every call -- e.g. a
    500 from a server that's up but erroring (plausibly a context-length
    overflow). Proves the except clause catches LLMError generally, not just
    the LLMUnavailable subclass."""

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        from src.llm.ollama import LLMError

        raise LLMError("simulated HTTP 500 from the model server")


def _fast_backoff(monkeypatch):
    """Tests must not really sleep for seconds -- shrink the backoff to milliseconds."""
    monkeypatch.setattr(J, "_TRIAGE_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(J, "_TRIAGE_BACKOFF_CAP_S", 0.02)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, n=7):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    for i in range(n):
        a = Article(
            url=f"https://src.test/{i}",
            canonical_url=f"https://src.test/{i}",
            source_id=src.id,
            title="T",
            content="c",
            hash=f"h{i}",
        )
        db.add(a)
        db.flush()
        # descending article_count so the head-scope order is deterministic and
        # every keyword clears min_articles=1 with room to spare.
        k = Keyword(
            term=f"topic{i}",
            normalized_term=f"topic{i}",
            language="en",
            article_count=n - i,
            mention_count=10,
        )
        db.add(k)
        db.flush()
        db.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, source_id=src.id))
    db.commit()


def _session_factory(db):
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        yield db

    return _scope


def _row_counts(db):
    return (
        db.query(Keyword).count(),
        db.query(KeywordMention).count(),
        db.query(Article).count(),
        db.query(Source).count(),
    )


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_progressive_sweep_completes_covering_every_head_scope_keyword(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_triage_job(
        ctx,
        model="stub:test",
        batch_size=3,
        min_articles=1,
        session_factory=scope,
        client=FakeClient(),
        state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["batches_completed"] == 3  # ceil(7/3)
    # every real keyword got a verdict + the 2 canaries ride EVERY batch
    assert res["totals"]["verdicts_out"] == 7 + 2 * 3
    assert "paused_reason" not in res

    recs = _read_jsonl(res["path"])
    assert recs[0]["schema"] == "oo-keyword-triage-run-1"
    assert recs[-1]["schema"] == "oo-keyword-triage-run-summary-1"
    assert recs[-1]["state"] == "done"


def test_progressive_sweep_resumes_from_a_persisted_cursor_across_calls(db, tmp_path):
    """Simulates a process restart: the SECOND call is a totally fresh invocation
    (a new FakeCtx, no in-memory state carried over) that must resume from the
    on-disk cursor, not re-triage what the first call already logged."""
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        max_batches=1,  # only ONE batch this call -- an early stop, not a cancel
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["batches_completed"] == 1

    # "restart the process": a brand-new FakeCtx, same state_path on disk.
    ctx2 = FakeCtx()
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["path"] == res1["path"], "a resumed sweep must APPEND to the SAME log file"
    assert res2["batches_completed"] == 3  # 1 (call 1) + 2 more (call 2) = ceil(7/3)

    # log append integrity: every line across BOTH calls parses, a resume marker
    # is present, and there is exactly ONE run header + ONE summary footer (never
    # a second header from a wrongly-fresh restart).
    recs = _read_jsonl(res2["path"])
    schemas = [r["schema"] for r in recs]
    assert schemas.count("oo-keyword-triage-run-1") == 1
    assert schemas.count("oo-keyword-triage-run-summary-1") == 1
    assert "oo-keyword-triage-resume-1" in schemas

    # no keyword was ever triaged twice (batch verdicts across the whole sweep
    # cover each real term exactly once).
    seen_terms = set()
    for r in recs:
        if r.get("schema") == "oo-keyword-triage-verdicts-1":
            for term in r.get("verdicts", {}):
                if term.startswith("topic"):
                    assert term not in seen_terms, f"{term} was triaged more than once"
                    seen_terms.add(term)
    assert seen_terms == {f"topic{i}" for i in range(7)}


def test_toggle_stop_then_start_honors_the_cursor(db, tmp_path):
    """A genuine CANCEL (ctx.stopping) leaves complete=False + a paused_reason;
    starting the toggle again (a fresh FakeCtx, same state) must continue instead
    of restarting from scratch."""
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx(stop_after=1)  # stopping() true from the 2nd check onward
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "cancelled" in res1["paused_reason"]
    assert res1["batches_completed"] == 1

    ctx2 = FakeCtx()  # "start" again
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["batches_completed"] == 3


def test_a_transient_outage_retries_and_the_sweep_completes_without_pausing(
    db, monkeypatch, tmp_path
):
    """2026-07-26 field-remarks item 7 fix: a single LLMUnavailable (or LLMError)
    on a batch must NOT pause the whole sweep -- it retries the SAME batch with
    backoff and the sweep continues, completing normally. Direct regression test
    for the reported symptom ('keyword-triage stopped after 56 batches')."""
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"
    _fast_backoff(monkeypatch)

    flaky = FlakyClient(fail_times=1)
    ctx = FakeCtx()
    res = J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=flaky, state_path=state_path,
    )
    assert res["complete"] is True
    assert "paused_reason" not in res
    assert res["batches_completed"] == 2  # ceil(4/2) -- the retried batch still counts once
    assert flaky.calls == 3, "1 failed attempt + 1 retry on batch 1, then batch 2 clean"


def test_llm_error_alongside_llm_unavailable_is_also_retried_not_a_hard_crash(
    db, monkeypatch, tmp_path
):
    """The field bug's actual likely trigger: the model server answers with an
    HTTP error (LLMError, not LLMUnavailable) -- e.g. a context-length overflow
    from the large embedded keyword batch. Today this must be caught by the SAME
    retry path as LLMUnavailable, never propagate uncaught."""
    _seed(db, n=2)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(J, "_TRIAGE_MAX_CONSECUTIVE_FAILURES", 2)
    _fast_backoff(monkeypatch)

    ctx = FakeCtx()
    with pytest.raises(RuntimeError, match="2 consecutive"):
        J.run_progressive_triage_job(
            ctx, model="stub:test", batch_size=2, min_articles=1,
            session_factory=scope, client=AlwaysRaisingHTTPErrorClient(),
            state_path=state_path,
        )


def test_after_the_configured_consecutive_failure_budget_the_job_gives_up_loudly(
    db, monkeypatch, tmp_path
):
    """Mirrors test_ai_langdetect_resilience.py::
    test_n_consecutive_failures_gives_up_loudly_never_as_done: a backend that
    never recovers must not spin forever, but the terminal outcome must be a
    genuine raise (so the outer BackgroundJob state becomes 'error'), never a
    silent, benign-looking 'done' -- and the JSONL log's own trailing summary
    must say 'error' too, so /keyword-triage/last agrees with /status."""
    _seed(db, n=2)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(J, "_TRIAGE_MAX_CONSECUTIVE_FAILURES", 3)
    _fast_backoff(monkeypatch)

    ctx = FakeCtx()
    with pytest.raises(RuntimeError, match="3 consecutive"):
        J.run_progressive_triage_job(
            ctx, model="stub:test", batch_size=2, min_articles=1,
            session_factory=scope, client=RaisingClient(), state_path=state_path,
        )

    # A resumable cursor state was still persisted (batches_completed=0 here,
    # since the very first batch never settled) -- a later start can still
    # pick this cursor up once the operator's backend recovers.
    persisted = J.load_progress_state(state_path)
    assert persisted["batches_completed"] == 0

    # find the run's own log via the persisted state (the export path isn't
    # returned from a raise) and confirm the trailing footer is honest.
    log_path = persisted["log_path"]
    recs = _read_jsonl(log_path)
    assert recs[-1]["schema"] == "oo-keyword-triage-run-summary-1"
    assert recs[-1]["state"] == "error"
    assert "3 consecutive" in recs[-1]["error"]


def test_a_genuine_cancel_during_a_retry_backoff_stops_immediately_no_further_retry(
    db, monkeypatch, tmp_path
):
    """Cancellation must never be mistaken for a transient outage and retried
    to exhaustion -- FakeCtx.stopping flips True on the very first check
    (inside the interruptible sleep helper), so the backoff wait is cut short
    and the sweep pauses as a genuine cancel, not a give-up-loudly error."""
    _seed(db, n=2)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(J, "_TRIAGE_MAX_CONSECUTIVE_FAILURES", 10_000)
    # A real (not fast) backoff would make this test slow if the cancel weren't
    # honoured promptly -- deliberately NOT calling _fast_backoff here, so a
    # regression that stops checking ctx.stopping inside the sleep would hang
    # this test for the full default backoff instead of failing fast.
    monkeypatch.setattr(J, "_TRIAGE_BACKOFF_BASE_S", 5.0)
    monkeypatch.setattr(J, "_TRIAGE_BACKOFF_CAP_S", 5.0)

    ctx = FakeCtx(stop_after=1)  # stopping() true from the 2nd check onward
    res = J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=RaisingClient(), state_path=state_path,
    )
    assert res["complete"] is False
    assert res["paused_reason"] and "cancelled" in res["paused_reason"]


def test_restart_true_discards_the_cursor_and_starts_a_fresh_log(db, tmp_path):
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is True

    ctx2 = FakeCtx()
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=2, min_articles=1, restart=True,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["path"] != res1["path"], "restart=True must start a brand-new log file"
    assert res2["complete"] is True
    assert res2["batches_completed"] == 2  # re-swept from scratch, not "0 more to do"


def test_export_only_zero_trusted_index_writes_across_the_whole_progressive_sweep(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    before = _row_counts(db)

    ctx = FakeCtx()
    J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert _row_counts(db) == before


def test_progress_reports_batches_and_a_growing_verdict_count(db, tmp_path):
    _seed(db, n=5)
    scope = _session_factory(db)

    ctx = FakeCtx()
    J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert ctx.progress[0][2] == "starting…"
    # every subsequent call reports a strictly-nondecreasing "done" count
    dones = [d for d, _t, _detail in ctx.progress if d is not None]
    assert dones == sorted(dones)


# --------------------------------------------------------------------------- #
#  A context overflow is deterministic, so it is not an outage (2026-08-13).
# --------------------------------------------------------------------------- #


class OverflowUntilSmallEnough:
    """Refuses the way vLLM refuses, until the batch fits.

    The real 400 body is quoted, because the classifier keys on the SERVER'S WORDS --
    a stub that invented its own phrasing would test the stub.
    """

    def __init__(self, *, fits_at: int):
        self._fits_at = fits_at
        self.batch_sizes: list[int] = []
        self._real = FakeClient()

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        n = sum(1 for ln in prompt.splitlines() if ln.strip().startswith("- "))
        self.batch_sizes.append(n)
        if n > self._fits_at:
            from src.llm.ollama import LLMError

            raise LLMError(
                "vLLM error: Client error '400 Bad Request' — This model's maximum "
                f"context length is 2048 tokens. However, you requested {n * 200} tokens."
            )
        return self._real.generate(prompt, model=model, system=system, keep_alive=keep_alive)


def test_an_oversized_prompt_shrinks_the_batch_instead_of_burning_the_outage_budget(
    db, tmp_path, monkeypatch
):
    """THE FIELD DEFECT. A 400 naming the context length was caught as "the backend
    might come back": ten retries of the SAME batch, 60s apart, then the whole sweep
    ended in state=error. The batch cannot get smaller by waiting.

    The cursor is untouched on failure, so halving re-selects the same keywords in a
    smaller chunk and the sweep completes covering everything.
    """
    _seed(db, n=7)
    _fast_backoff(monkeypatch)
    # Canaries ride every batch, so a "batch of 4" is 4+2 lines: fits_at=6 means the
    # 8-keyword prompt is refused and the 4-keyword one is accepted.
    client = OverflowUntilSmallEnough(fits_at=6)

    res = J.run_progressive_triage_job(
        FakeCtx(),
        model="stub:test",
        batch_size=8,
        min_articles=1,
        session_factory=_session_factory(db),
        client=client,
        state_path=tmp_path / "state.json",
    )

    assert res["complete"] is True, "the sweep must finish, not die at state=error"
    # Every real keyword still judged -- shrinking must not skip anyone.
    judged = {t for r in _read_jsonl(res["path"])
              if r.get("schema") == "oo-keyword-triage-verdicts-1"
              for t in r["verdicts"] if not t.startswith(("cookie", "subscribe"))}
    assert judged == {f"topic{i}" for i in range(7)}

    # It SHRANK rather than repeating: the first attempt is the big one, and no later
    # attempt is that size again.
    assert client.batch_sizes[0] > 6
    assert all(n <= 6 for n in client.batch_sizes[1:]), client.batch_sizes
    # And it did not spend the outage budget doing it -- ten identical retries would
    # be eleven calls at the original size before giving up.
    assert client.batch_sizes.count(client.batch_sizes[0]) == 1


def test_a_genuine_outage_still_retries_rather_than_shrinking(db, tmp_path, monkeypatch):
    """The twin, and the one that matters most: reading a connection failure as an
    overflow would shrink the batch against a backend that is simply down, and skip
    the retry that IS the right answer there. Two transient failures must still be
    ridden out at the ORIGINAL batch size."""
    _seed(db, n=4)
    _fast_backoff(monkeypatch)
    client = FlakyClient(fail_times=2)

    res = J.run_progressive_triage_job(
        FakeCtx(),
        model="stub:test",
        batch_size=4,
        min_articles=1,
        session_factory=_session_factory(db),
        client=client,
        state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["totals"]["verdicts_out"] == 4 + 2  # one batch, all four, plus canaries

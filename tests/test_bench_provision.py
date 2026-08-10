"""The bench's preflight: survey, ask, then fetch-and-bench in parallel.

Every assertion here is about a distinction the module exists to keep:

* missing vs incomplete vs unknown -- three states that call for three different
  actions, and that a boolean "is it installed" collapses into one;
* asking before downloading tens of gigabytes, with the size in the question;
* a download that failed is never benched, because a model that did not arrive would
  produce a row of errors indistinguishable from a model that arrived and is bad;
* the consumer always terminates -- a producer that raises must still close the queue,
  since a hang here looks exactly like a slow download.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading

import pytest

from src.ai_layer import bench_provision as BP


class _Ollama:
    def __init__(self, installed=(), boom: str | None = None):
        self._installed = list(installed)
        self._boom = boom

    def list_installed(self):
        if self._boom:
            raise RuntimeError(self._boom)
        return list(self._installed)


# --------------------------------------------------------------------------- #
#  survey
# --------------------------------------------------------------------------- #
def test_survey_separates_missing_from_incomplete_from_unknown(monkeypatch):
    """Three states, three repairs. A boolean would send all three to 'download it'."""
    # Keyed off the roster's own vLLM identifiers rather than a fixed sequence: a
    # positional fixture silently re-labels every row the day a model joins the roster.
    from src.llm.bench_roster import BENCH_ROSTER, identifiers_for

    vllm_models: list[str] = []
    for e in BENCH_ROSTER:
        ok, _ = identifiers_for("vllm", [e["key"]])
        vllm_models += [r["identifier"] for r in ok]
    assert len(vllm_models) >= 4, "this test needs four vLLM models to distinguish four states"
    answers = {
        vllm_models[0]: {"cached": True, "bytes": 10},
        vllm_models[1]: {"cached": False, "incomplete": "no config.json in it. Download again."},
        vllm_models[2]: {"cached": None},
    }
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.model_cache_state",
        lambda m: answers.get(m, {"cached": False}),
    )
    monkeypatch.setattr(
        BP, "_ollama_installed", lambda _c: (set(), "Ollama did not answer (refused)")
    )
    out = BP.survey(ollama_client=None)
    by_state: dict[str, int] = {}
    for r in out["models"]:
        if r["backend"] == "vllm":
            by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    assert by_state.get("ready") == 1
    assert by_state.get("incomplete") == 1
    assert by_state.get("unknown") == 1
    assert by_state.get("missing", 0) >= 1, "the rest of the roster falls through to missing"
    # The unknown one is neither queued for download nor counted as present.
    fetch_models = {r["state"] for r in out["to_fetch"]}
    assert fetch_models <= {"missing", "incomplete"}
    assert out["unknown"], "an unreadable probe is reported, not silently treated as absent"


def test_a_daemon_that_is_down_is_unknown_not_empty(monkeypatch):
    """Zero models from a live daemon and zero from a dead one are opposite facts.

    Reporting the dead case as 'missing' would offer to re-download a roster the
    operator may already hold."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": True})
    out = BP.survey(ollama_client=_Ollama(boom="connection refused"))
    ollama_rows = [r for r in out["models"] if r["backend"] == "ollama"]
    assert ollama_rows, "the roster publishes Ollama builds"
    assert all(r["state"] == "unknown" for r in ollama_rows)
    assert not [r for r in out["to_fetch"] if r["backend"] == "ollama"]


def test_a_live_daemon_with_nothing_installed_reports_missing(monkeypatch):
    """The negative-space twin of the test above: an over-eager 'unknown' would never
    offer to download anything for a working, empty Ollama."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": True})
    out = BP.survey(ollama_client=_Ollama(installed=[]))
    ollama_rows = [r for r in out["models"] if r["backend"] == "ollama"]
    assert ollama_rows and all(r["state"] == "missing" for r in ollama_rows)
    assert out["question"]["needs_download"] is True


def test_the_question_carries_the_size_and_never_downloads(monkeypatch):
    """A survey that fetched something would make the question rhetorical."""
    calls: list = []
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": False})
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.run_model_download_job",
        lambda *a, **k: calls.append(k) or {"downloaded": True},
    )
    out = BP.survey(ollama_client=_Ollama(installed=[]))
    assert not calls, "survey must never fetch"
    q = out["question"]
    assert q["needs_download"] is True
    assert q["estimated_mb"] > 0 and "GB" in q["text"]
    assert "ESTIMATE" in out["estimated_download_note"]


def test_everything_present_asks_nothing(monkeypatch):
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": True})
    from src.llm.bench_roster import BENCH_ROSTER, identifiers_for

    tags = set()
    for e in BENCH_ROSTER:
        ok, _ = identifiers_for("ollama", [e["key"]])
        tags |= {r["identifier"] for r in ok}
    out = BP.survey(ollama_client=_Ollama(installed=tags))
    assert out["to_fetch"] == []
    assert out["question"]["needs_download"] is False
    assert out["estimated_download_mb"] == 0.0


def test_survey_wakes_ollama_only_when_asked(monkeypatch):
    """A down daemon reports nothing, which reads as 'you have no models'. Waking it is
    the difference between a useful survey and a misleading one -- and it stays the
    caller's choice, so a test (or an operator who said never start a backend) can
    refuse it."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": True})
    woke: list[str] = []
    out = BP.survey(ollama_client=_Ollama(installed=[]), wake=lambda b: woke.append(b) or {"woken": True})
    assert woke == ["ollama"]
    assert out["woken"]["ollama"]["woken"] is True

    out2 = BP.survey(ollama_client=_Ollama(installed=[]))
    assert out2["woken"] == {}, "no wake callable, no wake"


# --------------------------------------------------------------------------- #
#  provision_and_bench
# --------------------------------------------------------------------------- #
def test_ready_models_are_benched_before_the_download_finishes():
    """The whole point of overlapping: first results while the rest is still arriving.

    The download blocks until the test releases it, so a sequential implementation
    would deadlock this rather than merely be slower."""
    released = threading.Event()
    benched: list[str] = []

    def slow_download(row):
        released.wait(timeout=5)
        return {"model": row["model"], "downloaded": True}

    def bench_one(pairs):
        benched.append(pairs[0])
        if len(benched) == 1:
            released.set()  # the ready model was benched while the fetch was blocked
        return {"ok": True}

    out = BP.provision_and_bench(
        [{"backend": "vllm", "model": "later"}],
        ready=[{"backend": "vllm", "model": "already-here"}],
        bench_one=bench_one,
        download=slow_download,
    )
    assert benched[0] == "vllm|already-here"
    assert benched[1] == "vllm|later"
    assert len(out["benched"]) == 2


def test_a_failed_download_is_reported_and_never_benched():
    benched: list[str] = []
    out = BP.provision_and_bench(
        [{"backend": "ollama", "model": "nope"}],
        bench_one=lambda p: benched.append(p[0]) or {"ok": True},
        download=lambda row: {"model": row["model"], "downloaded": False, "error": "gone"},
    )
    assert benched == [], "a model that never arrived must not be measured"
    assert out["downloads"][0]["error"] == "gone"


def test_a_raising_downloader_still_terminates():
    """The consumer waits on a sentinel. A producer that dies without putting it turns
    a crash into a hang, and a hang here is indistinguishable from a slow download."""
    def boom(_row):
        raise RuntimeError("disk on fire")

    out = BP.provision_and_bench(
        [{"backend": "vllm", "model": "x"}], bench_one=lambda p: {"ok": True}, download=boom
    )
    assert out["benched"] == []


def test_one_bad_pair_does_not_end_the_run():
    def bench_one(pairs):
        if pairs[0].endswith("bad"):
            raise RuntimeError("bench blew up")
        return {"ok": True}

    out = BP.provision_and_bench(
        [{"backend": "vllm", "model": "bad"}, {"backend": "vllm", "model": "good"}],
        bench_one=bench_one,
        download=lambda row: {"model": row["model"], "downloaded": True},
    )
    assert len(out["benched"]) == 2
    assert any(b.get("error") for b in out["benched"])
    assert any(b.get("report") for b in out["benched"])


def test_cancellation_stops_downloading_and_benching():
    class Ctx:
        stopping = False

    ctx = Ctx()

    def download(row):
        ctx.stopping = True   # the operator cancels during the first fetch
        return {"model": row["model"], "downloaded": True}

    out = BP.provision_and_bench(
        [{"backend": "vllm", "model": "a"}, {"backend": "vllm", "model": "b"}],
        bench_one=lambda p: pytest.fail("nothing may be benched after a cancel"),
        download=download,
        ctx=ctx,
    )
    assert len(out["downloads"]) == 1, "the second download is not started"


# --------------------------------------------------------------------------- #
#  the bundle member
# --------------------------------------------------------------------------- #
def test_the_bundle_member_produces_a_real_report_and_starts_nothing():
    """BEHAVIOURAL, not a signature check. A route that is also called directly gets
    FastAPI sentinels for its defaults, so the only guard that means anything drives
    the real member and reads what came back (the recorded ai.json lesson).

    And it must not wake the daemon: a bundle describes the machine, it does not change
    it. The cost is an honest ``unknown`` for a stopped Ollama, which is the truth."""
    from src.api.diagnostics import _bench_provision_snapshot

    out = _bench_provision_snapshot()
    assert out.get("schema") == BP.PROVISION_SCHEMA, "a real survey, not a degrade sentinel"
    assert out.get("woken") == {}, "the bundle starts no backend"
    assert isinstance(out.get("models"), list) and out["models"], "the roster was surveyed"
    assert "question" in out

"""Benching several models per backend, and the same model on both.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-10, items 1 and 2: "Ollama vs vLLM with identical models" and
"different models with vLLM and different models with Ollama".

Both were blocked by the same wrong question. ``GET /v1/models`` reports the ONE model a
vLLM server is currently serving, and the bench read that as "what is installed" -- so an
operator who had downloaded four models was told all four were not-installed, which is
the field report that started this. Availability for vLLM is the weights CACHE.

Reading downloaded weights as available creates its own hazard, and the tests below pin
it in both directions: a vLLM server answers as the model it was started with, so
benching a second downloaded model WITHOUT restarting the server would file the first
model's answers under the second's name. That is a fabricated measurement no reader
could later detect, so it is refused rather than run.
"""

from __future__ import annotations

import pytest

from src.ai_layer import model_bench as MB


# --------------------------------------------------------------------------- #
#  What "installed" means, per backend
# --------------------------------------------------------------------------- #
def test_a_downloaded_but_unserved_vllm_model_counts_as_available(monkeypatch):
    """THE FIELD REPORT. Weights on the disk, no server holding them: runnable."""
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.model_cache_state",
        lambda m: {"cached": m == "org/downloaded"},
    )
    monkeypatch.setattr(MB, "_wanted_on", lambda _b, e: (list(e), []))

    def _no_server(*_a, **_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("src.llm.vllm_client.VllmClient", _no_server)

    assert MB._vllm_available(["org/downloaded", "org/absent"]) == ["org/downloaded"]


def test_the_model_a_server_is_serving_is_available_even_if_the_cache_probe_misses_it(
    monkeypatch,
):
    """A server answering WITH a model is proof it can serve it. An operator-set HF_HOME
    can put the weights where our probe does not look, and refusing the model actually
    loaded would be the silliest possible false negative."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": False})

    class _Serving:
        def __init__(self, **_kw):
            pass

        def list_installed(self):
            return ["org/loaded"]

    monkeypatch.setattr("src.llm.vllm_client.VllmClient", _Serving)

    assert MB._vllm_available(["org/loaded"]) == ["org/loaded"]


def test_an_unreadable_cache_is_not_treated_as_downloaded(monkeypatch):
    """``model_cache_state`` returns None for "could not read the directory". Treating
    that as present sends the bench into a start that cannot work."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.model_cache_state", lambda _m: {"cached": None})

    def _no_server(*_a, **_kw):
        raise RuntimeError("down")

    monkeypatch.setattr("src.llm.vllm_client.VllmClient", _no_server)

    assert MB._vllm_available(["org/unknown"]) == []


def test_a_missing_vllm_model_is_told_to_download_not_to_pull(monkeypatch):
    """The two backends need different actions from the operator, so one sentence for
    both would send half of readers to the wrong button."""
    runnable, skipped = MB.resolve_pairs(
        models=["vllm|org/absent", "ollama|tag:absent"],
        installed_by_backend={"vllm": [], "ollama": []},
    )
    assert runnable == []
    detail = {s["backend"]: s["detail"] for s in skipped}
    assert "not downloaded for vLLM" in detail["vllm"]
    assert "Settings → AI" in detail["vllm"]
    assert "installed tag" in detail["ollama"]


# --------------------------------------------------------------------------- #
#  The hazard that comes with it
# --------------------------------------------------------------------------- #
class _Client:
    def __init__(self, served: tuple[str, ...] = ()):
        self._served = served

    def list_installed(self):
        return list(self._served)


def test_a_second_vllm_model_is_refused_rather_than_measured_as_the_first():
    """THE LOAD-BEARING NEGATIVE. Without a restart the loaded model answers, and the
    answers would be filed under a name it never ran under."""
    runnable = [
        {"backend": "vllm", "model": "org/loaded", "key": "vllm|org/loaded"},
        {"backend": "vllm", "model": "org/other", "key": "vllm|org/other"},
    ]

    kept, refused = MB._refuse_unswitchable_vllm(runnable, _Client(served=("org/loaded",)))

    assert [p["model"] for p in kept] == ["org/loaded"], "only the model that would answer"
    assert refused[0]["reason"] == "would-measure-the-wrong-model"
    assert "org/loaded" in refused[0]["detail"], "name what WOULD have answered"


def test_ollama_pairs_are_never_refused_by_that_guard():
    """Ollama loads the requested model per call, so the hazard does not exist there and
    an over-eager guard would silently halve the roster."""
    runnable = [{"backend": "ollama", "model": "a:1", "key": "ollama|a:1"}]

    kept, refused = MB._refuse_unswitchable_vllm(runnable, _Client())

    assert kept == runnable and refused == []


def test_with_switching_on_every_downloaded_vllm_model_is_kept(frozen_batch, monkeypatch):
    """The point of the whole slice: several models per backend, in one run."""
    switched: list[tuple[str, str]] = []
    report = MB.run_model_bench(
        None,
        models=["vllm|org/a", "vllm|org/b"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["org/a", "org/b"]},
        clients={"vllm": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        switch=lambda *, backend, model: switched.append((backend, model))
        or {"switched": True, "ready": True},
        unload=lambda *_a, **_kw: {"unloaded": True},
        tasks=("triage",),
        persist=False,
    )
    assert switched == [("vllm", "org/a"), ("vllm", "org/b")]
    assert sorted(report["pairs_run"]) == ["vllm|org/a", "vllm|org/b"]


def test_a_backend_that_never_came_up_is_not_recorded_as_a_model_failure(
    frozen_batch,
):
    """Five task errors under a model's name read as "this model failed". The finding is
    that the server did not start, and it has to say so."""
    report = MB.run_model_bench(
        None,
        models=["vllm|org/a"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["org/a"]},
        clients={"vllm": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        switch=lambda **_kw: {"switched": False, "ready": False, "reason": "CUDA out of memory"},
        tasks=("triage",),
        persist=False,
    )
    row = report["results"]["vllm|org/a"]
    assert row["status"] == "error"
    assert "CUDA out of memory" in row["detail"]
    assert "tasks" not in row, "nothing ran, so no task may appear to have been measured"


def test_the_card_is_handed_over_for_ollama_pairs_too(frozen_batch):
    """A vLLM server holds its allocation for its whole lifetime, so an Ollama pair
    measured beside a live one is measuring contention, when it loads at all."""
    handed: list[str] = []
    MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        switch=lambda *, backend, model: handed.append(backend) or {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert handed == ["ollama"]


# --------------------------------------------------------------------------- #
#  Ollama vs vLLM, same model
# --------------------------------------------------------------------------- #
def test_the_same_model_on_two_backends_is_recognised_through_the_roster():
    """The link is the roster entry, never string similarity: ``Qwen/Qwen3.5-0.8B`` and
    ``qwen3.5:0.8b-q8_0`` are one model because the roster publishes both."""
    mapping = MB._identifier_to_key()
    assert mapping.get("vllm|Qwen/Qwen3.5-0.8B") == "qwen35-0-8b"
    assert mapping.get("ollama|qwen3.5:0.8b-q8_0") == "qwen35-0-8b"


def test_both_sides_are_printed_with_their_own_quantization():
    results = {
        "ollama|qwen3.5:0.8b-q8_0": {
            "backend": "ollama",
            "model": "qwen3.5:0.8b-q8_0",
            "quantization": "q8_0",
            "tasks": {"triage": {"format_validity": 0.9}},
        },
        "vllm|Qwen/Qwen3.5-0.8B": {
            "backend": "vllm",
            "model": "Qwen/Qwen3.5-0.8B",
            "quantization": None,
            "tasks": {"triage": {"format_validity": 0.95}},
        },
    }

    rows = MB.same_model_across_backends(results)

    assert len(rows) == 1
    row = rows[0]
    assert row["roster_key"] == "qwen35-0-8b"
    assert row["metrics"]["triage.format_validity"]["by_backend"] == {
        "ollama": 0.9,
        "vllm": 0.95,
    }
    assert row["backends"]["ollama"]["quantization"] == "q8_0"
    assert "not one model measured twice" in row["caveat"], (
        "the reader must be told these are two builds, or a gap reads as run-to-run noise"
    )


def test_one_side_alone_is_not_a_comparison():
    results = {
        "ollama|qwen3.5:0.8b-q8_0": {
            "backend": "ollama",
            "model": "qwen3.5:0.8b-q8_0",
            "tasks": {"triage": {"format_validity": 0.9}},
        }
    }
    assert MB.same_model_across_backends(results) == []


def test_a_metric_that_did_not_run_is_absent_never_zero():
    """A task that errored and a task that measured zero are opposite findings, and a
    column of zeros reads as the model answering badly."""
    metrics = MB.comparable_metrics(
        {"tasks": {"triage": {"status": "error"}, "langdetect": {"accuracy_over_all": 0.0}}}
    )
    assert "triage.format_validity" not in metrics
    assert metrics["langdetect.accuracy_over_all"]["value"] == 0.0, "a real zero survives"


def test_every_comparable_metric_carries_its_unit():
    """Two numbers side by side with no unit is how a per-second rate gets read as a
    share."""
    for name, unit, _path in MB._COMPARABLE:
        assert unit, name


def test_the_comparison_names_no_winner():
    """No column, no delta, no ordering: the maintainer reads the table and decides."""
    results = {
        "ollama|qwen3.5:0.8b-q8_0": {
            "backend": "ollama",
            "model": "q",
            "tasks": {"triage": {"format_validity": 0.1}},
        },
        "vllm|Qwen/Qwen3.5-0.8B": {
            "backend": "vllm",
            "model": "Q",
            "tasks": {"triage": {"format_validity": 0.9}},
        },
    }
    banned = ("winner", "better", "best", "score", "ranking", "rating", "grade", "delta")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(MB.same_model_across_backends(results))


def test_the_report_carries_the_comparison(frozen_batch):
    report = MB.assemble_report(
        {},
        batch=frozen_batch,
        anchors=None,
        skipped=[],
        runnable=[],
        requested=[],
        run_id="t",
    )
    assert "same_model_across_backends" in report


# --------------------------------------------------------------------------- #
#  fixtures
# --------------------------------------------------------------------------- #
class _BenchStub:
    """Answers every listed item, so the triage parser's happy path runs without a model."""

    def __init__(self, served: tuple[str, ...] = ()):
        self._served = served

    def list_installed(self):
        return list(self._served)

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        items = [
            line[2:].split("  [")[0].strip()
            for line in prompt.splitlines()
            if line.startswith("- ")
        ]

        class _R:
            response = "\n".join(f"{t} :: content :: other" for t in items)
            prompt_eval_count = eval_count = None
            total_duration = load_duration = prompt_eval_duration = eval_duration = None

        return _R()


@pytest.fixture
def frozen_batch() -> dict:
    return {
        "digest": "d0",
        "built_at": "2026-08-10",
        "keywords": [{"term": "climate", "language": "en", "mention_count": 3, "article_count": 2}],
        "sources": [],
        "source_tag_vocabulary": [],
    }


def test_a_stopped_vllm_is_not_reported_as_an_unreachable_backend(monkeypatch):
    """This app STARTS the server, so "nothing answering" is not "cannot serve". A
    None here would put a spurious backend-unreachable row in the report, next to the
    downloaded models it is telling you it cannot run."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.is_installed", lambda: True)
    monkeypatch.setattr(MB, "_vllm_available", lambda _w: ["org/a"])

    out = MB._installed_by_backend(("vllm",), wanted=["vllm|org/a"])

    assert out["vllm"] == ["org/a"]


def test_vllm_not_installed_at_all_IS_unreachable(monkeypatch):
    """The negative-space twin: there is a real unreachable case and it must survive."""
    monkeypatch.setattr("src.llm.vllm_lifecycle.is_installed", lambda: False)

    out = MB._installed_by_backend(("vllm",), wanted=["vllm|org/a"])

    assert out["vllm"] is None
    _, skipped = MB.resolve_pairs(models=["vllm|org/a"], installed_by_backend=out)
    assert skipped[0]["reason"] == "backend-unreachable"


def test_latency_is_compared_per_prompt_shape_against_the_real_payload():
    """BUILT FROM THE REAL BUILDER, not from a hand-typed shape.

    This nearly shipped as a single ``latency.calls_per_hour`` reading a key that does
    not exist -- ``budget_translation`` reports per SHAPE, in ``budget.rows[]``. The dig
    would have returned None forever and the row would simply never have appeared,
    saying nothing about why: the silent-omission failure the ledger already names for
    resolvers that read another module's payload by an assumed key.
    """
    from src.monitoring.llm_bench import budget_translation

    real = budget_translation(
        [
            {"shape": "facts", "wall_s": {"p50": 0.5}, "ok_calls": 3},
            {"shape": "summary", "wall_s": {"p50": 2.0}, "ok_calls": 3},
        ],
        concurrency=2,
    )
    assert real["rows"], "the fixture must come from the builder, not from memory"
    # The builder reports None when no call succeeded; give it real numbers the way a
    # measured run would, keeping its own key names.
    for row in real["rows"]:
        row["per_hour"] = 100 if row["shape"] == "facts" else 25

    # ``run_llm_bench`` puts this block under "budget" (llm_bench.py, the report's own
    # assembly). Getting that nesting wrong here is how the production dig ended up one
    # level off in the first place, so the fixture mirrors the real report exactly.
    metrics = MB.comparable_metrics({"tasks": {"latency": {"budget": real}}})

    assert metrics["latency.facts.per_hour"]["value"] == 100
    assert metrics["latency.summary.per_hour"]["value"] == 25
    assert metrics["latency.facts.per_hour"]["unit"] == "per hour"
    assert not any(k == "latency.calls_per_hour" for k in metrics), (
        "a single blended latency figure would be the composite this bench refuses — "
        "a fact bundle and a 24,000-character synthesis are different work"
    )


def test_a_shape_that_never_completed_is_absent_rather_than_zero():
    """budget_translation reports per_hour None with a reason when no call succeeded."""
    metrics = MB.comparable_metrics(
        {"tasks": {"latency": {"budget": {"rows": [{"shape": "facts", "per_hour": None}]}}}}
    )
    assert metrics == {}


def test_the_cross_backend_table_carries_the_expanded_latency_rows():
    """The comparison used to loop the DECLARED table only, which would have dropped
    exactly the rows that are per-corpus data."""
    def pair(backend, per_hour):
        return {
            "backend": backend,
            "model": "m",
            "tasks": {
                "triage": {"format_validity": 0.9},
                "latency": {"budget": {"rows": [{"shape": "facts", "per_hour": per_hour}]}},
            },
        }

    rows = MB.same_model_across_backends(
        {
            "ollama|qwen3.5:0.8b-q8_0": pair("ollama", 120),
            "vllm|Qwen/Qwen3.5-0.8B": pair("vllm", 480),
        }
    )

    m = rows[0]["metrics"]
    assert m["latency.facts.per_hour"]["by_backend"] == {"ollama": 120, "vllm": 480}
    assert list(m)[0] == "triage.format_validity", "declared metrics keep their table order"


# --------------------------------------------------------------------------- #
#  Bringing the other backend up at all (field report 2026-08-10)
# --------------------------------------------------------------------------- #
def test_an_installed_but_stopped_ollama_is_woken_so_its_models_can_be_seen(monkeypatch):
    """THE FIELD DEFECT. The deep bench dropped every Ollama pair with
    "backend-unreachable" while Ollama was installed and launchable -- because nobody
    had started the daemon and the probe read that as "cannot serve". Listing models
    costs no GPU, so the wake belongs before the probe."""
    from src.llm import ollama_lifecycle as OL

    started: list[bool] = []
    monkeypatch.setenv("OO_LLM_AUTOSTART", "1")
    monkeypatch.setattr(OL, "is_running", lambda **_kw: False)
    monkeypatch.setattr(OL, "is_installed", lambda: True)
    monkeypatch.setattr(OL, "start", lambda **_kw: started.append(True) or {"started": True})

    out = MB._default_wake("ollama")

    assert started == [True]
    assert out["woken"] is True


def test_an_operator_who_turned_automatic_starts_off_is_obeyed(monkeypatch):
    """OO_LLM_AUTOSTART=0 means it here too. The suite sets it, which is also what
    stops a test run leaving a daemon behind on a developer's machine."""
    from src.llm import ollama_lifecycle as OL

    monkeypatch.setenv("OO_LLM_AUTOSTART", "0")
    monkeypatch.setattr(OL, "is_running", lambda **_kw: False)
    monkeypatch.setattr(OL, "is_installed", lambda: True)
    monkeypatch.setattr(
        OL, "start", lambda **_kw: (_ for _ in ()).throw(AssertionError("must not start"))
    )

    out = MB._default_wake("ollama")

    assert out["woken"] is False
    assert "OO_LLM_AUTOSTART=0" in out["reason"]


def test_vllm_is_never_woken_at_probe_time(monkeypatch):
    """It serves ONE model per server, so there is no model-independent "up" to reach --
    and its availability is read from the weights cache precisely so a stopped server
    is not mistaken for an empty one."""
    out = MB._default_wake("vllm")

    assert out["woken"] is False
    assert "only the Ollama daemon" in out["reason"]


def test_nothing_is_woken_when_switching_is_off(frozen_batch):
    """The negative-space twin: a run that was not given the machine must not start
    anything on it."""
    woken: list[str] = []
    MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=False,
        wake=lambda b: woken.append(b) or {"woken": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert woken == []


def test_the_wake_runs_before_the_probe_and_is_reported(frozen_batch, monkeypatch):
    """Reported because an operator who finds a daemon running afterwards deserves to
    know the bench started it."""
    order: list[str] = []
    monkeypatch.setattr(
        MB,
        "_installed_by_backend",
        lambda _b, **_kw: order.append("probe") or {"ollama": ["a:1"]},
    )
    report = MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda b: order.append(f"wake:{b}") or {"woken": True, "detail": {"started": True}},
        switch=lambda **_kw: {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert order == ["wake:ollama", "probe"], "a probe before the wake reads a stopped daemon"
    assert report["backends_woken"]["ollama"]["woken"] is True


# --------------------------------------------------------------------------- #
#  One handover per backend, and the machine put back
# --------------------------------------------------------------------------- #
def test_the_grouping_guard_actually_groups_an_interleaved_list():
    """Driven with the input it exists FOR. ``resolve_pairs`` happens to emit grouped
    output today (it iterates sorted backend names), so an end-to-end assertion alone
    would pass with this helper deleted -- a guard tested only where its subject never
    occurs."""
    interleaved = [
        {"backend": "vllm", "model": "org/a"},
        {"backend": "ollama", "model": "a:1"},
        {"backend": "vllm", "model": "org/b"},
        {"backend": "ollama", "model": "b:1"},
    ]

    out = MB._grouped_by_backend(interleaved)

    assert [p["backend"] for p in out] == ["vllm", "vllm", "ollama", "ollama"]
    # Within a backend the roster's own order survives, so one roster always produces
    # the same sequence and two runs stay comparable.
    assert [p["model"] for p in out] == ["org/a", "org/b", "a:1", "b:1"]


def test_the_card_changes_hands_once_per_backend(frozen_batch):
    """The property, end to end: every handover costs a stop and a model load, so a
    backend must never be returned to after another has had the card."""
    handed: list[str] = []
    MB.run_model_bench(
        None,
        models=["vllm|org/a", "ollama|a:1", "vllm|org/b", "ollama|b:1"],
        backends=("vllm", "ollama"),
        installed_by_backend={"vllm": ["org/a", "org/b"], "ollama": ["a:1", "b:1"]},
        clients={"vllm": _BenchStub(), "ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda *, backend, model: handed.append(backend) or {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert len(handed) == 4
    runs = [b for i, b in enumerate(handed) if i == 0 or b != handed[i - 1]]
    assert len(runs) == len(set(runs)), f"a backend was returned to: {handed}"


def test_the_machine_is_left_on_the_backend_it_was_found_on(frozen_batch, monkeypatch):
    """A bench that stops vLLM to measure Ollama and walks away has silently changed
    which backend serves every later request."""
    holders = [{"backend": "vllm", "model": "org/held"}, {"backend": "ollama", "model": None}]
    monkeypatch.setattr("src.llm.arbitration.current_holder", lambda: holders[-1])
    monkeypatch.setattr(MB, "_prior_holder", lambda: holders[0])
    handed: list[tuple] = []
    report = MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda *, backend, model: handed.append((backend, model)) or {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert handed[-1] == ("vllm", "org/held"), "the card goes back to what held it"
    assert report["backend_restored"] == {
        "backend": "vllm",
        "model": "org/held",
        "restored": True,
        "reason": None,
    }


def test_a_restore_that_fails_is_reported_rather_than_swallowed(frozen_batch, monkeypatch):
    monkeypatch.setattr("src.llm.arbitration.current_holder", lambda: {"backend": "ollama"})
    monkeypatch.setattr(MB, "_prior_holder", lambda: {"backend": "vllm", "model": "org/held"})
    report = MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda *, backend, model: {"ready": backend == "ollama", "reason": "CUDA OOM"},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert report["backend_restored"]["restored"] is False
    assert report["backend_restored"]["reason"] == "CUDA OOM"


def test_a_cold_start_is_restored_by_RELEASING_what_the_run_loaded(
    frozen_batch, monkeypatch
):
    """A machine with no backend up is a legitimate prior STATE, and restoring it means
    releasing -- not doing nothing.

    RE-POINTED 2026-08-12, deliberately, from ``test_nothing_is_restored_when_nothing_
    was_serving``, which asserted ``backend_restored is None``. That was the behaviour
    the field reported as a defect: "I did the model benchmark, and noticed the last
    model didn't unload from memory." Reading the prior holder as *nothing to do* left
    the final benched model resident -- five minutes of Ollama residency, or a vLLM
    server's whole lifetime -- and the next thing to want the GPU found it occupied.

    The docstring's original premise is PRESERVED and still asserted below: nothing is
    handed TO a backend that was never up. What changed is that the run cleans up after
    itself instead of walking away.
    """
    monkeypatch.setattr(MB, "_prior_holder", lambda: None)
    released = []
    monkeypatch.setattr(
        "src.llm.arbitration.release_backend",
        lambda b: released.append(b) or {"backend": b, "released": True, "method": "stub"},
    )
    handed = []
    report = MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda *, backend, model: handed.append((backend, model)) or {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    note = report["backend_restored"]
    assert note is not None, (
        "a cold start must still REPORT what it did at the end -- silence here is what "
        "let the last benched model stay resident with nothing saying so"
    )
    assert note["action"] == "release", (
        "the run loaded a model onto an idle machine, so putting the machine back means "
        "releasing it. Got: " + repr(note)
    )
    assert note["prior"] is None and note["restored"] is True
    assert released == ["vllm", "ollama"], (
        "both backends are asked to let go -- the run may have loaded either. Got: "
        + repr(released)
    )
    # THE ORIGINAL PROPERTY, unchanged: the only handover is the one the bench itself
    # needed. A second call here would mean the machine was handed INTO a state it
    # never had, which is the failure the old test was written to catch.
    assert handed == [("ollama", "a:1")], (
        "nothing may be started that was not up before the run. Got: " + repr(handed)
    )


def test_a_pair_that_died_at_the_handover_is_counted_at_the_top_level(frozen_batch):
    """"complete" over a table of pairs that never got the card reads as "these models
    were tested and did badly"."""
    report = MB.run_model_bench(
        None,
        models=["vllm|org/a"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["org/a"]},
        clients={"vllm": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda **_kw: {"ready": False, "reason": "serving org/other"},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    failures = report["handover_failures"]
    assert [f["key"] for f in failures] == ["vllm|org/a"]
    assert failures[0]["reason"] == "serving org/other"


def test_a_run_where_every_pair_worked_reports_no_handover_failures(frozen_batch):
    """The negative-space twin: the field's own shape must not become the only one
    this reports."""
    report = MB.run_model_bench(
        None,
        models=["vllm|org/a"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["org/a"]},
        clients={"vllm": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda **_kw: {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert report["handover_failures"] == []
    assert report["pairs_run"] == ["vllm|org/a"]


def test_the_restore_says_what_it_is_doing_so_a_cancel_is_not_a_mystery(frozen_batch, monkeypatch):
    """Putting the card back costs a model load, so a cancel can sit for tens of
    seconds. Shortening it would leave the machine rearranged; the honest answer is to
    say what the wait is for."""
    monkeypatch.setattr("src.llm.arbitration.current_holder", lambda: {"backend": "ollama"})
    monkeypatch.setattr(MB, "_prior_holder", lambda: {"backend": "vllm", "model": "org/held"})
    lines: list[str] = []

    class _Ctx:
        stopping = False

        # Pinned to the real JobContext below rather than guessed at: a double that
        # invents an arity is how a test comes to assert a bug (2026-08-10).
        def set_progress(self, *, done=None, total=None, detail=None):
            lines.append(detail)

    import inspect

    from src.jobs.background import JobContext

    def _shape(fn):
        # Names and KINDS, not annotations: the double must be callable everywhere the
        # real one is, which is what a caller depends on.
        return [(p.name, p.kind, p.default is inspect.Parameter.empty)
                for p in inspect.signature(fn).parameters.values()]

    assert _shape(_Ctx.set_progress) == _shape(JobContext.set_progress), (
        "the double must be callable exactly where the real context is, or it describes "
        "a context that cannot exist"
    )

    MB.run_model_bench(
        _Ctx(),
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda **_kw: {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert any("putting the card back on vllm" in ln for ln in lines), lines


def test_a_vllm_whose_model_could_not_be_read_is_left_alone_rather_than_guessed(
    frozen_batch, monkeypatch
):
    """Restarting it on the DEFAULT would put the machine on a model it was not on --
    a silent change, which is worse than a stated gap."""
    monkeypatch.setattr("src.llm.arbitration.current_holder", lambda: {"backend": "ollama"})
    monkeypatch.setattr(MB, "_prior_holder", lambda: {"backend": "vllm", "model": None})
    handed: list = []
    report = MB.run_model_bench(
        None,
        models=["ollama|a:1"],
        backends=("ollama",),
        installed_by_backend={"ollama": ["a:1"]},
        clients={"ollama": _BenchStub()},
        batch=frozen_batch,
        anchors=None,
        allow_backend_switch=True,
        wake=lambda _b: {"woken": False, "reason": "already running"},
        switch=lambda *, backend, model: handed.append(backend) or {"ready": True},
        unload=lambda *_a, **_kw: {},
        tasks=("triage",),
        persist=False,
    )
    assert handed == ["ollama"], "no vLLM restart was attempted on a guess"
    note = report["backend_restored"]
    assert note["restored"] is False
    assert "could not be read" in note["reason"] and "left alone" in note["reason"]


def test_a_partly_downloaded_vllm_model_is_named_as_such(monkeypatch):
    """"Never downloaded" and "downloaded and unusable" need opposite repairs.

    The field run skipped google/gemma-3n-E2B-it with "its weights are not in the model
    cache" while several GB of it sat on the disk missing only config.json — the
    operator would have re-downloaded it without learning where the space went.
    """
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.model_cache_state",
        lambda _m: {"cached": False, "incomplete": "no config.json in it. Download it again."},
    )
    _runnable, skipped = MB.resolve_pairs(
        models=["vllm|org/Half-Fetched"], installed_by_backend={"vllm": []}
    )
    detail = next(s["detail"] for s in skipped if s["model"] == "org/Half-Fetched")
    assert "config.json" in detail
    assert "not in the model cache" not in detail, "that wording is for a model never fetched"


def test_a_never_downloaded_vllm_model_keeps_the_plain_wording(monkeypatch):
    """The negative-space twin: an over-eager 'incomplete' would mislabel every
    model that was simply never fetched."""
    monkeypatch.setattr(
        "src.llm.vllm_lifecycle.model_cache_state",
        lambda _m: {"cached": False, "incomplete": None},
    )
    _runnable, skipped = MB.resolve_pairs(
        models=["vllm|org/Never-Fetched"], installed_by_backend={"vllm": []}
    )
    detail = next(s["detail"] for s in skipped if s["model"] == "org/Never-Fetched")
    assert "not in the model cache" in detail
    assert "config.json" not in detail

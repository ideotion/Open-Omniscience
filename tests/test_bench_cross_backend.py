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

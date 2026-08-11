"""The comparative model bench (2026-08-01 rulings 14-16).

The bench exists to answer "does the ruled default model deserve to stay the
default?" with a measurement. That only works if every model answered the SAME
questions, so most of what is asserted below is about the FROZEN inputs and the
refusals that protect them — a bench that silently re-sampled between models
would produce a table that looks comparable and is not.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.ai_layer import bench_batch as BB
from src.ai_layer import model_bench as MB


# --------------------------------------------------------------------------- #
#  Stubs.
# --------------------------------------------------------------------------- #
class _R:
    def __init__(self, text: str) -> None:
        self.text = text
        self.total_duration = 1_000_000_000
        self.load_duration = 0
        self.prompt_eval_count = 10
        self.prompt_eval_duration = 100_000_000
        self.eval_count = 5
        self.eval_duration = 400_000_000


class _Stub:
    """Echoes a well-formed answer for every item the prompt lists, so the parser's
    happy path runs end to end without a model."""

    def __init__(
        self,
        *,
        verdict: str = "content",
        kind: str = "other",
        tag: str | None = None,
        installed: tuple[str, ...] = (),
    ):
        self.verdict, self.kind, self.tag = verdict, kind, tag
        # Part of the LlmBackend protocol, and the bench now asks it which model will
        # ANSWER (a vLLM server serves exactly one). A double without it describes a
        # client that could not exist.
        self.installed = installed
        self.calls: list[tuple[str, str | None]] = []

    def list_installed(self) -> list[str]:
        return list(self.installed)

    @staticmethod
    def _listed(prompt: str) -> list[str]:
        out = []
        for line in prompt.splitlines():
            if line.startswith("- "):
                out.append(line[2:].split("  [")[0].strip())
        return out

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.calls.append((model, keep_alive))
        items = self._listed(prompt)
        if "assigning topical TAGS" in (system or ""):
            body = "\n".join(f"{d} :: {self.tag or 'none'}" for d in items)
        else:
            body = "\n".join(f"{t} :: {self.verdict} :: {self.kind}" for t in items)
        return _R(body)


class _Ctx:
    def __init__(self, stop_after: int | None = None) -> None:
        self._stop = False
        self.calls = 0
        self.stop_after = stop_after
        self.details: list[str] = []

    @property
    def stopping(self) -> bool:
        return self._stop

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.calls += 1
        if detail:
            self.details.append(detail)
        if self.stop_after and self.calls >= self.stop_after:
            self._stop = True


def _rows(n=40, langs=("en", "fr", "ar")):
    return [
        {
            "term": f"{lang}-term-{i}",
            "language": lang,
            "article_count": 1000 - i,
            "mention_count": 2000 - i,
        }
        for lang in langs
        for i in range(n)
    ]


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(BB, "bench_dir", lambda: tmp_path)
    monkeypatch.setattr(MB.BB, "bench_dir", lambda: tmp_path)
    return BB.build_frozen_batch(
        keywords=_rows(),
        sources=[
            {"domain": "a.example", "article_count": 30, "mention_count": 90,
             "top_terms": ["election", "parliament"]},
        ],
        source_tag_vocabulary=["politics", "science"],
        target_size=12,
    )


# --------------------------------------------------------------------------- #
#  The frozen batch: stratification + strict validation.
# --------------------------------------------------------------------------- #
def test_languages_get_equal_quotas_so_a_small_language_is_still_readable() -> None:
    """Proportional shares would reproduce the corpus's own skew inside the bench,
    leaving exactly the languages the roster is being questioned about with an n too
    small to read."""
    rows = [{"term": f"en-{i}", "language": "en", "article_count": 100 - i} for i in range(200)]
    rows += [{"term": f"ar-{i}", "language": "ar", "article_count": 50 - i} for i in range(20)]
    selected, strata = BB.stratify_keywords(rows, target_size=30)
    by = {s["language"]: s["n"] for s in strata}
    assert by["ar"] == by["en"] == 15, by
    assert len(selected) == 30


def test_a_language_that_cannot_fill_its_quota_gives_the_remainder_back() -> None:
    rows = [{"term": f"en-{i}", "language": "en", "article_count": 9} for i in range(100)]
    rows += [{"term": "ar-only", "language": "ar", "article_count": 5}]
    selected, strata = BB.stratify_keywords(rows, target_size=20)
    assert len(selected) == 20, "the batch still reaches its size when the corpus can supply it"
    assert {s["language"]: s["n"] for s in strata} == {"ar": 1, "en": 19}


def test_the_batch_falls_short_honestly_rather_than_repeating_a_term() -> None:
    rows = [{"term": f"en-{i}", "language": "en", "article_count": 1} for i in range(5)]
    selected, _ = BB.stratify_keywords(rows, target_size=50)
    assert len(selected) == 5
    assert len({k["term"] for k in selected}) == 5, "a short corpus is short, never padded"


def test_both_head_and_tail_are_sampled() -> None:
    """A bench drawn only from the head would flatter every model: junk concentrates
    in the low-spread tail, which is where triage has to earn its keep."""
    rows = [{"term": f"en-{i:03d}", "language": "en", "article_count": 500 - i} for i in range(100)]
    selected, strata = BB.stratify_keywords(rows, target_size=10)
    assert strata[0]["n_head"] > 0 and strata[0]["n_tail"] > 0
    spreads = [k["article_count"] for k in selected]
    assert max(spreads) >= 495 and min(spreads) <= 450


def test_stratification_is_deterministic() -> None:
    rows = _rows()
    a, _ = BB.stratify_keywords(rows, target_size=17)
    b, _ = BB.stratify_keywords(list(reversed(rows)), target_size=17)
    assert [k["term"] for k in a] == [k["term"] for k in b]


@pytest.mark.parametrize(
    "bad",
    [
        {"term": "", "article_count": 1},
        {"term": "x", "article_count": 2.9},
        {"term": "x", "article_count": True},
        {"term": "x", "article_count": -1},
        {"term": "x", "language": 7},
    ],
)
def test_a_malformed_row_is_refused_loudly_not_coerced(bad) -> None:
    """int(2.9) == 2 and int(True) == 1 both land a wrong number that looks perfectly
    valid to every reader downstream."""
    with pytest.raises(BB.BenchArtifactError):
        BB.build_frozen_batch(keywords=[bad])


def test_terms_that_differ_only_by_case_are_disclosed_not_dropped() -> None:
    """The triage parser refuses to guess between them — correct, and a fact about
    this batch whoever reads the numbers should know."""
    b = BB.build_frozen_batch(
        keywords=[{"term": "WHO", "language": "en"}, {"term": "who", "language": "en"}],
        target_size=2,
    )
    assert b["normalized_collisions"] == [["WHO", "who"]]


def test_the_digest_covers_the_questions_and_ignores_the_timestamp() -> None:
    """Rebuilding the same selection must not read as a different batch, or the resume
    guard would refuse a run whose inputs never moved."""
    kws = _rows(5)
    a = BB.build_frozen_batch(keywords=kws, target_size=6)
    b = BB.build_frozen_batch(keywords=kws, target_size=6)
    assert a["digest"] == b["digest"]
    c = BB.build_frozen_batch(keywords=_rows(5, langs=("en", "fr", "de")), target_size=6)
    assert c["digest"] != a["digest"], "different questions must read as a different batch"


def test_an_edited_batch_file_is_refused_on_load(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(BB, "bench_dir", lambda: tmp_path)
    payload = BB.build_frozen_batch(keywords=_rows(4), target_size=6)
    BB.save_frozen_batch(payload)
    p = tmp_path / "frozen-batch.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["keywords"].append({"term": "smuggled-in", "language": "en"})
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BB.BenchArtifactError, match="edited"):
        BB.load_frozen_batch()


def test_a_missing_batch_says_why_it_matters(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(BB, "bench_dir", lambda: tmp_path)
    with pytest.raises(BB.BenchArtifactError, match="fresh batch per model"):
        BB.load_frozen_batch()


# --------------------------------------------------------------------------- #
#  Anchors.
# --------------------------------------------------------------------------- #
def test_anchors_refuse_an_unknown_grade_rather_than_snapping_it_to_a_near_one() -> None:
    with pytest.raises(BB.BenchArtifactError, match="verdict"):
        BB.build_anchors([{"term": "x", "verdict": "rubbish"}])
    with pytest.raises(BB.BenchArtifactError, match="kind"):
        BB.build_anchors([{"term": "x", "verdict": "content", "kind": "company"}])


def test_a_term_graded_twice_is_refused_not_silently_overwritten() -> None:
    with pytest.raises(BB.BenchArtifactError, match="graded twice"):
        BB.build_anchors(
            [{"term": "x", "verdict": "junk"}, {"term": "x", "verdict": "content"}]
        )


def test_a_content_grade_without_a_kind_is_allowed() -> None:
    """One fewer kind case is honest; an invented kind is not."""
    out = BB.build_anchors([{"term": "x", "verdict": "content"}])
    assert out["anchors"]["x"] == {"verdict": "content"}


def test_anchor_candidates_come_from_the_batch_and_span_it(frozen) -> None:
    cands = BB.anchor_candidates(frozen, 4)
    terms = {k["term"] for k in frozen["keywords"]}
    assert len(cands) == 4 and {c["term"] for c in cands} <= terms
    assert cands[0]["term"] != cands[-1]["term"]


# --------------------------------------------------------------------------- #
#  Roster resolution.
# --------------------------------------------------------------------------- #
def test_a_model_missing_on_one_backend_still_runs_on_the_other() -> None:
    runnable, skipped = MB.resolve_pairs(
        models=["mistral:7b", "ghost:9b"],
        installed_by_backend={"ollama": ["mistral:7b"], "vllm": ["mistral:7b", "ghost:9b"]},
    )
    assert {p["key"] for p in runnable} == {"ollama|mistral:7b", "vllm|mistral:7b", "vllm|ghost:9b"}
    assert [s["reason"] for s in skipped] == ["not-installed"]
    assert skipped[0]["backend"] == "ollama" and skipped[0]["model"] == "ghost:9b"


def test_an_unreachable_backend_is_a_different_fact_from_a_missing_model() -> None:
    _, skipped = MB.resolve_pairs(
        models=["mistral:7b"], installed_by_backend={"ollama": ["mistral:7b"], "vllm": None}
    )
    assert [(s["backend"], s["reason"]) for s in skipped] == [("vllm", "backend-unreachable")]


def test_a_near_tag_is_never_substituted() -> None:
    """Benching 'the closest installed thing' would report numbers under a model name
    that never ran."""
    runnable, skipped = MB.resolve_pairs(
        models=["mistral:7b"], installed_by_backend={"ollama": ["mistral:7b-instruct-q4_K_M"]}
    )
    assert runnable == []
    assert skipped[0]["reason"] == "not-installed"


#: What the operator's GPU machine actually holds after ticking four boxes in the
#: Settings panel: vLLM serving, its own downloads present, no Ollama daemon at all.
_FIELD_MACHINE = {
    "vllm": [
        "mistralai/Ministral-3-3B-Instruct-2512",
        "Qwen/Qwen3.5-0.8B",
        "google/gemma-3n-E2B-it",
        "microsoft/Phi-4-mini-instruct",
        "LiquidAI/LFM2.5-1.2B-Instruct",
    ],
    "ollama": None,
}


def test_a_roster_key_resolves_to_each_backends_own_identifier() -> None:
    """The same model is a different string on each backend.

    ``qwen35-0-8b`` is ``Qwen/Qwen3.5-0.8B`` to vLLM and ``qwen3.5:0.8b-q8_0`` to
    Ollama; a bench that carried one string to both would ask each backend for the
    other's name.
    """
    runnable, _ = MB.resolve_pairs(
        models=["qwen35-0-8b"],
        installed_by_backend={
            "vllm": ["Qwen/Qwen3.5-0.8B"],
            "ollama": ["qwen3.5:0.8b-q8_0"],
        },
    )
    assert {p["key"] for p in runnable} == {
        "vllm|Qwen/Qwen3.5-0.8B",
        "ollama|qwen3.5:0.8b-q8_0",
    }


def test_the_default_roster_finds_the_models_this_machine_downloaded() -> None:
    """The field report, as a fixture.

    Every model the operator installed through the panel is benched, under the name
    the panel installed it as.
    """
    runnable, _ = MB.resolve_pairs(
        models=list(MB.DEFAULT_ROSTER), installed_by_backend=_FIELD_MACHINE
    )
    assert {p["model"] for p in runnable} == set(_FIELD_MACHINE["vllm"])


def test_no_ollama_tag_is_ever_reported_as_not_installed_on_vllm() -> None:
    """The defect itself: an instruction the operator cannot carry out.

    "vllm - gemma4:e4b - not-installed" is true and useless. vLLM serves Hugging Face
    repositories; an Ollama tag is not a thing it could ever have installed, so telling
    somebody to install the exact tag on vLLM asks for the impossible.
    """
    _, skipped = MB.resolve_pairs(
        models=list(MB.DEFAULT_ROSTER), installed_by_backend=_FIELD_MACHINE
    )
    for s in skipped:
        if s["backend"] == "vllm" and s.get("model"):
            assert "/" in s["model"], f"{s['model']!r} is not a Hugging Face repository id"


def test_a_model_the_operator_did_not_download_is_still_reported() -> None:
    """The negative-space twin.

    A fix that made the skipped list empty would be silence, not a fix -- a model that
    is genuinely absent must still be named, by its real identifier on this backend.
    """
    _, skipped = MB.resolve_pairs(
        models=list(MB.DEFAULT_ROSTER), installed_by_backend=_FIELD_MACHINE
    )
    missing = {s["model"] for s in skipped if s["reason"] == "not-installed"}
    assert "HuggingFaceTB/SmolLM3-3B" in missing
    assert "LiquidAI/LFM2.5-1.2B-Base" in missing


def test_no_build_for_a_backend_is_a_different_fact_from_no_download() -> None:
    """SmolLM3 has no Ollama tag at all; nobody can install it there.

    Reporting that as "not-installed" would send the operator looking for a download
    that does not exist.
    """
    _, skipped = MB.resolve_pairs(
        models=["smollm3-3b"],
        installed_by_backend={"ollama": [], "vllm": []},
    )
    by_backend = {s["backend"]: s for s in skipped}
    assert by_backend["ollama"]["reason"] == "not-published-for-backend"
    assert by_backend["ollama"]["roster_key"] == "smollm3-3b"
    assert by_backend["vllm"]["reason"] == "not-installed"


def test_a_bare_tag_is_still_asked_of_every_backend() -> None:
    """``extra_models`` is the operator typing a verified tag we have no roster row for.

    We do not know which backend they meant, and guessing from the string's shape would
    be inventing a rule, so it goes to both -- unchanged from before this fix.
    """
    runnable, skipped = MB.resolve_pairs(
        models=["some/hand-verified-repo"],
        installed_by_backend={"vllm": ["some/hand-verified-repo"], "ollama": []},
    )
    assert [p["key"] for p in runnable] == ["vllm|some/hand-verified-repo"]
    assert [(s["backend"], s["reason"]) for s in skipped] == [("ollama", "not-installed")]


def test_the_same_weights_on_two_backends_are_two_rows_never_one() -> None:
    runnable, _ = MB.resolve_pairs(
        models=["mistral:7b"], installed_by_backend={"ollama": ["mistral:7b"], "vllm": ["mistral:7b"]}
    )
    assert len({p["key"] for p in runnable}) == 2


def test_quantization_is_read_off_the_tag_and_never_guessed() -> None:
    assert MB.quantization_of("ministral-3:8b-instruct-2512-q4_K_M") == "q4_K_M"
    assert MB.quantization_of("mistralai/Ministral-3-3B-Instruct-2512") is None


def _norm(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def test_an_unresolved_candidate_is_a_note_not_an_invented_tag() -> None:
    """Writing a guessed tag into the roster would be a fabricated catalog entry.

    The needle is DERIVED from ``UNRESOLVED_CANDIDATES`` rather than hardcoded, because
    the hardcoded version ("lfm" must not appear) fired on the LFM2.5-1.2B roster keys
    -- which are a DIFFERENT, page-verified model that the maintainer added on purpose.
    A substring is only as meaningful as its uniqueness, and that one had stopped
    testing the property it was named for.
    """
    assert any("LFM2.5-8B-A1B" in c["named"] for c in MB.UNRESOLVED_CANDIDATES)
    entries = [_norm(e) for e in MB.DEFAULT_ROSTER]
    for candidate in MB.UNRESOLVED_CANDIDATES:
        # Drop the vendor word: what must never appear is the MODEL nobody verified.
        needle = _norm(candidate["named"].split(" ", 1)[-1])
        assert needle, candidate
        assert not any(needle in e for e in entries), (
            f"{candidate['named']!r} is unresolved and must travel as a note, "
            "never as a roster entry"
        )


def test_every_roster_entry_has_a_provenance_and_none_was_hand_typed() -> None:
    """Three legal shapes, and nothing else.

    This is the anti-fabrication guard the substring above was reaching for. A bench
    entry is either a key of the verified download roster, a backend-qualified tag from
    the ruled list, or an incumbent read from the app's own constants -- so a model name
    cannot enter the bench without somebody having verified it somewhere.
    """
    from src.llm.bench_roster import BENCH_ROSTER

    keys = {e["key"] for e in BENCH_ROSTER}
    for entry in MB.DEFAULT_ROSTER:
        assert entry in keys or "|" in entry, entry
        if "|" in entry:
            backend, _, identifier = entry.partition("|")
            assert backend in MB.BENCH_BACKENDS, entry
            assert identifier, entry


def test_the_bench_asks_for_what_the_download_panel_installs() -> None:
    """The two catalogues must not drift apart again.

    They had: the panel offered Qwen3.5-0.8B / Gemma-3n / Phi-4 / LFM2.5 while the bench
    asked for qwen3.5:4b / gemma4:e4b / mistral:7b / granite4.1, so an operator could
    download four models through the app and have the bench report all four of its own
    names as not-installed.
    """
    from src.llm.bench_roster import BENCH_ROSTER

    for entry in BENCH_ROSTER:
        assert entry["key"] in MB.DEFAULT_ROSTER, (
            f"{entry['key']} can be installed from Settings but the bench never asks for it"
        )


# --------------------------------------------------------------------------- #
#  The tasks.
# --------------------------------------------------------------------------- #
def test_the_triage_task_reports_each_metric_alone(frozen) -> None:
    out = MB._task_triage(
        _Stub(verdict="content", kind="org"), model="m", batch=frozen, anchors=None,
        keep_alive=None, chunk=5,
    )
    assert out["status"] == "ok"
    assert out["keywords_in"] >= len(frozen["keywords"])
    assert out["format_validity"] == 1.0
    assert out["pct_unsure"] == 0.0
    assert out["canary"]["ok"] is False, "the stub calls the known-junk canaries content"
    assert out["anchor_accuracy"]["status"] == "unmeasured"


def test_anchor_accuracy_is_measured_when_a_sitting_exists(frozen) -> None:
    term = frozen["keywords"][0]["term"]
    anchors = BB.build_anchors([{"term": term, "verdict": "junk"}])
    out = MB._task_triage(
        _Stub(verdict="content"), model="m", batch=frozen, anchors=anchors,
        keep_alive=None, chunk=50,
    )
    acc = out["anchor_accuracy"]
    assert acc["n_anchors"] == 1 and acc["junk_recall"] == 0.0


def test_an_ungraded_anchor_set_reads_as_unmeasured_never_as_a_pass(frozen) -> None:
    """'No anchors' must not present as perfect accuracy — that is the fabricated-pass
    shape this project refuses everywhere else."""
    out = MB._task_triage(
        _Stub(), model="m", batch=frozen, anchors={"anchors": {}}, keep_alive=None, chunk=50
    )
    assert out["anchor_accuracy"]["status"] == "unmeasured"


def test_the_source_tag_task_reports_none_apart_from_a_failure_to_answer(frozen) -> None:
    out = MB._task_source_tags(_Stub(tag="politics"), model="m", batch=frozen, keep_alive=None)
    assert out["status"] == "ok"
    assert out["assigned"] >= 1 and out["answered_none"] == 0
    out2 = MB._task_source_tags(_Stub(tag=None), model="m", batch=frozen, keep_alive=None)
    assert out2["answered_none"] >= 1 and out2["assigned"] == 0
    assert out2["format_validity"] == 1.0, "answering 'none' IS an answer"


def test_the_source_tag_task_is_unmeasured_without_a_vocabulary() -> None:
    batch = BB.build_frozen_batch(keywords=_rows(3), target_size=3)
    out = MB._task_source_tags(_Stub(), model="m", batch=batch, keep_alive=None)
    assert out["status"] == "unmeasured" and "vocabulary" in out["reason"]


def test_langdetect_separates_a_refusal_from_a_wrong_answer() -> None:
    pytest.importorskip("httpx")

    class _Refuser:
        def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
            return _R("I cannot tell.")

    out = MB._task_langdetect(_Refuser(), model="m", keep_alive=None)
    assert out["refused"] == out["n"] and out["wrong"] == 0
    assert out["accuracy_over_answered"] is None, "no answers means no accuracy, never 0.0"
    assert out["accuracy_over_all"] == 0.0
    assert "FLOOR" in out["caveat"]


# --------------------------------------------------------------------------- #
#  The run.
# --------------------------------------------------------------------------- #
def _run(frozen, ctx=None, **kw):
    stub = _Stub(tag="politics")
    kw.setdefault("models", ["m1", "m2"])
    kw.setdefault("backends", ("ollama",))
    kw.setdefault("installed_by_backend", {"ollama": ["m1", "m2"]})
    kw.setdefault("clients", {"ollama": stub})
    kw.setdefault("tasks", ("triage", "source_tags"))
    kw.setdefault("anchors", None)
    return MB.run_model_bench(ctx or _Ctx(), batch=frozen, **kw), stub


def test_every_pair_answers_the_same_frozen_batch(frozen) -> None:
    report, _ = _run(frozen)
    assert report["status"] == "complete"
    assert set(report["pairs_run"]) == {"ollama|m1", "ollama|m2"}
    digests = {r["batch_digest"] for r in report["results"].values()}
    assert digests == {frozen["digest"]}


def test_a_cancelled_run_keeps_what_it_measured_and_resumes(frozen) -> None:
    report, _ = _run(frozen, ctx=_Ctx(stop_after=3))
    assert report["status"] == "cancelled"
    assert report["pairs_pending"], "the unmeasured pair is named, not silently absent"
    resumed, _ = _run(frozen)
    assert resumed["status"] == "complete" and not resumed["pairs_pending"]


def test_a_resume_over_a_CHANGED_batch_is_refused(frozen, tmp_path) -> None:
    _run(frozen, ctx=_Ctx(stop_after=3))
    moved = BB.build_frozen_batch(keywords=_rows(9), target_size=9)
    assert moved["digest"] != frozen["digest"]
    report, _ = _run(moved)
    assert report["status"] == "refused" and report["reason"] == "frozen-batch-changed"
    assert "two different question sets" in report["detail"]


def test_restart_ignores_the_saved_cursor(frozen) -> None:
    _run(frozen, ctx=_Ctx(stop_after=3))
    moved = BB.build_frozen_batch(keywords=_rows(9), target_size=9)
    report, _ = _run(moved, restart=True)
    assert report["status"] == "complete"


def test_the_model_is_unloaded_before_the_next_one_is_measured(frozen) -> None:
    """Ruling 16: all tasks for one pair, then free it — never two models resident
    while one of them is being timed."""
    _, stub = _run(frozen)
    assert ("m1", "0") in stub.calls, "an Ollama pair ends with a keep_alive=0 unload"
    first_m2 = next(i for i, (m, _k) in enumerate(stub.calls) if m == "m2")
    last_m1 = max(i for i, (m, _k) in enumerate(stub.calls) if m == "m1")
    assert last_m1 < first_m2, "m1 finished entirely before m2 was loaded"


def test_a_failing_task_never_costs_the_whole_pair(frozen) -> None:
    class _Broken(_Stub):
        def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
            if "assigning topical TAGS" in (system or ""):
                raise RuntimeError("boom")
            return super().generate(prompt, model=model, system=system, keep_alive=keep_alive)

    report, _ = _run(frozen, clients={"ollama": _Broken(tag="politics")}, models=["m1"],
                     installed_by_backend={"ollama": ["m1"]})
    tasks = report["results"]["ollama|m1"]["tasks"]
    assert tasks["triage"]["status"] == "ok"
    assert tasks["source_tags"]["status"] == "error", "the failure is reported, not silently absent"


def test_vllm_is_not_restarted_unless_the_operator_allows_it(frozen) -> None:
    switched: list[str] = []
    report, _ = _run(
        frozen,
        models=["m1"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["m1"]},
        clients={"vllm": _Stub(tag="politics", installed=("m1",))},
        switch=lambda *, backend, model: switched.append(model) or {"switched": True},
    )
    assert switched == [], "restarting the operator's server is not a bench's decision to make"
    note = report["results"]["vllm|m1"]["backend_switch"]
    assert note["switched"] is False and "one model per server" in note["reason"]

    report2, _ = _run(
        frozen,
        restart=True,
        models=["m1"],
        backends=("vllm",),
        installed_by_backend={"vllm": ["m1"]},
        clients={"vllm": _Stub(tag="politics", installed=("m1",))},
        allow_backend_switch=True,
        switch=lambda *, backend, model: switched.append(model) or {"switched": True},
    )
    assert switched == ["m1"]
    assert report2["results"]["vllm|m1"]["backend_switch"]["switched"] is True


def test_the_report_carries_no_composite_and_no_winner(frozen) -> None:
    report, _ = _run(frozen)
    banned = ("score", "ranking", "rating", "grade", "winner", "best", "overall_")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).lower()
                assert not any(b in key for b in banned), f"{path}.{k} looks like a verdict"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(report)
    assert report["pairwise_verdict_agreement"] is not None
    assert "not either being right" in report["caveat"]


def test_the_report_states_which_pairs_could_not_run_and_why(frozen) -> None:
    report, _ = _run(
        frozen, models=["m1", "ghost"], installed_by_backend={"ollama": ["m1"], "vllm": None}
    )
    reasons = {(s["backend"], s["reason"]) for s in report["skipped"]}
    assert ("ollama", "not-installed") in reasons
    assert ("vllm", "backend-unreachable") in reasons


# --------------------------------------------------------------------------- #
#  The canary breach carries its denominator (2026-08-11)
# --------------------------------------------------------------------------- #
#
# A field run had Ministral fail 2 of 36 canary slots and three other models fail
# 36 of 36. All four rendered as the words "canary FAILED". `ok` stays strict --
# a canary exists to say "stop trusting this run" -- but a bench whose purpose is
# telling models apart cannot publish the breach without its n.


def test_a_canary_breach_is_reported_with_its_denominator(frozen) -> None:
    out = MB._task_triage(
        _Stub(verdict="content", kind="org"), model="m", batch=frozen, anchors=None,
        keep_alive=None, chunk=5,
    )
    can = out["canary"]
    assert can["ok"] is False
    assert can["checked"] > 0, "the number of canary slots ASKED must be published"
    assert can["failed_n"] == len(can["failed"])
    assert can["failed_n"] <= can["checked"], "more failures than slots is impossible"
    # The denominator has to scale with the run, or it is not a denominator: one
    # canary pair per batch, and the batch count comes from the chunk size.
    assert can["checked"] == out["batches"] * 2


class _Silent:
    """Answers nothing at all -- every canary slot fails."""

    def generate(self, prompt, **kw):
        return _R("")


def test_a_partial_canary_breach_is_distinguishable_from_a_total_one(frozen) -> None:
    """THE ONE THAT MATTERS. Both runs are `ok: False`; only the denominator tells
    the reader that one model is unusable and the other hiccuped once.

    Note the stub: the shared ``_Stub`` answers "content" for EVERY term including
    the canaries, so it already fails every slot -- it cannot discriminate here. A
    partial breach needs a client that gets the canaries RIGHT, which is what the
    real Ministral run did in 17 of its 18 batches."""
    from src.ai_layer.triage_job import CANARY_EXPECTED

    class _Honest:
        """Answers the canaries correctly; everything else is content."""

        def __init__(self, bad_batch: int | None = None):
            self.bad_batch, self.n = bad_batch, 0

        def generate(self, prompt, **kw):
            self.n += 1
            if self.bad_batch is not None and self.n == self.bad_batch:
                return _R("")
            lines = []
            for term in _Stub._listed(prompt):
                want = CANARY_EXPECTED.get(term, {}).get("verdict") or "content"
                lines.append(f"{term} :: {want} :: org")
            return _R("\n".join(lines))

    clean = MB._task_triage(
        _Honest(), model="m", batch=frozen, anchors=None, keep_alive=None, chunk=5,
    )["canary"]
    assert clean["ok"] is True and clean["failed_n"] == 0, (
        "anti-vacuity: the honest client must PASS, or the partial case below proves nothing"
    )

    partial = MB._task_triage(
        _Honest(bad_batch=1), model="m", batch=frozen, anchors=None, keep_alive=None, chunk=5,
    )["canary"]
    total = MB._task_triage(
        _Silent(), model="m", batch=frozen, anchors=None, keep_alive=None, chunk=5,
    )["canary"]

    assert partial["ok"] is False and total["ok"] is False, "both are breaches"
    assert partial["failed_n"] == 2, "one dropped batch is one canary pair"
    assert total["failed_n"] == total["checked"], "a total collapse fails every slot"
    assert partial["failed_n"] < total["failed_n"], (
        "and the counts are what separate them -- this is the whole finding, and the "
        "distinction the bare word FAILED destroyed"
    )

def test_the_source_tags_canary_carries_its_denominator_too(frozen) -> None:
    out = MB._task_source_tags(
        _Stub(verdict="content", kind="org", tag=None), model="m", batch=frozen, keep_alive=None,
    )
    assert "checked" in out["canary"] and "failed_n" in out["canary"]
    assert out["canary"]["failed_n"] == len(out["canary"]["failed"])


# --------------------------------------------------------------------------- #
#  A backend that answers but cannot serve (2026-08-11)
# --------------------------------------------------------------------------- #
#
# Ollama answered /api/tags perfectly -- so three models resolved and three pairs
# started -- and every generate returned 500 "llama-server binary not found": its
# runner was missing from the install. Nine identical task failures were filed under
# three model names, which reads as "these models failed". The existing guard covers
# a backend that never came UP; this is the same failure by another route.


def _broken_pair() -> dict:
    err = (
        "LLMError: Ollama error for model 'x': Server error '500 Internal Server Error' "
        "— error starting llama-server: llama-server binary not found (checked: /usr/local/lib)"
    )
    return {
        "tasks": {
            "perception": {"status": "unavailable", "detail": err},
            "triage": {"status": "error", "detail": err},
            "source_tags": {"status": "error", "detail": err},
            "langdetect": {"status": "error", "detail": err},
            "latency": {"available": True, "shapes": [{"errors": [err]}]},
        }
    }


def test_a_broken_install_is_recognised_from_a_completed_pair() -> None:
    # The PROPERTY, not which of two synonymous signatures matched first: pinning the
    # tuple's order would make a harmless reordering of the list a red test.
    why = MB._backend_is_broken(_broken_pair())
    assert why and "llama-server" in why


def test_one_failed_task_is_not_a_broken_backend() -> None:
    """The narrow direction, and the one that protects real models: a single task
    failing is that task's problem. Only a TOTAL, uniform failure says the backend
    cannot serve at all."""
    pair = _broken_pair()
    pair["tasks"]["triage"] = {"status": "ok", "format_validity": 0.9}
    assert MB._backend_is_broken(pair) is None


def test_a_model_specific_failure_is_never_called_a_broken_backend() -> None:
    """THE NEGATIVE-SPACE TWIN. "needs more system memory than is available" is a
    failure OF THIS MODEL — the next, smaller one may load fine. Treating it as an
    install fault would skip models that would have worked, which is worse than the
    repetition this saves."""
    err = "LLMError: model requires more system memory (9.3 GiB) than is available"
    pair = {"tasks": {k: {"status": "error", "detail": err}
                      for k in ("perception", "triage", "source_tags", "langdetect")}}
    assert MB._backend_is_broken(pair) is None


def test_a_healthy_pair_is_never_flagged(frozen) -> None:
    ok = MB.bench_one_pair(
        _Stub(verdict="content", kind="org"), model="m", backend="ollama", batch=frozen,
        anchors=None, repeats=1, triage_chunk=50, tasks=("triage",),
    )
    assert MB._backend_is_broken(ok) is None


def test_the_remaining_models_are_skipped_with_the_install_reason(frozen, monkeypatch) -> None:
    """The whole point: name it once, and do not re-derive the same non-result under
    every other model's name."""

    class _Broken:
        def list_installed(self):
            return ["a", "b", "c"]

        def generate(self, prompt, **kw):
            raise RuntimeError(
                "Ollama error: 500 — error starting llama-server: "
                "llama-server binary not found (checked: /usr/local/lib/ollama)"
            )

    out = MB.run_model_bench(
        None,
        models=["ollama|a", "ollama|b", "ollama|c"],
        clients={"ollama": _Broken()},
        installed_by_backend={"ollama": ["a", "b", "c"]},
        batch=frozen,
        tasks=("triage", "langdetect"),
        persist=False,
        allow_backend_switch=False,
    )
    assert len(out["results"]) == 1, "only the first pair is benched"
    skipped = [s for s in out["skipped"] if s.get("reason") == "backend-cannot-serve"]
    assert len(skipped) == 2, "the other two are skipped, not re-run"
    assert "llama-server" in skipped[0]["detail"], "and the install reason is named"
    assert "nothing here is a measurement" in skipped[0]["detail"]

"""Side-by-side translation evidence: the questions asked, and what is NOT claimed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.ai_layer import translation_probe as TP


def _articles() -> list[dict]:
    body = (
        "Le ministère des transports a publié mardi son bilan annuel. Les trajets sur "
        "le réseau régional ont augmenté de onze pour cent. La ponctualité a légèrement "
        "reculé. Les responsables citent la baisse des tarifs du printemps. "
    ) * 3
    return [
        {"id": 1, "title": "t1", "text": body, "language": "fr"},
        {"id": 2, "title": "t2", "text": body, "language": "ru"},
        {"id": 3, "title": "t3", "text": body, "language": "en"},
        {"id": 4, "title": "t4", "text": body, "language": "zh"},
    ]


# --------------------------------------------------------------------------- #
#  The three directions -- the whole reason this exists beside the bench task
# --------------------------------------------------------------------------- #
def test_all_three_directions_are_covered() -> None:
    """THE ONE THAT MATTERS. A probe that only translated INTO English would never see
    the failure it exists for: a model pivoting through English loses twice on a
    foreign-to-foreign pair."""
    tset = TP.build_translation_set(_articles())
    assert tset["directions"]["to-english"] > 0
    assert tset["directions"]["from-english"] > 0
    assert tset["directions"]["foreign-to-foreign"] > 0, (
        "the hard direction must be asked, or the probe measures the easy half only"
    )


def test_a_foreign_source_is_always_asked_for_english_AND_a_third_language() -> None:
    for src in ("fr", "ru", "zh", "hi"):
        targets = TP.choose_targets(src)
        assert "en" in targets, "the common case"
        assert [t for t in targets if t not in ("en", src)], "and the hard one"
        assert src not in targets, "translating a language into itself measures nothing"


def test_an_english_source_gets_foreign_targets_only() -> None:
    targets = TP.choose_targets("en")
    assert "en" not in targets and len(targets) == TP.DEFAULT_TARGETS_PER_SOURCE


def test_the_targets_are_deterministic_so_two_models_answer_the_same_questions() -> None:
    assert TP.choose_targets("fr") == TP.choose_targets("fr")
    # And different source languages do not all exercise the same pair.
    assert TP.choose_targets("fr") != TP.choose_targets("ru")


# --------------------------------------------------------------------------- #
#  The frozen set
# --------------------------------------------------------------------------- #
def test_the_digest_moves_only_when_the_QUESTIONS_move() -> None:
    a = TP.build_translation_set(_articles())
    b = TP.build_translation_set(_articles())
    assert a["digest"] == b["digest"], "an identical selection is the same sitting"

    changed = _articles()
    changed[0]["text"] = changed[0]["text"].replace("onze", "douze")
    assert TP.build_translation_set(changed)["digest"] != a["digest"]


def test_a_language_the_prompt_cannot_name_is_skipped_not_guessed() -> None:
    """A source in a language with no name in the table is not a question we can ask.
    Asking for a translation "into xx" would put a code in a prompt and measure the
    model's reaction to nonsense."""
    tset = TP.build_translation_set([{"id": 9, "title": "t", "text": "x" * 900, "language": "xx"}])
    assert tset["n_items"] == 0


def test_the_excerpt_ends_at_a_sentence_boundary() -> None:
    """A fragment stopping mid-clause would penalise whichever model tried hardest to
    finish the thought."""
    text = ("Une phrase complète ici. " * 200)
    got = TP.excerpt(text, limit=100)
    assert len(got) <= 100 and got.endswith(".")


def test_a_short_text_is_returned_whole() -> None:
    assert TP.excerpt("Court.") == "Court."


# --------------------------------------------------------------------------- #
#  The run, and what it refuses to claim
# --------------------------------------------------------------------------- #
class _Model:
    def __init__(self, tag: str):
        self.tag = tag

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        class R:
            text = f"[{model}] traduction"
            eval_count = 4
        return R()


def test_answers_are_grouped_by_QUESTION_with_the_models_side_by_side() -> None:
    """The comparison a reader makes is "these two answers to the same question", not
    "this model's list of answers"."""
    tset = TP.build_translation_set(_articles()[:1])
    rep = TP.run_translation_probe(
        {"ollama": _Model("a")},
        models=[("ollama", "model-a"), ("ollama", "model-b")],
        tset=tset,
    )
    assert rep["n_items"] == tset["n_items"]
    for item in rep["items"]:
        assert [a["model"] for a in item["answers"]] == ["model-a", "model-b"]
        assert item["source_language"] and item["target_language"]


def test_no_quality_score_is_computed() -> None:
    """Adequacy and fluency need reference translations this corpus does not have. The
    numbers beside an answer are its length and its wall time, and nothing else."""
    tset = TP.build_translation_set(_articles()[:1])
    rep = TP.run_translation_probe(
        {"ollama": _Model("a")}, models=[("ollama", "m")], tset=tset
    )

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(w in str(k).lower() for w in
                               ("score", "bleu", "quality", "adequacy", "fluency",
                                "rating", "grade", "rank")), f"quality-shaped key at {path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(rep)
    assert "NO QUALITY SCORE IS COMPUTED" in rep["caveat"]
    assert "reference translations" in rep["caveat"]


def test_the_report_says_it_carries_corpus_text() -> None:
    """Unlike most diagnostics here this one contains the operator's own articles, and
    the file says so on its face rather than leaving them to notice."""
    rep = TP.run_translation_probe(
        {"ollama": _Model("a")}, models=[("ollama", "m")],
        tset=TP.build_translation_set(_articles()[:1]),
    )
    assert "your own articles" in rep["privacy"]


def test_a_failed_call_is_recorded_against_that_model_not_the_item() -> None:
    class _Broken:
        def generate(self, prompt, **kw):
            raise RuntimeError("boom")

    tset = TP.build_translation_set(_articles()[:1])
    rep = TP.run_translation_probe(
        {"ollama": _Broken(), "vllm": _Model("b")},
        models=[("ollama", "bad"), ("vllm", "good")],
        tset=tset,
    )
    first = rep["items"][0]["answers"]
    assert first[0]["error"] and first[0]["translation"] == ""
    assert first[1]["error"] is None and first[1]["translation"], (
        "one model failing must not cost the other its answer to the same question"
    )


def test_the_markdown_puts_the_answers_under_their_question() -> None:
    tset = TP.build_translation_set(_articles()[:1])
    rep = TP.run_translation_probe(
        {"ollama": _Model("a")},
        models=[("ollama", "model-a"), ("ollama", "model-b")], tset=tset,
    )
    md = TP.render_comparison_markdown(rep)
    assert "# Translation comparison" in md
    assert "model-a" in md and "model-b" in md
    assert "foreign-to-foreign" in md or "to-english" in md
    assert rep["caveat"] in md, "the refusal to score travels with the readable form"
    # The source must be ON the page: a reader judging a translation needs the original.
    assert "**Source**" in md


# --------------------------------------------------------------------------- #
#  The bundle member
# --------------------------------------------------------------------------- #
def test_the_bundle_member_yields_the_json_report_not_the_markdown_attachment(monkeypatch, tmp_path):
    """The `ai.json` regression, one member over. `_all_diagnostics_members` calls this
    route DIRECTLY, so any FastAPI default it does not pass stays an unresolved sentinel
    -- and ``Query(False)`` is TRUTHY, which would send every bundle down the markdown
    branch and put an attachment where a `.json` member belongs.

    THE FIXTURE IS THE POINT: with no saved probe the markdown branch falls back to the
    same JSONResponse, so the two calls agree and the bug is invisible. A saved report
    has to exist for the branches to diverge at all -- which is exactly the shape the
    field bug had (harmless on an empty install, wrong on a used one)."""
    from src.api import diagnostics as d
    from src.database.session import SessionLocal

    monkeypatch.setattr(TP, "_dir", lambda: tmp_path)
    (tmp_path / "oo-translation-probe-20260811-120000.json").write_text(
        json.dumps({"schema": TP.TRANSLATION_PROBE_SCHEMA, "n_items": 1, "items": []}),
        encoding="utf-8",
    )
    (tmp_path / "oo-translation-probe-20260811-120000.md").write_text("# md", encoding="utf-8")

    with SessionLocal() as db:
        member = dict(d._all_diagnostics_members(db))["translation-probe.json"]
        resp = member()

    assert resp.media_type == "application/json", (
        f"a .json bundle member handed back {resp.media_type!r} -- the markdown branch ran"
    )
    assert "content-disposition" not in {k.lower() for k in resp.headers}
    body = json.loads(bytes(resp.body))
    assert body["available"] is True and body["n_items"] == 1, body


def test_a_person_can_reach_this_without_a_terminal() -> None:
    """The recorded lesson one level up: a capability whose only caller is an API call
    is a dead end for the person who asked for it. This probe exists so a reader can
    compare two translations, so the reader must be able to RUN it and DOWNLOAD it from
    the app -- scoped to the handler's own body, because a whole-file substring would be
    satisfied by any other endpoint string in an 18,000-line file."""
    from tests.js_source_helper import function_body, read_static

    html = read_static("index.html")
    assert 'id="translation-probe-box"' in html, "no panel"
    assert 'onclick="tpRun(this)"' in html, "the run button is not wired"
    assert "/api/diagnostics/translation-probe/last?download=1" in html, (
        "no way to get the readable file out -- the JSON alone is not what a person reads"
    )

    body = function_body(read_static("app.js"), "tpRun")
    assert '"/api/diagnostics/translation-probe"' in body
    assert "n_articles" in body and "targets_per_source" in body, (
        "the size controls must reach the request, or they are decoration"
    )


# --------------------------------------------------------------------------- #
#  One model at a time -- the field's "CPU 100%, GPU idle"
#
#  The report is grouped by ITEM and always was. The CALL order used to follow it
#  (items outer, models inner), so consecutive calls almost always asked a different
#  model than the one before: a server restart on vLLM, a load on Ollama, paid per
#  CALL instead of per MODEL. And with Ollama's own default keep_alive the models it
#  was cycled through all stay resident, so a roster of several oversubscribes the
#  card and Ollama spills the overflow onto the CPU.
# --------------------------------------------------------------------------- #
class _Recorder:
    """Records the order models are actually asked in."""

    def __init__(self, calls: list):
        self.calls = calls

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        self.calls.append(model)

        class R:
            text = f"[{model}]"
            eval_count = 4
        return R()


def _four_item_set() -> dict:
    return TP.build_translation_set(_articles())


def test_all_of_one_models_items_are_asked_before_the_next_model(monkeypatch) -> None:
    """THE ONE THAT MATTERS. Against the pre-fix loop this interleaved on every item."""
    calls: list[str] = []
    client = _Recorder(calls)
    tset = _four_item_set()
    assert tset["n_items"] >= 2, "the fixture must have enough items to interleave"

    TP.run_translation_probe(
        {"ollama": client},
        models=[("ollama", "model-a"), ("ollama", "model-b")],
        tset=tset,
    )

    # Grouped means each model appears as ONE contiguous run.
    runs = [m for i, m in enumerate(calls) if i == 0 or calls[i - 1] != m]
    assert len(runs) == len(set(runs)), (
        "a model was returned to after another one ran -- every one of those is a "
        f"reload, and on Ollama it also keeps both resident. Call order: {calls}"
    )
    assert len(runs) == 2, f"both models must be asked; got runs {runs}"


def test_the_report_is_still_grouped_by_item(monkeypatch) -> None:
    """The negative-space twin: changing the CALL order must not reorder the REPORT.
    The comparison a reader makes is "these two answers to the same question"."""
    tset = _four_item_set()
    rep = TP.run_translation_probe(
        {"ollama": _Recorder([])},
        models=[("ollama", "model-a"), ("ollama", "model-b")],
        tset=tset,
    )
    assert rep["n_items"] == tset["n_items"]
    for i, item in enumerate(rep["items"]):
        assert [a["model"] for a in item["answers"]] == ["model-a", "model-b"], (
            f"item {i} lost the side-by-side ordering the report is built on"
        )
        assert item["source_language"] and item["target_language"]


def test_the_card_is_handed_over_once_per_model_not_once_per_call() -> None:
    """Per CALL is the whole defect: a handover is a server restart on vLLM and a
    model load on Ollama, and the bench's own docstring puts it at "tens of seconds
    each way"."""
    tset = _four_item_set()
    switches: list[tuple] = []

    def _switch(*, backend, model):
        switches.append((backend, model))
        return {"ready": True}

    TP.run_translation_probe(
        {"ollama": _Recorder([]), "vllm": _Recorder([])},
        models=[("ollama", "a"), ("vllm", "b")],
        tset=tset,
        allow_backend_switch=True,
        switch=_switch,
    )
    assert switches == [("ollama", "a"), ("vllm", "b")], (
        f"expected one handover per model, got {len(switches)} for "
        f"{tset['n_items']} items x 2 models"
    )


def test_arbitration_is_opt_in_so_merely_calling_this_moves_nothing() -> None:
    """Handing the card over stops and starts servers. A function that does that just
    by being called makes it a side effect of every test and every other caller -- the
    same reason the bench defaults its own switch off."""
    switches: list = []
    TP.run_translation_probe(
        {"ollama": _Recorder([])},
        models=[("ollama", "a")],
        tset=_four_item_set(),
        switch=lambda **kw: (switches.append(kw), {"ready": True})[1],
    )
    assert switches == [], "the default must not rearrange the operator's machine"


def test_a_model_whose_backend_never_came_up_is_not_asked_and_says_so() -> None:
    """Recording refusals under the model's name would read as "this model translates
    badly", when nothing was ever asked of it."""
    tset = _four_item_set()
    rep = TP.run_translation_probe(
        {"ollama": _Recorder([])},
        models=[("ollama", "a")],
        tset=tset,
        allow_backend_switch=True,
        switch=lambda **kw: {"ready": False, "reason": "the server did not start"},
    )
    for item in rep["items"]:
        ans = item["answers"][0]
        assert ans["translation"] == ""
        assert ans["asked"] is False, (
            "the distinction must be a FIELD -- a renderer sniffing the prose for "
            "'not asked' is one reword away from calling this a failure again"
        )
        assert "not asked" in ans["error"] and "did not start" in ans["error"]
    assert rep["handovers"] == [
        {"backend": "ollama", "model": "a", "ready": False,
         "reason": "the server did not start"}
    ], (
        "a refused handover is the REASON a model's column is empty; collecting it and "
        "not publishing it leaves the reader to guess. Got: " + repr(rep.get("handovers"))
    )


def test_a_model_that_was_never_asked_is_not_called_FAILED_in_the_markdown() -> None:
    """THE RENDER BOUNDARY, which is where the distinction was being thrown away.

    The probe already refuses to record a refused handover as five bad translations --
    and the markdown, which is the artifact a person actually reads and sends on,
    labelled every one of them "failed". A model that never got the card has produced
    no evidence about itself in either direction.
    """
    rep = TP.run_translation_probe(
        {"ollama": _Recorder([])},
        models=[("ollama", "a")],
        tset=_four_item_set(),
        allow_backend_switch=True,
        switch=lambda **kw: {"ready": False, "reason": "the server did not start"},
    )
    md = TP.render_comparison_markdown(rep)
    assert "_failed:_" not in md, (
        "nothing was asked of this model, so nothing about it failed -- and 'failed' "
        "beside a model name is read as a measurement of the model"
    )
    assert "not asked" in md and "the server did not start" in md
    assert "Nothing was measured" in md


def test_a_real_failure_is_STILL_called_failed_in_the_markdown() -> None:
    """The negative-space twin. A fix that softened every error into 'not asked' would
    satisfy the test above while hiding the case where the model WAS asked and broke."""

    class _Broken:
        def generate(self, *_a, **_kw):
            raise RuntimeError("CUDA out of memory")

    rep = TP.run_translation_probe(
        {"ollama": _Broken()}, models=[("ollama", "a")], tset=_four_item_set(),
    )
    assert all(a["asked"] is True for it in rep["items"] for a in it["answers"])
    md = TP.render_comparison_markdown(rep)
    assert "_failed:_" in md and "CUDA out of memory" in md

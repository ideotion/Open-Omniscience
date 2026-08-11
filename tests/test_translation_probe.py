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

"""Is a second model worth the cost of switching — and does the harness that asks
answer honestly when it cannot tell?

Design of record: ``docs/design/MULTI_MODEL_SPECIALISATION_2026-08-10.md``.

The experiment is arithmetic over timings, which makes it unusually easy to write a
harness that produces a confident, wrong table. Two failure shapes get the most attention
here because the design doc names them itself:

  * **A refused switch must never read as a fast one.** A configuration whose hand-overs
    silently failed does less work and finishes sooner, so it is the fastest-looking row
    in any such table — and it measured a model it never loaded.
  * **Switch time is the number the design turns on**, so it is accumulated apart. Folded
    into a task's own wall it would show up as "perception got slower", which is a
    different finding about a different thing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ai_layer import specialisation as sp


class _Art:
    def __init__(self, content="hello world", language=None, detected=None, title=""):
        self.content = content
        self.language = language
        self.detected_language = detected
        self.title = title


# --------------------------------------------------------------------------- #
#  The gate: agreement, and never a fabricated accuracy
# --------------------------------------------------------------------------- #


def _detector(monkeypatch, answers):
    """Feed the language detector a scripted sequence of answers."""
    seq = list(answers)

    def _fake(client, title, content, *, model, keep_alive=None):
        return seq.pop(0) if seq else None

    monkeypatch.setattr("src.ai_layer.langdetect_llm.detect_language_llm", _fake)


def test_the_two_references_are_reported_apart(monkeypatch):
    """They disagree with each other on real corpora, and a blended figure would hide
    exactly the thing the operator needs to see."""
    arts = [
        _Art(language="fr", detected="en"),  # the references disagree
        _Art(language="en", detected="en"),  # and here they agree
    ]
    _detector(monkeypatch, ["en", "en"])

    out = sp.measure_language_agreement(arts, client=object(), model="m")
    by = out["by_reference"]
    assert by["detected"]["n"] == 2 and by["detected"]["match"] == 2
    assert by["asserted"]["n"] == 2 and by["asserted"]["match"] == 1
    assert by["agreed"]["n"] == 1, "only the article whose references agree qualifies"
    assert "agreement" in out["method"] and "not accuracy" in out["caveat"]


def test_a_region_subtag_is_not_a_disagreement(monkeypatch):
    """``Article.language`` is stored raw from <html lang>, so most major outlets arrive
    as en-US. Comparing that against a model's ``en`` would manufacture a disagreement
    out of a region subtag — the recorded normalise-on-read rule, one module over."""
    _detector(monkeypatch, ["en"])
    out = sp.measure_language_agreement(
        [_Art(language="en-US", detected="en_US")], client=object(), model="m"
    )
    assert out["by_reference"]["asserted"]["match"] == 1
    assert out["by_reference"]["detected"]["match"] == 1


def test_a_refusal_is_not_a_wrong_answer(monkeypatch):
    """The production detector treats them differently — a refusal stores nothing, a
    wrong label would be stored — so a measurement that merged them would misdescribe
    the behaviour it is measuring."""
    _detector(monkeypatch, ["en", None, "de"])
    out = sp.measure_language_agreement(
        [_Art(language="en"), _Art(language="fr"), _Art(language="fr")],
        client=object(),
        model="m",
    )
    assert out["n_refused"] == 1 and out["n_answered"] == 2
    assert out["by_reference"]["asserted"]["n"] == 2, "a refusal is not scored against"


def test_an_article_with_no_reference_scores_nothing(monkeypatch):
    """Negative space: a corpus row with neither label cannot agree or disagree, and
    counting it either way would invent evidence."""
    _detector(monkeypatch, ["en"])
    out = sp.measure_language_agreement([_Art()], client=object(), model="m")
    assert out["n_answered"] == 1
    assert all(out["by_reference"][r]["n"] == 0 for r in ("detected", "asserted", "agreed"))


def test_one_bad_article_does_not_end_the_sweep(monkeypatch):
    calls = {"n": 0}

    def _fake(client, title, content, *, model, keep_alive=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model hiccup")
        return "en"

    monkeypatch.setattr("src.ai_layer.langdetect_llm.detect_language_llm", _fake)
    out = sp.measure_language_agreement(
        [_Art(language="en"), _Art(language="en")], client=object(), model="m"
    )
    assert out["n_errors"] == 1 and out["n_answered"] == 1


# --------------------------------------------------------------------------- #
#  The comparison, and its two directions
# --------------------------------------------------------------------------- #


def _result(model, *, agreed, n=200, refused=0):
    return {
        "model": model,
        "backend": "ollama",
        "n_answered": n,
        "n_refused": refused,
        "wall_s": 1.0,
        "by_reference": {
            "detected": {"n": n, "match": int(agreed * n), "differ": 0, "agreement": agreed},
            "asserted": {"n": n, "match": int(agreed * n), "differ": 0, "agreement": agreed},
            "agreed": {"n": n, "match": int(agreed * n), "differ": 0, "agreement": agreed},
        },
    }


def test_a_surviving_advantage_says_the_shapes_are_worth_measuring():
    out = sp.compare_language_models([_result("big", agreed=0.80), _result("small", agreed=0.95)])
    assert out["leader"] == "small"
    assert out["specialisation_worth_measuring"] is True
    assert out["reference"] == "agreed", "the strongest reference with data"


def test_an_advantage_that_does_not_survive_says_so(monkeypatch):
    """THE FINDING THE DOC PREDICTS. n=17 made Qwen look 100 % against Ministral's 94 %;
    if that gap closes on a few hundred real articles the answer is 'one model', and
    that is cheaper to act on than the machinery it would have justified."""
    out = sp.compare_language_models([_result("big", agreed=0.94), _result("small", agreed=0.95)])
    assert out["specialisation_worth_measuring"] is False
    assert out["margin"] == pytest.approx(0.01, abs=1e-9)


def test_a_reference_with_no_data_is_skipped_not_guessed():
    """A corpus whose articles carry no publisher label must fall through to the one
    that does, and SAY which it used."""
    a = _result("big", agreed=0.8)
    b = _result("small", agreed=0.9)
    for r in (a, b):
        r["by_reference"]["agreed"] = {"n": 0, "match": 0, "differ": 0, "agreement": None}
    out = sp.compare_language_models([a, b])
    assert out["reference"] == "detected"


def test_one_model_cannot_be_compared_with_itself():
    out = sp.compare_language_models([_result("only", agreed=0.9)])
    assert out["verdict"] == "not-measurable-here"


# --------------------------------------------------------------------------- #
#  The shapes, and the refused-switch trap
# --------------------------------------------------------------------------- #

BIG = {"backend": "ollama", "model": "ministral"}
SMALL = {"backend": "ollama", "model": "qwen"}
ONE_MODEL = {"langdetect": BIG, "perception": BIG}
SPLIT = {"langdetect": SMALL, "perception": BIG}


@pytest.fixture(autouse=True)
def _no_real_work(monkeypatch):
    monkeypatch.setattr(
        "src.ai_layer.langdetect_llm.detect_language_llm",
        lambda *a, **k: "en",
    )
    monkeypatch.setattr(
        "src.ai_layer.perception.llm_perception_extract",
        lambda *a, **k: {"who": [], "where": [], "when": []},
    )


def _switch_ok(**kw):
    return {"ready": True}


def _switch_refused(**kw):
    return {"ready": False, "reason": "a stop did not take"}


def test_the_baseline_never_crosses():
    """One model, so ``_ensure`` finds the backend already current after the initial
    load and no crossing happens at all."""
    out = sp.run_shape(
        [_Art()] * 4, shape="one", assignment=ONE_MODEL,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    assert out["crossings"] == 0
    assert out["switches"] == 1, "the initial load, which every shape pays"


def test_the_phased_shape_crosses_exactly_once():
    """The doc's arithmetic: switches per corpus = 1, however big the corpus."""
    out = sp.run_shape(
        [_Art()] * 50, shape="phased", assignment=SPLIT,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    assert out["crossings"] == 1


@pytest.mark.parametrize("n,batch,expected", [(100, 100, 1), (300, 100, 5), (300, 300, 1)])
def test_the_batched_shape_crosses_twice_per_batch_less_the_first(n, batch, expected):
    """2 x (corpus / N) hand-overs, minus the initial load which is not a crossing.
    Parametrised over the ask's own range so the arithmetic is pinned at more than one
    point — a single case would be satisfied by several wrong formulas."""
    out = sp.run_shape(
        [_Art()] * n, shape="batched", batch_size=batch, assignment=SPLIT,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    assert out["crossings"] == expected


def test_a_refused_switch_is_not_recorded_as_current():
    """THE GUARD THAT MATTERS. If a refusal marked the backend as switched, the next
    request for that SAME model would be skipped as unnecessary — the run would do less
    work, finish sooner, and be the fastest row in the table while having measured a
    model it never loaded.

    THE ASSIGNMENT IS THE ONE-MODEL ONE, and that is what makes this discriminate. The
    first draft used the split, where the two tasks want DIFFERENT models, so ``current``
    failed to match on every phase whether or not the refusal was recorded — 4 switches
    either way, and the guard passed against the very defect it names. A repeated target
    is the only shape in which recording a refusal as success can suppress anything."""
    out = sp.run_shape(
        [_Art()] * 4, shape="one", assignment=ONE_MODEL,
        clients={"ollama": object()}, switch=_switch_refused,
    )
    assert out["switches"] == 2, (
        "the second phase must try again — the first hand-over never took"
    )
    assert out["switches_refused"] == 2
    assert out["trustworthy"] is False
    assert "REFUSED" in out["caveat"]


def test_a_refused_switch_in_a_split_run_still_retries_every_phase():
    """The alternating case, kept because it is the one the experiment actually runs —
    but it cannot stand in for the guard above, and saying so here is what stops it
    being mistaken for one."""
    out = sp.run_shape(
        [_Art()] * 4, shape="batched", batch_size=2, assignment=SPLIT,
        clients={"ollama": object()}, switch=_switch_refused,
    )
    assert out["switches"] == 4 and out["switches_refused"] == 4
    assert out["trustworthy"] is False


def test_a_clean_run_claims_no_caveat_it_has_not_earned():
    """The negative-space twin: a permanent warning would train the reader to ignore
    the one that matters."""
    out = sp.run_shape(
        [_Art()] * 4, shape="phased", assignment=SPLIT,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    assert out["trustworthy"] is True and out["caveat"] is None


def test_a_switch_that_raises_is_data_not_a_crash():
    def _boom(**kw):
        raise RuntimeError("the card is gone")

    out = sp.run_shape(
        [_Art()] * 2, shape="phased", assignment=SPLIT,
        clients={"ollama": object()}, switch=_boom,
    )
    assert out["switches_refused"] == 2 and out["trustworthy"] is False


def test_switch_time_is_its_own_line():
    """Folded into a task's wall it would read as 'perception got slower', which is a
    different finding about a different thing."""
    import time as _t

    def _slow(**kw):
        _t.sleep(0.05)
        return {"ready": True}

    out = sp.run_shape(
        [_Art()] * 2, shape="phased", assignment=SPLIT,
        clients={"ollama": object()}, switch=_slow,
    )
    assert out["switch_s"] >= 0.09, "two hand-overs at ~50ms each"
    assert sum(p["wall_s"] for p in out["phases"]) < out["switch_s"], (
        "the task walls must not contain the switching"
    )
    assert out["switch_share"] > 0.5


def test_the_rate_is_this_runs_own_arithmetic(monkeypatch):
    """n / wall, not a per-call latency multiplied by anything — the shape of claim a
    sibling bench had to be corrected into making.

    THE WORK HAS TO TAKE MEASURABLE TIME for this to assert anything: with instant fakes
    the wall rounds to 0.000 s and the recomputation divides by zero, which is a test
    that cannot pass rather than a code defect. The tolerance is derived, not picked —
    the wall is published to 3 dp, so the true wall is within +/-0.0005 s and the
    relative error in a rate recomputed from it is 0.0005/wall, i.e. ~1 % at the ~50 ms
    this run takes. 2 % leaves room for the rate's own 1-dp rounding."""
    import time as _t

    monkeypatch.setattr(
        "src.ai_layer.langdetect_llm.detect_language_llm",
        lambda *a, **k: (_t.sleep(0.005), "en")[1],
    )
    out = sp.run_shape(
        [_Art()] * 10, shape="one", assignment=ONE_MODEL,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    assert out["wall_s"] >= 0.04, "the fixture must be slow enough to measure"
    assert out["articles_per_hour"] == pytest.approx(10 / out["wall_s"] * 3600, rel=0.02)


def test_a_batched_run_needs_a_batch_size():
    with pytest.raises(ValueError):
        sp.run_shape([_Art()], shape="batched", assignment=SPLIT, clients={"ollama": object()})


def test_every_article_is_processed_once_per_task():
    """The sample must be ONE sample: batching changes when work happens, never how
    much of it there is."""
    out = sp.run_shape(
        [_Art()] * 7, shape="batched", batch_size=3, assignment=SPLIT,
        clients={"ollama": object()}, switch=_switch_ok,
    )
    per_task: dict[str, int] = {}
    for p in out["phases"]:
        per_task[p["task"]] = per_task.get(p["task"], 0) + p["done"]
    assert per_task == {"langdetect": 7, "perception": 7}

"""
Tests for src/ai_layer/perception_extract.py -- the pure per-language harness gate
and the per-article extraction-and-store batch runner (B6.2/B6.3, 2026-07-24
field-feedback Session B). No network: an injected fake client stands in for the
model.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import perception_extract as PE
from src.ai_layer.jobs import ArticleWork
from src.database.models import (
    AiKeyword,
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
)


# --------------------------------------------------------------------------- #
# gate_languages_from_report / language_gate -- pure, no DB.
# --------------------------------------------------------------------------- #


def test_gate_marks_a_clean_language_active():
    # The REAL persisted/live-eval shape: run metadata wrapping the harness's OWN
    # report dict under a "report" key (report["report"]["by_language"], not
    # report["by_language"] -- the exact nesting the 2026-07-25 fix restored).
    report = {
        "status": "ok",
        "report": {
            "by_language": {
                "en": {
                    "who": {"hallucination_rate": 0.0},
                    "where": {"hallucination_rate": 0.1},
                    "when": {"hallucination_rate": None},
                }
            }
        },
    }
    gate = PE.gate_languages_from_report(report)
    assert gate["en"]["active"] is True


def test_gate_disables_a_language_that_hallucinates_above_the_floor():
    report = {
        "status": "ok",
        "report": {
            "by_language": {
                "ar": {
                    "who": {"hallucination_rate": 0.9},
                    "where": {"hallucination_rate": 0.0},
                    "when": {"hallucination_rate": 0.0},
                }
            }
        },
    }
    gate = PE.gate_languages_from_report(report)
    assert gate["ar"]["active"] is False
    assert "who hallucination 0.9" in gate["ar"]["reason"]


def test_a_none_hallucination_rate_alone_never_disqualifies():
    """The TRUE half of the retired test_gate_none_hallucination_rate_never_
    disqualifies: silence on a field is not a hallucination. It is only a FAILURE
    when that field also carried gold (then the recall floor speaks) -- here
    who/when carry none and `where` was recovered, so the language clears.

    Its retired predecessor asserted `active is True` for an ALL-None row, which
    encoded the 2026-07-29 defect as a requirement: an extractor returning
    nothing scored tp+fp==0 everywhere -> rate None everywhere -> never failed ->
    licensed for every language."""
    report = {
        "report": {
            "by_language": {
                "fr": {
                    "who": {"hallucination_rate": None, "recall": None, "n_gold": 0, "n_pred": 0},
                    "where": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1, "n_pred": 1},
                    "when": {"hallucination_rate": None, "recall": None, "n_gold": 0, "n_pred": 0},
                    "n_cases": 1,
                }
            }
        }
    }
    gate = PE.gate_languages_from_report(report)
    assert gate["fr"]["active"] is True


def test_language_gate_absent_language_is_never_evaluated():
    gate = PE.gate_languages_from_report({"report": {"by_language": {"en": {}}}})
    active, reason = PE.language_gate("de", gate)
    assert active is False
    assert reason == "never evaluated"


def test_gate_from_a_real_harness_run_populates_the_gate():
    """Regression for the 2026-07-25 nesting bug (transversal audit 09): exercises
    the REAL production chain end-to-end -- evaluate_perception() (the actual S6.5
    harness) wrapped EXACTLY as run_perception_eval_against_model() builds the
    persisted artifact -- rather than a hand-typed mock report. The old buggy
    gate_languages_from_report() would return {} here even though a real eval just
    ran and scored real languages; every prior test mocked the wrong (bug-matching)
    shape, which is why the bug shipped green. This proves the fix against the
    REAL envelope, not an assumption about its shape."""
    from src.analytics.perception_eval import PERCEPTION_GOLD, evaluate_perception

    def extract_fn(text, language):
        return {"who": [], "where": [], "when": []}  # no predictions -> hallucination_rate=None everywhere

    harness_report = evaluate_perception(extract_fn, PERCEPTION_GOLD)
    assert harness_report["by_language"], "the harness itself produced no per-language stats -- test setup broken"

    # The EXACT envelope run_perception_eval_against_model() builds.
    artifact = {
        "status": "ok",
        "model": "stub:test",
        "backend": "ollama",
        "prompt_version": "test-1",
        "report": harness_report,
    }
    gate = PE.gate_languages_from_report(artifact)
    assert gate, "gate must be non-empty after a real harness run -- the nesting bug made this always {}"
    assert set(gate.keys()) == set(harness_report["by_language"].keys())
    for lang in gate:
        # AMENDED 2026-07-29 (the assertion, never the test -- this file's whole
        # reason for existing is the NESTING guarantee above, which is unchanged):
        # its extractor returns NOTHING, and under the new RECALL floor that is a
        # FAILURE, not a pass. It used to read `active is True` because the gate
        # caught only invention, never silence -- a model that says nothing was
        # licensed for every language. Every one of these gold languages carries
        # `where` gold, so every one is now correctly failed on recall.
        assert gate[lang]["active"] is False, gate[lang]
        assert "recall" in gate[lang]["reason"], gate[lang]


def test_language_gate_none_language_is_gated_honestly():
    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    active, reason = PE.language_gate(None, gate)
    assert active is False
    assert "no known language" in reason


def test_language_gate_empty_report_gates_every_language():
    """No live eval has ever run -> the gate is empty -> every language reads as
    never-evaluated. This is the intended honest behaviour, never a fabricated pass."""
    gate = PE.gate_languages_from_report(None)
    assert gate == {}
    active, reason = PE.language_gate("en", gate)
    assert active is False and reason == "never evaluated"


# --------------------------------------------------------------------------- #
# select_perception_batch / extract_perception_batch -- in-memory DB, fake client.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _mk_article(db, src, i, *, title="T", content="c", language="en", quarantined=False):
    a = Article(
        url=f"https://src.test/{i}",
        canonical_url=f"https://src.test/{i}",
        source_id=src.id,
        title=title,
        content=content,
        language=language,
        hash=f"h{i}",
        quarantined=quarantined,
    )
    db.add(a)
    db.flush()
    return a


def _row_counts(db):
    return (
        db.query(ArticleMentionedDate).count(),
        db.query(ArticleMentionedPlace).count(),
        db.query(ArticleEntity).count(),
    )


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    """Reports the SAME fixed who/where/when for every call -- a real client
    stand-in, so the extraction pipeline is exercised end-to-end."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("WHO: Acme Corp\nWHERE: Springfield\nWHEN: 2024-01-01")


class _AlwaysNothingClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("WHO: none\nWHERE: none\nWHEN: none")


class _HallucinatingUnparseableClient:
    """Never replies in the constrained format -- a garbage answer."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("I refuse to answer this request.")


class _RaisingClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("simulated outage")


def test_select_perception_batch_excludes_quarantined_and_orders_by_id(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    _mk_article(db, src, 1)
    _mk_article(db, src, 2, quarantined=True)
    _mk_article(db, src, 3)
    db.commit()

    work = PE.select_perception_batch(db, 0, 10)
    assert [w.article_id for w in work] == [1, 3]


def test_select_perception_batch_effective_language_falls_back_to_detected(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = Article(
        url="https://src.test/x", canonical_url="https://src.test/x", source_id=src.id,
        title="T", content="c", language=None, detected_language="fr", hash="hx",
    )
    db.add(a)
    db.commit()

    work = PE.select_perception_batch(db, 0, 10)
    assert work[0].language == "fr"


def test_extract_perception_batch_stores_all_three_kinds_and_never_the_trusted_tables(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1)
    db.commit()
    before = _row_counts(db)

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _FakeClient(), model="stub:test", gate=gate)

    assert result["stored"] == 1
    assert result["who"] == 1 and result["where"] == 1 and result["when"] == 1
    assert _row_counts(db) == before  # the trusted rule-based tables are UNTOUCHED

    rows = {r.kind: r.term for r in db.query(AiKeyword).filter_by(article_id=a.id)}
    assert rows == {"ai-who": "Acme Corp", "ai-place": "Springfield", "ai-date": "2024-01-01"}
    for r in db.query(AiKeyword).filter_by(article_id=a.id):
        assert r.model == "stub:test"
        from src.ai_layer.perception import PERCEPTION_PROMPT_VERSION

        assert r.prompt_version == PERCEPTION_PROMPT_VERSION
        assert r.confirmed is False


def test_a_disabled_language_is_never_attempted_the_model_is_never_called(db):
    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("the model must never be called for a gated language")

    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1, language="ar")
    db.commit()

    gate = {"ar": {"active": False, "reason": "hallucination-rate above 0.5 on the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _NeverCallMe(), model="stub:test", gate=gate)

    assert result["gated"] == 1
    assert result["stored"] == 0
    assert db.query(AiKeyword).count() == 0


def test_an_unevaluated_language_is_gated_never_assumed_safe(db):
    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("never evaluated must gate, not silently pass")

    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1, language="zh")
    db.commit()

    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _NeverCallMe(), model="stub:test", gate={})
    assert result["gated"] == 1
    assert result["gated_detail"] == {"never evaluated": 1}


def test_empty_content_is_gated_without_calling_the_model(db):
    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("empty content must never reach the model")

    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1, title="", content="   ")
    db.commit()

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _NeverCallMe(), model="stub:test", gate=gate)
    assert result["gated"] == 1
    assert result["gated_detail"]["empty content"] == 1


def test_negative_space_a_should_be_empty_article_yields_zero_candidates(db):
    """The model correctly says 'nothing to extract' -- must yield ZERO stored
    candidates, never a fabricated placeholder."""
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1, content="It was a quiet afternoon with nothing to report.")
    db.commit()

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _AlwaysNothingClient(), model="stub:test", gate=gate)

    assert result["stored"] == 1  # the ATTEMPT succeeded (a valid, honest negative)
    assert result["who"] == 0 and result["where"] == 0 and result["when"] == 0
    assert db.query(AiKeyword).filter_by(article_id=a.id).count() == 0


def test_negative_space_a_hallucinated_unparseable_reply_stores_nothing(db):
    """The B15/echo-back precedent: a garbage/unparseable answer must never be
    coerced into a fabricated candidate."""
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1)
    db.commit()

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(
        db, work, _HallucinatingUnparseableClient(), model="stub:test", gate=gate
    )
    assert result["who"] == 0 and result["where"] == 0 and result["when"] == 0
    assert db.query(AiKeyword).count() == 0


def test_negative_space_date_candidates_never_enter_the_trusted_date_store(db):
    """Even a SUCCESSFUL, non-empty extraction must never touch article_mentioned_
    dates/_places/article_entities -- only ai_keyword."""
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1)
    db.commit()
    before = _row_counts(db)

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    PE.extract_perception_batch(db, work, _FakeClient(), model="stub:test", gate=gate)

    assert _row_counts(db) == before
    assert db.query(AiKeyword).filter_by(kind="ai-date").count() == 1


def test_skip_existing_never_recalls_the_model_for_an_already_extracted_article(db):
    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("skip_existing must not re-call the model")

    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1)
    db.commit()

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    PE.extract_perception_batch(db, work, _FakeClient(), model="stub:test", gate=gate)

    result = PE.extract_perception_batch(
        db, work, _NeverCallMe(), model="stub:test", gate=gate, skip_existing=True
    )
    assert result["skipped_existing"] == 1
    assert result["stored"] == 0


def test_an_llm_outage_aborts_the_batch_and_reports_it_honestly(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a1 = _mk_article(db, src, 1)
    a2 = _mk_article(db, src, 2)
    db.commit()

    gate = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    work = [
        ArticleWork(a1.id, a1.title, a1.content, a1.language),
        ArticleWork(a2.id, a2.title, a2.content, a2.language),
    ]
    result = PE.extract_perception_batch(
        db, work, _RaisingClient(), model="stub:test", gate=gate, max_workers=1
    )
    assert result["aborted"] is True
    assert "simulated outage" in result["reason"]
    assert result["stored"] == 0


# --------------------------------------------------------------------------- #
# 2026-07-29: the RECALL floor + the TRI-STATE gate. The old loop failed only on
# hallucination, so an extractor that returned NOTHING scored tp+fp==0 ->
# hallucination_rate None -> never failed -> licensed for EVERY language. A gate
# that catches invention but never silence is half a gate.
#
# Every test below drives the REAL evaluate_perception() over the REAL gold set,
# per the house lesson: the 2026-07-25 nesting bug AND this one both shipped
# green because the tests mocked a shape the production chain cannot emit.
# --------------------------------------------------------------------------- #
def _real_gate(extract_fn):
    """A gate built the way production builds it: the REAL S6.5 harness over the
    REAL gold set, wrapped in the EXACT envelope run_perception_eval_against_
    model() persists."""
    from src.analytics.perception_eval import PERCEPTION_GOLD, evaluate_perception

    return PE.gate_languages_from_report(
        {
            "status": "ok",
            "model": "stub:test",
            "backend": "ollama",
            "prompt_version": "test-1",
            "report": evaluate_perception(extract_fn, PERCEPTION_GOLD),
        }
    )


def _gold_answer(text):
    from src.analytics.perception_eval import PERCEPTION_GOLD

    for c in PERCEPTION_GOLD:
        if c.text == text:
            return {"who": list(c.who), "where": list(c.where), "when": list(c.when)}
    return {"who": [], "where": [], "when": []}


def test_negative_space_an_extractor_that_answers_nothing_fails_every_language():
    """THE 2026-07-29 defect, pinned."""
    gate = _real_gate(lambda text, language: {"who": [], "where": [], "when": []})
    assert gate, "the real harness produced no per-language stats -- test setup broken"
    for lang, entry in gate.items():
        assert entry["active"] is False, (lang, entry)
        assert "recall" in entry["reason"], entry["reason"]
        assert "cleared" not in entry["reason"], entry["reason"]


def test_negative_space_a_where_only_language_is_never_failed_on_who_or_when():
    """Nine of the thirteen gold languages carry ONLY `where` gold. An extractor
    correct on `where` and silent on who/when must CLEAR them -- failing a field
    that was never tested is a FABRICATED FAIL, exactly as dishonest as the
    fabricated pass this fix removes. The four languages that DO carry who/when
    gold must still fail, or the floor is not biting."""
    gate = _real_gate(
        lambda text, language: {"who": [], "where": _gold_answer(text)["where"], "when": []}
    )
    for lang in ("pt", "nl", "ru", "id", "ar", "zh", "ja", "hi", "bn"):
        assert gate[lang]["active"] is True, (lang, gate[lang])
        # and it must not even MENTION who/when -- they were never checked.
        assert "who" not in gate[lang]["reason"] and "when" not in gate[lang]["reason"]
    for lang in ("en", "de", "es", "fr"):
        assert gate[lang]["active"] is False, (lang, gate[lang])


def test_a_perfect_extractor_clears_every_language_and_states_its_power():
    gate = _real_gate(lambda text, language: _gold_answer(text))
    assert all(e["active"] is True for e in gate.values()), gate
    assert gate["ru"]["n_cases"] == 1
    assert "1 synthetic case" in gate["ru"]["reason"]
    assert "low statistical power" in gate["ru"]["reason"]
    assert gate["en"]["n_cases"] == 5
    # the clearing verdict is AUDITABLE: it lists the floors actually applied.
    assert any("recall" in c for c in gate["en"]["checks"])


def test_a_language_row_with_no_evidence_is_unmeasured_never_cleared():
    """TRI-STATE null. A row with no field metrics at all used to return
    {"active": True, "reason": "cleared the S6.5 harness"} -- a fabricated pass on
    literally zero evidence."""
    gate = PE.gate_languages_from_report({"report": {"by_language": {"en": {}}}})
    assert gate["en"]["active"] is None
    assert gate["en"]["checks"] == []
    assert "cleared" not in gate["en"]["reason"].lower()
    assert "unmeasured" in gate["en"]["reason"].lower()


def test_unmeasured_never_runs_and_says_why():
    """null is EPISTEMIC, not permissive: it explains the ABSENCE of a
    measurement, it never grants permission on one. The run decision stays False."""
    gate = PE.gate_languages_from_report({"report": {"by_language": {"en": {}}}})
    active, reason = PE.language_gate("en", gate)
    assert active is False
    assert "unmeasured" in reason.lower() and "cleared" not in reason.lower()


def test_gate_entries_carry_no_score_shaped_keys():
    gate = _real_gate(lambda text, language: _gold_answer(text))
    banned = ("score", "ranking", "rating", "grade")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in banned), f"score-shaped key {k!r}"
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(gate)

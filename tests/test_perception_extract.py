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


def test_a_hallucinating_field_is_gated_without_taking_the_language_with_it():
    """AMENDED 2026-08-01 (E-S3, ruling 16's granularity ask -- the assertion, not the
    scenario). This used to read ``active is False`` for the whole language, which
    encoded the collapse the ruling removes: a model that invents people but reads
    dates perfectly extracted NOTHING, anywhere. The floors were always per field; only
    the verdict was collapsed. Now `who` is gated on its own evidence and its siblings
    keep theirs, and the language reason says which is which so "active" cannot
    over-read as "active for everything"."""
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
    fields = gate["ar"]["fields"]
    assert fields["who"]["active"] is False
    assert "who hallucination 0.9" in fields["who"]["reason"]
    assert fields["where"]["active"] is True and fields["when"]["active"] is True
    # The language is worth a call (two fields cleared) but says what is held back.
    assert gate["ar"]["active"] is True
    assert "gated for who" in gate["ar"]["reason"]
    # ...and the STORAGE decision follows the field, not the language.
    assert PE.field_gate("ar", "who", gate)[0] is False
    assert PE.field_gate("ar", "where", gate)[0] is True


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
# FIELD DEFECT 1 (2026-09-05): the language code is NORMALISED before the lookup.
#
# `Article.language` is stored raw from `<html lang>`, so most major outlets arrive
# as `en-US`/`en-GB`. A plain `gate.get(language)` missed every one of them and
# reported "never evaluated" -- 725,791 articles across a 33-day field sweep that
# attempted zero calls, 23 days of it AFTER the harness cleared 13 languages.
#
# BOTH DIRECTIONS ARE PINNED. The over-eager fix is exactly as wrong as the defect:
# a normaliser that folded distinct languages together would license a language the
# harness never cleared, which is the fabricated pass this whole module exists to
# refuse. So there is a test that `en-US` clears an `en` gate AND a test that `es`
# never does.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stored", ["en-US", "en-GB", "EN", "en_us", "en-Latn-US", " en "])
def test_a_region_tagged_article_language_clears_a_bare_code_gate(stored):
    gate = PE.gate_languages_from_report(
        {
            "status": "ok",
            "report": {
                "by_language": {
                    "en": {
                        "who": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1},
                        "where": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1},
                        "when": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1},
                        "n_cases": 1,
                    }
                }
            },
        }
    )
    active, reason = PE.language_gate(stored, gate)
    assert active is True, f"{stored!r} is an English article, not an unevaluated one"
    assert "never evaluated" not in reason
    # The STORAGE gate must agree with the CALL gate, or a paid-for call is discarded.
    assert PE.field_gate(stored, "where", gate)[0] is True


def test_negative_space_normalising_never_merges_distinct_languages():
    """The mirror defect: an over-eager key must not license an untested language."""
    gate = PE.gate_languages_from_report(
        {
            "status": "ok",
            "report": {
                "by_language": {
                    "en": {
                        "who": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1},
                        "n_cases": 1,
                    }
                }
            },
        }
    )
    for other in ("es", "eng", "de", "fr", "e"):
        active, reason = PE.language_gate(other, gate)
        assert active is False, f"{other!r} must never inherit en's verdict"
        assert reason == "never evaluated"


def test_a_region_tagged_report_key_is_reachable_by_a_bare_article_language():
    """Normalised on BOTH sides (the 2026-07-29 lesson's second half): a report keyed
    `en-US` must not create a bucket no article can ever address."""
    gate = PE.gate_languages_from_report(
        {
            "status": "ok",
            "report": {
                "by_language": {
                    "en-US": {
                        "where": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 1},
                        "n_cases": 1,
                    }
                }
            },
        }
    )
    assert set(gate) == {"en"}
    assert PE.language_gate("en", gate)[0] is True


def test_an_unknown_language_still_refuses_and_says_so():
    """Normalisation must not turn "we do not know" into a lookup miss that reads as
    "the harness never tested it" -- they are different facts."""
    gate = {"en": {"active": True, "reason": "cleared", "fields": {}}}
    for empty in (None, "", "   ", "-"):
        assert PE.language_gate(empty, gate) == (False, "article has no known language")
        assert PE.field_gate(empty, "who", gate) == (False, "article has no known language")


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

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        return _FakeResult("WHO: Acme Corp\nWHERE: Springfield\nWHEN: 2024-01-01")


class _AlwaysNothingClient:
    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        return _FakeResult("WHO: none\nWHERE: none\nWHEN: none")


class _HallucinatingUnparseableClient:
    """Never replies in the constrained format -- a garbage answer."""

    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
        return _FakeResult("I refuse to answer this request.")


class _RaisingClient:
    def generate(self, prompt, *, model, system=None, options=None, keep_alive=None):
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


def test_a_region_tagged_article_is_extracted_not_gated(db):
    """The field defect, end to end through the real batch runner: an `en-US` article
    against an `en` gate must reach the model and be stored, not counted as gated."""
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    a = _mk_article(db, src, 1, language="en-US")
    db.commit()

    gate = {
        "en": {
            "active": True,
            "reason": "cleared the S6.5 harness",
            "fields": {f: {"active": True, "reason": "cleared"} for f in ("who", "where", "when")},
        }
    }
    work = [ArticleWork(a.id, a.title, a.content, a.language)]
    result = PE.extract_perception_batch(db, work, _FakeClient(), model="stub:test", gate=gate)

    assert result["gated"] == 0, result["gated_detail"]
    assert result["attempted"] == 1
    assert result["stored"] == 1
    assert db.query(AiKeyword).count() > 0


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
        # AMENDED 2026-08-01 (E-S3): this used to assert the reason did not even
        # CONTAIN the words who/when. Under the per-field gate it does -- as
        # "unmeasured for who, when", which the reader needs, because those fields
        # will not be stored. So the assertion moves to the property the test is
        # actually named for: never FAILED, and never described as failed.
        assert gate[lang]["fields"]["who"]["active"] is None
        assert gate[lang]["fields"]["when"]["active"] is None
        assert "failed" not in gate[lang]["reason"], gate[lang]["reason"]
        assert "unmeasured for who, when" in gate[lang]["reason"]
    for lang in ("en", "de", "es", "fr"):
        # These four DO carry who/when gold, and the extractor recovered none of it.
        # AMENDED 2026-08-01 (E-S3): the floor still has to bite -- but on the FIELDS
        # that were tested and failed, not on `where`, which this extractor got right.
        # Asserting the whole language off would now re-encode the collapse the ruling
        # removed, and would silently discard a `where` extraction that measurably works.
        assert gate[lang]["fields"]["who"]["active"] is False, (lang, gate[lang])
        assert gate[lang]["fields"]["when"]["active"] is False, (lang, gate[lang])
        assert gate[lang]["fields"]["where"]["active"] is True, (lang, gate[lang])
        assert PE.field_gate(lang, "who", gate)[0] is False
        assert PE.field_gate(lang, "where", gate)[0] is True


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


# --------------------------------------------------------------------------- #
# E-S3 (2026-08-01, ruling 16's granularity ask): the PER-FIELD gate.
#
# Both directions, because a gate is only honest if it can be shown to bite AND to
# let through: an over-tight gate reads as conservative while quietly deleting a
# measurement that works, and only the second direction catches that.
# --------------------------------------------------------------------------- #
def _mixed_gate():
    """`where` cleared, `who` failed on hallucination, `when` never tested."""
    return PE.gate_languages_from_report(
        {
            "status": "ok",
            "report": {
                "by_language": {
                    "en": {
                        "n_cases": 3,
                        "who": {"hallucination_rate": 0.9, "recall": 1.0, "n_gold": 2},
                        "where": {"hallucination_rate": 0.0, "recall": 1.0, "n_gold": 2},
                        "when": {"hallucination_rate": None, "recall": None, "n_gold": 0},
                    }
                }
            },
        }
    )


def test_a_failing_field_stays_gated_while_its_passing_sibling_activates():
    gate = _mixed_gate()
    assert PE.field_gate("en", "who", gate)[0] is False
    assert PE.field_gate("en", "where", gate)[0] is True


def test_an_untested_field_refuses_and_says_unmeasured_not_failed():
    """The tri-state runs one level down too: 'we never looked' is not 'it failed',
    and it is certainly not 'it passed'."""
    gate = _mixed_gate()
    ok, reason = PE.field_gate("en", "when", gate)
    assert ok is False
    assert "UNMEASURED" in reason and "failed" not in reason


def test_a_gate_without_per_field_verdicts_falls_back_to_the_language_verdict():
    """An artifact persisted before per-field verdicts existed must keep working —
    at the OLD behaviour, never at an invented per-field one."""
    legacy = {"en": {"active": True, "reason": "cleared the S6.5 harness"}}
    assert PE.field_gate("en", "who", legacy)[0] is True
    legacy_off = {"en": {"active": False, "reason": "failed"}}
    assert PE.field_gate("en", "who", legacy_off)[0] is False


def test_extraction_stores_only_the_cleared_fields_and_counts_the_rest(db):
    """The three fields come from ONE call, so a gated field is generated and then
    DISCARDED. The tally must say so: a zero `who` count beside a real `where` count
    has to read as gated, not as 'the model found nothing'."""
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    _mk_article(db, src, 1, content="Acme met in Springfield on 1 January 2024.")
    db.commit()

    work = PE.select_perception_batch(db, 0, 10)
    tally = PE.extract_perception_batch(
        db, work, _FakeClient(), model="m", gate=_mixed_gate()
    )
    assert tally["where"] >= 1, "the cleared field is stored"
    assert tally["who"] == 0 and tally["when"] == 0
    assert tally["field_gated"]["who"] == 1 and tally["field_gated"]["when"] == 1
    kinds = {k.kind for k in db.query(AiKeyword).all()}
    assert kinds == {"ai-place"}, kinds
    # ...and the trusted rule-based tables are untouched, as ever.
    assert _row_counts(db) == (0, 0, 0)


def test_a_language_active_for_one_field_is_still_worth_a_call(db):
    """The article-level gate answers 'is this worth a call at all?'. Refusing the
    whole article because one field is gated would throw away the field that works —
    the exact collapse this change removes."""
    gate = _mixed_gate()
    active, reason = PE.language_gate("en", gate)
    assert active is True
    assert "gated for who" in reason and "unmeasured for when" in reason

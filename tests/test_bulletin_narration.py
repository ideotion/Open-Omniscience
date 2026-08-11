"""
Layer B — the removable narration.

The tests here are almost all about what happens when the model misbehaves,
because that is where the design lives. A model that writes clean prose needs no
machinery; a model that invents a figure is the reason all of this exists.

No real model is involved anywhere: a fake client returns whatever text the test
needs, and the real code decides what to do with it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.bulletin.narration import (
    DEFAULT_OPTIONS,
    NARRATION_PROMPT_VERSION,
    deterministic_paragraph,
    narrate,
    narrate_story,
)

_STORY = {
    "article_ids": [1, 2],
    "articles": 2,
    "distinct_sources": 2,
    "shared_terms": ["flood", "valencia"],
    "single_source": False,
}

_EVIDENCE = {
    "article_ids": [1, 2],
    "excerpts": [
        {
            "article_id": 1,
            "title": "Flooding in Valencia",
            "text": "Heavy rain hit Valencia. The regional government evacuated 300 people.",
        },
        {
            "article_id": 2,
            "title": "Rescue effort continues",
            "text": "Rescuers worked overnight in Valencia after the flooding.",
        },
    ],
}


class _Fake:
    """A model that says exactly what the test tells it to."""

    def __init__(self, text="", *, raises=None):
        self.text = text
        self.raises = raises
        self.calls: list[dict] = []

    def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
        self.calls.append({"prompt": prompt, "system": system, "options": options, "model": model})
        if self.raises:
            raise self.raises

        class _R:
            pass

        r = _R()
        r.text = self.text
        return r


def _narrate(text, **kw):
    return narrate_story(
        _STORY,
        _EVIDENCE,
        client=_Fake(text),
        model="m",
        backend="fake",
        language=kw.pop("language", "en"),
        **kw,
    )


# -- the grounding gate decides what survives ------------------------------- #


def test_a_grounded_sentence_is_kept():
    out = _narrate("Rescuers worked overnight in Valencia.")
    assert out["narrated"] is True
    assert "Valencia" in out["text"]
    assert out["sentences"][0]["kept"] is True


def test_an_invented_figure_costs_the_sentence_not_the_paragraph():
    out = _narrate(
        "Rescuers worked overnight in Valencia. The state moved 9,000 people."
    )
    assert out["narrated"] is True
    assert "9,000" not in out["text"], "the invented sentence must not reach the document"
    assert out["sentences_kept"] == 1 and out["sentences_dropped"] == 1


def test_a_partly_validated_paragraph_says_so():
    """A paragraph with pieces removed is still a model's paragraph with pieces
    removed — saying so is the difference between "checked" and "clean"."""
    out = _narrate("Rescuers worked in Valencia. It cost 9,000 euro.")
    assert out["partial"] is True


def test_a_fully_clean_paragraph_is_not_marked_partial():
    assert _narrate("Rescuers worked overnight in Valencia.")["partial"] is False


def test_when_every_sentence_fails_the_template_takes_over():
    out = _narrate("The Bavarian Assembly moved 9,000 people. It cost 4,000 euro.")
    assert out["narrated"] is False
    assert "flood" in out["text"], "the deterministic template names the real shared terms"
    assert "not in the evidence" in out["fallback_reason"] or "figure or name" in out[
        "fallback_reason"
    ]


def test_the_rejected_text_is_kept_for_inspection_but_not_published():
    out = _narrate("The Bavarian Assembly moved 9,000 people.")
    assert out["raw"], "the rejected output is recorded"
    assert "Bavarian" not in out["text"], "and is not what the document shows"


# -- degrading -------------------------------------------------------------- #


def test_a_model_failure_degrades_to_the_template():
    out = narrate_story(
        _STORY,
        _EVIDENCE,
        client=_Fake(raises=RuntimeError("backend down")),
        model="m",
        backend="fake",
    )
    assert out["narrated"] is False
    assert "backend down" in out["fallback_reason"]
    assert out["text"] == deterministic_paragraph(_STORY)


def test_an_empty_answer_degrades_to_the_template():
    out = _narrate("   ")
    assert out["narrated"] is False
    assert "returned nothing" in out["fallback_reason"]


def test_a_story_with_no_readable_text_is_never_narrated():
    """Narration must be grounded in something. With nothing to ground in, there
    is nothing to check, so there is nothing to publish."""
    out = narrate_story(
        _STORY, {"article_ids": [], "excerpts": []}, client=_Fake("Anything at all."),
        model="m", backend="fake",
    )
    assert out["narrated"] is False
    assert "no article text" in out["fallback_reason"]


def test_no_backend_degrades_whole_and_states_the_reason_once(monkeypatch):
    monkeypatch.setattr(
        "src.llm.backend.get_client_with_name",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("nothing reachable")),
    )
    out = narrate([_STORY, _STORY], lambda _s: _EVIDENCE)
    assert out["available"] is False
    assert "nothing reachable" in out["reason"]
    assert out["stories_narrated"] == 0
    assert all(p["text"] == deterministic_paragraph(_STORY) for p in out["paragraphs"])


def test_evidence_that_cannot_be_built_costs_one_story_not_the_run():
    def _evidence(story):
        if story is _STORY:
            raise RuntimeError("unreadable")
        return _EVIDENCE

    other = dict(_STORY, article_ids=[3, 4])
    out = narrate([_STORY, other], _evidence, client=_Fake("Rescuers worked in Valencia."))
    assert out["paragraphs"][0]["narrated"] is False
    assert "unreadable" in out["paragraphs"][0]["fallback_reason"]
    assert out["paragraphs"][1]["narrated"] is True


# -- the layer is removable ------------------------------------------------- #


def test_the_deterministic_paragraph_is_made_only_of_layer_a_counts():
    text = deterministic_paragraph(_STORY)
    assert "2 articles" in text and "2 sources" in text
    assert "flood" in text


def test_a_single_source_story_says_repetition_not_corroboration():
    text = deterministic_paragraph(dict(_STORY, distinct_sources=1, single_source=True))
    assert "repetition rather than corroboration" in text


def test_removing_the_layer_leaves_a_complete_document(monkeypatch):
    """The test of whether Layer B was built as an addition or a dependency."""
    monkeypatch.setattr(
        "src.llm.backend.get_client_with_name",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("no model")),
    )
    out = narrate([_STORY], lambda _s: _EVIDENCE)
    assert all(p["text"] for p in out["paragraphs"]), "every story still has a paragraph"
    assert "complete without it" in out["caveat"]


# -- determinism and provenance --------------------------------------------- #


def test_temperature_zero_reaches_the_backend():
    """An edition regenerated should read the same, and vLLM now maps options to
    OpenAI sampling — so this is the setting, not a hope."""
    fake = _Fake("Rescuers worked in Valencia.")
    narrate_story(_STORY, _EVIDENCE, client=fake, model="m", backend="fake")
    assert fake.calls[0]["options"]["temperature"] == 0.0
    assert DEFAULT_OPTIONS["temperature"] == 0.0


def test_the_caller_can_override_sampling():
    fake = _Fake("Rescuers worked in Valencia.")
    narrate_story(
        _STORY, _EVIDENCE, client=fake, model="m", backend="fake", options={"temperature": 0.7}
    )
    assert fake.calls[0]["options"]["temperature"] == 0.7


def test_every_paragraph_records_which_articles_it_could_have_come_from():
    out = _narrate("Rescuers worked in Valencia.")
    assert out["article_ids"] == [1, 2]
    assert out["model"] == "m" and out["backend"] == "fake"
    assert out["prompt_version"] == NARRATION_PROMPT_VERSION


def test_each_sentence_carries_its_own_verdict():
    out = _narrate("Rescuers worked in Valencia. It moved 9,000 people.")
    assert [s["kept"] for s in out["sentences"]] == [True, False]
    assert out["sentences"][1]["unsupported"] == ["9000"]


# -- what the model is not asked to do -------------------------------------- #


def test_the_prompt_forbids_judgement_and_invention():
    fake = _Fake("Rescuers worked in Valencia.")
    narrate_story(_STORY, _EVIDENCE, client=fake, model="m", backend="fake")
    system = fake.calls[0]["system"]
    assert "Do not invent" in system
    assert "important, significant, major or notable" in system
    assert "Do not rank" in system


def test_the_evidence_the_model_sees_is_the_evidence_it_is_checked_against():
    """A title the model was shown must count as evidence, or a real name lifted
    from a headline would be reported as an invention."""
    out = narrate_story(
        _STORY,
        _EVIDENCE,
        client=_Fake("Coverage described Flooding in Valencia."),
        model="m",
        backend="fake",
        language="en",
    )
    assert out["narrated"] is True


def test_the_caveat_labels_the_output_and_states_the_limit():
    out = narrate([_STORY], lambda _s: _EVIDENCE, client=_Fake("Rescuers worked in Valencia."))
    assert "AI-derived" in out["caveat"]
    assert "does NOT catch real facts arranged into a false claim" in out["caveat"]


def test_no_score_shaped_field_anywhere():
    out = narrate([_STORY], lambda _s: _EVIDENCE, client=_Fake("Rescuers worked in Valencia."))
    flat = json.dumps(out, default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


def test_the_number_of_stories_narrated_is_bounded_and_the_total_is_reported():
    out = narrate(
        [_STORY] * 20, lambda _s: _EVIDENCE, client=_Fake("Rescuers worked in Valencia."),
        max_stories=3,
    )
    assert out["stories_shown"] == 3
    assert out["stories_available"] == 20, "a cap on narration never hides the real count"


# -- the two layers meeting ------------------------------------------------- #


def test_narration_off_leaves_layer_a_byte_identical():
    """Turning narration on must ADD; it must never change a number already there.
    That asymmetry is what "removable" means in practice.

    AMENDED 2026-08-11, deliberately. This used to assert ``"stories" not in plain``
    as part of that property. It is not part of it: story clustering is MinHash over
    stored keywords — no model, no network, deterministic — and it now runs in phase
    one, where the maintainer's two-phase design puts everything the corpus can answer
    without a model. Coupling it to narration left the AI-less document with no
    stories at all. The property that actually matters is unchanged and still asserted
    below: narration adds a block and sentences, and changes no figure that was
    already there — including the stories' own counts.
    """
    from datetime import date, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.bulletin.edition import build_edition
    from src.bulletin.period import resolve_period
    from src.database.models import Article, Base, Source

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="A", domain="a.test")
    s.add(src)
    s.flush()
    for i in range(3):
        s.add(
            Article(
                url=f"u{i}", canonical_url=f"u{i}", source_id=src.id, title="t",
                content="body", hash=f"{i:064d}", language="en",
                published_at=datetime.fromisoformat("2026-07-27 12:00:00"), quarantined=False,
            )
        )
    s.commit()
    period = resolve_period("weekly", end=date(2026, 8, 1))

    plain = build_edition(s, period, narrate=False)
    narrated = build_edition(s, period, narrate=True, client=_Fake("Nothing to say."))

    assert plain["narration_requested"] is False
    assert "narration" not in plain, "the model layer is genuinely absent"
    for key in ("masthead", "period", "sections"):
        assert json.dumps(plain[key], default=str) == json.dumps(narrated[key], default=str), key

    # Phase one carries the deterministic clusters.
    assert "stories" in plain, "story clustering is AI-less and belongs to phase one"

    # And narration changes none of their figures — only adds a `narration` key to
    # each. This is the same "adds, never changes" property one level deeper, which
    # the old `"stories" not in plain` assertion could not reach at all.
    def _facts(edition):
        return [
            {k: v for k, v in st.items() if k != "narration"}
            for st in (edition.get("stories") or {}).get("stories") or []
        ]

    assert json.dumps(_facts(plain), default=str) == json.dumps(_facts(narrated), default=str)

    # The older, narrower behaviour is still reachable exactly.
    narrower = build_edition(s, period, narrate=False, cluster_stories=False)
    assert "stories" not in narrower and "narration" not in narrower
    for key in ("masthead", "period", "sections"):
        assert json.dumps(narrower[key], default=str) == json.dumps(plain[key], default=str), key


def test_a_clustering_failure_leaves_the_record_intact(monkeypatch):
    from datetime import date

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.bulletin import edition as edition_mod
    from src.bulletin.edition import build_edition
    from src.bulletin.period import resolve_period
    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    monkeypatch.setattr(
        "src.bulletin.stories.build_stories",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("clustering exploded")),
    )
    out = build_edition(s, resolve_period("weekly", end=date(2026, 8, 1)), narrate=True)
    assert out["masthead"]["articles"] == 0, "the deterministic record survives"
    assert "clustering exploded" in out["stories"]["error"]
    assert out["narration"]["available"] is False
    assert edition_mod is not None

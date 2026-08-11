"""A paragraph has to find its story, and the document has to describe what happened.

``narrate_story`` keyed each paragraph on the EVIDENCE's article ids — only those
articles whose text fit the char budget — while both consumers looked it up by the
STORY's full cluster. In the field edition of 2026-08-10 that was 15 ids against
115, so the join missed on every story large enough to be interesting and three
things followed silently:

* the deterministic sentence composed from the story's own counts never rendered,
  though it was sitting in the record;
* the review screen's per-sentence verdicts — the §13 requirement, "a sentence the
  operator can see was checked is a different thing from a paragraph labelled
  validated" — came out empty, because those live on the paragraph;
* and the edition still appended "the sentences under each story were written by a
  local model", on a run where Ollama refused every connection and nought of eight
  stories had been narrated.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.edition import build_edition
from src.bulletin.narration import narrate_story
from src.bulletin.period import resolve_period
from src.bulletin.review import review_view
from src.database.models import Base

# A story bigger than any evidence budget, which is the ordinary case.
_BIG_IDS = list(range(1, 116))
_STORY = {
    "article_ids": _BIG_IDS,
    "articles": len(_BIG_IDS),
    "distinct_sources": 1,
    "shared_terms": ["alerta", "vientos"],
    "single_source": True,
}
# What the model was actually shown: the first few that fit.
_EVIDENCE = {
    "article_ids": _BIG_IDS[:15],
    "excerpts": [{"article_id": i, "title": "t", "text": "Vientos in the region."}
                 for i in _BIG_IDS[:15]],
}


class _Reply:
    def __init__(self, text):
        self.text = text


class _Fake:
    """Shaped like the real client: ``generate`` returns an object carrying
    ``.text``, not a bare string. A double that returns the wrong shape makes
    narration silently fall back, which reads exactly like a validation failure."""

    def __init__(self, text=""):
        self.text = text

    def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
        return _Reply(self.text)


# --------------------------------------------------------------------------- #
#  the key
# --------------------------------------------------------------------------- #
def test_a_paragraph_is_keyed_to_its_story_not_to_the_subset_it_was_shown():
    out = narrate_story(_STORY, _EVIDENCE, client=_Fake("Vientos in the region."),
                        model="m", backend="fake")
    assert out["article_ids"] == _BIG_IDS, (
        "the identity every consumer joins on must be the story's own cluster"
    )


def test_the_paragraph_still_records_which_articles_it_could_have_come_from():
    """The subset is real provenance and keeps its own key — it just is not the
    identity. With the two lists equal, as every fixture used to have them, no test
    could tell which key meant which."""
    out = narrate_story(_STORY, _EVIDENCE, client=_Fake("Vientos in the region."),
                        model="m", backend="fake")
    assert out["grounded_in_article_ids"] == _BIG_IDS[:15]
    assert out["grounded_in_article_ids"] != out["article_ids"]


def test_a_paragraph_from_the_no_evidence_path_carries_the_same_identity():
    """Three paths build a paragraph and they used to disagree about the key, so
    whether the join worked depended on which failure had occurred."""
    out = narrate_story(_STORY, {"article_ids": [], "excerpts": []},
                        client=_Fake("x"), model="m", backend="fake")
    assert out["narrated"] is False
    assert out["article_ids"] == _BIG_IDS
    assert out["grounded_in_article_ids"] == []


# --------------------------------------------------------------------------- #
#  end to end
# --------------------------------------------------------------------------- #
def _edition(monkeypatch, *, text: str, stories=None):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    monkeypatch.setattr(
        "src.bulletin.stories.build_stories",
        lambda *_a, **_k: {"stories": list(stories if stories is not None else [dict(_STORY)]),
                           "stories_found": 1, "stories_shown": 1},
    )
    monkeypatch.setattr(
        "src.bulletin.stories.story_evidence", lambda *_a, **_k: dict(_EVIDENCE)
    )
    return build_edition(
        s, resolve_period("weekly", end=date(2026, 8, 11)), narrate=True, client=_Fake(text)
    )


def test_a_large_story_gets_its_paragraph_attached(monkeypatch):
    ed = _edition(monkeypatch, text="Vientos in the region.")
    story = ed["stories"]["stories"][0]
    assert story.get("narration"), "the paragraph never reached the story"
    assert story["narration"]["text"]
    assert ed["narration"]["paragraphs_attached"] == 1
    assert "attach_gap" not in ed["narration"]


def test_the_deterministic_sentence_reaches_the_page(monkeypatch):
    """The model says nothing usable, so the template stands in — which is the whole
    point of the fallback, and it was invisible for as long as the join missed."""
    from src.bulletin.render import render_markdown

    ed = _edition(monkeypatch, text="")
    md = render_markdown(ed)
    # Assert text ONLY the deterministic paragraph produces. "115 articles" would
    # not do: the story's own header line prints that whether a paragraph attached
    # or not, so the first draft of this test passed with the join still broken.
    assert "shared the terms" in md
    assert "repetition rather than corroboration" in md


def test_the_review_screen_can_show_the_per_sentence_verdicts(monkeypatch):
    """§13: the operator sees each sentence's verdict. Those live on the paragraph,
    so a missed join emptied the list the screen exists to show."""
    ed = _edition(monkeypatch, text="Vientos in the region.")
    view = review_view(ed)
    assert view["stories"], "no story reached the review screen"
    assert view["stories"][0]["sentences"], "the verdicts are the point of the screen"


# --------------------------------------------------------------------------- #
#  what the document says about itself
# --------------------------------------------------------------------------- #
def test_an_edition_that_narrated_nothing_does_not_claim_a_model_wrote_it(monkeypatch):
    ed = _edition(monkeypatch, text="")
    assert ed["narration"]["stories_narrated"] == 0
    assert "written by a local model" not in ed["caveat"]
    assert "produced nothing" in ed["caveat"]


def test_an_edition_that_did_narrate_says_how_many(monkeypatch):
    """The twin. Suppressing the claim outright would pass the test above and lose
    the label that makes the layer removable."""
    ed = _edition(monkeypatch, text="Vientos in the region.")
    assert ed["narration"]["stories_narrated"] == 1
    assert "written by a local model" in ed["caveat"]
    assert "1 of 1" in ed["caveat"]


def test_a_dangling_join_is_reported_rather_than_absorbed(monkeypatch):
    """The failure mode that hid for a year: an unmatched story is indistinguishable
    from a story nobody tried to narrate. Now it says so."""
    import src.bulletin.narration as nar

    real = nar.narrate

    def _mismatched(stories, evidence_of, **kw):
        out = real(stories, evidence_of, **kw)
        for p in out["paragraphs"]:
            p["article_ids"] = [999_999]
        return out

    monkeypatch.setattr("src.bulletin.narration.narrate", _mismatched)
    ed = _edition(monkeypatch, text="Vientos in the region.")
    assert ed["narration"]["paragraphs_attached"] == 0
    assert "disagree about the key" in ed["narration"]["attach_gap"]

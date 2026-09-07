"""
The edition's introduction — §20 question 2, RULED narrated by the model.

The maintainer chose the narrated form over a templated one. What that ruling does
NOT do is make the paragraph optional: the template beside it is the same §8 rule
every Layer-B sentence obeys, and it is what stops a document produced below the
hardware gate from opening with nothing at all.

Three properties are pinned, and two of them are the honesty ones:

* an invented figure is DROPPED, because the grounding evidence is the edition's
  own figures and nothing else;
* the fallback text is real prose made of the same numbers, so the model's absence
  costs style and never substance;
* the paragraph never names a leading subject — that is the composite judgement
  §11 refuses, and the prompt has to say so.

Pure: no DB, no network, no model.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.bulletin import introduction as I


class _Reply:
    def __init__(self, text: str) -> None:
        self.text = text


class _Client:
    def __init__(self, text: str = "", raises: bool = False) -> None:
        self.text = text
        self.raises = raises
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def generate(self, prompt, *, model=None, system=None, options=None):
        self.prompts.append(prompt)
        self.systems.append(system or "")
        if self.raises:
            raise RuntimeError("connection refused")
        return _Reply(self.text)


def _edition() -> dict:
    return {
        # persist_edition ALWAYS stamps generated_at, so a fixture without it is not
        # a smaller production record but a different one — and here it would send
        # the footer down its datetime.now() fallback, making any two renders differ
        # by microseconds. The recorded rule: make the fixture faithful, never
        # re-derive the expectation from the implementation's own clock.
        "generated_at": "2026-08-01T09:00:00+00:00",
        "period": {"cadence": "weekly", "start": "2026-07-25", "end": "2026-08-01", "days": 7},
        "masthead": {
            "articles": 412,
            "corpus_articles": 9001,
            "sources_contributing": 37,
            "languages": [{"language": "en", "articles": 300}, {"language": "fr", "articles": 112}],
            "source_countries": [
                {"country": "FR", "articles": 200},
                {"country": "DE", "articles": 150},
                {"country": "GB", "articles": 62},
            ],
            "days_with_ingest": 5,
            "period_days": 7,
            "top_3_share": 0.42,
        },
        "sections": [{"section": "a"}, {"section": "b"}],
        "stories": {"stories": [{"article_ids": [1, 2]}]},
    }


def _narrate(text: str, **kw):
    return I.narrate_introduction(
        _edition(), client=_Client(text), model="m", backend="b", **kw
    )


# --------------------------------------------------------------------------- #
#  the deterministic half
# --------------------------------------------------------------------------- #
def test_the_template_states_the_editions_own_numbers():
    out = I.deterministic_introduction(_edition())
    assert "412" in out and "37" in out
    assert "5" in out and "7" in out


def test_the_template_names_no_leading_subject():
    out = I.deterministic_introduction(_edition()).lower()
    for banned in ("most important", "top story", "dominated", "the biggest"):
        assert banned not in out


def test_a_record_with_no_masthead_still_produces_a_paragraph():
    """A degrade must not be a blank opening: an edition whose masthead failed still
    gets a sentence, and the em dashes say what could not be read."""
    out = I.deterministic_introduction({"period": {}, "masthead": {}})
    assert out.strip()


# --------------------------------------------------------------------------- #
#  the narrated half
# --------------------------------------------------------------------------- #
def test_a_grounded_paragraph_is_kept_and_marked_narrated():
    out = _narrate("The archive collected 412 articles from 37 sources.")
    assert out["narrated"] is True
    assert "412" in out["text"]


def test_an_invented_figure_is_dropped_and_the_template_takes_over():
    """The one check that matters: a figure the edition does not contain cannot
    reach the reader. 9999 appears in no bundle line."""
    out = _narrate("The archive collected 9999 articles.")
    assert out["narrated"] is False
    assert "9999" not in out["text"]
    assert "not among the edition's own" in out["fallback_reason"]
    assert out["sentences"][0]["kept"] is False


def test_a_partly_invented_paragraph_keeps_only_the_grounded_sentences():
    out = _narrate("It collected 412 articles. It also collected 9999 more.")
    assert out["narrated"] is True
    assert out["partial"] is True
    assert "9999" not in out["text"]
    assert "412" in out["text"]


def test_a_model_failure_degrades_to_the_template_with_the_reason():
    out = I.narrate_introduction(
        _edition(), client=_Client(raises=True), model="m", backend="b"
    )
    assert out["narrated"] is False
    assert "the model call failed" in out["fallback_reason"]
    assert out["text"] == I.deterministic_introduction(_edition())


def test_an_empty_answer_is_a_fallback_not_an_empty_paragraph():
    out = _narrate("")
    assert out["narrated"] is False
    assert out["text"].strip()
    assert "returned nothing" in out["fallback_reason"]


def test_the_prompt_forbids_naming_a_leading_subject():
    """§11 deliberately omits any 'top story'. A model told only to summarise would
    supply one, so the refusal has to be in the instruction."""
    client = _Client("It collected 412 articles.")
    I.narrate_introduction(_edition(), client=client, model="m", backend="b")
    system = client.systems[0].lower()
    assert "do not name a leading story" in system
    assert "important" in system


def test_the_model_is_shown_the_same_text_the_checker_reads():
    """One rendering feeds both. Two would let an invented number be "found" in a
    bundle the model was never given."""
    client = _Client("It collected 412 articles.")
    I.narrate_introduction(_edition(), client=client, model="m", backend="b")
    evidence = I.facts_text(I.introduction_facts(_edition()))
    assert evidence in client.prompts[0]


def test_the_block_carries_its_own_method_and_caveat():
    out = _narrate("It collected 412 articles.")
    assert "temperature 0" in out["method"]
    assert "AI-derived" in out["caveat"]
    assert "does not catch real figures arranged" in out["caveat"]


def test_the_no_model_block_has_the_same_shape_as_a_narrated_one():
    """Same shape rather than absent: a renderer branching on whether the key exists
    will one day forget, and an introduction that silently disappears is a document
    opening on its first section with nothing to say why."""
    a = I.deterministic_block(_edition(), "no backend")
    b = _narrate("It collected 412 articles.")
    for key in ("text", "narrated", "sentences", "prompt_version"):
        assert key in a and key in b


# --------------------------------------------------------------------------- #
#  it reaches the reader — a written key nothing renders is a dead end
# --------------------------------------------------------------------------- #
def test_the_introduction_reaches_both_renderers():
    from src.bulletin.render import render_html, render_markdown

    ed = _edition()
    ed["introduction"] = _narrate("It collected 412 articles.")
    md = render_markdown(ed)
    html = render_html(ed)
    assert "It collected 412 articles." in md
    assert "It collected 412 articles." in html
    assert "AI-derived" in md and "AI-derived" in html


def test_a_deterministic_introduction_is_NOT_labelled_ai_derived():
    """The label marks what a MODEL wrote. Putting it on a template would be the
    fabricated-AI-output mirror of hiding real model text."""
    from src.bulletin.render import render_markdown

    ed = _edition()
    ed["introduction"] = I.deterministic_block(ed, "no backend")
    md = render_markdown(ed)
    assert ed["introduction"]["text"] in md
    head = md[: md.index(ed["introduction"]["text"])]
    assert "AI-derived" not in head


def test_an_edition_with_no_introduction_renders_exactly_as_before():
    """Every edition already on disk carries none. The block must be additive."""
    from src.bulletin.render import render_markdown

    ed = _edition()
    before = render_markdown(ed)
    ed["introduction"] = {}
    assert render_markdown(ed) == before


def test_the_review_screen_shows_the_introductions_own_sentence_verdicts():
    from src.bulletin.review import review_view

    ed = _edition()
    ed["introduction"] = _narrate("It collected 412 articles. It also collected 9999 more.")
    view = review_view(ed)
    assert view["introduction"]["narrated"] is True
    kept = [s["kept"] for s in view["introduction"]["sentences"]]
    assert kept == [True, False]


def test_the_review_screen_omits_an_introduction_that_does_not_exist():
    from src.bulletin.review import review_view

    assert review_view(_edition())["introduction"] is None

"""Q512 — the ring at the centre, one arm per language, associations off the arms.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The GEOMETRY the mind-map rules constrain is driven in ``tests/concept_tree_node_test.js``
(centre → arms → always outward, no cross-tangle, deterministic), because those are
claims about coordinates and nothing but the coordinates can check them. What is pinned
here is the producer beneath it and the wiring around it: which arms exist, what they may
not claim, and that the view is reachable.

Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks exactly
like a passing one.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def corpus(tmp_path):
    """One concept in several languages, on a LOCAL engine.

    Two of the seeded articles carry `clima`, which the ring states as the form for
    Spanish, Italian AND Portuguese — that is not a fixture quirk, it is the case that
    made `form_shared_with` necessary and it belongs in the fixture rather than in a
    comment.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concept_map.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Session = sessionmaker(bind=engine, future=True)
    ex = BaselineExtractor()
    docs = [
        ("en", "Climate one", "the climate assembly met about the harbour district"),
        ("en", "Climate two", "climate policy and the climate assembly reported back"),
        ("fr", "Climat un", "le climat du quartier portuaire selon le rapport"),
        ("fr", "Climat deux", "le climat regional selon le rapport de l agence"),
        ("de", "Klima eins", "das Klima der Region wird seit vierzig Jahren erfasst"),
        ("es", "Clima uno", "el clima costero cambia segun el informe regional"),
        ("en", "Unrelated", "football results and the transfer window"),
    ]
    with Session() as s:
        srcs: dict[str, Source] = {}
        for i, (lg, title, body) in enumerate(docs):
            if lg not in srcs:
                src = Source(name=f"s-{lg}", rss_url=f"https://{lg}.test/f", domain=f"{lg}.test")
                s.add(src)
                s.flush()
                srcs[lg] = src
            u = f"https://{lg}.test/{i}"
            when = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=i)
            a = Article(title=title, content=body, url=u, canonical_url=u,
                        source_id=srcs[lg].id, language=lg, published_at=when,
                        created_at=when, hash=f"h{i}")
            s.add(a)
            s.flush()
            index_article(s, a, extractor=ex)
        s.commit()
    ensure_fts(engine, rebuild="always")
    with Session() as s:
        yield s
        s.rollback()


def test_concept_tree_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "concept_tree_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_one_arm_per_language_the_corpus_actually_carries(corpus):
    """An arm is a language this corpus HAS the concept in, never one the ring offers."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    assert ck.is_ring, "the fixture no longer resolves to a ring; the rest proves nothing"
    d = q.concept_arms(corpus, ck)
    langs = [a["language"] for a in d["arms"]]
    assert {"en", "fr", "de"} <= set(langs), f"a seeded language has no arm: {langs}"
    assert all(a["articles"] > 0 for a in d["arms"]), (
        "an arm was drawn for a language with no articles -- an empty arm asserts the "
        "concept exists there and is merely quiet, which is a different fact"
    )


def test_a_ring_language_this_corpus_has_nothing_in_is_NAMED_not_dropped(corpus):
    """The anti-capping rule, on a picture: name every population it omits."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    d = q.concept_arms(corpus, ck)
    missing = {n["language"] for n in d["not_observed"]}
    assert missing, "every ring language is present, so this test proves nothing"
    assert not (missing & {a["language"] for a in d["arms"]}), (
        "a language is both an arm and not-observed"
    )
    assert all(n["forms"] for n in d["not_observed"]), (
        "a not-observed language does not say WHICH form was looked for, so the reader "
        "cannot tell whether the gap is the corpus or the ring"
    )


def test_the_arms_overlap_and_the_centre_does_not(corpus):
    """The figure that would be read as a total if nothing said otherwise."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    d = q.concept_arms(corpus, ck)
    arm_sum = sum(a["articles"] for a in d["arms"])
    assert d["center"]["articles"] < arm_sum, (
        "the arms add up to the centre, so this corpus cannot demonstrate the overlap "
        "the caveat warns about -- the fixture needs a shared-form or bilingual article"
    )
    assert "do not add up" in d["caveat"]


def test_a_spelling_shared_by_several_languages_says_so(corpus):
    """`clima` is es, it AND pt: one article, three arms, and without this three arms
    that read as coverage in three languages."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    d = q.concept_arms(corpus, ck)
    shared = [a for a in d["arms"] if a.get("form_shared_with")]
    assert shared, (
        "no arm reports a shared spelling, although the fixture seeds `clima`, which "
        "the ring states for Spanish, Italian and Portuguese"
    )
    for a in shared:
        assert a["language"] not in a["form_shared_with"], "an arm shares with itself"
        assert all(
            set(a["forms"]) == set(o["forms"])
            for o in d["arms"] if o["language"] in a["form_shared_with"]
        ), "an arm claims to share a spelling with an arm that has a different one"


def test_the_concepts_own_forms_are_not_drawn_as_its_associations(corpus):
    """A ring member co-occurring with its own ring is the structure, not a finding."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    own = {str(k.normalized_term) for k in ck.keywords}
    d = q.concept_arms(corpus, ck)
    for a in d["arms"]:
        for x in a["associations"]:
            assert str(x["term"]).casefold() not in own, (
                f"{x['term']!r} is a form of the concept and is drawn as an association "
                "off its own arm"
            )


def test_the_ordering_is_deterministic(corpus):
    """Two runs over one corpus that disagree make CHANGE stop being signal."""
    ck = q.resolve_concept_keywords(corpus, "climate", ui_lang="en")
    a = q.concept_arms(corpus, ck)
    b = q.concept_arms(corpus, ck)
    assert [x["language"] for x in a["arms"]] == [x["language"] for x in b["arms"]]
    assert a["arms"] == b["arms"]
    counts = [x["articles"] for x in a["arms"]]
    assert counts == sorted(counts, reverse=True), "arms are not ordered by article count"


def test_the_endpoint_refuses_a_term_that_is_in_no_ring(corpus):
    """A one-armed tree is a straight line drawn as though it were a structure."""
    from src.api.insights import insights_concept_map

    d = insights_concept_map(term="zzqunringedterm", ui_lang="en", sense=None,
                             literal_cap=True, limit=8, db=corpus)
    assert d["expanded"] is False and d["arms"] == []
    assert d.get("skipped"), "the refusal carries no reason"
    live = insights_concept_map(term="climate", ui_lang="en", sense=None,
                                literal_cap=True, limit=8, db=corpus)
    assert live["expanded"] is True and live["arms"], (
        "neither term produced a tree, so the refusal above is vacuous"
    )


def test_the_mindmap_fetches_the_concept_map_on_the_typed_term_with_the_lens():
    """The wiring, and the two ways it would be subtly wrong.

    On the CORPUS'S TOP KEYWORD instead of the typed term, the view would draw the ring
    of whatever happens to be most frequent in the result set rather than of the word the
    reader searched. Without the lens, the tree and the list beside it would answer about
    different resolutions of that word.
    """
    body = strip_comments(read_static("app-analysis.js"))
    loader = function_body(body, "loadAnalysis")
    assert "/api/insights/concept-map?" in loader, "the Concept view has no payload"
    assert 'p.get("query")' in loader.split("/api/insights/concept-map?")[0][-800:], (
        "the concept map is not keyed on the typed term"
    )
    assert "_anMM.arms = cm" in loader, "the payload never reaches the renderer"
    assert 'cq.append("sense"' in loader and '"ui_lang", "literal_cap"' in loader, (
        "the lens does not travel to the concept map"
    )


def test_the_concept_view_is_offered_only_when_there_is_a_concept():
    """A Concept button on a term in no ring is a control that does nothing."""
    body = strip_comments(function_body(read_static("app-analysis.js"), "renderAnMindmap"))
    assert "_anMM.arms && _anMM.arms.expanded" in body, (
        "the Concept button is drawn unconditionally"
    )
    assert "_anConceptTreeSvg(" in body, "the Concept view draws nothing"
    assert "not_observed" in body, (
        "the view does not name the ring languages this corpus carries nothing in"
    )


def test_the_concept_view_survives_an_empty_association_graph():
    """A corpus can carry a concept in six languages and have no association to draw.

    Gated below the graph's own "no strong associations yet" line, the Concept button
    would be unreachable in exactly the young corpus it is most useful on.
    """
    body = strip_comments(function_body(read_static("app-analysis.js"), "renderAnMindmap"))
    assert "if (all.length < 2 && !_concept)" in body, (
        "the Concept view is gated on the association graph having content"
    )


def test_every_string_these_two_surfaces_render_is_keyed_in_all_twelve_locales():
    """The ×12 non-negotiable, at the point of use.

    Three of the nine come from the SERVER (the arms' method and caveat, and the watches
    panel's own caveat), so this asserts BOTH halves: that the client renders them through
    ``t()``, and that the server still EMITS the exact sentence the locale files are keyed
    on. A reworded caveat silently misses its key in eleven languages and renders in
    English — the defect a Chromium walk found on the analysis rail one PR earlier.
    """
    import ast
    import json

    analysis = strip_comments(read_static("app-analysis.js"))
    insights = strip_comments(read_static("app-insights.js"))
    ui_keys = [
        "This watch covers",
        "the concept “{concept}”",
        "in every language its ring carries.",
        "the same word in",
        "Not observed in this corpus:",
        "The concept at the centre, one arm per language, associations off the arms.",
    ]
    rendered = (
        function_body(insights, "_watchRingNote")
        + function_body(insights, "loadWatches")
        + function_body(analysis, "_anConceptTreeSvg")
        + function_body(analysis, "renderAnMindmap")
    )
    for key in ui_keys:
        assert key in rendered, f"{key!r} is not rendered by any of these functions"
    # The client must pass the server's own sentences through the translator.
    assert "t(d.method)" in function_body(analysis, "renderAnMindmap")
    assert "t(d.caveat)" in function_body(analysis, "renderAnMindmap")
    assert "t(d.caveat)" in function_body(insights, "loadWatches")
    emitted = set()
    for path in (
        _ROOT / "src" / "api" / "watches.py",
        _ROOT / "src" / "analytics" / "queries.py",
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                emitted.add(node.value)
    server_keys = [
        s for s in emitted
        if s.startswith("A watch is a saved search")
        or s.startswith("one arm per language the corpus")
        or s.startswith("The arms overlap")
    ]
    assert len(server_keys) == 3, (
        f"expected three server sentences, found {len(server_keys)} -- one was reworded, "
        "so its twelve locale keys are now dead"
    )
    locales = _ROOT / "src/static/locales"
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in ui_keys + server_keys:
            assert key in table, f"{path.name} has no entry for {key[:60]!r}"

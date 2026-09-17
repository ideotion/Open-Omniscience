"""S04-07 — one concept resolution for every search path (Q501, Q503, Q514, Q515).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gate row's bar is that *every analysis tab agrees with the Articles list on the same
concept*. These guards pin the pieces that bar rests on, and each one is written so the
mutation that removes its mechanism reddens BY NAME (the matrix is in the PR body).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics.equivalence import (
    CONCEPT_LITERAL_CAP,
    QueryExpander,
    resolve_concept,
)
from src.database.fts import build_match, search_ids, search_total

# --------------------------------------------------------------------------- #
# A ring fixture big enough to reach the cap, built by hand so the numbers in the
# assertions are facts about THIS file rather than about whatever the shipped ring
# files happen to contain today.
# --------------------------------------------------------------------------- #

_FORMS = 63  # Q503's own worked example: "expanded to 40 of 63 forms"


def _ring_fixture(monkeypatch, *, n_forms: int = _FORMS) -> tuple[str, list[str]]:
    """Install a single ring of ``n_forms`` distinct terms across three languages."""
    from src.analytics import equivalence as eq

    terms = ["climate"] + [f"klima{i:02d}" for i in range(n_forms - 1)]
    members = []
    for i, t in enumerate(terms):
        members.append((("en", "de", "fr")[i % 3], t))
    ring = eq.Ring(id="climate-change", members=tuple(members))
    # Clear the real caches FIRST (while ``load_rings`` is still the lru_cache'd
    # function that owns them), then swap it out and clear the two DERIVED indexes so
    # they rebuild from the fixture. Clearing after the swap would reach for
    # ``cache_clear`` on a plain lambda.
    eq.invalidate_ring_caches()
    monkeypatch.setattr(eq, "load_rings", lambda: (ring,))
    eq._index.cache_clear()
    eq._multi_index.cache_clear()
    monkeypatch.setattr(eq, "_enabled", lambda: True)
    return "climate", terms


@pytest.fixture()
def ring(monkeypatch):
    term, terms = _ring_fixture(monkeypatch)
    yield term, terms
    from src.analytics import equivalence as eq

    # UNDO FIRST, THEN CLEAR. ``monkeypatch``'s own finalizer runs AFTER this fixture's
    # teardown, so clearing here would leave the two derived indexes rebuilt from the
    # fixture ring and every later test in the session resolving against it — the
    # process-global-state pollution the conftest resets exist for.
    monkeypatch.undo()
    eq.invalidate_ring_caches()


# --------------------------------------------------------------------------- #
# Q504 — "only the words I typed" is a real refusal, not an approximation
# --------------------------------------------------------------------------- #


def test_expand_false_searches_exactly_the_typed_term_and_adds_nothing(ring):
    term, terms = ring
    c = resolve_concept(term, ui_lang="en", expand=False)
    assert c.literals == (term,)
    assert c.total_forms == 1
    assert c.expanded is False
    assert c("anything at all") == ()
    # The emitted MATCH must be byte-identical to a tree with no rings in it.
    assert build_match(term, expand=c) == build_match(term)


# --------------------------------------------------------------------------- #
# Q503 — the fan-out cap, and the anti-capping rule it must not break
# --------------------------------------------------------------------------- #


def test_the_cap_bounds_the_fan_out_and_never_the_reported_total(ring):
    term, terms = ring
    capped = resolve_concept(term, ui_lang="en")
    uncapped = resolve_concept(term, ui_lang="en", cap=None)

    assert capped.searched_forms == CONCEPT_LITERAL_CAP == 40
    assert uncapped.searched_forms == _FORMS
    # THE ANTI-CAPPING PROPERTY: both resolutions report the SAME exact total, and it is
    # the ring's real size — never the cap, on either side.
    assert capped.total_forms == uncapped.total_forms == _FORMS
    assert capped.cap_applied is True
    assert uncapped.cap_applied is False


def test_the_disclosure_states_both_numbers_and_the_ruling_s_own_sentence(ring):
    term, _ = ring
    c = resolve_concept(term, ui_lang="en")
    d = c.disclosure()
    assert d is not None
    row = next(t for t in d["terms"] if t["normalized"] == "climate")
    assert row["searched_forms"] == 40
    assert row["total_forms"] == _FORMS
    assert row["omitted_forms"] == _FORMS - 40
    assert row["capped"] is True
    assert d["capped"] is True and d["cap"] == 40
    # The row lists what was SEARCHED, not what the ring offers: a capped query that
    # named forms it never looked for would make the keyword group beside it offer
    # siblings the article count cannot account for.
    assert len(row["added_terms"]) == 39


def test_an_uncapped_search_discloses_no_cap_at_all(ring):
    term, _ = ring
    d = resolve_concept(term, ui_lang="en", cap=None).disclosure()
    assert d is not None
    assert "capped" not in d and "cap_caveat" not in d
    row = next(t for t in d["terms"] if t["normalized"] == "climate")
    assert row["capped"] is False and row["searched_forms"] == row["total_forms"]


def test_a_cap_that_admits_no_sibling_reports_the_search_as_NOT_widened(ring):
    """``expanded`` is a fact about the SEARCH, never about the ring.

    Under a cap of 1 the ring still offers 62 siblings and the query still looks for the
    typed form alone, so reading ``TermExpansion.expanded`` here would report a widening
    that did not happen.
    """
    term, _ = ring
    c = resolve_concept(term, ui_lang="en", cap=1)
    assert c.literals == (term,)
    assert c.expanded is False
    assert c.expander is not None and c.expander.any_expanded is False
    # And the underlying RING resolution is untouched: it still knows the siblings exist.
    assert len(c.expansion.siblings) == _FORMS - 1


# --------------------------------------------------------------------------- #
# Q503's "most frequent first" is a MEASUREMENT or it is not claimed
# --------------------------------------------------------------------------- #


def test_the_ordering_is_named_ring_order_when_no_frequency_resolver_answers(ring):
    term, _ = ring
    assert resolve_concept(term, ui_lang="en").ordering == "ring-order"


def test_a_frequency_resolver_reorders_the_cap_and_the_disclosure_says_so(ring):
    term, terms = ring
    # Make the LAST ring member the most-mentioned thing in the corpus.
    hot = terms[-1]
    c = resolve_concept(term, ui_lang="en", cap=3, frequency=lambda ts: {hot: 999})
    assert c.ordering == "corpus-frequency"
    assert c.literals[:2] == (term, hot)
    # ... and without the resolver that same form sits outside a cap of 3.
    plain = resolve_concept(term, ui_lang="en", cap=3)
    assert hot not in plain.literals


def test_a_measured_zero_and_an_unmeasured_form_are_different_facts(ring):
    """``Frequency``'s contract says an omitted term is UNMEASURED, never a zero.

    THE FIXTURE IS THE WHOLE TEST, and the first version of it could not discriminate:
    with one measured-zero sibling that was also FIRST in ring order, sorting it as
    measured and sorting it as a tied zero produce the same list, and the mutation that
    collapses the two survived. The discriminating shape needs a measured zero sitting
    BEHIND an unmeasured form in ring order, so the two rules disagree about which comes
    first — and a measured POSITIVE beside them, so the test still pins the ranking it is
    named for rather than only the tie-break.
    """
    term, terms = ring
    siblings = terms[1:]
    hot, measured_zero = siblings[5], siblings[1]
    c = resolve_concept(
        term,
        ui_lang="en",
        cap=None,
        frequency=lambda ts: {hot: 7, measured_zero: 0},
    )
    assert c.ordering == "corpus-frequency"
    got = list(c.literals[1:])
    # Measured first, by descending count; every UNMEASURED form keeps its ring position
    # behind them. A rule that read an omission as a zero would put ``siblings[0]`` —
    # which nobody measured — ahead of the form measured at zero.
    assert got[0] == hot, got[:4]
    assert got[1] == measured_zero, got[:4]
    assert got[2:] == [t for t in siblings if t not in (hot, measured_zero)]


# --------------------------------------------------------------------------- #
# Q515 = b — the exact, uncapped total describes the search that ran
# --------------------------------------------------------------------------- #


@pytest.fixture()
def fts_corpus():
    """Seven articles: 3 en ``climate``, 2 fr ``climat``, 2 de ``Klima``."""
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, "
                "content TEXT, quarantined INTEGER)"
            )
        )
        c.execute(
            text(
                "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, "
                "content='articles', content_rowid='id', "
                "tokenize='unicode61 remove_diacritics 2')"
            )
        )
        rows = (
            [("en", "climate change report")] * 3
            + [("fr", "le climat evolue")] * 2
            + [("de", "Klima bericht")] * 2
        )
        for i, (lg, body) in enumerate(rows, start=1):
            c.execute(
                text(
                    "INSERT INTO articles (id,title,content,quarantined) "
                    "VALUES (:i,:t,:b,0)"
                ),
                {"i": i, "t": f"{lg} doc {i}", "b": body},
            )
        c.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    S = sessionmaker(bind=eng)
    s = S()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def test_search_total_honours_the_expansion_hook_it_is_handed(fts_corpus):
    """The regression guard for a parameter that was accepted and dropped.

    ``search_total`` declared ``expand`` and called ``build_match(query)`` without it, so
    an expanded search's "exact total" described the LITERAL query. Live-reproduced on
    this exact fixture before the fix: 7 ids against a total of 3.
    """
    s = fts_corpus
    ex = QueryExpander(prefer_language="en")
    ids = search_ids(s, "climate", expand=ex)
    total = search_total(s, "climate", expand=ex)
    assert ids is not None and len(ids) == 7, ids
    assert total == 7, (
        "search_total must count the set search_ids returned; "
        f"got {total} for {len(ids)} ids"
    )


def test_the_literal_total_and_the_expanded_total_are_different_facts(fts_corpus):
    """The negative-space twin: the fix must not make every total the expanded one."""
    s = fts_corpus
    assert search_total(s, "climate") == 3
    assert search_total(s, "climate", expand=QueryExpander(prefer_language="en")) == 7


# --------------------------------------------------------------------------- #
# Q514 — expansion is RING-VERIFIED only
# --------------------------------------------------------------------------- #


def test_resolving_a_concept_never_reads_the_tentative_translation_table():
    """A ≈ machine translation may DISPLAY beside a keyword; it may never widen a query.

    Asserted as a property of what the resolver TOUCHES rather than as a filter that
    could be relaxed: the whole concept resolution runs with every attribute access on a
    ``keyword_translations`` sentinel recorded, and the recording must stay empty.
    """
    from src.analytics import equivalence as eq

    touched: list[str] = []

    class _Tripwire:
        def __getattr__(self, name):  # pragma: no cover - the point is that it is NOT hit
            touched.append(name)
            raise AssertionError(
                "concept resolution reached the tentative-translation table "
                f"(attribute {name!r}); Q514 says expansion is ring-verified only"
            )

    import src.database.models as models

    monkey = models.KeywordTranslation
    try:
        models.KeywordTranslation = _Tripwire()  # type: ignore[assignment]
        c = eq.resolve_concept("climate", ui_lang="fr")
        assert c is not None
    finally:
        models.KeywordTranslation = monkey  # type: ignore[assignment]
    assert touched == []


def test_the_resolver_offers_no_opt_in_argument_for_a_tentative_translation():
    """The ruling allows a PER-QUERY opt-in; none exists, so no caller can take one.

    A guard about a capability's ABSENCE, kept behavioural: a keyword argument nobody
    declared cannot be passed, and this is what makes "ring-verified only" a property of
    the signature rather than of everyone's memory.
    """
    import inspect

    from src.analytics import equivalence as eq

    params = set(inspect.signature(eq.resolve_concept).parameters)
    for forbidden in ("tentative", "translations", "allow_tentative", "include_tentative"):
        assert forbidden not in params, (
            f"resolve_concept grew a {forbidden!r} argument; Q514 requires an explicit, "
            "per-query opt-in that is never persisted as a default — adding one is a "
            "deliberate change, not a refactor"
        )


# --------------------------------------------------------------------------- #
# The four controls must have REAL defaults, not FastAPI sentinels
# --------------------------------------------------------------------------- #


CONCEPT_ROUTES = (
    "insights_corpus_keywords",
    "insights_corpus_www",
    "insights_corpus_facet_articles",
    "insights_corpus_sentiment",
    "insights_corpus_sources",
    "insights_trend",
    "insights_trend_articles",
    "insights_associations",
    "insights_keyword_stats",
    "insights_context",
    "insights_graph",
)


def test_the_four_controls_default_to_real_values_not_Query_sentinels():
    """A route called DIRECTLY must get ``None``/``True``, never a ``Query`` object.

    This repo calls route functions directly in several places (the diagnostics bundle
    builds a member by calling one), and a ``Query(...)`` default hands such a caller the
    sentinel itself. The recorded trap is that ``Query(False)`` is TRUTHY; the sharper
    version found here is that a ``Query`` object reaching ``.strip()`` raises, so two
    cache tests that had called ``insights_associations`` directly for years went red the
    moment these parameters landed.

    ``Annotated[T, Query(...)] = <default>`` keeps the OpenAPI description and gives every
    direct caller the real default. Asserted on the SIGNATURE rather than on one call,
    because the next such caller will be in a file named for something else entirely.
    """
    import inspect

    from fastapi import params as fastapi_params

    from src.api import insights as ins

    checked = 0
    for name in CONCEPT_ROUTES:
        fn = getattr(ins, name, None)
        assert fn is not None, f"{name} is not in src/api/insights.py any more"
        sig = inspect.signature(fn)
        for control, expected in (
            ("expand", True),
            ("ui_lang", None),
            ("sense", None),
            ("literal_cap", True),
        ):
            p = sig.parameters.get(control)
            assert p is not None, f"{name} lost its {control!r} control"
            assert not isinstance(p.default, fastapi_params.Param), (
                f"{name}.{control} defaults to a FastAPI sentinel; use "
                f"Annotated[T, Query(...)] = {expected!r} so a direct caller gets the "
                "real default"
            )
            assert p.default == expected, (
                f"{name}.{control} defaults to {p.default!r}, expected {expected!r}"
            )
            checked += 1
    # Anti-vacuity: the loop really visited every route and every control.
    assert checked == len(CONCEPT_ROUTES) * 4 == 44, checked


def test_a_cached_concept_endpoint_keys_its_cache_on_the_controls():
    """A key that forgets the toggle serves the answer the reader just turned off."""
    from src.api.insights import _xkey

    on = _xkey(True, "fr", ["climate:climate-change"], True)
    assert _xkey(False, "fr", ["climate:climate-change"], True) != on, "expand"
    assert _xkey(True, "en", ["climate:climate-change"], True) != on, "ui_lang"
    assert _xkey(True, "fr", [], True) != on, "sense"
    assert _xkey(True, "fr", ["climate:climate-change"], False) != on, "literal_cap"
    # ... and it is stable for one configuration, or every request misses.
    assert _xkey(True, "fr", ["climate:climate-change"], True) == on
    # Sense order must not change the key: two links naming the same pins are one search.
    assert _xkey(True, "fr", ["b:2", "a:1"], True) == _xkey(True, "fr", ["a:1", "b:2"], True)

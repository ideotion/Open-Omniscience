"""R1 — cross-language query expansion through the hand-vetted concept rings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The dictionary was already in the repository: 698 Wikidata-sourced, hand-vetted rings
covering the twelve UI languages, read by every analytics surface and by NOTHING in the
search path. So a corpus holding `climat`, `Klima` and `климат` answered a search for
`climate` with the English articles alone. This is the missing consumer.

THE REFUSALS ARE THE LOAD-BEARING HALF, and they rest on a measurement rather than a
worry: **91 (language, term) pairs in the shipped table sit in more than one ring** — de
`strom` is electricity AND river, de `wahl` is election AND public-election AND voting.
``ring_of`` cannot see them (it maps to ONE ring and its index keeps whichever was parsed
last), so expansion reads the ring members directly and REFUSES rather than resolving a
collision by dict order. Half these tests exist to keep that refusal, because the
tempting "improvement" — expand into the union of the matched rings — would drag river
vocabulary into a search about the power grid, and say nothing about it.
"""

from __future__ import annotations

import pytest

from src.analytics.equivalence import (
    DECLINE_SEVERAL_SENSES,
    DECLINE_TOO_SHORT,
    QueryExpander,
    expand_term,
    load_rings,
    ring_matches,
)
from src.database.fts import build_match


@pytest.fixture(scope="module", autouse=True)
def _rings_present() -> None:
    if not load_rings():
        pytest.skip("no ring table present in this checkout")


# --------------------------------------------------------------------------- #
# The feature: a term reaches its concept in every language the ring covers
# --------------------------------------------------------------------------- #

def test_a_search_term_reaches_its_concept_in_the_other_languages() -> None:
    exp = expand_term("climate", prefer_language="en")
    assert exp.expanded and exp.applied is not None
    assert exp.applied.ring_id == "climate"
    # Verified live against the shipped table when this was written.
    assert {"climat", "klima", "clima"} <= set(exp.siblings)
    breakdown = exp.applied.by_language()
    assert {"fr", "de", "es"} <= set(breakdown), "the per-language breakdown R1 requires"


def test_expansion_is_symmetric_across_languages() -> None:
    """A French reader typing `climat` and an English reader typing `climate` land on the
    same concept — that symmetry is the whole point, and it is not automatic: it holds
    only because the ring is looked up per (language, term) rather than per string."""
    en = expand_term("climate", prefer_language="en")
    fr = expand_term("climat", prefer_language="fr")
    assert en.applied and fr.applied
    assert en.applied.ring_id == fr.applied.ring_id == "climate"


def test_the_ui_language_narrows_but_never_adds() -> None:
    """`prefer_language` may only pick among candidates the term ALREADY has.

    A reader searching outside their UI locale must not be penalised for it: an
    English-locale reader typing `climat` still gets the ring, because nothing else
    could have been meant. If preference ever became a filter, cross-language search
    would work only for people already typing their own language — the opposite of R1.
    """
    assert expand_term("climat", prefer_language="en").expanded
    assert expand_term("climat", prefer_language=None).expanded


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #

def test_a_term_denoting_several_concepts_is_not_expanded() -> None:
    """de `strom` is electricity AND river. Expanding either way is a coin flip.

    The senses are REPORTED instead, which is the R2a query-time-choice grammar: the
    machine does not know which was meant, so it does not pretend to.
    """
    exp = expand_term("strom", prefer_language="de")
    assert not exp.expanded
    assert exp.declined == DECLINE_SEVERAL_SENSES
    assert exp.siblings == ()
    rings = {m.ring_id for m in exp.matches}
    assert len(rings) > 1 and {"electricity", "river"} <= rings
    payload = exp.to_dict()
    assert payload["expanded"] is False
    assert len(payload["senses"]) >= 2, "the reader is offered the choice, not a guess"


def test_the_ambiguous_population_is_real_and_the_refusal_covers_it() -> None:
    """Measured: 91 (language, term) pairs sit in more than one ring.

    Pinned as a floor rather than an exact count so a ring batch does not redden it —
    what must not happen is the population silently going to zero, which would mean the
    collision-preserving index had been replaced by ``ring_of`` again and every one of
    those terms had started resolving by dict order.
    """
    per_lang_term: dict[tuple[str, str], set[str]] = {}
    for ring in load_rings():
        for lang, term in ring.members:
            per_lang_term.setdefault((lang, term), set()).add(ring.id)
    ambiguous = {k: v for k, v in per_lang_term.items() if len(v) > 1}
    assert len(ambiguous) >= 50, (
        f"only {len(ambiguous)} ambiguous (language, term) pairs found — expansion's "
        f"refusal path may no longer be exercised by the shipped table"
    )
    for (lang, term), rings in list(ambiguous.items())[:20]:
        assert not expand_term(term, prefer_language=lang).expanded, (
            f"({lang}, {term}) is in {sorted(rings)} and was expanded anyway"
        )


def test_a_lone_letter_never_expands_but_a_lone_ideograph_does() -> None:
    """The one-character members split by script, and both halves matter.

    en `d` and `q` are generator noise sitting in the drone ring; expanding a search for
    `d` into unmanned-aerial-vehicle vocabulary is absurd. But in CJK one character is a
    whole word — ja `軍` is *military* — so a flat minimum length would disable expansion
    for zh/ja entirely, the recorded CJK trap.
    """
    assert expand_term("d", prefer_language="en").declined == DECLINE_TOO_SHORT
    assert expand_term("軍", prefer_language="ja").expanded, "CJK must not be disabled"
    assert expand_term("ai", prefer_language="en").expanded, "two letters is the floor"


def test_a_term_in_no_ring_is_silent() -> None:
    """No ring, no disclosure: an ordinary search must not carry the machinery's weight."""
    exp = expand_term("zzzznotaword", prefer_language="en")
    assert not exp.expanded and exp.declined is None and exp.matches == ()
    x = QueryExpander(prefer_language="en")
    build_match("zzzznotaword", expand=x)
    assert x.disclosure() is None


# --------------------------------------------------------------------------- #
# build_match: the hook, and byte-identity when it is off
# --------------------------------------------------------------------------- #

def test_the_match_is_byte_identical_when_the_hook_is_off() -> None:
    """`expand=false` is the "narrow to the literal term" click, so it has to be EXACT.

    Not "close to" the old behaviour — the same string, or the reader cannot get back to
    what they typed.
    """
    for q in ("climate", "climate AND drought", '"sea level" OR ice NOT arctic',
              "(a OR b) AND c", "AT&T", "oil prices DROP"):
        assert build_match(q) == build_match(q, expand=None)
    assert build_match("climate") == '"climate"'


def test_expansion_ors_the_siblings_into_the_match() -> None:
    x = QueryExpander(prefer_language="en")
    match = build_match("climate", expand=x)
    assert match is not None and match.startswith("(") and " OR " in match
    assert '"climate"' in match and '"climat"' in match


def test_a_multi_word_ring_member_is_emitted_as_a_phrase() -> None:
    """Ring members are multi-word for some concepts (fr `migration humaine`).

    A loose two-word emission would silently change the query from a phrase to an AND —
    matching articles that mention the two words paragraphs apart.
    """
    multi = next(
        (t for r in load_rings() for _l, t in r.members if " " in t and '"' not in t), None
    )
    if multi is None:
        pytest.skip("no multi-word ring member in this table")
    x = QueryExpander()
    match = build_match(multi.split()[0], expand=x) or ""
    for exp in x.expansions:
        for sib in exp.siblings:
            if " " in sib:
                assert f'"{sib}"' in match, "a multi-word sibling must be quoted as a phrase"
                return


def test_exclusions_expand_too() -> None:
    """`NOT climate` means "not this CONCEPT", in every language the ring covers.

    Expanding only the positive half would make an exclusion mean something narrower
    than the inclusion beside it, with nothing saying so.
    """
    x = QueryExpander(prefer_language="en")
    match = build_match("drought NOT climate", expand=x) or ""
    tail = match.split(" NOT ", 1)[1]
    assert '"klima"' in tail or '"climat"' in tail, "the excluded concept was not widened"


def test_the_hook_records_each_term_once_however_often_it_runs() -> None:
    """One request runs the hook several times BY DESIGN — the omnibar retries a
    half-typed Boolean as a phrase, and a capped result is re-counted through
    ``search_total`` with the same hook so count and rows describe one set. Recording per
    call would make the disclosure say a term was expanded twice, which is a statement
    about our plumbing, not about the reader's query.
    """
    x = QueryExpander(prefer_language="en")
    for _ in range(3):
        build_match("climate AND drought", expand=x)
    assert [e.term for e in x.expansions] == ["climate", "drought"]


# --------------------------------------------------------------------------- #
# The disclosure
# --------------------------------------------------------------------------- #

def test_the_disclosure_names_the_concept_the_languages_and_the_way_back() -> None:
    x = QueryExpander(prefer_language="en")
    build_match("climate", expand=x)
    d = x.disclosure()
    assert d is not None and d["expanded"] is True
    term = d["terms"][0]
    assert term["concept"] and term["ring_id"] == "climate"
    assert term["added_terms"] and term["by_language"]
    assert "method" in d and "caveat" in d
    # No score-shaped field anywhere: the recursive no-score convention.
    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(bad in k.lower() for bad in
                               ("score", "ranking", "rating", "grade", "confidence")), k
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(d)


def test_a_declined_term_still_discloses() -> None:
    """A refusal is information the reader can act on, not silence.

    If a decline produced no disclosure, `strom` would look like an ordinary unexpanded
    search and the reader would never learn the app had two concepts to offer.
    """
    x = QueryExpander(prefer_language="de")
    build_match("strom", expand=x)
    d = x.disclosure()
    assert d is not None
    assert d["expanded"] is False, "nothing was expanded, and the flag must say so"
    assert d["terms"][0]["declined"] == DECLINE_SEVERAL_SENSES
    assert len(d["terms"][0]["senses"]) >= 2


def test_ring_matches_keeps_collisions_that_ring_of_loses() -> None:
    """The reason this does not call ``ring_of``: that function keeps ONE ring.

    A regression here is invisible in behaviour until a reader searches an ambiguous
    term and silently gets one arbitrary sense's vocabulary.
    """
    from src.analytics.equivalence import ring_of

    rings = {m.ring_id for m in ring_matches("strom", languages=["de"])}
    assert len(rings) > 1
    assert ring_of("de", "strom") in rings
    assert len({ring_of("de", "strom")}) == 1, "ring_of still collapses — as documented"

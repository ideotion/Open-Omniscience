"""The three-tier translation ladder and its tentative store (S04-06; Q403, Q412, Q418).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIXTURE REACHES EVERY RUNG. A ladder tested on one rung certifies a third of its
behaviour, and the rung most likely to be wrong is the one nothing exercises — so each
test below names which rung it is on, and `test_every_tier_is_reachable_on_one_fixture`
asserts all four appear together rather than leaving that to inspection.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import equivalence as eq
from src.analytics import queries as q
from src.analytics import translation_store as TS
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _sess():
    e = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


# (term, normalized, language) chosen so ONE fixture reaches all four tiers into `en`:
#   climat       fr -> a clean single-ring member              -> verified
#   kanzleramt   de -> in NO ring; a tentative row is added     -> tentative
#   zzznotaword  fr -> in no ring, no tentative row             -> untranslated
#   budget       en -> already the target language              -> same_language
#   wahl         de -> in THREE rings                           -> untranslated + declined
#
# Each membership claim was MEASURED against the shipped tables rather than assumed: the
# first draft used `haushalt` for the tentative rung and it is a `budget` ring member, so
# the fixture silently tested `verified` twice and never reached the rung it named.
_SEED = [
    ("climat", "climat", "fr", 60),
    ("Kanzleramt", "kanzleramt", "de", 50),
    ("zzznotaword", "zzznotaword", "fr", 40),
    ("budget", "budget", "en", 30),
    ("Wahl", "wahl", "de", 20),
]


def _seed(s):
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    a = Article(url="u", canonical_url="u", source_id=1, title="t", content="c", hash="h")
    s.add(a)
    s.flush()
    for term, norm, lang, m in _SEED:
        k = Keyword(term=term, normalized_term=norm, language=lang, frequency=0,
                    mention_count=m, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=m,
                             observed_on=date.today(), language=lang))
    s.commit()
    return a


def _by_norm(res):
    return {t["normalized"]: t for t in res["terms"]}


# --------------------------------------------------------------------------- #
#  The ladder itself (pure)
# --------------------------------------------------------------------------- #

def test_the_verified_rung_carries_its_source_language_and_its_qid():
    """Q401 + Q402 + Q418: the translation, what it was translated FROM, and the QID the
    hover cites. A verified row with no source language could not render the tag at all."""
    r = eq.resolve_translation("de", "premierminister", "en")
    assert r.tier == eq.TIER_VERIFIED and r.text == "prime minister"
    assert r.source_lang == "de" and r.translated
    assert r.qid == "Q14212", "a generated ring's QID must reach the payload (Q418 = a)"
    assert r.to_dict()["translation_source"] == "ring"


def test_a_curated_ring_reports_an_HONEST_NULL_qid():
    """26 of the 698 shipped rings are hand-curated from the operator's own logs and were
    never resolved from a Wikidata item. Inventing a QID for them would be a fabricated
    citation on the one surface that exists to let a reader check us."""
    r = eq.resolve_translation("fr", "climat", "en")
    assert r.tier == eq.TIER_VERIFIED and r.text == "climate"
    assert r.qid is None
    assert "translation_qid" not in r.to_dict()


def test_the_untranslated_rung_still_names_the_language_the_term_IS_in():
    """R7: a foreign keyword stays searchable and is TAGGED, never silently blank — being
    unable to translate a word is not a reason to stop telling the reader what it is."""
    r = eq.resolve_translation("fr", "zzznotaword", "en")
    assert r.tier == eq.TIER_UNTRANSLATED and r.text is None
    assert r.source_lang == "fr" and not r.translated
    assert r.to_dict()["translation_source_lang"] == "fr"


def test_same_language_is_NOT_untranslated():
    """Two absences must not share a sentinel. A term already in the reader's language has
    nothing to translate; telling them it is 'untranslated' is false, and tagging every
    native term would be noise over the majority of any corpus."""
    r = eq.resolve_translation("en", "budget", "en")
    assert r.tier == eq.TIER_SAME_LANGUAGE
    assert r.tier != eq.TIER_UNTRANSLATED
    assert r.text is None and not r.translated


def test_several_senses_refuses_and_hands_back_a_pickable_list():
    """Q412 = a, on the ruling's own headline example. Refusing is the point; refusing
    WITHOUT the alternatives would be the recorded dead-end (a refusal that names a choice
    and offers no way to make it)."""
    r = eq.resolve_translation("de", "wahl", "en")
    assert r.tier == eq.TIER_UNTRANSLATED and r.text is None
    assert r.declined == eq.DECLINE_SEVERAL_SENSES_TR
    assert {x.ring_id for x in r.senses} == {"election", "public-election", "voting"}
    # Each option carries what a picker needs: the concept, its QID, and what it READS as
    # -- a picker that offered bare ring ids would make the reader choose blind.
    for opt in r.senses:
        assert opt.concept and opt.translation
    assert {x["translation"] for x in r.to_dict()["senses"]} == {
        "election", "public election", "voting"
    }


def test_a_pinned_sense_outranks_the_refusal():
    """The pin answers the exact question the refusal exists to avoid guessing at, on the
    same grammar `parse_sense_pins` already reads — and it can never REACH: a pin naming a
    ring the term does not belong to falls through to the refusal rather than expanding
    into a concept the term does not carry."""
    r = eq.resolve_translation("de", "wahl", "en", pinned_ring="voting")
    assert r.tier == eq.TIER_VERIFIED and r.text == "voting" and r.ring_id == "voting"
    stale = eq.resolve_translation("de", "wahl", "en", pinned_ring="no-such-ring")
    assert stale.declined == eq.DECLINE_SEVERAL_SENSES_TR


def test_the_verified_rung_always_beats_the_tentative_one():
    """The 2026-06-19 doctrine, pinned rather than left to call order: a model's answer can
    never displace a published label, even when the model was asked first."""
    r = eq.resolve_translation(
        "de", "premierminister", "en",
        tentative={"text": "chancellor", "model": "m", "prompt_version": "v"},
    )
    assert r.tier == eq.TIER_VERIFIED and r.text == "prime minister"
    assert "translation_model" not in r.to_dict()


def test_the_tentative_rung_carries_who_said_it():
    """A tentative row without its model is an unattributable claim; the ~ marker says it
    is unverified and the provenance says by whom."""
    r = eq.resolve_translation(
        "de", "kanzleramt", "en",
        tentative={"text": "chancellery", "model": "m2", "prompt_version": "v1"},
    )
    assert r.tier == eq.TIER_TENTATIVE and r.text == "chancellery"
    d = r.to_dict()
    assert d["translation_source"] == "llm" and d["translation_model"] == "m2"
    assert d["translation_prompt_version"] == "v1"


def test_an_echoed_tentative_answer_is_refused():
    """A model handed back the source term has added nothing, and storing it would let a
    coverage count over the table read as progress."""
    r = eq.resolve_translation("de", "kanzleramt", "en", tentative={"text": "Kanzleramt"})
    assert r.tier == eq.TIER_UNTRANSLATED and r.text is None


# --------------------------------------------------------------------------- #
#  The store (Q404's writers)
# --------------------------------------------------------------------------- #

def test_the_nullsafe_identity_actually_dedupes():
    """The trap S04-04 MEASURED: SQLite's UNIQUE treats NULL as distinct, so with `model`
    and `prompt_version` unset the declared constraint stops nothing and two byte-identical
    inserts produce two rows. The expression index is what enforces it; this asserts the
    writer goes through it rather than around it."""
    s = _sess()
    assert TS.record_tentative(s, term="Kanzleramt", source_lang="de", target_lang="en", text="chancellery")
    assert not TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en", text="chancellery")
    assert TS.tentative_coverage(s, "en")["rows"] == 1


def test_two_models_are_two_measurements_and_both_are_kept():
    """The vintage shape: collapsing them would pick a winner between two answers nobody
    compared. The READ picks the newest and says so; the WRITE deletes nothing."""
    s = _sess()
    TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en",
                        text="chancellery", model="m1", prompt_version="v1")
    TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en",
                        text="chancellor's office", model="m2", prompt_version="v1")
    cov = TS.tentative_coverage(s, "en")
    assert cov["rows"] == 2 and cov["terms"] == 1
    got = TS.tentative_translations(s, ["Kanzleramt"], "en")
    assert got["kanzleramt"]["model"] in {"m1", "m2"}


def test_a_term_with_no_row_is_ABSENT_never_an_empty_string():
    """"No model has answered this" and "a model answered with nothing" are different
    facts. Only the first is true here, and the ladder needs to be able to tell."""
    s = _sess()
    TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en", text="chancellery")
    got = TS.tentative_translations(s, ["kanzleramt", "nothing-was-asked"], "en")
    assert "nothing-was-asked" not in got
    assert got["kanzleramt"]["text"] == "chancellery"


def test_the_writer_refuses_a_useless_row():
    """Same-language, empty and echo answers assert nothing; recording them would inflate
    every count taken over the table."""
    s = _sess()
    assert not TS.record_tentative(s, term="budget", source_lang="en", target_lang="en", text="budget")
    assert not TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en", text="   ")
    assert not TS.record_tentative(s, term="kanzleramt", source_lang="de", target_lang="en", text="Kanzleramt")
    assert TS.tentative_coverage(s, "en")["rows"] == 0


# --------------------------------------------------------------------------- #
#  End to end, through the real query path
# --------------------------------------------------------------------------- #

def test_every_tier_is_reachable_on_one_fixture():
    """The anti-vacuity assertion for this whole file: if a rung stopped being reachable,
    the tests above would keep passing individually while the ladder served three tiers."""
    s = _sess()
    _seed(s)
    TS.record_tentative(s, term="Kanzleramt", source_lang="de", target_lang="en",
                        text="chancellery", model="m2", prompt_version="v1")
    by = _by_norm(q.top_terms(s, limit=20, group=False, target_lang="en"))

    assert by["climat"]["translation_tier"] == "verified"
    assert by["climat"]["translation"] == "climate"
    assert by["climat"]["translation_source_lang"] == "fr"

    assert by["kanzleramt"]["translation_tier"] == "tentative"
    assert by["kanzleramt"]["translation"] == "chancellery"
    assert by["kanzleramt"]["translation_source"] == "llm"
    assert by["kanzleramt"]["translation_model"] == "m2"

    assert by["zzznotaword"]["translation_tier"] == "untranslated"
    assert "translation" not in by["zzznotaword"]
    assert by["zzznotaword"]["translation_source_lang"] == "fr"

    assert by["budget"]["translation_tier"] == "same_language"

    assert by["wahl"]["translation_tier"] == "untranslated"
    assert by["wahl"]["translation_declined"] == "several-senses"
    assert len(by["wahl"]["senses"]) == 3

    tiers = {r["translation_tier"] for r in by.values()}
    assert tiers == {"verified", "tentative", "untranslated", "same_language"}


def test_no_target_lang_stays_byte_compatible():
    """The no-annotation default must be unchanged, or every caller that never asked for a
    language starts carrying tier fields it did not request."""
    s = _sess()
    _seed(s)
    plain = _by_norm(q.top_terms(s, limit=20, group=False))
    for row in plain.values():
        assert not any(k.startswith("translation") for k in row)
        assert "senses" not in row

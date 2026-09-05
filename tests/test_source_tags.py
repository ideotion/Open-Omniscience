"""
Tests for the LLM source-tag-assignment CORE (design entry + GO ruling,
maintainer 2026-07-20) -- mirrors ``tests/test_keyword_triage.py``'s shape.

The negative-space cases (out-of-vocabulary tag / hallucinated domain / an
empty-evidence source) are mandatory for a closed-set parser (the same #590
lesson triage.py's tests already cover); the EVIDENCE FLOOR and the explicit
'none' verdict are this module's own additions and get their own tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import source_tags as ST
from src.database.models import Article, Base, Keyword, KeywordMention, Source


# --------------------------------------------------------------------------- #
# The self-test (the exported mechanism proof).
# --------------------------------------------------------------------------- #
def test_selftest_passes():
    r = ST.run_source_tags_selftest()
    assert r["passed"] is True, r["checks"]
    assert r["schema"] == "oo-source-tags-selftest-1"


# --------------------------------------------------------------------------- #
# parse_source_tags -- the closed-vocabulary parser + echo-back (negative space).
# --------------------------------------------------------------------------- #
def test_parse_happy_path_multiple_tags():
    pb = ST.parse_source_tags(
        "a.com :: sports|finance", ["a.com"], ["sports", "finance", "technology"]
    )
    assert pb.tags["a.com"] == ("finance", "sports")  # sorted, deduped
    assert pb.parse_failures == 0


def test_explicit_none_is_a_valid_verdict_not_a_parse_failure():
    pb = ST.parse_source_tags("a.com :: none", ["a.com"], ["sports"])
    assert pb.tags["a.com"] == ()
    assert pb.none_count == 1
    assert pb.assigned_count == 0
    assert pb.parse_failures == 0
    assert "a.com" not in pb.missing  # 'none' is stored, distinct from missing


def test_out_of_vocabulary_tag_rejects_the_whole_line_never_partial():
    # 'startups' is not in the vocabulary -- the model also said 'technology'
    # (which IS valid), but the WHOLE line must be rejected, never half-stored.
    pb = ST.parse_source_tags("a.com :: technology|startups", ["a.com"], ["technology", "sports"])
    assert "a.com" not in pb.tags
    assert "technology" not in pb.tags.get("a.com", ())  # nothing partial stored
    assert pb.parse_failures == 1
    assert "a.com" in pb.missing


def test_hallucinated_domain_is_rejected():
    pb = ST.parse_source_tags("ghost.example :: sports", ["real.example"], ["sports"])
    assert "ghost.example" not in pb.tags
    assert pb.parse_failures == 1


def test_ambiguous_tag_fold_is_rejected_never_guessed():
    # two vocabulary entries fold to the SAME normalized key -- never silently
    # collapse a model's answer onto one of them (the same lesson triage.py's
    # Straße/Strasse case tests).
    pb = ST.parse_source_tags("a.com :: strasse", ["a.com"], ["Straße", "STRASSE"])
    assert "a.com" not in pb.tags
    assert pb.parse_failures == 1


def test_missing_source_is_counted_when_model_gives_no_line():
    pb = ST.parse_source_tags("a.com :: sports", ["a.com", "b.com"], ["sports"])
    assert pb.tagged_out == 1
    assert pb.missing == ["b.com"]


def test_duplicate_line_first_valid_wins():
    raw = "a.com :: sports\na.com :: finance"
    pb = ST.parse_source_tags(raw, ["a.com"], ["sports", "finance"])
    assert pb.tags["a.com"] == ("sports",)


# --------------------------------------------------------------------------- #
# Canaries -- vocabulary-conditional evaluation (never assert a tag the corpus
# doesn't have; a canary applies only when its expected tag exists live).
# --------------------------------------------------------------------------- #
def test_canary_fails_when_expected_tag_present_but_not_proposed():
    pb = ST.ParsedSourceBatch(tags={"canary.example": ()}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"sports"})}, vocabulary=["sports"]
    )
    assert out["ok"] is False
    assert out["checked"] == 1
    assert out["failed"][0]["domain"] == "canary.example"


def test_canary_is_skipped_not_failed_when_its_tag_is_out_of_this_installs_vocabulary():
    """Amended 2026-09-05: this used to assert ``ok is True`` on a run where NOTHING
    was checked -- a vacuous pass. The verdict is now a TRI-STATE, and 'no canary was
    applicable' is inconclusive, not a pass. The property the test guards (an
    inapplicable canary is SKIPPED, never counted as a model failure) is unchanged."""
    pb = ST.ParsedSourceBatch(tags={}, sources_in=0)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"sports"})}, vocabulary=["finance"]
    )
    assert out["ok"] is None  # nothing applicable -> no verdict, never a pass
    assert out["checked"] == 0
    assert out["failed_n"] == 0
    assert out["skipped"] and out["skipped"][0]["domain"] == "canary.example"


def test_canary_passes_with_extra_correct_tags_beyond_the_expected_subset():
    pb = ST.ParsedSourceBatch(tags={"canary.example": ("finance", "government")}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"finance"})}, vocabulary=["finance", "government"]
    )
    assert out["ok"] is True and out["checked"] == 1


# --------------------------------------------------------------------------- #
# The expected set is an ALTERNATIVES list, graded by RECALL (2026-09-05, from the
# 2026-09-03 field run: 161 recorded "failures" that were 82 unanswered canaries and
# 79 partial matches against an alternatives list read as a conjunction -- and ZERO
# wrong topics).
# --------------------------------------------------------------------------- #
def test_recovering_one_of_several_alternative_spellings_is_a_pass_not_a_failure():
    """The field's stats canary expects {business, economy, finance} -- one concept
    in several spellings. Answering ``economy + official-statistics`` is a correct
    answer for a statistics agency; the shipped subset rule scored it FAILED in all
    118 batches of the field run."""
    pb = ST.ParsedSourceBatch(
        tags={"canary-stats.example": ("economy", "official-statistics")}, sources_in=1
    )
    out = ST.check_source_canaries(
        pb,
        {"canary-stats.example": frozenset({"business", "economy", "finance"})},
        vocabulary=["business", "economy", "finance", "official-statistics"],
    )
    assert out["ok"] is True
    assert out["passed"] == 1 and out["failed_n"] == 0
    # Reported, with its number, so a reader can still tighten the bar later.
    assert out["partial_n"] == 1
    entry = out["partial"][0]
    assert entry["recovered"] == ["economy"]
    assert entry["recall"] == round(1 / 3, 4)


def test_a_genuinely_wrong_topic_is_still_fatal():
    """NEGATIVE SPACE: the whole point of a canary. Grading by recall must not turn
    into 'anything the model says is fine' -- recall 0 on an applicable set is a
    hard failure, and this is the assertion that stops the fix being a laundering."""
    pb = ST.ParsedSourceBatch(tags={"canary-sports.example": ("finance",)}, sources_in=1)
    out = ST.check_source_canaries(
        pb,
        {"canary-sports.example": frozenset({"sport", "sports"})},
        vocabulary=["finance", "sport", "sports"],
    )
    assert out["ok"] is False
    assert out["failed_n"] == 1 and out["passed"] == 0
    assert out["failed"][0]["recovered"] == [] and out["failed"][0]["recall"] == 0.0


def test_an_explicit_none_answer_is_a_failure_not_a_partial():
    """``()`` is the explicit 'no allowed tag fits' verdict -- an ANSWER, and a wrong
    one for an obvious source. It was 5 of the field run's 161 recorded failures and
    is the one genuinely interesting signal in them."""
    pb = ST.ParsedSourceBatch(tags={"canary-sports.example": ()}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary-sports.example": frozenset({"sport"})}, vocabulary=["sport"]
    )
    assert out["ok"] is False and out["failed_n"] == 1
    assert out["no_answer_n"] == 0  # answering 'none' is not the same as not answering


def test_no_line_at_all_is_reported_apart_and_is_not_a_judgement_failure():
    """A canary the model never answered expressed no topical opinion. ``pb.missing``
    already counts exactly this for every source; folding it into the canary verdict
    is what made 39 dead batches (median missing-share 1.00) read as model failures."""
    pb = ST.ParsedSourceBatch(tags={}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary-sports.example": frozenset({"sport"})}, vocabulary=["sport"]
    )
    assert out["checked"] == 1
    assert out["no_answer_n"] == 1 and out["failed_n"] == 0
    assert out["answered"] == 0
    assert out["ok"] is None  # nothing answered -> inconclusive, never a pass


def test_a_model_that_answers_nothing_can_never_read_as_a_pass():
    """NEGATIVE SPACE for the tri-state: the vacuous-pass trap. If 'no answer' is not
    a failure, then a silent model must not become ``ok: True`` either."""
    pb = ST.ParsedSourceBatch(tags={}, sources_in=2)
    out = ST.check_source_canaries(
        pb,
        {"a.example": frozenset({"sport"}), "b.example": frozenset({"finance"})},
        vocabulary=["sport", "finance"],
    )
    assert out["ok"] is None
    assert out["checked"] == 2 and out["answered"] == 0


def test_one_answered_canary_is_enough_for_a_verdict():
    """...but the moment ANY canary is answered there is evidence to judge, and the
    unanswered ones must not hold the verdict hostage."""
    pb = ST.ParsedSourceBatch(tags={"a.example": ("sport",)}, sources_in=2)
    out = ST.check_source_canaries(
        pb,
        {"a.example": frozenset({"sport"}), "b.example": frozenset({"finance"})},
        vocabulary=["sport", "finance"],
    )
    assert out["ok"] is True
    assert out["answered"] == 1 and out["no_answer_n"] == 1


# --------------------------------------------------------------------------- #
# The run-level tally -- ONE accumulator, shared by both jobs, verdict DERIVED.
# --------------------------------------------------------------------------- #
def test_the_run_verdict_is_derived_from_counts_never_from_a_batch_boolean():
    """A batch that answered nothing reports ``ok: None``; ANDing ``bool(None)`` into
    a run boolean would publish a failure the run has no evidence for."""
    tally = ST.new_canary_tally()
    silent = ST.check_source_canaries(
        ST.ParsedSourceBatch(sources_in=1), {"a.example": frozenset({"sport"})}, ["sport"]
    )
    good = ST.check_source_canaries(
        ST.ParsedSourceBatch(tags={"a.example": ("sport",)}, sources_in=1),
        {"a.example": frozenset({"sport"})},
        ["sport"],
    )
    ST.accumulate_canary(tally, silent)
    assert ST.canary_verdict(tally) is None  # still no evidence
    ST.accumulate_canary(tally, good)
    assert ST.canary_verdict(tally) is True
    assert tally == {
        "checked": 2,
        "answered": 1,
        "passed": 1,
        "failed_n": 0,
        "partial_n": 0,
        "no_answer_n": 1,
    }


def test_one_wrong_topic_among_many_passes_still_fails_the_run_with_its_denominator():
    tally = ST.new_canary_tally()
    for got in [("sport",)] * 9 + [("finance",)]:
        ST.accumulate_canary(
            tally,
            ST.check_source_canaries(
                ST.ParsedSourceBatch(tags={"a.example": got}, sources_in=1),
                {"a.example": frozenset({"sport"})},
                ["sport", "finance"],
            ),
        )
    assert ST.canary_verdict(tally) is False
    # The denominator is what makes 1-in-10 readable next to 10-in-10.
    assert tally["failed_n"] == 1 and tally["answered"] == 10 and tally["passed"] == 9


# --------------------------------------------------------------------------- #
# Vocabulary hygiene -- fold what is PROVABLE, report the rest.
# --------------------------------------------------------------------------- #
def test_separator_variants_are_folded_for_the_prompt():
    folded, dropped = ST.fold_separator_variants(["case-law", "case_law", "finance"])
    assert folded == ["case-law", "finance"]
    assert dropped == {"case_law": "case-law"}


def test_folding_never_narrows_what_the_parser_accepts():
    """NEGATIVE SPACE: only the PROMPT is folded. A model answering the dropped
    spelling must still resolve exactly as before -- a fold that made a previously
    valid answer a parse failure would trade one defect for a worse one."""
    vocabulary = ["case-law", "case_law", "finance"]
    for spelling in ("case-law", "case_law"):
        pb = ST.parse_source_tags(f"x.example :: {spelling}", ["x.example"], vocabulary)
        assert pb.tags["x.example"] == (spelling,)
        assert pb.parse_failures == 0


def test_a_vocabulary_with_no_separator_variants_is_returned_unchanged():
    vocabulary = ["africa", "east-africa", "finance", "official-statistics"]
    folded, dropped = ST.fold_separator_variants(vocabulary)
    assert folded == vocabulary and dropped == {}


def test_legitimately_distinct_tags_are_never_folded():
    """NEGATIVE SPACE, and the reason only the provable class is folded: of the 17
    collision candidates in the field's 204-tag vocabulary, 14 were real hierarchies
    (``africa``/``east-africa``, ``official``/``official-statistics``,
    ``lean-center``/``lean-center-left``). A near-synonym sweep would have destroyed
    them."""
    vocabulary = [
        "africa",
        "east-africa",
        "official",
        "official-statistics",
        "lean-center",
        "lean-center-left",
    ]
    folded, dropped = ST.fold_separator_variants(vocabulary)
    assert folded == vocabulary and dropped == {}
    report = ST.vocabulary_collisions(vocabulary)
    assert report["separator_variants"] == [] and report["near_synonyms"] == []


def test_the_collision_report_names_judgements_without_making_them():
    report = ST.vocabulary_collisions(
        ["case-law", "case_law", "commodities", "commodity", "finance", "via:curated", "lean-left"]
    )
    assert report["separator_variants"] == [["case-law", "case_law"]]
    assert report["near_synonyms"] == [["commodities", "commodity"]]
    assert report["non_topical"]["provenance"] == ["via:curated"]
    assert report["non_topical"]["stance-or-ownership"] == ["lean-left"]


def test_a_non_topical_entry_is_reported_but_never_filtered_out():
    """propose-never-auto-apply: deciding ``independent`` is not a topic is a taxonomy
    ruling a human makes. The prompt still offers it; the report names it."""
    vocabulary = ["finance", "independent", "via:curated"]
    folded, _ = ST.fold_separator_variants(vocabulary)
    assert folded == vocabulary
    system, _user, _expected = ST.build_source_tag_prompt([], vocabulary)
    assert "independent" in system and "via:curated" in system


def test_the_prompt_states_the_folded_vocabulary_and_the_parser_gets_the_full_one():
    system, _user, _expected = ST.build_source_tag_prompt([], ["case-law", "case_law", "finance"])
    assert "case-law" in system
    assert "case_law" not in system


def test_the_run_header_carries_the_collision_report():
    header = ST.source_tag_run_header(model="stub:test", vocabulary=["case-law", "case_law"])
    assert header["vocabulary"] == ["case-law", "case_law"]  # the FULL vocabulary is recorded
    assert header["vocabulary_collisions"]["separator_variants"] == [["case-law", "case_law"]]


def test_the_batch_record_carries_the_canary_denominator():
    canary = ST.check_source_canaries(
        ST.ParsedSourceBatch(tags={"a.example": ("economy",)}, sources_in=1),
        {"a.example": frozenset({"economy", "finance"})},
        ["economy", "finance"],
    )
    rec = ST.source_tag_batch_record(
        started_at="2026-09-05T00:00:00",
        finished_at="2026-09-05T00:00:01",
        gen_meta={},
        pb=ST.ParsedSourceBatch(sources_in=1),
        canary=canary,
        model="stub:test",
    )
    assert rec["canary_ok"] is True
    assert rec["canary_checked"] == 1 and rec["canary_answered"] == 1
    assert rec["canary_partial_n"] == 1 and rec["canary_failed_n"] == 0


def test_the_batch_record_never_coerces_an_inconclusive_verdict_to_a_failure():
    """NEGATIVE SPACE for the tri-state at the serialisation boundary: ``bool(None)``
    is False, so a record built with ``bool(...)`` would publish a fabricated failure
    for every batch whose canaries went unanswered."""
    canary = ST.check_source_canaries(
        ST.ParsedSourceBatch(sources_in=1), {"a.example": frozenset({"economy"})}, ["economy"]
    )
    rec = ST.source_tag_batch_record(
        started_at="2026-09-05T00:00:00",
        finished_at="2026-09-05T00:00:01",
        gen_meta={},
        pb=ST.ParsedSourceBatch(sources_in=1),
        canary=canary,
        model="stub:test",
    )
    assert rec["canary_ok"] is None
    assert rec["canary_no_answer_n"] == 1 and rec["canary_failed_n"] == 0


# --------------------------------------------------------------------------- #
# resolve_tag_vocabulary + select_source_tag_candidates -- the EVIDENCE FLOOR,
# on an in-memory corpus (mirrors test_source_enrichment.py's fixture style).
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_source_with_articles(db, *, domain, tags, n_articles, term="football", stopword=False):
    src = Source(name=domain, domain=domain, tags=tags)
    db.add(src)
    db.flush()
    kw = Keyword(term=("the" if stopword else term), normalized_term=term, language="en")
    db.add(kw)
    db.flush()
    for i in range(n_articles):
        a = Article(
            url=f"https://{domain}/{i}",
            canonical_url=f"https://{domain}/{i}",
            source_id=src.id,
            title="T",
            content=term,
            hash=f"{domain}-h{i}",
        )
        db.add(a)
        db.flush()
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=2, source_id=src.id))
    db.commit()
    return src


def test_resolve_vocabulary_is_the_live_distinct_tag_set(db):
    _seed_source_with_articles(db, domain="a.test", tags="sports, us", n_articles=1)
    _seed_source_with_articles(db, domain="b.test", tags="technology", n_articles=1)
    vocab = ST.resolve_tag_vocabulary(db)
    assert vocab == ["sports", "technology", "us"]


def test_evidence_floor_skips_a_source_below_min_articles_never_a_guess(db):
    _seed_source_with_articles(db, domain="thin.test", tags=None, n_articles=1)
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=3)
    assert items == []
    assert skipped[0].domain == "thin.test"
    assert skipped[0].reason == "insufficient evidence"


def test_a_source_with_zero_keyword_mentions_is_an_honest_skip_not_a_silent_drop(db):
    # a source with NO keyword_mentions rows at all must still be REPORTED as a
    # skip -- never silently absent from both items and skipped.
    src = Source(name="empty.test", domain="empty.test", tags="news")
    db.add(src)
    db.commit()
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=1)
    domains_seen = {i.domain for i in items} | {s.domain for s in skipped}
    assert "empty.test" in domains_seen
    assert any(s.domain == "empty.test" and s.reason == "insufficient evidence" for s in skipped)


def test_source_with_only_stoplisted_terms_is_skipped_not_sent_as_content(db):
    _seed_source_with_articles(db, domain="junk.test", tags=None, n_articles=5, stopword=True)
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=1)
    assert items == []
    assert any(
        s.domain == "junk.test" and s.reason == "no content terms after stoplist" for s in skipped
    )


def test_a_source_with_real_evidence_is_a_candidate_with_its_top_terms(db):
    _seed_source_with_articles(
        db, domain="ok.test", tags=None, n_articles=5, term="quarterly earnings"
    )
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=3)
    assert len(items) == 1
    assert items[0].domain == "ok.test"
    assert "quarterly earnings" in items[0].top_terms
    assert skipped == []

"""Keyword-engine efficacy + performance report (src/analytics/engine_report.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bounded, read-only diagnostic over the corpus. Pins the metric shapes (no
composite score), the honest entity-precision + per-language-status logic, and that
translation/tag coverage + the self-test + timings are reported.
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.engine_report import (
    _is_acronym,
    _lang_status,
    keyword_engine_report,
    lemma_preview_report,
)
from src.database.models import Article, Base, Keyword, KeywordMention, KeywordTag, Source


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw(s, term, norm, *, entity=False, lang="en"):
    k = Keyword(
        term=term, normalized_term=norm, language=lang, frequency=0,
        is_entity=entity, entity_type=("entity" if entity else None),
        is_ngram=(" " in norm), ngram_size=len(norm.split()),
    )
    s.add(k)
    s.flush()
    return k


def _seed(s):
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/1", canonical_url="https://s.test/1", source_id=1,
        title="t", content="The election was held. WHO met. World news today.", hash="h1",
    )
    s.add(a)
    s.flush()
    who = _kw(s, "WHO", "WHO", entity=True)  # valid acronym entity
    world = _kw(s, "World", "world", entity=True)  # legacy non-acronym entity
    elec = _kw(s, "election", "election")  # term, in the real 'election' ring
    junk = _kw(s, "widget", "widget")  # term, no ring/tag
    for k in (who, world, elec, junk):
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, observed_on=date.today()))
    s.add(KeywordTag(keyword_id=elec.id, axis="topic", tag="politics", source="baseline"))
    s.commit()


def test_report_structure_and_metrics():
    s = _sess()
    _seed(s)
    r = keyword_engine_report(s, top_n=50, sample_articles=5)
    assert r["kind"] == "keyword-engine-report" and r["schema"] == "oo-keyword-engine-1"
    assert r["composition"]["keywords"] == 4 and r["composition"]["entities"] == 2
    # entity precision: WHO is an acronym, World is not -> 1 of 2
    assert r["entity_precision"]["valid_acronyms"] == 1 and r["entity_precision"]["pct_acronym"] == 50.0
    # translation coverage: "election" is in the real ring config
    assert r["translation_coverage"]["in_a_ring"] >= 1 and r["translation_coverage"]["rings_total"] >= 1
    # tag coverage: election carries a baseline tag
    assert r["tag_coverage"]["tagged"] >= 1
    langs = {x["language"]: x["status"] for x in r["language_coverage"]["languages"]}
    assert langs.get("en") == "functional"
    assert r["selftest"]["failed"] == 0
    assert r["performance"]["extraction"]["articles_sampled"] == 1
    assert "score" not in r  # no composite score, anywhere at the top level


def test_extraction_noise_flags_actionable_classes():
    """The report self-surfaces junk keywords by actionable class (2026-06-18 field
    asks). An elision-contaminated term, a markup token and a bare-year are each
    flagged; a clean content keyword is not."""
    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    _kw(s, "l'assemblée", "l'assemblée")   # elision backlog (pre de-elision)
    _kw(s, "colspan", "colspan")           # leaked HTML token
    _kw(s, "2024", "2024")                 # bare digits
    _kw(s, "government", "government")      # clean content keyword
    s.commit()
    r = keyword_engine_report(s, top_n=50, sample_articles=1)
    noise = r["extraction_noise"]
    cls = noise["classes"]
    assert "l'assemblée" in cls["elision_contaminated"]["examples"]
    assert "colspan" in cls["markup_token"]["examples"]
    assert "2024" in cls["mostly_digits"]["examples"]
    # a clean content keyword appears in NONE of the example lists
    assert all("government" not in c["examples"] for c in cls.values())
    assert noise["scanned"] == 4 and noise["total_flagged"] == 3


def test_extraction_noise_flags_code_tokens():
    """The PROJECTED §2.5/§2.6 reduction: digit-segmented codes + underscore identifiers
    the extraction code-token filter drops are surfaced as a ``code_token`` class, so the
    maintainer can measure the backlog the next re-index removes from the same report."""
    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    _kw(s, "a-10c", "a-10c")                      # multi-segment code
    _kw(s, "gd_combo_table", "gd_combo_table")    # underscore template identifier
    _kw(s, "elections", "elections")              # clean content keyword (kept)
    s.commit()
    cls = keyword_engine_report(s, top_n=50, sample_articles=1)["extraction_noise"]["classes"]
    assert "code_token" in cls
    ex = cls["code_token"]["examples"]
    assert "a-10c" in ex and "gd_combo_table" in ex and "elections" not in ex


def test_lemma_preview_surfaces_candidate_conflations():
    """P4.3 measurability: the report previews what OPT-IN lemmatization WOULD merge among
    the top terms (study/studied -> study), so the maintainer reviews precision before
    enabling OO_FAMILY_LEMMA. Denylisted meaning-changers (media/medium) must NOT appear,
    and there is no score. Degrades honestly (available:false) without simplemma."""
    from src.analytics.families import _simplemma

    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/2", canonical_url="https://s.test/2", source_id=1,
        title="t", content="A study. They studied. Media and medium.", hash="h2",
    )
    s.add(a)
    s.flush()
    kws = [_kw(s, "study", "study"), _kw(s, "studied", "studied"), _kw(s, "widget", "widget"),
           _kw(s, "media", "media"), _kw(s, "medium", "medium")]
    for k in kws:
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, observed_on=date.today()))
    s.commit()

    lp = keyword_engine_report(s, top_n=50, sample_articles=1)["lemma_preview"]
    assert "score" not in lp  # counts only, never a score
    if _simplemma is None:
        assert lp["available"] is False
        return
    assert lp["available"] is True and "enabled" in lp
    member_sets = {tuple(g["members"]) for g in lp["examples"]}  # members are sorted
    assert ("studied", "study") in member_sets  # the verb form a plural rule would miss
    # S2: the group is tagged as the TRUE delta over the plural rule (a verb form, not a
    # plural the earlier step already collapses), and the summary tally reflects it.
    study_group = next(g for g in lp["examples"] if tuple(g["members"]) == ("studied", "study"))
    assert study_group["plural_overlap"] == "lemma_only"
    assert lp["by_plural_overlap"]["lemma_only"] >= 1


def test_plural_rule_classification_distinguishes_true_delta():
    """S2 (2026-07-18 default-on brief): a group the PLURAL rule already fully collapses
    (election/elections -- a regular -s plural, families step 1.5) must be tagged
    'plural_rule', not lumped in with a genuine lemma-only addition (study/studied) --
    else a precision review can't tell what lemmatization is ACTUALLY adding beyond the
    step that already runs before it."""
    from src.analytics.engine_report import _plural_rule_classification

    assert _plural_rule_classification(["election", "elections"]) == "plural_rule"
    assert _plural_rule_classification(["study", "studied"]) == "lemma_only"
    # a lemma group spanning two otherwise-unconnected plural pairs: the lemma step is
    # doing real work bridging them, beyond what either plural pair gets alone.
    assert _plural_rule_classification(["city", "cities", "town"]) == "mixed"


def test_focused_lemma_preview_report_matches_the_full_report(monkeypatch):
    """S5.4: the FOCUSED lemma_preview_report (surfaced standalone in the Diagnostics panel)
    returns the same candidate conflations as the full report's lemma_preview block, WITHOUT
    running the heavy report. Counts only, no score; honest available:false without simplemma."""
    from src.analytics.families import _simplemma

    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/3", canonical_url="https://s.test/3", source_id=1,
        title="t", content="A study. They studied.", hash="h3",
    )
    s.add(a)
    s.flush()
    for k in (_kw(s, "study", "study"), _kw(s, "studied", "studied")):
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, observed_on=date.today()))
    s.commit()

    lp = lemma_preview_report(s, top_n=50)
    assert "score" not in lp
    if _simplemma is None:
        assert lp["available"] is False
        return
    assert lp["available"] is True
    assert ("studied", "study") in {tuple(g["members"]) for g in lp["examples"]}
    # the denylist holds: media/medium never appear as a would-merge candidate
    assert all("media" not in g["members"] and "medium" not in g["members"] for g in lp["examples"])


def test_language_status_is_honest():
    from src.analytics.segmentation import segmenter_available

    # zh/ja flip to 'functional' when the optional [segmentation] extra is installed,
    # 'unsegmented' otherwise — honest in both environments.
    want_zh = "functional" if segmenter_available("zh") else "unsegmented"
    want_ja = "functional" if segmenter_available("ja") else "unsegmented"
    assert _lang_status("zh") == want_zh and _lang_status("ja") == want_ja
    assert _lang_status("en") == "functional" and _lang_status("ru") == "functional"
    assert _lang_status("vi") == "no_stoplist" and _lang_status("xx") == "no_stoplist"


def test_acronym_predicate():
    assert _is_acronym("WHO") and _is_acronym("G7") and _is_acronym("COVID-19")
    assert not _is_acronym("world") and not _is_acronym("a")

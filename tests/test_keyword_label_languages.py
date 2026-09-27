"""What a keyword label may say about LANGUAGE, measured from the row's own mentions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

M11 (click-through 2026-09-26). Keys are language-agnostic -- Q416 keys a term by its lemma
alone -- so one keyword can hold English ``software`` and Spanish ``software`` together, and
the label's one source language (``Keyword.language``, the MAJORITY, Q414) then tagged the
English word "in Spanish" in the English UI. The key is NOT changed here (a stored-key change
needs a ruling); instead the rows a surface displays carry the languages their own mentions
were recorded in, so the label can name the split.

M12 (same walk). A solo row the ladder resolved to a verified ring said nothing of the ring
behind its translation; it now carries the ring's members present in the corpus with their
per-language counts, in the ``language_breakdown`` shape the hover already renders -- over
the row's OWN scope (its window where the row is windowed, the whole corpus elsewhere), and
the row says which.

Driven through the public query functions rather than the helper, so an endpoint that stops
calling it fails here too.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _sess():
    e = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


_TODAY = date.today()
_OLD = _TODAY - timedelta(days=60)

# (normalized, Keyword.language, [(mention language, count, observed_on), ...])
#   software  one key, two languages: the majority is Spanish, the English mentions are real.
#   climat    fr, a clean member of the `climate` ring -> verified into en.
#   klima     de, another member of that ring; mostly OLD, so a 7-day window leaves it out,
#             plus mentions written before their language was recorded (Q414, no backfill).
#   budget    en, already the reader's language: nothing to say.
_SEED = [
    ("software", "es", [("es", 40, _TODAY), ("en", 30, _TODAY)]),
    ("climat", "fr", [("fr", 60, _TODAY)]),
    ("klima", "de", [("de", 10, _OLD), (None, 5, _OLD)]),
    ("budget", "en", [("en", 20, _TODAY)]),
]


def _seeded():
    s = _sess()
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    arts = {}
    for i, lg in enumerate(("en", "es", "fr", "de", "xx")):
        a = Article(url=f"u{i}", canonical_url=f"u{i}", source_id=1, title="t", content="c",
                    hash=f"h{i}", language=None if lg == "xx" else lg)
        s.add(a)
        s.flush()
        arts[lg] = a.id
    for norm, klang, mentions in _SEED:
        total = sum(n for _lg, n, _d in mentions)
        k = Keyword(term=norm, normalized_term=norm, language=klang, frequency=0,
                    mention_count=total, article_count=len(mentions))
        s.add(k)
        s.flush()
        for lg, n, on in mentions:
            s.add(KeywordMention(keyword_id=k.id, article_id=arts[lg or "xx"], count=n,
                                 observed_on=on, language=lg))
    s.commit()
    return s


def _rows(res):
    return {t["normalized"]: t for t in res["terms"]}


def test_a_keyword_split_across_languages_names_the_split_not_the_majority():
    rows = _rows(q.top_terms(_seeded(), group=False, target_lang="en", limit=20))
    sw = rows["software"]
    # The ladder still names the majority as the ONE source language...
    assert sw["translation_source_lang"] == "es"
    # ...and the row now carries what its own mentions measure, largest first.
    assert sw["mention_languages"] == {"es": 40, "en": 30}
    assert list(sw["mention_languages"]) == ["es", "en"]
    assert sw["language_counts_scope"] == "corpus"
    # A row already in the reader's language, or with one language that IS its tag, says
    # nothing more: the field appears only where the label would otherwise be wrong.
    assert "mention_languages" not in rows["budget"]
    assert "mention_languages" not in rows["climat"]


def test_a_solo_row_on_a_verified_ring_carries_the_ring_members_in_its_own_scope():
    s = _seeded()
    whole = _rows(q.top_terms(s, group=False, target_lang="en", limit=20))["climat"]
    assert whole["translation_tier"] == "verified" and whole["translation"] == "climate"
    # The ring's members PRESENT in the corpus, each under its own language; the mentions
    # written before languages were recorded are named as such, never guessed.
    assert whole["language_breakdown"] == {"fr": 60, "de": 10, "?": 5}
    assert whole["translation_ring_members"] == [
        {"term": "climat", "language": "fr", "mentions": 60},
        {"term": "klima", "language": "de", "mentions": 10},
    ]
    assert whole["language_counts_scope"] == "corpus"
    assert "language_counts_days" not in whole

    # The SAME row on a 7-day surface counts over those 7 days: the old German mentions
    # are outside it, and the row says which scope its numbers are.
    week = _rows(q.top_terms(s, group=False, target_lang="en", limit=20, days=7))["climat"]
    assert week["language_breakdown"] == {"fr": 60}
    assert week["language_counts_scope"] == "window" and week["language_counts_days"] == 7


def test_the_rising_list_counts_over_its_own_recent_window():
    s = _seeded()
    res = q.trending(s, window_days=7, baseline_days=30, min_recent=1, target_lang="en")
    rows = _rows(res)
    assert rows["climat"]["language_breakdown"] == {"fr": 60}
    assert rows["climat"]["language_counts_scope"] == "window"
    assert rows["climat"]["language_counts_days"] == 7
    assert rows["software"]["mention_languages"] == {"es": 40, "en": 30}


def test_a_country_filter_never_claims_the_whole_corpus():
    s = _seeded()
    out = q.annotate_label_languages(
        s,
        [{"normalized": "software", "translation_tier": "untranslated",
          "translation_source_lang": "es"}],
        "en",
        country="fr",
    )
    # No mention carries that country, so nothing is claimed at all...
    assert "mention_languages" not in out[0]
    out = q.annotate_label_languages(
        s,
        [{"normalized": "software", "translation_tier": "untranslated",
          "translation_source_lang": "es"}],
        "en",
    )
    assert out[0]["language_counts_scope"] == "corpus"


def test_the_query_reads_only_the_rows_on_screen():
    """Bounded by the rows displayed: one grouped query for the page, never per row, and
    none at all when no row's label names a language."""
    s = _seeded()
    calls = []
    real = s.query

    def spy(*a, **k):
        calls.append(a)
        return real(*a, **k)

    s.query = spy  # type: ignore[method-assign]
    q.annotate_label_languages(s, [{"normalized": "budget", "translation_tier": "same_language",
                                    "translation_source_lang": "en"}], "en")
    assert calls == []
    rows = [{"normalized": n, "translation_tier": "untranslated", "translation_source_lang": "es"}
            for n in ("software", "klima", "budget")]
    q.annotate_label_languages(s, rows, "en")
    assert len(calls) == 1

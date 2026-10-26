"""
Story clusters — grouping a period's articles into the things they are about.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §9 (the story-cluster unit). Narration works one story at a time,
so this is what decides what a narrated paragraph is about.

HOW, and the honesty of the method is the whole of it: articles are grouped by
the overlap of their KEYWORD sets — the rule-based, trusted index — not by a
semantic model. Two articles land together when they share enough indexed terms.
That is a LEXICAL grouping and the payload says so: it will split one story told
in two languages, and it will join two unrelated stories that share a vocabulary.
Neither is a bug to be hidden; both are properties of grouping by words.

The alternative — an embedding model deciding what is "the same story" — would
put an unverifiable judgement underneath every narrated paragraph, which is
exactly what the deterministic-first design exists to avoid.

Cost: keyword sets come from ``keyword_mentions``, which is indexed and carries
``source_id`` denormalised, so building them costs no article decrypt at all.
Only the narration step reads article text, and only for the articles it narrates.
"""

from __future__ import annotations

import heapq
import logging
import os
from array import array
from collections.abc import Iterator
from datetime import datetime, time
from typing import Any

from sqlalchemy import and_, func

from src.bulletin.period import Period
from src.database.derived_views import KeywordMentionRead
from src.database.models import Article, Keyword, Source
from src.database.stand_in import not_a_stand_in_article_id
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

_CLOCK = func.coalesce(Article.published_at, Article.created_at)

#: Terms per article used to compare. The most-mentioned terms in that article —
#: enough to characterise it, few enough that two articles sharing a handful of
#: incidental words do not join.
_TERMS_PER_ARTICLE = 12

#: Jaccard overlap at or above which two articles are the same story. Deliberately
#: high: over-merging is the worse failure, because a merged cluster invites a
#: narrated sentence spanning two unrelated things, and no downstream check would
#: catch that.
_JOIN_AT = 0.34

#: A story with fewer articles than this is not narrated as a story — one article
#: is not a story, it is an article, and calling it one would inflate the shape of
#: the period. Single articles are still counted everywhere else.
_MIN_ARTICLES = 2

#: Articles whose mention rows are read in one statement. It protects two things: SQLite's bound-variable limit (999, so 900 is the
#: figure every chunked IN list in this package keeps under), and the memory of one read, which is this many articles times the
#: mentions each carries (78 on the field corpus, so about 70,000 rows) and no more, whatever the length of the period.
#: MEASURED (audit-0.5.0/inputs/remeasure-stories-export, written corpora of 1.56 to 12.48 million mentions at 78 per article): the Python
#: heap of the whole read is 30.2, 33.6 and 45.7 MB at 100, 300 and 900 articles a read (tracemalloc peak, 1.56 M mentions), so one read
#: costs about 19 KB an article (248 B a mention row), 17 MB at 900; and 900 is also the fastest of the three (cold 38.0 s against 40.5 s
#: at 300 and 43.7 s at 100 on 12.48 M mentions, warm 32.7 against 34.3 and 39.4 s). A larger chunk is not available: the variable limit.
_ARTICLE_CHUNK = 900

#: Keyword ids whose stoplist verdict is remembered between chunks. It protects memory: at about 100 bytes an entry the table stays near
#: 10 MB however many distinct keywords the period holds, and when it fills it is emptied and refilled by the next chunks (a verdict
#: is a pure function of the keyword's normalised term, so forgetting one costs a lookup, never a different answer).
_VERDICTS_KEPT = 100_000


#: The longest the mention read of one edition may run by default. It protects the request thread and the one connection the app
#: shares, which a yearly edition holds for the whole read, from a read that is not coming back; it is NOT a bound on a slow machine's
#: patience. MEASURED (same folder): the read takes 3.0 microseconds a mention row cold and 2.6 warm on a 2.1 GHz virtual core, linear from
#: 1.56 to 12.48 million mentions (38.0 s cold, 32.7 s warm at 12.48 M), which puts the field corpus (20.9 M mentions, 268,241 articles) at
#: about 64 s cold and 55 s warm, an extrapolation and labelled as one. 600 s is about nine times that: a machine nine times slower than
#: that core still finishes, and one that cannot reads as "stories unavailable". The cards of the same edition have 240 s for the whole
#: card layer (``cards.DEFAULT_BUDGET_S``); this read has more because a yearly edition is generated once, and not polled.
_DEADLINE_DEFAULT_S = 600.0


def _stories_deadline_s() -> float:
    """``OO_BULLETIN_STORIES_DEADLINE_S`` (default :data:`_DEADLINE_DEFAULT_S`): the longest the mention read of one edition may run, in seconds.

    The deadline's progress handler also stops a read that takes the machine to the memory guard's floor. The edition that cannot
    finish reads as "stories unavailable", with the error class, instead of as a button that never comes back. Clamped finite and
    positive, and to an hour, as the diagnostics deadlines are."""
    import math

    try:
        v = float(os.environ.get("OO_BULLETIN_STORIES_DEADLINE_S", _DEADLINE_DEFAULT_S))
    except ValueError:
        return _DEADLINE_DEFAULT_S
    if not math.isfinite(v) or v <= 0:
        return _DEADLINE_DEFAULT_S
    return min(v, 3600.0)


def _period_article_ids(session, period: Period) -> array:
    """The ids of the articles the period holds, sorted, from the ``articles`` clock index alone.

    ``ix_article_observed`` is ``coalesce(published_at, created_at)`` (``_CLOCK`` is written exactly as it defines it), and a
    keyword mention's ``observed_on`` is that same clock's date (``store.py`` stamps ``(published_at or created_at).date()``), so
    ``clock in [start, end)`` names the articles whose mentions the period holds. An index range over the clock reads no article row
    page; a stand-in (the placeholder a salvage copy writes for a lost article) is left out through the hash index, as the mention
    read did through its article ids. A quarantined article is NOT left out here, as it was not before: that is D22's slice.
    The ids come back as an ``array('q')``, eight bytes each, so a period of millions of articles costs megabytes. Sorted, so each
    chunk of the mention read lands on neighbouring pages of the covering index."""
    lo = datetime.combine(period.start, time.min)
    hi = datetime.combine(period.end, time.min)
    clock = _CLOCK
    ids = array(
        "q",
        (
            int(aid)
            for (aid,) in session.query(Article.id)
            .filter(and_(clock >= lo, clock < hi), not_a_stand_in_article_id(Article.id))
            .yield_per(10_000)
        ),
    )
    return array("q", sorted(ids))


def _visible_sets(session, period: Period) -> Iterator[tuple[int, set[int]]]:
    """Each in-period article that has mention rows, with its characterising keyword ids; one chunk of articles in memory at a time.

    The period's articles are taken first (:func:`_period_article_ids`); their mention rows are then read ``_ARTICLE_CHUNK``
    articles at a time through the covering index ``ix_mention_article_count`` (``article_id, count, keyword_id``), the stoplist
    verdict is asked of the keywords of that chunk only, and each article is reduced to its top ``_TERMS_PER_ARTICLE`` before the
    next chunk is read. What is resident is one chunk of rows plus the verdict table, never the period's mentions: this replaced a
    single ``.all()`` over every mention of the period, which a yearly edition on a field corpus made several gigabytes (audit
    0.5.0, A-003).

    An article whose every keyword is hidden is yielded with an EMPTY set, so the period's article count stays exact; an article
    with no mention row at all is not yielded, as before."""
    from src.analytics.queries import _hidden_predicate

    is_hidden = _hidden_predicate()
    verdicts: dict[int, bool] = {}
    ids = _period_article_ids(session, period)
    for start in range(0, len(ids), _ARTICLE_CHUNK):
        chunk = ids[start : start + _ARTICLE_CHUNK].tolist()
        per: dict[int, list[tuple[int, int]]] = {}
        for aid, kid, cnt in session.query(
            KeywordMentionRead.article_id, KeywordMentionRead.keyword_id, KeywordMentionRead.count
        ).filter(KeywordMentionRead.article_id.in_(chunk)):
            per.setdefault(int(aid), []).append((int(cnt or 0), int(kid)))
        # One lookup per keyword this chunk has not yet been judged on, small columns only, under the variable cap. A keyword the
        # table does not hold is judged visible, as it was when only the ones found were tested.
        unjudged = sorted({kid for pairs in per.values() for _c, kid in pairs} - verdicts.keys())
        for i in range(0, len(unjudged), 900):
            part = unjudged[i : i + 900]
            for kid in part:
                verdicts[kid] = False
            for kid, norm in session.query(Keyword.id, Keyword.normalized_term).filter(Keyword.id.in_(part)):
                if is_hidden(norm):
                    verdicts[int(kid)] = True
        for aid in sorted(per):
            pairs = [p for p in per[aid] if not verdicts[p[1]]]
            pairs.sort(key=lambda p: (-p[0], p[1]))
            yield aid, {kid for _c, kid in pairs[:_TERMS_PER_ARTICLE]}
        if len(verdicts) > _VERDICTS_KEPT:
            verdicts.clear()


def article_keyword_sets(session, period: Period) -> dict[int, set[int]]:
    """Each in-period article's characterising keyword ids.

    Reads ``keyword_mentions`` only — indexed, no article decrypt. Per article the
    top ``_TERMS_PER_ARTICLE`` by mention count; ties broken by keyword id so the
    grouping is deterministic across runs, which is what lets an edition be
    regenerated and come out the same.

    A keyword the stoplist hides (R111 step T2) takes no slot: it is dropped BEFORE the top
    ``_TERMS_PER_ARTICLE`` is taken. Left in, two unrelated articles that both repeat a
    hidden word (`news`, a LaTeX macro) overlapped on it and could join one story, and the
    terms a story names as shared would have listed it. The shared terms are the
    intersection of these sets, so they inherit the rule. The listing's length rule applies too:
    two-letter terms (`eu`, `un`, `ai`) no longer take part in grouping.

    The WHOLE answer, one set per article of the period: what it holds grows with the period. The edition does not use it
    (:func:`build_stories` keeps only the sets it compares, :func:`_richest_sets`); it is the reference the tests compare that
    path against."""
    return dict(_visible_sets(session, period))


def _richest_sets(session, period: Period, max_articles: int) -> tuple[dict[int, set[int]], int, int]:
    """The sets of the ``max_articles`` richest articles, and how many articles there were: ``(kept, articles_in_period, with_terms)``.

    ``articles_in_period`` counts every article that has mention rows (one whose keywords are all hidden too); ``with_terms``
    those with a non-empty set, the ones that can be compared. The rule for which to keep is the one the comparison always
    had: most visible keywords first, the lowest id among equals. It is applied as the sets arrive, with a heap of
    ``max_articles`` entries whose root is the worst article kept, so what is resident is ``max_articles`` sets of at most
    ``_TERMS_PER_ARTICLE`` ids plus one chunk of mention rows, however many articles the period holds (the period's article COUNT
    is still exact: it is a counter, not a list)."""
    heap: list[tuple[int, int]] = []  # (visible keywords, -article id); the smallest is the worst article kept
    kept: dict[int, set[int]] = {}
    total = with_terms = 0
    for aid, terms in _visible_sets(session, period):
        total += 1
        if not terms:
            continue
        with_terms += 1
        if max_articles < 1:
            continue
        entry = (len(terms), -aid)
        if len(heap) < max_articles:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            _n, worst = heapq.heapreplace(heap, entry)
            del kept[-worst]
        else:
            continue
        kept[aid] = terms
    return kept, total, with_terms


def cluster_articles(
    sets: dict[int, set[int]], *, threshold: float = _JOIN_AT, min_articles: int = _MIN_ARTICLES
) -> list[list[int]]:
    """Group article ids whose keyword sets overlap, using the proven primitives.

    Exact Jaccard (the sets are small, so exact rather than MinHash-estimated) and
    the shared union-find from ``src.signals.near_dup``. Returns clusters of at
    least ``min_articles``, each sorted, the whole list ordered largest first then
    by lowest id — deterministic, so a regenerated edition matches.

    O(n²) in the number of articles, which is why the caller bounds what it hands
    in. That bound is disclosed by the caller, not hidden here.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    from src.signals.near_dup import _connected_components

    ids = sorted(sets)
    labels = {str(i): i for i in ids}
    edges: set[tuple[str, str]] = set()
    for i, a in enumerate(ids):
        sa = sets[a]
        if not sa:
            continue
        for b in ids[i + 1 :]:
            sb = sets[b]
            if not sb:
                continue
            union = sa | sb
            if union and len(sa & sb) / len(union) >= threshold:
                edges.add((str(a), str(b)))
    comps = _connected_components({str(i) for i in ids}, edges)
    clusters = [sorted(labels[lbl] for lbl in comp) for comp in comps]
    clusters = [c for c in clusters if len(c) >= min_articles]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def build_stories(
    session,
    period: Period,
    *,
    limit: int = 12,
    max_articles: int = 4000,
    threshold: float = _JOIN_AT,
) -> dict:
    """The period's story clusters, with the facts each one is built from.

    ``max_articles`` bounds the pairwise comparison. It is a bound on WHICH
    articles were compared, disclosed in the payload — the period's article COUNT
    stays exact everywhere else, and this never changes it. When the bound bites,
    the payload says how many were compared out of how many there were.

    ``limit`` bounds the stories RETURNED, and likewise says so.
    """
    from src.database.maintenance import statement_deadline

    deadline_s = _stories_deadline_s()
    # The mention read is the one step that touches the corpus at its size. It holds a chunk of articles at a time and keeps only the
    # richest ``max_articles`` sets (an article with two indexed terms cannot characterise a story anyway; deterministic tie-break:
    # most visible keywords, then the lowest id), and the deadline bounds how long it may hold the request thread and the shared
    # connection and stops it if it takes the machine to the memory guard's floor. The clustering below is Python over at most
    # ``max_articles`` sets and needs neither. An article with no visible keyword (empty set) is counted in the period and compared on nothing.
    with statement_deadline(session, deadline_s):
        compared, total_articles, with_terms = _richest_sets(session, period, max_articles)
    bounded = with_terms > len(compared)

    clusters = cluster_articles(compared, threshold=threshold)
    shown = clusters[:limit]

    # Terms and sources per shown cluster — small lookups over ids we already hold.
    kw_names: dict[int, str] = {}
    # Each term's stored key and recorded language ride beside its name (re-walk M-3/M-5):
    # the review and the document printed a Russian story's terms bare in a French edition,
    # with nothing saying what language they were in. Additive -- ``shared_terms`` stays the
    # list of names every older reader of the record consumes.
    kw_rows: dict[int, dict[str, Any]] = {}
    wanted = {k for c in shown for a in c for k in compared[a]}
    for i in range(0, len(wanted), 900):
        chunk = list(wanted)[i : i + 900]
        for kid, term, norm, lang in session.query(
            Keyword.id, Keyword.term, Keyword.normalized_term, Keyword.language
        ).filter(Keyword.id.in_(chunk)):
            kw_names[int(kid)] = term
            kw_rows[int(kid)] = {"term": term, "normalized": norm, "language": lang}

    from src.database.outlet import OutletMap

    outlets = OutletMap(session)  # one scan of sources for every shown story, not one each
    stories: list[dict[str, Any]] = []
    for cluster in shown:
        shared: set[int] | None = None
        for a in cluster:
            shared = compared[a] if shared is None else (shared & compared[a])
        shared = shared or set()
        srcs = _sources_of(session, cluster, outlets)
        stories.append(
            {
                "article_ids": cluster,
                "articles": len(cluster),
                "distinct_sources": len(srcs),
                "sources": sorted(srcs.values()),
                "shared_terms": sorted(
                    (kw_names.get(k) for k in shared if kw_names.get(k)), key=str
                ),
                "shared_term_rows": sorted(
                    (kw_rows[k] for k in shared if kw_names.get(k)),
                    key=lambda r: str(r["term"]),
                ),
                "single_source": len(srcs) <= 1,
            }
        )

    return {
        "stories": stories,
        "stories_found": len(clusters),
        "stories_shown": len(shown),
        "articles_in_period": total_articles,
        "articles_compared": len(compared),
        "comparison_bounded": bounded,
        "read_bound": {
            "max_articles": max_articles,
            "terms_per_article": _TERMS_PER_ARTICLE,
            "articles_per_read": _ARTICLE_CHUNK,
            "deadline_s": deadline_s,
            "method": (
                "the period's articles are taken from the article clock index and their mention rows are read "
                f"{_ARTICLE_CHUNK} articles at a time, each reduced to its top {_TERMS_PER_ARTICLE} visible keywords before the "
                f"next read: what is held is the keyword sets of the richest {max_articles:,} articles and one read, whatever the "
                f"length of the period. The read is stopped after {deadline_s:g} s, and the edition then says its stories "
                "could not be built."
            ),
        },
        "threshold": threshold,
        "method": (
            f"articles grouped by the overlap of their top {_TERMS_PER_ARTICLE} indexed "
            f"keywords (exact Jaccard >= {threshold}); clusters of at least "
            f"{_MIN_ARTICLES} articles, largest first. Built from keyword_mentions only "
            "— no article text is read here."
        ),
        "caveat": (
            "A LEXICAL grouping, not a semantic one. It will split one story told in two "
            "languages, and it will join two unrelated stories that share a vocabulary. "
            "Both are properties of grouping by words, not faults to be read around. "
            "`single_source` marks a cluster carried by one source: repetition by one "
            "voice, not corroboration by several."
            + (
                f" Only {len(compared):,} of {total_articles:,} in-period articles were "
                "compared (the richest keyword sets first) — the period's article counts "
                "elsewhere are unaffected and exact."
                if bounded
                else ""
            )
        ),
    }


def _sources_of(session, article_ids: list[int], outlets=None) -> dict[int, str]:
    """The distinct sources behind a cluster, as {source_id: display name}."""
    from src.database.outlet import OutletMap

    rows = (
        session.query(Article.source_id, Source.name, Source.domain)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(article_ids[:900]))
        .all()
    )
    outlets = outlets or OutletMap(session)
    # keyed by the OUTLET's oldest source id so two feeds of one site are one entry in the story's source list
    return {outlets.primary_id(int(sid)): outlets.label(sid, name, domain) for sid, name, domain in rows}


def story_evidence(session, article_ids: list[int], *, budget_chars: int) -> dict:
    """The text a story's narration is grounded in, and nothing else.

    Reads article text — the only place in Layer A/B's fact path that does — and
    only for the articles of ONE story, bounded by ``budget_chars``. Returns the
    excerpt set plus the ids it actually covers, so a narrated sentence's
    provenance names the articles it could possibly have come from rather than the
    whole cluster.

    Lead-first: an article contributes its opening paragraphs, which is where a
    news article states what happened. Truncation is disclosed per article.
    """
    rows = (
        session.query(Article.id, Article.title, Article.published_at)
        .filter(Article.id.in_(article_ids[:900]))
        .order_by(Article.published_at.asc().nullslast(), Article.id)
        .all()
    )
    order = [int(r[0]) for r in rows]
    titles = {int(r[0]): r[1] for r in rows}
    per = max(400, budget_chars // max(1, len(order))) if order else 0

    excerpts: list[dict] = []
    covered: list[int] = []
    used = 0
    for aid in order:
        if used >= budget_chars:
            break
        art = session.get(Article, aid)
        if art is None:
            continue
        try:
            text = (art.get_content() or "").strip()
        except Exception as exc:  # noqa: BLE001 - one unreadable article never loses the story
            log_failure(_LOG, f"bulletin: article {aid} unreadable for narration", exc, level=logging.WARNING)
            continue
        take = text[:per]
        used += len(take)
        covered.append(aid)
        excerpts.append(
            {
                "article_id": aid,
                "title": titles.get(aid),
                "published_at": None
                if not isinstance(art.published_at, datetime)
                else art.published_at.isoformat(),
                "text": take,
                "truncated": len(text) > len(take),
                "chars": len(take),
            }
        )

    return {
        "excerpts": excerpts,
        "article_ids": covered,
        "articles_requested": len(article_ids),
        "articles_covered": len(covered),
        "chars": used,
        "budget_chars": budget_chars,
        "method": (
            "the opening of each article in the story, oldest first, within a character "
            "budget shared across the cluster; truncation is marked per excerpt"
        ),
        "caveat": (
            "Narration may only use what is here. An article the budget did not reach is "
            "NOT part of the evidence, and article_ids lists exactly what is — so a "
            "sentence's provenance names what it could have come from, not the whole cluster."
        ),
    }

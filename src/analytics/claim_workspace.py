"""The Claim Workspace, slice 1 -- an evidence trail for a claim, never a verdict.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design of record: ``docs/FUTURE_DEVELOPMENTS.md`` §"User-centric reflections" A1 and the
action plan's A-2 (``docs/archive/releases/V01_ALPHA_ACTION_PLANS.md``); gate row K of
``docs/product/RELEASE_0.5_GATE.md``, brief ``S05-11`` S1. The user pastes a CLAIM and the
app walks a visible pipeline:

  ① related corpus articles (the full-text index, the same grammar as the Search tab),
  ② grouped by INDEPENDENCE -- articles joined into one PATH when they share a source, a
     near-identical text, an outbound link or a wire attribution,
  ③ who said what, when -- the trail in publication order, with the sentence of each
     article that carries the most of the claim's words,
  ⑤ what is missing -- the countries, languages and source types the corpus holds that
     are silent in this trail, and the kinds of evidence that WOULD discriminate.

Steps ④ (consented corroboration) and ⑥ (the signed export) are slice 2 and say so.

THE TWO LINES THIS MODULE HOLDS (the A-2 comment, both risks named there):

* Independence is never presented as certainty. A path of one article is an article we
  found NO link for -- absence of evidence, and the payload calls it ``unjoined``, never
  ``independent``. The join reasons are the only positive statements, and each one names
  what joined the articles.
* No verdict and no composite. Every figure is a count with its population beside it; no
  field is a score, a rating or a grade (the non-negotiable; walked by the tests). There
  is no LLM anywhere in this path.

COMPOSITION, NOT INVENTION: the related set is :func:`src.database.fts.search_ids`, the
near-identical grouping is :func:`src.signals.near_dup.near_duplicate_clusters` at the
threshold ``queries.corpus_coordination`` uses, the wire attribution is
:func:`src.signals.lineage.detect_wire_attribution`, and the shared-link join reads
``article_links`` the way ``convergence._shared_origin`` does. Nothing here touches the
network and nothing here writes.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from typing import Any

#: The longest claim the workspace accepts (characters). A claim is a sentence or a short
#: paragraph; anything longer is a document, and deriving a query from it would widen the
#: related set past meaning.
MAX_CLAIM_CHARS = 1000
#: How many related articles the trail reads by default, and the most it will ever read.
#: The trail reads article CONTENT (the sentence in step ③, the near-identical text and the
#: wire attribution in step ②), so it is bounded; the TOTAL matched is always reported
#: beside it, so the bound is visible and never a silent cap.
DEFAULT_TRAIL = 50
MAX_TRAIL = 200
#: The most words a derived query carries. More words OR-ed together widen the related set
#: faster than they sharpen its order.
MAX_TERMS = 8
#: The near-identical threshold, the one ``queries.corpus_coordination`` uses (high
#: precision, biased toward under-merging).
NEAR_DUP_THRESHOLD = 0.7
#: A said-what sentence is cut at this many characters (never mid-claim silently: the cut
#: is marked with an ellipsis).
MAX_SENTENCE_CHARS = 300
#: The languages whose closed-class grammar words are dropped when a query is derived from
#: a claim: the twelve UI languages. The derived query is SHOWN and editable, so a word a
#: stoplist wrongly dropped is one edit away.
_QUERY_STOP_LANGS = ("en", "fr", "es", "de", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id")
#: Source types that hold a primary record rather than a report of one.
PRIMARY_RECORD_TYPES = ("statistics", "law")

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？؟।])\s+|\n+")
# Scripts written without spaces between words: a \w+ run there is a phrase, not a word.
_NO_SPACE_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "THAI")


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    from src.services.stopwords import StopwordsManager

    mgr = StopwordsManager()
    words: set[str] = set()
    for lang in _QUERY_STOP_LANGS:
        words |= {w.casefold() for w in mgr.get_stopwords(lang)}
    return frozenset(words)


def _unspaced(token: str) -> bool:
    for ch in token:
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        if any(name.startswith(s) for s in _NO_SPACE_SCRIPTS):
            return True
    return False


#: English function words the shared keyword stoplist keeps (it was tuned for keyword
#: extraction, where "since" or "last" never won a count anyway), dropped here because a
#: derived query OR-ing them would match most of an English corpus.
_QUERY_EXTRA_STOP = frozenset({
    "since", "not", "last", "has", "have", "had", "been", "does", "did", "will", "would",
    "can", "could", "may", "might", "must", "should", "than", "then", "very", "more",
    "most", "less", "every", "each", "over", "under", "after", "before", "about", "into",
    "from", "with", "without", "also", "just", "only", "still", "now", "all", "any",
})


def _tokens(text: str) -> list[str]:
    """The claim's words. A run in a script written without spaces is segmented the way
    the index segments a query (``fts_norm``'s jieba / sudachi, when installed); without
    the segmenter the run stays whole, as the index's own query path leaves it."""
    out: list[str] = []
    for tok in _WORD_RE.findall(text or ""):
        if _unspaced(tok):
            try:
                from src.database import fts_norm

                seg, _bit = fts_norm._segment(tok, fts_norm.available_mask(), for_query=True)
                out.extend(_WORD_RE.findall(seg) or [tok])
                continue
            except Exception:  # noqa: BLE001 -- a missing segmenter leaves the run whole
                pass
        out.append(tok)
    return out


def claim_terms(claim: str) -> list[str]:
    """The claim's content words, in the order it states them, deduplicated.

    Drops the twelve UI languages' grammar words and one- or two-letter tokens, but keeps
    every number of two digits or more (a figure is usually the claim's point). Capped at
    :data:`MAX_TERMS`."""
    stop = _stopwords()
    out: list[str] = []
    seen: set[str] = set()
    for tok in _tokens(claim):
        low = tok.casefold()
        if low in seen:
            continue
        if tok.isdigit():
            if len(tok) < 2:
                continue
        elif len(tok) < (2 if _unspaced(tok) else 3):
            continue
        if low in stop or low in _QUERY_EXTRA_STOP or tok.replace("_", "") == "":
            continue
        seen.add(low)
        out.append(tok)
        if len(out) >= MAX_TERMS:
            break
    return out


def derive_query(claim: str) -> tuple[str, list[str]]:
    """The query step ① runs when the reader typed none: the claim's content words, each
    quoted (so a word such as ``NOT`` is a word, not an operator) and OR-ed together.

    OR, not AND: a claim's exact wording rarely appears in reporting about it, and an AND
    of eight words matches nothing. The order is the index's relevance order (BM25), which
    ranks an article carrying more of the words higher -- the list is a ranking, never a
    sample, and the payload's ``ordering`` says so."""
    terms = claim_terms(claim)
    if not terms:
        return "", []
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms), terms


def _query_words(query: str) -> list[str]:
    """The words of a reader-typed query, for the said-what sentence -- operators and
    field prefixes dropped, grammar words too."""
    stop = _stopwords()
    out: list[str] = []
    seen: set[str] = set()
    for tok in _tokens(query):
        low = tok.casefold()
        if tok in ("AND", "OR", "NOT", "NEAR") or low in stop or low in _QUERY_EXTRA_STOP \
                or low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def best_sentence(text: str, words: list[str]) -> tuple[str | None, int]:
    """The sentence of ``text`` carrying the most distinct ``words`` (case-folded), and
    how many it carries. The earliest sentence wins a tie. ``(None, 0)`` when no sentence
    carries any: the trail then shows the title alone rather than an unrelated line."""
    folded = [w.casefold() for w in words if w]
    if not text or not folded:
        return None, 0
    best, best_n = None, 0
    for raw in _SENT_SPLIT_RE.split(text):
        sent = raw.strip()
        if not sent:
            continue
        low = sent.casefold()
        n = sum(1 for w in folded if w in low)
        if n > best_n:
            best, best_n = sent, n
    if best is not None and len(best) > MAX_SENTENCE_CHARS:
        best = best[: MAX_SENTENCE_CHARS - 1].rstrip() + "…"
    return best, best_n


class _UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic: the smaller id is the root, so the same trail groups the same.
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def group_paths(articles: list[dict], shared_links: dict[str, list[int]],
                near_dup_groups: list[list[int]]) -> dict:
    """Step ② -- join the trail's articles into PATHS, and say what joined each one.

    ``articles``: ``{id, source_id, source, wire, published_at}`` per article.
    ``shared_links``: normalised outbound URL -> the trail's article ids that cite it (only
    URLs cited by two or more). ``near_dup_groups``: groups of near-identical article ids.

    Four joins, each stated on the path it made: the SAME SOURCE (one outlet is one voice),
    NEAR-IDENTICAL TEXT, a SHARED OUTBOUND LINK (several articles citing one page are one
    origin echoed) and the SAME WIRE ATTRIBUTION (three echoes of one wire are one path).
    Pure; deterministic for a given input."""
    ids = [a["id"] for a in articles]
    by_id = {a["id"]: a for a in articles}
    uf = _UnionFind(ids)
    joins: list[dict] = []

    by_source: dict[Any, list[int]] = defaultdict(list)
    by_wire: dict[str, list[int]] = defaultdict(list)
    for a in articles:
        if a.get("source_id") is not None:
            by_source[a["source_id"]].append(a["id"])
        if a.get("wire"):
            by_wire[a["wire"]].append(a["id"])

    def _join(kind: str, members: list[int], detail: str | None) -> None:
        members = sorted({m for m in members if m in by_id})
        if len(members) < 2:
            return
        for m in members[1:]:
            uf.union(members[0], m)
        joins.append({"kind": kind, "detail": detail, "article_ids": members})

    for _sid, members in sorted(by_source.items(), key=lambda kv: str(kv[0])):
        _join("same_source", members, by_id[members[0]].get("source"))
    for group in near_dup_groups:
        _join("near_identical", list(group), None)
    for url in sorted(shared_links):
        _join("shared_link", shared_links[url], url)
    for wire in sorted(by_wire):
        _join("same_wire", by_wire[wire], wire)

    members_of: dict[int, list[int]] = defaultdict(list)
    for i in ids:
        members_of[uf.find(i)].append(i)

    paths: list[dict] = []
    for members in members_of.values():
        mset = set(members)
        path_joins = [j for j in joins if mset.issuperset(j["article_ids"])]
        sources = sorted({by_id[m].get("source") or "?" for m in members})
        dates = sorted(by_id[m]["published_at"] for m in members if by_id[m].get("published_at"))
        paths.append({
            "article_ids": sorted(members),
            "n_articles": len(members),
            "sources": sources,
            "n_sources": len(sources),
            "joins": path_joins,
            # A path of one article with nothing joining it: absence of evidence of a
            # shared origin -- never evidence of independence (the A-2 line).
            "unjoined": len(members) == 1,
            "first_seen": dates[0] if dates else None,
            "last_seen": dates[-1] if dates else None,
        })
    paths.sort(key=lambda p: (-p["n_articles"], p["first_seen"] or "9999", p["article_ids"][0]))
    for n, p in enumerate(paths, start=1):
        p["path"] = n

    all_sources = {by_id[i].get("source") or "?" for i in ids}
    return {
        "paths": paths,
        "n_articles": len(ids),
        "n_sources": len(all_sources),
        "n_paths": len(paths),
        "n_joined_paths": sum(1 for p in paths if not p["unjoined"]),
        "n_unjoined": sum(1 for p in paths if p["unjoined"]),
        "join_counts": dict(Counter(j["kind"] for j in joins)),
    }


def _discriminators(claim: str, trail: list[dict], independence: dict,
                    trail_types: set[str], trail_langs: set[str]) -> list[dict]:
    """Step ⑤'s second half: the kinds of evidence that WOULD discriminate, each tied to a
    fact about THIS trail. Codes, not sentences -- the UI words them in twelve languages,
    and a code with its fact is what a test can pin."""
    out: list[dict] = []
    if not trail:
        return [{"code": "no_related", "fact": {}}]
    if independence["n_paths"] == 1:
        out.append({"code": "one_path", "fact": {"n_articles": independence["n_articles"]}})
    if not trail_types.intersection(PRIMARY_RECORD_TYPES):
        out.append({"code": "no_primary_record", "fact": {"types": list(PRIMARY_RECORD_TYPES)}})
    if len(trail_langs) <= 1:
        out.append({"code": "one_language", "fact": {"languages": sorted(trail_langs)}})
    dates = sorted(a["published_at"] for a in trail if a.get("published_at"))
    if dates:
        span = (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days
        if span <= 2:
            out.append({"code": "short_window", "fact": {"days": span}})
    undated = sum(1 for a in trail if not a.get("published_at"))
    if undated:
        out.append({"code": "undated", "fact": {"n": undated}})
    figures = [t for t in _WORD_RE.findall(claim or "") if any(c.isdigit() for c in t)]
    if figures:
        out.append({"code": "figure_source", "fact": {"figures": figures[:5]}})
    return out


def _silent(corpus: Counter, trail: set, limit: int = 12) -> dict:
    """The keys the corpus holds that the trail does not, most-sourced first. The TOTAL is
    exact; only the listed examples are bounded."""
    silent = sorted((k for k in corpus if k not in trail), key=lambda k: (-corpus[k], str(k)))
    return {
        "total": len(silent),
        "items": [{"key": k, "corpus_sources": corpus[k]} for k in silent[:limit]],
        "in_trail": sorted(str(k) for k in trail),
        "corpus_total": len(corpus),
    }


def _corpus_source_facets(session) -> dict[str, Counter]:
    """Countries, languages and source types over the sources the corpus holds at least one
    (non-quarantined) article from, counted in SOURCES."""
    from sqlalchemy import select

    from src.database.models import Article, Source

    held = select(Article.source_id).where(Article.quarantined.isnot(True)).distinct()
    rows = session.query(Source.country, Source.language, Source.source_type).filter(
        Source.id.in_(held)
    ).all()
    out: dict[str, Counter] = {"countries": Counter(), "languages": Counter(), "source_types": Counter()}
    for country, language, stype in rows:
        if country:
            out["countries"][country.strip().lower()] += 1
        if language:
            out["languages"][language.strip().lower()] += 1
        out["source_types"][(stype or "").strip().lower() or "untyped"] += 1
    return out


def build_workspace(session, claim: str, *, query: str | None = None,
                    limit: int = DEFAULT_TRAIL, expand: bool = True,
                    ui_lang: str | None = None) -> dict:
    """Walk steps ①②③⑤ for ``claim`` over the local corpus. Read-only; no network.

    ``query``: the reader's own query in the Search tab's grammar; ``None`` or blank derives
    one from the claim (:func:`derive_query`) and says so. ``expand`` is the Search tab's R1
    cross-language expansion, on by default as it is there, and disclosed in the payload's
    ``cross_language`` exactly as the Search tab discloses it; ``ui_lang`` only narrows an
    ambiguous term, never adds. Raises
    :class:`src.database.fts.SearchQueryError` on a query the grammar rejects, and
    ``ValueError`` on an empty or over-long claim."""
    from sqlalchemy import func

    from src.database.fts import search_ids
    from src.database.models import Article, ArticleLink, Source
    from src.signals.lineage import detect_wire_attribution
    from src.signals.near_dup import near_duplicate_clusters

    claim = (claim or "").strip()
    if not claim:
        raise ValueError("the claim is empty")
    if len(claim) > MAX_CLAIM_CHARS:
        raise ValueError(f"the claim is longer than {MAX_CLAIM_CHARS} characters")
    limit = max(1, min(int(limit), MAX_TRAIL))

    typed = (query or "").strip()
    if typed:
        q_text, terms, derived = typed, _query_words(typed), False
    else:
        q_text, terms = derive_query(claim)
        derived = True

    expander = None
    if q_text and expand:
        from src.analytics.equivalence import CONCEPT_LITERAL_CAP, QueryExpander

        expander = QueryExpander(prefer_language=(ui_lang or "").strip().casefold() or None,
                                 cap=CONCEPT_LITERAL_CAP)
    ids: list[int] = []
    if q_text:
        ids = search_ids(session, q_text, exclude_quarantined=True, expand=expander) or []
    from src.database.fts import _MAX_CANDIDATES

    total = len(ids)
    at_cap = total >= _MAX_CANDIDATES
    trail_ids = ids[:limit]

    rows = (
        session.query(Article, Source)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(trail_ids))
        .all()
        if trail_ids
        else []
    )
    by_id = {a.id: (a, s) for a, s in rows}
    words = terms or claim_terms(claim)

    trail: list[dict] = []
    texts: dict[str, str] = {}
    for pos, aid in enumerate(trail_ids, start=1):
        if aid not in by_id:
            continue
        a, s = by_id[aid]
        content = a.get_content() or ""
        texts[str(aid)] = ((a.title or "") + "\n" + content).strip()
        said, carried = best_sentence(content, words)
        trail.append({
            "id": a.id,
            "position": pos,
            "title": a.title,
            "url": a.url,
            "source_id": a.source_id,
            "source": (s.name or s.domain) if s else None,
            "source_type": ((s.source_type or "").strip().lower() or "untyped") if s else None,
            "country": ((s.country or "").strip().lower() or None) if s else None,
            "language": a.language or a.detected_language or (s.language if s else None),
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "wire": detect_wire_attribution(content),
            "said": said,
            "said_words": carried,
        })

    near_groups: list[list[int]] = []
    if len(texts) >= 2:
        res = near_duplicate_clusters(texts, threshold=NEAR_DUP_THRESHOLD)
        near_groups = [[int(m) for m in c.members] for c in res.clusters if len(c.members) >= 2]

    shared: dict[str, list[int]] = {}
    present = [a["id"] for a in trail]
    if len(present) >= 2:
        grouped = (
            session.query(ArticleLink.normalized_url)
            .filter(ArticleLink.article_id.in_(present), ArticleLink.normalized_url.isnot(None))
            .group_by(ArticleLink.normalized_url)
            .having(func.count(func.distinct(ArticleLink.article_id)) > 1)
            .subquery()
        )
        for url, aid in (
            session.query(ArticleLink.normalized_url, ArticleLink.article_id)
            .filter(ArticleLink.article_id.in_(present),
                    ArticleLink.normalized_url.in_(session.query(grouped.c.normalized_url)))
            .distinct()
            .all()
        ):
            shared.setdefault(url, []).append(int(aid))

    independence = group_paths(trail, shared, near_groups)
    path_of = {aid: p["path"] for p in independence["paths"] for aid in p["article_ids"]}

    # ③ publication order; undated last, in the index's order among themselves.
    timeline = sorted(trail, key=lambda a: (a["published_at"] is None, a["published_at"] or "",
                                            a["position"]))
    first_dated = next((a["id"] for a in timeline if a["published_at"]), None)
    timeline_rows = [
        {**{k: a[k] for k in ("id", "title", "url", "source", "published_at", "wire", "said",
                              "said_words", "language", "country", "source_type")},
         "path": path_of.get(a["id"]),
         "first_in_corpus": a["id"] == first_dated}
        for a in timeline
    ]

    facets = _corpus_source_facets(session)
    trail_countries = {a["country"] for a in trail if a["country"]}
    trail_langs = {(a["language"] or "").lower() for a in trail if a["language"]}
    trail_source_langs = set()
    trail_types = {a["source_type"] for a in trail if a["source_type"]}
    for a in trail:
        s = by_id[a["id"]][1]
        if s is not None and s.language:
            trail_source_langs.add(s.language.strip().lower())
    missing = {
        "countries": _silent(facets["countries"], trail_countries),
        "languages": _silent(facets["languages"], trail_source_langs),
        "source_types": _silent(facets["source_types"], trail_types),
        "would_discriminate": _discriminators(claim, trail, independence, trail_types,
                                              trail_langs),
    }

    return {
        "claim": claim,
        "query": {"text": q_text, "derived": derived, "terms": terms, "expanded": expander is not None},
        "cross_language": expander.disclosure() if expander is not None else None,
        "related": {
            "total": total,
            "at_index_cap": at_cap,
            "index_cap": _MAX_CANDIDATES,
            "shown": len(trail),
            "limit": limit,
            "ordering": "relevance" if q_text else None,
            "articles": [
                {k: a[k] for k in ("id", "position", "title", "url", "source", "published_at",
                                   "language")}
                for a in trail
            ],
        },
        "independence": independence,
        "timeline": timeline_rows,
        "missing": missing,
        "steps_built": [1, 2, 3, 5],
        "steps_not_built": [4, 6],
    }

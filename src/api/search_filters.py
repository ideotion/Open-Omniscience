"""The advanced search's filter set, as ONE object every search surface shares (S05-01).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row A of the 0.5 gate closes on one property above all: *an export reproduces the
filtered view* (Q607), and a saved search re-runs identically (Q606). Both are promises
that several endpoints read the SAME filters the SAME way. The way that fails is a second
copy of the parameter list that drifts -- ``/api/articles/export`` took eight of
``/api/articles``' thirteen parameters for as long as both existed, and five analysis
subtabs once searched a different set than the Articles list beside them.

So the filters beyond the original seven live here, once:

* :func:`advanced_search_params` is a FastAPI dependency. ``/api/articles``,
  ``/api/articles/export`` and every analysis-window endpoint declare it, so a filter
  added here reaches all of them in the same diff.
* :meth:`AdvancedSearch.conditions` turns it into SQLAlchemy conditions over
  ``Article`` -- the only place the meaning of each filter is written down.
* :meth:`AdvancedSearch.to_dict` / :meth:`AdvancedSearch.from_dict` are the stored form a
  saved search (a watch with threshold 0) keeps, so the watch engine rebuilds the same
  object from the row and evaluates the same conditions.

Every filter is DESCRIPTIVE -- asserted metadata, a stored measurement or a count --
never a score. The two whose meaning is easy to overstate carry their caveat in the
payload (:data:`FILTER_CAVEATS`), so the surfaces render it rather than re-word it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, Query

from src.database.fts import NEAR_DEFAULT, NEAR_MAX, NEAR_MIN

#: The three stored sentiment labels (VADER, English only; see the caveat below).
SENTIMENT_LABELS = ("positive", "neutral", "negative")
#: Which of an article's two language facts a language filter reads (Q601).
LANG_BASES = ("any", "asserted", "detected")

#: The caveats a surface must show beside the filter they qualify, verbatim.
FILTER_CAVEATS = {
    "sentiment": (
        "Sentiment is VADER, an English lexicon: it is stored for English articles only, "
        "so filtering by it keeps English articles and drops every other language."
    ),
    "words": (
        "Word counts are split on spaces. Chinese, Japanese and Thai are written without "
        "them, so an article in those scripts counts as a few very long words."
    ),
    "mentions": (
        "A mentioned date is extracted from the text by a pattern matcher and never "
        "confirmed unless you confirm it; rejected dates are ignored."
    ),
    "quarantine": (
        "Quarantined items are pages the app judged not to be articles (navigation, "
        "cookie walls). They are hidden unless you include them; each shows its reason."
    ),
}


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _iso_date(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        date.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be YYYY-MM-DD") from exc
    return value[:10]


@dataclass
class AdvancedSearch:
    """The Q601 filters the original ``/api/articles`` parameters did not cover.

    Every field defaults to "no constraint", so an ``AdvancedSearch()`` changes nothing:
    the endpoints that gained it return byte-identical results to a caller that never
    sends one of these parameters."""

    langs: list[str] = field(default_factory=list)
    lang_basis: str = "any"
    source_ids: list[int] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    collected_from: str | None = None
    collected_to: str | None = None
    words_min: int | None = None
    words_max: int | None = None
    sentiments: list[str] = field(default_factory=list)
    mentions_from: str | None = None
    mentions_to: str | None = None
    include_quarantined: bool = False
    exact: bool = False
    near: int = NEAR_DEFAULT

    # -- the stored form (saved searches) ---------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Only the fields that differ from the default, so a stored row stays small and
        a filter added later reads as "not set" on every row saved before it existed."""
        default = asdict(AdvancedSearch())
        return {k: v for k, v in asdict(self).items() if v != default[k]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AdvancedSearch:
        """The inverse of :meth:`to_dict`; unknown keys are ignored (a newer build's row
        read by an older one), a malformed value falls back to the default."""
        out = cls()
        if not isinstance(data, dict):
            return out
        known = set(asdict(out))
        for k, v in data.items():
            if k in known:
                setattr(out, k, v)
        try:
            return _validated(out)
        except HTTPException:
            return cls()

    @property
    def is_default(self) -> bool:
        return not self.to_dict()

    # -- the meaning ------------------------------------------------------------ #

    def conditions(self, session) -> list:
        """SQLAlchemy conditions over ``Article`` (bound values only)."""
        from sqlalchemy import and_, exists, false, or_

        from src.catalog.countries import country_query_forms
        from src.database.models import Article, ArticleMentionedDate, Source

        conds: list = []
        if self.langs:
            langs = [lang.lower() for lang in self.langs]
            asserted = Article.language.in_(langs)
            # `detected_language` is set only when `language` is absent (field §2.6), so
            # "any" is the asserted language, or the detected one where none is asserted.
            detected = and_(Article.language.is_(None), Article.detected_language.in_(langs))
            conds.append(
                asserted if self.lang_basis == "asserted"
                else detected if self.lang_basis == "detected"
                else or_(asserted, detected)
            )
        if self.source_ids:
            conds.append(Article.source_id.in_(self.source_ids))
        if self.countries or self.regions:
            sq = session.query(Source.id)
            if self.countries:
                forms: set[str] = set()
                for c in self.countries:
                    forms.update(country_query_forms(c))
                sq = sq.filter(Source.country.in_(sorted(forms)))
            if self.regions:
                sq = sq.filter(Source.region.in_(self.regions))
            ids = [sid for (sid,) in sq]
            conds.append(Article.source_id.in_(ids) if ids else false())
        if self.collected_from:
            conds.append(Article.created_at >= datetime.fromisoformat(self.collected_from))
        if self.collected_to:
            # Inclusive of the whole last day: "collected between 1 and 3 May" includes an
            # article collected at 14:00 on the 3rd.
            conds.append(Article.created_at < _day_after(self.collected_to))
        if self.words_min is not None:
            conds.append(Article.word_count >= self.words_min)
        if self.words_max is not None:
            conds.append(Article.word_count <= self.words_max)
        if self.sentiments:
            conds.append(Article.sentiment_label.in_(self.sentiments))
        if self.mentions_from or self.mentions_to:
            sub = [
                ArticleMentionedDate.article_id == Article.id,
                ArticleMentionedDate.status != "rejected",
            ]
            if self.mentions_from:
                sub.append(ArticleMentionedDate.mentioned_on >= date.fromisoformat(self.mentions_from))
            if self.mentions_to:
                sub.append(ArticleMentionedDate.mentioned_on <= date.fromisoformat(self.mentions_to))
            conds.append(exists().where(and_(*sub)))
        return conds


def _day_after(iso: str) -> datetime:
    from datetime import timedelta

    return datetime.fromisoformat(iso[:10]) + timedelta(days=1)


def _validated(a: AdvancedSearch) -> AdvancedSearch:
    """Normalise and bound every field; a value no filter can mean is a 400, not a guess."""
    a.langs = [str(v).strip().lower() for v in (a.langs or []) if str(v).strip()][:50]
    if a.lang_basis not in LANG_BASES:
        raise HTTPException(status_code=400, detail=f"lang_basis must be one of {list(LANG_BASES)}")
    try:
        a.source_ids = [int(v) for v in (a.source_ids or [])][:500]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="sources must be article-source ids") from exc
    a.countries = [str(v).strip() for v in (a.countries or []) if str(v).strip()][:100]
    a.regions = [str(v).strip() for v in (a.regions or []) if str(v).strip()][:50]
    a.collected_from = _iso_date(a.collected_from, "collected_from")
    a.collected_to = _iso_date(a.collected_to, "collected_to")
    a.mentions_from = _iso_date(a.mentions_from, "mentions_from")
    a.mentions_to = _iso_date(a.mentions_to, "mentions_to")
    for name in ("words_min", "words_max"):
        v = getattr(a, name)
        if v is not None:
            try:
                v = int(v)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{name} must be a whole number") from exc
            if v < 0:
                raise HTTPException(status_code=400, detail=f"{name} must not be negative")
            setattr(a, name, v)
    bad = [s for s in (a.sentiments or []) if s not in SENTIMENT_LABELS]
    if bad:
        raise HTTPException(status_code=400, detail=f"sentiment must be among {list(SENTIMENT_LABELS)}")
    a.sentiments = list(dict.fromkeys(a.sentiments or []))
    try:
        a.near = int(a.near)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="near must be a whole number") from exc
    if not NEAR_MIN <= a.near <= NEAR_MAX:
        raise HTTPException(status_code=400, detail=f"near must be between {NEAR_MIN} and {NEAR_MAX}")
    a.include_quarantined = bool(a.include_quarantined)
    a.exact = bool(a.exact)
    return a


def advanced_search_params(
    langs: str | None = Query(None, description="Q601: languages, comma-separated (multi-select)."),
    lang_basis: str = Query(
        "any",
        description="Which language fact `langs` reads: any (asserted, else detected) | "
        "asserted | detected.",
    ),
    sources: str | None = Query(None, description="Q601: source ids, comma-separated."),
    countries: str | None = Query(
        None, description="Q601: source countries, comma-separated; alpha-2 or alpha-3."
    ),
    regions: str | None = Query(None, description="Q601: source regions, comma-separated."),
    collected_from: str | None = Query(
        None, description="Q601: collected on or after (YYYY-MM-DD); the app's own clock."
    ),
    collected_to: str | None = Query(None, description="Q601: collected on or before (YYYY-MM-DD)."),
    words_min: int | None = Query(None, ge=0, description="Q601: at least this many words."),
    words_max: int | None = Query(None, ge=0, description="Q601: at most this many words."),
    sentiment: str | None = Query(
        None, description="Q601: stored sentiment labels, comma-separated (English only)."
    ),
    mentions_from: str | None = Query(
        None, description="Q601: mentions a date on or after (YYYY-MM-DD)."
    ),
    mentions_to: str | None = Query(None, description="Q601: mentions a date on or before."),
    include_quarantined: bool = Query(
        False, description="Q617: include items the app judged not to be articles."
    ),
    exact: bool = Query(
        False, description="Q610: match case and accents exactly (default folds them)."
    ),
    near: int = Query(NEAR_DEFAULT, description="Q612: the distance a NEAR without one takes."),
) -> AdvancedSearch:
    """The FastAPI dependency; every endpoint that searches articles declares it."""
    return _validated(
        AdvancedSearch(
            langs=_csv(langs),
            lang_basis=(lang_basis or "any").strip().lower(),
            source_ids=[v for v in _csv(sources) if v.lstrip("-").isdigit()]  # type: ignore[misc]
            if sources else [],
            countries=_csv(countries),
            regions=_csv(regions),
            collected_from=collected_from,
            collected_to=collected_to,
            words_min=words_min,
            words_max=words_max,
            sentiments=[s.lower() for s in _csv(sentiment)],
            mentions_from=mentions_from,
            mentions_to=mentions_to,
            include_quarantined=include_quarantined,
            exact=exact,
            near=near,
        )
    )


#: What each order IS, in one sentence -- the payload, the export header and the table
#: all carry this, so a reader never mistakes a ranked list for a sample (Q618 = b).
_ORDER_STATEMENTS = {
    "relevance": (
        "Ordered by relevance (FTS5 bm25, title weighted above body): the best text "
        "matches first. A ranked list is not a sample of the corpus."
    ),
    "date": "Ordered by publication date.",
    "source": "Ordered by source name.",
    "title": "Ordered by title.",
    "language": "Ordered by language code.",
    "words": "Ordered by stored word count; articles with none counted sort lowest.",
    "sentiment": (
        "Ordered by stored VADER score; articles without one (every non-English "
        "article) sort lowest."
    ),
    "top_keyword": "Ordered by how often each article's own most-mentioned keyword occurs.",
    "keyword_count": "Ordered by how often the searched keyword occurs in each article.",
    "request": "In the order the article ids were given.",
}


def result_ordering(
    query: str | None, sort_by: str | None, sort_dir: str | None, *, ids: bool = False
) -> dict[str, str | None]:
    """The order a result list is in: ``{"by", "direction", "statement"}``.

    Relevance is the default for a text query (Q618 = b); without one there is nothing
    to rank by, so the default -- and an explicit ``relevance`` -- is newest first, and
    the statement says which of the two the reader actually got."""
    if ids:
        return {"by": "request", "direction": None, "statement": _ORDER_STATEMENTS["request"]}
    by = sort_by or ("relevance" if query else "date")
    if by == "relevance" and not query:
        by = "date"
    direction = None if by == "relevance" else ("asc" if (sort_dir or "").lower() == "asc" else "desc")
    return {"by": by, "direction": direction, "statement": _ORDER_STATEMENTS.get(by, "")}

"""The Feed: your corpus, one article at a time, in an order nothing chose for you.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, rulings 8-13 and 40-41. A reading surface rather than an
analysis one: it defaults to EVERYTHING in the corpus, shows each article's own top
keywords, and expands in place.

WHAT THE ORDER IS, AND WHAT IT IS NOT
-------------------------------------
Two orders, both exact and both stateless:

``recent``    -- newest first, keyset on ``(published_at, id)``.
``shuffled``  -- a deterministic PERMUTATION of the article ids, chosen by a seed.

The shuffled key is ``(id * mult + add) % P`` with P prime and ``mult`` non-zero mod P,
which makes it a bijection: distinct ids get distinct keys, so a page boundary can
neither repeat an article nor skip one. It depends on the article's ID and the SEED and
on nothing else -- not on the article's content, its source, its age, its length, how
many keywords it has, or anything the reader has ever done. There is no engagement
signal here to leak into it, because none is collected: that is what makes this a browse
aid rather than a recommendation engine, and it is a property of the arithmetic rather
than a promise about our intentions.

Stated plainly rather than dressed up, because the structure is real: this is an AFFINE
permutation, so consecutive cards are a constant id-stride apart, and from a handful of
positions the seed is recoverable. On a corpus of a dozen articles that stride is visible
to the naked eye; at the scale this runs at it is hundreds of thousands of ids wide, so
two consecutive cards are nowhere near each other in ingestion order, which is the
property a reader actually wants. It is not unpredictable and does not claim to be --
"an order I did not choose" is the whole promise, and a cryptographic shuffle would buy
nothing here except a sentence we would then have to keep true.

WHY THE SERVER KEEPS NO READING HISTORY
---------------------------------------
Because the order is a permutation, "everything I have already scrolled past" is exactly
"every key below where I am now" -- ONE number. So the whole of seen/unseen is the seed
plus a watermark, held by the client, and there is no per-article read log anywhere: not
in the corpus, not in a table, not in a backup. A reading history is a surveillance
artifact for the people this app is built for, and the cheapest way not to leak one is
not to have one.

The honest limit of that: an article ingested WHILE you are scrolling gets a key like any
other, and if it lands below your watermark this pass will not show it. Reshuffling (a
new seed, from zero) reaches it. The same is true of the chronological order, where new
articles arrive above a watermark that is moving down. The UI says so rather than leaving
a reader to assume they have seen everything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, literal, literal_column, select, text, tuple_
from sqlalchemy.orm import Session

from src.database.session import get_db

router = APIRouter(prefix="/api/feed", tags=["feed"])

# 2**31 - 1, a Mersenne prime. Every article id is far below it, so `id % P == id` and
# the map below is a permutation of the ids rather than of residue classes.
_P = 2147483647

_PAGE_DEFAULT = 20
_PAGE_MAX = 50

# How much of the body the "read more" expansion shows without a second request. The
# collapsed card shows _EXCERPT_SHORT; expanding shows _EXCERPT_LONG, which is already in
# the payload. Past that the card says so and points at the reader, because pretending a
# 40 KB article fits in a feed card would be the dishonest part, not the bound itself.
_EXCERPT_SHORT = 320
_EXCERPT_LONG = 1400

# Per-article keywords shown on a card (ruling 10). Three, with their real counts.
_TOP_K = 3


# Knuth's 32-bit golden-ratio multiplier and a mixing constant. They are here to SPREAD
# the seed, not to secure anything: see the defect note in shuffle_params.
_SPREAD = 2654435761
_MIX = 0x7F4A7C15


def shuffle_params(seed: int) -> tuple[int, int]:
    """``(mult, add)`` for a seed -- the whole of the shuffle's state.

    ``mult`` is forced non-zero mod P so the map stays a bijection; a seed that happened
    to land on zero would collapse every article onto one key, which is the one input
    that would break pagination.

    THE MULTIPLIER IS SPREAD, and that is not cosmetic. An affine map over the integers
    only MIXES where the product wraps the modulus. A first cut took ``mult = 1 + seed %
    (P-1)``, so seed 12 gave multiplier 13 -- and for a corpus of a few thousand articles
    13*id never reaches P, so the key stayed strictly increasing in id and the "shuffled"
    feed was the corpus in ingestion order while saying it was shuffled. That is a
    fabricated shuffle, and it fails exactly where it is least likely to be noticed: on a
    small corpus, where a reader has no way to tell. Hashing the seed first makes the
    multiplier large for EVERY seed, so consecutive ids land far apart whatever the
    caller sends and the endpoint does not depend on the client choosing a good one.

    ``add`` only rotates, so it is the multiplier that makes two seeds different ORDERS
    rather than the same order started somewhere else.
    """
    s = abs(int(seed))
    # Confined to the MIDDLE HALF of the range, [P/4, 3P/4). "Large" is not enough on its
    # own: a multiplier just BELOW P behaves like a small negative one, so seed 0 with a
    # merely-hashed multiplier produced strict descending id order -- structured in the
    # other direction, and just as visible. Inside this band both `mult` and `P - mult`
    # exceed P/4, so consecutive ids are always at least a quarter of the range apart.
    mult = (_P // 4) + ((s * _SPREAD + _MIX) % (_P // 2))
    add = ((s * _MIX) + _SPREAD) % _P
    return mult, add


def shuffle_key(article_id: int, seed: int) -> int:
    """The pure reference for the SQL expression below. Tests compare the two."""
    mult, add = shuffle_params(seed)
    return (article_id * mult + add) % _P


def _visible(Article: Any, Source: Any) -> list:
    """The two exclusions of ruling 11, as SQL.

    QUARANTINED articles are held back with ``isnot(True)``, so a pre-migration NULL (an
    article never judged) reads as not-quarantined, exactly as every other quarantine
    filter in this codebase treats it.

    NOT-YET-QUALIFIED sources are held back too, which is the stricter half: `status` is
    NOT NULL DEFAULT 'unqualified', so a corpus whose qualification pass has never run
    holds EVERYTHING back. That is the ruling working, not a bug -- but it means an empty
    feed is a state a real machine reaches, so the endpoint reports the held-back count
    and its reason rather than rendering nothing and letting a reader conclude their
    corpus is empty.
    """
    return [
        Article.quarantined.isnot(True),
        Source.status == "qualified",
    ]


def _top_keywords(session: Session, article_ids: list[int]) -> dict[int, list[dict]]:
    """The top ``_TOP_K`` keywords of each article on THIS page, with real counts.

    Reads ``keyword_mentions`` and ``keywords`` only. It never joins back to ``articles``
    -- that join drags whole article rows (content sits early in the column order)
    through the SQLCipher codec for a short string, which is the measured trap this
    codebase has hit before. Ordering is by count then keyword id, so a tie resolves the
    same way on every call rather than shifting between reloads.
    """
    if not article_ids:
        return {}
    from src.database.models import Keyword, KeywordMention

    rows = session.execute(
        select(
            KeywordMention.article_id,
            KeywordMention.keyword_id,
            KeywordMention.count,
            Keyword.term,
        )
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .where(KeywordMention.article_id.in_(article_ids))
    ).all()
    by_article: dict[int, list[tuple[int, int, str]]] = {}
    for aid, kid, count, term in rows:
        by_article.setdefault(aid, []).append((int(count or 0), int(kid), term))
    out: dict[int, list[dict]] = {}
    for aid, items in by_article.items():
        items.sort(key=lambda t: (-t[0], t[1]))
        out[aid] = [{"term": term, "count": n} for n, _kid, term in items[:_TOP_K]]
    return out


def _card(a: Any, keywords: list[dict]) -> dict:
    body = a.content or ""
    return {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "source": a.source.name if a.source else None,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "language": a.language,
        "detected_language": a.detected_language,
        # Two lengths, both already here: expanding a card must not cost a request, and a
        # feed that fetches on every "read more" is a feed that stutters.
        "excerpt": body[:_EXCERPT_SHORT],
        "excerpt_full": body[:_EXCERPT_LONG],
        # Says outright that there is more than the card can hold, so "read more" never
        # implies it showed you the article.
        "truncated": len(body) > _EXCERPT_LONG,
        "chars": len(body),
        # This article's own top keywords with their real counts (ruling 10) -- countable
        # facts a reader can check in the reader, never a relevance figure.
        "keywords": keywords,
        "reader_url": f"/api/articles/{a.id}/view",
    }


@router.get("")
def feed(
    order: str = Query("shuffled", description="shuffled | recent"),
    seed: int = Query(0, description="the shuffle's seed; ignored when order=recent"),
    after: str | None = Query(None, description="opaque cursor from the previous page"),
    limit: int = Query(_PAGE_DEFAULT, ge=1, le=_PAGE_MAX),
    provenance: str | None = Query(None, description="one content-provenance class"),
    db: Session = Depends(get_db),
) -> dict:
    """One page of the feed, plus the cursor for the next.

    Keyset, never OFFSET: an offset page re-counts everything before it and, on a corpus
    that grows while you scroll, silently shifts rows across the boundary you already
    passed. The cursor is the last row's own order key, so the next page starts exactly
    where this one stopped whatever arrived in between.
    """
    from src.catalog.provenance import PROVENANCE_CLASSES, provenance_of
    from src.database.models import Article, Source

    if order not in ("shuffled", "recent"):
        raise HTTPException(status_code=400, detail="order must be shuffled or recent")
    if provenance is not None and provenance not in PROVENANCE_CLASSES:
        raise HTTPException(
            status_code=400, detail=f"provenance must be one of {sorted(PROVENANCE_CLASSES)}"
        )

    # ID-ONLY resolve, then load the page's full rows (the house over-fetch bound). The
    # shuffled order cannot be indexed, so SQLite sorts the whole admissible set through a
    # temp b-tree -- and that sorter stores the SELECTED columns, so `SELECT articles.*`
    # pushes every candidate's `content` through it to return twenty. Measured on a
    # synthetic 200,000-article corpus: 529 ms with the full-row select, 25 ms resolving
    # ids first. On the encrypted store each of those rows is also a decrypt.
    # NO QUALIFIED SOURCE, NO WALK. Both orders would otherwise scan the whole corpus to
    # return nothing -- and "nothing is qualified yet" is not a rare state: it is what a
    # fresh install and a just-imported corpus both look like until the qualification pass
    # has run, which is precisely the case `held_back` exists to explain. One index probe
    # (idx_source_status) replaces that scan; measured on the synthetic 200,000-article
    # corpus with zero qualified sources, the walk it skips costs 214 ms. The result is
    # the same empty page, built by the same code below, so this can only make the empty
    # case cheaper -- never say anything different about it.
    has_qualified = bool(db.query(Source.id).filter(Source.status == "qualified").limit(1).first())

    # ID-ONLY resolve, then load the page's full rows (the house over-fetch bound). The
    # shuffled order cannot be indexed, so SQLite sorts the whole admissible set through a
    # temp b-tree -- and that sorter stores the SELECTED columns, so `SELECT articles.*`
    # pushes every candidate's `content` through it to return twenty. Measured on a
    # synthetic 200,000-article corpus: 529 ms with the full-row select, 25 ms resolving
    # ids first. On the encrypted store each of those rows is also a decrypt.
    #
    # THE JOIN CARRIES A PLAN HINT, and only for the chronological order. Unary `+` on a
    # column is a SQLite no-op that makes that term unusable as an index lookup, which is
    # the documented way to refuse a join order. Without it SQLite drives the FIRST page
    # from `sources`: for each qualified source it walks every article of that source by
    # source_id, then sorts the whole admissible set in a temp b-tree, because it cannot
    # tell that walking `published_at` in reverse would satisfy the LIMIT after ~21 rows.
    # With it, articles is the outer loop, the existing idx_article_published_at gives the
    # ORDER BY for free, and a bloom filter tests the source. Measured on the synthetic
    # 200,000-article corpus, first page, median of n=5, ACROSS the fraction of sources
    # that are qualified -- the axis that decides this, since the planner's cost grows
    # with it while the hint's stays flat:
    #
    #     qualified   planner    +hint          qualified   planner    +hint
    #       1/200       2.3 ms    4.2 ms          20/200      43.4 ms    0.2 ms
    #       2/200       4.4 ms    2.2 ms         100/200     217.7 ms    0.2 ms
    #       5/200      11.1 ms    0.9 ms         180/200     406.3 ms    0.1 ms
    #
    # Identical rows at every fraction. It loses only at 0/200, which the guard above now
    # answers without a query at all. The hint is FAIL-SOFT: `INDEXED BY` would pin the
    # same plan but raises "no query solution" if the index is ever absent, on the most
    # common request in the tab; `+` on a store without a usable index simply lets SQLite
    # plan as it does today.
    if order == "recent":
        q = db.query(Article.id).join(Source, text("+articles.source_id = sources.id"))
    else:
        q = db.query(Article.id).join(Source, Article.source_id == Source.id)
    q = q.filter(and_(*_visible(Article, Source)))

    if order == "shuffled":
        mult, add = shuffle_params(seed)
        key = (Article.id * mult + add) % _P
        if after:
            try:
                q = q.filter(key > int(after))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="malformed cursor") from exc
        q = q.order_by(key)
    else:
        if after:
            try:
                ts_s, id_s = after.split("|", 1)
                cur_ts = datetime.fromisoformat(ts_s) if ts_s else None
                cur_id = int(id_s)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="malformed cursor") from exc
            # (published_at, id) DESC, so "after" means strictly older -- with the id as
            # the tiebreak, because a great many articles share a publication timestamp
            # and a boundary without one drops or repeats every row that shares it.
            #
            # Written as a ROW VALUE rather than the equivalent
            # ``published_at < ts OR (published_at = ts AND id < id)``. The disjunction is
            # correct and SQLite plans it as a MULTI-INDEX OR with a temp b-tree on top;
            # the row value collapses to one index search. Measured on the same synthetic
            # 200,000-article corpus: 191.8 ms -> 1.3 ms for one page. Row-value
            # comparison needs SQLite >= 3.15 (2016), which is far below this project's
            # floor.
            if cur_ts is not None:
                # ``literal`` rather than the bare Python values: SQLAlchemy coerces
                # them either way and the compiled SQL is byte-identical (verified,
                # same binds, same types), but the bare form is untyped to mypy.
                q = q.filter(
                    tuple_(Article.published_at, Article.id)
                    < tuple_(
                        literal(cur_ts, Article.published_at.type),
                        literal(cur_id, Article.id.type),
                    )
                )
            else:
                q = q.filter(Article.published_at.is_(None), Article.id < cur_id)
        q = q.order_by(Article.published_at.desc(), Article.id.desc())

    # LIMIT AS A LITERAL, not a bind. SQLAlchemy renders `.limit(n)` as `LIMIT ? OFFSET ?`,
    # and SQLite plans a bound limit without knowing it is small: it abandons the covering
    # index for the feed scan, falls back to a plain source_id index, and reads article
    # ROWS for the sort. Measured on the synthetic 200,000-article corpus, same statement,
    # same parameters, same connection: 323 ms with `LIMIT ?`, 33 ms with `LIMIT 21` --
    # and the EXPLAIN differs, so it is a plan change rather than noise. The value is an
    # int FastAPI has already bounded to [1, _PAGE_MAX] and is re-cast here, so only an
    # integer can ever reach the SQL.
    page_n = int(limit) + 1   # one extra: is there a next page, without a count?
    ids = [r[0] for r in q.limit(literal_column(str(page_n))).all()] if has_qualified else []
    has_more = len(ids) > limit
    ids = ids[:limit]

    # Full rows for the PAGE only, returned in the resolved order. `content` is decrypted
    # for these twenty and no others.
    by_id = {a.id: a for a in db.query(Article).filter(Article.id.in_(ids)).all()} if ids else {}
    rows = [by_id[i] for i in ids if i in by_id]

    if provenance:
        rows = [
            a
            for a in rows
            if provenance_of(
                a.source.domain if a.source else None,
                a.source.source_type if a.source else None,
            )
            == provenance
        ]

    kw = _top_keywords(db, [a.id for a in rows])
    cards = [_card(a, kw.get(a.id, [])) for a in rows]

    # The cursor is the last position the SCAN reached, not the last row that survived the
    # provenance filter. Those differ whenever the filter drops the tail of a page, and if
    # a page is filtered away entirely the surviving list is empty -- taking the cursor
    # from it would return null and END the scroll while the corpus still had pages. The
    # scan position never lies about where to resume.
    last = by_id.get(ids[-1]) if ids else None
    if last is None:
        next_cursor = None
    elif order == "shuffled":
        next_cursor = str(shuffle_key(last.id, seed))
    else:
        next_cursor = f"{last.published_at.isoformat() if last.published_at else ''}|{last.id}"

    return {
        "order": order,
        "seed": seed if order == "shuffled" else None,
        "results": cards,
        "next_cursor": next_cursor,
        "has_more": has_more,
        # A card count is not a corpus count, and a reader who scrolls into an empty page
        # deserves the reason rather than a blank column.
        #
        # FIRST PAGE ONLY. These are two exact COUNTs over the whole corpus, so paying
        # them on every page of an infinite scroll costs O(corpus) per twenty cards. They
        # describe the corpus rather than the page, so they cannot change as you scroll:
        # the client keeps the first answer.
        #
        # THE FIGURE HERE WAS 180 ms AND IS NOW 4.7 (median of n=7, same corpus). Nothing
        # about these counts changed -- idx_article_feed_scan, added for the shuffled
        # walk, happens to cover both of them. Recorded rather than quietly restated,
        # because a measurement that was true when taken and was made false by a later
        # change is exactly the kind of number that goes on justifying a decision after
        # it has stopped supporting it. First-page-only still holds on its own terms: 4.7
        # ms times every page of an infinite scroll is waste for an answer that cannot
        # have changed.
        #
        # `None` here means "not recomputed", which is why it is null rather than a zero
        # that would read as "nothing is held back".
        "held_back": None if after else _held_back(db, Article, Source),
        # Both of these are i18n KEYS: the DOM walker translates a text node by exact
        # match, so they are written once here and carried in all twelve locale files.
        # Editing either without re-keying it silently un-translates it in eleven of them
        # -- and the caveat is a caveat, which ships x12 by the informed-consent rule.
        "method": (
            "A fixed order chosen by a seed — it uses each article's id and that seed "
            "and nothing else. No reading history is kept or consulted."
            if order == "shuffled"
            else "By publication date, newest first."
        ),
        "caveat": (
            "Articles collected while you scroll may fall below the point you have "
            "reached; reshuffling reaches them."
            if order == "shuffled"
            else "Articles collected while you scroll arrive above the point you have "
            "reached; returning to the top reaches them."
        ),
    }


def _held_back(db: Session, Article: Any, Source: Any) -> dict:
    """Why the feed is shorter than the corpus -- counted, never estimated.

    Both numbers are exact counts over indexed columns. They exist so that an empty feed
    on a corpus that has articles reads as "your sources have not been qualified yet",
    which is actionable, instead of as "you have nothing", which is false.
    """
    quarantined = db.query(func.count(Article.id)).filter(Article.quarantined.is_(True)).scalar()
    unqualified = (
        db.query(func.count(Article.id))
        .join(Source, Article.source_id == Source.id)
        .filter(Source.status != "qualified", Article.quarantined.isnot(True))
        .scalar()
    )
    return {
        "quarantined": int(quarantined or 0),
        "source_not_qualified": int(unqualified or 0),
    }

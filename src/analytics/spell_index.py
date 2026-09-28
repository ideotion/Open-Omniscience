"""The "did you mean" table: a SymSpell-shaped deletion neighbourhood (S05-01 S6, Q605 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS SHAPE (the 2026-09-09 docket entry, ruled 2026-09-15). The keyword table holds
~400k terms on a real corpus, and its only index is a B-tree on ``normalized_term`` --
useless for edit distance. A bounded Damerau-Levenshtein pass over it is a 400k-row scan
per query word, which the search surfaces promise never to do. SymSpell turns the problem
around: precompute, for every vocabulary word, the strings reachable by deleting up to
two characters; a misspelt word then generates ITS deletes and meets its correction on a
shared delete (``climte`` and ``climate`` both reach ``climte``). A lookup is a handful of
primary-key probes, whatever the corpus size.

WHAT IS IN THE TABLE, and what is left out on purpose:

* Only single-word keywords of letters, 3 to 40 characters -- a suggestion is a WORD.
* Only keywords seen in at least :data:`MIN_ARTICLES` articles. On a real corpus most
  keywords occur in one article (the "71 % single-article tail" the scale generator
  models), and a word the corpus used once is a poor thing to suggest as the spelling
  someone meant; it also keeps the table a fraction of the size.
* Deletes of the first :data:`PREFIX_LEN` characters only (SymSpell's prefix
  optimisation). It does not lose corrections: a typo past the prefix leaves the prefix
  intact, the candidate is still found, and the true distance is checked on the whole
  word afterwards. It only makes the candidate lists longer for common prefixes.

HONESTY RAILS: a suggestion is OFFERED beside the literal results, never substituted
(the query the reader typed is the query that ran); each carries its edit distance and
the number of articles the suggested word occurs in; and the whole block carries the
build time, because a keyword collected after the build is invisible until the next one.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime

from sqlalchemy import text

_LOG = logging.getLogger(__name__)

#: SymSpell's maximum edit distance. Two catches the common slips (one wrong, one
#: missing, two adjacent swapped) without drowning a short word in unrelated neighbours.
MAX_DISTANCE = 2
#: Only the first PREFIX_LEN characters generate deletes (see the module docstring).
PREFIX_LEN = 7
#: A keyword must occur in at least this many articles to be suggested.
MIN_ARTICLES = 3
#: Suggestions per misspelt word, and misspelt words looked at per query.
MAX_SUGGESTIONS = 3
MAX_TERMS = 5
#: Words this short get distance 1 at most: at 2, a four-letter word is two edits from
#: a large share of the vocabulary, and the suggestions stop meaning anything.
SHORT_WORD = 4

_WORD = re.compile(r"^[^\W\d_]{3,40}$", re.UNICODE)
_KV_KEY = "search.spell_index"
_TABLE = "spell_deletes"
_BUILD = "spell_deletes_build"
_CHUNK = 2000

CAVEAT = (
    "Suggestions come from your corpus' own keywords, as they stood when the suggestion "
    "table was last built. A word collected since then is not suggested until it is "
    "rebuilt. Your query ran exactly as you typed it."
)


def deletes(word: str, max_distance: int = MAX_DISTANCE, prefix_len: int = PREFIX_LEN) -> set[str]:
    """Every string reachable from ``word``'s prefix by deleting up to ``max_distance``
    characters, the prefix itself included."""
    key = word[:prefix_len]
    out = {key}
    frontier = {key}
    for _ in range(max_distance):
        nxt: set[str] = set()
        for w in frontier:
            if len(w) <= 1:
                continue
            for i in range(len(w)):
                d = w[:i] + w[i + 1:]
                if d not in out:
                    nxt.add(d)
        out |= nxt
        frontier = nxt
    return out


def distance(a: str, b: str, limit: int = MAX_DISTANCE) -> int:
    """Optimal-string-alignment Damerau-Levenshtein distance, ``limit + 1`` when over."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[len(b)] if prev[len(b)] <= limit else limit + 1


def _limit_for(word: str) -> int:
    return 1 if len(word) <= SHORT_WORD else MAX_DISTANCE


# --------------------------------------------------------------------------- #
# The build (a task-manager job)
# --------------------------------------------------------------------------- #


def _vocabulary(session) -> list[tuple[int, str]]:
    """(keyword id, normalised term) for every suggestible keyword."""
    rows = session.execute(
        text(
            "SELECT k.id, k.normalized_term FROM keywords k "
            "JOIN (SELECT keyword_id, COUNT(*) AS n FROM keyword_mentions "
            "GROUP BY keyword_id HAVING COUNT(*) >= :min) m ON m.keyword_id = k.id "
            "WHERE k.is_ngram IS NOT 1"
        ),
        {"min": MIN_ARTICLES},
    ).fetchall()
    return [(int(i), t) for i, t in rows if t and _WORD.match(t)]


def build(ctx=None, *, session_factory=None) -> dict:
    """Rebuild the table whole. Writes a staging table in committed chunks (the writer
    gate is taken per chunk, never across the build), then swaps it in with one short
    transaction, so a search during the build reads the previous table, never half of one.
    Returns the measured cost: keywords, rows, seconds, bytes (when the store reports it).
    """
    from src.config.kv_store import kv_set_json

    if session_factory is None:
        from src.database.session import session_scope as session_factory
    t0 = time.monotonic()
    with session_factory() as s:
        vocab = _vocabulary(s)
    total = len(vocab)
    if ctx is not None:
        ctx.set_progress(done=0, total=total, detail="Building the did-you-mean table")
    with session_factory() as s:
        s.execute(text(f"DROP TABLE IF EXISTS {_BUILD}"))  # nosec B608 - constant table name
        s.execute(text(
            f"CREATE TABLE {_BUILD} (term_delete VARCHAR(64) NOT NULL, "  # nosec B608 - constant table name
            "keyword_id INTEGER NOT NULL, PRIMARY KEY (term_delete, keyword_id)) WITHOUT ROWID"
        ))
    rows = 0
    for start in range(0, total, _CHUNK):
        if ctx is not None and ctx.stopping:
            with session_factory() as s:
                s.execute(text(f"DROP TABLE IF EXISTS {_BUILD}"))  # nosec B608 - constant table name
            return {"state": "cancelled", "keywords": start, "rows": rows}
        batch: list[dict] = []
        for kid, term in vocab[start:start + _CHUNK]:
            for d in deletes(term, _limit_for(term)):
                batch.append({"d": d[:64], "k": kid})
        with session_factory() as s:
            s.execute(
                text(f"INSERT OR IGNORE INTO {_BUILD} (term_delete, keyword_id) VALUES (:d, :k)"),  # nosec B608 - constant table name
                batch,
            )
        rows += len(batch)
        if ctx is not None:
            ctx.set_progress(done=min(total, start + _CHUNK), total=total)
    with session_factory() as s:
        s.execute(text(f"DROP TABLE IF EXISTS {_TABLE}"))  # nosec B608 - constant table name
        s.execute(text(f"ALTER TABLE {_BUILD} RENAME TO {_TABLE}"))  # nosec B608 - constant table names
        stored = int(s.execute(text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar() or 0)  # nosec B608 - constant table name
        size = _table_bytes(s)
    seconds = round(time.monotonic() - t0, 2)
    meta = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "keywords": total,
        "rows": stored,
        "seconds": seconds,
        "bytes": size,
        "min_articles": MIN_ARTICLES,
        "prefix_len": PREFIX_LEN,
        "max_distance": MAX_DISTANCE,
    }
    try:
        kv_set_json(_KV_KEY, meta)
    except Exception:  # noqa: BLE001 - the table is built; the note about it is best-effort
        _LOG.warning("could not record the did-you-mean build note", exc_info=True)
    return {"state": "done", **meta}


def _table_bytes(session) -> int | None:
    """The table's on-disk size via ``dbstat`` when this SQLite has it, else None."""
    try:
        v = session.execute(
            text("SELECT SUM(pgsize) FROM dbstat WHERE name = :t"), {"t": _TABLE}
        ).scalar()
        return int(v) if v is not None else None
    except Exception:  # noqa: BLE001 - dbstat is a compile-time option; absent -> unmeasured
        return None


def status() -> dict:
    """The last build's note, or ``{"built": False}``."""
    from src.config.kv_store import kv_get_json

    meta = kv_get_json(_KV_KEY) or {}
    return {"built": bool(meta), **meta, "caveat": CAVEAT}


# --------------------------------------------------------------------------- #
# The lookup
# --------------------------------------------------------------------------- #


def suggest(session, word: str) -> list[dict]:
    """Up to :data:`MAX_SUGGESTIONS` corrections of ``word``, nearest first, then most
    articles. ``[]`` when the word is itself a known keyword, when nothing is within reach,
    or when the table has never been built."""
    from src.database.fts_norm import search_fold

    w = (search_fold(word) or "").strip()
    if not _WORD.match(w):
        return []
    try:
        known = session.execute(
            text("SELECT 1 FROM keywords WHERE normalized_term = :t LIMIT 1"), {"t": w}
        ).fetchone()
    except Exception:  # noqa: BLE001 - no keyword table: nothing to suggest from
        return []
    if known:
        return []
    limit = _limit_for(w)
    probes = sorted(deletes(w, limit))
    cand: dict[int, str] = {}
    try:
        for i in range(0, len(probes), 400):
            chunk = probes[i:i + 400]
            params = {f"p{j}": v for j, v in enumerate(chunk)}
            marks = ", ".join(f":p{j}" for j in range(len(chunk)))
            for kid, term in session.execute(
                text(
                    "SELECT DISTINCT k.id, k.normalized_term FROM spell_deletes d "  # nosec B608 - only generated :pN placeholders are interpolated
                    f"JOIN keywords k ON k.id = d.keyword_id WHERE d.term_delete IN ({marks})"
                ),
                params,
            ):
                cand[int(kid)] = term
    except Exception:  # noqa: BLE001 - the table does not exist yet (never built)
        return []
    scored = []
    for kid, term in cand.items():
        dist = distance(w, term, limit)
        if 0 < dist <= limit:
            scored.append((dist, kid, term))
    if not scored:
        return []
    ids = [kid for _d, kid, _t in scored]
    counts: dict[int, int] = {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        params = {f"i{j}": v for j, v in enumerate(chunk)}
        marks = ", ".join(f":i{j}" for j in range(len(chunk)))
        for kid, n in session.execute(
            text(
                "SELECT keyword_id, COUNT(*) FROM keyword_mentions "  # nosec B608 - only generated :iN placeholders are interpolated
                f"WHERE keyword_id IN ({marks}) GROUP BY keyword_id"
            ),
            params,
        ):
            counts[int(kid)] = int(n)
    scored.sort(key=lambda r: (r[0], -counts.get(r[1], 0), r[2]))
    return [
        {"term": term, "distance": dist, "articles": counts.get(kid, 0)}
        for dist, kid, term in scored[:MAX_SUGGESTIONS]
    ]


def query_words(query: str | None) -> list[str]:
    """The plain words of a query worth checking: its positive terms, in order."""
    from src.database.fts import SearchQueryError, _AndGroup, _Or, _Term, parse_query

    try:
        parsed = parse_query(query, grammar=True)
    except SearchQueryError:
        return []
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, _Term):
            for w in node.value.split():
                if w not in out:
                    out.append(w)
        elif isinstance(node, _Or):
            for c in node.children:
                walk(c)
        elif isinstance(node, _AndGroup):
            for c in node.includes:
                walk(c)

    walk(parsed.ast)
    return out[:MAX_TERMS]


def did_you_mean(session, query: str | None) -> dict | None:
    """The disclosure block for ``/api/articles``, or ``None`` when there is nothing to
    offer. ``query`` is the suggested whole query -- each misspelt word replaced by its
    nearest suggestion -- for the reader to click; it is never run on their behalf."""
    words = query_words(query)
    if not words:
        return None
    found = []
    for w in words:
        sug = suggest(session, w)
        if sug:
            found.append({"term": w, "suggestions": sug})
    if not found:
        return None
    suggested = query or ""
    for f in found:
        suggested = re.sub(
            r"(?<![\w])" + re.escape(f["term"]) + r"(?![\w])",
            f["suggestions"][0]["term"],
            suggested,
            count=1,
        )
    st = status()
    return {
        "terms": found,
        "query": suggested,
        "built_at": st.get("built_at"),
        "caveat": CAVEAT,
        "method": (
            f"Words within {MAX_DISTANCE} edits (1 for words of {SHORT_WORD} letters or "
            f"fewer) among your keywords seen in at least {MIN_ARTICLES} articles; nearest "
            "first, then the one in more articles."
        ),
    }


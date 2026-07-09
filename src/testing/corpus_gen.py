"""
Synthetic corpus generator (scale harness G1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Write a REAL app-schema SQLite corpus of a target size so scale cliffs are found
in dev, not in the field. The schema is created from ``Base.metadata`` (never a
hand-copy), so it can NEVER drift from the models; the FTS5 index is built with
the app's own ``ensure_fts``; keyword counters are the app's own denormalised
columns; the hot mention/keyword indexes are exactly the model's. What is left
UNBUILT on purpose is the ONE index the app self-heals at unlock -- the
``coalesce(published_at, created_at)`` expression index (``ix_article_observed``,
not on any ORM model) -- so the benchmark's cold-unlock phase reproduces the
field's 735 s index-build cost instead of measuring a no-op.

Distributions are grounded in the live 2026-07-09 field numbers:
    268,241 articles / 3.06 M keywords / 20.9 M mentions / 11.7 GB
    => ~78 distinct keywords (mentions) per article, ~11 keywords per article
       shared across the corpus, and 71 % of keywords appear in exactly ONE
       article (the long single-article tail the segmenter ruling keeps citing).
The generator reproduces that shape: a bounded, Zipf-weighted HEAD pool of shared
"common" keywords plus a per-article set of FRESH single-article TAIL keywords.

HONESTY BY CONSTRUCTION:
  * Every generated corpus carries a VISIBLE synthetic marker -- an ``app_state``
    row (survives a backup/restore) AND a distinctive SQLite ``application_id``
    (survives a raw file copy) -- so it can never be mistaken for real user data.
    :func:`is_synthetic` reads the marker back.
  * Generation NEVER reads the wall clock (``end_date`` is an explicit spec field,
    default fixed) and draws every random value from ONE seeded RNG in a fixed
    order, so ``(spec) -> corpus`` is byte-reproducible for a fixed article count.
  * Nothing here reaches the network; it computes no scores or quality signals --
    it only fabricates plausible SHAPES to stress the storage/query layer.

Offline generation into a NEW db path is the primary mode. It uses its own
engine + a dedicated raw connection (NOT ``SessionLocal``), so it does not touch
the app's module engine or the single-writer gate; do not point it at a live
corpus while the app is running.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import event, insert
from sqlalchemy.engine import Engine

_LOG = logging.getLogger("testing.corpus_gen")

# --------------------------------------------------------------------------- #
# Synthetic markers (this corpus is NOT real data -- stated two ways)
# --------------------------------------------------------------------------- #
SYNTHETIC_MARKER_KEY = "__synthetic_corpus__"
# A distinctive, non-zero value in the SQLite header's application_id slot (the
# app never sets or reads it). Survives a raw file copy; the app_state row below
# survives a logical backup/restore, so the flag is redundant on purpose.
SYNTHETIC_APPLICATION_ID = 0x004F_053C  # "OO" scale marker
GENERATOR_VERSION = "1"

# A fixed spread end so a library/test run is reproducible without the wall clock.
# The CLI overrides this with "today" so the recent-window endpoints (trending)
# actually have in-range rows to scan.
DEFAULT_END_DATE = date(2026, 7, 1)

# A small, weighted language/country mix (de-US-centred, like the real catalog).
_LANG_COUNTRY: tuple[tuple[str, str, int], ...] = (
    ("en", "us", 20),
    ("en", "gb", 10),
    ("fr", "fr", 10),
    ("de", "de", 9),
    ("es", "es", 8),
    ("pt", "br", 7),
    ("ru", "ru", 6),
    ("ar", "eg", 5),
    ("zh", "cn", 6),
    ("ja", "jp", 5),
    ("hi", "in", 5),
    ("id", "id", 4),
    ("sv", "se", 3),
    ("el", "gr", 2),
)

# Syllable alphabet for a bijective int -> pronounceable word encoding, so N
# distinct keyword/word ids yield N distinct word-like terms deterministically.
_SYLL = (
    "ba", "be", "bi", "bo", "ka", "ke", "ki", "ko", "da", "de", "di", "do",
    "ra", "re", "ri", "ro", "mi", "mo", "na", "ne", "sa", "se", "ta", "to",
    "la", "le", "lo", "va", "ve", "vi", "za", "zo",
)  # 32 syllables


def _word_from_int(n: int) -> str:
    """Bijective, deterministic ``int -> pronounceable word`` (base-32 syllables)."""
    if n < 0:
        raise ValueError("word index must be non-negative")
    out = _SYLL[n % len(_SYLL)]
    n //= len(_SYLL)
    while n > 0:
        out += _SYLL[n % len(_SYLL)]
        n //= len(_SYLL)
    return out


# --------------------------------------------------------------------------- #
# Spec
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CorpusSpec:
    """Parameters for a synthetic corpus. Set EITHER ``articles`` (exact count,
    fully reproducible) OR ``target_bytes`` (grow batches until the db file
    reaches ~the target; ``articles`` then acts as a hard cap). Defaults are
    grounded in the live 2026-07-09 field ratios; scale them down for CI."""

    articles: int | None = None
    target_bytes: int | None = None
    seed: int = 1729
    sources: int = 200
    mentions_per_article: int = 78          # ~= 20.9 M mentions / 268 K articles
    fresh_keywords_per_article: int = 8     # the single-article TAIL (drives the 71 %)
    head_pool: int = 40_000                 # bounded shared "common" vocabulary
    zipf_exponent: float = 2.0              # head-frequency skew (a few very hot terms)
    content_words: int = 220                # ~= the ~190-content-words/article anchor
    time_span_days: int = 365
    end_date: date = DEFAULT_END_DATE
    passphrase: str | None = None           # None -> plaintext store
    batch_articles: int = 2000
    max_articles: int = 60_000_000          # runaway backstop for target_bytes runs

    def validate(self) -> None:
        if self.articles is None and self.target_bytes is None:
            raise ValueError("CorpusSpec needs either `articles` or `target_bytes`")
        if self.articles is not None and self.articles <= 0:
            raise ValueError("articles must be > 0")
        if self.target_bytes is not None and self.target_bytes <= 0:
            raise ValueError("target_bytes must be > 0")
        if self.sources <= 0:
            raise ValueError("sources must be > 0")
        if self.mentions_per_article < 1:
            raise ValueError("mentions_per_article must be >= 1")
        if self.fresh_keywords_per_article < 0:
            raise ValueError("fresh_keywords_per_article must be >= 0")
        if self.fresh_keywords_per_article > self.mentions_per_article:
            raise ValueError("fresh_keywords_per_article cannot exceed mentions_per_article")
        if self.head_pool < 1:
            raise ValueError("head_pool must be >= 1")
        if self.batch_articles < 1:
            raise ValueError("batch_articles must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "articles": self.articles,
            "target_bytes": self.target_bytes,
            "seed": self.seed,
            "sources": self.sources,
            "mentions_per_article": self.mentions_per_article,
            "fresh_keywords_per_article": self.fresh_keywords_per_article,
            "head_pool": self.head_pool,
            "zipf_exponent": self.zipf_exponent,
            "content_words": self.content_words,
            "time_span_days": self.time_span_days,
            "end_date": self.end_date.isoformat(),
            "encrypted": self.passphrase is not None,
            "batch_articles": self.batch_articles,
        }


# --------------------------------------------------------------------------- #
# Engine (own, NOT SessionLocal) with bulk-load PRAGMAs
# --------------------------------------------------------------------------- #
def _build_engine(db_path: Path, passphrase: str | None) -> Engine:
    """A dedicated engine on ``db_path`` via the app's ONE connection factory.

    Bulk-load PRAGMAs (WAL, synchronous=OFF, foreign_keys=OFF, big cache) are set
    per connection -- FK integrity is guaranteed by construction (keywords +
    articles are inserted before the mentions that reference them), and
    synchronous=OFF is safe because a crashed offline generation just re-runs.
    """
    from sqlalchemy import create_engine

    from src.database.connect import connect

    def _creator() -> Any:
        if passphrase is not None:
            return connect(str(db_path), key=passphrase, check_same_thread=False, timeout=60)
        return connect(str(db_path), create_encrypted=False, check_same_thread=False, timeout=60)

    engine = create_engine(f"sqlite:///{db_path}", future=True, creator=_creator)

    @event.listens_for(engine, "connect")
    def _bulk_pragmas(dbapi_conn: Any, _rec: Any) -> None:  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=OFF")
            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA cache_size=-131072")  # 128 MiB
        finally:
            cur.close()

    return engine


def _db_size(db_path: Path) -> int:
    """Bytes on disk for the main file + its WAL side file (progress measure)."""
    total = db_path.stat().st_size if db_path.exists() else 0
    wal = db_path.with_name(db_path.name + "-wal")
    if wal.exists():
        total += wal.stat().st_size
    return total


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
@dataclass
class _State:
    """Bounded, streaming generation state (only the HEAD counters are held)."""

    head_mentions: list[int]
    head_articles: list[int]
    tail_next_id: int
    articles_written: int = 0
    mentions_written: int = 0
    tail_keywords: int = 0
    word_pool: list[str] = field(default_factory=list)


def generate_corpus(db_path: str | Path, spec: CorpusSpec) -> dict[str, Any]:
    """Generate a synthetic corpus at ``db_path`` per ``spec``. Returns a summary.

    Raises ``FileExistsError`` if the file already exists (never overwrites) and
    ``ValueError`` on an invalid spec.
    """
    spec.validate()
    path = Path(db_path)
    if path.exists():
        raise FileExistsError(f"{path} already exists (the generator never overwrites)")
    path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    engine = _build_engine(path, spec.passphrase)
    try:
        _create_schema(engine)
        # Build the FTS vtable + sync triggers BEFORE filling, so every article
        # insert indexes incrementally. This keeps the size measured DURING a
        # target-size run equal to the final on-disk footprint (an FTS index built
        # in one pass at the end would add a post-loop jump that overshoots target).
        _build_fts(engine)
        summary = _fill(engine, path, spec)
        _write_marker(engine, path, spec, summary)
        _checkpoint(engine)
    finally:
        engine.dispose()

    summary["bytes"] = _db_size(path)
    summary["duration_s"] = round(time.perf_counter() - t0, 3)
    summary["path"] = str(path)
    summary["synthetic"] = True
    _LOG.info("generated synthetic corpus: %s", json.dumps(summary))
    return summary


def _create_schema(engine: Engine) -> None:
    """Create every table from ``Base.metadata`` (never a hand-copy) + tag the
    header ``application_id`` as synthetic. The FTS vtable/triggers and the
    ``ix_article_observed`` expression index are deliberately left for later."""
    from sqlalchemy import text

    from src.database.models import Base

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA application_id = {SYNTHETIC_APPLICATION_ID}"))


def _fill(engine: Engine, path: Path, spec: CorpusSpec) -> dict[str, Any]:
    """Insert sources, then stream article + keyword + mention batches."""
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.utils.url_utils import CANON_VERSION, CONTENT_HASH_ALGO

    rng = random.Random(spec.seed)

    # A word pool that OVERLAPS the head-keyword terms, so article content is
    # searchable for the common terms (FTS realism). Bounded and deterministic.
    pool_n = min(spec.head_pool, 4000)
    word_pool = [_word_from_int(i) for i in range(pool_n)]

    # Sources (bounded, inserted once).
    langs = _weighted_langs(spec.sources, rng)
    source_rows: list[dict[str, Any]] = []
    for sid in range(1, spec.sources + 1):
        lang, country = langs[sid - 1]
        source_rows.append(
            {
                "id": sid,
                "name": f"Synthetic Source {sid}",
                "domain": f"src{sid:05d}.synthetic.example",
                "rss_url": f"https://src{sid:05d}.synthetic.example/feed.xml",
                "enabled": True,
                "priority": 2,
                "tags": _source_tags(sid),
                "language": lang,
                "region": "global",
                "country": country,
                "source_type": _source_type(sid),
            }
        )
    with engine.begin() as conn:
        conn.execute(insert(Source), source_rows)

    st = _State(
        head_mentions=[0] * (spec.head_pool + 1),
        head_articles=[0] * (spec.head_pool + 1),
        tail_next_id=spec.head_pool + 1,
        word_pool=word_pool,
    )

    target = spec.target_bytes
    hard_cap = spec.articles if spec.articles is not None else spec.max_articles
    aid = 0
    while st.articles_written < hard_cap:
        remaining = hard_cap - st.articles_written
        batch_n = min(spec.batch_articles, remaining)
        article_rows: list[dict[str, Any]] = []
        keyword_rows: list[dict[str, Any]] = []
        mention_rows: list[dict[str, Any]] = []
        for _ in range(batch_n):
            aid += 1
            src_id = rng.randint(1, spec.sources)
            lang, country = langs[src_id - 1]
            published = _published_at(spec, aid, hard_cap, rng)
            created = published + timedelta(hours=rng.randint(0, 12))
            kw_ids, counts = _keywords_for_article(spec, rng, st, keyword_rows, lang)
            content = _content(spec, rng, st.word_pool, kw_ids, spec.head_pool)
            digest = hashlib.sha256(f"{spec.seed}:{aid}".encode()).hexdigest()
            article_rows.append(
                {
                    "id": aid,
                    "url": f"https://src{src_id:05d}.synthetic.example/a/{aid}",
                    "canonical_url": f"https://src{src_id:05d}.synthetic.example/a/{aid}",
                    "source_id": src_id,
                    "title": _title(rng, st.word_pool),
                    "content": content,
                    "published_at": published,
                    "created_at": created,
                    "language": lang,
                    "country": country,
                    "region": "global",
                    "word_count": content.count(" ") + 1,
                    "hash": digest,
                    "content_multihash": f"{CONTENT_HASH_ALGO}:{digest}",
                    "canon_version": CANON_VERSION,
                }
            )
            obs = published.date()
            for kw_id, cnt in zip(kw_ids, counts, strict=True):
                mention_rows.append(
                    {
                        "keyword_id": kw_id,
                        "article_id": aid,
                        "count": cnt,
                        "first_offset": 0,
                        "observed_on": obs,
                        "country": country,
                        "source_id": src_id,
                        "extractor": "synthetic",
                    }
                )
            st.mentions_written += len(kw_ids)
        with engine.begin() as conn:
            if keyword_rows:
                conn.execute(insert(Keyword), keyword_rows)
            conn.execute(insert(Article), article_rows)
            conn.execute(insert(KeywordMention), mention_rows)
        st.articles_written += batch_n
        st.tail_keywords += len(keyword_rows)
        if target is not None:
            # Fold the WAL into the main file before measuring, so the progress
            # size reflects the COMPACTED on-disk footprint (an uncheckpointed WAL
            # under synchronous=OFF is far larger than the final size, which would
            # stop generation well short of the target).
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            if path.stat().st_size >= target:
                break
        if spec.articles is not None and st.articles_written >= spec.articles:
            break

    # Insert the HEAD keyword rows -- ONLY those an article actually used (a
    # keyword with zero mentions would be an orphan the real pipeline never
    # creates), with their EXACT in-memory counters (no corpus scan).
    used_head = 0
    head_single = 0
    head_rows: list[dict[str, Any]] = []
    for hid in range(1, spec.head_pool + 1):
        arts = st.head_articles[hid]
        if arts == 0:
            continue
        used_head += 1
        if arts == 1:
            head_single += 1
        term = _word_from_int(hid)
        head_rows.append(
            {
                "id": hid,
                "term": term,
                "normalized_term": term,
                "language": _LANG_COUNTRY[(hid * 2654435761) % len(_LANG_COUNTRY)][0],
                "frequency": 0,
                "is_entity": False,
                "ngram_size": 1,
                "extractor": "synthetic",
                "mention_count": st.head_mentions[hid],
                "article_count": arts,
            }
        )
        if len(head_rows) >= 10_000:
            with engine.begin() as conn:
                conn.execute(insert(Keyword), head_rows)
            head_rows = []
    if head_rows:
        with engine.begin() as conn:
            conn.execute(insert(Keyword), head_rows)

    single_article = st.tail_keywords + head_single
    total_keywords = used_head + st.tail_keywords
    return {
        "articles": st.articles_written,
        "sources": spec.sources,
        "keywords": total_keywords,
        "head_keywords": used_head,
        "tail_keywords": st.tail_keywords,
        "mentions": st.mentions_written,
        "single_article_keywords": single_article,
        "single_article_fraction": round(single_article / total_keywords, 4)
        if total_keywords
        else 0.0,
        "seed": spec.seed,
        "spec": spec.to_dict(),
    }


def _keywords_for_article(
    spec: CorpusSpec,
    rng: random.Random,
    st: _State,
    keyword_rows: list[dict[str, Any]],
    lang: str,
) -> tuple[list[int], list[int]]:
    """Pick this article's keyword ids + per-mention counts. Head keywords are
    sampled distinct with a Zipf skew (a few very hot terms); tail keywords are
    fresh, single-article, appended to ``keyword_rows`` for this batch's insert."""
    n_total = spec.mentions_per_article
    n_fresh = min(spec.fresh_keywords_per_article, n_total)
    n_head = n_total - n_fresh

    kw_ids: list[int] = []
    counts: list[int] = []
    picked: set[int] = set()
    attempts = 0
    while len(picked) < n_head and attempts < n_head * 6:
        attempts += 1
        # Skew toward low ids (id 1 hottest) via a power transform.
        hid = 1 + int(spec.head_pool * (rng.random() ** spec.zipf_exponent))
        if hid > spec.head_pool:
            hid = spec.head_pool
        if hid in picked:
            continue
        picked.add(hid)
        cnt = 1 + int(rng.random() ** 2 * 5)  # 1..5, mostly 1-2
        kw_ids.append(hid)
        counts.append(cnt)
        st.head_mentions[hid] += cnt
        st.head_articles[hid] += 1

    for _ in range(n_fresh):
        tid = st.tail_next_id
        st.tail_next_id += 1
        cnt = 1 + int(rng.random() ** 2 * 3)  # 1..3
        term = _word_from_int(tid)
        keyword_rows.append(
            {
                "id": tid,
                "term": term,
                "normalized_term": term,
                "language": lang,
                "frequency": 0,
                "is_entity": False,
                "ngram_size": 1,
                "extractor": "synthetic",
                "mention_count": cnt,   # single mention
                "article_count": 1,     # single article, by construction
            }
        )
        kw_ids.append(tid)
        counts.append(cnt)

    return kw_ids, counts


def _build_fts(engine: Engine) -> None:
    """Create the FTS5 vtable + sync triggers with the app's own helper (called
    BEFORE the fill, so inserts index incrementally via the triggers)."""
    from src.database.fts import ensure_fts

    ensure_fts(engine)


def _write_marker(
    engine: Engine, path: Path, spec: CorpusSpec, summary: dict[str, Any]
) -> None:
    """Write the visible synthetic marker row into ``app_state``."""
    from src.database.models import AppState

    value = json.dumps(
        {
            "synthetic": True,
            "generator": "src.testing.corpus_gen",
            "generator_version": GENERATOR_VERSION,
            "warning": "SYNTHETIC benchmark corpus -- fabricated data, not real. "
            "Do not treat as a real corpus.",
            "seed": spec.seed,
            "spec": spec.to_dict(),
            "articles": summary.get("articles"),
            "keywords": summary.get("keywords"),
            "mentions": summary.get("mentions"),
        },
        ensure_ascii=False,
    )
    # A fixed timestamp (no wall clock): the spec's end_date at midnight UTC.
    stamp = datetime(spec.end_date.year, spec.end_date.month, spec.end_date.day, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(AppState), [{"key": SYNTHETIC_MARKER_KEY, "value": value, "updated_at": stamp}]
        )


def _checkpoint(engine: Engine) -> None:
    """Fold the WAL back into the main file so the on-disk size is accurate and
    the corpus is in a clean, single-file state.

    Deliberately does NOT run ``PRAGMA optimize``/``ANALYZE``: a freshly bulk-loaded
    corpus has no query-planner statistics yet, exactly like the field's cold store.
    Building them is part of the app's unlock (``optimize_at_boot``), so the bench's
    cold-unlock phase measures that cost instead of finding it pre-baked."""
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")


# --------------------------------------------------------------------------- #
# Content helpers
# --------------------------------------------------------------------------- #
def _weighted_langs(n: int, rng: random.Random) -> list[tuple[str, str]]:
    """A deterministic weighted (language, country) assignment for n sources."""
    bag: list[tuple[str, str]] = []
    for lang, country, weight in _LANG_COUNTRY:
        bag.extend([(lang, country)] * weight)
    return [bag[rng.randrange(len(bag))] for _ in range(n)]


def _source_tags(sid: int) -> str:
    tags = ("news", "investigative", "science", "financial", "state-media", "history")
    return ",".join({tags[sid % len(tags)], tags[(sid // 3) % len(tags)]})


def _source_type(sid: int) -> str:
    types = ("news", "financial", "scientific", "statistics", "newsletter")
    return types[sid % len(types)]


def _published_at(spec: CorpusSpec, aid: int, total: int, rng: random.Random) -> datetime:
    """Spread articles across [end_date - time_span_days, end_date]. Weighted
    toward recent so the recent-window endpoints have rows to scan."""
    end = datetime(spec.end_date.year, spec.end_date.month, spec.end_date.day, tzinfo=UTC)
    # sqrt weighting -> denser near the end (recent), like a growing live corpus.
    frac = rng.random() ** 0.5
    days_back = int(spec.time_span_days * (1.0 - frac))
    seconds = rng.randint(0, 86_399)
    return end - timedelta(days=days_back, seconds=seconds)


def _content(
    spec: CorpusSpec,
    rng: random.Random,
    word_pool: list[str],
    kw_ids: list[int],
    head_pool: int,
) -> str:
    """Article body: filler words interleaved with this article's HEAD keyword
    terms (so FTS MATCH finds the common terms). Tail terms are omitted from the
    pool but appended, keeping the body searchable + realistic."""
    n = max(20, spec.content_words)
    words = [word_pool[rng.randrange(len(word_pool))] for _ in range(n)]
    # Sprinkle the head keyword terms into the body at deterministic positions.
    head_terms = [_word_from_int(k) for k in kw_ids if k <= head_pool]
    for i, term in enumerate(head_terms):
        pos = (i * 7 + 3) % n
        words[pos] = term
    return " ".join(words)


def _title(rng: random.Random, word_pool: list[str]) -> str:
    return " ".join(word_pool[rng.randrange(len(word_pool))] for _ in range(rng.randint(4, 9)))


# --------------------------------------------------------------------------- #
# Honesty check: read the synthetic marker back
# --------------------------------------------------------------------------- #
def is_synthetic(db_path: str | Path, passphrase: str | None = None) -> dict[str, Any] | None:
    """Return the parsed synthetic marker for ``db_path``, or ``None`` if the file
    carries no synthetic marker (i.e. it is -- or claims to be -- a real corpus).

    Reads through the app's ONE connection factory (handles plaintext or
    SQLCipher). Never raises on a missing table/row; returns ``None`` instead.
    """
    from src.database.connect import connect

    path = Path(db_path)
    if not path.exists():
        return None
    # is_synthetic is a POSITIVE flag: anything that stops us reading the marker
    # (a non-OO/garbage file, an encrypted file without the right passphrase, a
    # missing app_state table) means "not proven synthetic" -> None, NEVER a crash.
    try:
        conn = connect(str(path), key=passphrase, check_same_thread=False)
    except Exception:  # noqa: BLE001 - can't open -> can't prove synthetic
        return None
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT value FROM app_state WHERE key = ?", (SYNTHETIC_MARKER_KEY,)
            )
            row = cur.fetchone()
        except Exception:  # noqa: BLE001 - no app_state table / read error
            return None
        finally:
            cur.close()
    finally:
        conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None

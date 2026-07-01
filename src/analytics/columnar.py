"""
Derived columnar read-model engine (DuckDB) — bring-up + encryption gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Data-architecture build Slice 4, PR-1 (engine bring-up). This is the optional DuckDB
accelerator behind the A1 read-model seam (``src/analytics/readmodel.py``). It is a
**disposable, rebuildable cache** — the encrypted SQLCipher store is ALWAYS the source
of truth; a missing / cold / unavailable columnar store means the seam serves the live
SQLite query (slower, never wrong). PR-1 establishes the engine + the encryption gate +
the offline guarantee; the endpoint port (reading aggregations from here) is PR-2/3.

Three hard rules, all enforced in code (maintainer ruling 2026-06-19):

1. **Encrypted under the SAME passphrase, or in-memory — never plaintext on disk.**
   The persisted file at ``data_dir()/analytics.duckdb`` is opened with DuckDB's AES
   ``ENCRYPTION_KEY`` derived deterministically from the ONE corpus passphrase (no
   second secret for the user to manage — :func:`_derive_key`). A persisted file is
   used ONLY after :func:`encryption_gate` empirically proves it is really encrypted. If
   a SECURE crypto backend is not available offline (see below), the engine falls back
   to **DuckDB in-memory** and writes NO file — never a plaintext derived store.

2. **Fully offline.** Opened with extension autoload/autoinstall DISABLED and external
   access OFF, so opening the engine makes zero network calls (the airplane socket guard
   is the net beneath this; here we simply never reach for the network).

3. **No fabricated security.** DuckDB's built-in mbedtls crypto is documented by DuckDB
   itself as "NOT securely encrypted"; we NEVER trust it for the derived store
   (:func:`secure_crypto_available` requires the OpenSSL/httpfs backend). Trusting the
   unsafe backend would be exactly the lock-screen-over-plaintext theatre the project
   forbids — so when only the unsafe backend exists, we go in-memory instead.

EMPIRICAL FINDING (recorded for the persistence decision): the stock ``duckdb`` PyPI
wheel does NOT bundle the OpenSSL crypto (``httpfs``) extension, and DuckDB autoloads it
from its network extension repository — which rule 2 forbids. So out of the box the
SECURE persisted store is unavailable offline and the engine runs IN-MEMORY. Enabling a
persisted encrypted store offline needs a per-OS ``httpfs`` extension bundled locally
(a packaging decision); the code is ready for it the moment ``secure_crypto_available()``
returns True. ``OO_COLUMNAR_DIR`` overrides the store directory; ``OO_COLUMNAR=0`` forces
the engine off (always live query).

VERIFY-FIRST OUTCOME — keyword-engine P2.4, tested on **DuckDB 1.5.4** (2026-06-25): the
hypothesis that DuckDB >=1.4 WRITES an authenticated-AES-256-GCM encrypted store NATIVELY
(without httpfs) is **REFUTED**. Writing an encrypted store still REQUIRES loading
``httpfs`` (OpenSSL): DuckDB 1.5.4 refuses the write with "DuckDB currently has a
read-only crypto module loaded. Please ensure httpfs is loaded using `LOAD httpfs` ... To
write an encrypted database ... that is NOT securely encrypted, one can use SET
force_mbedtls_unsafe = 'true'." The only no-httpfs write path is that explicitly-UNSAFE
mbedtls — exactly the fabricated-security the project forbids. So ``secure_crypto_available``
stays gated on httpfs; the gate is NOT relaxed; the engine stays IN-MEMORY until the per-OS
httpfs binaries are bundled (operational/packaging, networked machine). Separately, the
1.5.x ``enable_external_access=False`` in :func:`_offline_config` also blocks a FILE attach
outright — a second reason the persisted file path is unavailable under the strict offline
config; both are moot while httpfs is the gating blocker.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

# A unique token written into a probe store to PROVE the file is encrypted (the gate).
_SENTINEL = "OO_COLUMNAR_ENC_SENTINEL_b7f3"
_STORE_FILENAME = "analytics.duckdb"


def duckdb_available() -> bool:
    """True if the optional ``duckdb`` dependency is importable (else: live query)."""
    try:
        import duckdb  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return False


def _offline_config() -> dict:
    """DuckDB config that guarantees no network on open: extension autoload/autoinstall
    DISABLED and external access OFF. The columnar engine is local-first by construction.
    """
    return {
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "enable_external_access": False,
    }


def _derive_key(passphrase: str) -> str:
    """A DuckDB ENCRYPTION_KEY derived from the ONE corpus passphrase.

    NOT a second key surface: there is no second secret for the user to manage — the
    derived store rides the same passphrase as the canonical SQLCipher store. A hex
    digest avoids any SQL-literal-escaping hazard in the ``ENCRYPTION_KEY`` clause. The
    store is a disposable cache; this protects the same at-rest threat model.
    """
    return hashlib.sha256(("oo-columnar-v1:" + passphrase).encode("utf-8")).hexdigest()


def secure_crypto_available() -> bool:
    """True ONLY if a SECURE crypto backend (OpenSSL via ``httpfs``) can be loaded
    OFFLINE. DuckDB's built-in mbedtls is "NOT securely encrypted" and is never trusted
    for the derived store. When this is False the engine runs in-memory (no plaintext
    file is ever written). Pure check; opens and closes a throwaway in-memory connection.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return False
    import duckdb

    try:
        con = duckdb.connect(config=_offline_config())
        try:
            con.execute("LOAD httpfs")  # OpenSSL crypto; autoload is OFF so this is local-only
            return True
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - not loadable offline -> not available
        return False


def encryption_gate(path: str | Path, passphrase: str) -> bool:
    """Empirically PROVE a persisted DuckDB store is really encrypted (Slice 4 gate).

    The three checks the acceptance criteria require, run on a throwaway file at
    ``path``: (a) the sentinel is ABSENT from the raw file bytes, (b) opening WITHOUT the
    key FAILS, (c) opening WITH the key returns the sentinel. Returns True only if all
    three hold; cleans up the probe file. Any DuckDB error -> False (degrade loudly to
    in-memory, never assume encryption).
    """
    if not duckdb_available():
        return False
    import duckdb

    p = Path(path)
    key = _derive_key(passphrase)
    try:
        if p.exists():
            p.unlink()
        con = duckdb.connect(config=_offline_config())
        try:
            con.execute(f"ATTACH '{p.as_posix()}' AS g (ENCRYPTION_KEY '{key}')")
            con.execute("CREATE TABLE g.probe (s VARCHAR)")
            con.execute("INSERT INTO g.probe VALUES (?)", [_SENTINEL])
            con.execute("CHECKPOINT g")
        finally:
            con.close()
        # (a) sentinel must NOT appear in the raw bytes
        if _SENTINEL.encode("utf-8") in p.read_bytes():
            return False
        # (b) opening without the key must FAIL
        try:
            c2 = duckdb.connect(config=_offline_config())
            c2.execute(f"ATTACH '{p.as_posix()}' AS x")
            c2.execute("SELECT * FROM x.probe").fetchall()
            c2.close()
            return False  # opened without a key -> NOT encrypted
        except Exception:  # noqa: BLE001 - expected: encrypted store rejects no-key open
            pass
        # (c) opening with the key must return the sentinel
        c3 = duckdb.connect(config=_offline_config())
        try:
            c3.execute(f"ATTACH '{p.as_posix()}' AS y (ENCRYPTION_KEY '{key}')")
            got = c3.execute("SELECT s FROM y.probe").fetchone()
        finally:
            c3.close()
        return bool(got and got[0] == _SENTINEL)
    except Exception:  # noqa: BLE001
        _LOG.warning("columnar encryption gate raised; treating as unavailable", exc_info=True)
        return False
    finally:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _store_dir() -> Path:
    override = os.getenv("OO_COLUMNAR_DIR")
    if override:
        return Path(override)
    from src.paths import data_dir

    return Path(data_dir())


def status(passphrase: str | None = None) -> dict:
    """Honest disclosure of the engine's mode WITHOUT opening a real store.

    ``mode`` is one of: ``unavailable`` (duckdb absent / disabled), ``persisted``
    (a secure encrypted file is usable), or ``memory`` (in-memory fallback — secure
    persisted encryption is not available offline). Never claims encryption it cannot
    prove. ``as_of`` is set by the caller when it (re)builds the store, not here.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return {"available": False, "mode": "unavailable", "encrypted": False,
                "secure_crypto": False}
    secure = bool(passphrase) and secure_crypto_available()
    return {
        "available": True,
        "mode": "persisted" if secure else "memory",
        "encrypted": secure,
        "secure_crypto": secure_crypto_available(),
    }


def connect(passphrase: str | None = None):
    """Open the derived columnar engine — a persisted ENCRYPTED store when that is
    securely possible offline, else an in-memory store. NEVER a plaintext file on disk.

    Returns a DuckDB connection, or ``None`` when the engine is unavailable (duckdb
    absent / ``OO_COLUMNAR=0``) so the caller falls back to the live query. The returned
    connection's working schema lives in the attached encrypted database ``oo`` when
    persisted, or the default in-memory catalog when not.

    COMPATIBILITY: the store is DISPOSABLE. A persisted file written by an incompatible
    DuckDB (the on-disk format is version-bound) or an older read-model schema is detected
    via its format marker and REBUILT, and ANY open failure (corrupt / unreadable file)
    deletes the file and falls back to in-memory — never a crash, because the canonical
    SQLCipher store is always the source of truth.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return None
    import duckdb

    # Persisted-encrypted ONLY when a SECURE backend is available AND the gate proves it.
    if passphrase and secure_crypto_available():
        store_dir = _store_dir()
        path = store_dir / _STORE_FILENAME
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
            # Prove encryption on a throwaway probe before trusting the real file.
            if encryption_gate(store_dir / ".oo_columnar_probe.duckdb", passphrase):
                con = _attach_persisted(path, passphrase)
                marker = read_store_meta(con)
                if marker is None:
                    ensure_store_meta(con)  # a fresh store: adopt the current marker
                elif not marker_compatible(marker):
                    # Incompatible DuckDB format / read-model schema -> drop + rebuild
                    # (the store is a disposable cache; the canonical store is the truth).
                    con.close()
                    path.unlink(missing_ok=True)
                    con = _attach_persisted(path, passphrase)
                    ensure_store_meta(con)
                    _LOG.info("columnar engine: rebuilt persisted store (was %s)", marker)
                _LOG.info("columnar engine: persisted encrypted store at %s", path)
                return con
            _LOG.warning("columnar engine: encryption gate failed; using in-memory store")
        except Exception:  # noqa: BLE001 - any failure -> drop the disposable file, in-memory
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            _LOG.warning("columnar engine: persisted open failed; in-memory", exc_info=True)

    # In-memory fallback — rebuilt lazily on use; writes NO file (never plaintext).
    con = duckdb.connect(database=":memory:", config=_offline_config())
    ensure_store_meta(con)
    _LOG.info("columnar engine: in-memory store (no secure persisted encryption offline)")
    return con


def _attach_persisted(path, passphrase):
    """Open a persisted encrypted DuckDB store with the secure backend loaded."""
    import duckdb

    con = duckdb.connect(config=_offline_config())
    con.execute("LOAD httpfs")  # the OpenSSL crypto backend (offline; autoload is off)
    con.execute(f"ATTACH '{path.as_posix()}' AS oo (ENCRYPTION_KEY '{_derive_key(passphrase)}')")
    con.execute("USE oo")
    return con


# Bump when the columnar read-model TABLE SHAPES change (forces a disposable rebuild).
STORE_SCHEMA_VERSION = 1


def store_format_marker() -> str:
    """A self-describing marker of what can READ this store: the DuckDB major.minor (the
    on-disk format is bound to it) + our read-model schema rev. A persisted store whose
    marker differs is treated as INCOMPATIBLE and rebuilt — never migrated, never crashed
    on (it is a disposable projection of the canonical store)."""
    v = "?"
    try:
        import duckdb

        v = ".".join(str(duckdb.__version__).split(".")[:2])  # major.minor
    except Exception:  # noqa: BLE001
        pass
    return f"duckdb-{v}/schema-{STORE_SCHEMA_VERSION}"


def ensure_store_meta(con) -> None:
    """Stamp the format marker into the store (idempotent)."""
    con.execute("CREATE TABLE IF NOT EXISTS oo_meta (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.execute("DELETE FROM oo_meta WHERE k = 'format'")
    con.execute("INSERT INTO oo_meta VALUES ('format', ?)", [store_format_marker()])


def read_store_meta(con) -> str | None:
    """The store's recorded format marker, or None if unmarked (a fresh store)."""
    try:
        row = con.execute("SELECT v FROM oo_meta WHERE k = 'format'").fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - no oo_meta table yet (fresh/legacy store)
        return None


def marker_compatible(marker: str | None) -> bool:
    """True iff a stored marker matches the current reader (same DuckDB major.minor +
    schema rev). ``None`` (unmarked/fresh) is NOT 'incompatible' — the caller adopts it."""
    return marker == store_format_marker()


# --------------------------------------------------------------------------- #
# Read-model maintenance (Slice 4 PR-2 foundation).
#
# The derived read-model the heavy whole-corpus aggregations will read from. PR-2
# builds the maintenance + a first BYTE-IDENTICAL projection (the keyword counters); the
# perf win lands when the store is PERSISTED (a maintained store survives restarts), so
# the hot endpoints are NOT wired to it yet (offline it is in-memory = a per-process
# rebuild = no gain over the Slice-2 counters). The canonical SQLCipher store stays the
# source of truth; a reader returning nothing means the seam falls back to the live query.

_KEYWORD_AGG_DDL = (
    "CREATE OR REPLACE TABLE keyword_agg ("
    "normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
    "mention_count BIGINT, article_count BIGINT, language VARCHAR)"
)


def build_keyword_read_model(con, session) -> int:
    """(Re)build the columnar ``keyword_agg`` table from the canonical keyword counters.

    A byte-identical projection of ``Keyword.mention_count`` / ``article_count`` (the
    Slice-2 counters) — NOT a recompute, so it inherits their honesty envelope. Off the
    request path (a background/maintenance step). Returns the row count written. The
    canonical store is unchanged; this is a disposable derived table.
    """
    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    con.execute(_KEYWORD_AGG_DDL)
    rows = [
        (kw.normalized_term, kw.term, kind_of(kw), int(kw.mention_count or 0),
         int(kw.article_count or 0), kw.language)
        for kw in session.query(Keyword).filter(Keyword.mention_count > 0)
    ]
    if rows:
        con.executemany(
            "INSERT INTO keyword_agg VALUES (?, ?, ?, ?, ?, ?)", rows
        )
    return len(rows)


def top_terms_raw(con, *, kind: str | None = None, limit: int = 20) -> list[dict]:
    """Read the corpus-wide most-mentioned keywords from the columnar read-model.

    Returns the SAME raw row shape the live counter query produces
    (``{term, normalized, kind, mentions, articles}``) BEFORE the Python family/ring
    grouping — so the seam can apply the existing honesty layers unchanged and the
    result stays byte-identical. Returns ``[]`` if the table is absent (caller falls back
    to the live query). Counts only, no score.
    """
    try:
        sql = "SELECT term, normalized_term, kind, mention_count, article_count FROM keyword_agg"
        params: list = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY mention_count DESC LIMIT ?"
        params.append(int(limit))
        out = con.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001 - missing table / cold store -> fall back to live
        return []
    return [
        {"term": r[0], "normalized": r[1], "kind": r[2], "mentions": int(r[3]),
         "articles": int(r[4])}
        for r in out
    ]


# --------------------------------------------------------------------------- #
# D2 — the ``keyword_daily`` windowed-aggregation rollup (scaling workstream 5A-bis;
# docs/design/SCALING_DERIVED_LAYER_1000X.md).
#
# The measured freeze (field remark 8): windowed most-mentioned / trending sums
# ``keyword_mentions.count`` over an ``observed_on`` day range — ~2.4M rows on the live
# 61K-article corpus, each in-range row paying a SQLCipher page decrypt. The structural
# fix is to NOT scan the mention table on the read path: read a maintained per-day rollup
# and sum the tiny rollup instead.
#
# HONESTY (the load-bearing part, docstring'd on every function):
#   * ``mentions`` (= SUM(count)) summed over a window is EXACT — it equals the live
#     SUM(count) by construction.
#   * ``articles_on_day`` summed over a window is an UPPER BOUND on the window's distinct
#     article count: a (keyword, article) pair observed on more than one day is counted
#     once PER DAY here, whereas the live COUNT(DISTINCT article_id) dedups it across the
#     window. In the common single-day-per-article case the two are EQUAL; the rollup can
#     only ever OVER-count, never under-count. Callers disclose this as the ``columnar
#     (upper bound)`` basis, with a cheap per-keyword live-exact escape.
#     NOTE (measured): TODAY the unique ``(keyword_id, article_id)`` index means each pair
#     has exactly one mention row on exactly one day, so the bound is in fact EXACT (gap 0,
#     proven by the parity tests). We still DISCLOSE it as an upper bound because the rollup
#     STRUCTURE (pre-aggregate per day) cannot guarantee exactness on its own — it relies on
#     that external invariant; a future per-occurrence-with-date mention schema would make
#     the gap real. Honesty by construction: disclose what the structure can prove, not the
#     value it happens to yield under today's constraints.
#
# This module builds the rollup + the serve primitives + a parity probe, and PROVES parity
# in-memory (tests). The hot read path is NOT wired to it here: serving safely needs the
# corpus-epoch guard + the epoch-bump-on-mutate discipline (D3) so a re-index can never make
# an incremental rollup double-count. Until then this is a correctness scaffold — built and
# proven, dormant at runtime. The canonical SQLCipher store stays the source of truth; a cold
# / missing rollup means the seam falls back to the live query (identical results).

_KEYWORD_DAILY_DDL = (
    "CREATE OR REPLACE TABLE keyword_daily ("
    "keyword_id BIGINT, day DATE, mentions BIGINT, articles_on_day BIGINT)"
)
# Metadata projection so the windowed serve resolves term/kind/language in DuckDB (a JOIN
# on the rollup) instead of a second round-trip to the canonical store. ``is_entity`` +
# ``entity_type`` are carried verbatim so the ``kind`` filter reproduces ``_apply_kind``.
_KEYWORD_META_DDL = (
    "CREATE OR REPLACE TABLE keyword_meta ("
    "keyword_id BIGINT, normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
    "is_entity BOOLEAN, entity_type VARCHAR, language VARCHAR)"
)


def _set_meta(con, key: str, value) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS oo_meta (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.execute("DELETE FROM oo_meta WHERE k = ?", [key])
    con.execute("INSERT INTO oo_meta VALUES (?, ?)", [key, str(value)])


def _get_meta(con, key: str) -> str | None:
    try:
        row = con.execute("SELECT v FROM oo_meta WHERE k = ?", [key]).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - no oo_meta yet
        return None


def build_keyword_daily(con, session, *, batch_size: int = 50_000) -> dict:
    """(Re)build ``keyword_daily`` + ``keyword_meta`` — the FULL streamed build (D2).

    Streams canonical mention rows out of the app's SQLite/SQLCipher connection in
    ``batch_size`` chunks (column-projected — never ``SELECT *``, never the decrypt-heavy
    article join), inserts each batch into a DuckDB staging table, then GROUPs THERE
    (columnar, fast) into the per-day rollup. This is a resumable-shaped BATCH job scheduled
    WITH the re-index — NEVER on the query path.

    Rows with a NULL ``observed_on`` are excluded: the windowed query filters by an
    ``observed_on`` range, so an undated mention can never fall inside a window. Records
    ``last_mention_id`` (MAX mention id) in ``oo_meta`` so D3 can refresh incrementally.
    Returns a small tally. The canonical store is unchanged; this is a disposable table.
    """
    from sqlalchemy import text as _sql

    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    ensure_store_meta(con)  # idempotent: guarantees oo_meta exists

    # -- stream mentions -> DuckDB staging (dates kept as text; cast in the GROUP BY) ---- #
    con.execute("CREATE OR REPLACE TABLE keyword_daily_stage "
                "(keyword_id BIGINT, day VARCHAR, cnt BIGINT, article_id BIGINT)")
    result = session.execute(_sql(
        "SELECT keyword_id, observed_on, count, article_id FROM keyword_mentions "
        "WHERE observed_on IS NOT NULL"
    ))
    streamed = 0
    while True:
        chunk = result.fetchmany(batch_size)
        if not chunk:
            break
        con.executemany(
            "INSERT INTO keyword_daily_stage VALUES (?, ?, ?, ?)",
            [(int(r[0]), str(r[1])[:10], int(r[2]), int(r[3])) for r in chunk],
        )
        streamed += len(chunk)

    con.execute(_KEYWORD_DAILY_DDL)
    con.execute(
        "INSERT INTO keyword_daily "
        "SELECT keyword_id, CAST(day AS DATE) AS day, SUM(cnt) AS mentions, "
        "COUNT(DISTINCT article_id) AS articles_on_day "
        "FROM keyword_daily_stage GROUP BY keyword_id, CAST(day AS DATE)"
    )
    con.execute("DROP TABLE keyword_daily_stage")
    daily_rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]

    # -- keyword metadata projection (for the windowed serve's JOIN) --------------------- #
    con.execute(_KEYWORD_META_DDL)
    meta = [
        (int(kw.id), kw.normalized_term, kw.term, kind_of(kw),
         bool(kw.is_entity), kw.entity_type, kw.language)
        for kw in session.query(Keyword).filter(Keyword.mention_count > 0)
    ]
    if meta:
        con.executemany("INSERT INTO keyword_meta VALUES (?, ?, ?, ?, ?, ?, ?)", meta)

    max_id = session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar()
    _set_meta(con, "keyword_daily.last_mention_id", int(max_id or 0))
    return {
        "streamed_mentions": streamed,
        "keyword_daily_rows": int(daily_rows),
        "keyword_meta_rows": len(meta),
        "last_mention_id": int(max_id or 0),
    }


def _kind_where(kind: str | None, params: list) -> str:
    """Reproduce ``queries._apply_kind`` against the projected ``keyword_meta``."""
    if not kind:
        return ""
    if kind == "term":
        return " AND m.is_entity = FALSE"
    if kind == "entity":
        return " AND m.is_entity = TRUE"
    params.append(kind)
    return " AND m.entity_type = ?"


def windowed_term_counts(
    con, *, start_day=None, end_day=None, kind: str | None = None
) -> dict[int, tuple[int, int]]:
    """Per-keyword windowed ``(mentions, articles_upper_bound)`` from the rollup.

    ``mentions`` is EXACT (== live SUM(count) over the window). ``articles_upper_bound`` is
    ``SUM(articles_on_day)`` — an UPPER BOUND on the window's distinct-article count (see the
    module honesty note). ``start_day`` inclusive / ``end_day`` inclusive; either may be None
    for an open bound (None/None = all history). Returns ``{}`` if the rollup is absent (the
    caller falls back to the live query). Counts only, no score.
    """
    where = []
    params: list = []
    if start_day is not None:
        where.append("d.day >= ?")
        params.append(start_day)
    if end_day is not None:
        where.append("d.day <= ?")
        params.append(end_day)
    kw = " WHERE " + " AND ".join(where) if where else ""
    try:
        rows = con.execute(
            "SELECT keyword_id, SUM(mentions), SUM(articles_on_day) "  # nosec B608 - only the constant WHERE fragments (d.day >= ?/<= ?) are concatenated; every value is a bound ? param
            "FROM keyword_daily d" + kw + " GROUP BY keyword_id", params
        ).fetchall()
    except Exception:  # noqa: BLE001 - missing/cold rollup -> fall back to live
        return {}
    return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}


def windowed_top_terms_raw(
    con, *, start_day=None, end_day=None, kind: str | None = None, limit: int = 20
) -> list[dict]:
    """The ranked windowed most-mentioned rows from the rollup — the shape the live
    ``top_terms`` produces BEFORE the Python hidden-word / family / ring layers, so the seam
    (D3) can apply those unchanged and stay byte-identical.

    Ordered by ``mentions`` DESC (the live order). ``mentions`` EXACT; ``articles`` the
    upper bound. Returns ``[]`` if the rollup / metadata are absent. Counts only, no score.
    """
    params: list = []
    where = ["d.day >= ?"] if start_day is not None else []
    if start_day is not None:
        params.append(start_day)
    if end_day is not None:
        where.append("d.day <= ?")
        params.append(end_day)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    kind_sql = _kind_where(kind, params)
    params.append(int(limit))
    try:
        rows = con.execute(
            "SELECT m.term, m.normalized_term, m.kind, m.language, "  # nosec B608 - only constant clause fragments (where_sql/kind_sql) are concatenated; every value is a bound ? param
            "SUM(d.mentions) AS mentions, SUM(d.articles_on_day) AS articles "
            "FROM keyword_daily d JOIN keyword_meta m ON m.keyword_id = d.keyword_id"
            + where_sql + kind_sql
            + " GROUP BY m.term, m.normalized_term, m.kind, m.language "
            "ORDER BY mentions DESC LIMIT ?",
            params,
        ).fetchall()
    except Exception:  # noqa: BLE001 - missing/cold rollup -> fall back to live
        return []
    return [
        {"term": r[0], "normalized": r[1], "kind": r[2], "language": r[3],
         "mentions": int(r[4]), "articles": int(r[5])}
        for r in rows
    ]


def keyword_daily_parity(con, session, *, start_day=None, end_day=None) -> dict:
    """Honest parity probe: compare the rollup's windowed counts to the LIVE query, so we
    can PROVE (on a real corpus) that ``mentions`` is exact and the distinct-article count is
    an upper bound whose gap is reported — never hidden. Used by tests + a future diagnostics
    surface. Read-only; counts only.
    """
    from sqlalchemy import text as _sql

    roll = windowed_term_counts(con, start_day=start_day, end_day=end_day)
    clauses = ["observed_on IS NOT NULL"]
    p: dict = {}
    if start_day is not None:
        clauses.append("observed_on >= :s")
        p["s"] = start_day
    if end_day is not None:
        clauses.append("observed_on <= :e")
        p["e"] = end_day
    live_rows = session.execute(_sql(
        "SELECT keyword_id, SUM(count), COUNT(DISTINCT article_id) FROM keyword_mentions "  # nosec B608 - clauses are constant SQL fragments; every value is a bound :param
        "WHERE " + " AND ".join(clauses) + " GROUP BY keyword_id"
    ), p).fetchall()
    live = {int(r[0]): (int(r[1]), int(r[2])) for r in live_rows}

    mention_mismatches = 0
    distinct_gap_keywords = 0
    distinct_gap_total = 0
    upper_bound_holds = True
    for kid, (lm, la) in live.items():
        rm, ra = roll.get(kid, (0, 0))
        if rm != lm:
            mention_mismatches += 1
        if ra < la:
            upper_bound_holds = False  # a rollup distinct count must NEVER be below live
        if ra > la:
            distinct_gap_keywords += 1
            distinct_gap_total += ra - la
    return {
        "keywords_compared": len(live),
        "mentions_exact": mention_mismatches == 0,
        "mention_mismatches": mention_mismatches,
        "distinct_upper_bound_holds": upper_bound_holds,
        "distinct_gap_keywords": distinct_gap_keywords,
        "distinct_gap_total": distinct_gap_total,
        "method": (
            "keyword_daily windowed counts vs the live keyword_mentions aggregation. "
            "mentions (SUM(count)) is exact; articles (SUM(articles_on_day)) is an upper "
            "bound on COUNT(DISTINCT article_id) — the gap is the count of (keyword,article) "
            "pairs observed on more than one day, reported here, never hidden."
        ),
    }


# --------------------------------------------------------------------------- #
# D3 — incremental refresh + the corpus-epoch guard (the correctness-critical part;
# docs/design/SCALING_DERIVED_LAYER_1000X.md). Keeps the rollup fresh WITHOUT a full
# rebuild every pass, while a re-index can never make it double-count.
#
# THE TRAP (grounded in this repo): ``index_article`` does delete-then-reinsert of an
# article's mentions (store.py). So an id-watermark MERGE-ADD (tail = ``id > last_mention_id``)
# is correct ONLY for APPEND — a brand-new article's mentions carry strictly higher ids the
# tail captures once. EVERY path that re-runs ``index_article`` over an EXISTING article
# (reindex_all_batch / reindex_articles / reindex_imported_articles [restore] / clean-up-
# keywords) AND ``prune_orphan_keywords`` (deletes rows) leaves the OLD contribution in the
# rollup AND re-inserts higher-id rows into the tail = a fabricated (doubled) number. So those
# mutators bump a CORPUS EPOCH; a changed epoch forces a FULL rebuild, never an incremental
# merge. Normal new-article ingest does NOT bump the epoch (else we full-rebuild every pass).
#
# The epoch itself lives on the CANONICAL side and is passed in here — this module owns only
# the refresh DECISION + the merge. Wiring the canonical epoch counter into the mutators, and
# wiring the serve into the hot read path behind the ``built_epoch == corpus_epoch`` guard,
# are the next slice; this one builds + proves the incremental algorithm in-memory (the design
# mandate), dormant at runtime.


def _table_present(con, name: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 - catalog unavailable -> treat as absent
        return False


def _upsert_keyword_meta(con, session, keyword_ids: list[int]) -> int:
    """Add ``keyword_meta`` rows for keyword ids not already projected (new keywords that
    first appear in an incremental tail). Existing rows are LEFT unchanged — an incremental
    merge is APPEND-only (the epoch guard forces a full rebuild when a keyword's metadata
    could have changed via re-index), so a present row is already current."""
    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    added = 0
    for i in range(0, len(keyword_ids), 900):  # bounded IN() (SQLite variable limit)
        chunk = keyword_ids[i : i + 900]
        kws = session.query(Keyword).filter(Keyword.id.in_(chunk)).all()
        rows = [
            (int(kw.id), kw.normalized_term, kw.term, kind_of(kw),
             bool(kw.is_entity), kw.entity_type, kw.language)
            for kw in kws
        ]
        if not rows:
            continue
        con.execute("CREATE OR REPLACE TEMP TABLE _new_meta ("
                    "keyword_id BIGINT, normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
                    "is_entity BOOLEAN, entity_type VARCHAR, language VARCHAR)")
        con.executemany("INSERT INTO _new_meta VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute(
            "INSERT INTO keyword_meta SELECT n.* FROM _new_meta n "
            "WHERE NOT EXISTS (SELECT 1 FROM keyword_meta m WHERE m.keyword_id = n.keyword_id)"
        )
        con.execute("DROP TABLE _new_meta")
        added += len(rows)
    return added


def refresh_keyword_daily(con, session, *, corpus_epoch: int, batch_size: int = 50_000) -> dict:
    """Bring ``keyword_daily`` up to date. FULL rebuild when the corpus epoch changed since
    the last build (a re-index / prune / restore happened) or there is no usable prior build;
    otherwise an INCREMENTAL merge of the new mention tail.

    ``corpus_epoch`` is supplied by the caller from the canonical side (the value bumped by
    the re-index/prune/restore mutators). Returns ``{mode: 'full'|'incremental', ...}``.

    Incremental correctness: the tail (``id > last_mention_id``) contains only APPENDED
    mentions (the epoch guard rules out a re-index), so each carries a NEW ``(keyword,
    article)`` pair and a fresh higher id — merge-ADD into the per-day rollup is exact
    (mentions summed; per-day distinct articles summed, disjoint from existing days by the
    unique-pair invariant). Undated tail rows are skipped but the watermark still advances
    past them (never re-scanned).
    """
    ensure_store_meta(con)
    built_epoch = _get_meta(con, "keyword_daily.built_epoch")
    needs_full = (
        built_epoch is None
        or not _table_present(con, "keyword_daily")
        or not _table_present(con, "keyword_meta")
        or int(built_epoch) != int(corpus_epoch)
    )
    if needs_full:
        tally = build_keyword_daily(con, session, batch_size=batch_size)
        _set_meta(con, "keyword_daily.built_epoch", int(corpus_epoch))
        return {"mode": "full", "corpus_epoch": int(corpus_epoch), **tally}

    # -- INCREMENTAL: merge only the tail (id > watermark) ------------------------------- #
    from sqlalchemy import text as _sql

    last_id = int(_get_meta(con, "keyword_daily.last_mention_id") or 0)
    new_max = int(session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar() or last_id)
    if new_max <= last_id:
        return {"mode": "incremental", "merged_days": 0, "new_keywords": 0,
                "last_mention_id": last_id, "corpus_epoch": int(corpus_epoch)}

    con.execute("CREATE OR REPLACE TABLE keyword_daily_stage "
                "(keyword_id BIGINT, day VARCHAR, cnt BIGINT, article_id BIGINT)")
    result = session.execute(_sql(
        "SELECT keyword_id, observed_on, count, article_id FROM keyword_mentions "
        "WHERE id > :lo AND observed_on IS NOT NULL"
    ), {"lo": last_id})
    while True:
        chunk = result.fetchmany(batch_size)
        if not chunk:
            break
        con.executemany(
            "INSERT INTO keyword_daily_stage VALUES (?, ?, ?, ?)",
            [(int(r[0]), str(r[1])[:10], int(r[2]), int(r[3])) for r in chunk],
        )

    con.execute(
        "CREATE OR REPLACE TABLE keyword_daily_tail AS "
        "SELECT keyword_id, CAST(day AS DATE) AS day, SUM(cnt) AS mentions, "
        "COUNT(DISTINCT article_id) AS articles_on_day "
        "FROM keyword_daily_stage GROUP BY keyword_id, CAST(day AS DATE)"
    )
    # Portable MERGE: add to matched (keyword, day) rows, insert the rest.
    con.execute(
        "UPDATE keyword_daily d SET mentions = d.mentions + t.mentions, "
        "articles_on_day = d.articles_on_day + t.articles_on_day "
        "FROM keyword_daily_tail t WHERE d.keyword_id = t.keyword_id AND d.day = t.day"
    )
    con.execute(
        "INSERT INTO keyword_daily "
        "SELECT keyword_id, day, mentions, articles_on_day FROM keyword_daily_tail t "
        "WHERE NOT EXISTS (SELECT 1 FROM keyword_daily d "
        "WHERE d.keyword_id = t.keyword_id AND d.day = t.day)"
    )
    merged_days = con.execute("SELECT COUNT(*) FROM keyword_daily_tail").fetchone()[0]
    tail_kids = [int(r[0]) for r in
                 con.execute("SELECT DISTINCT keyword_id FROM keyword_daily_stage").fetchall()]
    new_keywords = _upsert_keyword_meta(con, session, tail_kids)
    con.execute("DROP TABLE keyword_daily_stage")
    con.execute("DROP TABLE keyword_daily_tail")
    _set_meta(con, "keyword_daily.last_mention_id", new_max)
    return {"mode": "incremental", "merged_days": int(merged_days),
            "new_keywords": int(new_keywords), "last_mention_id": new_max,
            "corpus_epoch": int(corpus_epoch)}


def refresh_persisted_read_model(session, passphrase: str | None = None) -> dict:
    """Maintain the read-model in the background — ONLY when the store is PERSISTED.

    Called where ``warm_cache`` runs (off the request path). Persisting the read-model is
    worthwhile only when it SURVIVES the process (the encrypted persisted store); an
    in-memory store is rebuilt per process, so building it in the background would be
    wasted work — hence the in-memory case is a deliberate no-op. Best-effort: a failure
    never breaks the pass; the canonical store remains the source of truth. Returns a
    small status dict.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return {"skipped": "unavailable"}
    if not (passphrase and secure_crypto_available()):
        return {"skipped": "in-memory"}  # nothing to persist across restarts
    con = None
    try:
        con = connect(passphrase=passphrase)
        if con is None:
            return {"skipped": "unavailable"}
        rows = build_keyword_read_model(con, session)
        return {"persisted": True, "keyword_agg_rows": rows}
    except Exception:  # noqa: BLE001 - a background accelerator must never break a pass
        _LOG.warning("columnar read-model refresh failed", exc_info=True)
        return {"skipped": "error"}
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass

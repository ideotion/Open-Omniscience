"""
Scale benchmark runner (scale harness G2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measure, against a given (synthetic or real) corpus, the operations the 2026-07-09
field event proved break at scale, and emit ONE honest JSON report. The report
FORMAT is the acceptance instrument for the Round-2 backup rework (P0.1): a run
before and after ZETA's change is the pass/fail evidence.

Phases:
  * unlock   -- the cold-unlock wall on a COLD COPY: the init_db + ensure_*
                self-heal sequence, INCLUDING building the ``ix_article_observed``
                expression index the field measured at 735 s, then a WARM re-run
                (the P0.4 discriminator "is the NEXT unlock fast?").
  * backup   -- the volumes+parity backup wall + PEAK RSS (the OOM the field hit).
  * restore  -- the volume-set restore round-trip (verify + parity-recover + stage).
  * endpoints-- hot-endpoint p50/p95 (top / trending-windows / latest / graph /
                status) against the real app via TestClient.
  * wal      -- WAL growth under a write burst.

HONESTY: every metric states its METHOD; there are NO scores/rankings anywhere in
the report (only measured times, byte counts and status codes). Peak RSS is a real
sampled maximum (psutil) cross-checked against ``getrusage`` ru_maxrss.

ISOLATION: ``unlock_bench`` and ``wal_bench`` take an explicit corpus path and use
their OWN engine on a COPY -- never ``SessionLocal`` / the shared data dir. The
backup/restore/endpoint phases operate on the app's live store (``live_db_path`` /
the real app), so they run PROCESS-MODE: the corpus must be the process's
``OO_DATA_DIR`` store (``run_scale_bench.py`` sets that before importing the app).
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import threading
import time

try:
    import resource  # Unix-only: getrusage peak-RSS cross-check
except ModuleNotFoundError:  # pragma: no cover - Windows has no `resource` module
    resource = None  # type: ignore[assignment]
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("testing.scale_bench")

REPORT_SCHEMA = "oo-scale-bench-1"

# Fixed, literal COUNT queries (never built from user input) so the descriptive
# corpus fingerprint carries no dynamic-SQL surface.
_COUNT_SQL: dict[str, str] = {
    "articles": "SELECT COUNT(*) FROM articles",
    "keywords": "SELECT COUNT(*) FROM keywords",
    "keyword_mentions": "SELECT COUNT(*) FROM keyword_mentions",
    "sources": "SELECT COUNT(*) FROM sources",
}

# Default hot endpoints (path, label). All have safe defaults, so a bare GET works;
# a non-200 is measured + reported honestly, never treated as a bench failure.
DEFAULT_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("/api/insights/status", "insights_status"),
    ("/api/scheduler/status", "scheduler_status"),
    ("/api/insights/top?limit=20", "top"),
    ("/api/insights/trending-windows", "trending_windows"),
    ("/api/insights/latest?limit=20", "latest"),
    ("/api/insights/graph?level=supergroup", "graph"),
)

ALL_PHASES: tuple[str, ...] = ("unlock", "endpoints", "backup", "verify", "restore", "wal")


# --------------------------------------------------------------------------- #
# Fingerprints (machine + corpus)
# --------------------------------------------------------------------------- #
def machine_fingerprint() -> dict[str, Any]:
    """Descriptive host facts so two reports are comparable. No scores."""
    out: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        out["ram_total_mb"] = round(vm.total / 1024 / 1024)
        out["ram_available_mb"] = round(vm.available / 1024 / 1024)
    except Exception:  # noqa: BLE001 - psutil is core; degrade honestly if absent
        out["ram_total_mb"] = None
    return out


def corpus_fingerprint(db_path: str | Path, passphrase: str | None = None) -> dict[str, Any]:
    """Descriptive facts about the corpus under test (bytes, row counts, whether it
    is the synthetic harness output). Read-only; never mutates the corpus."""
    from src.database.connect import connect, is_encrypted_file
    from src.testing.corpus_gen import is_synthetic

    path = Path(db_path)
    out: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size if path.exists() else 0,
        "encrypted": bool(is_encrypted_file(path)),
    }
    marker = is_synthetic(path, passphrase=passphrase)
    out["synthetic"] = marker is not None
    if marker is not None:
        out["synthetic_marker"] = {
            k: marker.get(k) for k in ("seed", "articles", "keywords", "mentions")
        }
    counts: dict[str, int | None] = {}
    try:
        conn = connect(str(path), key=passphrase, check_same_thread=False)
        try:
            cur = conn.cursor()
            for table, sql in _COUNT_SQL.items():
                try:
                    cur.execute(sql)
                    counts[table] = int(cur.fetchone()[0])
                except Exception:  # noqa: BLE001 - a missing table is reported as None
                    counts[table] = None
            cur.close()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - report the read failure honestly
        out["row_counts_error"] = str(exc)
    out["row_counts"] = counts
    return out


# --------------------------------------------------------------------------- #
# Peak-RSS sampler (a real sampled maximum, not a guess)
# --------------------------------------------------------------------------- #
class _RssPeak:
    def __init__(self) -> None:
        self.peak_bytes = 0


@contextmanager
def sample_peak_rss(interval_s: float = 0.05) -> Iterator[_RssPeak]:
    """Sample this process's RSS on a background thread; expose the peak. Also
    resets the interpretation of ``getrusage`` by capturing the baseline (the
    caller reads ru_maxrss separately as a monotonic cross-check)."""
    holder = _RssPeak()
    try:
        import psutil

        proc = psutil.Process()
    except Exception:  # pragma: no cover - psutil is core
        yield holder
        return

    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                rss = proc.memory_info().rss
                if rss > holder.peak_bytes:
                    holder.peak_bytes = rss
            except Exception:  # noqa: BLE001 - sampling must never crash the bench
                pass
            stop.wait(interval_s)

    t = threading.Thread(target=_loop, name="rss-sampler", daemon=True)
    t.start()
    try:
        # Prime one sample so a very fast phase still reports a real number.
        holder.peak_bytes = max(holder.peak_bytes, proc.memory_info().rss)
        yield holder
    finally:
        stop.set()
        t.join(timeout=1.0)
        holder.peak_bytes = max(holder.peak_bytes, proc.memory_info().rss)


def _ru_maxrss_mb() -> float | None:
    """Peak RSS since process start (getrusage). Linux reports KiB, macOS bytes.
    Returns None on Windows, where the ``resource`` module does not exist -- the
    primary peak-RSS metric is the cross-platform psutil sampler, so this is only
    the honest cross-check and degrades cleanly rather than fabricating a number."""
    if resource is None:  # pragma: no cover - Windows only
        return None
    val = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(val / 1024 / 1024, 1)
    return round(val / 1024, 1)  # KiB -> MiB


def _ru_delta_mb(before: float | None, after: float | None) -> float | None:
    """getrusage peak-RSS delta, or None when unavailable (Windows)."""
    if before is None or after is None:
        return None
    return round(after - before, 1)


# --------------------------------------------------------------------------- #
# unlock phase (engine-mode: own engine on a COLD COPY)
# --------------------------------------------------------------------------- #
def _copy_corpus(src: Path, dest_dir: Path) -> Path:
    """Copy the corpus (+ any -wal/-shm side files) into ``dest_dir`` (a cold copy
    so the source stays reusable and each unlock measures from a clean state)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "open_omniscience.db"
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dest.with_name(dest.name + suffix))
    return dest


# The init/ensure sequence run at unlock, mirroring src.database.session.init_db
# (the ensure_* self-heals) PLUS optimize_at_boot (the ANALYZE the app runs at
# startup). Kept in lock-step with init_db by test_scale_bench's drift guard.
def _run_init_sequence(engine: Any) -> dict[str, Any]:
    """Run the app's unlock upkeep on ``engine`` and report what it did."""
    from src.database.fts import ensure_fts
    from src.database.maintenance import (
        ensure_article_analysis_columns,
        ensure_article_detected_language_column,
        ensure_article_identity_columns,
        ensure_article_ip_columns,
        ensure_external_source_discovery_columns,
        ensure_feed_backoff_columns,
        ensure_hot_indexes,
        ensure_keyword_counter_columns,
        ensure_keyword_extractor_column,
        ensure_keyword_mention_source_column,
        ensure_law_document_language_columns,
        ensure_law_text_columns,
        ensure_source_counter_columns,
        ensure_supergroup_ring_column,
        ensure_wiki_text_columns,
        optimize_at_boot,
    )
    from src.database.migrate import stamp_if_unstamped
    from src.database.models import Base

    Base.metadata.create_all(engine)
    ensure_fts(engine)
    stamp_if_unstamped(engine)
    ensure_keyword_counter_columns(engine)
    ensure_article_identity_columns(engine)
    ensure_article_ip_columns(engine)
    ensure_article_detected_language_column(engine)
    ensure_keyword_mention_source_column(engine)
    created = ensure_hot_indexes(engine)
    ensure_feed_backoff_columns(engine)
    ensure_article_analysis_columns(engine)
    ensure_keyword_extractor_column(engine)
    ensure_wiki_text_columns(engine)
    ensure_supergroup_ring_column(engine)
    ensure_external_source_discovery_columns(engine)
    ensure_law_text_columns(engine)
    ensure_law_document_language_columns(engine)
    ensure_source_counter_columns(engine)
    analyze = optimize_at_boot(engine)
    return {"hot_indexes_created": created, "analyze": analyze}


def _bench_engine(db_path: Path, passphrase: str | None) -> Any:
    from sqlalchemy import create_engine, event

    from src.database.connect import connect

    def _creator() -> Any:
        if passphrase is not None:
            return connect(str(db_path), key=passphrase, check_same_thread=False, timeout=60)
        return connect(str(db_path), create_encrypted=False, check_same_thread=False, timeout=60)

    engine = create_engine(f"sqlite:///{db_path}", future=True, creator=_creator)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _rec: Any) -> None:  # pragma: no cover - trivial
        # Mirror the app's real per-connection PRAGMAs (src/database/session.py) so
        # the measured unlock/wal timing matches production: WAL + NORMAL sync + the
        # 64 MiB page cache + in-memory temp trees are what make (or don't make) the
        # index build fast under the SQLCipher codec. mmap is plaintext-only (codec
        # pages can't be mapped), exactly like the app.
        from src.config.power_profiles import sqlite_cache_mb

        cache_mb = sqlite_cache_mb()  # OO_SQLITE_CACHE_MB / active profile (Optimized = 64)
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute(f"PRAGMA cache_size=-{max(2, cache_mb) * 1024}")
            cur.execute("PRAGMA temp_store=MEMORY")
            if "sqlcipher" not in type(dbapi_conn).__module__:
                cur.execute("PRAGMA mmap_size=268435456")
        finally:
            cur.close()

    return engine


def unlock_bench(
    corpus_path: str | Path,
    *,
    passphrase: str | None = None,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Measure the cold + warm unlock upkeep on a COLD COPY of the corpus.

    The cold run builds the ``ix_article_observed`` expression index over every
    article (the field's 735 s cost); the warm run re-runs the sequence with the
    index already present (the P0.4 "is the NEXT unlock fast?" discriminator)."""
    import tempfile

    src = Path(corpus_path)
    tmp_root = Path(work_dir) if work_dir else Path(
        tempfile.mkdtemp(prefix=".oo-unlock-", dir=src.parent)
    )  # beside the corpus, SAME filesystem: /tmp is tmpfs on the Qubes field machine
    # (the ledger lesson) -- a RAM-disk copy would fake I/O costs and ENOSPC at 50 GB
    copy_dir = tmp_root / "cold"
    result: dict[str, Any] = {
        "method": "init_db + ensure_* self-heals + optimize_at_boot on a cold file "
        "copy; cold builds ix_article_observed over every article, warm re-runs it. "
        "COLD means no-index/no-stats/fresh-engine ONLY: the copy just wrote the file, "
        "so reads come from the OS page cache -- a machine with RAM > corpus understates "
        "the field's disk-I/O term (disclosed, not corrected)",
    }
    try:
        t_copy = time.perf_counter()
        db = _copy_corpus(src, copy_dir)
        result["copy_s"] = round(time.perf_counter() - t_copy, 3)

        engine = _bench_engine(db, passphrase)
        try:
            with sample_peak_rss() as peak:
                t0 = time.perf_counter()
                cold = _run_init_sequence(engine)
                result["cold_unlock_s"] = round(time.perf_counter() - t0, 3)
            result["cold_peak_rss_mb"] = round(peak.peak_bytes / 1024 / 1024, 1)
            result["hot_indexes_created_cold"] = cold["hot_indexes_created"]
            result["analyze_cold"] = cold["analyze"]

            t1 = time.perf_counter()
            warm = _run_init_sequence(engine)
            result["warm_unlock_s"] = round(time.perf_counter() - t1, 3)
            result["hot_indexes_created_warm"] = warm["hot_indexes_created"]
        finally:
            engine.dispose()
    finally:
        if work_dir is None:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return result


# --------------------------------------------------------------------------- #
# WAL phase (engine-mode: write burst on a COPY)
# --------------------------------------------------------------------------- #
def wal_bench(
    corpus_path: str | Path,
    *,
    passphrase: str | None = None,
    writes: int = 5000,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Measure WAL growth under a write burst on a COPY of the corpus. Writes go to
    the ``app_state`` table (a real, always-present table) with no intervening
    checkpoint, so the ``-wal`` peak reflects unchecked-write pressure."""
    import tempfile

    src = Path(corpus_path)
    tmp_root = Path(work_dir) if work_dir else Path(
        tempfile.mkdtemp(prefix=".oo-wal-", dir=src.parent)
    )  # same-filesystem rule as unlock_bench (never tmpfs /tmp)
    copy_dir = tmp_root / "wal"
    out: dict[str, Any] = {
        "writes": writes,
        "method": "N app_state upserts, ONE COMMIT EACH (a realistic write burst), "
        "on a WAL copy with the app's default auto-checkpoint left ON; wal_peak_bytes "
        "is the max -wal high-water mark during the burst -- a bounded peak is healthy "
        "WAL hygiene, an unbounded one is the P0.3 runaway-WAL signal",
    }
    try:
        db = _copy_corpus(src, copy_dir)
        wal_path = db.with_name(db.name + "-wal")
        engine = _bench_engine(db, passphrase)
        try:
            # Ensure app_state exists (a real corpus always has it; be defensive).
            from src.database.models import Base

            Base.metadata.tables["app_state"].create(bind=engine, checkfirst=True)
            peak_wal = 0
            # Commit PER write via a raw connection = many transactions, so SQLite's
            # default wal_autocheckpoint (1000 pages) operates as in production.
            raw = engine.raw_connection()
            t0 = time.perf_counter()
            try:
                cur = raw.cursor()
                for i in range(writes):
                    cur.execute(
                        "INSERT INTO app_state(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (f"__wal_bench_{i}", "x" * 200),
                    )
                    raw.commit()
                    if i % 250 == 0 and wal_path.exists():
                        peak_wal = max(peak_wal, wal_path.stat().st_size)
                cur.close()
            finally:
                raw.close()
            out["duration_s"] = round(time.perf_counter() - t0, 3)
            if wal_path.exists():
                peak_wal = max(peak_wal, wal_path.stat().st_size)
            out["wal_peak_bytes"] = peak_wal
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            out["wal_bytes_after_checkpoint"] = (
                wal_path.stat().st_size if wal_path.exists() else 0
            )
        finally:
            engine.dispose()
    finally:
        if work_dir is None:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return out


# --------------------------------------------------------------------------- #
# endpoint phase (process-mode: the real app via TestClient)
# --------------------------------------------------------------------------- #
def _pct(sorted_ms: Sequence[float], q: float) -> float:
    """Nearest-rank percentile of a sorted list of latencies (ms)."""
    if not sorted_ms:
        return 0.0
    idx = min(len(sorted_ms) - 1, max(0, int(round(q * (len(sorted_ms) - 1)))))
    return round(sorted_ms[idx], 2)


def endpoint_bench(
    client: Any,
    endpoints: Sequence[tuple[str, str]] = DEFAULT_ENDPOINTS,
    *,
    repeats: int = 8,
    warmup: int = 1,
) -> dict[str, Any]:
    """GET each endpoint ``repeats`` times through ``client`` (a TestClient) and
    report p50/p95 latency + the HTTP status. Warmup calls are excluded. No scores."""
    rows: list[dict[str, Any]] = []
    for path, label in endpoints:
        for _ in range(max(0, warmup)):
            with suppress(Exception):  # warmup errors are measured on the real GETs below
                client.get(path)
        samples: list[float] = []
        status: int | None = None
        error: str | None = None
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            try:
                resp = client.get(path)
                status = resp.status_code
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            samples.append((time.perf_counter() - t0) * 1000.0)
        samples.sort()
        rows.append(
            {
                "label": label,
                "path": path,
                "method": "GET",
                "n": len(samples),
                "status": status,
                "p50_ms": _pct(samples, 0.50),
                "p95_ms": _pct(samples, 0.95),
                "min_ms": round(samples[0], 2),
                "max_ms": round(samples[-1], 2),
                "error": error,
            }
        )
    return {
        "endpoints": rows,
        "method": f"{repeats} GETs/endpoint via TestClient (warmup {warmup} excluded); "
        "nearest-rank percentiles; a non-200 status is reported, not a failure",
    }


# --------------------------------------------------------------------------- #
# backup + restore phases (process-mode: the real volumes+parity path)
# --------------------------------------------------------------------------- #
def backup_bench(
    dest_dir: str | Path,
    *,
    passphrase: str,
    include_newsletters: bool = True,
    parity_fraction: float = 0.1,
    interrupt_volumes: int = 0,
) -> dict[str, Any]:
    """Measure the REAL streaming (oo-volumes-2) backup wall + PEAK RSS. Backs up
    the process's live store (``live_db_path``), so the caller must have pointed
    OO_DATA_DIR at the corpus before importing the app.

    ``interrupt_volumes`` > 0 PROVES resumability at this scale: a first run is
    stopped after that many volumes (measured, reported under ``interrupted``),
    then the SAME backup is started again and must complete by reusing the
    finished volumes. NOTE the completed run's wall then includes reuse, so it is
    NOT the official full-backup number — run with 0 for that (stated in method)."""
    from src.backup.artifact import write_volume_backup
    from src.backup.volumes import VolumeStopped

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "method": "src.backup.artifact.write_volume_backup (oo-volumes-2 member-streamed "
        "OOENC2 volumes + banded Reed-Solomon parity; the corpus streams as its at-rest "
        "bytes under the writer gate); wall is end-to-end, peak RSS is a sampled maximum"
    }
    ru_before = _ru_maxrss_mb()
    if interrupt_volumes > 0:
        calls = {"n": 0}

        def _stop() -> bool:
            calls["n"] += 1
            return calls["n"] > interrupt_volumes

        t_int = time.perf_counter()
        try:
            write_volume_backup(
                dest,
                passphrase,
                include_newsletters=include_newsletters,
                parity_fraction=parity_fraction,
                should_stop=_stop,
            )
            out["interrupted"] = {"error": "the run completed before the interrupt fired"}
        except VolumeStopped:
            out["interrupted"] = {
                "after_volumes": interrupt_volumes,
                "wall_s": round(time.perf_counter() - t_int, 3),
            }
        out["method"] += (
            "; interrupted after "
            f"{interrupt_volumes} volumes then RESUMED — the completed wall below "
            "includes volume reuse, NOT a full-backup number"
        )
    with sample_peak_rss() as peak:
        t0 = time.perf_counter()
        summary = write_volume_backup(
            dest,
            passphrase,
            include_newsletters=include_newsletters,
            parity_fraction=parity_fraction,
        )
        out["wall_s"] = round(time.perf_counter() - t0, 3)
    out["peak_rss_mb"] = round(peak.peak_bytes / 1024 / 1024, 1)
    out["ru_maxrss_delta_mb"] = _ru_delta_mb(ru_before, _ru_maxrss_mb())
    for key in (
        "volumes",
        "volumes_reused",
        "volumes_emitted",
        "plaintext_bytes",
        "corpus_bytes",
        "corpus_encrypted",
        "parity_available",
        "format",
        "resumed",
        "gate_held_s",
        "notes",
    ):
        out[key] = summary.get(key)
    out["dest_bytes"] = _dir_bytes(dest)
    return out


def verify_bench(src_dir: str | Path, *, passphrase: str | None = None) -> dict[str, Any]:
    """Measure the end-to-end VERIFY of the produced volume set (P0.1): manifest
    signature + every volume checksum, and — with the passphrase — a full
    stream-decrypt of every volume into a hash sink (nothing written). Reports
    the verifier's own verdict verbatim plus wall + peak RSS."""
    from src.backup.stream_backup import verify_stream_backup

    out: dict[str, Any] = {
        "method": "src.backup.stream_backup.verify_stream_backup; with the passphrase "
        "every volume is stream-decrypted into a hash sink (nothing written to disk)"
    }
    ru_before = _ru_maxrss_mb()
    with sample_peak_rss() as peak:
        t0 = time.perf_counter()
        report = verify_stream_backup(Path(src_dir), passphrase)
        out["wall_s"] = round(time.perf_counter() - t0, 3)
    out["peak_rss_mb"] = round(peak.peak_bytes / 1024 / 1024, 1)
    out["ru_maxrss_delta_mb"] = _ru_delta_mb(ru_before, _ru_maxrss_mb())
    out["ok"] = report.get("ok")
    out["report"] = report
    return out


def restore_bench(
    src_dir: str | Path,
    *,
    passphrase: str,
    staging_root: str | Path | None = None,
) -> dict[str, Any]:
    """Measure the REAL volume-set restore round-trip (verify + parity-recover +
    reassemble + stage) wall + peak RSS. Cleans up the staged artifact."""
    from src.backup.artifact import cleanup_staging, read_volume_backup

    out: dict[str, Any] = {
        "method": "src.backup.artifact.read_volume_backup (verify + parity-recover + "
        "streamed reassembly + stage; STAGE-ONLY, so the disk preflight excludes "
        "the merge's working-copy budget); wall is end-to-end, peak RSS sampled"
    }
    ru_before = _ru_maxrss_mb()
    staged = None
    with sample_peak_rss() as peak:
        t0 = time.perf_counter()
        staged = read_volume_backup(
            Path(src_dir),
            passphrase,
            Path(staging_root) if staging_root else None,
            include_merge_budget=False,  # the bench stages + cleans, never merges
        )
        out["wall_s"] = round(time.perf_counter() - t0, 3)
    out["peak_rss_mb"] = round(peak.peak_bytes / 1024 / 1024, 1)
    out["ru_maxrss_delta_mb"] = _ru_delta_mb(ru_before, _ru_maxrss_mb())
    out["verified"] = True  # read_volume_backup raises on any verify/parity failure
    if staged is not None:
        with suppress(Exception):  # cleanup is best-effort
            cleanup_staging(staged)
    return out


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- #
# Orchestration (process-mode)
# --------------------------------------------------------------------------- #
def _iso_now(now: Callable[[], Any] | None = None) -> str:
    from datetime import UTC, datetime

    dt = now() if now is not None else datetime.now(UTC)
    return dt.isoformat(timespec="seconds")


def run_full(
    corpus_dir: str | Path,
    *,
    backup_passphrase: str,
    corpus_passphrase: str | None = None,
    phases: Sequence[str] = ALL_PHASES,
    endpoints: Sequence[tuple[str, str]] = DEFAULT_ENDPOINTS,
    repeats: int = 8,
    wal_writes: int = 5000,
    parity_fraction: float = 0.1,
    interrupt_volumes: int = 0,
    now: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Run the requested phases against the PROCESS's live corpus (the file at
    ``corpus_dir/open_omniscience.db`` == ``live_db_path``) and return the report.

    The caller MUST have set OO_DATA_DIR=corpus_dir before importing the app (see
    run_scale_bench.py), so ``live_db_path`` and the app engine point at the corpus.
    ``phases`` selects a subset (each backup/restore needs ~corpus-size scratch).

    ORDER + FAITHFULNESS: ``unlock`` runs FIRST on a COLD COPY of the still-pristine
    corpus, so its cold number reproduces the field's index-build cost. The
    ``endpoints`` phase then boots the real app, which runs the app's own unlock
    upkeep (``init_db`` -> builds ``ix_article_observed`` + ANALYZE) on the LIVE
    corpus, so the endpoint p95s are the steady-state (post-unlock) numbers. That
    HEALS the live corpus, so to re-measure a true COLD unlock, regenerate the
    corpus (the generator is deterministic + cheap) rather than re-running here."""
    corpus_dir = Path(corpus_dir)
    corpus_db = corpus_dir / "open_omniscience.db"
    if not corpus_db.exists():
        raise FileNotFoundError(f"no corpus at {corpus_db}")

    report: dict[str, Any] = {
        "report_schema": REPORT_SCHEMA,
        "generated_at": _iso_now(now),
        "machine": machine_fingerprint(),
        "corpus": corpus_fingerprint(corpus_db, passphrase=corpus_passphrase),
        "phases_requested": list(phases),
        "phases": {},
        "notes": "Measured times/bytes/status only -- NO scores or rankings. "
        "Peak RSS is a sampled maximum; unlock/wal run on a cold copy.",
    }
    if not report["corpus"].get("encrypted"):
        # The acceptance-instrument caveat (post-merge audit, 2026-07-09): the field
        # cost is DOMINATED by the SQLCipher codec (~26 s of a measured 32 s wall), so
        # a plaintext corpus understates backup/restore/unlock/endpoints across the
        # board. Never silent -- the Round-2 acceptance gate must see encrypted:true.
        report["plaintext_caveat"] = (
            "PLAINTEXT corpus: every SQLCipher codec cost is ABSENT from these numbers. "
            "Do NOT use this report for scale-acceptance decisions; regenerate the "
            "corpus with --passphrase and assert corpus.encrypted == true."
        )
    phase_out: dict[str, Any] = report["phases"]

    if "unlock" in phases:
        _LOG.info("scale-bench: unlock phase")
        phase_out["unlock"] = _guard(
            lambda: unlock_bench(corpus_db, passphrase=corpus_passphrase)
        )

    if "endpoints" in phases:
        _LOG.info("scale-bench: endpoints phase")
        phase_out["endpoints"] = _guard(lambda: _endpoints_phase(endpoints, repeats))

    backup_dir = corpus_dir / "_bench_backup"
    if "backup" in phases:
        _LOG.info("scale-bench: backup phase")
        # Clean slate: a stale volume set from a crashed prior run must not be mixed
        # with this run's volumes (that would fail the restore's verify).
        shutil.rmtree(backup_dir, ignore_errors=True)
        phase_out["backup"] = _guard(
            lambda: backup_bench(
                backup_dir,
                passphrase=backup_passphrase,
                parity_fraction=parity_fraction,
                interrupt_volumes=interrupt_volumes,
            )
        )

    if "verify" in phases:
        _LOG.info("scale-bench: verify phase")
        if not backup_dir.exists():
            phase_out["verify"] = {"skipped": "no backup was produced to verify"}
        else:
            phase_out["verify"] = _guard(
                lambda: verify_bench(backup_dir, passphrase=backup_passphrase)
            )

    if "restore" in phases:
        _LOG.info("scale-bench: restore phase")
        if not backup_dir.exists():
            phase_out["restore"] = {"skipped": "no backup was produced to restore"}
        else:
            phase_out["restore"] = _guard(
                lambda: restore_bench(
                    backup_dir, passphrase=backup_passphrase, staging_root=corpus_dir
                )
            )

    if "wal" in phases:
        _LOG.info("scale-bench: wal phase")
        phase_out["wal"] = _guard(
            lambda: wal_bench(corpus_db, passphrase=corpus_passphrase, writes=wal_writes)
        )

    # Best-effort cleanup of the backup scratch so a re-run starts clean.
    shutil.rmtree(backup_dir, ignore_errors=True)
    return report


def _endpoints_phase(
    endpoints: Sequence[tuple[str, str]], repeats: int
) -> dict[str, Any]:
    """Boot the real app against the live store and measure the endpoints."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        return endpoint_bench(client, endpoints, repeats=repeats)


def _guard(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a phase; a failure is reported as a structured error, never aborts the
    whole report (a diagnostic must degrade, never crash the run)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - degrade loudly, don't abort the report
        _LOG.warning("scale-bench phase failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Acceptance gate (the P0.1 audit conditions — Round 2 / ZETA)
# --------------------------------------------------------------------------- #
def acceptance_gate(
    report: dict[str, Any],
    *,
    max_backup_peak_rss_mb: float | None = None,
    official: bool = False,
) -> dict[str, Any]:
    """Evaluate a benchmark report against the P0.1 acceptance AUDIT CONDITIONS.

    Checks (each recorded with its evidence; ``ok`` only when every applicable
    check passes — nothing is scored, nothing weighted):

      * the corpus under test is ENCRYPTED (``report.corpus.encrypted == true``)
        — a plaintext corpus omits every SQLCipher codec cost, so its numbers
        must never gate a scale decision (the plaintext_caveat made it loud;
        this makes it BLOCKING);
      * the backup phase ran without error, and — when a bound is supplied —
        its sampled peak RSS stayed under ``max_backup_peak_rss_mb``. The gate
        NEVER invents a bound: with no bound given, the check reports the
        measured value as not-evaluated;
      * the verify phase ran and its verdict is ok;
      * the restore phase ran without error (the additive round-trip);
      * ``official=True`` additionally requires the report to be a
        fresh-process ``--phases backup`` run (earlier phases inflate
        process-lifetime ru_maxrss and can mask a backup RSS spike), and then
        requires only the backup checks.
    """
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def _check(name: str, ok: bool | None, evidence: Any) -> None:
        checks.append({"name": name, "ok": ok, "evidence": evidence})
        if ok is False:
            failures.append(name)

    corpus = report.get("corpus") or {}
    _check(
        "corpus_encrypted",
        bool(corpus.get("encrypted")),
        {"encrypted": corpus.get("encrypted"), "path": corpus.get("path")},
    )
    if report.get("plaintext_caveat"):
        _check("no_plaintext_caveat", False, report["plaintext_caveat"])

    phases = report.get("phases") or {}
    requested = list(report.get("phases_requested") or [])
    if official:
        _check(
            "official_backup_process",
            requested == ["backup"],
            {
                "phases_requested": requested,
                "why": "the OFFICIAL backup number comes from a fresh-process "
                "--phases backup run (other phases inflate process-lifetime RSS)",
            },
        )

    backup = phases.get("backup") or {}
    _check(
        "backup_ran",
        bool(backup) and "error" not in backup and backup.get("wall_s") is not None,
        {"error": backup.get("error"), "wall_s": backup.get("wall_s")},
    )
    peak = backup.get("peak_rss_mb")
    if max_backup_peak_rss_mb is not None:
        _check(
            "backup_peak_rss_bounded",
            peak is not None and float(peak) <= float(max_backup_peak_rss_mb),
            {"peak_rss_mb": peak, "bound_mb": max_backup_peak_rss_mb},
        )
    else:
        _check(
            "backup_peak_rss_bounded",
            None,
            {"peak_rss_mb": peak, "bound_mb": None, "note": "no bound supplied — not evaluated"},
        )
    if backup.get("interrupted") is not None:
        _check(
            "interrupt_and_resume",
            isinstance(backup.get("interrupted"), dict)
            and "error" not in backup["interrupted"]
            and bool(backup.get("resumed"))
            and int(backup.get("volumes_reused") or 0) > 0,
            {
                "interrupted": backup.get("interrupted"),
                "resumed": backup.get("resumed"),
                "volumes_reused": backup.get("volumes_reused"),
            },
        )

    if not official:
        verify = phases.get("verify") or {}
        _check(
            "verify_ok",
            bool(verify) and "error" not in verify and verify.get("ok") is True,
            {"error": verify.get("error"), "ok": verify.get("ok")},
        )
        restore = phases.get("restore") or {}
        _check(
            "restore_ran",
            bool(restore) and "error" not in restore and "skipped" not in restore,
            {"error": restore.get("error"), "skipped": restore.get("skipped")},
        )

    return {
        "ok": not failures,
        "failures": failures,
        "checks": checks,
        "method": "each audit condition checked against the report's measured "
        "evidence; no scores, no weighting — any failed check fails the gate",
    }

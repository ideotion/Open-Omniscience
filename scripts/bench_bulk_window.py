"""The break-even of the R23 index window over a re-index drain (row 407, R825).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Seeds an ENCRYPTED store (SQLCipher, random key held in memory only) with E mention rows under
every index the model declares, then for each N compares the two ways to add N more rows:

* ``live``: insert them with every index maintained (what a drain does without the window);
* ``window``: drop the droppable mention indexes (never the unique ones, never
  ``ix_mention_article``), insert, then rebuild each, ``temp_store=MEMORY``, in a child process
  so its peak resident memory is read on its own.

It prints one JSON line per measurement: the seconds of each mode, the peak memory of each
rebuild above the child's baseline (which includes the connection's 64 MiB page cache), and, once,
the bytes the dropped indexes occupy per row (``BW_DISK=0`` skips it).
``bulk_build.DRAIN_WINDOW_MIN_FRACTION``, ``RAM_BYTES_PER_MENTION`` and
``DISK_BYTES_PER_MENTION`` cite its output.

    python -I scripts/bench_bulk_window.py . 2000000 50000,100000,300000

Rows are synthetic (98 keywords per article out of 300,000, the REPORT-2 shape). Nothing is
written outside a private temporary folder, which is removed at the end.
"""

from __future__ import annotations

import contextlib
import json
import multiprocessing as mp
import os
import random
import resource
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "."))
os.environ.setdefault("OO_DB_PLAINTEXT", "1")
os.environ.setdefault("OO_NO_SCHEDULER", "1")

from sqlalchemy.dialects import sqlite  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from src.database import models  # noqa: E402

_TABLE = models.Base.metadata.tables["keyword_mentions"]
_DIALECT = sqlite.dialect()
TABLE_DDL = str(CreateTable(_TABLE).compile(dialect=_DIALECT)).strip()
INDEX_DDL = {i.name: str(CreateIndex(i).compile(dialect=_DIALECT)).strip() for i in _TABLE.indexes}
KEEP = {i.name for i in _TABLE.indexes if i.unique} | {"ix_mention_article"}
DROP = sorted(set(INDEX_DDL) - KEEP)
COLS = (
    "keyword_id", "article_id", "count", "first_offset", "observed_on", "country", "city", "language",
    "source_id", "extractor", "created_at",
)
INSERT = f"INSERT INTO keyword_mentions ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})"
_KEY = os.urandom(32).hex()  # in memory only; never printed


def _connect(path: str):
    import sqlcipher3

    c = sqlcipher3.connect(path)
    c.execute(f"PRAGMA key = \"x'{_KEY}'\"")
    c.execute("PRAGMA cipher_page_size = 16384")
    for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "cache_size=-65536", "temp_store=MEMORY"):
        c.execute("PRAGMA " + pragma)
    return c


def _rows(seed: int, n: int, first_article: int):
    rnd = random.Random(seed)
    article = first_article
    while n > 0:
        article += 1
        for kw in rnd.sample(range(1, 300_000), 98):
            yield (
                kw, article, rnd.randint(1, 9), rnd.randint(0, 5000),
                f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}", "fr", "Paris", "en",
                rnd.randint(1, 500), "bench", f"2026-11-24 10:{rnd.randint(0, 59):02d}:00",
            )
            n -= 1
            if n <= 0:
                return


def _load(c, rows) -> None:
    buf: list[tuple] = []
    for r in rows:
        buf.append(r)
        if len(buf) == 20_000:
            c.execute("BEGIN")
            c.executemany(INSERT, buf)
            c.execute("COMMIT")
            buf = []
    if buf:
        c.execute("BEGIN")
        c.executemany(INSERT, buf)
        c.execute("COMMIT")


def _size(path: str) -> int:
    c = _connect(path)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    return os.path.getsize(path)


def _dropped_index_bytes(seed: str, work: str) -> dict:
    """The bytes the dropped indexes occupy, per row: the seed VACUUMed whole, then without them, VACUUMed
    again (a DROP alone leaves its pages on the freelist, so the file size would not move)."""
    path = os.path.join(work, "disk.db")
    shutil.copy(seed, path)
    c = _connect(path)
    rows = c.execute("SELECT COUNT(*) FROM keyword_mentions").fetchone()[0]
    c.execute("VACUUM")
    c.close()
    full = _size(path)
    c = _connect(path)
    for name in DROP:
        c.execute(f"DROP INDEX {name}")
    c.execute("VACUUM")
    c.close()
    bare = _size(path)
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(path + suffix)
    return {"rows": rows, "file_bytes": full, "without_dropped_bytes": bare, "dropped_index_bytes_per_row": round((full - bare) / rows, 1)}


def _child_build(path: str, name: str, q) -> None:
    c = _connect(path)
    base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t0 = time.perf_counter()
    c.execute(INDEX_DDL[name])
    took = time.perf_counter() - t0
    q.put((name, took, (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - base) / 1024))
    c.close()


def main() -> None:
    existing = int(sys.argv[2])
    news = [int(x) for x in sys.argv[3].split(",")]
    work = tempfile.mkdtemp(prefix="oo-bw-")
    os.chmod(work, 0o700)
    try:
        seed = os.path.join(work, "seed.db")
        c = _connect(seed)
        c.execute(TABLE_DDL)
        for ddl in INDEX_DDL.values():
            c.execute(ddl)
        t0 = time.perf_counter()
        _load(c, _rows(1, existing, 0))
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
        print(json.dumps({"seed_rows": existing, "seed_s": round(time.perf_counter() - t0, 1), "drop": DROP, "keep": sorted(KEEP)}), flush=True)
        if os.environ.get("BW_DISK", "1") != "0":
            print(json.dumps({"disk": _dropped_index_bytes(seed, work)}), flush=True)
        for n in news:
            for mode in ("live", "window"):
                path = os.path.join(work, f"{mode}{n}.db")
                shutil.copy(seed, path)
                c = _connect(path)
                t0 = time.perf_counter()
                out: dict = {"E": existing, "N": n, "mode": mode}
                if mode == "window":
                    for name in DROP:
                        c.execute(f"DROP INDEX {name}")
                _load(c, _rows(2, n, 50_000_000))
                out["load_s"] = round(time.perf_counter() - t0, 1)
                c.close()
                if mode == "window":
                    builds = []
                    for name in DROP:
                        q: mp.Queue = mp.Queue()
                        proc = mp.Process(target=_child_build, args=(path, name, q))
                        proc.start()
                        builds.append(q.get())
                        proc.join()
                    out["rebuild_s"] = round(sum(b[1] for b in builds), 1)
                    out["peak_rss_mb"] = {b[0]: round(b[2]) for b in builds}
                    out["total_s"] = round(time.perf_counter() - t0, 1)
                else:
                    out["total_s"] = round(time.perf_counter() - t0, 1)
                print(json.dumps(out), flush=True)
                for suffix in ("", "-wal", "-shm"):
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(path + suffix)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

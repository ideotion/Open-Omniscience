"""Real stores and real damage for the damaged-database tests (plan slices E2b and E3: the page pass, the salvage and the repair).

Nothing here is a stub of a database: the stores are built through the app's own models, its own full-text index and its own
connection factory (plaintext or SQLCipher), and damaged by overwriting whole pages with random bytes, which is what a bad
sector or a torn write leaves and what the earlier slices' tests do. A plaintext store is targeted page by page through
``dbstat``; an encrypted store has no ``dbstat`` (measured: the SQLCipher build has none), so its pages are chosen by
position and the tests assert only what holds whichever tables they hit.
"""
from __future__ import annotations

import os
import random
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

KEY = "a passphrase that is long enough"
PLAIN_PAGE = 4096
CIPHER_PAGE = 16384


def needs_sqlcipher() -> None:
    pytest.importorskip("sqlcipher3")


def build_app_store(
    path: Path, *, articles: int = 1500, encrypted: bool = False, key: str = KEY, sources: int = 12, cipher_page_size: int | None = None
) -> None:
    """A store with the app's real schema (every model table, the full-text index and its triggers) holding ``sources`` sources
    and ``articles`` articles, in a file of its own. SQLCipher stores are created at the app's page size (16 KiB) unless
    ``cipher_page_size`` says another (a file made before the app moved to 16 KiB pages is 4 KiB)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from src.database import connect as connect_mod
    from src.database import fts
    from src.database.models import Article, Base, Source

    previous = connect_mod.get_passphrase()
    connect_mod.set_passphrase(key if encrypted else None)

    def creator():
        return connect_mod.connect(
            str(path),
            check_same_thread=False,
            timeout=30,
            create_encrypted=bool(encrypted),
            cipher_page_size=cipher_page_size if encrypted else None,
        )

    engine = create_engine("sqlite://", creator=creator, future=True)
    try:
        Base.metadata.create_all(engine)
        fts.ensure_fts(engine)
        rng = random.Random(3)
        words = [f"w{i}" for i in range(1500)]
        Session = sessionmaker(bind=engine)
        with Session() as s:
            for k in range(sources):
                s.add(Source(name=f"s{k}", domain=f"s{k}.example.org"))
            s.flush()
            ids = list(s.execute(select(Source.id)).scalars())
            for i in range(articles):
                s.add(
                    Article(
                        url=f"https://e.org/{i}",
                        canonical_url=f"https://e.org/{i}",
                        source_id=ids[i % len(ids)],
                        content=" ".join(rng.choice(words) for _ in range(300)),
                        hash=f"h{i}",
                        title=f"Title {i} " + " ".join(rng.choice(words) for _ in range(5)),
                        language="en",
                    )
                )
                if i % 500 == 499:
                    s.commit()
            s.commit()
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        engine.dispose()
        connect_mod.set_passphrase(previous)


def open_store(path: Path, *, key: str | None = None):
    """A plain read connection through the app's factory (the key given, or the one the process holds)."""
    from src.database.connect import connect

    return connect(str(path), key=key, check_same_thread=False, timeout=30)


def leaf_pages(path: Path, table: str, kind: str = "leaf") -> list[int]:
    """The pages of ``table`` of a PLAINTEXT store (``kind``: ``leaf`` or ``internal``), through ``dbstat``."""
    con = sqlite3.connect(path)
    try:
        return [p for p, t in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name=?", (table,)) if t == kind]
    except sqlite3.OperationalError:
        reason = "this SQLite build has no dbstat virtual table (SQLITE_ENABLE_DBSTAT_VTAB)"
        if os.getenv("CI"):
            pytest.fail(reason + " -- the damaged-page tests must run in CI")
        pytest.skip(reason)
    finally:
        con.close()


def overwrite_pages(path: Path, pages: list[int], page_size: int) -> None:
    with open(path, "r+b") as f:
        for pg in pages:
            f.seek((pg - 1) * page_size)
            f.write(random.Random(pg).randbytes(page_size))


def copy_store(src: Path, dst: Path) -> Path:
    """A byte copy of a store and whatever side files it has."""
    shutil.copy(src, dst)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy(side, Path(str(dst) + suffix))
    return dst


def sha(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rows_of(path: Path, table: str, *, key: str | None = None) -> dict[int, tuple]:
    """``{row id: (row id, *columns)}`` of a readable table, through the app's factory. A table WITHOUT ROWID has no row id
    and is keyed by its position in primary-key order."""
    con = open_store(path, key=key)
    try:
        try:
            return {int(r[0]): tuple(r) for r in con.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid")}  # noqa: S608 - a test's own name
        except Exception:  # noqa: BLE001 - WITHOUT ROWID: the primary-key order is the only order there is
            return {n: tuple(r) for n, r in enumerate(con.execute(f"SELECT * FROM {table} ORDER BY 1"))}  # noqa: S608
    finally:
        con.close()


def readable_ids(path: Path, table: str = "articles", *, key: str | None = None) -> set[int]:
    """The ids of ``table`` that a read in id order gets to before the first unreadable page, plus the ones after it that a
    seek can reach, found the slow honest way (one id at a time), so a test does not trust the code under test to say what
    could be read."""
    con = open_store(path, key=key)
    ok: set[int] = set()
    try:
        hi = con.execute(f"SELECT max(id) FROM {table}").fetchone()[0]  # noqa: S608
    finally:
        con.close()
    for i in range(1, int(hi) + 1):
        con = open_store(path, key=key)
        try:
            row = con.execute(f"SELECT id FROM {table} WHERE id = ?", (i,)).fetchone()  # noqa: S608
            if row is not None:
                ok.add(i)
        except Exception:  # noqa: BLE001 - an unreadable id is what is being counted
            pass
        finally:
            con.close()
    return ok


def damage_encrypted_pages(path: Path, *, count: int = 3, seed: int = 9, lo: float = 0.2, hi: float = 0.8) -> list[int]:
    """Overwrite ``count`` pages of an encrypted store, chosen by position from the middle of the file."""
    n = os.path.getsize(path) // CIPHER_PAGE
    bad = sorted(random.Random(seed).sample(range(int(n * lo), int(n * hi)), count))
    overwrite_pages(path, bad, CIPHER_PAGE)
    return bad


def damage_encrypted_table(path: Path, table: str, *, count: int = 2, seed: int = 9, key: str | None = None) -> list[int]:
    """Overwrite ``count`` pages that BELONG TO ``table`` of an encrypted store (no ``dbstat`` there to name them): candidate pages
    are tried in a seeded order, a page is kept damaged only when the start-up's per-table check of ``table`` then files it
    ``damaged``, else it is put back. Measured: under SQLCipher a bad page makes ``PRAGMA quick_check(<table>)`` answer either a row
    ("unable to get the page", which is a confirmed verdict) or ``SQLITE_ERROR`` ("SQL logic error", which the start-up files as
    ``unchecked``), depending on which page of which table it is, so a test that needs a CONFIRMED verdict must hit the table."""
    from src.database import verify

    n = os.path.getsize(path) // CIPHER_PAGE
    order = random.Random(seed).sample(range(2, n + 1), n - 1)
    hit: list[int] = []
    for pg in order:
        with open(path, "r+b") as f:
            f.seek((pg - 1) * CIPHER_PAGE)
            old = f.read(CIPHER_PAGE)
            f.seek((pg - 1) * CIPHER_PAGE)
            f.write(random.Random(pg).randbytes(CIPHER_PAGE))
        try:
            # the start-up's own per-table check, so "damaged" here is exactly what the app would file; a schema page that was hit
            # makes the OPEN fail (unchecked), and the schema is not the table under test
            corrupt = verify.check_table(path, table, opener=lambda p: open_store(p, key=key))["verdict"] == verify.VERDICT_DAMAGED
        except Exception:  # noqa: BLE001 - check_table never raises; belt and braces for a test helper
            corrupt = False
        if corrupt:
            hit.append(pg)
            if len(hit) == count:
                break
        else:
            with open(path, "r+b") as f:
                f.seek((pg - 1) * CIPHER_PAGE)
                f.write(old)
    assert len(hit) == count, "no pages of the table could be damaged"
    return sorted(hit)


def reads_clean(path: Path, *, key: str | None = None) -> tuple[bool, list[Any]]:
    """The per-table check of the start-up, on a file: ``(clean, the tables that were not)``."""
    from src.database import salvage

    return salvage.check_copy(path)

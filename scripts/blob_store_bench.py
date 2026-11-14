#!/usr/bin/env python3
"""
Open Omniscience - blob-store benchmark (Q1009 rows 3-6, coordinator ruling R700).
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A DESIGN-AND-BENCHMARK instrument. It changes nothing in the production store and
imports nothing from ``src.database``: every engine below opens its own throwaway
files in a temporary directory that is deleted when the run ends.

What it compares, on the same synthetic corpus and the same access patterns:

  sqlcipher   the CURRENT store: sqlcipher3 with the app's pragmas
              (cipher_page_size=16384, auto_vacuum=INCREMENTAL, WAL,
              synchronous=NORMAL, temp_store=MEMORY, 64 MiB cache), article
              text in the ``articles`` row, FTS5 external-content on it.
  sqlite      stdlib SQLite with the same schema and pragmas, NO encryption.
              The floor: what encryption itself costs on this machine.
  sqlite3mc-chacha20 / sqlite3mc-sqlcipher
              SQLite3 Multiple Ciphers through ``apsw`` (the ``apsw-sqlite3mc``
              wheel), same schema, ChaCha20-Poly1305 and SQLCipher-v4-compatible
              ciphers. Skipped, with the reason in the report, when ``apsw`` is
              not importable or is not the sqlite3mc build. THESE TWO CODE PATHS
              HAVE NEVER BEEN EXECUTED (apsw-sqlite3mc was not installable where this
              script was written); the ChaCha20 engine is set to 256,000 KDF iterations
              so its unlock is comparable, but its KDF hash (SHA-256) and MAC still differ
              from SQLCipher v4's, and the report records that.
  blobpack    the Phase-C PROTOTYPE: metadata + a contentless FTS5 index in
              SQLCipher; article text staged in SQLCipher at ingest, then sealed
              by a packer into fixed-size OOPACK1 packs that reuse OOENC2's STREAM
              framing (AES-256-GCM, counter + final-flag nonce, as
              ``src/safety/crypto.py``) under a per-pack HKDF subkey with the header as
              associated data, addressed by HMAC-SHA-256 under a derived key, with dedup
              by address, opaque random pack names and padding so every pack is the
              same size. Pack writes are crash-ordered: pack to a temp name (0600),
              fsync, rename, fsync every directory involved, THEN one SQL transaction
              moves the index rows. Every read checks the body against its address.
              Run at two frame sizes (4 MiB, the OOENC2 default, and 64 KiB) because
              the frame size decides what a single-article read must decrypt.

Workloads (each the shape of a real app path, named in the report):
  unlock      open + key + first read (PBKDF2 256k for the SQLCipher-format engines).
  ingest      batched inserts (default 200 articles per transaction, the collector's
              batching), article row + FTS row, articles/s.
  pack        (blobpack only) seal every staged body into packs.
  read        the reader: random article ids, title + full body, p50/p95 µs,
              once on a FRESH connection (SQLite page cache cold, OS cache warm)
              and once warm.
  feed        the Feed: newest 100 by published_at, metadata only.
  search      Explore: FTS MATCH on one term, top 50 ids by rank, then the body
              of the top 10 (what a results page with snippets of the first rows reads).
  disk        bytes on disk after the run (db + wal + packs).
  cipher      raw AES-256-GCM vs ChaCha20-Poly1305 over 16 KiB and 64 KiB buffers,
              the question sqlite3mc's ChaCha cipher exists to answer.

SECRETS: every key or passphrase is generated in-process (``secrets``), is
throwaway, is never printed, logged, written to a file or placed in argv. The
corpus is synthetic (seeded Zipf words), never real articles.

Run:  python scripts/blob_store_bench.py [--n 20000] [--repeat 3] [--json out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import random
import secrets
import shutil
import statistics
import struct
import sys
import tempfile
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PAGE_SIZE = 16384  # the ruled fresh-store page size (DB-10 §1b)
AUTO_VACUUM = 2  # INCREMENTAL (DB-10 §1a)
CACHE_KIB = 64 * 1024
PACK_TARGET = 8 * 1024 * 1024  # STORAGE_5TB_PLAN §3-C: ~8-16 MB packs
TAG = 16
PACK_MAGIC = b"OOPACK1\x00"  # the design note's Q-W2: never OOENC2's magic
PACK_VERSION = 1

SCHEMA = [
    """CREATE TABLE articles (
        id INTEGER PRIMARY KEY,
        url TEXT NOT NULL,
        source_id INTEGER NOT NULL,
        title TEXT,
        content TEXT NOT NULL,
        published_at TEXT,
        language TEXT,
        hash TEXT NOT NULL UNIQUE)""",
    "CREATE INDEX ix_articles_published ON articles(published_at)",
    """CREATE VIRTUAL TABLE article_fts USING fts5(
        title, content, content='articles', content_rowid='id', tokenize='unicode61')""",
]

# blobpack: content leaves the row; the FTS index is contentless (STORAGE_5TB_PLAN Phase B)
BLOB_SCHEMA = [
    """CREATE TABLE articles (
        id INTEGER PRIMARY KEY,
        url TEXT NOT NULL,
        source_id INTEGER NOT NULL,
        title TEXT,
        blob_addr BLOB NOT NULL,
        published_at TEXT,
        language TEXT,
        hash TEXT NOT NULL UNIQUE)""",
    "CREATE INDEX ix_articles_published ON articles(published_at)",
    "CREATE INDEX ix_articles_blob ON articles(blob_addr)",
    """CREATE VIRTUAL TABLE article_fts USING fts5(
        title, content, content='', contentless_delete=1, tokenize='unicode61')""",
    # bodies not yet sealed into a pack: same consistency domain as the article row
    "CREATE TABLE blob_staging (id INTEGER PRIMARY KEY, addr BLOB NOT NULL UNIQUE, body BLOB NOT NULL)",
    """CREATE TABLE blobs (addr BLOB PRIMARY KEY, pack_id INTEGER NOT NULL,
        off INTEGER NOT NULL, len INTEGER NOT NULL, codec INTEGER NOT NULL) WITHOUT ROWID""",
    """CREATE TABLE packs (id INTEGER PRIMARY KEY, name BLOB NOT NULL UNIQUE,
        frame INTEGER NOT NULL, n_frames INTEGER NOT NULL, plain_len INTEGER NOT NULL,
        ct_len INTEGER NOT NULL)""",
]


# --------------------------------------------------------------------------- corpus
def make_corpus(n: int, seed: int, dup_rate: float) -> list[dict[str, Any]]:
    """Synthetic articles: Zipf-distributed words from a fixed vocabulary, lognormal
    body length (median ~3 KB, capped at 120 KB), a ``dup_rate`` share of bodies that
    are byte-identical copies of an earlier body under a different URL (syndication)."""
    rng = random.Random(seed)
    letters = "abcdefghijklmnopqrstuvwxyz"
    vocab = ["".join(rng.choice(letters) for _ in range(rng.randint(3, 10))) for _ in range(30000)]
    weights = [1.0 / (i + 1) for i in range(len(vocab))]
    cum: list[float] = []
    s = 0.0
    for w in weights:
        s += w
        cum.append(s)

    def words(k: int) -> str:
        return " ".join(rng.choices(vocab, cum_weights=cum, k=k))

    out: list[dict[str, Any]] = []
    t0 = 1_700_000_000
    for i in range(n):
        if out and rng.random() < dup_rate:
            body = out[rng.randrange(len(out))]["content"]
        else:
            nbytes = min(int(rng.lognormvariate(8.0, 0.9)), 120_000)
            body = words(max(20, nbytes // 7))
        title = words(rng.randint(5, 12))
        url = f"https://example.invalid/{i}/{rng.getrandbits(48):x}"
        out.append(
            {
                "id": i + 1,
                "url": url,
                "source_id": rng.randint(1, 400),
                "title": title,
                "content": body,
                "published_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime(t0 + i * 37 + rng.randint(0, 3600))
                ),
                "language": "en",
                "hash": hashlib.sha256(url.encode() + body.encode()).hexdigest(),
            }
        )
    return out


# --------------------------------------------------------------------------- engines
def _esc(value: str) -> str:
    return value.replace("'", "''")


class Conn:
    """A thin uniform wrapper: explicit BEGIN/COMMIT on every driver."""

    def __init__(self, raw: Any, kind: str) -> None:
        self.raw, self.kind = raw, kind

    def execute(self, sql: str, params: tuple | list = ()) -> list[tuple]:
        cur = self.raw.cursor()
        try:
            cur.execute(sql, params)
            return list(cur.fetchall()) if self.kind != "apsw" else list(cur)
        finally:
            cur.close()

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        cur = self.raw.cursor()
        try:
            cur.executemany(sql, rows)
        finally:
            cur.close()

    def close(self) -> None:
        self.raw.close()


def _pragmas(c: Conn, encrypted: bool) -> None:
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute(f"PRAGMA cache_size=-{CACHE_KIB}")
    c.execute("PRAGMA temp_store=MEMORY")
    if not encrypted:
        c.execute("PRAGMA mmap_size=268435456")  # the app does this for plaintext stores only


def open_sqlite(path: Path, secret: str, fresh: bool) -> Conn:
    import sqlite3

    c = Conn(sqlite3.connect(str(path), isolation_level=None), "sqlite3")
    if fresh:
        c.execute(f"PRAGMA page_size={PAGE_SIZE}")
        c.execute(f"PRAGMA auto_vacuum={AUTO_VACUUM}")
    _pragmas(c, encrypted=False)
    return c


def open_sqlcipher(path: Path, secret: str, fresh: bool) -> Conn:
    import sqlcipher3

    c = Conn(sqlcipher3.connect(str(path), isolation_level=None), "sqlcipher3")
    c.execute(f"PRAGMA key = '{_esc(secret)}'")  # in-process throwaway secret, never logged
    c.execute(f"PRAGMA cipher_page_size = {PAGE_SIZE}")
    if fresh:
        c.execute(f"PRAGMA auto_vacuum={AUTO_VACUUM}")
    _pragmas(c, encrypted=True)
    return c


def _sqlite3mc_available() -> str | None:
    try:
        import apsw
    except ImportError:
        return "apsw is not importable (apsw-sqlite3mc not installed)"
    probe = apsw.Connection(":memory:")
    try:
        rows = list(probe.execute("PRAGMA cipher"))
    except Exception as exc:  # noqa: BLE001 - any failure means "not the sqlite3mc build"
        return f"apsw is importable but PRAGMA cipher failed: {type(exc).__name__}"
    finally:
        probe.close()
    if not rows:
        return "apsw is importable but is not the sqlite3mc build (PRAGMA cipher returned nothing)"
    return None


def make_open_sqlite3mc(cipher: str) -> Callable[[Path, str, bool], Conn]:
    def _open(path: Path, secret: str, fresh: bool) -> Conn:
        import apsw

        c = Conn(apsw.Connection(str(path)), "apsw")
        c.execute(f"PRAGMA cipher = '{cipher}'")
        if cipher == "chacha20":
            c.execute("PRAGMA kdf_iter = 256000")  # SQLCipher v4's count; the hash stays SHA-256
        if cipher == "sqlcipher":
            c.execute("PRAGMA legacy = 4")  # SQLCipher v4 defaults: PBKDF2-SHA512 256k, HMAC-SHA512
            c.execute(f"PRAGMA legacy_page_size = {PAGE_SIZE}")
        c.execute(f"PRAGMA key = '{_esc(secret)}'")  # in-process throwaway secret, never logged
        if fresh:
            if cipher != "sqlcipher":
                c.execute(f"PRAGMA page_size={PAGE_SIZE}")
            c.execute(f"PRAGMA auto_vacuum={AUTO_VACUUM}")
        _pragmas(c, encrypted=True)
        return c

    return _open


def cipher_versions(kind: str) -> dict[str, str]:
    try:
        if kind == "sqlite":
            import sqlite3

            return {"sqlite": sqlite3.sqlite_version}
        if kind in ("sqlcipher", "blobpack-4m", "blobpack-64k"):
            import sqlcipher3

            c = sqlcipher3.connect(":memory:")
            v = {
                "sqlite": c.execute("select sqlite_version()").fetchone()[0],
                "sqlcipher": c.execute("pragma cipher_version").fetchone()[0],
                "sqlcipher3_module": getattr(sqlcipher3, "__version__", "?"),
            }
            c.close()
            return v
        if kind.startswith("sqlite3mc"):
            import apsw

            kdf = (
                "PBKDF2-HMAC-SHA256 x256,000 (kdf_iter set; MAC Poly1305)"
                if kind.endswith("chacha20")
                else "SQLCipher v4 legacy: PBKDF2-HMAC-SHA512 x256,000, HMAC-SHA512"
            )
            return {"sqlite": apsw.sqlite_lib_version(), "apsw": apsw.apsw_version(), "kdf": kdf}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}
    return {}


# --------------------------------------------------------------------------- blob store prototype
class BlobStore:
    """Phase-C prototype of the design note's §3-§6. Keys come from one in-process master
    secret through HKDF with explicit domain labels; nothing here persists a key (the real
    store would keep the master key inside SQLCipher, which this benchmark does not model).

    Pack layout: header = PACK_MAGIC(8) | version(1) | frame(4) | n_frames(4) | name(16),
    then n_frames AES-256-GCM frames (STREAM nonce: 7 zero bytes | counter | final flag),
    each under a per-pack subkey HKDF(pack key, "oo/v1/pack-subkey\\0" + name) and with the
    header as associated data. Every pack holds exactly PACK_TARGET plaintext bytes (bodies
    then zero padding, all inside the AEAD), so its size says nothing about what it holds."""

    def __init__(
        self,
        root: Path,
        master: bytes,
        frame: int,
        compress: Callable[[bytes], bytes] | None,
        decompress: Callable[[bytes], bytes] | None,
        codec_id: int,
    ) -> None:
        self.root, self.frame = root, frame
        self.k_addr = self._hkdf(master, b"oo/v1/blob-address")
        self.k_pack = self._hkdf(master, b"oo/v1/pack-aead")
        self.compress, self.decompress, self.codec_id = compress, decompress, codec_id
        self._pack_cache: dict[int, tuple[bytes, int, int, AESGCM, bytes]] = {}
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _fsync_dir(self.root.parent)

    @staticmethod
    def _hkdf(master: bytes, info: bytes) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)

    def address(self, body: bytes) -> bytes:
        return hmac.new(self.k_addr, body, hashlib.sha256).digest()

    def _cipher(self, name: bytes) -> AESGCM:
        return AESGCM(self._hkdf(self.k_pack, b"oo/v1/pack-subkey\x00" + name))

    @staticmethod
    def _nonce(counter: int, final: bool) -> bytes:
        # the subkey is unique per pack, so the nonce only has to be unique inside one pack
        return bytes(7) + struct.pack(">I", counter) + (b"\x01" if final else b"\x00")

    @staticmethod
    def _header(name: bytes, frame: int, n_frames: int) -> bytes:
        return PACK_MAGIC + bytes([PACK_VERSION]) + struct.pack(">II", frame, n_frames) + name

    def _pack_path(self, name: bytes) -> Path:
        h = name.hex()
        return self.root / h[:2] / h

    def seal(self, c: Conn, *, flush_partial: bool = True) -> dict[str, float]:
        """Move staged bodies into fixed-size packs. Order: pack bytes durable on disk first
        (file fsync, rename, fsync of every directory on the path that this call created),
        then ONE SQL transaction per pack that indexes it and drops the staging rows. A crash
        between the two leaves an unreferenced pack, never a reference to absent bytes.
        ``flush_partial`` pads and seals the last, part-full pack (the real packer would wait
        for a full pack or a maximum age; padding keeps the size constant either way)."""
        staged = c.execute("SELECT id, addr, body FROM blob_staging ORDER BY id")
        packs = 0
        bytes_in = 0
        pad_bytes = 0
        i = 0
        while i < len(staged):
            buf = bytearray()
            entries: list[tuple[int, bytes, int, int]] = []
            pending_in = 0
            while i < len(staged):
                sid, addr, body = staged[i]
                body = bytes(body)
                stored = self.compress(body) if self.compress else body
                if len(stored) > PACK_TARGET:
                    raise ValueError(
                        "a body larger than one pack needs a size class (open question)"
                    )
                if len(buf) + len(stored) > PACK_TARGET:
                    break
                entries.append((sid, addr, len(buf), len(stored)))
                buf += stored
                pending_in += len(body)
                i += 1
            used = len(buf)
            if i >= len(staged) and used < PACK_TARGET and not flush_partial:
                break  # leave the part-full last pack staged
            pad_bytes += PACK_TARGET - used
            buf += bytes(PACK_TARGET - used)
            name = secrets.token_bytes(16)  # opaque: says nothing about content or order
            n_frames = -(-PACK_TARGET // self.frame)
            header = self._header(name, self.frame, n_frames)
            aead = self._cipher(name)
            path = self._pack_path(name)
            created = not path.parent.exists()
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if created:
                _fsync_dir(self.root)
            tmp = path.with_name(path.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(header)
                for k in range(n_frames):
                    chunk = bytes(buf[k * self.frame : (k + 1) * self.frame])
                    f.write(aead.encrypt(self._nonce(k, k == n_frames - 1), chunk, header))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            _fsync_dir(path.parent)
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT INTO packs(name, frame, n_frames, plain_len, ct_len) VALUES (?,?,?,?,?)",
                (name, self.frame, n_frames, used, path.stat().st_size),
            )
            pack_id = c.execute("SELECT last_insert_rowid()")[0][0]
            c.executemany(
                "INSERT INTO blobs(addr, pack_id, off, len, codec) VALUES (?,?,?,?,?)",
                [(a, pack_id, off, ln, self.codec_id) for _, a, off, ln in entries],
            )
            c.executemany("DELETE FROM blob_staging WHERE id = ?", [(s,) for s, _, _, _ in entries])
            c.execute("COMMIT")
            packs += 1
            bytes_in += pending_in
        return {"packs": packs, "plain_bytes": bytes_in, "padding_bytes": pad_bytes}

    def read(self, c: Conn, addr: bytes) -> bytes:
        row = c.execute("SELECT pack_id, off, len, codec FROM blobs WHERE addr = ?", (addr,))
        if not row:
            staged = c.execute("SELECT body FROM blob_staging WHERE addr = ?", (addr,))
            if not staged:
                raise ValueError("address not found in packs or staging")
            body = bytes(staged[0][0])
        else:
            pack_id, off, ln, codec = row[0]
            meta = self._pack_cache.get(pack_id)
            if meta is None:
                p = c.execute("SELECT name, frame, n_frames FROM packs WHERE id = ?", (pack_id,))[0]
                name = bytes(p[0])
                meta = (
                    name,
                    int(p[1]),
                    int(p[2]),
                    self._cipher(name),
                    self._header(name, int(p[1]), int(p[2])),
                )
                self._pack_cache[pack_id] = meta
            name, frame, n_frames, aead, header = meta  # the pack's own recorded frame size
            first, last = off // frame, (off + ln - 1) // frame
            out = bytearray()
            # the file's length is NOT checked against packs.ct_len here; the design checks it
            # at open and at restore (note §8), so a truncated padding tail goes unseen here
            with open(self._pack_path(name), "rb") as f:
                if f.read(len(header)) != header:  # the file must be the pack the index names
                    raise ValueError("pack header does not match its index row")
                f.seek(len(header) + first * (frame + TAG))
                for k in range(first, last + 1):
                    out += aead.decrypt(
                        self._nonce(k, k == n_frames - 1), f.read(frame + TAG), header
                    )
            start = off - first * frame
            stored = bytes(out[start : start + ln])
            body = self.decompress(stored) if (codec and self.decompress) else stored
        if not hmac.compare_digest(
            self.address(body), addr
        ):  # the bytes must be the body asked for
            raise ValueError("body does not match its address")
        return body


def _fsync_dir(path: Path) -> None:
    dfd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


# --------------------------------------------------------------------------- workloads
def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[k]


def _dir_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def run_engine(
    name: str,
    opener: Callable[[Path, str, bool], Conn],
    corpus: list[dict[str, Any]],
    args: argparse.Namespace,
    workdir: Path,
    blob_frame: int | None,
) -> dict[str, Any]:
    rng = random.Random(args.seed + 1)
    secret = secrets.token_urlsafe(24)  # throwaway; never leaves this process
    master = secrets.token_bytes(32)
    db = workdir / "store.db"
    res: dict[str, Any] = {"engine": name}
    store: BlobStore | None = None
    if blob_frame is not None:
        comp, decomp, codec = _codec(args.codec)
        res["codec"] = {0: "none", 1: "zlib-6", 2: "zstd-3"}[codec]
        store = BlobStore(workdir / "packs", master, blob_frame, comp, decomp, codec)

    # ingest
    c = opener(db, secret, True)
    for stmt in BLOB_SCHEMA if store else SCHEMA:
        c.execute(stmt)
    t0 = time.perf_counter()
    dedup_hits = 0
    for b in range(0, len(corpus), args.batch):
        batch = corpus[b : b + args.batch]
        c.execute("BEGIN IMMEDIATE")
        if store is None:
            c.executemany(
                "INSERT INTO articles(id,url,source_id,title,content,published_at,language,hash) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        a["id"],
                        a["url"],
                        a["source_id"],
                        a["title"],
                        a["content"],
                        a["published_at"],
                        a["language"],
                        a["hash"],
                    )
                    for a in batch
                ],
            )
            c.executemany(
                "INSERT INTO article_fts(rowid,title,content) VALUES (?,?,?)",
                [(a["id"], a["title"], a["content"]) for a in batch],
            )
        else:
            rows = []
            for a in batch:
                body = a["content"].encode()
                addr = store.address(body)
                known = c.execute(
                    "SELECT 1 FROM blobs WHERE addr=? UNION ALL SELECT 1 FROM blob_staging WHERE addr=?",
                    (addr, addr),
                )
                if known:
                    dedup_hits += 1
                else:
                    c.execute("INSERT INTO blob_staging(addr, body) VALUES (?,?)", (addr, body))
                rows.append(
                    (
                        a["id"],
                        a["url"],
                        a["source_id"],
                        a["title"],
                        addr,
                        a["published_at"],
                        a["language"],
                        a["hash"],
                    )
                )
            c.executemany(
                "INSERT INTO articles(id,url,source_id,title,blob_addr,published_at,language,hash) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            c.executemany(
                "INSERT INTO article_fts(rowid,title,content) VALUES (?,?,?)",
                [(a["id"], a["title"], a["content"]) for a in batch],
            )
        c.execute("COMMIT")
    dt = time.perf_counter() - t0
    plain_mb = sum(len(a["content"]) for a in corpus) / 1e6
    res["ingest"] = {
        "seconds": dt,
        "articles_per_s": len(corpus) / dt,
        "body_mb_per_s": plain_mb / dt,
    }
    if store is not None:
        res["ingest"]["dedup_hits"] = dedup_hits
        t0 = time.perf_counter()
        sealed = store.seal(c)
        res["pack"] = {"seconds": time.perf_counter() - t0, **sealed}
        # the staging rows the packer dropped leave free pages; the app's idle maintenance
        # reclaims them with a bounded incremental_vacuum (DB-10 §3), so the disk figure does too
        t0 = time.perf_counter()
        c.execute("PRAGMA incremental_vacuum")
        res["pack"]["incremental_vacuum_s"] = time.perf_counter() - t0
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()

    # unlock (fresh process-level connection, first read)
    unlocks = []
    for _ in range(3):
        t0 = time.perf_counter()
        c = opener(db, secret, False)
        c.execute("SELECT count(*) FROM articles")
        unlocks.append(time.perf_counter() - t0)
        c.close()
    res["unlock_s"] = statistics.median(unlocks)

    ids = [rng.randint(1, len(corpus)) for _ in range(args.reads)]

    def read_one(conn: Conn, i: int) -> int:
        if store is None:
            r = conn.execute("SELECT title, content FROM articles WHERE id=?", (i,))
            return len(r[0][1])
        r = conn.execute("SELECT title, blob_addr FROM articles WHERE id=?", (i,))
        return len(store.read(conn, bytes(r[0][1])))

    for label in ("read_cold_conn", "read_warm"):
        c = opener(db, secret, False)
        if store is not None:
            store._pack_cache.clear()
        if label == "read_warm":
            for i in ids:
                read_one(c, i)
        lat = []
        for i in ids:
            t0 = time.perf_counter()
            read_one(c, i)
            lat.append((time.perf_counter() - t0) * 1e6)
        res[label] = {"p50_us": _pct(lat, 0.5), "p95_us": _pct(lat, 0.95), "n": len(lat)}
        c.close()

    c = opener(db, secret, False)
    lat = []
    for _ in range(args.feed):
        t0 = time.perf_counter()
        c.execute(
            "SELECT id, title, source_id, published_at FROM articles ORDER BY published_at DESC LIMIT 100"
        )
        lat.append((time.perf_counter() - t0) * 1e6)
    res["feed"] = {"p50_us": _pct(lat, 0.5), "p95_us": _pct(lat, 0.95), "n": len(lat)}

    terms = corpus[0]["title"].split() + corpus[1]["title"].split()
    terms = terms[: args.searches] or ["a"]
    lat = []
    for t in terms:
        t0 = time.perf_counter()
        hits = c.execute(
            "SELECT rowid FROM article_fts WHERE article_fts MATCH ? ORDER BY rank LIMIT 50",
            (f'"{t}"',),
        )
        for (rid,) in hits[:10]:
            read_one(c, rid)
        lat.append((time.perf_counter() - t0) * 1e6)
    res["search"] = {"p50_us": _pct(lat, 0.5), "p95_us": _pct(lat, 0.95), "n": len(lat)}
    c.close()

    res["disk_bytes"] = _dir_bytes(workdir)
    res["disk_breakdown"] = {
        "db": db.stat().st_size,
        "wal": (workdir / "store.db-wal").stat().st_size
        if (workdir / "store.db-wal").exists()
        else 0,
        "packs": _dir_bytes(workdir / "packs") if (workdir / "packs").exists() else 0,
    }
    res["plain_body_bytes"] = int(plain_mb * 1e6)
    return res


def _codec(
    name: str,
) -> tuple[Callable[[bytes], bytes] | None, Callable[[bytes], bytes] | None, int]:
    if name == "none":
        return None, None, 0
    if name == "zstd":
        try:
            import zstandard

            cz, dz = zstandard.ZstdCompressor(level=3), zstandard.ZstdDecompressor()
            return cz.compress, dz.decompress, 2
        except ImportError:
            pass  # fall through to zlib; the report's "codec" field names the one used
    return (lambda b: zlib.compress(b, 6)), zlib.decompress, 1


def cipher_bench(seconds: float = 0.5) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, cls in (("aes256gcm", AESGCM), ("chacha20poly1305", ChaCha20Poly1305)):
        aead = cls(secrets.token_bytes(32))
        for size in (16384, 65536):
            data = os.urandom(size)
            n = 0
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < seconds:
                aead.encrypt(os.urandom(12), data, None)
                n += 1
            dt = time.perf_counter() - t0
            out[f"{label}_{size // 1024}k_MBps"] = n * size / dt / 1e6
    return out


def machine() -> dict[str, Any]:
    flags = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("flags"):
                flags = line
                break
        model = next(
            (
                ln.split(":", 1)[1].strip()
                for ln in Path("/proc/cpuinfo").read_text().splitlines()
                if ln.startswith("model name")
            ),
            platform.processor(),
        )
    except OSError:
        model = platform.processor()
    return {
        "cpu": model,
        "aes_ni": " aes " in f" {flags} ",
        "cpus": os.cpu_count(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=20000, help="articles in the synthetic corpus")
    ap.add_argument(
        "--repeat", type=int, default=3, help="runs per engine; the report keeps the median"
    )
    ap.add_argument("--batch", type=int, default=200, help="articles per ingest transaction")
    ap.add_argument("--reads", type=int, default=2000)
    ap.add_argument("--feed", type=int, default=200)
    ap.add_argument("--searches", type=int, default=20)
    ap.add_argument(
        "--dup-rate", type=float, default=0.2, help="share of byte-identical bodies (syndication)"
    )
    ap.add_argument(
        "--codec", choices=("none", "zlib", "zstd"), default="none", help="blobpack body codec"
    )
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument(
        "--engines",
        default="sqlite,sqlcipher,sqlite3mc-chacha20,sqlite3mc-sqlcipher,blobpack-4m,blobpack-64k",
    )
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument(
        "--tmp", type=Path, help="parent for the throwaway work dirs (default: system temp)"
    )
    args = ap.parse_args(argv)

    corpus = make_corpus(args.n, args.seed, args.dup_rate)
    mc_reason = _sqlite3mc_available()
    openers: dict[str, tuple[Callable[[Path, str, bool], Conn], int | None]] = {
        "sqlite": (open_sqlite, None),
        "sqlcipher": (open_sqlcipher, None),
        "sqlite3mc-chacha20": (make_open_sqlite3mc("chacha20"), None),
        "sqlite3mc-sqlcipher": (make_open_sqlite3mc("sqlcipher"), None),
        "blobpack-4m": (open_sqlcipher, 4 * 1024 * 1024),
        "blobpack-64k": (open_sqlcipher, 64 * 1024),
    }
    report: dict[str, Any] = {
        "machine": machine(),
        "params": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "corpus": {
            "articles": len(corpus),
            "body_bytes": sum(len(a["content"]) for a in corpus),
            "median_body_bytes": statistics.median(len(a["content"]) for a in corpus),
        },
        "cipher": cipher_bench(),
        "engines": {},
        "skipped": {},
    }
    for name in [e.strip() for e in args.engines.split(",") if e.strip()]:
        if name not in openers:
            report["skipped"][name] = "unknown engine"
            continue
        if name.startswith("sqlite3mc") and mc_reason:
            report["skipped"][name] = mc_reason
            continue
        opener, frame = openers[name]
        runs = []
        for r in range(args.repeat):
            wd = Path(tempfile.mkdtemp(prefix=f"oo-blobbench-{name}-", dir=args.tmp))
            try:
                runs.append(run_engine(name, opener, corpus, args, wd, frame))
            finally:
                shutil.rmtree(wd, ignore_errors=True)
            print(f"{name} run {r + 1}/{args.repeat} done", file=sys.stderr)
        report["engines"][name] = {
            "versions": cipher_versions(name),
            "runs": runs,
            "median": _median_runs(runs),
        }
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        args.json.write_text(text)
    print(text)
    return 0


def _median_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    def walk(vals: list[Any]) -> Any:
        if isinstance(vals[0], dict):
            return {k: walk([v[k] for v in vals]) for k in vals[0]}
        if isinstance(vals[0], (int, float)) and not isinstance(vals[0], bool):
            return statistics.median(vals)
        return vals[0]

    return walk(runs)


if __name__ == "__main__":
    raise SystemExit(main())

"""Row 410-A (R829 A): an import's staged corpus and custody log are never left on disk in plaintext.

A1, an encrypted member (the normal volume set), is read in place under the passphrase that opens it; A2, everything
else, is sealed as soon as it is staged under a random key held only in this process. What is pinned here:

- every reader path stages no plaintext SQLite header: a volume set with an encrypted corpus, one with a plaintext
  corpus, a legacy oo-volumes-1 set, an uploaded zip (bare, OOENC1-wrapped), a bare SQLite upload, a legacy ``.ooenc``,
  and the custody log beside each (condition 5);
- a key reaches SQLite only through the C API or a bound ``KEY ?``: never SQL text, never a statement trace (which
  expands bound values), never a ``repr``, never a pickle, never an exception's text (condition 2);
- the sealing key is random per file and never written; a sealed file is owner-only and its plaintext is gone
  (condition 3);
- a staged schema holding a trigger, view or virtual table the app does not make is refused before a row is read
  (condition 2, R826 b);
- the merge of a keyed staged copy writes exactly what the merge of the plaintext one writes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import artifact, staged_key
from src.backup.artifact import BACKUP_SCHEMA, cleanup_staging, read_artifact, read_volume_backup
from src.backup.stream_backup import CorpusSource, _no_freeze, read_stream_backup, write_stream_backup
from src.reporting.evidence import canonical_bytes

_HEADER = b"SQLite format 3\x00"
_PLANTED = "planted-corpus-passphrase-410A-QxV7"


def _db(path: Path, n: int = 60) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
    )
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i}", "z" * 400) for i in range(n)])
    con.commit()
    con.close()
    return path


def _custody(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE custody_entries(seq INTEGER PRIMARY KEY, item TEXT)")
    con.executemany("INSERT INTO custody_entries(item) VALUES(?)", [(f"e{i}",) for i in range(20)])
    con.commit()
    con.close()
    return path


def _plaintext_files(folder: Path) -> list[str]:
    """Every file under ``folder`` whose first bytes are a plaintext SQLite header."""
    found = []
    for top, _dirs, files in os.walk(folder):
        for f in files:
            p = Path(top, f)
            with open(p, "rb") as fh:
                if fh.read(16) == _HEADER:
                    found.append(str(p.relative_to(folder)))
    return found


def _signed_zip(members: dict[str, bytes]) -> bytes:
    key = Ed25519PrivateKey.generate()
    manifest = {
        "backup_schema": BACKUP_SCHEMA, "app_version": "test", "alembic_rev": "rev",
        "created_at": "2026-11-24T00:00:00+00:00", "encrypted": True, "keys_included": False,
        "members": [
            {"name": n, "role": "corpus" if n == "corpus.db" else "custody", "sha256": hashlib.sha256(b).hexdigest(),
             "bytes": len(b)}
            for n, b in members.items()
        ],
        "excluded": {}, "corpus": {},
    }
    envelope = {
        "manifest": manifest, "signature": key.sign(canonical_bytes(manifest)).hex(),
        "public_key": key.public_key().public_bytes_raw().hex(), "algorithm": "ed25519",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(envelope))
        for n, b in members.items():
            zf.writestr(n, b)
    return buf.getvalue()


def _assert_sealed(staged) -> None:
    assert staged.hash_failures == []
    assert _plaintext_files(staged.staging_dir) == [], "a plaintext SQLite file is in the staging folder"
    for p in [staged.corpus_path, staged.custody_path]:
        if p is None:
            continue
        key = staged_key.key_for(p)
        assert key is not None, p.name
        c = staged_key.open_staged(p)
        try:
            assert c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0
        finally:
            c.close()


# --------------------------------------------------------------------------- the five reader paths


def _volume_set(tmp_path: Path, *, encrypted: bool):
    from src.database.connect import connect

    corpus = tmp_path / "src-corpus.db"
    if encrypted:
        con = connect(corpus, key=_PLANTED)
        con.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);")
        con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i}", "z" * 400) for i in range(60)])
        con.commit()
        con.close()
    else:
        _db(corpus)
    dest = tmp_path / "dest"
    write_stream_backup(
        dest, "backup-pw",
        corpus_source=CorpusSource(
            path=corpus, member_name="corpus.db.sqlcipher" if encrypted else "corpus.db", encrypted=encrypted,
            freeze=_no_freeze, facts_key=_PLANTED if encrypted else None,
        ),
        side_members=[], volume_size=65536,
    )
    return dest


@pytest.mark.parametrize("encrypted", [True, False], ids=["A1-encrypted-member", "A2-plaintext-member"])
def test_a_volume_set_stages_no_plaintext(tmp_path, encrypted):
    dest = _volume_set(tmp_path, encrypted=encrypted)
    staged = read_stream_backup(
        dest, "backup-pw", staging_root=tmp_path / "st", corpus_passphrase=_PLANTED if encrypted else None
    )
    try:
        _assert_sealed(staged)
        assert staged_key.key_for(staged.corpus_path).origin == ("member" if encrypted else "ephemeral")
        assert "seal" in staged.stage_a_timings
        assert not any(n.endswith(".sealing") for n in os.listdir(staged.staging_dir))
    finally:
        cleanup_staging(staged)
    assert not staged_key.is_keyed(staged.corpus_path), "the key outlived its staging folder"


def test_a_legacy_volume_set_stages_no_plaintext(tmp_path):
    from src.backup.volumes import write_volume_set

    corpus = _db(tmp_path / "c.db").read_bytes()
    custody = _custody(tmp_path / "k.db").read_bytes()
    z = tmp_path / "a.zip"
    z.write_bytes(_signed_zip({"corpus.db": corpus, "custody_log.db": custody}))
    write_volume_set(z, tmp_path / "vols", "pw", volume_size=4096, chunk_size=2048)
    staged = read_volume_backup(tmp_path / "vols", "pw", staging_root=tmp_path / "st")
    try:
        _assert_sealed(staged)
        assert staged.custody_path is not None and staged_key.key_for(staged.custody_path).origin == "ephemeral"
    finally:
        cleanup_staging(staged)


@pytest.mark.parametrize("wrapped", [False, True], ids=["zip", "OOENC1-zip"])
def test_an_uploaded_zip_stages_no_plaintext(tmp_path, wrapped):
    from src.safety.crypto import encrypt_bytes

    blob = _signed_zip({"corpus.db": _db(tmp_path / "c.db").read_bytes(),
                        "custody_log.db": _custody(tmp_path / "k.db").read_bytes()})
    if wrapped:
        blob = encrypt_bytes(blob, "upload-pw")
    staged = read_artifact(blob, "upload-pw" if wrapped else None, staging_root=tmp_path / "st")
    try:
        _assert_sealed(staged)
    finally:
        cleanup_staging(staged)


@pytest.mark.parametrize("wrapped", [False, True], ids=["bare-sqlite", "legacy-ooenc"])
def test_a_bare_database_upload_stages_no_plaintext(tmp_path, wrapped):
    from src.safety.crypto import encrypt_bytes

    blob = _db(tmp_path / "c.db").read_bytes()
    if wrapped:
        blob = encrypt_bytes(blob, "upload-pw")
    staged = read_artifact(blob, "upload-pw" if wrapped else None, staging_root=tmp_path / "st")
    try:
        _assert_sealed(staged)
        assert staged_key.key_for(staged.corpus_path).origin == "ephemeral"
    finally:
        cleanup_staging(staged)


def test_a_file_that_is_not_a_database_is_left_for_the_validation_to_refuse(tmp_path):
    staged = read_artifact(_HEADER + b"not really" * 50, staging_root=tmp_path / "st")
    try:
        assert not staged_key.is_keyed(staged.corpus_path)
        from src.backup.sqlite_backup import BackupError, validate_sqlite_file

        with pytest.raises(BackupError):
            validate_sqlite_file(staged.corpus_path)
    finally:
        cleanup_staging(staged)


# --------------------------------------------------------------------------- the key


def test_a_sealed_copy_is_owner_only_keyed_at_random_and_its_plaintext_is_gone(tmp_path):
    secrets_seen = set()
    for i in range(2):
        p = _db(tmp_path / f"s{i}.db")
        wal = p.with_name(p.name + "-wal")
        wal.write_bytes(b"")
        staged_key.seal_plaintext(p)
        try:
            key = staged_key.key_for(p)
            assert key.origin == "ephemeral"
            assert key.secret.startswith(b"x'") and len(key.secret) == 67, "a raw 256-bit key, not a passphrase"
            secrets_seen.add(key.secret)
            assert p.read_bytes()[:16] != _HEADER
            assert key.secret not in p.read_bytes() and key.secret[2:66] not in p.read_bytes()
            if os.name != "nt":
                assert stat.S_IMODE(p.stat().st_mode) == 0o600
            assert not wal.exists() and not p.with_name(p.name + ".sealing").exists()
            with pytest.raises(sqlite3.DatabaseError):
                sqlite3.connect(p).execute("SELECT count(*) FROM articles").fetchone()
            c = staged_key.open_staged(p)
            try:
                assert c.execute("SELECT count(*) FROM articles").fetchone() == (60,)
            finally:
                c.close()
        finally:
            staged_key.forget(p)
    assert len(secrets_seen) == 2, "two seals shared a key"


def test_a_key_never_reaches_sql_text_a_trace_a_repr_or_a_pickle(tmp_path):
    p = _db(tmp_path / "s.db")
    staged_key.seal_plaintext(p)
    key = staged_key.key_for(p)
    hex_of_secret = key.secret.hex()  # how SQLite writes a blob value expanded into a traced statement
    try:
        sqc = staged_key._driver()
        host = sqc.connect(":memory:")
        traced: list[str] = []
        host.set_trace_callback(traced.append)  # a trace expands bound values: attach_staged must not be watched
        assert staged_key.attach_staged(host, p, "inc")
        assert host.execute("SELECT count(*) FROM inc.articles").fetchone() == (60,)
        host.close()
        for text in traced:
            assert key.secret.decode() not in text and hex_of_secret not in text.lower() and key.secret[2:66].decode() not in text
        assert not any("ATTACH" in t.upper() for t in traced), "the ATTACH was traced"
        for shown in (repr(key), str(key), repr(staged_key._registry)):
            assert key.secret.decode() not in shown and key.secret[2:66].decode() not in shown
        with pytest.raises(TypeError):
            pickle.dumps(key)
    finally:
        staged_key.forget(p)


def test_a_staged_copy_that_no_longer_opens_says_so_in_fixed_words(tmp_path):
    p = _db(tmp_path / "s.db")
    staged_key.seal_plaintext(p)
    key = staged_key.key_for(p)
    try:
        staged_key.register(p, staged_key.StagedKey(secret=b"x'" + b"00" * 32 + b"'", page_size=key.page_size,
                                                    origin="ephemeral"))
        with pytest.raises(staged_key.StagedKeyError) as refused:
            staged_key.open_staged(p)
        assert str(refused.value) == "the staged copy of the backup no longer opens with its key"
        assert refused.value.__cause__ is None and refused.value.__context__ is None
    finally:
        staged_key.forget(p)


def test_a_plaintext_install_attaches_a_keyed_copy_through_a_keyless_host(tmp_path):
    """A plaintext working copy opened with ``sqlcipher_host`` attaches a keyed staged copy (A2 on a plaintext
    install), and the plaintext file stays plaintext: nothing claims it encrypted."""
    from src.database.connect import attach, connect

    work = _db(tmp_path / "work.db", n=1)
    p = _db(tmp_path / "s.db")
    staged_key.seal_plaintext(p)
    try:
        con = connect(work, sqlcipher_host=True)
        try:
            attach(con, p, "inc")
            assert con.execute("SELECT count(*) FROM inc.articles").fetchone() == (60,)
        finally:
            con.close()
        assert work.read_bytes()[:16] == _HEADER
    finally:
        staged_key.forget(p)


# --------------------------------------------------------------------------- the schema of a foreign file


@pytest.fixture()
def known(monkeypatch):
    objs = {"article_fts": "table", "article_fts_ai": "trigger", "keyword_mentions_all": "view"}
    monkeypatch.setattr(staged_key, "_known_objects", lambda: dict(objs))
    return objs


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE VIEW evil AS SELECT 1",
        "CREATE TRIGGER evil AFTER INSERT ON articles BEGIN SELECT 1; END",
        "CREATE VIEW article_fts_ai AS SELECT 1",  # a known name of another kind
        "CREATE VIRTUAL TABLE evil USING fts5(x)",
        "CREATE VIRTUAL TABLE article_fts USING rtree(id, a, b)",  # a known name on another module
    ],
)
def test_a_foreign_schema_object_is_refused_before_a_row_is_read(tmp_path, known, ddl):
    p = _db(tmp_path / "s.db")
    con = sqlite3.connect(p)
    con.execute(ddl)
    con.commit()
    con.close()
    c = staged_key.open_staged(p)
    try:
        with pytest.raises(staged_key.StagedKeyError) as refused:
            staged_key.check_staged_schema(c)
        assert "evil" not in str(refused.value)
    finally:
        c.close()


def test_the_apps_own_objects_pass(tmp_path, known):
    p = _db(tmp_path / "s.db")
    con = sqlite3.connect(p)
    con.execute("CREATE VIRTUAL TABLE article_fts USING fts5(title, content)")
    con.execute("CREATE TRIGGER article_fts_ai AFTER INSERT ON articles BEGIN SELECT 1; END")
    con.execute("CREATE VIEW keyword_mentions_all AS SELECT 1 AS x")
    con.commit()
    con.close()
    c = staged_key.open_staged(p)
    try:
        staged_key.check_staged_schema(c)
    finally:
        c.close()


def test_the_check_fails_closed_when_the_apps_own_schema_cannot_be_read(monkeypatch):
    class _Broken:
        def connect(self):
            raise RuntimeError("no engine")

    monkeypatch.setattr("src.database.session.engine", _Broken())
    with pytest.raises(staged_key.StagedKeyError):
        staged_key._known_objects()


def test_a_staged_connection_is_hardened(tmp_path):
    p = _db(tmp_path / "s.db")
    for sealed in (False, True):
        if sealed:
            staged_key.seal_plaintext(p)
        c = staged_key.open_staged(p)
        try:
            assert c.execute("PRAGMA trusted_schema").fetchone() == (0,)
            assert c.execute("PRAGMA cell_size_check").fetchone() == (1,)
        finally:
            c.close()
    staged_key.forget(p)


# --------------------------------------------------------------------------- the merge


def test_the_merge_of_a_keyed_copy_writes_what_the_merge_of_the_plaintext_one_writes(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from src.backup.merge import merge_corpus
    from src.database.models import Article, Base, Source
    from tests._app_engine import app_sqlite_engine

    def build(path: Path, n: int) -> None:
        engine = app_sqlite_engine(path, future=True)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, future=True)() as s:
            src = Source(name="s", domain="s.example")
            s.add(src)
            s.flush()
            for i in range(n):
                s.add(Article(url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}", source_id=src.id,
                              title=f"t{i}", content=f"body {i}", hash=f"h{i}", language="en",
                              created_at=datetime(2026, 1, 1, tzinfo=UTC)))
            s.commit()
        engine.dispose()

    meta = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "t", "app_version": "0.6", "alembic_rev": "head",
            "manifest": None}
    out = []
    for sealed in (False, True):
        work, inc = tmp_path / f"w{sealed}.db", tmp_path / f"i{sealed}.db"
        build(work, 0)
        build(inc, 40)
        if sealed:
            staged_key.seal_plaintext(inc)
        try:
            counts, _ = merge_corpus(inc, work, meta, cache_mb=8)
        finally:
            staged_key.forget(inc)
        con = sqlite3.connect(work)
        rows = con.execute("SELECT url, title, content, hash FROM articles ORDER BY url").fetchall()
        con.close()
        out.append((counts, rows))
    assert out[0] == out[1] and len(out[0][1]) == 40


def test_every_staging_reader_seals_what_it_stages():
    """The four places a staged artifact is built each seal it (``seal_staged_members``)."""
    root = Path(__file__).resolve().parents[1]
    a = (root / "src/backup/artifact.py").read_text(encoding="utf-8")
    s = (root / "src/backup/stream_backup.py").read_text(encoding="utf-8")
    assert a.count("seal_staged_members(") == 4  # the definition, the volume set, the bare upload, the zip upload
    assert s.count("seal_staged_members(staged") == 1
    assert "sqlcipher_export('snap')" not in s, "the plaintext export of an encrypted member is back"
    assert artifact.seal_staged_members is not None

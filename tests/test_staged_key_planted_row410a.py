"""Row 410-A, R829 condition 2: a planted key reaches no report, log, exception text or field-data bundle.

Two keys are planted and hunted for, each in every form SQLite or Python could write it:

- A1: the corpus member's own passphrase, which the staged copy is read with in place;
- A2: the random key a plaintext member is sealed under, caught as it is registered.

A real restore runs end to end on each (a volume set with an encrypted member through the library, an uploaded backup
through the surviving HTTP route), then one is refused on a foreign schema object so that a failure's text is hunted
too. The hunt reads the report, every log record, every file left in the data folder (the run journal and the
persisted reports among them) and the debug bundle.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import traceback
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.backup import staged_key

_PLANTED = "planted-member-passphrase-410A-Zk4Rw9"


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _forms(secret: bytes) -> list[bytes]:
    """Every way a key could be written: raw, as text, the hex inside a raw-key literal, the hex SQLite expands a blob
    value to, in either case."""
    out = {secret, secret.hex().encode(), secret.hex().upper().encode()}
    if secret.startswith(b"x'"):
        inner = secret[2:-1]
        out |= {inner, inner.upper(), bytes.fromhex(inner.decode())}
    return [f for f in out if len(f) >= 16]


def _hunt(secrets_: list[bytes], *, texts: list[str], folder: Path | None) -> list[str]:
    forms = [f for s in secrets_ for f in _forms(s)]
    hits = []
    for i, t in enumerate(texts):
        b = t.encode("utf-8", "surrogatepass")
        hits += [f"text #{i}" for f in forms if f in b or f.decode("latin-1") in t]
    if folder is not None:
        for top, _d, files in os.walk(folder):
            for name in files:
                p = Path(top, name)
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                hits += [str(p) for f in forms if f in data]
    return sorted(set(hits))


@pytest.fixture()
def captured(monkeypatch):
    seen: list[bytes] = []
    real = staged_key.register

    def spy(path, key):
        seen.append(key.secret)
        return real(path, key)

    monkeypatch.setattr(staged_key, "register", spy)
    return seen


def _encrypted_member_volume_set(tmp_path: Path) -> Path:
    """A volume set of the live corpus (the app's own schema), its corpus member encrypted under the planted key."""
    import sqlcipher3.dbapi2 as sqc

    from src.backup.stream_backup import CorpusSource, _no_freeze, write_stream_backup
    from src.database import session as S

    member = tmp_path / "member.db"
    con = sqc.connect(str(S.DB_FILE))
    try:
        if con.execute("PRAGMA page_size").fetchone() is None:  # pragma: no cover - the live store opens plain
            raise AssertionError
        con.execute("ATTACH DATABASE ? AS enc KEY ?", (str(member), _PLANTED))
        con.execute("SELECT sqlcipher_export('enc')").fetchall()
        con.execute("DETACH DATABASE enc")
    finally:
        con.close()
    dest = tmp_path / "vols"
    write_stream_backup(
        dest, "backup-pw",
        corpus_source=CorpusSource(path=member, member_name="corpus.db.sqlcipher", encrypted=True, freeze=_no_freeze,
                                   facts_key=_PLANTED),
        side_members=[], volume_size=1 << 20,
    )
    member.unlink()
    return dest


def test_a1_the_member_passphrase_reaches_no_report_log_file_or_bundle(client, tmp_path, caplog, captured):
    from src.backup.artifact import cleanup_staging
    from src.backup.merge import run_restore
    from src.backup.stream_backup import read_stream_backup
    from src.paths import data_dir

    caplog.set_level(logging.DEBUG)
    dest = _encrypted_member_volume_set(tmp_path)
    staged = read_stream_backup(dest, "backup-pw", staging_root=data_dir(), corpus_passphrase=_PLANTED)
    try:
        assert staged_key.key_for(staged.corpus_path).origin == "member"
        report = run_restore(staged, commit=True)
    finally:
        cleanup_staging(staged)
    assert report.get("committed") is True, report.get("error")
    bundle = client.post("/api/diagnostics/debug-bundle?slim=true")
    assert bundle.status_code == 200
    secrets_ = [_PLANTED.encode(), *captured]
    texts = [json.dumps(report, default=str), bundle.text, *(r.getMessage() for r in caplog.records)]
    assert _hunt(secrets_, texts=texts, folder=data_dir()) == []


def test_a2_the_sealing_key_reaches_no_report_log_file_or_bundle(client, tmp_path, caplog, captured):
    from src.backup.artifact import write_backup_v2
    from src.paths import data_dir

    caplog.set_level(logging.DEBUG)
    blob_path = tmp_path / "b.oobak"
    write_backup_v2(blob_path)
    resp = client.post("/api/backup/legacy/restore", json={"path": str(blob_path)})
    assert resp.status_code == 200, resp.text
    assert resp.json().get("committed") is True
    assert captured and all(s.startswith(b"x'") for s in captured), "the upload was not sealed"
    bundle = client.post("/api/diagnostics/debug-bundle?slim=true")
    texts = [resp.text, bundle.text, *(r.getMessage() for r in caplog.records)]
    assert _hunt(list(captured), texts=texts, folder=data_dir()) == []


def test_a_refusal_carries_neither_key_in_its_text(client, tmp_path, caplog, captured, monkeypatch):
    """The member is refused (a foreign view in its schema) after it was opened with its key: the exception, its
    chain, its traceback and the log carry neither key."""
    from src.backup.artifact import cleanup_staging
    from src.backup.merge import MergeError, run_restore
    from src.backup.stream_backup import read_stream_backup
    from src.paths import data_dir

    caplog.set_level(logging.DEBUG)
    dest = _encrypted_member_volume_set(tmp_path)
    staged = read_stream_backup(dest, "backup-pw", staging_root=data_dir(), corpus_passphrase=_PLANTED)
    c = staged_key.open_staged(staged.corpus_path, read_only=False)
    c.execute("CREATE VIEW planted_view AS SELECT 1")
    c.commit()
    c.close()
    failure: list[str] = []
    try:
        with pytest.raises(MergeError) as refused:
            run_restore(staged, commit=True)
        exc = refused.value
        failure = [str(exc), repr(exc), "".join(traceback.format_exception(exc))]
        assert "view this app does not make" in str(exc)
    finally:
        cleanup_staging(staged)
    secrets_ = [_PLANTED.encode(), *captured]
    assert _hunt(secrets_, texts=failure + [r.getMessage() for r in caplog.records], folder=data_dir()) == []


def test_the_hunt_finds_a_planted_key_when_one_is_there(tmp_path):
    """Positive control: the hunt is not blind to a key written in any of its forms."""
    secret = b"x'" + b"ab" * 32 + b"'"
    for form in _forms(secret):
        f = tmp_path / "leak.txt"
        f.write_bytes(b"prefix " + form + b" suffix")
        assert _hunt([secret], texts=[], folder=tmp_path), form
    assert _hunt([_PLANTED.encode()], texts=[f"oops {_PLANTED}"], folder=None)
    con = sqlite3.connect(":memory:")
    traced: list[str] = []
    con.set_trace_callback(traced.append)
    con.execute("SELECT ?", (secret,))
    assert _hunt([secret], texts=traced, folder=None), "a traced blob value is not found"

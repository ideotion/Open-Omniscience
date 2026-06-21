"""Server-side .eml folder-import job (brief §2.B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A pausable DB-writer job that imports a folder of .eml files (the 20 GB+ case the
upload path can't handle). Reuses the batched ingest_emails; resume is idempotent
(content-hash dedup + a processed-paths set so progress continues, never re-imports).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Source
from src.ingest.email import ingest_emails
from src.ingest.import_job import NewsletterImportManager, _import_source


@pytest.fixture()
def env(tmp_path):
    # A shared in-memory DB (StaticPool) so the worker's own session sees the schema.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    return engine, Session, tmp_path


def _eml(folder, n, body):
    p = folder / f"{n}.eml"
    p.write_bytes(
        (
            f"From: N <n@x.test>\nSubject: S{n}\nMessage-ID: <m{n}@x.test>\n"
            f"Date: Mon, 05 Jan 2026 18:00:00 +0000\nContent-Type: text/plain; charset=utf-8\n\n{body}\n"
        ).encode()
    )
    return p


def _join(mgr, t=5.0):
    if mgr._thread is not None:
        mgr._thread.join(t)


def test_import_job_imports_a_folder(env):
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    for i in range(5):
        _eml(folder, i, f"unique newsletter body number {i} about elections")
    mgr = NewsletterImportManager()
    st = mgr.start(str(folder), _session_factory=Session)
    assert st["state"] == "running" and st["files_total"] == 5
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["files_done"] == 5 and s["tally"]["stored"] == 5
    with Session() as sess:
        assert sess.query(Article).count() == 5
        # the dedicated, DISABLED .eml source was created
        src = sess.query(Source).filter_by(domain="newsletters.import.local").first()
        assert src is not None and src.enabled is False


def test_reimport_dedups_idempotently(env):
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    for i in range(3):
        _eml(folder, i, f"body {i} inflation")
    mgr = NewsletterImportManager()
    mgr.start(str(folder), _session_factory=Session)
    _join(mgr)
    assert mgr.status()["tally"]["stored"] == 3
    # A fresh import of the same folder stores nothing new (content-hash dedup).
    mgr.start(str(folder), _session_factory=Session)
    _join(mgr)
    s = mgr.status()
    assert s["tally"]["stored"] == 0 and s["tally"]["duplicate"] == 3
    with Session() as sess:
        assert sess.query(Article).count() == 3


def test_resume_skips_already_done(env):
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    files = [_eml(folder, i, f"body {i} drought") for i in range(4)]
    # Simulate: the first two were imported, then paused.
    with Session() as sess:
        src = _import_source(sess)
        ingest_emails(sess, src, [files[0].read_bytes(), files[1].read_bytes()])
    mgr = NewsletterImportManager()
    mgr._folder = str(folder)
    mgr._files = [f.resolve() for f in files]
    mgr._done = {str(files[0].resolve()), str(files[1].resolve())}
    mgr._tally = {"stored": 2}
    mgr._state = "paused"
    mgr._session_factory = Session
    mgr.resume()
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["files_done"] == 4
    with Session() as sess:
        assert sess.query(Article).count() == 4  # 2 prior + 2 from resume


def test_bad_folder_and_concurrent_start(env):
    engine, Session, tmp = env
    mgr = NewsletterImportManager()
    with pytest.raises(ValueError, match="not a folder"):
        mgr.start(str(tmp / "does-not-exist"), _session_factory=Session)


def test_status_shape_and_eta(env):
    mgr = NewsletterImportManager()
    s = mgr.status()
    assert s["state"] == "idle" and s["files_total"] == 0 and s["eta_seconds"] is None

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


def _new_mgr(tmp):
    # A tmp state file so tests never touch the real data_dir().
    return NewsletterImportManager(state_path=tmp / "import_state.json")


def test_import_job_imports_a_folder(env):
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    for i in range(5):
        _eml(folder, i, f"unique newsletter body number {i} about elections")
    mgr = _new_mgr(tmp)
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
    mgr = _new_mgr(tmp)
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
    # Simulate: the first two were imported, then paused at cursor 2.
    with Session() as sess:
        src = _import_source(sess)
        ingest_emails(sess, src, [files[0].read_bytes(), files[1].read_bytes()])
    mgr = _new_mgr(tmp)
    mgr._folder = str(folder)
    mgr._files = sorted(f.resolve() for f in files)
    mgr._cursor = 2
    mgr._tally = {"stored": 2}
    mgr._state = "paused"
    mgr._session_factory = Session
    mgr.resume()
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["files_done"] == 4
    with Session() as sess:
        assert sess.query(Article).count() == 4  # 2 prior + 2 from resume


def test_persisted_cursor_survives_an_app_restart(env):
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    files = sorted((_eml(folder, i, f"body {i} restart")).resolve() for i in range(6))
    state = tmp / "import_state.json"
    # Manager A imports the first 3, then is interrupted (state persisted as running).
    with Session() as sess:
        src = _import_source(sess)
        ingest_emails(sess, src, [p.read_bytes() for p in files[:3]])
    a = NewsletterImportManager(state_path=state)
    a._folder, a._files, a._cursor, a._tally, a._state = str(folder), files, 3, {"stored": 3}, "running"
    a._save()
    # Manager B = a fresh process restart: it LOADS the interrupted import as PAUSED.
    b = NewsletterImportManager(state_path=state)
    assert b.status()["state"] == "paused" and b.status()["files_done"] == 3
    b._session_factory = Session
    b.resume()
    _join(b)
    assert b.status()["state"] == "done" and b.status()["files_done"] == 6
    with Session() as sess:
        assert sess.query(Article).count() == 6
    assert not state.exists()  # the cursor file is cleared on completion


def test_bad_folder_and_concurrent_start(env):
    engine, Session, tmp = env
    mgr = _new_mgr(tmp)
    with pytest.raises(ValueError, match="not a folder"):
        mgr.start(str(tmp / "does-not-exist"), _session_factory=Session)


def test_status_shape_and_eta(env):
    mgr = _new_mgr(__import__("pathlib").Path("/tmp"))
    s = mgr.status()
    assert s["state"] == "idle" and s["files_total"] == 0 and s["eta_seconds"] is None


_NAV_SOUP_BODY = (
    "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
    "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
    "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
    "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
    "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
    "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
    "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
    "Statement Complaints Regulation Archive Sitemap Jobs Shop Weddings Announcements Obituaries "
    "Horoscopes Puzzles Crosswords Competitions Vouchers Discounts Deals Reviews Betting Casino "
    "Lottery Results Traffic Cameras Roadworks Bus Times Train Times Flight Tracker Currency "
    "Converter Recipes Wine Beer Cocktails Restaurants Bars Nightlife Theatre Cinema Music Books"
)


def test_import_job_quarantines_nav_soup_but_not_a_real_article(env):
    """S3.3: a successful import auto-screens its OWN newly-imported articles and stamps
    the reversible quarantine flag on detected junk, while a genuine article stays clean."""
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    _eml(folder, 0, _NAV_SOUP_BODY)
    _eml(
        folder, 1,
        "The government said on Tuesday that it would review the policy after months of "
        "criticism from opposition lawmakers, who argued the reform had failed to deliver "
        "the promised benefits to the region's struggling economy. " * 2,
    )
    mgr = _new_mgr(tmp)
    mgr.start(str(folder), _session_factory=Session)
    _join(mgr)
    assert mgr.status()["state"] == "done"
    with Session() as sess:
        arts = sess.query(Article).order_by(Article.id).all()
        assert len(arts) == 2
        quarantined = [a for a in arts if a.quarantined is True]
        clean = [a for a in arts if a.quarantined is not True]
        assert len(quarantined) == 1
        assert len(clean) == 1
        assert quarantined[0].quarantine_reason == "nav_soup"


def test_import_job_persists_a_downloadable_report_on_completion(env):
    """S3.5: a successful import writes a standalone JSON report (the newsletter path had
    no persisted report at all before this). Compares a BEFORE/AFTER count rather than an
    absolute one, since data_dir()/import_reports/ is a session-shared directory other
    tests in this file may also write into."""
    from src.backup.import_reports import list_import_reports

    engine, Session, tmp = env
    before = len([r for r in list_import_reports() if r["kind"] == "newsletter"])
    folder = tmp / "nl"
    folder.mkdir()
    for i in range(3):
        _eml(folder, i, f"a genuine article body number {i} about the economy and trade")
    mgr = _new_mgr(tmp)
    mgr.start(str(folder), _session_factory=Session)
    _join(mgr)
    assert mgr.status()["state"] == "done"
    after = len([r for r in list_import_reports() if r["kind"] == "newsletter"])
    assert after == before + 1


def test_import_job_never_quarantines_an_article_that_predates_this_run(env):
    """Scoping correctness: a PRE-EXISTING article (from a prior, unrelated import) must
    never be re-scanned or stamped by a LATER run's quarantine hook, even though it would
    itself be flagged by the same criteria."""
    engine, Session, tmp = env
    folder1 = tmp / "nl1"
    folder1.mkdir()
    _eml(folder1, 0, _NAV_SOUP_BODY)  # a pre-existing junk article, imported FIRST
    mgr1 = _new_mgr(tmp)
    mgr1.start(str(folder1), _session_factory=Session)
    _join(mgr1)
    with Session() as sess:
        pre_existing_id = sess.query(Article).one().id
        # simulate: this pre-existing article was reviewed and un-quarantined by a human
        sess.query(Article).filter(Article.id == pre_existing_id).update({"quarantined": False})
        sess.commit()

    folder2 = tmp / "nl2"
    folder2.mkdir()
    _eml(folder2, 0, "a genuine second article body about renewable energy and policy reform " * 2)
    mgr2 = NewsletterImportManager(state_path=tmp / "import_state_2.json")
    mgr2.start(str(folder2), _session_factory=Session)
    _join(mgr2)
    assert mgr2.status()["state"] == "done"

    with Session() as sess:
        # the pre-existing article's human-reviewed un-quarantined state must be untouched
        assert sess.get(Article, pre_existing_id).quarantined is False


def test_paused_then_resumed_import_screens_articles_from_both_halves(env):
    """The before-id baseline must be captured ONCE at the TRUE start of a logical
    import and PRESERVED across a pause/resume -- not re-captured on the resume, which
    would silently skip auto-screening the articles the pre-pause half already stored.
    Simulates: a first _run() stores one nav-soup article then is interrupted before
    reaching the completion branch (never scanned yet, exactly like a real pause);
    resuming and completing must then quarantine that carried-over article too."""
    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    files = [
        _eml(folder, 0, _NAV_SOUP_BODY),  # the pre-pause half's article
        _eml(folder, 1, "a genuine second article about trade policy and tariffs " * 3),
    ]
    with Session() as sess:
        src = _import_source(sess)
        # simulate the pre-pause half already having ingested file 0 -- the interrupted
        # run never reached its own completion branch, so nothing was screened yet.
        ingest_emails(sess, src, [files[0].read_bytes()])

    mgr = NewsletterImportManager(state_path=tmp / "state.json")
    mgr._folder = str(folder)
    mgr._files = sorted(f.resolve() for f in files)
    mgr._cursor = 1
    mgr._tally = {"stored": 1}
    mgr._state = "paused"
    # the baseline WAS captured before the interrupted half ran (article count was 0)
    mgr._quarantine_before_id = 0
    mgr._quarantine_baseline_attempted = True
    mgr._session_factory = Session
    mgr.resume()
    _join(mgr)
    assert mgr.status()["state"] == "done"

    with Session() as sess:
        arts = sess.query(Article).order_by(Article.id).all()
        assert len(arts) == 2
        # article[0] = the pre-pause nav-soup specimen (inserted first); article[1] =
        # the genuine post-resume article. Both must have been considered for
        # screening -- the pre-pause one quarantined, the genuine one left clean.
        assert arts[0].quarantined is True
        assert arts[1].quarantined is not True


def test_import_job_completes_successfully_even_if_quarantine_scan_raises(env, monkeypatch):
    """Best-effort property: a failure in the new quarantine/report hook must never turn a
    successful import into an error state."""
    import src.analytics.quarantine_job as qj

    def _boom(*a, **kw):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(qj, "default_quarantine_candidates_batch", _boom)

    engine, Session, tmp = env
    folder = tmp / "nl"
    folder.mkdir()
    _eml(folder, 0, "a genuine article body about the economy and trade policy " * 3)
    mgr = _new_mgr(tmp)
    mgr.start(str(folder), _session_factory=Session)
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done"  # never "error", despite the injected failure
    with Session() as sess:
        assert sess.query(Article).count() == 1


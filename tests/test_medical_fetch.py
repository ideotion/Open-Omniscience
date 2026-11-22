"""The medical lane's one egress (S07-01 PR 3; R745, R750): what it asks for, what it keeps, and what it says it cannot find.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No network: a fake session serves an invented NLM directory and the parser's invented update file.
Checks are mostly negative space -- nothing is asked for while airplane mode is on, a file whose
checksum does not match applies nothing, a record nobody cites is not kept, a body past its cap is
refused, the corpus scan writes nothing, and the routes refuse without consent and name airplane
mode. The gap (R750) is stated by the page itself and counted, never left for the user to guess.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from src.medical import fetch as F
from src.medical import store as M
from src.medical.lane_models import MedicalFile, MedicalPaper
from src.versioned import store
from tests._app_engine import app_sqlite_engine

FIXTURE = Path(__file__).parent / "fixtures" / "medical" / "pubmed_update_sample.xml"
ROOT = Path(__file__).resolve().parent.parent
NAMES = ("pubmed25n1300.xml.gz", "pubmed25n1301.xml.gz")


@pytest.fixture
def medical(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setattr(F, "kill_switch_active", lambda: False)
    monkeypatch.setattr("src.stats.fetch.kill_switch_active", lambda: False)
    try:
        yield tmp_path
    finally:
        store.dispose_all()


class _Resp:
    def __init__(self, url: str, body: bytes, status: int = 200) -> None:
        self.url = url
        self._body = body
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.is_redirect = False
        self._content: bytes | None = None
        self._content_consumed = False

    def iter_content(self, n: int):
        for i in range(0, len(self._body), n):
            yield self._body[i : i + n]

    @property
    def content(self) -> bytes:
        return self._content if self._content is not None else self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def close(self) -> None:
        pass


class _Session:
    """Serves a fixed map of URL -> body; records every URL asked for."""

    max_redirects = 5

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.asked: list[str] = []

    def get(self, url: str, **_kw):
        self.asked.append(url)
        if url not in self.bodies:
            return _Resp(url, b"", 404)
        return _Resp(url, self.bodies[url])


def _listing(*names: str) -> bytes:
    links = "".join(f'<a href="{n}">{n}</a> <a href="{n}.md5">{n}.md5</a>\n' for n in names)
    junk = '<a href="../baseline/">x</a><a href="pubmed25n1302.xml.gz.evil">y</a><a href="https://elsewhere.test/a.xml.gz">z</a>'
    return f"<html><body>{links}{junk}</body></html>".encode()


def _site(names=NAMES, *, md5_override: str | None = None) -> _Session:
    gz = gzip.compress(FIXTURE.read_bytes())
    md5 = md5_override or hashlib.md5(gz, usedforsecurity=False).hexdigest()
    bodies = {F.UPDATE_BASE: _listing(*names)}
    for n in names:
        bodies[F.UPDATE_BASE + n] = gz
        bodies[F.UPDATE_BASE + n + ".md5"] = f"MD5 ({n}) = {md5}\n".encode()
    return _Session(bodies)


def _wanted(**kinds: set[str]) -> M.Wanted:
    w = M.Wanted()
    for k, vals in kinds.items():
        for v in vals:
            w.add(k, v)
    return w


@pytest.fixture
def no_corpus(monkeypatch):
    """run_fetch's corpus scan, replaced: the corpus file is not this test's subject."""
    cited = {"w": M.Wanted()}

    @contextlib.contextmanager
    def _scope():
        yield None

    monkeypatch.setattr("src.database.session.session_scope", _scope)
    monkeypatch.setattr(F, "cited_in_corpus", lambda _db, **_k: cited["w"])
    return cited


def _papers() -> set[int]:
    with store.lane_session("medical") as s:
        return set(s.execute(select(MedicalPaper.pmid)).scalars())


# --- the corpus scan -------------------------------------------------------------------------


def test_cited_ids_reads_pmid_pmcid_and_doi_links_and_guesses_nothing():
    w = F.cited_ids([
        "https://pubmed.ncbi.nlm.nih.gov/90000001/",
        "https://www.ncbi.nlm.nih.gov/pubmed/90000003?dopt=Abstract",
        "https://pmc.ncbi.nlm.nih.gov/articles/pmc9000001/",
        "https://doi.org/10.9999/JIR.2024.001",
        "https://dx.doi.org/10.9999%2Fpreprint.3).",
        "https://pubmed.ncbi.nlm.nih.gov/0123/",       # a leading zero is not a PMID
        "https://doi.org/11.1/not-a-doi",              # not a DOI
        "https://example.test/90000002",               # a number on another site is not a PMID
    ])
    assert w.pmid == {"90000001", "90000003"}
    assert w.pmcid == {"PMC9000001"}
    assert w.doi == {"10.9999/jir.2024.001", "10.9999/preprint.3"}


def test_the_corpus_scan_reads_links_and_writes_nothing():
    pytest.importorskip("sqlalchemy")
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, ArticleLink, Base, Source

    eng = app_sqlite_engine(":memory:", future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(id=1, name="Web", domain="w.test", source_type="news"))
    s.add(Article(id=1, url="https://x/1", canonical_url="https://x/1", source_id=1, title="t", hash="h1",
                  language="en", content="c", created_at=datetime.now(UTC)))
    urls = ["https://pubmed.ncbi.nlm.nih.gov/90000001/", "https://doi.org/10.9999/cited.paper",
            "https://news.test/story", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8888888/"]
    s.add_all([ArticleLink(article_id=1, url=u, normalized_url=u, link_type="external") for u in urls])
    s.commit()
    before = s.execute(select(ArticleLink.id, ArticleLink.url)).all()
    w = F.cited_in_corpus(s)
    assert (w.pmid, w.doi, w.pmcid) == ({"90000001"}, {"10.9999/cited.paper"}, {"PMC8888888"})
    assert not s.new and not s.dirty and not s.deleted
    assert s.execute(select(ArticleLink.id, ArticleLink.url)).all() == before
    assert F.cited_in_corpus(s, stopping=lambda: True)._set("pmid") == set(), "a stop before the first batch reads nothing"


# --- the fetch -------------------------------------------------------------------------------


def test_a_fetch_keeps_only_what_is_cited_and_counts_what_it_did_not_find(medical, no_corpus):
    no_corpus["w"] = _wanted(pmid={"90000001", "12345678"}, doi={"10.9999/never.seen"})
    site = _site()
    out = F.run_fetch(1, session=site)
    assert [a["kept"] for a in out["applied"]] == [1]
    assert _papers() == {90000001}, "a record nobody cites is not kept (R745)"
    assert out["cited_ids"] == 3
    assert out["coverage"]["cited"] == 3
    assert out["coverage"]["cited_found"] == 1
    assert out["coverage"]["cited_not_found"] == 2, "R750: the papers not found are counted, never dropped"
    assert out["listed"] == 2 and out["remaining"] == 1
    assert all(u.startswith(F.UPDATE_BASE) for u in site.asked), "every request stays in NLM's update directory"
    assert not any("evil" in u or "elsewhere" in u or "baseline" in u for u in site.asked)


def test_the_oldest_unapplied_file_goes_first_and_a_finished_file_is_not_fetched_again(medical, no_corpus):
    no_corpus["w"] = _wanted(pmid={"90000001"})
    site = _site(names=("pubmed25n1301.xml.gz", "pubmed25n1300.xml.gz"))
    F.run_fetch(1, session=site)
    with store.lane_session("medical") as s:
        assert set(s.execute(select(MedicalFile.name).where(MedicalFile.status == "finished")).scalars()) == {
            "pubmed25n1300.xml.gz"
        }
    site.asked.clear()
    second = F.run_fetch(5, session=site)
    assert len(second["applied"]) == 1 and second["remaining"] == 0
    assert F.UPDATE_BASE + "pubmed25n1300.xml.gz" not in site.asked


def test_a_checksum_mismatch_applies_nothing_and_no_newer_file_overtakes_it(medical, no_corpus):
    no_corpus["w"] = _wanted(pmid={"90000001"})
    site = _site()
    site.bodies[F.UPDATE_BASE + NAMES[0] + ".md5"] = b"MD5 (x) = " + b"0" * 32 + b"\n"
    out = F.run_fetch(2, session=site)
    assert out["failed"]["file"] == NAMES[0] and out["failed"]["error"] == "FileRefused"
    assert "checksum" in out["failed"]["reason"]
    assert out["applied"] == [] and _papers() == set()
    assert F.UPDATE_BASE + NAMES[1] not in site.asked, (
        "a newer file must never land before an older one that failed: its deletions of records not "
        "kept yet leave no trace, so the older file could later bring a deleted record back"
    )
    with store.lane_session("medical") as s:
        rows = s.execute(select(MedicalFile.name, MedicalFile.status)).all()
    assert rows == [(NAMES[0], "failed")]
    assert out["remaining"] == 2
    site.bodies[F.UPDATE_BASE + NAMES[0] + ".md5"] = site.bodies[F.UPDATE_BASE + NAMES[1] + ".md5"]
    again = F.run_fetch(2, session=site)
    assert len(again["applied"]) == 2 and again["failed"] is None and again["remaining"] == 0


def test_the_newest_file_is_named_by_nlm_sequence_not_by_when_it_was_applied(medical):
    from datetime import UTC, datetime, timedelta

    store.create_lane("medical")
    now = datetime.now(UTC)
    with store.lane_session("medical") as s:
        s.add(MedicalFile(name="pubmed25n1301.xml.gz", status="finished", finished_at=now))
        s.add(MedicalFile(name="pubmed25n1300.xml.gz", status="finished", finished_at=now + timedelta(hours=1)))
    with store.lane_session("medical") as s:
        assert M.summary(s)["last_file"]["name"] == "pubmed25n1301.xml.gz"


def test_a_stop_inside_the_file_loop_is_reported_as_stopped(medical, no_corpus):
    calls = {"n": 0}

    def _stopping() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # the after-scan check and the first file pass, then stop

    out = F.run_fetch(2, session=_site(), stopping=_stopping)
    assert len(out["applied"]) == 1 and out["stopped"] is True and out["failed"] is None


def test_a_body_past_its_cap_is_refused_before_it_is_read_whole(medical, no_corpus, monkeypatch):
    monkeypatch.setattr(F, "MAX_FILE_BYTES", 64)
    out = F.run_fetch(1, session=_site())
    assert out["failed"]["error"] == "FileRefused" and _papers() == set()


def test_a_file_that_inflates_past_its_cap_is_refused(medical, no_corpus, monkeypatch):
    no_corpus["w"] = _wanted(pmid={"90000001"})
    monkeypatch.setattr(F, "MAX_XML_BYTES", 512)
    out = F.run_fetch(1, session=_site())
    assert out["failed"]["error"] == "FileRefused" and "inflates" in out["failed"]["reason"]
    assert _papers() == set(), "nothing of a refused file is applied"


def test_airplane_mode_refuses_before_any_request(medical, no_corpus, monkeypatch):
    monkeypatch.setattr(F, "kill_switch_active", lambda: True)
    site = _site()
    with pytest.raises(RuntimeError, match="airplane mode"):
        F.run_fetch(1, session=site)
    assert site.asked == []


def test_airplane_mode_mid_run_is_named_and_not_charged_to_the_file(medical, no_corpus, monkeypatch):
    site = _site()
    calls = {"n": 0}

    def _switch() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # off for the run's own check and the listing, on from the first file

    monkeypatch.setattr(F, "kill_switch_active", _switch)
    out = F.run_fetch(1, session=site)
    assert out["failed"]["error"] == "airplane_mode"
    with store.lane_session("medical") as s:
        assert s.execute(select(MedicalFile)).first() is None, "a refusal by the kill switch is not the file's failure"


@pytest.mark.parametrize(("reason", "error"), [("protected", "protected_mode"), ("unprotected", "protected_mode_off"), ("proxy", "proxy_changed"), ("unreadable", "settings_unreadable")])
def test_a_transport_change_mid_run_is_named_and_not_charged_to_the_file(medical, no_corpus, monkeypatch, reason, error):
    """R768/R769: protected mode switched on under a direct run, or the settings no longer readable, ends the run, named."""
    from src.safety.transport_watch import TransportStopped, stop_message

    real_get = F._get

    def _get(session, url, max_bytes):
        if url.endswith(".xml.gz"):
            raise TransportStopped(reason)
        return real_get(session, url, max_bytes)

    monkeypatch.setattr(F, "_get", _get)
    out = F.run_fetch(1, session=_site())
    assert out["failed"]["error"] == error and out["failed"]["reason"] == stop_message(reason)
    with store.lane_session("medical") as s:
        assert s.execute(select(MedicalFile)).first() is None, "a stop by a transport change is not the file's failure"


def test_a_transport_change_before_the_listing_is_named_and_is_no_fetch(medical, no_corpus, monkeypatch):
    """R772(b): the corpus scan runs before the first request; a change in between ends the run named, with nothing listed."""
    from src.safety.transport_watch import TransportStopped, stop_message

    def _listing(http):
        raise TransportStopped("proxy")

    monkeypatch.setattr(F, "list_update_files", _listing)
    out = F.run_fetch(1, session=_site())
    assert out["listed"] is None and out["applied"] == []
    assert out["failed"]["error"] == "proxy_changed" and out["failed"]["reason"] == stop_message("proxy")


def test_the_session_is_held_to_nlm_and_its_update_directory(monkeypatch):
    seen = {}
    monkeypatch.setattr("src.safety.fetcher.guarded_session", lambda **kw: seen.update(kw) or object())
    F._session()
    assert seen["allowed_hosts"] == ("ftp.ncbi.nlm.nih.gov",)
    assert seen["allowed_path_prefixes"] == ("/pubmed/updatefiles/",)


# --- the routes ------------------------------------------------------------------------------


@pytest.fixture
def client(medical):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.medical import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_fetch_route_refuses_without_consent_and_names_airplane_mode(client, monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    r = client.post("/api/medical/fetch", json={})
    assert r.status_code == 400 and "consent" in r.json()["detail"]
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    r = client.post("/api/medical/fetch", json={"consent": True})
    assert r.status_code == 409 and "airplane mode" in r.json()["detail"]


def test_the_status_route_is_local_and_carries_the_disclosure_and_the_gap(client, monkeypatch):
    def _no_network(*_a, **_k):
        raise AssertionError("the status route must not build a network session")

    monkeypatch.setattr(F, "_session", _no_network)
    d = client.get("/api/medical/status").json()
    assert d["disclosure"] == F.DISCLOSURE and d["gap"] == F.GAP
    assert d["coverage"]["cited_not_found"] == 0 and d["papers"] == 0


def test_the_panel_states_the_gap_and_the_disclosure_visibly():
    html = (ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('data-adv="medical"')
    section = html[start : html.index("</details>", start)]
    assert f'<p class="card-caveat" style="margin-top:6px">{F.GAP}</p>' in section, "R750: the gap is a visible caveat line"
    assert F.DISCLOSURE in section
    assert "hidden" not in section.split("medical-counts")[0]
    js = (ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    assert "ensureOnline" in js and "consent: true" in js
    assert "{missing} not found yet" in js, "the count of cited papers not found is drawn"


def test_a_stop_during_the_corpus_scan_sends_nothing_and_keeps_the_last_snapshot(medical, no_corpus):
    no_corpus["w"] = _wanted(pmid={"90000001", "12345678"})
    F.run_fetch(1, session=_site())
    site = _site()
    no_corpus["w"] = _wanted(pmid={"1"})
    out = F.run_fetch(1, session=site, stopping=lambda: True)
    assert out["stopped"] is True and out["listed"] is None
    assert site.asked == [], "a stop asked for before any request sends none"
    with store.lane_session("medical") as s:
        assert M.coverage(s)["cited"] == 2, "a partial scan never replaces the last full snapshot"

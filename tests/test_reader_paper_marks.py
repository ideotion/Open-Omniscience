"""The reader marks a cited link to a kept paper with its class and notices (row 214; S07-01 S1, R750).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mostly negative space: the marks are read from this install's ``medical.db`` and nothing is requested;
a lane never fetched is not opened and no file appears; a link whose paper is not kept here gets NO mark
(R750: not kept here is not missing from PubMed); a badge sits on the link that names the paper, never on
its neighbour; and the labels and hover text are the Papers subtab's own keys, so all twelve locales
already carry them.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.medical import fetch as F
from src.medical import reader_marks as RM
from src.medical import store as M
from src.versioned import store

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "medical" / "pubmed_update_sample.xml"


@pytest.fixture
def medical(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")

    def _no_network(*_a, **_k):
        raise AssertionError("the reader's paper marks must never build a network session")

    monkeypatch.setattr(F, "_session", _no_network)
    try:
        yield tmp_path
    finally:
        store.dispose_all()


def _apply_fixture() -> None:
    w = M.Wanted()
    for pmid in ("90000001", "90000002", "90000003"):
        w.add("pmid", pmid)
    store.create_lane(M.LANE)
    body = gzip.compress(FIXTURE.read_bytes())
    F.apply_body("pubmed25n1300.xml.gz", body, hashlib.md5(body, usedforsecurity=False).hexdigest(), w)


URLS = [
    "https://pubmed.ncbi.nlm.nih.gov/90000002/",  # retracted, with a retraction notice
    "https://news.test/story",  # not a paper
    "https://doi.org/10.9999/jir.2024.001",  # PMID 90000001 by its DOI: a journal record with an erratum
    "https://doi.org/10.9999/never.kept",  # a paper id no file carried
    "https://doi.org/10.9999/preprint.3",  # a preprint
]


def test_each_link_carries_the_papers_it_names_and_nothing_else(medical):
    _apply_fixture()
    marks = RM.link_marks(URLS)
    assert set(marks) == {0, 2, 4}, "a mark sits on the link that names a kept paper, never on its neighbour"
    assert [m["provenance_class"] for m in marks[0]] == ["retracted"] and "retraction" in marks[0][0]["notices"]
    assert [m["provenance_class"] for m in marks[2]] == ["journal"] and "erratum" in marks[2][0]["notices"]
    assert [m["provenance_class"] for m in marks[4]] == ["preprint"]
    # R750: the DOI no file carried gets nothing at all, not a "not found" mark.
    assert 3 not in marks and 1 not in marks
    assert all(set(m) == {"pmid", "provenance_class", "notices", "withdrawn"} for ms in marks.values() for m in ms)


def test_a_lane_never_fetched_is_not_opened_and_no_file_appears(medical):
    assert not store.lane_path(M.LANE).exists()
    assert RM.link_marks(URLS) == {}
    assert not store.lane_path(M.LANE).exists(), "reading the marks must not create medical.db"


def test_links_with_no_paper_id_do_not_open_the_lane(medical, monkeypatch):
    _apply_fixture()

    def _boom(*_a, **_k):
        raise AssertionError("no paper id, no lookup")

    monkeypatch.setattr(store, "lane_session", _boom)
    assert RM.link_marks(["https://news.test/a", "", "https://example.org/b"]) == {}


def test_the_badges_are_labels_with_their_hover_and_never_a_verdict():
    html = RM.marks_html([{"pmid": 1, "provenance_class": "retracted", "notices": ["retraction"], "withdrawn": True}])
    assert ">Retracted<" in html and ">Retraction notice<" in html and ">Withdrawn from PubMed<" in html
    assert "title='The PubMed record says this paper was retracted." in html
    assert RM.marks_html([]) == ""
    # A class this module cannot name is not drawn: an unnamed label would read as a claim.
    assert RM.marks_html([{"pmid": 2, "provenance_class": "mystery", "notices": [], "withdrawn": False}]) == ""
    assert "score" not in html.lower() and "reliab" not in html.lower()


def test_the_labels_are_the_papers_subtabs_own_and_keyed_in_every_locale():
    js = (ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    for table in (RM.CLASS_LABEL, RM.CLASS_HOVER, RM.NOTICE_LABEL):
        for key, text in table.items():
            assert re.search(re.escape(key) + r':\s*"' + re.escape(text) + '"', js), (key, text)
    assert '"' + RM.WITHDRAWN_LABEL + '"' in js
    texts = [*RM.CLASS_LABEL.values(), *RM.CLASS_HOVER.values(), *RM.NOTICE_LABEL.values(), RM.WITHDRAWN_LABEL]
    for loc in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        missing = [t for t in texts if t not in d]
        assert not missing, (loc.name, missing)


def test_the_reader_draws_the_marks_on_its_cited_links(medical, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, ArticleLink, Base, Source
    from src.database.session import get_db

    _apply_fixture()
    engine = create_engine(f"sqlite:///{tmp_path / 'rd.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add(Article(url="https://wire.test/a", canonical_url="https://wire.test/a", source_id=1, title="Article A",
                      content="Body A.", hash="ha", language="en", created_at=datetime.now(UTC)))
        s.commit()
        s.add_all([ArticleLink(article_id=1, url=u, normalized_url=u, link_text=f"link {i}", link_type="external",
                               position=i) for i, u in enumerate(URLS)])
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        body = TestClient(app).get("/api/articles/1/view").text
    finally:
        app.dependency_overrides.clear()
    cites = body.split("Sources this article cites", 1)[1].split("</section>", 1)[0]
    items = {m.group(1): m.group(0) for m in re.finditer(r"<li>.*?>(link \d)</a>.*?</li>", cites)}
    assert ">Retracted<" in items["link 0"] and ">Retraction notice<" in items["link 0"]
    assert ">Journal record<" in items["link 2"] and ">Erratum published<" in items["link 2"]
    assert ">Preprint<" in items["link 4"]
    for quiet in ("link 1", "link 3"):
        assert "med-badge" not in items[quiet], quiet

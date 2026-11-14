"""Sources an instance qualified that no shipped catalogue has, PROPOSED for review (maintainer 2026-11-14).

The Field data button saves them; scripts/propose_source_additions.py turns them into a review table. Nothing here adds a
source to a catalogue: every row reads "proposed".
"""
from __future__ import annotations

import importlib
import io
import json
import zipfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.catalog import candidate_sources as cs
from src.database.models import Article, Base, MergedRow, Source, SourceQualificationAttempt

WHEN = datetime(2026, 11, 1, 12, 0)


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__, SourceQualificationAttempt.__table__,
                                          MergedRow.__table__])
    monkeypatch.setattr("src.catalog.provenance_scope.curated_catalogue_domains", lambda: frozenset({"shipped.example"}))
    with Session(eng) as s:
        yield s


def _src(db, sid, domain, *, tags="via:wikidata-discovery,news,fr", status="qualified", attempt=True, rss=None):
    db.add(Source(id=sid, name=f"N{sid}", domain=domain, tags=tags, status=status, language="fr", country="fr",
                  rss_url=rss, qualified_at=WHEN, qualification_criteria_version="v3"))
    db.flush()
    if attempt:
        db.add(SourceQualificationAttempt(source_id=sid, attempted_at=WHEN, verdict="qualified", criteria_version="v3"))
    db.add(Article(url=f"https://{domain}/a", canonical_url=f"https://{domain}/a", source_id=sid, title="t",
                   content="x", hash=f"{sid:064d}", published_at=WHEN))
    db.commit()


def test_only_measured_qualified_sources_outside_every_catalogue_are_proposed(db):
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    _src(db, 1, "new.example", rss="https://user:pw@new.example/feed.xml?token=SECRET#frag")
    _src(db, 2, "shipped.example")                       # a catalogue already has it
    _src(db, 3, "copied.example", attempt=False)         # qualified, but never measured here
    _src(db, 4, NEWSLETTER_SOURCE_DOMAINS[0])            # a mailbox: stays home
    _src(db, 5, "letters.example", tags="newsletter")    # a newsletter publisher: stays home
    _src(db, 6, "pending.example", status="unqualified")
    _src(db, 7, "someauthor.substack.com", tags="")       # a publisher row the newsletter import made
    db.query(Source).filter(Source.id == 7).update({"source_type": "newsletter"})
    db.add(Article(url="https://new.example/n", canonical_url="https://new.example/n", source_id=1, title="n",
                   content="x", hash="7" * 64, published_at=datetime(2026, 11, 9), newsletter_attached_via="list-id"))
    db.commit()
    doc = cs.build_candidate_sources(db)
    assert [c["domain"] for c in doc["candidates"]] == ["new.example"]
    row = doc["candidates"][0]
    assert row["proposal"] == "proposed" and row["tags"] == ["via:wikidata-discovery", "news", "fr"]
    assert row["feed"] == "https://new.example/feed.xml", "no user, password, query or fragment"
    assert row["evidence"]["articles_stored"] == 1 and row["evidence"]["attempts"] == {"qualified": 1}
    assert doc["left_out"] == {"in_a_shipped_catalogue": 1, "inherited_not_measured": 1, "newsletter_or_mailbox": 3}
    assert row["evidence"]["last_article"].startswith("2026-11-01"), "an attached newsletter stays out of the dates"
    assert "SECRET" not in json.dumps(doc) and "pw@" not in json.dumps(doc)


@pytest.mark.parametrize(("raw", "shown"), [
    ("https://news.example:8443/rss?k=1", "https://news.example:8443/rss"),
    ("http://[2606:4700::1111]/rss", "http://[2606:4700::1111]/rss"),
    ("https://news.example/feeds/private/a1b2c3d4e5f6a7b8c9d0/rss.xml", "https://news.example/feeds/private/[withheld]/rss.xml"),
    ("https://news.example/u/john.doe@mail.com/feed", "https://news.example/u/[withheld]/feed"),
    ("https://news.example/rss;jsessionid=ABC123", "https://news.example/rss"),
    ("https://news.example/2026/world-news/rss.xml", "https://news.example/2026/world-news/rss.xml"),
    ("https://news.example/p/how-to-learn-python-3-in-2026-guide", "https://news.example/p/how-to-learn-python-3-in-2026-guide"),
    ("https://news.example/feed/john.smith%40gmail.com", "https://news.example/feed/[withheld]"),
    ("https://news.example/k/deadbeefdeadbeef/rss", "https://news.example/k/[withheld]/rss"),
    ("http://0x7f.1/rss", "[non-public address withheld]"),
    ("http://[::1]:8080/rss", "[non-public address withheld]"),
    ("http://192.168.1.4/rss", "[non-public address withheld]"),
    ("http://intranet/rss", "[non-public address withheld]"),
    ("ftp://u:p@host/x", "[non-web address withheld]"),
    ("javascript:alert(1)", "[non-web address withheld]"),
    ("http://bad.example:port/x", "[address withheld]"),
    (None, None),
])
def test_feed_addresses_keep_only_scheme_host_port_and_path(raw, shown):
    assert cs.clean_feed_address(raw) == shown


def test_the_route_answers_a_zip_with_a_manifest_and_the_instance(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _src(db, 1, "new.example")
    fc = importlib.import_module("src.api.diagnostics.field_cards")
    paths = {(r.path, tuple(sorted(r.methods))) for r in fc.router.routes if r.path.endswith("/field-candidate-sources")}
    assert paths == {("/api/diagnostics/field-candidate-sources", ("POST",))}
    resp = fc.field_candidate_sources(db=db)
    from src.paths import instance_tag

    assert resp.headers["X-OO-Instance"] == instance_tag()
    with zipfile.ZipFile(io.BytesIO(resp.body)) as z:
        man = json.loads(z.read("manifest.json"))
        doc = json.loads(z.read("candidates.json"))
    assert man["instance"] == instance_tag() and "proposed" in man["proposal"] and doc["candidates"][0]["domain"] == "new.example"
    assert str(tmp_path) not in resp.body.decode("latin-1")


def _zip(path, inst, rows):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"instance": inst}))
        z.writestr("candidates.json", json.dumps({"candidates": rows}))
    return path


def test_the_script_groups_by_domain_across_instances_and_adds_nothing(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("psa", cs.__file__.replace("src/catalog/candidate_sources.py",
                                                                             "scripts/propose_source_additions.py"))
    psa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(psa)
    monkeypatch.setattr(psa, "_shipped_domains", lambda: frozenset({"old.example"}))
    a = {"domain": "new.example", "name": "New", "tags": ["news"], "language": "fr", "country": "fr",
         "evidence": {"articles_stored": 40, "attempts": {"qualified": 2}, "last_article": "2026-11-10"}}
    b = dict(a, language="en", evidence={"articles_stored": 7, "attempts": {"qualified": 1}})
    _zip(tmp_path / "one.zip", "aaaa1111", [a, {"domain": "old.example", "tags": []}])
    _zip(tmp_path / "two.zip", "bbbb2222", [b])
    _zip(tmp_path / "again.zip", "aaaa1111", [a])          # a second press of the first instance counts once
    (tmp_path / "x-part-001-of-002.zip").write_bytes(b"PK\x03\x04 half a zip")   # a lone piece is reported, not fatal
    out = tmp_path / "out"
    assert psa.main([str(tmp_path), "--out", str(out)]) == 0
    rep = json.loads((out / "proposed-sources.json").read_text(encoding="utf-8"))
    row = rep["rows"][0]
    assert row["domain"] == "new.example" and row["instances_n"] == 2 and row["max_articles_stored"] == 40
    assert row["disagreement"] == ["language"] and row["proposal"] == "proposed" and row["already_shipped"] is False
    assert row["attempts"] == {"qualified": 3} and row["tags"] == {"news": 2}, "one count per instance, never per press"
    assert rep["unreadable"] == ["x-part-001-of-002.zip: BadZipFile"]
    assert [r for r in rep["rows"] if r["domain"] == "old.example"][0]["already_shipped"] is True
    assert "Proposed source additions" in (out / "proposed-sources.md").read_text(encoding="utf-8")

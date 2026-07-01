"""Tests for the per-language keyword-log ZIP export (?format=zip) — the ≤20 MB
shareable archive — and that the analyzer reads it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

_ROOT = Path(__file__).resolve().parents[1]


def _load_analyzer():
    path = _ROOT / "scripts" / "analyze_keyword_log.py"
    spec = importlib.util.spec_from_file_location("analyze_keyword_log_zip_t", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'kz.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    # A multilingual corpus so the archive genuinely splits per language.
    docs = [
        ("en", "WHO warned that climate policy and trade policy will shape the decade ahead."),
        ("en", "Markets and inflation dominated the debate while traders weighed the data."),
        ("fr", "La politique climatique et le commerce ont dominé le sommet de Paris aujourd'hui."),
        ("fr", "Les marchés et l'inflation ont marqué la séance selon les analystes réunis."),
        ("de", "Die Klimapolitik und der Handel bestimmten die Debatte im Bundestag heute klar."),
    ]
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test", country="fr"))
        s.commit()
        for i, (lang, content) in enumerate(docs):
            a = Article(
                url=f"https://wire.test/{i}",
                canonical_url=f"https://wire.test/{i}",
                source_id=1,
                title=f"t{i}",
                content=content,
                hash=f"kz{i:060d}",
                language=lang,
                published_at=datetime(2026, 6, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
            s.add(a)
            s.commit()
            index_article(s, a, extractor=BaselineExtractor(), country="fr")

    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def _open_zip(content: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(content))
    return {n: z.read(n) for n in z.namelist()}


def test_keyword_zip_splits_per_language_and_is_bounded(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/keywords?format=zip")
            assert r.status_code == 200, r.text
            assert r.headers["content-type"] == "application/zip"
            assert len(r.content) <= 10 * 1024 * 1024  # under a typical 10 MB attach limit
            members = _open_zip(r.content)
            assert "manifest.json" in members and "summary.json" in members
            shards = [n for n in members if n.startswith("keywords/") and n.endswith(".json")]
            assert len(shards) >= 2  # at least en + fr split out

            manifest = json.loads(members["manifest.json"])
            assert manifest["kind"] == "keyword-diagnostics-archive"
            assert manifest["keywords_omitted_to_fit"] == 0  # small corpus: nothing trimmed

            # every shard parses; total keywords across shards == manifest count
            total = 0
            langs_seen = set()
            for n in shards:
                shard = json.loads(members[n])
                assert shard["count"] == len(shard["keywords"])
                total += shard["count"]
                langs_seen.add(shard["language"])
            assert total == manifest["keywords_in_archive"] and total > 0
            assert {"en", "fr"} <= langs_seen

            # summary carries the corpus-wide aggregates (not the keyword list)
            summary = json.loads(members["summary.json"])["data"]
            assert "families" in summary and "per_source_concentration" in summary
            assert "keywords" not in summary  # the keywords live in the shards

            # honesty: no composite scores anywhere in the archive
            assert all(b'"score"' not in members[n] and b"_score" not in members[n] for n in members)
    finally:
        app.dependency_overrides.clear()


def test_keyword_zip_caps_families_in_summary(tmp_path, monkeypatch):
    # The full per-keyword family dump was ~150 MB on a large corpus (redundant with the
    # shards, unused by the analyzer) and defeated the byte cap. summary.json now embeds
    # only the top-N families, recording the omission honestly.
    monkeypatch.setenv("OO_KEYWORD_LOG_FAMILIES", "1")
    app, client = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/keywords?format=zip")
            assert r.status_code == 200
            summary = json.loads(_open_zip(r.content)["summary.json"])["data"]
            prov = summary["families_provenance"]
            assert len(summary["families"]) <= 1  # capped to the top family
            assert prov["shown"] == len(summary["families"]) <= prov["total"]
            # if the corpus has more families than the cap, the omission is RECORDED (never silent)
            if prov["total"] > prov["shown"]:
                assert prov["omitted"] == prov["total"] - prov["shown"] > 0
            assert "keywords" not in summary  # the keywords still live in the shards
    finally:
        app.dependency_overrides.clear()


def test_keyword_zip_trims_per_language_when_over_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_KEYWORD_LOG_MAX_MB", "0.0005")  # ~512 B: forces trimming
    app, client = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/keywords?format=zip")
            assert r.status_code == 200
            manifest = json.loads(_open_zip(r.content)["manifest.json"])
            # trimming engaged, recorded honestly per language — never silent
            assert manifest["keywords_omitted_to_fit"] > 0
            assert sum(m["omitted_to_fit"] for m in manifest["languages"]) == (
                manifest["keywords_omitted_to_fit"]
            )
    finally:
        app.dependency_overrides.clear()


def test_keyword_zip_paging_exports_more_and_walks_the_full_set(tmp_path):
    """Maintainer 2026-06-21: export MORE than the top-5000/lang — per_lang raises the
    per-language quota and page walks through the whole corpus in digestible files."""
    def _kw(content: bytes) -> set:
        mem = _open_zip(content)
        out = set()
        for n in mem:
            if n.startswith("keywords/") and n.endswith(".json"):
                for k in json.loads(mem[n])["keywords"]:
                    out.add((k["language"], k["normalized"]))
        return out

    app, client = _client(tmp_path)
    try:
        with client:
            # per_lang=1, page 1 = the top keyword per language; more remain
            r1 = client.get("/api/diagnostics/keywords?format=zip&per_lang=1&page=1")
            m1 = json.loads(_open_zip(r1.content)["manifest.json"])
            assert m1["per_lang"] == 1 and m1["page"] == 1
            assert m1["has_more"] is True and m1["pages_total"] >= 2
            # page 2 is the NEXT slice — disjoint from page 1 (no double-export)
            r2 = client.get("/api/diagnostics/keywords?format=zip&per_lang=1&page=2")
            p1, p2 = _kw(r1.content), _kw(r2.content)
            assert p1 and p2 and p1.isdisjoint(p2)
            # a big per_lang exports the WHOLE set in one archive (nothing left over)
            rall = client.get("/api/diagnostics/keywords?format=zip&per_lang=1000000")
            mall = json.loads(_open_zip(rall.content)["manifest.json"])
            assert mall["has_more"] is False
            assert mall["keywords_in_archive"] == mall["keywords_total_corpus"]
            assert mall["keywords_in_archive"] >= m1["keywords_in_archive"]
    finally:
        app.dependency_overrides.clear()


def test_analyzer_reads_the_zip(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            content = client.get("/api/diagnostics/keywords?format=zip").content
    finally:
        app.dependency_overrides.clear()
    p = tmp_path / "oo-keyword-log.zip"
    p.write_bytes(content)
    analyzer = _load_analyzer()
    doc = analyzer.load_log(p)
    assert doc.get("kind") == "keyword-diagnostics"
    kws = doc["data"]["keywords"]
    assert isinstance(kws, list) and len(kws) > 0
    assert all("normalized" in k and "language" in k for k in kws)


def test_default_json_export_unchanged(tmp_path):
    # The default (no format) path must still be the JSON stream, byte-parity intact.
    app, client = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/keywords")
            assert r.status_code == 200
            assert "application/json" in r.headers["content-type"]
            body = json.loads(r.content)
            assert body["kind"] == "keyword-diagnostics"
            assert isinstance(body["data"]["keywords"], list)
    finally:
        app.dependency_overrides.clear()

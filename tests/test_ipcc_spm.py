"""IPCC AR6 SPM lane (src/ingest/ipcc_spm.py): consented fetch, honest extraction, provenance.

Hand-made fixtures only; the live www.ipcc.ch download is an operator step.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base
from src.ingest import ipcc_spm
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.ingest.pdf import pdf_available

_FIX = Path(__file__).parent / "fixtures" / "pdf"
_TEXT_PDF = (_FIX / "text_statute.pdf").read_bytes()
_IMAGE_PDF = (_FIX / "scanned_image.pdf").read_bytes()
needs_pypdf = pytest.mark.skipif(not pdf_available(), reason="pypdf not installed")


class _Resp:
    def __init__(self, content: bytes, headers: dict | None = None):
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_catalog_is_four_distinct_ipcc_pdfs():
    assert [e.key for e in ipcc_spm.SPM_CATALOG] == ["wg1", "wg2", "wg3", "syr"]
    assert len({e.url for e in ipcc_spm.SPM_CATALOG}) == 4
    for e in ipcc_spm.SPM_CATALOG:
        assert e.url.startswith(f"https://{ipcc_spm.IPCC_HOST}/") and e.url.endswith(".pdf")


def test_unknown_key_is_refused():
    with pytest.raises(ValueError):
        ipcc_spm.spm_entry("wg9")


def test_kill_switch_refuses_before_any_request(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: True)
    called = []
    with pytest.raises(RuntimeError, match=NETWORK_REFUSED):
        ipcc_spm.fetch_spm("wg1", get=lambda u: called.append(u))
    assert called == []


def test_fetch_returns_bytes_for_a_pdf(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    got = ipcc_spm.fetch_spm(
        "wg1", get=lambda u: _Resp(_TEXT_PDF, {"Content-Length": str(len(_TEXT_PDF))})
    )
    assert got == _TEXT_PDF


@pytest.mark.parametrize(
    "body,headers,msg",
    [
        (b"", {"Content-Length": "0"}, "empty"),
        (b"<html>not found</html>", {"Content-Length": "22"}, "not a PDF"),
        (_TEXT_PDF[:-10], {"Content-Length": "999999"}, "truncated"),
        (_TEXT_PDF, {}, "declared no length"),
    ],
)
def test_fetch_refuses_bodies_that_cannot_be_the_document(monkeypatch, body, headers, msg):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    with pytest.raises(ValueError, match=msg):
        ipcc_spm.fetch_spm("wg2", get=lambda u: _Resp(body, headers))


@needs_pypdf
def test_ingest_stores_one_article_under_its_own_source_and_is_idempotent(db):
    res = ipcc_spm.ingest_spm(db, "wg3", _TEXT_PDF)
    assert res["status"] == "imported"
    art = db.get(Article, res["article_id"])
    entry = ipcc_spm.spm_entry("wg3")
    assert art.url == entry.url and art.title == entry.title and art.language == "en"
    assert art.published_at.date().isoformat() == entry.approved
    assert art.source.domain == ipcc_spm.IPCC_SOURCE_DOMAIN
    assert ipcc_spm.ingest_spm(db, "wg3", _TEXT_PDF)["status"] == "duplicate"
    assert db.query(Article).count() == 1


@needs_pypdf
def test_scanned_pdf_stores_nothing(db):
    res = ipcc_spm.ingest_spm(db, "wg1", _IMAGE_PDF)
    assert res["status"] == "skipped" and res["reason"]
    assert db.query(Article).count() == 0


def test_non_pdf_bytes_store_nothing(db):
    assert ipcc_spm.ingest_spm(db, "syr", b"<html>nope</html>")["status"] == "skipped"
    assert db.query(Article).count() == 0


@needs_pypdf
def test_changed_file_at_same_address_is_not_overwritten(db, monkeypatch):
    first = ipcc_spm.ingest_spm(db, "wg1", _TEXT_PDF)
    monkeypatch.setattr(
        "src.ingest.pdf.extract_pdf_text", lambda data, **k: ("a different long text " * 40, "ok")
    )
    res = ipcc_spm.ingest_spm(db, "wg1", b"%PDF-x")
    assert res["status"] == "changed" and res["article_id"] == first["article_id"]
    assert db.query(Article).count() == 1


def test_disclosure_is_translated_in_all_locales():
    import json

    for p in sorted((Path(__file__).parents[1] / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert ipcc_spm.DISCLOSURE in d and "IPCC reports" in d, p.name


class _Stream(_Resp):
    def __init__(self, chunks, headers):
        super().__init__(b"", headers)
        self._chunks = chunks

    def iter_content(self, chunk_size=1):
        yield from self._chunks


def test_streamed_body_longer_than_declared_is_refused_while_reading(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    resp = _Stream([_TEXT_PDF, b"x" * 100], {"Content-Length": str(len(_TEXT_PDF))})
    with pytest.raises(ValueError, match="runs past"):
        ipcc_spm.fetch_spm("wg1", get=lambda u: resp)


def test_streamed_body_matching_declared_length_is_returned(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    half = len(_TEXT_PDF) // 2
    resp = _Stream([_TEXT_PDF[:half], _TEXT_PDF[half:]], {"Content-Length": str(len(_TEXT_PDF))})
    assert ipcc_spm.fetch_spm("wg1", get=lambda u: resp) == _TEXT_PDF


def test_http_error_propagates(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)

    class _Bad(_Resp):
        def raise_for_status(self):
            raise RuntimeError("HTTP 404")

    with pytest.raises(RuntimeError, match="404"):
        ipcc_spm.fetch_spm("wg1", get=lambda u: _Bad(b""))


def test_default_getter_is_held_to_the_ipcc_host_and_asks_for_identity(monkeypatch):
    seen = {}

    class _S:
        def get(self, url, **kw):
            seen["kw"] = kw
            return "resp"

    def fake_session(**kw):
        seen["session"] = kw
        return _S()

    monkeypatch.setattr(ipcc_spm, "guarded_session", fake_session)
    assert ipcc_spm._default_getter("https://www.ipcc.ch/x.pdf") == "resp"
    assert tuple(seen["session"]["allowed_hosts"]) == (ipcc_spm.IPCC_HOST,)
    assert seen["kw"]["stream"] is True and seen["kw"]["headers"]["Accept-Encoding"] == "identity"


class _Closing(_Stream):
    closed = False

    def close(self):
        self.closed = True


def test_response_is_closed_on_every_exit(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    over = _Closing([_TEXT_PDF, b"x"], {"Content-Length": str(len(_TEXT_PDF))})
    with pytest.raises(ValueError):
        ipcc_spm.fetch_spm("wg1", get=lambda u: over)
    assert over.closed
    ok = _Closing([_TEXT_PDF], {"Content-Length": str(len(_TEXT_PDF))})
    ipcc_spm.fetch_spm("wg1", get=lambda u: ok)
    assert ok.closed


def test_short_streamed_body_and_library_errors_become_truncated(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)

    class _Short(_Closing):
        def iter_content(self, chunk_size=1):
            yield b"%PDF-1"
            raise ConnectionError("IncompleteRead")

    with pytest.raises(ValueError, match="truncated transfer"):
        ipcc_spm.fetch_spm("wg1", get=lambda u: _Short([], {"Content-Length": "5000"}))


def test_server_that_compresses_despite_identity_is_named(monkeypatch):
    monkeypatch.setattr(ipcc_spm, "kill_switch_active", lambda: False)
    resp = _Closing([_TEXT_PDF], {"Content-Length": "10", "Content-Encoding": "gzip"})
    with pytest.raises(ValueError, match="compressed"):
        ipcc_spm.fetch_spm("wg1", get=lambda u: resp)

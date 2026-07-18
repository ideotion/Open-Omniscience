"""
Slice 3 (schema foundation) — the law versioned-text columns. A law is an Article + a linked
revision/audit trail (the versioned-sources ruling); this pins that LawDocument.latest_text (+revid)
and LawRevision.full_text exist and round-trip through CompressedText, mirroring the wiki columns.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, LawDocument, LawRevision


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_law_document_latest_text_round_trips():
    s = _session()
    body = "An Act to amend the law. " * 200  # a real-ish full text
    doc = LawDocument(jurisdiction="uk", title="Example Act", url="https://law.example/act",
                      latest_text=body, latest_text_revid=42)
    s.add(doc)
    s.commit()
    s.expire_all()
    got = s.query(LawDocument).one()
    assert got.latest_text == body          # CompressedText compressed on write, decompressed on read
    assert got.latest_text_revid == 42


def test_law_revision_full_text_makes_a_past_version_reconstructable():
    s = _session()
    doc = LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/loi")
    s.add(doc)
    s.flush()
    old = "Version one of the statute text. " * 50
    rev = LawRevision(document_id=doc.id, content_hash="a" * 64, full_text=old, diff="+ some added line")
    s.add(rev)
    s.commit()
    s.expire_all()
    got = s.query(LawRevision).one()
    assert got.full_text == old   # the FULL past text is stored, not only a lossy capped diff
    assert got.diff == "+ some added line"


def test_columns_default_to_null_so_the_change_is_additive():
    s = _session()
    doc = LawDocument(jurisdiction="us", title="Statute", url="https://law.example/s")
    s.add(doc)
    s.flush()
    rev = LawRevision(document_id=doc.id, content_hash="b" * 64)
    s.add(rev)
    s.commit()
    s.expire_all()
    assert s.query(LawDocument).one().latest_text is None
    assert s.query(LawRevision).one().full_text is None


def test_law_document_language_and_country_round_trip():
    """S4b (the Cambodia fix): additive columns for the catalog's own asserted
    per-document language/country."""
    s = _session()
    doc = LawDocument(jurisdiction="kh", title="Code civil", url="https://law.example/kh",
                      language="fr", country="kh")
    s.add(doc)
    s.commit()
    s.expire_all()
    got = s.query(LawDocument).one()
    assert got.language == "fr" and got.country == "kh"


def test_ensure_law_document_language_columns_self_heals_a_pre_existing_store():
    """A store created before language/country existed must self-heal at boot
    (the established additive-column pattern; matches ensure_law_text_columns)."""
    from sqlalchemy import text

    from src.database.maintenance import ensure_law_document_language_columns

    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        # A pre-fix schema: law_documents WITHOUT language/country.
        conn.execute(text(
            "CREATE TABLE law_documents (id INTEGER PRIMARY KEY, jurisdiction TEXT, "
            "title TEXT, url TEXT)"
        ))
    added = ensure_law_document_language_columns(engine)
    assert set(added) == {"law_documents.language", "law_documents.country"}
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(law_documents)")).fetchall()}
    assert {"language", "country"} <= cols
    # Idempotent: a second pass adds nothing.
    assert ensure_law_document_language_columns(engine) == []

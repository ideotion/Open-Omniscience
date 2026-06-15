"""
Tests for the local fixity audit (plan B-2) -- re-hash corpus vs capture hash.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Acceptance: a clean corpus reports zero mismatches; a row whose stored content is
mutated AFTER its hash was set is reported as mismatched (LOUDLY, never auto-fixed);
a row with no stored hash is reported under missing_hash; the exact method string is
present; and the recompute uses the SAME function the ingest pipeline stored with so
parity holds by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.utils.url_utils import generate_content_hash
from src.verification.fixity import METHOD, audit_fixity


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _add_article(s, *, n: int, content: str, hash_value: str | None = None) -> Article:
    """Insert one Article whose stored hash is the capture-time hash of ``content``
    unless ``hash_value`` overrides it (used to simulate post-capture mutation)."""
    src = Source(name=f"src{n:02d}", domain=f"src{n:02d}.example", country="zz")
    s.add(src)
    s.flush()
    art = Article(
        url=f"https://src{n:02d}.example/a",
        canonical_url=f"https://src{n:02d}.example/a",
        source_id=src.id,
        title=f"Article {n}",
        content=content,
        hash=hash_value if hash_value is not None else generate_content_hash(content),
        language="en",
        published_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    s.add(art)
    s.flush()
    return art


def test_clean_corpus_reports_zero_mismatches(session):
    for i in range(5):
        _add_article(session, n=i, content=f"Genuine article body number {i}, captured intact.")
    session.commit()

    result = audit_fixity(session)

    assert result["checked"] == 5
    assert result["ok"] == 5
    assert result["mismatched"] == 0
    assert result["missing_hash"] == 0
    assert result["mismatches"] == []
    # bookkeeping is internally consistent
    assert result["ok"] + result["mismatched"] + result["missing_hash"] == result["checked"]


def test_mutated_content_after_hash_is_flagged(session):
    good = _add_article(session, n=0, content="Untouched body that still matches its hash.")
    tampered = _add_article(session, n=1, content="Original captured body.")
    session.commit()

    # Simulate tampering / bit-rot: change the stored content AFTER the capture-time
    # hash was written, without updating the hash.
    captured_hash = tampered.hash
    tampered.content = "Silently rewritten body -- history must not be edited unnoticed."
    session.commit()

    result = audit_fixity(session)

    assert result["checked"] == 2
    assert result["ok"] == 1
    assert result["mismatched"] == 1
    assert result["missing_hash"] == 0

    flagged = result["mismatches"]
    assert len(flagged) == 1
    row = flagged[0]
    assert row["id"] == tampered.id
    assert row["stored_hash"] == captured_hash
    # the recomputed digest reflects the mutated content and differs from the stored one
    assert row["computed_hash"] == generate_content_hash(tampered.content)
    assert row["computed_hash"] != captured_hash
    assert "reason" in row

    # the genuine row is NOT among the mismatches
    assert all(r["id"] != good.id for r in flagged)


def test_missing_stored_hash_is_reported_loudly(session):
    _add_article(session, n=0, content="Body whose stored hash was lost.", hash_value="")
    session.commit()

    result = audit_fixity(session)

    assert result["checked"] == 1
    assert result["ok"] == 0
    assert result["mismatched"] == 0
    assert result["missing_hash"] == 1
    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0]["stored_hash"] is None


def test_method_string_and_timestamp_present(session):
    _add_article(session, n=0, content="Anything.")
    session.commit()

    result = audit_fixity(session)

    assert result["method"] == METHOD
    assert isinstance(result["method"], str) and result["method"]
    assert "generate_content_hash" in result["method"]
    assert "computed_at" in result and result["computed_at"]


def test_limit_bounds_the_work(session):
    for i in range(6):
        _add_article(session, n=i, content=f"Body {i}.")
    session.commit()

    result = audit_fixity(session, limit=3)

    assert result["checked"] == 3
    assert result["ok"] == 3


def test_empty_corpus_is_clean(session):
    result = audit_fixity(session)
    assert result["checked"] == 0
    assert result["ok"] == 0
    assert result["mismatched"] == 0
    assert result["missing_hash"] == 0
    assert result["mismatches"] == []

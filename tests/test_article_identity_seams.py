"""K1/K2 article identity seams (data-architecture Slice 5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

content_multihash + canon_version are ADDITIVE: stamped forward on every insert
(the before_insert hook), backfilled for existing rows (self-heal), and they must
NOT change the dedup-load-bearing `hash` (unique) one bit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.maintenance import ensure_article_identity_columns
from src.database.models import Article, Base, Source
from src.utils.url_utils import (
    CANON_VERSION,
    content_multihash,
    generate_content_hash,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _add(db, i, text_, *, hash_=None):
    h = hash_ or generate_content_hash(text_)
    a = Article(
        url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
        title="T", content=text_, hash=h, language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_forward_population_on_insert(db):
    a = _add(db, 1, "Some article body about a federal budget.")
    db.expire_all()
    a = db.get(Article, a.id)
    assert a.content_multihash == content_multihash("Some article body about a federal budget.")
    assert a.content_multihash == f"sha2-256:{a.hash}"  # consistent with the bare hash
    assert a.canon_version == CANON_VERSION


def test_helper_is_self_describing_and_consistent():
    text_ = "hello world"
    assert content_multihash(text_) == f"sha2-256:{generate_content_hash(text_)}"
    assert content_multihash("") == ""  # never a fabricated digest of nothing


def test_odd_hash_leaves_multihash_null_never_fabricated(db):
    # A non-64-hex hash (shouldn't happen via the real pipeline) must NOT get a
    # fabricated algorithm label — honest NULL instead.
    a = _add(db, 2, "x", hash_="short-hash")
    db.expire_all()
    a = db.get(Article, a.id)
    assert a.content_multihash is None
    assert a.canon_version == CANON_VERSION  # canon_version still stamped


def test_dedup_hash_is_untouched_and_still_unique(db):
    a = _add(db, 3, "dedup body text")
    # hash is unchanged by the seam (bare hex, no prefix).
    assert a.hash == generate_content_hash("dedup body text")
    assert ":" not in a.hash
    # the unique constraint on hash still bites
    from sqlalchemy.exc import IntegrityError

    dup = Article(
        url="https://x.test/dup", canonical_url="https://x.test/dup", source_id=1,
        title="T", content="dedup body text", hash=a.hash, language="en",
        created_at=datetime.now(UTC),
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_self_heal_adds_and_backfills_existing_rows():
    # Simulate an OLD-schema store: an articles table without the identity columns.
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE articles (id INTEGER PRIMARY KEY, hash VARCHAR(64), "
                "canonical_url VARCHAR(1000))"
            )
        )
        good = "a" * 64
        c.execute(
            text("INSERT INTO articles (id, hash, canonical_url) VALUES (1, :h, 'u')"),
            {"h": good},
        )
        c.execute(
            text("INSERT INTO articles (id, hash, canonical_url) VALUES (2, 'odd', 'u2')")
        )
    added = ensure_article_identity_columns(eng)
    assert set(added) == {"content_multihash", "canon_version"}
    with eng.begin() as c:
        rows = {
            r[0]: (r[1], r[2])
            for r in c.execute(text("SELECT id, content_multihash, canon_version FROM articles"))
        }
    assert rows[1] == (f"sha2-256:{'a' * 64}", "url-v1")  # backfilled from the 64-hex hash
    assert rows[2] == (None, "url-v1")  # odd hash -> no fabricated multihash, version still set
    # Idempotent second pass adds nothing.
    assert ensure_article_identity_columns(eng) == []

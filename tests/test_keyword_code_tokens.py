"""
Digit-heavy "code" tokens must never become keywords (field diagnostics 2026-06-23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The live keyword log (27,303 articles / 406,723 keywords) showed a ~35k bucket of
alphanumeric code tokens (A-10C, internal IDs, model-variant cruft, clock timecodes
like 1h15) minted as junk keywords. They cannot be told apart from REAL digit-bearing
terms by a digit RATIO — the maintainer's own keep/drop examples (a-10 keep vs a-10c
drop) are shape-identical modulo a trailing letter. The discriminator is the number of
letter<->digit transitions: a real designation keeps its digits in ONE run (1
transition), a code alternates (>= 2). We drop >= 2-transition tokens, with a small
allowlist of real multi-transition terms (flu subtypes, A1C), plus a glued-digit-prefix
catch for timecode fragments (1h15 -> h15). The non-negotiable: NO real term is lost —
this fixture proves it hard.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import (
    BaselineExtractor,
    _alnum_transitions,
    _is_code_token,
)
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source

# Real digit-bearing terms / designations that must SURVIVE (never dropped). Each is a
# pure word (0 transitions), a one-transition designation, or an allowlisted exception.
_KEEP = [
    "elections", "government", "economy",          # pure words
    "a-10", "f-18", "covid-19", "g7", "g20",        # one-transition designations
    "cop26", "b52", "mp3", "web3", "x86", "t-34",   #   (military / virus / tech / model)
    "mig-29", "su-57", "gpt4", "dota2",
    "x86_64",                                        # underscore is not a class boundary
    "h1n1", "h5n1", "h3n2", "h7n9", "a1c",          # allowlisted real multi-transition
]

# Multi-segment alphanumeric codes / IDs / model-variant cruft that must be DROPPED.
_DROP = [
    "a-10c", "b-52h",            # model variants (a-10/b52 stay; the -C/-H cruft goes)
    "a1b2", "x1y2z3", "gd1x2y",  # internal IDs
    "section3a", "r2d2", "c3po",  # doc refs / fictional codes
]


# --------------------------------------------------------------------------- #
# _alnum_transitions: the discriminator
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("a10", 1), ("a-10", 1), ("covid19", 1), ("mp3", 1), ("g7", 1), ("b52", 1),
        ("x86_64", 1), ("elections", 0), ("123", 0),
        ("a10c", 2), ("a1b2", 3), ("h1n1", 3), ("x1y2z3", 5),
    ],
)
def test_alnum_transitions_counts_letter_digit_changes(word, expected):
    assert _alnum_transitions(word) == expected


# --------------------------------------------------------------------------- #
# _is_code_token: hard keep/drop fixture (the brief's requirement)
# --------------------------------------------------------------------------- #
def test_is_code_token_keeps_every_real_term():
    leaked = [w for w in _KEEP if _is_code_token(w)]
    assert not leaked, f"real terms wrongly classified as code: {leaked}"


def test_is_code_token_drops_multi_segment_codes():
    survivors = [w for w in _DROP if not _is_code_token(w)]
    assert not survivors, f"code tokens not classified as code: {survivors}"


def test_is_code_token_never_touches_a_pure_word():
    # No digits -> never a code token, regardless of length or hyphens.
    for w in ("prime-minister", "anti-government", "self-driving", "neighbourhood"):
        assert not _is_code_token(w)


def test_code_filter_is_env_killable(monkeypatch):
    monkeypatch.setenv("OO_CODE_TOKEN_FILTER", "0")
    assert not _is_code_token("a-10c")  # disabled -> nothing is a code token
    assert not _is_code_token("x1y2z3")
    monkeypatch.delenv("OO_CODE_TOKEN_FILTER")
    assert _is_code_token("a-10c")  # default on


# --------------------------------------------------------------------------- #
# extract(): codes + timecodes absent, real terms present
# --------------------------------------------------------------------------- #
_ARTICLE = (
    "The briefing at 1h15 ran long, resuming at 12h00. The A-10C jets and the a1b2 "
    "tracking ids were mentioned. The A-10 jet, the F-18, COVID-19 cases, H1N1 flu, "
    "the G7 summit and an mp3 recording were discussed alongside the economy and "
    "the upcoming elections across the wider region."
)


def _norms(terms) -> set[str]:
    return {t.normalized.casefold() for t in terms}


def test_extract_drops_codes_and_timecodes_keeps_real_terms():
    norms = _norms(BaselineExtractor().extract(_ARTICLE))
    # Codes + clock-time fragments gone.
    for junk in ("a-10c", "a1b2", "h15", "h00"):
        assert junk not in norms, f"code/timecode leaked as keyword: {junk}"
    # Every real term survived.
    for real in ("a-10", "f-18", "covid-19", "h1n1", "g7", "mp3", "economy", "elections"):
        assert real in norms, f"real term lost: {real}"


def test_extract_offsets_unchanged_for_clean_text():
    # The code filter is token-level (no text mutation), so a clean article keeps
    # exact first-offsets — the reader's surrounding-sentence slice still lines up.
    text = "Markets fell as inflation worried traders about the wider economy today."
    for t in BaselineExtractor().extract(text):
        if t.first_offset is not None:
            assert text[t.first_offset:].lower().startswith(t.term.split()[0].lower())


# --------------------------------------------------------------------------- #
# end-to-end: indexing stores no code keywords; re-index drains them (counters OK)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_index_article_stores_no_code_keywords(db):
    db.add(Source(name="S", domain="x.test", country="us"))
    art = Article(
        url="https://x.test/1",
        canonical_url="https://x.test/1",
        source_id=1,
        title="T",
        content=_ARTICLE,
        hash="h-codes",
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(art)
    db.commit()

    index_article(db, art, extractor=BaselineExtractor())
    stored = {k.normalized_term.casefold() for k in db.query(Keyword).all()}
    assert not ({"a-10c", "a1b2", "h15", "h00"} & stored), f"code keywords indexed: {stored}"
    assert "a-10" in stored and "h1n1" in stored and "elections" in stored
    # Re-index stays clean and keeps counters consistent (one mention row per article).
    index_article(db, art, extractor=BaselineExtractor())
    for kw in db.query(Keyword).all():
        live = db.query(KeywordMention).filter_by(keyword_id=kw.id).count()
        assert kw.article_count == live

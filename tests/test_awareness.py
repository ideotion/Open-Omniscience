"""
Tests for the world-awareness features: local translation + honest framing.

Translation uses the mocked Ollama client (no real model); framing uses real
VADER sentiment + keyword extraction on fixtures and asserts it surfaces SIGNALS
without ever emitting a bias verdict.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.llm import get_llm_client
from src.api.main import app
from src.awareness.framing import compare_framing
from src.database.fts import ensure_fts
from src.database.models import Article, ArticleAnalysis, Base, Source
from src.database.session import get_db
from src.llm.ollama import OllamaClient

# --------------------------------------------------------------------------- #
# framing (pure function)
# --------------------------------------------------------------------------- #


def test_framing_surfaces_tone_and_terms_no_verdict():
    data = {
        "Outlet A": [
            {
                "title": "Reform praised",
                "content": "The landmark reform was praised as a historic success and a triumph.",
                "url": "a1",
                # LOAD-BEARING since 2026-07-29: compare_framing scores tone only for
                # English articles (VADER is an English lexicon), so a fixture without a
                # language is treated as unmeasurable -- the honest default. These
                # fixtures ARE English prose; the old test relied on ungated scoring.
                "language": "en",
                "published_at": None,
            }
        ],
        "Outlet B": [
            {
                "title": "Reform slammed",
                "content": "The disastrous reform was slammed as a corrupt failure and a scandal.",
                "url": "b1",
                "language": "en",
                "published_at": None,
            }
        ],
    }
    res = compare_framing(data)
    assert res["sources_compared"] == 2
    by = {f["source"]: f for f in res["framing"]}
    # real, opposite tone signals
    assert by["Outlet A"]["avg_tone"] > 0
    assert by["Outlet B"]["avg_tone"] < 0
    assert by["Outlet A"]["tone_label"] == "positive"
    assert by["Outlet B"]["tone_label"] == "negative"
    assert by["Outlet A"]["top_terms"]
    # honesty: no fabricated bias score/field anywhere -- only measurable signals,
    # and the caveat explicitly disclaims a verdict.
    for f in res["framing"]:
        assert not any("bias" in k or "score" in k for k in f)
    assert "signals" in res["caveat"].lower()
    assert "not a judgement" in res["caveat"].lower()


def test_framing_empty_source_skipped():
    res = compare_framing(
        {
            "A": [],
            "B": [{"title": "x", "content": "good news great", "url": "u", "published_at": None}],
        }
    )
    assert res["sources_compared"] == 1


# --------------------------------------------------------------------------- #
# API: translation + framing
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'a.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        a = Source(name="Le Monde", domain="lemonde.fr", language="fr")
        b = Source(name="Guardian", domain="theguardian.com", language="en")
        s.add_all([a, b])
        s.flush()
        s.add_all(
            [
                Article(
                    url="https://lemonde.fr/1",
                    canonical_url="https://lemonde.fr/1",
                    source_id=a.id,
                    title="Élection",
                    content="le scandale de corruption a indigné les électeurs",
                    hash="1".rjust(64, "0"),
                    language="fr",
                ),
                Article(
                    url="https://theguardian.com/2",
                    canonical_url="https://theguardian.com/2",
                    source_id=b.id,
                    title="Election reform",
                    content="the reform was welcomed as a positive step forward",
                    hash="2".rjust(64, "0"),
                    language="en",
                ),
            ]
        )
        s.commit()

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    def _fake_llm():
        def handler(request):
            return httpx.Response(
                200, json={"response": "Election: the corruption scandal outraged voters."}
            )

        http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        return OllamaClient(client=http, base_url="http://t")

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_llm_client] = _fake_llm
    with TestClient(app) as c:
        yield c, Sess
    app.dependency_overrides.clear()


def test_translate_persists_with_provenance(client):
    c, Sess = client
    r = c.post("/api/llm/articles/1/translate", json={"target_language": "English"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "translation"
    assert body["source_language"] == "fr"
    assert body["target_language"] == "English"
    assert body["prompt_version"].startswith("translate-v2")
    assert "corruption" in body["result"].lower()
    with Sess() as s:
        assert s.query(ArticleAnalysis).filter_by(kind="translation").count() == 1


def test_translate_unknown_article_404(client):
    c, _ = client
    assert c.post("/api/llm/articles/999/translate", json={}).status_code == 404


def test_framing_endpoint_groups_by_source(client):
    c, _ = client
    r = c.get("/api/framing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sources_compared"] == 2
    sources = {f["source"] for f in body["framing"]}
    assert sources == {"Le Monde", "Guardian"}
    assert "signals" in body["caveat"].lower()


def test_framing_endpoint_reports_no_tone_for_non_english_coverage(client):
    """End-to-end through the REAL endpoint (the fixture's Le Monde article is
    French, the Guardian one English). A compare_framing-only test would pass
    even if src/api/framing.py forgot to thread `language` -- this is the test
    that drives the production path, per the standing "a test double injected via
    a parameter BYPASSES the production path" lesson."""
    c, _ = client
    body = c.get("/api/framing").json()
    by = {f["source"]: f for f in body["framing"]}
    assert by["Le Monde"]["avg_tone"] is None and by["Le Monde"]["tone_label"] is None
    assert by["Le Monde"]["tone_unmeasured"] == 1
    assert by["Guardian"]["avg_tone"] is not None
    assert body["tone_unmeasured_articles"] >= 1


# --------------------------------------------------------------------------- #
# 2026-07-29: framing must never publish a FABRICATED NEUTRAL. VADER is an
# English lexicon and returns compound 0.0 for text it cannot read -- which is
# indistinguishable from a genuinely neutral English sentence -- so the previously
# ungated scoring published `tone_label: "neutral"` for EVERY non-English outlet.
# Its sibling src/analytics/sentiment.py:55 refuses exactly this by design.
# (The `if tones else 0.0` the design doc originally cited was unreachable dead
# code: the loop already `continue`s on an empty article list.)
# --------------------------------------------------------------------------- #
def test_framing_never_fabricates_a_neutral_for_a_language_vader_cannot_read():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    body = "le scandale de corruption a indigné les électeurs"
    # the MECHANISM, pinned: this is WHY an ungated score would be a fabrication.
    assert SentimentIntensityAnalyzer().polarity_scores(body)["compound"] == 0.0

    res = compare_framing(
        {
            "Le Monde": [
                {
                    "title": "Élection",
                    "content": body,
                    "url": "u",
                    "published_at": None,
                    "language": "fr",
                }
            ]
        }
    )
    f = res["framing"][0]
    assert f["avg_tone"] is None and f["tone_label"] is None
    assert f["tone_articles"] == 0 and f["tone_unmeasured"] == 1
    assert res["tone_measured_articles"] == 0 and res["tone_unmeasured_articles"] == 1


def test_framing_missing_language_is_a_gap_never_assumed_english():
    res = compare_framing(
        {"Unknown": [{"title": "x", "content": "good news great", "url": "u", "published_at": None}]}
    )
    assert res["framing"][0]["avg_tone"] is None


def test_framing_mixed_language_source_averages_only_the_readable_subset():
    """A source with 2 English + 1 French pieces reports tone over the 2, and SAYS
    SO -- the denominator travels with the number, never a silent average over a
    fabricated 0.0."""
    res = compare_framing(
        {
            "Wire": [
                {"title": "a", "content": "a historic success and a triumph", "url": "1",
                 "published_at": None, "language": "en"},
                {"title": "b", "content": "a wonderful and excellent outcome", "url": "2",
                 "published_at": None, "language": "en"},
                {"title": "c", "content": "le scandale de corruption", "url": "3",
                 "published_at": None, "language": "fr"},
            ]
        }
    )
    f = res["framing"][0]
    assert f["article_count"] == 3
    assert f["tone_articles"] == 2 and f["tone_unmeasured"] == 1
    assert f["avg_tone"] is not None and f["avg_tone"] > 0 and f["tone_label"] == "positive"


def test_framing_caveat_states_the_gap_is_not_a_neutral():
    res = compare_framing(
        {"X": [{"title": "t", "content": "c", "url": "u", "published_at": None, "language": "fr"}]}
    )
    caveat = res["caveat"].lower()
    assert "english" in caveat
    assert "neutral" in caveat  # explicitly says the gap is NOT a neutral
    assert "signals" in caveat and "not a judgement" in caveat


def test_framing_split_never_sorts_on_a_missing_tone():
    """producers.framing_split sorted EVERY framing row by avg_tone; once an
    unreadable-language outlet reports None that raises TypeError and blanks the
    producer. Pinned at the source: the sort must run over the MEASURED subset."""
    import inspect

    from src.briefing import producers as P

    src = inspect.getsource(P.framing_split)
    assert 'avg_tone") is not None' in src, (
        "framing_split must filter to measured outlets before sorting on avg_tone"
    )
    assert "sorted(measured" in src

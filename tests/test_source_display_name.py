"""A bare Wikidata id is never shown as a source's name (field test 2026-11-14, row 71).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.catalog.qid_labels import looks_like_bare_qid
from src.database.models import Source
from src.database.source_names import is_bare_qid, shown_source_name

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("name", "domain", "shown"),
    [
        ("Q11858063", "epari.fi", "epari.fi"),
        (" q42 ", " epari.fi ", "epari.fi"),
        ("Q42 Douglas Adams", "x.org", "Q42 Douglas Adams"),  # a label that starts with an id is a label
        ("Epari", "epari.fi", "Epari"),
        ("Q11858063", "", "Q11858063"),  # no domain: keep the id rather than show nothing
        ("Q11858063", None, "Q11858063"),
        (None, "epari.fi", None),
    ],
)
def test_shown_name(name, domain, shown):
    assert shown_source_name(name, domain) == shown


def test_same_test_as_the_label_resolver():
    for s in ["Q1", "q1", " Q123 ", "Q", "Q1a", "QQ1", "Q42 Douglas Adams", "", None, "1"]:
        assert is_bare_qid(s) == looks_like_bare_qid(s), s


def test_source_display_name_keeps_the_stored_name():
    s = Source(name="Q11858063", domain="epari.fi")
    assert s.display_name == "epari.fi" and s.name == "Q11858063"


# The reader and every list that credits an article to its source go through the helper; the
# exports (CSV/JSON) keep the stored value, which is provenance rather than display.
_DISPLAY_SITES = {
    "src/api/feed.py": "a.source.display_name",
    "src/api/framing.py": "a.source.display_name",
    "src/api/llm.py": "a.source.display_name",
    "src/api/markets.py": "r.source.display_name",
    "src/api/insights.py": "shown_source_name(",
    "src/api/link_analysis.py": "shown_source_name(",
    "src/api/search_instant.py": "shown_source_name(",
    "src/analytics/latest.py": "shown_source_name(",
}


@pytest.mark.parametrize(("path", "needle"), sorted(_DISPLAY_SITES.items()))
def test_display_sites_use_the_shown_name(path, needle):
    assert needle in (ROOT / path).read_text(encoding="utf-8")


def test_field_bundle_splits_the_flat_source_count():
    """The flat count read 20k-37k on the field test; the bundle now says what the parts are."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/diagnostics/debug-bundle")
    assert r.status_code == 200
    corpus = r.json()["data"]["corpus"]
    parts = ("sources_collecting", "sources_enabled_not_qualified", "sources_not_enabled")
    assert all(isinstance(corpus[k], int) for k in (*parts, "sources_named_by_bare_id")), corpus
    assert sum(corpus[k] for k in parts) == corpus["sources"]
    never = corpus["sources_never_stored"]
    grouped = sum(g["sources"] for g in never["groups"])
    assert never["total"] <= corpus["sources"] and grouped <= never["total"]
    assert never["groups_truncated"] is (grouped < never["total"])


def test_a_source_whose_enabled_flag_was_never_set_is_counted_in_the_split():
    """NULL is "never set", which the app reads as enabled: it must land in a part, or the parts stop summing."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from src.api.main import app
    from src.database.session import SessionLocal

    s = SessionLocal()
    try:
        row = Source(name="Q424242", domain="unset-flag.example.org", enabled=None)
        s.add(row)
        s.commit()
        sid = row.id
        # The ORM default would fill the flag in; a raw restore merge can leave it NULL, as this does.
        s.execute(text("UPDATE sources SET enabled = NULL WHERE id = :i"), {"i": sid})
        s.commit()
        assert s.execute(text("SELECT enabled FROM sources WHERE id = :i"), {"i": sid}).scalar() is None
    finally:
        s.close()
    try:
        with TestClient(app) as c:
            corpus = c.post("/api/diagnostics/debug-bundle").json()["data"]["corpus"]
        parts = ("sources_collecting", "sources_enabled_not_qualified", "sources_not_enabled")
        assert sum(corpus[k] for k in parts) == corpus["sources"]
    finally:
        s = SessionLocal()
        try:
            s.query(Source).filter(Source.id == sid).delete()
            s.commit()
        finally:
            s.close()


def test_a_failing_never_stored_scan_leaves_the_corpus_counts(monkeypatch):
    """The never-stored breakdown is one scan; when it fails, the counts beside it still report."""
    import sqlalchemy
    from fastapi.testclient import TestClient

    from src.api.main import app

    real_text = sqlalchemy.text

    def _text(sql, *a, **k):
        if "NOT EXISTS (SELECT 1 FROM articles x" in str(sql):
            raise sqlalchemy.exc.OperationalError(str(sql), {}, Exception("interrupted"))
        return real_text(sql, *a, **k)

    monkeypatch.setattr(sqlalchemy, "text", _text)
    with TestClient(app) as c:
        corpus = c.post("/api/diagnostics/debug-bundle").json()["data"]["corpus"]
    assert isinstance(corpus["articles"], int) and isinstance(corpus["sources"], int)
    assert corpus["sources_never_stored"] == {"error": "OperationalError"}

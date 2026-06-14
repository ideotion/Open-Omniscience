"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

The 0.09 performance batch (maintainer-mandated 2026-06-12): covering index,
streamed keyword export with cap-before-work, statement deadlines, boot-time
planner statistics, plaintext-only mmap, cached counts with disclosed
freshness, and the Settings VACUUM tool. Honesty contracts are tested as hard
as behaviour: the export envelope is unchanged, caches disclose their window,
timeouts fail loudly and typed.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    """A tiny two-language corpus with known counts (plus one zero-mention
    keyword, which the export contract keeps with zero counts)."""
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    with session_scope() as s:
        src = Source(name="PerfSeed", domain="perfseed.example", language="en", country="fr")
        s.add(src)
        s.flush()
        arts = []
        for i, lang in enumerate(["en", "en", "fr"]):
            a = Article(
                url=f"https://perfseed.example/{i}",
                canonical_url=f"https://perfseed.example/{i}",
                source_id=src.id,
                title=f"seed {i}",
                content=f"seed content {i}",
                language=lang,
                hash=f"perfseedhash{i:056d}",
            )
            s.add(a)
            arts.append(a)
        s.flush()
        kws = {}
        for term, lang in [("alpha-perf", "en"), ("beta-perf", "fr"), ("gamma-perf", "en")]:
            k = Keyword(term=term, normalized_term=term, language=lang)
            s.add(k)
            kws[term] = k
        s.flush()
        # alpha: 2 en articles (counts 3+2); beta: 1 fr article (count 4); gamma: none.
        s.add(
            KeywordMention(
                keyword_id=kws["alpha-perf"].id,
                article_id=arts[0].id,
                count=3,
                observed_on=date(2026, 1, 5),
            )
        )
        s.add(
            KeywordMention(
                keyword_id=kws["alpha-perf"].id,
                article_id=arts[1].id,
                count=2,
                observed_on=date(2026, 2, 6),
            )
        )
        s.add(
            KeywordMention(
                keyword_id=kws["beta-perf"].id,
                article_id=arts[2].id,
                count=4,
                observed_on=date(2026, 3, 7),
            )
        )
        ids = {t: k.id for t, k in kws.items()}
    yield ids
    with session_scope() as s:
        id_list = ",".join(str(i) for i in ids.values())
        s.execute(text(f"DELETE FROM keyword_mentions WHERE keyword_id IN ({id_list})"))
        s.execute(text(f"DELETE FROM keywords WHERE id IN ({id_list})"))
        s.execute(text("DELETE FROM articles WHERE url LIKE 'https://perfseed.example/%'"))
        s.execute(text("DELETE FROM sources WHERE domain = 'perfseed.example'"))


# --------------------------------------------------------------------------- #
# Covering index + boot upkeep
# --------------------------------------------------------------------------- #
def test_covering_index_exists_after_init(client):
    from src.database.session import engine

    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            )
        }
    assert "ix_mention_covering" in names


def test_ensure_hot_indexes_self_heals(client):
    from src.database.maintenance import ensure_hot_indexes
    from src.database.session import engine

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_mention_covering"))
    created = ensure_hot_indexes(engine)
    assert created == ["ix_mention_covering"]
    assert ensure_hot_indexes(engine) == []  # idempotent


def test_migration_matches_model_index():
    """Drift guard: the alembic migration creates exactly the model's index."""
    from pathlib import Path

    from src.database.models import KeywordMention

    model_cols = None
    for idx in KeywordMention.__table_args__:
        if getattr(idx, "name", "") == "ix_mention_covering":
            model_cols = [c.name for c in idx.columns]
    assert model_cols == ["keyword_id", "article_id", "count", "observed_on"]
    mig = Path("migrations/versions/e2f3a4b5c6d7_mention_covering_index.py").read_text(encoding="utf-8")
    for col in model_cols:
        assert col in mig


def test_optimize_at_boot_reports_real_work(client):
    from src.database.maintenance import optimize_at_boot
    from src.database.session import engine

    out = optimize_at_boot(engine)
    assert "duration_ms" in out and out["duration_ms"] >= 0
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT name FROM sqlite_master WHERE name='sqlite_stat1'")
        ).fetchone()


def test_mmap_applied_on_plaintext_connection(client):
    from src.database.session import engine

    with engine.connect() as conn:
        size = conn.execute(text("PRAGMA mmap_size")).scalar()
    # The suite runs the explicit plaintext profile; mmap must be active.
    assert int(size) == 268435456


# --------------------------------------------------------------------------- #
# Statement deadline (loud, typed)
# --------------------------------------------------------------------------- #
def test_statement_deadline_aborts_runaway_query(client):
    from src.database.maintenance import StatementTimeout, statement_deadline
    from src.database.session import session_scope

    runaway = text(
        "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt"
        " LIMIT 200000000) SELECT MAX(x) FROM cnt"
    )
    with session_scope() as s:
        with pytest.raises(StatementTimeout, match="deadline"), statement_deadline(s, seconds=0.05):
            s.execute(runaway).scalar()
        # The connection stays usable after the abort (handler removed).
        assert s.execute(text("SELECT 1")).scalar() == 1


def test_statement_deadline_zero_disables(client):
    from src.database.maintenance import statement_deadline
    from src.database.session import session_scope

    with session_scope() as s, statement_deadline(s, seconds=0):
        assert s.execute(text("SELECT 1")).scalar() == 1


# --------------------------------------------------------------------------- #
# The streamed keyword export (contract unchanged)
# --------------------------------------------------------------------------- #
def test_keyword_export_streams_valid_envelope(client, seeded):
    r = client.get("/api/diagnostics/keywords")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = json.loads(r.content)  # the streamed chunks form ONE valid document
    assert body["export_schema"] == "oo-export-1"
    assert body["kind"] == "keyword-diagnostics"
    data = body["data"]
    for key in ("corpus", "method", "keywords", "families", "overrides", "supergroups"):
        assert key in data
    by_term = {k["term"]: k for k in data["keywords"]}
    alpha, beta, gamma = (
        by_term["alpha-perf"],
        by_term["beta-perf"],
        by_term["gamma-perf"],
    )
    assert alpha["mentions"] == 5 and alpha["articles"] == 2
    assert alpha["first_seen"] == "2026-01-05" and alpha["last_seen"] == "2026-02-06"
    assert alpha["language_signature"] == {"en": 2}
    assert beta["mentions"] == 4 and beta["language_signature"] == {"fr": 1}
    # Zero-mention keywords stay in the export with honest zeros (old contract).
    assert gamma["mentions"] == 0 and gamma["articles"] == 0
    assert gamma["first_seen"] is None and gamma["language_signature"] == {}
    # Mentions-descending among mentioned keywords.
    terms = [k["term"] for k in data["keywords"] if k["term"].endswith("-perf")]
    assert terms.index("alpha-perf") < terms.index("beta-perf") < terms.index("gamma-perf")
    assert body["count"] == data["corpus"]["keywords_exported"] == len(data["keywords"])


def test_keyword_export_cap_bounds_work_per_language(client, seeded, monkeypatch):
    from src.api import diagnostics as d

    monkeypatch.setattr(d, "_MAX_KEYWORDS_PER_LANG", 1)
    body = json.loads(client.get("/api/diagnostics/keywords").content)
    per_lang = body["data"]["corpus"]["exported_per_language"]
    assert all(v <= 1 for v in per_lang.values())
    assert "en" in body["data"]["corpus"]["capped_languages"]  # alpha won, gamma capped


# --------------------------------------------------------------------------- #
# Cached counts (freshness disclosed) + the VACUUM tool
# --------------------------------------------------------------------------- #
def test_stats_cached_with_disclosed_freshness(client):
    from src.api import database as dbmod

    dbmod._cache.clear()
    first = client.get("/api/database/stats").json()
    assert "computed_at" in first and first["cache_ttl_s"] == dbmod._CACHE_TTL_S
    assert "reclaimable_bytes" in first
    second = client.get("/api/database/stats").json()
    assert second["computed_at"] == first["computed_at"]  # served from cache
    dbmod._cache.clear()
    third = client.get("/api/database/stats").json()
    assert "computed_at" in third


def test_vacuum_endpoint_reports_real_numbers(client):
    r = client.post("/api/database/vacuum")
    assert r.status_code == 200
    out = r.json()
    assert out["supported"] is True
    assert out["bytes_before"] > 0 and out["bytes_after"] > 0
    assert out["duration_ms"] >= 0
    assert "VACUUM" in out["method"]


# --------------------------------------------------------------------------- #
# Near-dup: numpy/pure parity, memo purity
# --------------------------------------------------------------------------- #
def test_minhash_numpy_and_pure_paths_identical():
    import src.signals.near_dup as nd

    sh = nd.shingles("the quick brown fox jumps over the lazy dog again and again")
    fast = nd.minhash_signature(sh, 64)
    saved = nd._np
    nd._np = None
    try:
        pure = nd.minhash_signature(sh, 64)
    finally:
        nd._np = saved
    if saved is None:  # core-only install: both runs were the pure path
        pytest.skip("numpy not installed; parity not measurable here")
    assert fast == pure


def test_near_dup_memo_returns_equal_isolated_results():
    from src.signals.near_dup import near_duplicate_clusters

    docs = {
        "a": "the central bank raised interest rates amid inflation worries today",
        "b": "the central bank raised interest rates amid inflation worries today!!",
        "c": "completely different text about a football match in another country",
    }
    r1 = near_duplicate_clusters(docs)
    r2 = near_duplicate_clusters(docs)
    assert r1.to_dict() == r2.to_dict()
    # Mutating one result must not poison the cache (defensive copies).
    if r1.clusters:
        r1.clusters[0].members.append("tampered")
    r3 = near_duplicate_clusters(docs)
    assert "tampered" not in (r3.clusters[0].members if r3.clusters else [])


# --------------------------------------------------------------------------- #
# The performance field report (maintainer-asked 2026-06-12): real evidence,
# on click, never transmitted.
# --------------------------------------------------------------------------- #
def test_performance_report_carries_real_evidence(client, seeded):
    client.get("/api/database/stats")  # ensure at least one measured request
    r = client.get("/api/diagnostics/performance")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.json()
    assert body["kind"] == "performance-report"
    data = body["data"]
    env = data["environment"]
    assert env["cpu_count"] >= 1 and env["at_rest_state"].startswith("unlocked")
    assert data["store"]["page_size"] > 0
    assert data["corpus"]["keywords"] >= 3
    lat = data["endpoint_latency_since_boot"]
    assert "real use since this boot" in lat["method"]
    st = data["selftest"]
    assert st["ran"] is True
    probes = {row["probe"] for row in st["results"]}
    assert {"database_stats", "insights_map", "keyword_export_streamed"} <= probes
    for row in st["results"]:
        assert ("ms" in row) or ("error" in row)  # measured or honestly failed
    streamed = [x for x in st["results"] if x["probe"] == "keyword_export_streamed"]
    assert all("bytes" in x for x in streamed), "streamed body must be fully consumed"


def test_performance_report_selftest_can_be_skipped(client):
    body = client.get("/api/diagnostics/performance?selftest=false").json()
    assert body["data"]["selftest"]["ran"] is False
    assert body["data"]["selftest"]["results"] == []

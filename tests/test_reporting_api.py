"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoint tests for the reporting router (finding TEST-05, 0.0.8 WP4):
POST /api/reports/evidence and POST /api/reports/evidence/verify had no
dedicated tests. Covers bundle build (by ids), the verify round-trip, tamper
detection, and the validation failure paths.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Article, Source
from src.database.session import init_db, session_scope


def _seed_articles(n: int = 2) -> list[int]:
    init_db()
    ids: list[int] = []
    with session_scope() as s:
        domain = f"rep-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"Reporting {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        for i in range(n):
            a = Article(
                url=f"https://{domain}/a/{i}",
                canonical_url=f"https://{domain}/a/{i}",
                source_id=src.id,
                title=f"Evidence article {i}",
                content=f"Body of evidence article {i} " * 20,
                language="en",
                hash=uuid.uuid4().hex + uuid.uuid4().hex,  # 64 hex chars
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
    return ids


def test_evidence_bundle_builds_and_verifies_round_trip():
    ids = _seed_articles(2)
    with TestClient(app) as client:
        r = client.post("/api/reports/evidence", json={"article_ids": ids, "case_name": "t-1"})
        assert r.status_code == 200
        bundle = r.json()
        # Signed-bundle contract: {manifest, signature, public_key, algorithm},
        # manifest carrying items + the Merkle root.
        assert bundle["manifest"]["items"]
        assert bundle["manifest"]["merkle_root"]
        assert bundle["signature"] and bundle["public_key"]

        v = client.post("/api/reports/evidence/verify", json={"bundle": bundle})
        assert v.status_code == 200
        out = v.json()
        assert out["verified"] is True, out


def test_tampered_bundle_fails_verification():
    ids = _seed_articles(1)
    with TestClient(app) as client:
        bundle = client.post("/api/reports/evidence", json={"article_ids": ids}).json()
        # Flip one character somewhere inside the payload's content.
        import json as _json

        raw = _json.dumps(bundle)
        tampered = raw.replace("Evidence article", "Tampered article", 1)
        v = client.post(
            "/api/reports/evidence/verify", json={"bundle": _json.loads(tampered)}
        )
        assert v.status_code == 200
        assert v.json()["verified"] is False


def test_evidence_requires_ids_or_query():
    with TestClient(app) as client:
        r = client.post("/api/reports/evidence", json={})
        assert r.status_code == 400


def test_evidence_404_when_nothing_matches():
    init_db()
    with TestClient(app) as client:
        r = client.post("/api/reports/evidence", json={"article_ids": [99999999]})
        assert r.status_code == 404

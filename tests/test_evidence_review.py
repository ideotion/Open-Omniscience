"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The review before a signed evidence bundle is saved (gate row K, brief S05-11 S5).

The Search tab's and the analysis window's "Export signed evidence" buttons used to write
the file at once and say "Signed bundle: N item(s)" in a toast. They now open a review
first (``POST /api/reports/evidence/plan``, ``src/static/app-evidence.js``). The route's
promises are what these tests hold it to:

* READ-ONLY: looking at the plan creates no signing key and writes nothing (a review that
  changes the install is not a review);
* the numbers are the bundle's own: the same selection gives the same article count, and the
  item fields it lists ARE the keys ``_article_item`` writes (one list, not two);
* the text is not in the bundle and the plan says so;
* an empty selection and a missing scope refuse loudly, exactly like the export.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Article, Source
from src.database.session import init_db, session_scope
from src.reporting import evidence as ev

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def _seed(n_sources: int = 2, per_source: int = 2) -> list[int]:
    init_db()
    ids: list[int] = []
    with session_scope() as s:
        for k in range(n_sources):
            domain = f"evrev-{uuid.uuid4().hex[:8]}.example"
            src = Source(name=f"Review {domain}", domain=domain, language="en")
            s.add(src)
            s.flush()
            for i in range(per_source):
                a = Article(
                    url=f"https://{domain}/a/{k}-{i}",
                    canonical_url=f"https://{domain}/a/{k}-{i}",
                    source_id=src.id,
                    title=f"Review article {k}-{i}",
                    content=f"Body {k}-{i} " * 30,
                    language="en",
                    hash=uuid.uuid4().hex + uuid.uuid4().hex,
                )
                s.add(a)
                s.flush()
                ids.append(a.id)
    return ids


@pytest.fixture()
def key_path(tmp_path, monkeypatch) -> Path:
    """An isolated key location, so a test can prove nothing was created there."""
    p = tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(ev, "_default_key_path", lambda: p)
    return p


def test_plan_counts_articles_and_sources_and_names_the_fields(key_path):
    ids = _seed(n_sources=2, per_source=2)
    with TestClient(app) as client:
        r = client.post("/api/reports/evidence/plan", json={"article_ids": ids})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["articles"] == 4
    assert plan["sources"] == 2
    assert plan["bundle_version"] == ev.BUNDLE_VERSION
    assert plan["text_included"] is False
    assert plan["item_fields"] == list(ev.ITEM_FIELDS)


def test_plan_creates_no_signing_key(key_path):
    ids = _seed()
    assert not key_path.exists()
    with TestClient(app) as client:
        plan = client.post("/api/reports/evidence/plan", json={"article_ids": ids}).json()
    assert plan["signer"] == {"exists": False, "state": "none", "ed25519_pub": None}
    assert not key_path.exists(), "the review must not create the key"
    assert not key_path.parent.exists() or not any(key_path.parent.iterdir())


def test_plan_names_the_key_that_will_sign_once_one_exists(key_path):
    ids = _seed()
    with TestClient(app) as client:
        bundle = client.post("/api/reports/evidence", json={"article_ids": ids}).json()
        plan = client.post("/api/reports/evidence/plan", json={"article_ids": ids}).json()
    assert key_path.exists(), "the export creates the key"
    assert plan["signer"]["exists"] is True
    assert plan["signer"]["state"] == "ok"
    assert plan["signer"]["ed25519_pub"] == bundle["public_key"]
    assert plan["articles"] == bundle["manifest"]["item_count"]


def test_a_foreign_or_unreadable_key_file_reads_as_no_key_and_is_left_alone(key_path):
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(b"not a pem file")
    assert ev.existing_public_key_hex() is None
    assert key_path.read_bytes() == b"not a pem file", "a review never rewrites a key file"


def test_a_key_that_vanishes_or_is_odd_is_never_regenerated_by_a_review(key_path, monkeypatch):
    # missing: no key, and none created
    assert ev.existing_public_key_hex() is None
    assert not key_path.exists()
    # a PEM of another algorithm reads as no key (the export fails loudly, where someone waits)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PrivateKey

    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(Ed448PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    assert ev.existing_public_key_hex() is None
    # the helper must not even hold a path to key CREATION
    import inspect

    assert "load_or_create_signing_key(" not in inspect.getsource(ev.existing_public_key_hex)


def test_the_plan_counts_with_a_select_not_by_loading_article_rows():
    import inspect

    from src.api import reporting

    body = inspect.getsource(reporting.plan_evidence)
    assert "_select_articles" not in body, "counts need no article text in memory"
    assert "func.count" in body


def test_the_listed_fields_are_the_keys_the_export_writes(key_path):
    ids = _seed(1, 1)
    with TestClient(app) as client:
        bundle = client.post("/api/reports/evidence", json={"article_ids": ids}).json()
    item = bundle["manifest"]["items"][0]
    assert list(item) == list(ev.ITEM_FIELDS), "the review promises exactly what the file holds"
    assert "content" not in item and "text" not in item


def test_plan_refuses_an_empty_selection_and_a_missing_scope(key_path):
    with TestClient(app) as client:
        none = client.post("/api/reports/evidence/plan", json={"article_ids": [987654321]})
        no_scope = client.post("/api/reports/evidence/plan", json={})
    assert none.status_code == 404
    assert no_scope.status_code == 400
    assert not key_path.exists()


def test_plan_by_query_counts_what_the_export_writes(key_path):
    _seed(2, 2)
    term = "Review"
    with TestClient(app) as client:
        bad = client.post("/api/reports/evidence/plan", json={"query": '"unterminated'})
        plan = client.post("/api/reports/evidence/plan", json={"query": term})
        bundle = client.post("/api/reports/evidence", json={"query": term})
    assert bad.status_code in (400, 404)
    assert plan.status_code == 200 and bundle.status_code == 200, (plan.text, bundle.text)
    assert plan.json()["articles"] == bundle.json()["manifest"]["item_count"] >= 1


def test_a_present_but_unusable_key_is_named_by_the_plan_and_refused_by_the_export(key_path):
    """The review must not promise 'a key is created' when a file is in the way: saving
    fails on it (a foreign PEM is never replaced), so the plan says 'unreadable' and the
    export answers with the reason, not a bare 500."""
    ids = _seed()
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(b"not a pem file")
    with TestClient(app) as client:
        plan = client.post("/api/reports/evidence/plan", json={"article_ids": ids}).json()
        export = client.post("/api/reports/evidence", json={"article_ids": ids})
    assert plan["signer"] == {"exists": True, "state": "unreadable", "ed25519_pub": None}
    assert export.status_code == 409 and "signing key" in export.json()["detail"]
    assert key_path.read_bytes() == b"not a pem file"


# ---- the page --------------------------------------------------------------


def test_the_page_wires_the_review_and_the_old_direct_export_is_gone():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="evidence-review"' in html
    for ident in ("evidence-body", "evidence-status", "evidence-close", "evidence-save"):
        assert f'id="{ident}"' in html, ident
    assert '<script src="/static/app-evidence.js"></script>' in html
    assert html.index('src="/static/app-evidence.js"') < html.index('src="/static/app-boot.js"')

    tools = (_STATIC / "app-ai-tools.js").read_text(encoding="utf-8")
    body = re.search(r"function exportEvidence\(scope\) \{(.*?)\n    \}", tools, re.S)
    assert body, "exportEvidence not found"
    assert "openEvidenceReview(" in body.group(1)
    assert "/api/reports/evidence" not in body.group(1), "the button no longer writes the file itself"


def test_the_review_module_is_precached_and_has_no_inline_handlers():
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    assert "/static/app-evidence.js" in sw
    js = (_STATIC / "app-evidence.js").read_text(encoding="utf-8")
    assert not re.search(r"\bon(click|change|input|submit)\s*=", js), "the CSP has no 'unsafe-inline'"
    assert "innerHTML" in js and "esc(" in js


def test_a_save_in_flight_is_dropped_when_its_dialog_closed_or_moved_on():
    js = (_STATIC / "app-evidence.js").read_text(encoding="utf-8")
    save = re.search(r"async function evidenceSave\(\) \{(.*?)\n    \}\n", js, re.S).group(1)
    assert "const mine = _evSeq" in save and "mine !== _evSeq" in save
    assert "!dlg.open" in save, "a closed dialog downloads nothing"
    assert 'addEventListener("close"' in js and "_evSeq++" in js, "Esc and Cancel both retire it"
    # a stale plan's failure does not toast over the newer review
    assert "if (seq === _evSeq) toast(" in js


def test_the_save_button_still_goes_through_the_signed_export_and_names_the_key():
    js = (_STATIC / "app-evidence.js").read_text(encoding="utf-8")
    assert '"/api/reports/evidence"' in js and '"/api/reports/evidence/plan"' in js
    assert "Signing key (Ed25519), to give the recipient some other way:" in js


def test_the_review_renderers_behave():
    import subprocess

    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "evidence_review_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout

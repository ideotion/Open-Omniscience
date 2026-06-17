"""
Corpus-scoped coordination (the ambient "N near-identical copies = one voice"
surface in the analysis window) + the Related-subtab / branch wiring.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17: the coordination scan is ambient/automatic and lives
in the analysis window, and related articles can BRANCH into a new corpus for
associated research. These checks pin the honesty (independence = distinct
sources; single-source repeat flagged; no score; caveat present) and the frontend
wiring (Related subtab -> corpus-coordination -> openAnalysisForIds branch).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.queries import corpus_coordination
from src.database.models import Article, Base, Source

_ROOT = Path(__file__).resolve().parents[1]

# A long, identical body so MinHash word-shingles (k=5) over near-identical docs
# estimate Jaccard well above the 0.7 confirm threshold.
_SHARED = (
    "The ministry announced a sweeping new policy on coastal infrastructure funding "
    "today, citing climate resilience and regional development goals as the central "
    "justification for the multi-year program of public works it intends to deliver "
    "across the northern provinces over the coming decade and beyond."
)
_UNIQUE = (
    "An unrelated local report describes a small community garden opening in the old "
    "railway district after several years of patient volunteer fundraising, planning "
    "permission battles, soil remediation work and a great deal of neighbourly effort."
)


def _mk_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _add(s, *, aid, source_id, title, body):
    s.add(Article(
        id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
        source_id=source_id, title=title, content=body, hash=f"h{aid}", language="en",
    ))


def test_near_identical_across_sources_is_one_coordinated_cluster():
    s = _mk_session()
    for i in (1, 2, 3):
        s.add(Source(id=i, name=f"Outlet {i}", domain=f"outlet{i}.test"))
    _add(s, aid=1, source_id=1, title="Alpha", body=_SHARED)
    _add(s, aid=2, source_id=2, title="Beta", body=_SHARED)
    _add(s, aid=3, source_id=3, title="Gamma", body=_SHARED)
    _add(s, aid=4, source_id=1, title="Delta", body=_UNIQUE)   # unique -> no cluster
    s.commit()

    res = corpus_coordination(s, article_ids=[1, 2, 3, 4])
    assert res["n_articles"] == 4
    assert len(res["clusters"]) == 1, res
    c = res["clusters"][0]
    assert c["size"] == 3 and set(c["article_ids"]) == {1, 2, 3}
    assert c["distinct_sources"] == 3 and c["single_source"] is False
    # the EXACT set is carried for the branch; counts only, NO composite score
    assert "score" not in c
    assert res["caveat"] and ("not proof" in res["caveat"].lower())


def test_single_source_repeat_is_flagged_as_one_voice_not_coordination():
    s = _mk_session()
    s.add(Source(id=1, name="Solo", domain="solo.test"))
    _add(s, aid=10, source_id=1, title="x", body=_SHARED)
    _add(s, aid=11, source_id=1, title="y", body=_SHARED)
    s.commit()

    res = corpus_coordination(s, article_ids=[10, 11])
    assert len(res["clusters"]) == 1
    c = res["clusters"][0]
    assert c["size"] == 2 and c["distinct_sources"] == 1 and c["single_source"] is True


def test_empty_corpus_is_honest():
    s = _mk_session()
    res = corpus_coordination(s, article_ids=[])
    assert res["clusters"] == [] and res["n_clusters"] == 0
    assert res["caveat"] and res["method"]


def test_related_subtab_is_wired_and_branches_into_a_new_corpus():
    js = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="related"' in html and 'id="an-related"' in html
    assert "function renderAnRelated" in js and "function branchFromRelated" in js
    assert 'key === "related"' in js, "anSelectTab must lazy-render Related"
    assert "/api/insights/corpus-coordination" in js
    # the branch spawns a NEW corpus over the cluster's exact article ids
    assert "openAnalysisForIds(c.article_ids" in js
    # honesty visible by default
    assert "= effectively one voice" in js and "= one voice" in js
    assert "card-caveat" in js

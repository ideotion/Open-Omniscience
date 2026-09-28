"""The Claim Workspace, slice 1 (gate row K, brief S05-11 S1): steps ①②③⑤.

The A-2 "Done when" is pinned here in its testable half: the independence grouping is
tested against a SEEDED WIRE-ECHO FIXTURE -- one wire story re-run by three outlets (one
near-identical copy, two attributing the wire in their own words), one outlet citing the
same origin page, and two genuinely unconnected reports -- plus the negative space the brief
names: a claim with no related article (the Socratic empty state), a single-source trail
(no independence claim), and no field named like a score anywhere in the payload.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import claim_workspace as cw
from src.api.main import app
from src.database.models import Article, ArticleLink, Base, Source
from src.database.session import get_db

_WIRE_BODY = (
    "Glacier melt in the Alps doubled between 2000 and 2020, a study published on Monday "
    "found. The researchers measured the ice loss of 180 glaciers with satellite images. "
    "The loss accelerated after 2015, the authors said."
)


def _seed(TS):
    now = datetime(2026, 9, 1, 12, 0)
    with TS() as s:
        srcs = {
            key: Source(name=name, domain=dom, country=cc, language=lang, source_type=st)
            for key, name, dom, cc, lang, st in [
                ("wire", "Wire Desk", "wiredesk.example", "gb", "en", "news"),
                ("echo1", "Echo Daily", "echo1.example", "us", "en", "news"),
                ("echo2", "Echo Times", "echo2.example", "au", "en", "news"),
                ("cite", "Citing Post", "cite.example", "ca", "en", "news"),
                ("indep", "Alpine Review", "alpine.example", "ch", "de", "news"),
                ("stats", "Stat Office", "stats.example", "fr", "fr", "statistics"),
                ("other", "Unrelated Gazette", "other.example", "jp", "ja", "news"),
            ]
        }
        s.add_all(srcs.values())
        s.flush()

        def art(key, i, title, body, days):
            a = Article(url=f"https://{srcs[key].domain}/{i}", canonical_url=f"https://{srcs[key].domain}/{i}",
                        source_id=srcs[key].id, title=title, content=body, hash=str(i).ljust(64, "0"),
                        language=srcs[key].language, word_count=len(body.split()),
                        created_at=now - timedelta(days=days), published_at=now - timedelta(days=days))
            s.add(a)
            s.flush()
            return a

        wire = art("wire", 1, "Alps glacier melt doubled", "(Reuters) " + _WIRE_BODY, 5)
        # A near-identical copy of the wire text on another outlet.
        copy = art("echo1", 2, "Alps glacier melt doubled, study", "(Reuters) " + _WIRE_BODY, 4)
        # A rewrite that attributes the same wire in its own words.
        rewrite = art("echo2", 3, "Study: Alpine ice loss twice as fast",
                      "Melt of Alpine glaciers doubled over two decades, according to Reuters. "
                      "Scientists counted the ice lost from 180 glaciers.", 4)
        # A report citing the same origin page as the wire.
        citer = art("cite", 4, "Glacier melt doubled in the Alps",
                    "A new study says the melt of glaciers in the Alps doubled. The paper "
                    "looked at satellite images.", 3)
        # Two reports with nothing linking them to the wire or to each other.
        indep = art("indep", 5, "Zurich glaciologists on the ice",
                    "Glaciologists in Zurich say the melt of Alpine ice has doubled in their "
                    "own measurements of twelve glaciers.", 1)
        stat = art("stats", 6, "Glacier inventory 2020",
                   "The glacier inventory records the melt of Alpine glaciers since 2000.", 30)
        art("other", 7, "Stock markets close higher", "Shares rose in Tokyo on Friday.", 2)
        origin = "https://journal.example/glacier-study"
        for a in (wire, citer):
            s.add(ArticleLink(article_id=a.id, url=origin, normalized_url=origin))
        s.commit()
        return {"wire": wire.id, "copy": copy.id, "rewrite": rewrite.id, "citer": citer.id,
                "indep": indep.id, "stat": stat.id}


@pytest.fixture()
def corpus(tmp_path):
    from src.database.fts import ensure_fts
    from src.database.fts_norm import install_pool_hook

    install_pool_hook()
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    TS = sessionmaker(bind=engine, future=True)
    ids = _seed(TS)
    return TS, ids


@pytest.fixture()
def client(corpus):
    TS, ids = corpus

    def _db():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c, ids
    app.dependency_overrides.clear()


CLAIM = "Glacier melt in the Alps has doubled since 2000"


# --------------------------------------------------------------------------- #
#  The pure parts
# --------------------------------------------------------------------------- #


def test_the_derived_query_is_the_claims_content_words_quoted_and_ORed():
    q, terms = cw.derive_query(CLAIM)
    assert terms == ["Glacier", "melt", "Alps", "doubled", "2000"]
    assert q == '"Glacier" OR "melt" OR "Alps" OR "doubled" OR "2000"'


def test_an_operator_word_in_a_claim_is_quoted_never_an_operator():
    q, terms = cw.derive_query("Vaccines do NOT cause autism")
    # NOT is a grammar word in English and drops; if it survived it would be quoted.
    assert "NOT" not in terms
    assert all(part.startswith('"') for part in q.split(" OR "))


def test_a_claim_of_only_grammar_words_derives_nothing():
    assert cw.derive_query("it is what it is") == ("", [])


def test_the_said_sentence_is_the_one_carrying_most_words():
    text = "Markets rose. The melt of glaciers in the Alps doubled. Nothing else."
    sent, n = cw.best_sentence(text, ["melt", "Alps", "doubled"])
    assert sent == "The melt of glaciers in the Alps doubled."
    assert n == 3
    assert cw.best_sentence("Markets rose.", ["melt"]) == (None, 0)


def test_group_paths_three_echoes_of_one_wire_are_one_path_and_say_why():
    arts = [
        {"id": 1, "source_id": 1, "source": "A", "wire": "Reuters", "published_at": "2026-01-01"},
        {"id": 2, "source_id": 2, "source": "B", "wire": "Reuters", "published_at": "2026-01-02"},
        {"id": 3, "source_id": 3, "source": "C", "wire": "Reuters", "published_at": "2026-01-03"},
        {"id": 4, "source_id": 4, "source": "D", "wire": None, "published_at": "2026-01-04"},
    ]
    out = cw.group_paths(arts, {}, [])
    assert out["n_paths"] == 2
    top = out["paths"][0]
    assert top["article_ids"] == [1, 2, 3]
    assert [j["kind"] for j in top["joins"]] == ["same_wire"]
    assert top["joins"][0]["detail"] == "Reuters"
    lone = out["paths"][1]
    assert lone["unjoined"] is True and lone["joins"] == []


# --------------------------------------------------------------------------- #
#  The seeded wire-echo fixture, end to end
# --------------------------------------------------------------------------- #


def test_the_wire_echo_fixture_groups_into_one_path_with_every_join_named(corpus):
    TS, ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, CLAIM)
    related = {a["id"] for a in ws["related"]["articles"]}
    # ① the six glacier articles are related; the market report is not.
    assert related == {ids[k] for k in ("wire", "copy", "rewrite", "citer", "indep", "stat")}
    assert ws["query"]["derived"] is True
    assert ws["related"]["ordering"] == "relevance"

    ind = ws["independence"]
    echo = {ids[k] for k in ("wire", "copy", "rewrite", "citer")}
    paths = {frozenset(p["article_ids"]): p for p in ind["paths"]}
    assert frozenset(echo) in paths, ind["paths"]
    p = paths[frozenset(echo)]
    kinds = {j["kind"] for j in p["joins"]}
    # The copy by near-identical text, the rewrite by its wire attribution, the citer by
    # the shared origin page: three different joins, one path.
    assert {"near_identical", "same_wire", "shared_link"} <= kinds
    assert any(j["kind"] == "shared_link" and j["detail"] == "https://journal.example/glacier-study"
               for j in p["joins"])
    assert p["n_sources"] == 4 and p["unjoined"] is False
    # The two unconnected reports are paths of one, called unjoined -- never independent.
    assert ind["n_paths"] == 3 and ind["n_unjoined"] == 2 and ind["n_joined_paths"] == 1


def test_the_timeline_is_publication_order_with_the_first_seen_marked(corpus):
    TS, ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, CLAIM)
    dates = [r["published_at"] for r in ws["timeline"]]
    assert dates == sorted(dates)
    assert ws["timeline"][0]["id"] == ids["stat"] and ws["timeline"][0]["first_in_corpus"]
    assert sum(r["first_in_corpus"] for r in ws["timeline"]) == 1
    wire_row = next(r for r in ws["timeline"] if r["id"] == ids["wire"])
    assert wire_row["wire"] == "Reuters"
    assert "doubled" in (wire_row["said"] or "")
    assert all(r["path"] for r in ws["timeline"])


def test_whats_missing_names_the_silent_countries_languages_and_types(corpus):
    TS, _ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, CLAIM)
    miss = ws["missing"]
    assert [i["key"] for i in miss["countries"]["items"]] == ["jp"]
    assert [i["key"] for i in miss["languages"]["items"]] == ["ja"]
    assert miss["source_types"]["total"] == 0  # news and statistics both speak here
    codes = {d["code"] for d in miss["would_discriminate"]}
    assert "figure_source" in codes
    assert "no_primary_record" not in codes  # the statistics office is in the trail


def test_a_single_source_trail_makes_no_independence_claim(corpus):
    TS, ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, CLAIM, query='"Tokyo"')
    assert [a["id"] for a in ws["related"]["articles"]] != []
    assert ws["independence"]["n_paths"] == 1
    codes = {d["code"] for d in ws["missing"]["would_discriminate"]}
    assert "one_path" in codes
    assert ws["query"]["derived"] is False


def test_a_claim_with_no_related_article_is_the_socratic_empty_state(corpus):
    TS, _ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, "Penguins migrate to the Sahara every winter")
    assert ws["related"]["total"] == 0 and ws["timeline"] == []
    assert ws["independence"]["n_paths"] == 0
    assert [d["code"] for d in ws["missing"]["would_discriminate"]] == ["no_related"]
    # The silent facets are still reported: the whole corpus is silent on it.
    assert ws["missing"]["countries"]["total"] == 7


def test_quarantined_articles_never_enter_the_trail(corpus):
    TS, ids = corpus
    with TS() as s:
        s.get(Article, ids["indep"]).quarantined = True
        s.commit()
        ws = cw.build_workspace(s, CLAIM)
    assert ids["indep"] not in {a["id"] for a in ws["related"]["articles"]}


def _walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, path
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, path)


def test_no_field_is_a_score_a_rating_a_ranking_or_a_grade(corpus):
    TS, _ids = corpus
    with TS() as s:
        ws = cw.build_workspace(s, CLAIM)
    banned = ("score", "rating", "ranking", "grade", "verdict", "credib", "confidence", "true")
    for key, where in _walk_keys(ws):
        # Whole-word check on snake_case parts: "degraded" must not trip "grade".
        parts = key.lower().split("_")
        assert not any(p.startswith(b) for p in parts for b in banned), (key, where)


# --------------------------------------------------------------------------- #
#  The route
# --------------------------------------------------------------------------- #


def test_the_route_answers_and_refuses_what_it_cannot_run(client):
    c, ids = client
    r = c.get("/api/claims/workspace", params={"claim": CLAIM})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["steps_built"] == [1, 2, 3, 5] and body["steps_not_built"] == [4, 6]
    assert c.get("/api/claims/workspace", params={"claim": ""}).status_code == 422
    assert c.get("/api/claims/workspace", params={"claim": "x" * 1001}).status_code == 422
    bad = c.get("/api/claims/workspace", params={"claim": CLAIM, "query": "(glacier OR"})
    assert bad.status_code == 400, bad.text
    lim = c.get("/api/claims/workspace", params={"claim": CLAIM, "limit": 2}).json()
    assert lim["related"]["shown"] == 2 and lim["related"]["total"] == 6


# --------------------------------------------------------------------------- #
#  The UI: its renderers in node, and its wiring pinned at the source
# --------------------------------------------------------------------------- #

_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_the_renderers_hold_their_refusals_in_node():
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    res = subprocess.run(["node", str(_ROOT / "tests" / "claim_workspace_node_test.js")],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr


def test_the_workspace_opens_by_an_explicit_command_never_by_enter():
    """Q608 = a: Enter in the omnibar opens the analysis window. The workspace's row is
    spliced in at index 1, AFTER the Analysis row is unshifted to index 0."""
    shell = (_ROOT / "src/static/app-shell.js").read_text(encoding="utf-8")
    analysis = shell.index('label: ooLabelText(t("Analysis")')
    claim = shell.index('live.splice(1, 0, {grp: t("Search"), label: ooLabelText(t("Check as a claim")')
    assert analysis < claim
    assert '{id:"claim",    label:"Claim workspace"' in shell
    assert "claim: () => _claimWire()" in shell


def test_the_tab_is_wired_off_the_sidebar_and_cached_offline():
    html = (_ROOT / "src/static/index.html").read_text(encoding="utf-8")
    assert 'id="tab-claim"' in html and 'id="claim-from-search"' in html
    assert 'data-tab="claim"' not in html, "the workspace is kept off the sidebar, like Analysis"
    assert html.index('src="/static/app-claim.js"') < html.index('src="/static/app-boot.js"')
    sw = (_ROOT / "src/static/sw.js").read_text(encoding="utf-8")
    assert '"/static/app-claim.js"' in sw
    js = (_ROOT / "src/static/app-claim.js").read_text(encoding="utf-8")
    assert "onclick" not in js.lower(), "no inline handlers (the CSP has no 'unsafe-inline')"


def test_every_string_the_workspace_draws_is_keyed_in_all_twelve_locales():
    """The repo's i18n gates skip a t() literal that carries a {placeholder} and a tf() frame
    called through a parameter, and two of this view's sentences went through that gap
    (the Chromium walk found them in English on the Arabic page). So this file checks its
    own literals directly."""
    import json
    import re

    js = (_ROOT / "src/static/app-claim.js").read_text(encoding="utf-8")
    lits = {m.replace('\\"', '"') for m in re.findall(r'\btf?\("((?:[^"\\]|\\.)*)"', js)}
    assert len(lits) > 40
    for code in ("en", "fr", "es", "de", "pt", "ru", "ar", "hi", "bn", "zh", "ja", "id"):
        loc = json.loads((_ROOT / f"src/static/locales/{code}.json").read_text(encoding="utf-8"))
        missing = sorted(x for x in lits if x not in loc)
        assert not missing, (code, missing)

"""The keyword surfaces the 2026-09-27 re-walk still found bare, untranslated or wrong.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

* M-3 / M-5 / M-15: the Explore mind map and word cloud drew every keyword as its bare
  stored word (no "in Russian"), and the i18n walker translated a keyword that equals an
  interface key ("errors" drawn as "erreurs"). The graph is now fetched with the reader's
  language and its nodes carry the label fields every keyword list uses; the bulletin
  review's stories and the document's stories and country lists name each term's
  language too.
* M-10: the Explore hint's method and caveat, the bounded-view disclosure and the VADER
  framing caveat were English in every locale. They are keys (and a frame) now, x12.
* M-11: the landscape chip's hover was an English template with a raw number.
* M-8 / M-16: the Top list clipped the language tag out of sight, and the mind-map level
  toggle clipped "Keywords" to "Keywo".
* M-7: the Diagnostics job lines are re-read whenever the section opens.
* M-2 / M-9: the boot locale fires the same repaint event a switch fires.

The behaviour is driven by four node suites against the shipped JavaScript; this file
runs them and pins the server halves.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from tests.js_source_helper import function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

_NODE_SUITES = [
    "mindmap_label_layout_node_test.js",
    "keyword_kind_story_terms_node_test.js",
    "i18n_boot_langchange_node_test.js",
    "diagnostics_job_watch_node_test.js",
    "patterns_gate_colon_node_test.js",
]


@pytest.mark.parametrize("suite", _NODE_SUITES)
def test_node_suite(suite: str) -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / suite)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  The graph carries the label fields (M-3/M-5) and keyed wording (M-10)
# --------------------------------------------------------------------------- #
def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


_HUB = "alphahub"
_RELATIVES = {"избирателей": "ru", "голосов": "ru", "votaciones": "es", "ballots": "en"}


def _seed(s) -> None:
    src = Source(name="S", domain="graph.test", country="fr")
    s.add(src)
    s.flush()
    for aid in range(24):
        s.add(
            Article(
                url=f"https://graph.test/{aid}",
                canonical_url=f"https://graph.test/{aid}",
                source_id=src.id,
                title=f"t{aid}",
                content="body",
                hash=f"{aid:064d}",
                language="en",
                published_at=datetime(2026, 9, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
    s.flush()
    terms = {_HUB: "en", **_RELATIVES, "fillerone": "en", "fillertwo": "en"}
    ids = {}
    for term, lang in terms.items():
        k = Keyword(term=term, normalized_term=term, language=lang, is_entity=False)
        s.add(k)
        s.flush()
        ids[term] = k.id
    placed: dict[str, set[int]] = {t: set() for t in terms}
    for aid in range(12):  # the hub and its relatives, together
        for t in (_HUB, *_RELATIVES):
            placed[t].add(aid)
    for aid in range(12, 24):  # unrelated vocabulary, so the association is not trivial
        for t in ("fillerone", "fillertwo"):
            placed[t].add(aid)
    for t, aids in placed.items():
        for aid in aids:
            s.add(
                KeywordMention(
                    keyword_id=ids[t], article_id=aid + 1, count=1,
                    observed_on=date(2026, 9, 1), language=terms[t],
                )
            )
        s.query(Keyword).filter_by(id=ids[t]).update(
            {Keyword.article_count: len(aids), Keyword.mention_count: len(aids)}
        )
    s.commit()


def test_graph_nodes_carry_the_keyword_label_in_the_readers_language() -> None:
    s = _session()
    _seed(s)
    g = q.layered_graph(s, level="keyword", term=_HUB, hops=2, target_lang="fr")
    by_id = {n["id"]: n for n in g["nodes"]}
    assert set(_RELATIVES) <= set(by_id), sorted(by_id)
    ru = by_id["избирателей"]
    assert ru["translation_source_lang"] == "ru", ru
    assert ru["translation_tier"] in {"untranslated", "verified", "tentative"}, ru
    # The id and label stay the stored word: edges and the click key on them.
    assert ru["label"] == "избирателей"
    assert by_id["votaciones"]["translation_source_lang"] == "es"
    # The keyed halves of the wording (M-10).
    assert g["caveat_i18n"] == "Association is not causation; PMI on small samples is noisy."
    assert g["method"] == "PMI/co-occurrence association, two hops (relatives, and their relatives)"


def test_graph_without_a_reader_language_is_unchanged() -> None:
    s = _session()
    _seed(s)
    g = q.layered_graph(s, level="keyword", term=_HUB, hops=2)
    assert g["nodes"], g
    assert not any("translation_tier" in n for n in g["nodes"]), g["nodes"]


def test_a_bounded_graph_sends_its_disclosure_as_a_frame() -> None:
    s = _session()
    _seed(s)
    g = q.layered_graph(s, level="keyword", term=_HUB, hops=2, limit_nodes=3, target_lang="fr")
    assert g.get("bounded") is True, g
    assert g["disclosure_i18n"] == q._GRAPH_BOUNDED_FRAME
    assert g["disclosure"] == q._GRAPH_BOUNDED_FRAME.format(**g["disclosure_vars"])
    # The English caveat still reads whole for any client that shows only it.
    assert g["caveat"].endswith(g["disclosure"])


def test_the_graph_endpoint_asks_in_the_readers_language_and_caches_per_language() -> None:
    import ast

    py = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(py))
              if isinstance(n, ast.FunctionDef) and n.name == "insights_graph")
    body = ast.get_source_segment(py, fn) or ""
    assert "target_lang=_gtl" in body, "the graph must be built for the reader's language"
    assert "tl=_gtl" in body, "a graph cached for one language must not answer another"


# --------------------------------------------------------------------------- #
#  The bulletin names each story term's language (M-3/M-5)
# --------------------------------------------------------------------------- #
def test_stories_carry_each_shared_terms_language() -> None:
    from src.bulletin.period import resolve_period
    from src.bulletin.stories import build_stories

    s = _session()
    src = Source(name="One", domain="one.test")
    s.add(src)
    s.flush()
    words = {"голосов": "ru", "избирателей": "ru", "явку": "ru", "подсчет": "ru"}
    kws = {}
    for w, lang in words.items():
        k = Keyword(term=w, normalized_term=w, language=lang)
        s.add(k)
        s.flush()
        kws[w] = k.id
    for i in range(2):
        a = Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=src.id,
                    title="t", content="b", hash=f"{i:064d}",
                    published_at=datetime(2026, 7, 27, 12), quarantined=False)
        s.add(a)
        s.flush()
        for w in words:
            s.add(KeywordMention(keyword_id=kws[w], article_id=a.id, count=1,
                                 observed_on=date(2026, 7, 27), source_id=src.id))
    s.commit()
    story = build_stories(s, resolve_period("weekly", end=date(2026, 8, 1)))["stories"][0]
    assert sorted(story["shared_terms"]) == sorted(words)  # unchanged for older readers
    rows = story["shared_term_rows"]
    assert [r["term"] for r in rows] == story["shared_terms"], "the two lists must agree in order"
    assert {r["language"] for r in rows} == {"ru"}
    assert all(r["normalized"] == r["term"] for r in rows)


def _story_edition(story: dict) -> dict:
    from tests.test_bulletin_render import _EDITION

    rising = {
        "section": "rising_concepts",
        "window": {"days": 7, "matches_period": True},
        "baseline_days": 30,
        "terms": [{"term": "выборы", "normalized": "выборы", "language": "ru", "recent": 40,
                   "prior": 30, "expected": 7.0, "growth": 5.7, "growth_is_ratio": True}],
    }
    coverage = {
        "section": "country_coverage",
        "window": {"days": 7, "matches_period": True},
        "countries": [{
            "country": "ru", "name": "Russia", "reading": "Coverage reading.",
            "local": {"articles": 2, "terms": [
                {"term": "избирателей", "normalized": "избирателей", "language": "ru",
                 "mentions": 4, "articles": 2}]},
            "international": {"articles": 1, "terms": [
                {"term": "élection", "normalized": "élection", "language": "fr",
                 "mentions": 2, "articles": 1}]},
        }],
    }
    return dict(_EDITION, sections=[rising, coverage],
                stories={"stories": [story], "caveat": "A lexical grouping."})


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_document_names_a_story_terms_language(fmt: str) -> None:
    from src.bulletin.render import render

    story = {"article_ids": [1, 2], "articles": 2, "distinct_sources": 1, "single_source": True,
             "shared_terms": ["голосов", "избирателей"],
             "shared_term_rows": [
                 {"term": "голосов", "normalized": "голосов", "language": "ru"},
                 {"term": "избирателей", "normalized": "избирателей", "language": "ru"}]}
    fr = render(_story_edition(story), fmt, lang="fr")
    assert "голосов (en rus), избирателей (en rus)" in fr, fr
    # A record from before the rows existed: the edition's own sections name the language.
    old = dict(story)
    old.pop("shared_term_rows")
    old["shared_terms"] = ["выборы"]
    assert "выборы (en rus)" in render(_story_edition(old), fmt, lang="fr")


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_country_coverage_lists_name_each_terms_language(fmt: str) -> None:
    from src.bulletin.render import render

    story = {"article_ids": [1, 2], "articles": 2, "distinct_sources": 1, "shared_terms": ["x"]}
    fr = render(_story_edition(story), fmt, lang="fr")
    assert "избирателей (en rus) 4" in fr, fr
    # Already in the document's language: nothing added.
    assert "élection (en fra)" not in fr and "élection 2" in fr


def test_the_review_sends_story_terms_as_rows() -> None:
    from src.bulletin.review import review_view, story_term_rows

    rows = [{"term": "голосов", "normalized": "голосов", "language": "ru"}]
    ed = {"sections": [{"terms": [{"term": "выборы", "normalized": "выборы", "language": "ru"}]}],
          "stories": {"stories": [
              {"article_ids": [1], "shared_terms": ["голосов"], "shared_term_rows": rows},
              {"article_ids": [2], "shared_terms": ["выборы", "unknown"]}]}}
    view = review_view(ed)
    assert view["stories"][0]["shared_term_rows"] == rows
    # The older record: looked up in the edition's own sections, else no language at all.
    assert view["stories"][1]["shared_term_rows"] == [
        {"term": "выборы", "normalized": "выборы", "language": "ru"},
        {"term": "unknown", "normalized": "unknown", "language": None},
    ]
    assert story_term_rows({}) == []


# --------------------------------------------------------------------------- #
#  The client halves the node suites cannot reach
# --------------------------------------------------------------------------- #
def test_the_mind_map_fetches_in_the_readers_language_and_repaints_on_a_switch() -> None:
    corpus = read_static("app-corpus.js")
    fetches = re.findall(r"api\(`/api/insights/graph\?[^\n]*", corpus)
    assert len(fetches) >= 3, fetches
    for f in fetches:
        assert "tgtLangParam()" in f, "a graph fetched without the reader's language: " + f
    body = function_body(corpus, "renderGraph")
    assert "kwLabelParts(" in body, "the map must draw THE keyword label"
    assert re.search(r'<g class="mm-node"[^`]*data-i18n-dyn', body), (
        "a keyword node without data-i18n-dyn lets the walker translate data (M-15)"
    )
    assert "esc(n.label)}</text>" not in body, "the bare stored word is back"
    assert '"ins-mindmap", "mmReload"' in function_body(corpus, "ooKwRepaintOnLangChange")


def test_the_mind_map_hint_is_keyed_and_opted_out_of_the_walker() -> None:
    body = function_body(read_static("app-corpus.js"), "renderGraph")
    assert 't("Branches grow outward from the centre; each leaf hangs off its strongest relative.")' in body
    assert 't("Cloud view: weight-ordered, no links.")' in body
    assert "g.caveat_i18n" in body and "g.disclosure_i18n" in body
    assert '<div class="hint" data-i18n-dyn>' in body
    assert 'unit: t8("mentions")' in function_body(read_static("app-corpus.js"), "exploreTerm")


def test_the_landscape_chip_hover_is_keyed_frames() -> None:
    body = function_body(read_static("app-insights.js"), "loadLandscape")
    assert '_kwTf("{n} mentions — click to zoom in", {n: fmtNum(f.mentions)})' in body
    assert '_kwTf("family of {n}: {members}"' in body
    assert "mentions — click to zoom in\"" not in body.replace('_kwTf("{n} mentions — click to zoom in"', "")


def test_the_framing_table_keeps_data_out_of_the_walker() -> None:
    body = function_body(read_static("app-ai-tools.js"), "loadFraming")
    assert "<td data-i18n-dyn>${esc(f.source)}</td>" in body
    assert re.search(r"<td[^>]*data-i18n-dyn>\$\{\(f\.top_terms", body)
    assert '<div class="hint">${esc(d.caveat||"")}</div>' in body, (
        "the caveat must stay a walker-reachable text node: it is translated as a key"
    )


def test_opening_diagnostics_reads_the_job_lines() -> None:
    boot = read_static("app-boot.js")
    assert 'details.adv-sec[data-adv="diagnostics"]' in boot
    assert "watchDiagnosticsJobs()" in boot
    diag = read_static("app-diagnostics.js")
    for fn in ("_pollReindexJob", "_pollFoldJob", "_pollSearchReindex"):
        body = function_body(diag, fn)
        assert "_watchJobLine(" in body, f"{fn} is a second writer again"
        # The button waits for the job to STOP RUNNING, not for the watch to end: the watch
        # follows a paused job while the section is open, and a button held disabled through
        # a pause is a paused run that cannot be continued from Diagnostics.
        assert body.rstrip().rstrip("}").rstrip().endswith(".settled;"), (
            f"{fn} makes its button wait for the whole watch"
        )


def test_the_top_list_label_wraps_its_tag_instead_of_clipping_it() -> None:
    css = read_static("app.css")
    rule = re.search(r"\.tb-label\s*\{([^}]*)\}", css).group(1)
    assert "flex-wrap:wrap" in rule.replace(" ", ""), rule
    assert "overflow:hidden" not in rule.replace(" ", ""), "the label box clips its tag again (M-8)"
    assert re.search(r"\.tb-label \.kw-term\s*\{[^}]*text-overflow:ellipsis", css)
    assert re.search(r"\.tb-label \.kw-tag\s*\{[^}]*white-space:normal", css)


def test_a_long_language_tag_never_pushes_the_phone_page_sideways() -> None:
    """The review of M-8: the same nowrap tag scrolled a 375 px page sideways elsewhere --
    the Explore landscape chips (de 35 px, ru 96 px), the Trends rows (fr 15 px, ru 108 px)
    and the framing table's last column beside them (de/ru)."""
    css = read_static("app.css")
    chip = re.search(r"\.ls-chip\s*\{([^}]*max-width[^}]*)\}", css)
    assert chip and "white-space:normal" in chip.group(1).replace(" ", ""), "the chip keeps its tag on one line"
    assert re.search(r"\.ls-chip \.kw-tag, \.kw-row \.kw-tag\s*\{[^}]*white-space:normal", css)
    assert re.search(r"\.kw-row\s*\{[^}]*flex-wrap:wrap", css)
    corpus = read_static("app-corpus.js")
    assert 'class="kw-row"' in function_body(corpus, "termListHtml")
    assert 'class="kw-row"' in function_body(corpus, "loadTrendWindows")
    framing = function_body(read_static("app-ai-tools.js"), "loadFraming")
    assert '<div style="overflow-x:auto"><table>' in framing, "the framing table widens the page again"


def test_the_explore_level_toggle_never_shrinks_below_its_label() -> None:
    css = read_static("app.css")
    assert re.search(r"\.row > \.seg-toggle button\s*\{[^}]*min-width:max-content", css), (
        "'Keywords' clipped to 'Keywo' at 1440 px (M-16)"
    )
    assert re.search(r"\.row > \.seg-toggle\s*\{[^}]*flex-wrap:wrap", css)


_NEW_KEYS = [
    "PMI/co-occurrence association, two hops (relatives, and their relatives)",
    "Association is not causation; PMI on small samples is noisy.",
    "shared-article overlap between keyword FAMILIES (top members each)",
    "Families group surface forms of one entity; overlap counts articles, not causation.",
    "shared-article overlap between SUPER-GROUPS (curated groups of families); top "
    "unassigned families shown for context",
    "Super-groups are the user's own curation; overlap counts articles, not causation.",
    "{n} mentions — click to zoom in",
    "family of {n}: {members}",
    "Person",
    "Organisation",
    "Place",
    "Entity",
]


def test_every_new_string_is_keyed_in_all_twelve_locales() -> None:
    from src.awareness.framing import _CAVEAT

    keys = [*_NEW_KEYS, q._GRAPH_BOUNDED_FRAME, _CAVEAT]
    locales = sorted(_LOCALES.glob("*.json"))
    assert len(locales) == 12
    bad: list[str] = []
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in keys:
            v = data.get(k)
            if not v:
                bad.append(f"{path.stem}: missing {k[:50]}")
            elif set(re.findall(r"\{\w+\}", v)) != set(re.findall(r"\{\w+\}", k)):
                bad.append(f"{path.stem}: placeholders differ in {k[:50]}")
            elif path.stem != "en" and k == _CAVEAT and v == k:
                bad.append(f"{path.stem}: the VADER caveat is untranslated")
    assert not bad, bad
    # The graph's server wording IS the key, so the two cannot drift apart.
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    for k in _NEW_KEYS[:6]:
        assert k.split(" (")[0] in src, k
        assert en[k] == k

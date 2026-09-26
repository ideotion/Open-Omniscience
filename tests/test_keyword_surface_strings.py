"""M14 (delegated click-through 2026-09-26): English on the keyword surfaces in fr/ar/zh.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The walk read, on a French page: "Resolved to … term · 109 mentions in 55 articles", the
Combine block's hint and its three operators, the analysis Keywords caveat, the keyword-
stats bubble's caveat, the super-group lines ("N members · N mentions", "Dominated by"),
the Bulletin list ("COVERS THROUGH", "Review", "weekly", "Draft built."), the fold job's
label in both task managers, and three Home card titles. None of it was caught by the
i18n ratchets, which were green throughout: those count keys and ``t("…")`` literals, and
these strings were template text, server sentences and data printed raw.

So each is pinned on BOTH halves -- the call site goes through ``t()``/``tf()``, AND the
key exists in all twelve locale files -- because either half alone is silent. The server
sentences the client now translates are read out of the server source, so a reworded
caveat fails here instead of quietly falling back to English.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"


def _tables() -> dict[str, dict]:
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}


_T = _tables()


def _keyed(key: str) -> None:
    for lang, table in _T.items():
        assert key in table, f"{lang}.json has no entry for {key!r}"


# --- the client: each literal goes through the translator, and is keyed ---------------- #

_CLIENT = [
    ("exploreTerm", 't8("Resolved to")', "Resolved to"),
    ("exploreTerm", 'tf8("{n} mentions in {articles} articles"', "{n} mentions in {articles} articles"),
    ("anConjunctionHtml",
     't("set algebra over N keywords. The set expression is the corpus label; counts only, never a score.")',
     "set algebra over N keywords. The set expression is the corpus label; counts only, never a score."),
    ("anConjunctionHtml", 't("∩ All")', "∩ All"),
    ("anConjunctionHtml", 't("∪ Any")', "∪ Any"),
    ("anConjunctionHtml", 't("∖ First-only")', "∖ First-only"),
    ("anCombineHtml", 'tf("Open {n} article(s) as a corpus →"', "Open {n} article(s) as a corpus →"),
    ("anCombineHtml", 'tf("{n} article(s)"', "{n} article(s)"),
    ("anCombineHtml", '"No resolvable keyword given."', "No resolvable keyword given."),
    ("sgCard", 'tf("Dominated by “{member}” ({share}% of this total)"',
     "Dominated by “{member}” ({share}% of this total)"),
    ("sgCard", '"{n} members · {m} mentions"', "{n} members · {m} mentions"),
    ("sgCard", '"{n} member · {m} mentions"', "{n} member · {m} mentions"),
    ("sgCard", 'tf("+{n} with no mentions yet"', "+{n} with no mentions yet"),
]


@pytest.mark.parametrize(("fn", "call", "key"), _CLIENT, ids=[f"{f}:{k[:24]}" for f, _, k in _CLIENT])
def test_the_keyword_surface_string_is_translated_and_keyed(fn: str, call: str, key: str) -> None:
    body = strip_comments(function_body(app_js(), fn))
    assert call in body, f"{fn} does not route {key!r} through the translator"
    _keyed(key)


def test_the_old_bare_english_is_gone() -> None:
    app = app_js()
    explore = strip_comments(function_body(app, "exploreTerm"))
    assert "Resolved to <strong>" not in explore and " mentions in ${tr.articles} articles" not in explore
    conj = strip_comments(function_body(app, "anConjunctionHtml"))
    assert ">∩ All</button>" not in conj and "set algebra over N keywords. `" not in conj
    sg = strip_comments(function_body(app, "sgCard"))
    assert "Dominated by <b>" not in sg and 'member${g.count === 1 ? "" : "s"}' not in sg


def test_the_bulletin_list_is_keyed_and_its_cadence_is_a_label() -> None:
    """The list printed the cadence CODE ("weekly"); it now shows the Period picker's own
    label, through the same keys."""
    agenda = strip_comments(read_static("app-agenda.js"))
    assert "_bulT(_BUL_CADENCE_LABEL[r.cadence] || r.cadence)" in agenda
    labels = dict(re.findall(r'(\w+): "(\w+)"', agenda.split("const _BUL_CADENCE_LABEL = {", 1)[1].split("}", 1)[0]))
    assert set(labels) == {"daily", "weekly", "monthly", "trimester", "semester", "yearly"}
    for label in list(labels.values()) + ["Covers through", "Review", "Draft built."]:
        _keyed(label)


# --- the server sentences the client translates must BE the keys ------------------------ #

def _module(rel: str) -> ast.Module:
    return ast.parse((_ROOT / rel).read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no function {name}")


def test_the_keyword_stats_caveat_is_a_key() -> None:
    """app-boot.js now renders ``t(d.caveat)``; a reworded caveat would silently fall back."""
    fn = _func(_module("src/analytics/queries.py"), "keyword_stats")
    # The RESOLVED payload's caveat: an unresolved term renders its own keyed "not in your
    # corpus" line in the bubble and never shows a caveat.
    def resolved(n: ast.Dict) -> bool:
        for k, v in zip(n.keys, n.values, strict=True):
            if isinstance(k, ast.Constant) and k.value == "resolved":
                return not (isinstance(v, ast.Constant) and v.value is None)
        return False

    caveats = [
        v.value for n in ast.walk(fn) if isinstance(n, ast.Dict) and resolved(n)
        for k, v in zip(n.keys, n.values, strict=True)
        if isinstance(k, ast.Constant) and k.value == "caveat" and isinstance(v, ast.Constant)
    ]
    assert caveats, "keyword_stats no longer returns a fixed caveat"
    for c in caveats:
        _keyed(c)
    boot = strip_comments(read_static("app-boot.js"))
    assert '" · " + t(d.caveat)' in boot


def test_the_combine_caveat_is_a_key() -> None:
    fn = _func(_module("src/analytics/conjunction.py"), "corpus_algebra")
    base = [
        n.value.value for n in ast.walk(fn)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "caveat" for t in n.targets)
        and isinstance(n.value, ast.Constant)
    ]
    assert base, "corpus_algebra's fixed caveat moved"
    for c in base:
        _keyed(c)


def test_the_analysis_keywords_caveat_is_a_frame_the_client_renders() -> None:
    src = (_ROOT / "src/api/insights.py").read_text(encoding="utf-8")
    m = re.search(r'res\["caveat_i18n"\] = \(\s*"([^"]+)"\s*\)', src)
    assert m, "corpus-keywords sends no caveat frame"
    frame = m.group(1)
    assert "{n}" in frame and 'res["caveat_vars"] = {"n": len(ids)}' in src
    # The frame IS the English caveat with the count as a slot, so the two cannot drift.
    assert frame.replace("{n}", "{len(ids)}") in src.replace('"\n            "', "")
    _keyed(frame)
    chips = strip_comments(function_body(app_js(), "anRenderKwChips"))
    assert "tfK(d.caveat_i18n, d.caveat_vars || {})" in chips


def test_the_fold_jobs_label_and_details_are_keys() -> None:
    """Both task managers print ``t(j.label)`` and ``t(r.detail)`` (M5); the fold's own
    strings must be keys, including the "paused for an import" form the server builds."""
    tree = _module("src/api/jobs.py")
    fn = _func(tree, "_keyword_fold_jobs")
    labels = [
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value in ("Setting each keyword's language from its mentions",
                        "Folding keyword forms into their base form")
    ]
    assert len(set(labels)) == 2, "the fold job's labels moved"
    for label in set(labels):
        _keyed(label)
        _keyed("Paused for an import — " + label[0].lower() + label[1:])
    details = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("keyword fold ")
    }
    assert len(details) == 3, details
    for d in details:
        _keyed(d)


# --- the Home card titles ----------------------------------------------------------------- #

_TITLES = {
    "lonely_signal": "Single-source: “{title}”",
    "recycled_claim": "Resurfaced after {days} days: {title}",
    "story_propagation": "“{term}” spread across {n} sources",
}


def test_the_card_titles_the_walk_read_in_english_are_templates() -> None:
    src = (_ROOT / "src/briefing/producers.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Card":
            kw = {k.arg: k.value for k in n.keywords}
            typ = kw.get("type")
            tmpl = kw.get("title_i18n")
            if isinstance(typ, ast.Constant) and isinstance(tmpl, ast.Constant):
                found[typ.value] = tmpl.value
                names = {k.value for k in kw["title_vars"].keys}  # type: ignore[attr-defined]
                assert names == set(re.findall(r"\{(\w+)\}", tmpl.value)), (typ.value, names)
    for typ, tmpl in _TITLES.items():
        assert found.get(typ) == tmpl, f"{typ} carries no translatable title"
        _keyed(tmpl)


# --- the French grammar slip -------------------------------------------------------------- #

def test_the_thin_baseline_sentence_puts_no_article_before_the_window() -> None:
    """``{window}`` is "période précédente" OR "30 jours précédents": a plural article in
    front of it read "sur les période précédente". The window now sits in parentheses in
    the three languages whose frame hard-coded an article or a bare preposition."""
    key = "{n} mentions, against {prior} in the {window} — too thin a baseline to divide by"
    for lang in ("fr", "es", "pt"):
        assert "({window})" in _T[lang][key], f"{lang}: {_T[lang][key]}"
    assert "sur les {window}" not in _T["fr"][key]


# --- M7: the trend's "Resolved to …" label carries its tier ------------------------------ #

def test_the_trend_resolved_keyword_walks_the_translation_ladder() -> None:
    """Explore's header draws ``kwLabelHtml(r)`` on the trend's ``resolved`` keyword, so the
    endpoint must hand it the same tier fields every other keyword row carries -- and the
    keyword's language, without which a foreign word cannot be told apart from a native
    one. Without ``target_lang`` the payload is unchanged."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.insights import insights_trend
    from src.database.models import Base, Source
    from tests.test_exact_term_resolution import _COLLIDING_TEXT, _mk

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    for i, when in enumerate(["2024-03-01", "2024-03-02"]):
        _mk(s, f"tr{i}", _COLLIDING_TEXT, when)
    kw = {"bucket": "week", "country": None, "expand": False, "ui_lang": None, "sense": None,
          "literal_cap": True, "db": s}
    fr = insights_trend("lithium", target_lang="fr", **kw)["resolved"]
    assert fr["language"] == "en"
    assert fr["translation_tier"] == "untranslated"
    assert fr["translation_source_lang"] == "en"
    plain = insights_trend("lithium", target_lang=None, **kw)["resolved"]
    assert plain["language"] == "en" and "translation_tier" not in plain
    s.close()

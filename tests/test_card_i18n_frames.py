"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A Lead reads in the UI language, not only its title (click-through re-walk
2026-09-27, defects L-1, L-2, N-8 and the producer half of M-6).

Before this, five producers' TITLES had a keyed template and nothing else did: every
summary, method, caveat and ranking line was English prose with its data welded in, so
no locale key could ever match it, and fr/ar/zh readers got English under a translated
chrome. A card now carries keyed FRAMES beside its English fields (``Card.i18n``), the
ranking line carries its own (``order_explain_i18n``), and the English is BUILT from the
frames so the two cannot drift.

What is pinned here, and why each is not a grep:
  * every frame template a producer, recipe or the ranking line can emit is a key in all
    twelve locales with the same placeholders -- scanned from the modules' own AST, so a
    new ``frame("...")`` with no key fails here, not in a browser walk;
  * every method and caveat an analytics module hands a producer frames to a key ×12
    (they are auto-framed from their numbers, which is what makes a tuned threshold
    survive translation);
  * the laundering card of L-1 renders in French/Arabic/Chinese from its frames, end to
    end through the real producer;
  * "1 source candidate await your review" (M-6) is now a whole singular frame.
The Home renderer that consumes the frames is proven in tests/card_frames_node_test.js.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.briefing.card import Card, CardSchemaError, frame, frames_text, numeric_frames

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"
_LANGS = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")
_FRAME_MODULES = ("src/briefing/producers.py", "src/briefing/recipes.py", "src/briefing/leads.py")
_HOLE = re.compile(r"\{(\w+)\}")


def _locale(lang: str) -> dict[str, str]:
    return json.loads((_LOCALES / f"{lang}.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def locales() -> dict[str, dict[str, str]]:
    return {lang: _locale(lang) for lang in _LANGS}


def _tf(template: str, variables: dict, table: dict[str, str]) -> str:
    """The UI's OOI18N.tf, reduced to what these assertions need."""
    out = table.get(template, template)
    return _HOLE.sub(lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0), out)


def _assert_keyed(template: str, locales: dict, where: str) -> None:
    holes = sorted(_HOLE.findall(template))
    for lang, table in locales.items():
        assert template in table, f"{where}: not keyed in {lang}.json: {template!r}"
        assert sorted(_HOLE.findall(table[template])) == holes, (
            f"{where}: {lang} translation changes the placeholders of {template!r}"
        )
    # Arabic and Chinese share no script with English, so an identical value is an
    # untranslated one (the --max-untranslatable gate is the whole-file version).
    for lang in ("ar", "zh"):
        if re.search(r"[A-Za-z]{4,}", _HOLE.sub("", template)):
            assert locales[lang][template] != template, f"{where}: {lang} left English: {template!r}"


# --------------------------------------------------------------------------- #
#  the frame primitives
# --------------------------------------------------------------------------- #
def test_numeric_frames_rebuild_the_english_byte_for_byte():
    text = "Near-duplicate clusters (Jaccard >= 0.6) spanning >= 30 days; up to 1,500 recent."
    frames = numeric_frames(text)
    assert frames == [
        {
            "t": "Near-duplicate clusters (Jaccard >= {v1}) spanning >= {v2} days; up to {v3} recent.",
            "v": {"v1": "0.6", "v2": "30", "v3": "1,500"},
        }
    ]
    assert frames_text(frames) == text
    # A literal brace would read as a hole: that sentence keeps its plain English.
    assert numeric_frames("a {literal} brace") == []
    assert numeric_frames("") == []


def test_frames_text_writes_a_month_day_in_english_and_keeps_an_unfilled_hole():
    fr = frame("{n} articles on {day}.", md=("day",), n=3, day="03-14")
    assert frames_text([fr, frame("Then {missing}.")]) == "3 articles on March 14. Then {missing}."


def test_card_frames_a_plain_method_and_caveat_and_ships_them():
    card = Card(
        type="rising", title="T", summary="S", bucket="watch",
        method="a ratio over 7 days", caveat="Read it and judge.",
    )
    assert card.i18n["method"] == [{"t": "a ratio over {v1} days", "v": {"v1": "7"}}]
    assert card.i18n["caveat"] == [{"t": "Read it and judge.", "v": {}}]
    assert card.to_dict()["i18n"] == card.i18n


@pytest.mark.parametrize(
    "bad",
    [
        {"summary": [{"t": "{n} sources", "v": {}}]},  # a hole with no data
        {"summary": [{"t": "x", "v": {"n": [1, 2]}}]},  # data that is not a scalar
        {"summary": [{"t": "{a}", "v": {"a": "x"}, "tr": ["b"]}]},  # tr names a missing var
        {"trigger": []},  # not a text field
        {"summary": "not a list"},
    ],
)
def test_card_rejects_a_malformed_frame(bad):
    with pytest.raises(CardSchemaError):
        Card(type="rising", title="T", summary="S", bucket="watch", method="m", caveat="c", i18n=bad)


# --------------------------------------------------------------------------- #
#  every template is a key, in every language
# --------------------------------------------------------------------------- #
def _strs(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _strs(node.body) + _strs(node.orelse)
    return []


def _frame_templates() -> dict[str, str]:
    """Every ``frame(<template>, ...)`` the producer modules can emit, from their AST.

    A template held in a ``*_template`` variable (the lineage summary picks one of two)
    is collected from its assignment."""
    found: dict[str, str] = {}
    for rel in _FRAME_MODULES:
        tree = ast.parse((_ROOT / rel).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "frame" and node.args:
                for s in _strs(node.args[0]):
                    found.setdefault(s, f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and "template" in t.id for t in node.targets
            ):
                for s in _strs(node.value):
                    found.setdefault(s, f"{rel}:{node.lineno}")
    return found


def test_every_frame_template_is_keyed_in_all_twelve_locales(locales):
    templates = _frame_templates()
    # A floor, so a scan that silently stops finding frames cannot pass on nothing.
    assert len(templates) >= 100, len(templates)
    for template, where in templates.items():
        _assert_keyed(template, locales, where)


def _inline_method_caveat_texts() -> dict[str, str]:
    """Literal ``method=``/``caveat=`` strings on a ``Card(...)`` -- auto-framed at build."""
    found: dict[str, str] = {}
    for rel in _FRAME_MODULES:
        tree = ast.parse((_ROOT / rel).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Card":
                for kw in node.keywords:
                    if kw.arg in ("method", "caveat"):
                        # (leads.py's self-check builds throwaway cards with method="m")
                        for s in _strs(kw.value):
                            if len(s) > 3:
                                found.setdefault(s, f"{rel}:{node.lineno} {kw.arg}")
    return found


def test_every_inline_method_and_caveat_frames_to_a_key(locales):
    texts = _inline_method_caveat_texts()
    assert len(texts) >= 20, len(texts)
    for text, where in texts.items():
        frames = numeric_frames(text)
        _assert_keyed(frames[0]["t"] if frames else text, locales, where)


@pytest.fixture()
def empty_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def test_every_analytics_method_and_caveat_frames_to_a_key(locales, empty_session):
    """The sentences an analytics finder hands a producer (they reach the card as its
    method or caveat). Read from the finders themselves, over an empty database, so a
    reworded caveat that loses its key fails here."""
    from src.analytics import (
        alerts,
        convergence,
        copypasta,
        disputed_chronology,
        emergence,
        headline_body,
        laundering,
        recycled_claim,
        story_propagation,
        supergroup_rising,
        supply_chain_ripple,
    )
    from src.analytics import concentration as conc
    from src.awareness.emotion import emotion_profile
    from src.awareness.framing import compare_framing
    from src.briefing.catalog import settings_for
    from src.integrity.actors import corpus_actors
    from src.signals.concentration import concentration
    from src.signals.lineage import trace_lineage
    from src.signals.near_dup import near_duplicate_clusters

    s = empty_session
    lf, cf, cc = settings_for("source_laundering"), settings_for("flooded_topic"), settings_for("copypasta")
    prof = emotion_profile(["fear panic"])
    diet = concentration({"a": 5, "b": 3, "c": 1, "d": 1}, top_n=3)
    lin = trace_lineage([
        {"id": "1", "source": "A", "text": "x y z", "published_at": "2026-01-01T00:00:00"},
        {"id": "2", "source": "B", "text": "x y z", "published_at": "2026-01-02T00:00:00"},
    ])
    actors = corpus_actors(s, days=settings_for("echo_chamber")["days"])
    texts = {
        "convergence.method": convergence.CONVERGENCE_METHOD,
        "convergence.caveat": convergence.CONVERGENCE_CAVEAT,
        "laundering.method": laundering.find_source_laundering(
            s, min_sources=lf["min_sources"], min_articles=lf["min_articles"])["method"],
        "laundering.caveat": laundering.LAUNDERING_CAVEAT,
        "recycled.method": recycled_claim.find_recycled_claims(s)["method"],
        "recycled.caveat": recycled_claim.RECYCLED_CAVEAT,
        "headline.method": headline_body.find_headline_body_mismatch(s)["method"],
        "headline.caveat": headline_body.HEADLINE_BODY_CAVEAT,
        "emergence.method": emergence.find_manufactured_emergence(s)["method"],
        "emergence.caveat": emergence.EMERGENCE_CAVEAT,
        "flood.method": conc.find_flooded_topics(
            s, recent_days=cf["recent_days"], baseline_days=cf["baseline_days"],
            min_recent_articles=cf["min_recent_articles"], min_share=cf["min_share"],
            z_min=cf["z_min"])["method"],
        "flood.caveat": conc.FLOOD_CAVEAT,
        "copypasta.method": copypasta.find_copypasta(
            s, recent_days=cc["recent_days"], k=cc["k"], min_sources=cc["min_sources"])["method"],
        "copypasta.caveat": copypasta.COPYPASTA_CAVEAT,
        "bury.method": conc.find_buried_topics(s)["method"],
        "bury.caveat": conc.BURY_CAVEAT,
        "alert.method": alerts.ALERT_METHOD,
        "alert.caveat": alerts.ALERT_CAVEAT,
        "disputed.method": disputed_chronology.find_disputed_chronology(s)["method"],
        "disputed.caveat": disputed_chronology.DISPUTED_CAVEAT,
        "propagation.method": story_propagation.find_story_propagation(s)["method"],
        "propagation.caveat": story_propagation.STORY_PROPAGATION_CAVEAT,
        "supply.method": supply_chain_ripple.find_supply_chain_ripples(s)["method"],
        "supply.caveat": supply_chain_ripple.SUPPLY_CHAIN_CAVEAT,
        "supergroup.method": supergroup_rising.find_rising_supergroups(s)["method"],
        "supergroup.caveat": supergroup_rising.RISING_CAVEAT,
        "emotion.method": prof["method"],
        "emotion.caveat": prof["caveat"],
        "diet.method": diet.method,
        "diet.caveat": diet.caveat,
        "neardup.method": near_duplicate_clusters(
            {"1": "a b c d e f g", "2": "a b c d e f g"}, threshold=0.5).method,
        "lineage.method": lin.method,
        "lineage.caveat": lin.caveat,
        "framing.caveat": compare_framing({
            "A": [{"text": "great wonderful", "language": "en", "title": "t"}],
            "B": [{"text": "terrible awful", "language": "en", "title": "t"}],
        })["caveat"],
        "echo.method": actors.method,
        "echo.caveat": actors.caveat,
    }
    for where, text in texts.items():
        assert isinstance(text, str) and text, where
        frames = numeric_frames(text)
        _assert_keyed(frames[0]["t"] if frames else text, locales, where)


def _type_labels() -> dict[str, str]:
    js = (_ROOT / "src" / "static" / "app-home.js").read_text("utf-8")
    body = js[js.index("const _CARD_TYPE_LABELS = {"):]
    body = body[: body.index("};")]
    return dict(re.findall(r'(\w+): "([^"]+)"', body))


def test_every_card_type_has_a_keyed_type_label(locales):
    """L-2: the chip read the raw type id ("SOURCE LAUNDERING") in every language."""
    labels = _type_labels()
    types: set[str] = set()
    for rel in ("src/briefing/producers.py", "src/briefing/recipes.py"):
        types |= set(re.findall(r'\btype="([a-z_]+)"', (_ROOT / rel).read_text("utf-8")))
    assert len(types) >= 35, types
    assert types <= set(labels), sorted(types - set(labels))
    for card_type, label in labels.items():
        _assert_keyed(label, locales, f"type label {card_type}")


# --------------------------------------------------------------------------- #
#  end to end through the real producers
# --------------------------------------------------------------------------- #
def _render(card: Card, field: str, table: dict[str, str]) -> str:
    return " ".join(_tf(fr["t"], fr["v"], table) for fr in card.i18n[field])


def test_the_laundering_card_reads_in_french_arabic_and_chinese(monkeypatch, locales):
    """L-1, the card the walk named: title, summary, method and caveat all frame to keys,
    and the rendering keeps the data (origin, source names, counts) as data."""
    from src.analytics import laundering
    from src.briefing import producers

    found = {
        "clusters": [{
            "origin": "https://origin.example/report", "origin_domain": "origin.example",
            "distinct_sources": 3, "n_articles": 5,
            "source_names": ["Alpha", "Beta", "Gamma"], "article_ids": [1, 2, 3, 4, 5],
        }],
        "min_sources": 3,
        "min_articles": 3,
        "method": (
            "Outbound origins cited by >= 3 distinct sources (and >= 3 articles); "
            "social/storefront/infrastructure origins excluded (CDNs, cookie/privacy-policy "
            "pages, share widgets, license footers); at most one card per registrable origin "
            "domain. Independence = distinct sources, not article count."
        ),
    }
    monkeypatch.setattr(laundering, "find_source_laundering", lambda *_a, **_k: found)
    (card,) = producers.source_laundering(None)
    assert card.title == "3 sources, one origin: origin.example"
    assert set(card.i18n) == {"title", "summary", "method", "caveat"}
    for field in ("title", "summary", "method", "caveat"):
        assert frames_text(card.i18n[field]) == getattr(card, field), field
        for fr in card.i18n[field]:
            _assert_keyed(fr["t"], locales, f"source_laundering.{field}")
    for lang in ("fr", "ar", "zh"):
        title = _render(card, "title", locales[lang])
        assert "origin.example" in title and "3" in title
        assert "sources, one origin" not in title, (lang, title)
        summary = _render(card, "summary", locales[lang])
        assert "Alpha, Beta, Gamma" in summary and "apparent corroboration" not in summary
        assert "one source wearing many hats" not in _render(card, "caveat", locales[lang])


class _CountQuery:
    def __init__(self, n: int) -> None:
        self.n = n

    def query(self, _model):
        return self

    def filter_by(self, **_kw):
        return self

    def count(self) -> int:
        return self.n


def test_source_candidates_title_agrees_with_its_count(locales):
    """M-6: "1 source candidate await your review" -- a count spliced before a plural."""
    from src.briefing.recipes import source_candidates_waiting

    (one,) = source_candidates_waiting(_CountQuery(1))
    (many,) = source_candidates_waiting(_CountQuery(4))
    assert one.title == "1 source candidate awaits your review"
    assert many.title == "4 source candidates await your review"
    assert "staged 1 suggested source." in one.summary
    assert "staged 4 suggested sources." in many.summary
    for card in (one, many):
        for field in ("title", "summary", "method", "caveat"):
            for fr in card.i18n[field]:
                _assert_keyed(fr["t"], locales, f"source_candidates.{field}")


@pytest.mark.parametrize(
    "template",
    [
        "{n} sources, one origin: {origin}",
        "Through time: this day in past years",
        "Your reading diet leans on a few sources",
        "{n} source candidate awaits your review",
        "{n} source candidates await your review",
    ],
)
def test_the_m6_titles_are_keyed(template, locales):
    """The four titles the re-walk found English in fr/ar (M-6, producer half)."""
    assert template in _frame_templates()
    _assert_keyed(template, locales, "M-6")


# --------------------------------------------------------------------------- #
#  the ranking line (N-8)
# --------------------------------------------------------------------------- #
def test_the_ranking_line_is_keyed_frames_and_its_english_is_unchanged(locales):
    from src.briefing.leads import explain_order, explain_order_frames

    now = datetime.now(UTC)
    dated = Card(
        type="rising", title="T", summary="S", bucket="watch", method="m", caveat="c", n=12,
        evidence=[{"source": "A", "published_at": (now - timedelta(days=2)).isoformat()}],
    )
    undated = Card(type="rising", title="T", summary="S", bucket="watch", method="m", caveat="c", n=0)
    for card in (dated, undated):
        frames = explain_order_frames(card, now=now)
        assert frames_text(frames) == explain_order(card, now=now)
        for fr in frames:
            _assert_keyed(fr["t"], locales, "explain_order")
    line = explain_order(dated, now=now)
    assert line.startswith("Ranked by a disclosed order (independent sources → sample magnitude → recency), never a score. This lead: 1 independent source(s); n=12 ")
    assert "freshest evidence 2.0 day(s) old." in line
    assert explain_order(undated, now=now).endswith("; no dated evidence.")


def test_the_served_cards_carry_the_ranking_frames():
    from src.briefing.service import _sorted

    card = Card(type="rising", title="T", summary="S", bucket="watch", method="m", caveat="c", n=3)
    cards = _sorted([card.to_dict()])
    assert cards[0]["order_explain_i18n"][0]["t"].startswith("Ranked by a disclosed order")
    assert cards[0]["order_explain"] == frames_text(cards[0]["order_explain_i18n"])


# --------------------------------------------------------------------------- #
#  the renderer (behavioural, node)
# --------------------------------------------------------------------------- #
def test_card_frames_node_suite():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "card_frames_node_test.js")],
        capture_output=True, text=True, timeout=60, cwd=_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

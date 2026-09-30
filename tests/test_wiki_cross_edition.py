"""Q712's analytics 4 and 5 (S05-06 S4): cross-edition divergence and attention against coverage.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ways these could be quietly false, and so the spine of this file: an edition the walk never
reached read as "Wikipedia has no page", a page the stream does not follow read as "nobody
edited it", a spread of sizes folded into one ratio, one day's top list presented as a series,
a Wikipedia-sourced article counted as press coverage of its own page, and a rank or a view
count replaced by something computed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.versioned.models import VersionedChange, VersionedEntity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import cross_edition as X
from src.wiki.identity import external_id_for
from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage
from tests.js_source_helper import object_literal

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


@pytest.fixture
def corpus():
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    session = sessionmaker(bind=eng, future=True)()
    try:
        yield session
    finally:
        session.close()
        eng.dispose()


def _walk(db, edition, page_id, title, qid, length, *, days_ago=1):
    db.add(
        WikiWalkPage(
            edition=edition, page_id=page_id, title=title, qid=qid, length_bytes=length,
            last_revid=1, walked_at=NOW - timedelta(days=days_ago), pass_no=1,
        )
    )


def _cursor(db, edition, *, seen, total, done):
    db.add(
        WikiWalkCursor(
            edition=edition, pass_no=1, pages_seen=seen, requests=1, response_bytes=1,
            edition_articles=total, completed_at=NOW if done else None,
        )
    )


def _follow(db, edition, page_id, *, changes, days_ago=1):
    ext = external_id_for(edition, page_id)
    db.add(VersionedEntity(external_id=ext, title="t"))
    for i in range(changes):
        db.add(
            VersionedChange(
                change_ref=f"{ext}-{i}", feed=f"stream:{edition}", change_kind="edit",
                external_id=ext, recorded_at=NOW - timedelta(days=days_ago, minutes=i), byte_delta=5,
            )
        )


def _record(db, edition, page_id, *, changes, days_ago=1, title=None):
    """Stream changes with NO followed-page entity, as the stream records them for every page
    of a followed edition; ``title`` writes the legacy title-keyed form instead of the id."""
    from src.wiki.identity import legacy_external_id_for

    ext = legacy_external_id_for(edition, title) if title else external_id_for(edition, page_id)
    for i in range(changes):
        db.add(
            VersionedChange(
                change_ref=f"{ext}-r{i}", feed=f"stream:{edition}", change_kind="edit",
                external_id=ext, recorded_at=NOW - timedelta(days=days_ago, minutes=i), byte_delta=5,
            )
        )


# --------------------------------------------------------------------------- #
# 4. Divergence.
# --------------------------------------------------------------------------- #
def test_an_invalid_item_is_refused_by_name_and_a_lowercase_one_is_read(lane):
    assert X.normalise_qid(" q42 ") == "Q42"
    for bad in ("42", "Q", "Q0", "Q-1", "Q42; DROP", "", None, 7):
        assert X.normalise_qid(bad) is None
    with lane_session("wiki") as db:
        out = X.divergence(db, "nope", editions=["en"], now=NOW)
    assert out["measured"] is False and out["reason"] == "qid-invalid"


def test_every_edition_is_named_with_WHY_it_has_no_page(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _cursor(db, "en", seen=10, total=10, done=True)
        _cursor(db, "de", seen=30, total=1000, done=False)
        _cursor(db, "fr", seen=500, total=500, done=True)
        # es: no cursor at all; the walk never ran there.
        db.flush()
        out = X.divergence(db, "Q34", editions=["en", "de", "fr", "es"], now=NOW)
    by = {r["edition"]: r for r in out["editions"]}
    assert by["en"]["state"] == X.STATE_FOUND
    assert by["de"]["state"] == X.STATE_WALK_INCOMPLETE and by["de"]["walk"]["pages_seen"] == 30
    assert by["fr"]["state"] == X.STATE_NONE_AFTER_WALK and by["fr"]["walk"]["edition_articles"] == 500
    assert by["es"]["state"] == X.STATE_NOT_WALKED and by["es"]["walk"] is None
    assert (out["n_found"], out["n_editions"]) == (1, 4)


def test_sizes_are_shown_as_they_are_with_the_extremes_named_and_no_ratio(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _walk(db, "de", 2, "Salz", "Q34", 12000)
        _walk(db, "fr", 3, "Sel", "Q34", 300)
        db.flush()
        out = X.divergence(db, "Q34", editions=["en", "de", "fr"], now=NOW)
    assert out["smallest"] == {"edition": "fr", "length_bytes": 300}
    assert out["largest"] == {"edition": "de", "length_bytes": 12000}
    flat = repr(out).lower()
    for word in ("ratio", "score", "rank", "diverge_by", "percent"):
        assert word not in flat, word
    assert [r["length_bytes"] for r in out["editions"]] == [9000, 12000, 300]


def test_an_edition_the_stream_recorded_nothing_for_has_UNKNOWN_changes_not_zero(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _walk(db, "de", 2, "Salz", "Q34", 12000)
        _follow(db, "en", 1, changes=3)
        db.flush()
        out = X.divergence(db, "Q34", editions=["en", "de"], now=NOW)
    by = {r["edition"]: r for r in out["editions"]}
    assert by["en"]["stream_recorded"] is True and by["en"]["changes_in_window"] == 3
    assert by["de"]["stream_recorded"] is False and by["de"]["changes_in_window"] is None


def test_changes_the_stream_recorded_without_a_followed_entity_are_counted_by_either_key(lane):
    """The stream records every change of a followed edition, entity or not, under the id
    form or (before Q715) the title form; both count, and neither is reported as unknown."""
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _record(db, "en", 1, changes=6)
        _record(db, "en", 1, changes=4, title="Salt")
        db.flush()
        out = X.divergence(db, "Q34", editions=["en"], now=NOW)
    row = out["editions"][0]
    assert row["stream_recorded"] is True and row["changes_in_window"] == 10


def test_a_recorded_edition_with_no_changes_in_the_window_is_a_real_zero(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _follow(db, "en", 1, changes=2, days_ago=40)
        db.flush()
        out = X.divergence(db, "Q34", editions=["en"], window_days=7, now=NOW)
    assert out["editions"][0]["stream_recorded"] is True and out["editions"][0]["changes_in_window"] == 0


def test_an_item_no_walk_found_is_unmeasured_and_says_so(lane):
    with lane_session("wiki") as db:
        _cursor(db, "en", seen=1, total=5, done=False)
        db.flush()
        out = X.divergence(db, "Q999", editions=["en"], now=NOW)
    assert out["measured"] is False and out["reason"] == "item-not-found"
    assert out["editions"][0]["state"] == X.STATE_WALK_INCOMPLETE


def test_an_edition_the_item_was_found_in_is_listed_even_if_the_operator_does_not_follow_it(lane):
    with lane_session("wiki") as db:
        _walk(db, "it", 7, "Sale", "Q34", 500)
        db.flush()
        out = X.divergence(db, "Q34", editions=["en"], now=NOW)
    assert [r["edition"] for r in out["editions"]] == ["en", "it"]


def test_candidates_are_the_items_of_the_most_changed_followed_pages(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _walk(db, "de", 2, "Salz", "Q34", 9000)
        _walk(db, "en", 3, "Iron", "Q677", 100)
        _walk(db, "en", 4, "No item", None, 100)
        _follow(db, "en", 1, changes=5)
        _follow(db, "en", 3, changes=2)
        _follow(db, "en", 4, changes=9)  # most changed, but no item: never suggested
        db.flush()
        out = X.divergence_candidates(db, now=NOW)
    assert [(i["qid"], i["changes_in_window"], i["editions_found"]) for i in out["items"]] == [
        ("Q34", 5, 2), ("Q677", 2, 1),
    ]


def test_candidates_count_title_keyed_rows_and_say_how_many_pages_they_read(lane):
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _record(db, "en", 1, changes=6)
        _record(db, "en", 1, changes=4, title="Salt")  # a row written before Q715
        db.flush()
        out = X.divergence_candidates(db, now=NOW)
    assert [(i["qid"], i["changes_in_window"]) for i in out["items"]] == [("Q34", 10)]
    assert out["read_top"] == X.CANDIDATE_ROWS_READ


def test_candidates_are_empty_without_changes(lane):
    with lane_session("wiki") as db:
        assert X.divergence_candidates(db, now=NOW) == {
            "items": [], "n": 0, "window_days": 7, "read_top": X.CANDIDATE_ROWS_READ,
        }


# --------------------------------------------------------------------------- #
# 5. Attention against coverage.
# --------------------------------------------------------------------------- #
def _top(monkeypatch, edition, day, rows):
    blob = {"day": day, "rows": rows, "titles": [r["title"] for r in rows], "n": 1000}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda key: blob if key.endswith(f".{edition}") else None)


def _article(db, n, title, content, when, domain="news.example"):
    src = db.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(name=domain, domain=domain, rss_url=None)
        db.add(src)
        db.flush()
    db.add(
        Article(
            url=f"https://{domain}/{n}", canonical_url=f"https://{domain}/{n}", source_id=src.id,
            title=title, content=content, hash=f"{n:064d}", published_at=when,
        )
    )
    db.commit()


def test_no_top_list_yet_is_named_not_shown_as_an_empty_table(corpus, monkeypatch):
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda key: None)
    out = X.attention(corpus, edition="en")
    assert out == {"measured": False, "reason": "no-top-list-yet", "edition": "en"}


def test_the_sources_rank_and_views_are_kept_as_given_beside_the_press_counts(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [
        {"title": "Solar eclipse", "rank": 1, "views": 900_000},
        {"title": "Quiet page", "rank": 2, "views": 120_000},
    ])
    day = datetime(2026, 9, 29, 10, 0)
    _article(corpus, 1, "Eclipse today", "The Solar eclipse crossed the coast.", day)
    _article(corpus, 2, "Eclipse earlier", "A Solar eclipse was forecast.", day - timedelta(days=3))
    _article(corpus, 3, "Too old", "Solar eclipse, long ago.", day - timedelta(days=20))
    _article(corpus, 4, "Next day", "Solar eclipse tomorrow.", day + timedelta(days=2))
    out = X.attention(corpus, edition="en")
    assert out["measured"] and out["day"] == "2026-09-29" and out["n"] == 2 and out["skipped"] == 0
    first, second = out["rows"]
    assert (first["rank"], first["views"]) == (1, 900_000) and (second["rank"], second["views"]) == (2, 120_000)
    assert (first["press_day"], first["press_7d"]) == (1, 2)
    assert (second["press_day"], second["press_7d"]) == (0, 0), "no article mentions it: a real zero, counted"


def test_a_wikipedia_sourced_article_is_not_coverage_of_its_own_page(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [{"title": "Solar eclipse", "rank": 1, "views": 10}])
    day = datetime(2026, 9, 29, 10, 0)
    _article(corpus, 1, "Solar eclipse", "Solar eclipse is when the moon passes.", day, domain="en.wikipedia.org")
    _article(corpus, 2, "Press", "The Solar eclipse was seen.", day)
    out = X.attention(corpus, edition="en")
    assert out["rows"][0]["press_day"] == 1


def test_the_bare_wikipedia_domain_is_excluded_like_its_subdomains(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [{"title": "Solar eclipse", "rank": 1, "views": 10}])
    day = datetime(2026, 9, 29, 10, 0)
    _article(corpus, 1, "Solar eclipse", "Solar eclipse is when the moon passes.", day, domain="wikipedia.org")
    out = X.attention(corpus, edition="en")
    assert out["rows"][0]["press_day"] == 0


def test_a_title_with_no_searchable_words_is_named_as_such_never_as_a_timeout(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [
        {"title": "Main Page", "rank": 1, "views": 9}, {"title": "-", "rank": 2, "views": 8},
    ])
    out = X.attention(corpus, edition="en")
    assert out["skipped"] == 0 and out["unsearchable"] == 1
    dash = out["rows"][1]
    assert dash["press_day"] is None and dash["not_counted"] == "unsearchable"
    assert out["rows"][0]["not_counted"] is None


def test_an_undated_article_is_in_neither_window(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [{"title": "Solar eclipse", "rank": 1, "views": 10}])
    _article(corpus, 1, "Undated", "The Solar eclipse.", None)
    out = X.attention(corpus, edition="en")
    assert (out["rows"][0]["press_day"], out["rows"][0]["press_7d"]) == (0, 0)
    assert "undated" in out["caveat"]


def test_rows_not_counted_before_the_deadline_are_reported_as_skipped_never_as_zero(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [
        {"title": "First", "rank": 1, "views": 3}, {"title": "Second", "rank": 2, "views": 2},
    ])
    clock = iter([0.0, 0.0, 99.0, 99.0, 99.0])
    out = X.attention(corpus, edition="en", deadline_s=1.0, monotonic=lambda: next(clock))
    assert out["skipped"] == 1
    assert out["rows"][1]["press_day"] is None and out["rows"][1]["press_7d"] is None
    assert out["rows"][1]["not_counted"] == "time"
    assert out["rows"][0]["press_day"] == 0


def test_the_block_is_one_days_cross_section_and_says_so_with_no_score_anywhere(corpus, monkeypatch):
    _top(monkeypatch, "en", "2026-09-29", [{"title": "Solar eclipse", "rank": 1, "views": 10}])
    out = X.attention(corpus, edition="en")
    assert "cross-section" in out["caveat"] and "not a series" in out["caveat"]
    assert "never combined" in out["caveat"]
    flat = repr({k: v for k, v in out.items() if k not in ("method", "caveat")}).lower()
    for word in ("score", "ratio", "gap", "lead", "weight"):
        assert word not in flat, word


# --------------------------------------------------------------------------- #
# The routes.
# --------------------------------------------------------------------------- #
def test_the_divergence_route_answers_suggestions_without_an_item_and_the_table_with_one(lane, monkeypatch):
    from src.api import wiki_lane as R

    monkeypatch.setattr(R, "_followed_editions", lambda: ("en", "de"))
    monkeypatch.setattr(X, "_utcnow", lambda: NOW)  # the route reads the real clock otherwise
    with lane_session("wiki") as db:
        _walk(db, "en", 1, "Salt", "Q34", 9000)
        _follow(db, "en", 1, changes=2, days_ago=0)
        db.commit()
    first = R.lane_divergence(qid=None, window_days=7)
    assert first["measured"] is False and first["reason"] == "no-item-chosen"
    assert [c["qid"] for c in first["candidates"]["items"]] == ["Q34"]
    bad = R.lane_divergence(qid="salt", window_days=7)
    assert bad["reason"] == "qid-invalid"
    ok = R.lane_divergence(qid="q34", window_days=7)
    assert ok["measured"] and ok["qid"] == "Q34" and {r["edition"] for r in ok["editions"]} == {"en", "de"}
    assert "candidates" not in ok and "candidates" not in bad, "the suggestions scan the window: only asked for with no item"


def test_the_divergence_route_is_absent_when_the_lane_never_ran(tmp_path, monkeypatch):
    from src.api import wiki_lane as R

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    dispose_all()
    assert R.lane_divergence(qid=None, window_days=7)["reason"] == "lane-never-run"


# --- the two views in Living sources ------------------------------------------------
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def test_the_renderers_behave():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "wiki_compare_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_views_sit_in_the_wikipedia_panel_with_no_inline_handlers():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    wiki = html[html.index('<div id="living-wiki">'):html.index('<div id="living-law"')]
    for ident in ("wiki-div-form", "wiki-div-q", "wiki-div-cands", "wiki-div-result", "wiki-att-tools", "wiki-att-result"):
        assert f'id="{ident}"' in wiki, ident
    block = wiki[wiki.index("One item across editions"):]
    assert "onclick" not in block.lower()
    js = (_STATIC / "app-living.js").read_text(encoding="utf-8")
    assert "loadWikiDivergence(" in js and "loadWikiAttention()" in js
    assert "repaintWikiCompareFromCache();" in js, "a language switch redraws both views from the cache"


def test_every_string_the_two_views_draw_is_keyed_in_all_twelve_locales():
    """The i18n gate skips a t() literal carrying a {placeholder}; check this block's own."""
    js = (_STATIC / "app-living.js").read_text(encoding="utf-8")
    block = js[js.index("// --- One item across editions, and the most-viewed"):]
    lits = {m.replace('\\"', '"') for m in re.findall(r'\btf?\("((?:[^"\\]|\\.)*)"', block)}
    table = object_literal(block, "_WIKI_DIV_STATES")
    lits |= set(re.findall(r':\s*\n?\s*"((?:[^"\\]|\\.)*)"', table))
    lits |= set(re.findall(r'"(The Wikipedia lane [^"]*)"', block))
    from src.wiki import cross_edition

    source = Path(cross_edition.__file__).read_text(encoding="utf-8")
    for key in ("method", "caveat"):
        for m in re.finditer(rf'"{key}": \(\n((?:\s+".*"\n)+)\s+\),', source):
            lits.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace('\\"', '"'))
    assert len(lits) > 35
    for code in ("en", "fr", "es", "de", "pt", "ru", "ar", "hi", "bn", "zh", "ja", "id"):
        loc = json.loads((_STATIC / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        missing = sorted(x for x in lits if x not in loc)
        assert not missing, (code, missing)

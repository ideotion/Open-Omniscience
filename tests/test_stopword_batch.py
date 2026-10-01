"""The offline stoplist-batch tool (R111): every refusal, the YAML round trip, and --apply.

The tool runs in a checkout on a diagnostics keyword log and never touches the app or the
network; these tests run it on a synthetic log so the refusals are proved, not described.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("stopword_batch", ROOT / "scripts" / "stopword_batch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sb = _load()


def _kw(term, lang, arts, *, kind="term", hidden=False, **extra):
    return {"term": term, "normalized": term, "language": lang, "kind": kind, "articles": arts,
            "mentions": arts * 2, "hidden": hidden, **extra}


LOG = [
    _kw("permalink", "en", 900),
    _kw("follow", "en", 700),
    _kw("facebook", "en", 500),
    _kw("election", "en", 400),  # a shipped ring member
    _kw("pie", "en", 300),
    _kw("pie", "de", 40),  # live content in another language
    _kw("rose", "en", 600),
    _kw("rose", "en", 50, kind="person"),  # also an entity
    _kw("sidebar", "en", 500, top_source_share=0.9, sources=2),
    _kw("widget", "en", 500, top_source_share=0.1, sources=200),
    _kw("the", "en", 9000),
]


@pytest.fixture()
def ctx():
    hidden, ring = sb.app_context("en")
    return hidden, ring, sb.index_log(LOG)


def _refusals(word, ctx, allow=frozenset()):
    hidden, ring, index = ctx
    ev = sb.evidence(word, "en", index.get(word, []), hidden)
    return sb.refusals(word, ev, ring_words=ring, platforms=sb.platform_names(), allow=allow), ev


def test_a_plain_page_word_is_addable(ctx):
    why, ev = _refusals("permalink", ctx)
    assert why == [] and ev["articles"] == 900


def test_every_refusal_has_its_reason(ctx):
    assert _refusals("facebook", ctx)[0] == ["platform_name"]
    assert "ring_member" in _refusals("election", ctx)[0]
    assert _refusals("pie", ctx)[0] == ["content_elsewhere"]
    assert _refusals("rose", ctx)[0] == ["also_an_entity"]
    assert _refusals("sidebar", ctx)[0] == ["single_source"]
    assert _refusals("the", ctx)[0] == ["already_hidden"]
    assert "phrase" in _refusals("read more", ctx)[0]


def test_ring_and_platform_refusals_cannot_be_overridden(ctx):
    allow = frozenset({"facebook", "election"})
    assert "platform_name" in _refusals("facebook", ctx, allow)[0]
    assert "ring_member" in _refusals("election", ctx, allow)[0]
    assert _refusals("pie", ctx, frozenset({"pie"}))[0] == []  # the maintainer's judgement call


def test_a_spread_word_is_not_a_single_source_boilerplate(ctx):
    assert _refusals("widget", ctx)[0] == []


def test_a_log_without_source_spread_is_not_judged_and_says_so(ctx, capsys, tmp_path):
    zpath = tmp_path / "log.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("summary.json", json.dumps({"kind": "keyword-diagnostics", "data": {}}))
        z.writestr("keywords/en.json", json.dumps({"keywords": LOG}))
    words = tmp_path / "w.txt"
    words.write_text("permalink\nfacebook  # a platform\n", "utf-8")
    assert sb.main([str(zpath), "--language", "en", "--words", str(words)]) == 0
    out = capsys.readouterr().out
    assert "1 addable, 1 refused" in out and "platform_name" in out
    assert "permalink" in out
    assert "single-source boilerplate NOT judged" in out  # a log without source spread says so


def test_apply_appends_a_batch_that_still_loads_and_quotes_yaml_words(tmp_path, monkeypatch, capsys):
    (tmp_path / "en.yml").write_text("# header\nstopwords:\n  - alpha\n  - beta\n", "utf-8")
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    path = sb.append_batch("en", ["yes", "null", "permalink", "123"], "en-test", ["pie"], "log.zip")
    doc = yaml.safe_load(path.read_text("utf-8"))
    assert doc["stopwords"][:2] == ["alpha", "beta"]
    assert doc["stopwords"][2:] == sorted(["yes", "null", "permalink", "123"])
    assert "batch en-test" in path.read_text("utf-8") and "pie" in path.read_text("utf-8")


def test_apply_writes_nothing_when_the_file_has_no_list(tmp_path, monkeypatch):
    (tmp_path / "xx.yml").write_text("other: 1\n", "utf-8")
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        sb.append_batch("xx", ["word"], "xx-1", [], "log.json")
    assert (tmp_path / "xx.yml").read_text("utf-8") == "other: 1\n"


def test_apply_creates_the_file_for_a_language_that_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    path = sb.append_batch("ja", ["サイト"], "ja-1", [], "log.zip")
    assert yaml.safe_load(path.read_text("utf-8"))["stopwords"] == ["サイト"]


@pytest.mark.parametrize("layout", ["stopwords:\n- a\n- b\n", "stopwords: [a, b]\n"])
def test_an_unusual_file_layout_is_a_clear_refusal_and_nothing_is_written(tmp_path, monkeypatch, layout):
    (tmp_path / "xx.yml").write_text(layout, "utf-8")
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        sb.append_batch("xx", ["word"], "xx-1", [], "log.json")
    assert "Nothing written" in str(exc.value) or "refusing" in str(exc.value)
    assert (tmp_path / "xx.yml").read_text("utf-8") == layout


def test_a_final_sigma_word_already_listed_is_seen_as_listed_and_written_as_extraction_reads_it():
    # extraction compares .lower() tokens; casefold would turn the final sigma into a medial one
    assert sb.spelling("ΈΝΑΣ") == "ένας" and sb.norm("ένας") == "ένασ"
    hidden, _ring = sb.app_context("el")
    ev = sb.evidence(sb.spelling("ένας"), "el", [], hidden)
    assert ev["already_hidden"] is True


def test_read_words_keeps_c_sharp_and_refuses_a_tab_separated_phrase(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("c#\nread\tmore\npermalink  # a trailing comment\n# a whole-line comment\n", "utf-8")
    words = sb.read_words(f)
    assert words == ["c#", "read more", "permalink"]
    ev = sb.evidence("read more", "en", [], frozenset())
    assert "phrase" in sb.refusals("read more", ev, ring_words=frozenset(), platforms=frozenset(),
                                   allow=frozenset())


def test_a_trimmed_or_paged_log_is_announced(tmp_path):
    z = tmp_path / "log.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"keywords_omitted_to_fit": 120, "has_more": True}))
    note = sb.trimmed_log_notice(z)
    assert note and "120" in note and "incomplete" in note
    full = tmp_path / "full.zip"
    with zipfile.ZipFile(full, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"keywords_omitted_to_fit": 0}))
    assert sb.trimmed_log_notice(full) is None


def test_the_platform_keep_list_ships_and_reads():
    assert {"facebook", "twitter", "youtube"} <= sb.platform_names()


def test_the_tool_is_offline_and_outside_the_app():
    src = (ROOT / "scripts" / "stopword_batch.py").read_text("utf-8")
    for banned in ("import requests", "import httpx", "urllib.request", "socket"):
        assert banned not in src
    app_main = (ROOT / "src" / "api" / "main.py").read_text("utf-8")
    assert "stopword_batch" not in app_main


def test_a_word_shipped_in_a_stoplist_hides_in_the_stored_keywords_with_no_user_step(monkeypatch):
    """R111's premise on the main path: a stored keyword disappears from the top list the moment
    the shipped stoplist holds it (after the restart an update brings); nothing is recomputed.

    SCOPE, stated plainly: it patches the in-memory extra stoplist, so it proves READ-TIME hiding on
    ``top_terms`` and nothing else. That a word written to a YAML file reaches the loader is
    ``tests/test_analytics_extract.py``'s job; extraction-time dropping and the surfaces that never
    consult the stoplist are not covered here (R111 steps T2 and T3)."""
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics import extract, filters, queries
    from src.database.models import Article, Base, Keyword, KeywordMention, Source

    monkeypatch.setattr(filters, "load_settings", lambda: filters.KeywordFilter(use_builtin_stopwords=True))
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        s.add(Source(id=1, name="A", domain="a.test", country="fr"))
        s.commit()
        s.add(Article(id=1, url="https://a.test/1", canonical_url="https://a.test/1", source_id=1, title="t",
                      content="c", hash="h1", country="fr", language="en",
                      published_at=datetime(2024, 4, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
        s.add(Keyword(id=1, term="zzfurniture", normalized_term="zzfurniture", language="en", mention_count=9, article_count=1))
        s.add(Keyword(id=2, term="harvest", normalized_term="harvest", language="en", mention_count=7, article_count=1))
        s.commit()
        s.add(KeywordMention(keyword_id=1, article_id=1, count=9))
        s.add(KeywordMention(keyword_id=2, article_id=1, count=7))
        s.commit()

        def listed() -> set[str]:
            return {r.get("term") for r in queries.top_terms(s, limit=20)["terms"]}

        assert listed() == {"zzfurniture", "harvest"}
        monkeypatch.setattr(extract, "_EXTRA_STOPWORDS", frozenset(extract._EXTRA_STOPWORDS) | {"zzfurniture"})
        def _recache() -> None:  # what the restart after an update does
            for fn in (extract._global_stopwords_raw, extract._ring_member_exemptions, extract.global_stopwords):
                fn.cache_clear()

        _recache()
        try:
            assert listed() == {"harvest"}  # hidden at read time; the stored rows are untouched
            assert s.query(Keyword).count() == 2
        finally:
            monkeypatch.undo()
            _recache()

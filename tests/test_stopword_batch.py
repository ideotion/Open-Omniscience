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
_REAL_APP_CONTEXT = sb.app_context
REAL_KEEP_FILE = sb.KEEP_FILE

# What extraction already drops per language and what the rings hold, SYNTHETIC: no test here may
# depend on what the shipped stoplists hold today, or the first real batch that adds "permalink"
# would turn it red (coordinator check on #1280, P5).
HIDDEN = {
    "en": frozenset({"the"}),
    "de": frozenset({"heisst"}),
    "el": frozenset({"ένας"}),
    "ca": frozenset({"li'n", "d'una", "s'han"}),  # straight-only contractions, as the vendored list holds them
}
RING = frozenset({"election"})
KEEP = {"platform_names": ["facebook", "twitter", "youtube"], "ambiguous_platform_names": ["signal", "x", "threads"]}


@pytest.fixture(autouse=True)
def synthetic_shipped_data(tmp_path, monkeypatch):
    keep = tmp_path / "keep.yml"
    keep.write_text(yaml.safe_dump(KEEP), "utf-8")
    monkeypatch.setattr(sb, "KEEP_FILE", keep)
    monkeypatch.setattr(sb, "app_context", lambda lang: (HIDDEN.get(lang, frozenset()), RING))


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
    _kw("signal", "en", 300),
    _kw("x", "en", 300),
]


@pytest.fixture()
def ctx():
    hidden, ring = sb.app_context("en")
    return hidden, ring, sb.index_log(LOG)


def _refusals(word, ctx, allow=frozenset()):
    hidden, ring, index = ctx
    ev = sb.evidence(word, "en", index.get(word, []), hidden)
    return sb.refusals(word, ev, ring_words=ring, platforms=sb.platform_names(),
                       ambiguous=sb.ambiguous_platform_names(), allow=allow), ev


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
    assert _refusals("zznotinlog", ctx)[0] == ["not_in_log"]
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
    assert {"facebook", "twitter", "youtube"} <= sb.platform_names(REAL_KEEP_FILE)
    assert {"signal", "threads", "x"} <= sb.ambiguous_platform_names(REAL_KEEP_FILE)


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
        s.add(Keyword(id=2, term="zzharvest", normalized_term="zzharvest", language="en", mention_count=7, article_count=1))
        s.commit()
        s.add(KeywordMention(keyword_id=1, article_id=1, count=9))
        s.add(KeywordMention(keyword_id=2, article_id=1, count=7))
        s.commit()

        def listed() -> set[str]:
            return {r.get("term") for r in queries.top_terms(s, limit=20)["terms"]}

        assert listed() == {"zzfurniture", "zzharvest"}
        monkeypatch.setattr(extract, "_EXTRA_STOPWORDS", frozenset(extract._EXTRA_STOPWORDS) | {"zzfurniture"})
        def _recache() -> None:  # what the restart after an update does
            for fn in (extract._global_stopwords_raw, extract._ring_member_exemptions, extract.global_stopwords):
                fn.cache_clear()

        _recache()
        try:
            assert listed() == {"zzharvest"}  # hidden at read time; the stored rows are untouched
            assert s.query(Keyword).count() == 2
        finally:
            monkeypatch.undo()
            _recache()


def test_an_eszett_word_is_not_refused_as_already_hidden_when_only_the_ss_spelling_is_listed():
    # the German list holds "heisst"; extraction keeps "heißt" (a different token), so it is addable
    hidden, _ring = sb.app_context("de")
    assert "heisst" in hidden and "heißt" not in hidden
    assert sb.evidence(sb.spelling("heißt"), "de", [], hidden)["already_hidden"] is False
    assert sb.evidence("heisst", "de", [], hidden)["already_hidden"] is True


def test_candidate_mode_prints_the_surface_form_not_the_casefold_key():
    log = {"data": {"keywords": [
        {"term": "όσος", "normalized": "όσοσ", "language": "el", "kind": "term", "articles": 80,
         "mentions": 200, "sources": 9},
    ]}}
    shown = sb.candidates_to_read(log, "el", frozenset())
    assert shown and all(w == "όσος" for w in shown)
    assert [sb.spelling(w) for w in shown] == ["όσος"]


@pytest.mark.parametrize("bad", ["../escaped", "/etc/x", "a/b", "", "EN ", "x.y"])
def test_a_language_code_cannot_carry_a_path(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path / "extra")
    (tmp_path / "extra").mkdir()
    with pytest.raises(SystemExit):
        sb.append_batch(bad, ["word"], "b-1", [], "log.zip")
    assert not (tmp_path / "escaped.yml").exists()
    assert list((tmp_path / "extra").iterdir()) == []


def test_a_curly_apostrophe_is_written_straight_and_meets_a_log_spelt_either_way(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("y’all\n", "utf-8")
    assert sb.read_words(f) == ["y'all"]
    idx = sb.index_log([_kw("y’all", "en", 50)])
    assert "y'all" in idx


def test_the_last_page_of_a_paged_export_is_announced_too(tmp_path):
    z = tmp_path / "last.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"page": 3, "pages_total": 3, "has_more": False,
                                                   "keywords_omitted_to_fit": 0}))
    note = sb.trimmed_log_notice(z)
    assert note and "page" in note
    only = tmp_path / "only.zip"
    with zipfile.ZipFile(only, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"page": 1, "pages_total": 1, "has_more": False}))
    assert sb.trimmed_log_notice(only) is None


def _verdict_file(tmp_path, *rows, name="v.tsv"):
    f = tmp_path / name
    f.write_text("# language\tword\tverdict\tcode\tconfidence\tmodel\tflags\n"
                 + "\n".join("\t".join(r) for r in rows) + "\n", "utf-8")
    return f


def _apply(tmp_path, monkeypatch, lang, words_text, verdict_rows, keywords, *extra, batch_id="b-1"):
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(sb, "EXTRA_DIR", extra_dir)
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": keywords}}), "utf-8")
    words = tmp_path / "w.txt"
    words.write_text(words_text, "utf-8")
    verdicts = _verdict_file(tmp_path, *verdict_rows)
    return sb.main([str(log), "--language", lang, "--words", str(words), "--verdicts", str(verdicts),
                    "--apply", "--batch-id", batch_id, *extra])


def test_apply_hints_the_curly_copy_and_the_script_guard_for_a_new_file(tmp_path, monkeypatch, capsys):
    rc = _apply(tmp_path, monkeypatch, "xx", "y'all\n", [("xx", "y'all", "N", "fn", "H", "sonnet-5.5")],
                [_kw("y'all", "xx", 50, sources=9)], batch_id="xx-1")
    assert rc == 0
    out = capsys.readouterr().out
    assert '"y’all"' in out and '"y\'all"' in out
    assert "_NON_LATIN_FILES" in out


def test_a_contraction_listed_only_with_a_straight_apostrophe_is_not_already_hidden():
    # ca "li'n" sits in a vendored list (no curly copy), so extraction still keeps "li’n"
    hidden, _ring = sb.app_context("ca")
    assert "li'n" in hidden and "li’n" not in hidden
    assert sb.evidence("li'n", "ca", [], hidden)["already_hidden"] is False
    assert sb.evidence("l", "ca", [], frozenset({"l"}))["already_hidden"] is True


def test_an_elided_contraction_is_refused_because_extraction_never_sees_it_as_one():
    # "d'una" becomes "una" before the stop check, in either apostrophe, so a stoplist entry is a no-op
    hidden, _ring = sb.app_context("ca")
    for w in ("d'una", "s'han", "d'xyzzy"):
        ev = sb.evidence(w, "ca", [], hidden)
        assert ev["de_elided"] is True and ev["already_hidden"] is False  # its own reason, not "listed"
        assert "de_elided" in sb.refusals(w, ev, ring_words=frozenset(), platforms=frozenset(), allow=frozenset())


# ---- the verdict gate (R98/R111; coordinator check P1) ----------------------------------------

def test_the_verdict_gate_admits_only_a_reproducible_high_confidence_n(tmp_path):
    f = _verdict_file(
        tmp_path,
        ("en", "permalink", "N", "bp", "H", "sonnet-5.5"),
        ("en", "follow", "N", "lv", "L", "sonnet-5.5"),
        ("en", "rose", "K", "", "", "sonnet-5.5"),
        ("en", "sidebar", "N", "bp", "H", "sonnet-5.5", "unstable"),
        ("en", "widget", "N", "bp", "H", "sonnet-5.5"),
        ("en", "widget", "N", "bp", "L", "haiku-4.5"),  # a second, unsure reading spoils it
        ("fr", "lundi", "N", "cal", "H", "sonnet-5.5"),
    )
    v = sb.read_verdicts(f, "en")
    assert sb.verdict_refusals("permalink", v) == []
    assert sb.verdict_refusals("follow", v) == ["not_high_confidence"]
    assert sb.verdict_refusals("rose", v) == ["not_junk", "not_high_confidence"]
    assert sb.verdict_refusals("sidebar", v) == ["unstable"]
    assert sb.verdict_refusals("widget", v) == ["not_high_confidence"]
    assert sb.verdict_refusals("lundi", v) == ["no_verdict"]  # another language's row is not this one's
    assert sb.verdict_refusals("unjudged", v) == ["no_verdict"]


def test_apply_refuses_to_run_without_a_verdict_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": LOG}}), "utf-8")
    words = tmp_path / "w.txt"
    words.write_text("permalink\n", "utf-8")
    with pytest.raises(SystemExit) as exc:
        sb.main([str(log), "--language", "en", "--words", str(words), "--apply", "--batch-id", "b-1"])
    assert "--verdicts" in str(exc.value)
    assert not (tmp_path / "en.yml").exists()


def test_apply_writes_only_judged_words_and_records_where_the_decision_came_from(tmp_path, monkeypatch, capsys):
    rc = _apply(
        tmp_path, monkeypatch, "en", "permalink\nfollow\nwidget\n",
        [("en", "permalink", "N", "bp", "H", "sonnet-5.5"), ("en", "follow", "K", "", "", "sonnet-5.5"),
         ("en", "widget", "N", "bp", "H", "sonnet-5.5", "single_reader")],
        LOG,
    )
    assert rc == 0
    text = (tmp_path / "extra" / "en.yml").read_text("utf-8")
    assert yaml.safe_load(text)["stopwords"] == ["permalink", "widget"]  # "follow" was kept by the triage
    assert "verdicts sha256" in text and "models sonnet-5.5" in text and "single reader: widget" in text
    assert "REFUSED follow" in capsys.readouterr().out


def test_the_batch_comment_is_deterministic_no_date_no_file_name(tmp_path, monkeypatch):
    rows = [("en", "permalink", "N", "bp", "H", "sonnet-5.5")]
    _apply(tmp_path, monkeypatch, "en", "permalink\n", rows, LOG)
    text = (tmp_path / "extra" / "en.yml").read_text("utf-8")
    assert "log.json" not in text and "v.tsv" not in text
    import re as _re
    assert not _re.search(r"20\d\d-\d\d-\d\d", text)


def test_candidate_mode_with_verdicts_is_limited_to_judged_words(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": LOG}}), "utf-8")
    v = _verdict_file(tmp_path, ("en", "permalink", "N", "bp", "H", "sonnet-5.5"),
                      ("en", "follow", "N", "lv", "L", "sonnet-5.5"))
    assert sb.main([str(log), "--language", "en", "--verdicts", str(v)]) == 0
    out = capsys.readouterr().out
    assert "permalink" in out and "follow" not in out and "1 words read" in out


# ---- the platform guard fails closed (P2) ------------------------------------------------------

def test_a_missing_or_empty_keep_file_stops_the_tool(tmp_path, monkeypatch):
    for content in (None, "", "platform_names: []\n", "- a\n- b\n", "platform_names: [unclosed\n"):
        keep = tmp_path / "k.yml"
        if content is None:
            keep.unlink(missing_ok=True)
        else:
            keep.write_text(content, "utf-8")
        monkeypatch.setattr(sb, "KEEP_FILE", keep)
        with pytest.raises(SystemExit):
            sb.platform_names()


def test_the_main_run_stops_when_the_keep_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "KEEP_FILE", tmp_path / "gone.yml")
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": LOG}}), "utf-8")
    with pytest.raises(SystemExit):
        sb.main([str(log), "--language", "en"])


def test_an_ambiguous_platform_name_is_refused_and_only_allow_lifts_it(ctx):
    assert _refusals("signal", ctx)[0] == ["platform_name"]
    assert _refusals("x", ctx)[0] == ["platform_name"]
    assert _refusals("signal", ctx, frozenset({"signal"}))[0] == []
    assert "platform_name" in _refusals("facebook", ctx, frozenset({"facebook"}))[0]  # a firm name has no override


# ---- evidence, not silence (P3) ----------------------------------------------------------------

def test_a_flat_json_log_is_read_with_its_guards_on(tmp_path, capsys):
    log = tmp_path / "flat.json"
    log.write_text(json.dumps({"keywords": LOG}), "utf-8")
    words = tmp_path / "w.txt"
    words.write_text("rose\npie\n", "utf-8")
    assert sb.main([str(log), "--language", "en", "--words", str(words)]) == 0
    out = capsys.readouterr().out
    assert "also_an_entity" in out and "content_elsewhere" in out


def test_a_log_with_no_keyword_rows_stops_the_tool(tmp_path):
    log = tmp_path / "empty.json"
    log.write_text(json.dumps({"data": {"keywords": []}}), "utf-8")
    with pytest.raises(SystemExit):
        sb.main([str(log), "--language", "en"])


# ---- write scope (P4, P6, P7, P8) ---------------------------------------------------------------

@pytest.mark.parametrize("bad", ["inj-1\n  - facebook #", "a b", "", "x" * 65, "../x", "a;b"])
def test_a_batch_id_cannot_open_a_new_line(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        sb.append_batch("en", ["permalink"], bad, [], "log")
    assert not (tmp_path / "en.yml").exists()


def test_the_round_trip_compares_the_whole_list(tmp_path, monkeypatch):
    (tmp_path / "en.yml").write_text("stopwords:\n  - alpha\n", "utf-8")
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    # a source string that tried to smuggle an entry is reduced to harmless comment text
    sb.append_batch("en", ["permalink"], "b-1", [], "log\n  - facebook")
    loaded = yaml.safe_load((tmp_path / "en.yml").read_text("utf-8"))["stopwords"]
    assert loaded == ["alpha", "permalink"]


def test_a_symlink_in_the_directory_is_never_written_through(tmp_path, monkeypatch):
    outside = tmp_path / "outside.yml"
    outside.write_text("stopwords:\n  - keep\n", "utf-8")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "en.yml").symlink_to(outside)
    monkeypatch.setattr(sb, "EXTRA_DIR", extra)
    with pytest.raises(SystemExit):
        sb.append_batch("en", ["permalink"], "b-1", [], "log")
    assert outside.read_text("utf-8") == "stopwords:\n  - keep\n"


@pytest.mark.parametrize("name", ["con", "nul", "aux", "com1", "lpt9"])
def test_a_windows_device_name_is_not_a_language_code(tmp_path, monkeypatch, name):
    monkeypatch.setattr(sb, "EXTRA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        sb.append_batch(name, ["permalink"], "b-1", [], "log")
    assert not list(tmp_path.glob(f"{name}.yml"))


def test_main_refuses_a_path_as_language_before_reading_anything(tmp_path):
    with pytest.raises(SystemExit):
        sb.main([str(tmp_path / "no-such-log.json"), "--language", "../x"])


def test_json_report_is_confined_to_a_json_file_outside_configs(tmp_path):
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": LOG}}), "utf-8")
    for bad in (tmp_path / "r.txt", ROOT / "configs" / "stopwords_extra" / "en.json"):
        with pytest.raises(SystemExit):
            sb.main([str(log), "--language", "en", "--json", str(bad)])
    ok = tmp_path / "report.json"
    assert sb.main([str(log), "--language", "en", "--json", str(ok)]) == 0
    assert json.loads(ok.read_text("utf-8"))["language"] == "en"


def test_ring_members_are_keyed_like_the_word_they_are_compared_with(monkeypatch):
    from src.analytics import equivalence

    class _Ring:
        members = (("en", "Y\u2019all"), ("de", "Fl\u00fcchtling"))

    monkeypatch.setattr(equivalence, "shipped_rings", lambda: [_Ring()])
    _hidden, ring = _REAL_APP_CONTEXT("en")
    assert sb.norm("y'all") in ring and sb.norm("flüchtling") in ring


def test_long_evidence_lists_say_how_many_more_there_are(tmp_path, capsys):
    rows = [_kw("shared", "en", 50, sources=9)] + [_kw("shared", lang, 40) for lang in ("de", "fr", "es", "it", "pt", "nl")]
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"data": {"keywords": rows}}), "utf-8")
    words = tmp_path / "w.txt"
    words.write_text("shared\n", "utf-8")
    assert sb.main([str(log), "--language", "en", "--words", str(words)]) == 0
    assert "and 2 more" in capsys.readouterr().out

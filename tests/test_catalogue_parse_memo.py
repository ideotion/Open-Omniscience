"""Each catalogue is parsed once per start-up, the parse runs with the garbage collector paused, and nothing it hands out can corrupt the next reader.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

A boot read seven catalogue files and parsed 18 documents of them in one lifespan call (29 on a plaintext launch): the seeder, the
law seed and the curated-domain set the qualification stamp builds each parsed the same text. Two changes, both in
``src/ingest/seed_sources.py``:

* ``_load_safe_yaml`` runs the parse inside ``_gc_paused()``, a COUNTED pause (the collector is process-global and the web
  server's threads allocate during a parse), restored on every exit and left off if the process had it off;
* ``_parsed_catalogue`` keeps one parse per sha256 of the TEXT until ``forget_parsed_catalogues()`` ends start-up, and
  ``load_sources_from_yaml`` / ``law.catalog._read_catalog_yaml`` hand out COPIES.

What these tests pin is what the quicker form could get wrong: a collector left off, a stale parse served after an edit, a reader
writing into the held tree (the next reader would then seed from a changed catalogue), a held tree that outlives start-up, and a
first install that differs from the unchanged tree's in any column.
"""

from __future__ import annotations

import ast
import copy
import gc
import threading
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.api.main as api_main
import src.ingest.seed_sources as ss
import src.law.catalog as law_catalog
from src.database.models import Base, Source


@pytest.fixture(autouse=True)
def _open_memo(monkeypatch):
    """A fresh, open memo for each test (and the real one restored after): other tests close it by running the start-up."""
    monkeypatch.setattr(ss, "_PARSED", {})
    yield
    assert not ss._GC_HOLDERS, "a test left a collector pause registered"
    gc.enable()


def _spy(monkeypatch):
    """Count parses by text, through both module names that reach the shared loader."""
    seen: list[str] = []
    real = ss._load_safe_yaml

    def spy(text: str):
        seen.append(text)
        return real(text)

    monkeypatch.setattr(ss, "_load_safe_yaml", spy)
    monkeypatch.setattr(law_catalog, "_load_safe_yaml", spy)
    return seen


def _catalogue(tmp_path: Path, name: str = "c.yml", **extra) -> Path:
    body = {
        "sources": [{"name": "A", "domain": "a.example", "tags": ["news", "x"], "rss_url": "https://a.example/f"}],
        "documents": [{"url": "https://a.example/law", "jurisdiction": "FR", "verification": {"status": "fetched", "notes": ["n"]}}],
        **extra,
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


# --- (a) the collector pause --------------------------------------------------------------------------------------------------


def test_the_collector_is_back_on_after_a_parse_and_after_a_failed_one():
    assert gc.isenabled()
    ss._load_safe_yaml("sources: []\n")
    assert gc.isenabled()
    with pytest.raises(yaml.YAMLError):
        ss._load_safe_yaml("sources: [unclosed\n")
    assert gc.isenabled() and not ss._GC_HOLDERS


def test_the_collector_is_off_while_a_parse_runs():
    seen: list[bool] = []
    real = ss._YAML_LOADER

    class Loader(real):  # type: ignore[valid-type, misc]
        def get_single_data(self):
            seen.append(gc.isenabled())
            return super().get_single_data()

    ss._YAML_LOADER, saved = Loader, ss._YAML_LOADER
    try:
        ss._load_safe_yaml("sources: []\n")
    finally:
        ss._YAML_LOADER = saved
    assert seen == [False] and gc.isenabled()


def test_a_process_that_had_the_collector_off_keeps_it_off():
    gc.disable()
    try:
        ss._load_safe_yaml("sources: []\n")
        assert not gc.isenabled(), "a parse switched on a collector the process had switched off"
    finally:
        gc.enable()


def test_two_overlapping_pauses_leave_the_collector_on_only_when_both_are_over():
    first_in, second_done, release = threading.Event(), threading.Event(), threading.Event()
    states: dict[str, bool] = {}

    def first():
        with ss._gc_paused():
            first_in.set()
            second_done.wait(5)
            states["after_second_left"] = gc.isenabled()
            release.wait(5)

    t = threading.Thread(target=first)
    t.start()
    assert first_in.wait(5)
    with ss._gc_paused():
        pass
    second_done.set()
    states["still_held_by_first"] = not gc.isenabled()
    release.set()
    t.join(5)
    assert states == {"after_second_left": False, "still_held_by_first": True}, states
    assert gc.isenabled() and not ss._GC_HOLDERS


def test_an_interrupt_between_registering_and_switching_leaves_the_collector_on(monkeypatch):
    """R171: the pause registers itself before it switches the collector off, so a ``finally`` that runs in between still
    releases it. Red without that order: the collector stayed off for the life of the process."""

    real_disable = gc.disable

    def switched_off_then_interrupted():
        real_disable()
        raise KeyboardInterrupt

    monkeypatch.setattr(gc, "disable", switched_off_then_interrupted)
    with pytest.raises(KeyboardInterrupt), ss._gc_paused():
        pytest.fail("the body must not run")
    monkeypatch.undo()
    assert gc.isenabled() and not ss._GC_HOLDERS


# --- (b) one parse per catalogue ----------------------------------------------------------------------------------------------


def test_the_same_text_is_parsed_once_whoever_asks(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    path = _catalogue(tmp_path)
    ss.load_sources_from_yaml(path)
    ss.load_sources_from_yaml(path)
    law_catalog._read_catalog_yaml(path)       # the law reader and the source reader share one parse of one text
    law_catalog._read_catalog_yaml(path)
    assert len(seen) == 1, f"{len(seen)} parses of one text"


def test_an_edit_of_the_same_size_is_parsed_afresh(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    path = _catalogue(tmp_path)
    assert ss.load_sources_from_yaml(path)[0]["domain"] == "a.example"
    path.write_text(path.read_text(encoding="utf-8").replace("a.example", "b.example"), encoding="utf-8")   # same length
    assert ss.load_sources_from_yaml(path)[0]["domain"] == "b.example"
    assert len(seen) == 2


def test_a_failed_parse_is_not_held(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    bad = tmp_path / "bad.yml"
    bad.write_text("sources: [unclosed\n", encoding="utf-8")
    for _ in range(2):
        with pytest.raises(yaml.YAMLError):
            ss.load_sources_from_yaml(bad)
    assert len(seen) == 2 and ss._PARSED == {}


def test_what_a_reader_changes_is_never_seen_by_the_next_one(tmp_path):
    path = _catalogue(tmp_path)
    first = ss.load_sources_from_yaml(path)
    first[0]["_provenance"] = "changed"
    first[0]["name"] = "changed"
    first.append({"name": "extra", "domain": "extra.example"})
    again = ss.load_sources_from_yaml(path)
    assert [(s["name"], s.get("_provenance")) for s in again] == [("A", None)]

    law_a = law_catalog._read_catalog_yaml(path)
    law_a["sources"][0]["tags"].append("changed")                  # a NESTED write through the law reader
    law_a["documents"][0]["verification"]["notes"].append("changed")
    law_a["documents"][0]["verification"]["status"] = "changed"
    law_b = law_catalog._read_catalog_yaml(path)
    assert law_b["sources"][0]["tags"] == ["news", "x"]
    assert law_b["documents"][0]["verification"] == {"status": "fetched", "notes": ["n"]}


def test_start_up_dropping_the_parses_means_later_reads_are_not_held(tmp_path, monkeypatch):
    seen = _spy(monkeypatch)
    path = _catalogue(tmp_path)
    ss.load_sources_from_yaml(path)
    assert len(ss._PARSED) == 1
    ss.forget_parsed_catalogues()
    assert ss._PARSED is None
    ss.load_sources_from_yaml(path)
    ss.load_sources_from_yaml(path)
    assert ss._PARSED is None and len(seen) == 3, "a read after start-up must parse, and must not re-grow the held tree"


def test_the_start_up_upkeep_ends_by_dropping_the_parses():
    text = Path(api_main.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "_run_startup_upkeep")
    body = ast.get_source_segment(text, fn) or ""
    assert body.count("forget_parsed_catalogues()") == 1
    assert body.index("forget_parsed_catalogues()") > body.index("seed_default_sources(session)")
    # the last statements of the function: the drop, then the "started" line
    last, started = fn.body[-2:], fn.body[-1]
    assert ast.get_source_segment(text, last[0]) == "forget_parsed_catalogues()"
    assert (ast.get_source_segment(text, started) or "").startswith('logger.info(f"Open Omniscience API')


# --- the whole start-up pass: parse count, the held tree untouched, the rows unchanged ----------------------------------------


def _start_up_pass(session):
    """The seeding block of ``_run_startup_upkeep``, in its order: every reader of every catalogue."""
    from src.catalog.provenance import ensure_channel_tags
    from src.catalog.qualification import stamp_curated_catalog
    from src.catalog.qualification_overlay import apply_overlay

    ss.seed_default_sources(session)
    law_catalog.seed_legal_sources(session)
    law_catalog.register_documents(session)
    ensure_channel_tags(session)
    apply_overlay(session)
    stamp_curated_catalog(session)


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)()


_VOLATILE = {"id", "created_at", "updated_at", "qualified_at", "last_checked_at", "added_at"}


def _rows(session):
    cols = [c.key for c in Source.__table__.columns if c.key not in _VOLATILE]
    return sorted(tuple(repr(getattr(r, k)) for k in cols) for r in session.query(Source))


def test_a_first_install_parses_each_text_once_leaves_the_held_tree_untouched_and_writes_the_same_rows(monkeypatch):
    seen = _spy(monkeypatch)
    memo_session = _fresh_session()
    _start_up_pass(memo_session)
    texts = list(seen)
    assert len(texts) == len(set(texts)), f"{len(texts) - len(set(texts))} text(s) parsed more than once in one start-up pass"
    assert len(texts) >= 5, "the shipped catalogues were not read at all"

    # NESTED values are shared with the held tree: no reader may have written into it. Parse every held text again, apart.
    for text in texts:
        assert ss._PARSED[ss.hashlib.sha256(text.encode("utf-8")).hexdigest()] == ss._load_safe_yaml(text), (
            "a reader wrote into the held parse"
        )
    # (that comparison is the shallow-copy decision of load_sources_from_yaml: it holds for the seeder, the law seed, the
    # channel tags, the overlay and the curated stamp. A fourth reader that writes a nested value fails HERE.)
    rows_with_memo = _rows(memo_session)

    # The unchanged tree: no memo at all, every reader parses for itself.
    monkeypatch.setattr(ss, "_PARSED", None)
    plain_session = _fresh_session()
    _start_up_pass(plain_session)
    assert rows_with_memo == _rows(plain_session), "the rows differ from what parsing every time writes"
    assert len(rows_with_memo) > 1000


def test_the_held_tree_is_what_the_pure_parser_reads(tmp_path):
    """The memo returns the SAME objects a plain parse would: pinned on the shipped files by value and type."""
    for path in (ss.DEFAULT_SOURCES_PATH, ss.LEGAL_SOURCES_PATH):
        text = Path(path).read_text(encoding="utf-8")
        held = ss._parsed_catalogue(text)
        assert held == yaml.safe_load(text)
        assert copy.deepcopy(held) == held

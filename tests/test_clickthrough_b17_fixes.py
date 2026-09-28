"""Batch B17 of the 2026-09-26 delegated click-through, pinned: the tail. A Library tile
keeps the window it was switched to (T1); one language switch fetches the Trends windows
once (T2); a user calendar's event is named by its calendar (T3); the Bulletin Review's
counts are one frame chosen by the count (T4); /tasks writes counts and percents as the
app does (T5); the collection estimate's method sentence travels as a keyed frame (T6);
a duration's unit is keyed on both task managers (T7); the AI store's sizes go through
the one size writer (T8); the reader's density line and mindmap remainder are whole
frames (T9); the top-bar chip's "Collecting x/y…" reaches the screen, keyed (T10); and a
job label that carries a value travels as a frame beside the unchanged English label,
drawn by both task managers (T11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first, in Chromium against a seeded state. CI runs no browser,
so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b17_node_test.js``); what is a contract between two files -- a
server frame and the key that translates it, a listener and the painter it calls -- is
pinned here from the shipped sources and the server's own functions.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    event_listener_bodies,
    function_body,
    page_source,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(key: str) -> None:
    want = sorted(re.findall(r"\{(\w+)\}", key))
    for code, d in _locales().items():
        assert key in d, f"{code}.json has no key {key!r}"
        assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
            f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
        )


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b17_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- T11: a label carrying a value travels as a frame -------------------------------- #

#: Every frame a job label can be sent as. Each must be written VERBATIM in the module
#: that sends it (so a reworded producer fails here) and keyed in all twelve locales.
_FRAMES = {
    "src/api/jobs.py": (
        "{language} Wikipedia — articles dump",
        "{language} Wikipedia — articles dump index",
        "{language} Wikipedia — {kind}",
        "Restoring to {dest}",
        "Backing up to {dest}",
        "Importing {label}",
        "Importing newsletters from {folder}",
        "Paused for a corpus import — importing newsletters from {folder}",
        "Downloading model {model}",
        "Model {model}",
        "Wikipedia page walk — {pages}",
    ),
    "src/api/llm.py": (
        "Summarizing “{title}”",
        "Translating → {language}: “{title}”",
        "Summarizing {n} article(s)",
        "Translating → {language} {n} article(s)",
    ),
    "src/api/ai.py": (
        "Extracting AI keywords · {n} article(s)",
        "AI: {label} · {n} article(s)",
    ),
}


@pytest.mark.parametrize("module,frame", [(m, f) for m, fs in _FRAMES.items() for f in fs])
def test_every_label_frame_is_sent_verbatim_and_keyed_x12(module, frame):
    src = (_ROOT / module).read_text(encoding="utf-8")
    assert f'"{frame}"' in src, f"{module} no longer sends the frame {frame!r}"
    _keyed_everywhere(frame)


def test_no_label_frame_is_sent_that_this_test_does_not_know():
    """The reverse direction: a NEW `label_i18n=` literal added to a producer must be
    listed above (and so keyed), or it ships English into every locale again."""
    known = {f for fs in _FRAMES.values() for f in fs}
    for module in _FRAMES:
        src = (_ROOT / module).read_text(encoding="utf-8")
        for m in re.finditer(r'(?:label_i18n=|_label_frame\(\s*|_translate_label_frame\([^,]+,\s*)"([^"]+)"', src):
            assert m.group(1) in known, f"{module} sends an unlisted label frame {m.group(1)!r}"


def test_a_dump_label_sends_the_edition_as_a_code():
    import src.api.jobs as jobs

    assert jobs._dump_label_frame("fr", "pages-articles-multistream") == {
        "label_i18n": "{language} Wikipedia — articles dump", "label_vars": {"language": "fr"}}
    assert jobs._dump_label_frame("de", "pages-articles-multistream-index")["label_i18n"] == (
        "{language} Wikipedia — articles dump index")
    # A kind the table does not know is carried as data, never dropped.
    odd = jobs._dump_label_frame("ja", "stub-meta-history")
    assert odd == {"label_i18n": "{language} Wikipedia — {kind}",
                   "label_vars": {"language": "ja", "kind": "stub-meta-history"}}
    # The English label is unchanged: it is the API's answer and the busy_with line.
    assert jobs._dump_label("fr", "pages-articles") == "French Wikipedia — articles dump"


def test_a_model_pull_sends_its_frame_beside_the_english_label(monkeypatch):
    pytest.importorskip("fastapi")
    import src.api.jobs as jobs
    import src.llm.pull_queue as pq

    class _Mgr:
        def status(self):
            return {"active": {"model": "llama3:8b", "total": 10, "completed": 4, "percent": 40.0},
                    "queue": ["qwen2:7b"]}

    monkeypatch.setattr(pq, "get_pull_manager", lambda: _Mgr())
    active, queued = jobs._model_pull_jobs()
    assert active["label"] == "Downloading model llama3:8b"
    assert active["label_i18n"] == "Downloading model {model}" and active["label_vars"] == {"model": "llama3:8b"}
    assert queued["label"] == "Model qwen2:7b" and queued["label_vars"] == {"model": "qwen2:7b"}


def test_a_background_task_passes_its_frame_through_the_registry():
    pytest.importorskip("fastapi")
    import src.api.jobs as jobs
    import src.monitoring.tasks as tasks

    tok = tasks.register("llm", "Summarizing 3 article(s)", total=3,
                         label_i18n="Summarizing {n} article(s)", label_vars={"n": 3})
    try:
        row = next(r for r in jobs._task_jobs() if r["id"] == f"task:{tok}")
        assert row["label"] == "Summarizing 3 article(s)"
        assert row["label_i18n"] == "Summarizing {n} article(s)" and row["label_vars"] == {"n": 3}
        # T5: a task's progress is a COUNT and names it; with no unit the in-app window
        # draws a unit-less row as bytes ("3 B / 12 B").
        assert row["progress"]["unit"] == "items"
    finally:
        tasks.finish(tok)
    # A task registered the old way carries no frame, and its label is still a key.
    tok = tasks.register("analytics", "Re-indexing the corpus")
    try:
        row = next(r for r in jobs._task_jobs() if r["id"] == f"task:{tok}")
        assert "label_i18n" not in row
    finally:
        tasks.finish(tok)
    with tasks.track("llm", "x", label_i18n="Summarizing “{title}”", label_vars={"title": "t"}) as tok:
        snap = next(t for t in tasks.snapshot() if t["token"] == tok)
        assert snap["label_i18n"] == "Summarizing “{title}”" and snap["label_vars"] == {"title": "t"}


def test_a_translation_task_names_its_target_by_code_or_not_at_all():
    pytest.importorskip("fastapi")
    from src.api.llm import _translate_label_frame

    assert _translate_label_frame("French", "Translating → {language}: “{title}”", title="t") == {
        "label_i18n": "Translating → {language}: “{title}”", "label_vars": {"language": "fr", "title": "t"}}
    # A free-text target this table cannot map keeps the English label alone.
    assert _translate_label_frame("Klingon", "Translating → {language} {n} article(s)", n=2) == {}


def test_both_task_managers_draw_the_frame():
    core = function_body(read_static("app-core.js"), "_jobRow")
    assert "_jobLabel(j, t)" in core and "esc(t(j.label))" not in core
    tm = page_source("taskmanager.html")
    assert "esc(jobLabel(j))" in tm and "esc(t(j.label))" not in tm


# --- T6: the estimate's method sentence ---------------------------------------------- #

def test_the_estimate_method_is_its_frame_filled(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source
    from src.scheduler.runner import plan_preview
    from src.scheduler.settings import SchedulerSettings

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for i in range(3):
        s.add(Source(name=f"S{i}", domain=f"s{i}.test", rss_url=f"https://s{i}.test/feed.xml",
                     enabled=True, status="qualified", rate_limit_ms=2000))
    s.commit()
    plan = plan_preview(s, SchedulerSettings(), last_result={"sources_processed": 3, "pages_fetched": 4})
    frame = plan["estimate_method_i18n"]
    assert plan["estimate_method_vars"] == {"sources": 3, "delay": 2.0, "fetches": 1.3}
    # The English answer is unchanged, and it is this frame filled.
    assert plan["estimate_method"] == (
        "3 source(s) × ~2.0s politeness delay × ~1.3 fetch(es) each (from the last run) — an "
        "assumption, not a promise; robots crawl-delays can stretch it.")
    assert plan["estimate_method"] == frame.format(sources=3, delay="2.0", fetches="1.3")
    _keyed_everywhere(frame)
    assert "_estimateMethodText(plan, tf)" in function_body(read_static("app-core.js"), "_renderVitals")


# --- T10: the chip's count is composed at paint time --------------------------------- #

def test_the_activity_chip_composes_the_count_and_is_repainted_on_a_switch():
    core = read_static("app-core.js")
    poll = strip_comments(function_body(core, "_pollVitals"))
    assert "activity-label" not in poll, "the poll writes the chip itself again, and the paint overwrites it"
    assert "_bgProgress =" in poll
    assert 'TF("Collecting {done}/{total}…"' in function_body(core, "_paintActivity")
    _keyed_everywhere("Collecting {done}/{total}…")
    bodies = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("_paintActivity()" in b for b in bodies), "a switch leaves the chip in the old language"


# --- T8: the AI store's sizes ------------------------------------------------------ #

def test_the_ai_store_sizes_go_through_the_one_size_writer():
    body = strip_comments(function_body(read_static("app-ai-tools.js"), "loadAiStore"))
    assert "_fmtBytes(n)" in body
    assert "1e9" not in body and "GB)" not in body, "a hand-written GB came back"


# --- the strings ------------------------------------------------------------------ #

@pytest.mark.parametrize("key", [
    "{n} source", "{n} sources", "{n} h", "Loaded-term density", "({n} of {m} word)",
    "({n} of {m} words)", "+ {n} more keyword not shown.", "+ {n} more keywords not shown.",
    # T12: the bulk qualification's tally
    "{n} source qualified", "{n} sources qualified", "{n} source disqualified",
    "{n} sources disqualified", "{n} source with no evidence yet", "{n} sources with no evidence yet",
])
def test_the_new_counted_frames_are_keyed_x12(key):
    _keyed_everywhere(key)


def test_the_qualification_tally_is_counted_frames_not_welded_words():
    """T12: "3 qualifié" -- a number welded to an adjective keyed in the singular."""
    body = strip_comments(function_body(read_static("app-ai-tools.js"), "qualifyBulkStart"))
    assert 't("qualified")' not in body and 't("disqualified")' not in body and 't("no evidence yet")' not in body
    assert '"{n} source qualified", "{n} sources qualified"' in body


def test_russian_and_arabic_many_frames_are_labels():
    """A two-form pair ("{n} article" / "{n} articles") cannot carry Russian's or Arabic's
    plural forms: "4 статей" and "3 مقالاً" are wrong. The many frame is a label and a
    count, grammatical for every number (the house form: "статей: {n}")."""
    loc = _locales()
    for code in ("ru", "ar"):
        for key in ("{n} articles", "{n} sources", "({n} of {m} words)", "+ {n} more keywords not shown."):
            assert re.search(r":\s*\{\w+\}", loc[code][key]), f"{code}: {key!r} = {loc[code][key]!r}"

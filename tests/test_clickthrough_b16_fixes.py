"""Batch B16 of the 2026-09-26 delegated click-through, pinned: the text leftovers earlier
fix batches found beside their own work. The agenda row's sentences as whole frames (V3),
the reader's "Original source:" through the locale's own separator (V4), the Bulletin's
numbered skip reason as a keyed frame (V5), the Review's checkboxes inline (V6), the
seasons' own accuracy (V7), the AI hardware chips keyed (V8), the task manager's System
panel keyed and repainted on a switch (V9), job progress units and labels keyed (V10), a
language switch that no longer fetches for panels never opened and graph views that do
not refetch on a repaint (V11), two welded colons (V13, V14), dead task-manager rules
(V15) and the reader page's numbers through the ruled formatter (V16). V1 and V2 (the
planning index's "Must NOT touch" parser and the scanner's aliases) are pinned in
tests/test_planned_index.py and tests/test_i18n_scanner_coverage.py.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first. CI runs no browser, so the behaviour runs as real,
EXTRACTED code under node (``tests/clickthrough_b16_node_test.js``); what is a contract
between two files (a server sentence and the key that translates it, the markup's
placeholders and the repaint's guard) is pinned here from the shipped sources themselves.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
import subprocess
from datetime import date
from pathlib import Path

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    css_rule,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"


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
        ["node", str(_ROOT / "tests" / "clickthrough_b16_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- V3: the agenda row's sentences are whole frames -------------------------------- #

def test_the_agenda_row_writes_each_sentence_as_one_keyed_frame():
    """"also in 2", "from Nager", "date varies by source: …" were English words glued to a
    number or a name, so no locale could reorder them."""
    body = function_body(read_static("app-agenda.js"), "agRow")
    for frame in ("This event also appears in: {calendars}", "also in {n}", "from {feed}",
                  "date varies by source: {dates}"):
        assert_present(body, f'tfa("{frame}"')
        _keyed_everywhere(frame)
    code = strip_comments(body)
    assert 'T("from"))} ${' not in code, "the provenance pill still glues 'from' to a name"
    assert ">also in ${" not in code and "date varies by source: ${" not in code
    assert_present(body, 'T("official source ↗")')
    for key in ("official source ↗", "Calendar feed(s) this event came from:",
                "Imported calendar folder"):
        _keyed_everywhere(key)


# --- V4: the reader footer's label through the locale's separator ------------------- #

def test_the_reader_footer_label_is_a_frame_the_page_repaints():
    main = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    # The server's anchor sits in the frame's host, which the DOM walker leaves alone.
    assert "<span class='src-orig' data-i18n-dyn>" in main
    reader = read_static("reader.js")
    body = function_body(reader, "paintOrigSource")
    assert_present(body, 'TF("{prefix}: {text}"')
    assert_present(body, 'T("Original source")')
    assert_present(body, "frag.appendChild(a)", why="the server's anchor node is moved, never rebuilt")
    listener = reader[reader.index('document.addEventListener("oo:langchange"'):]
    assert "paintOrigSource();" in listener[:200], "a language switch must repaint the footer"
    for key in ("Original source", "No original (http/https) URL recorded.", "{prefix}: {text}"):
        _keyed_everywhere(key)


# --- V5: the through-time skip reason as a keyed frame ------------------------------ #

def _long_period_section() -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.bulletin import sections
    from src.bulletin.period import resolve_period
    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sections.through_time(Session(engine), resolve_period("yearly", end=date(2026, 8, 1)))


def test_the_long_period_reason_travels_as_a_frame_and_its_numbers():
    from src.bulletin.sections import _ANNIVERSARY_MAX_DAYS, _THROUGH_TIME_SKIP

    out = _long_period_section()
    assert out["skipped_i18n"] == _THROUGH_TIME_SKIP
    assert out["skipped_vars"]["max"] == _ANNIVERSARY_MAX_DAYS
    assert out["skipped_vars"]["days"] > _ANNIVERSARY_MAX_DAYS
    # The English sentence an older reader of the record sees is the frame, filled.
    assert out["skipped"] == _THROUGH_TIME_SKIP.format(**out["skipped_vars"])
    assert "stops being a lens" in out["skipped"]
    _keyed_everywhere(_THROUGH_TIME_SKIP)


def test_the_review_passes_the_frame_through_and_the_panel_fills_it():
    from src.bulletin.review import review_view

    sec = _long_period_section()
    row = review_view({"sections": [sec]})["sections"][0]
    assert row["skipped_i18n"] == sec["skipped_i18n"]
    assert row["skipped_vars"] == sec["skipped_vars"]
    body = function_body(read_static("app-agenda.js"), "_bulRender")
    assert_present(body, "_bulTf(s.skipped_i18n, s.skipped_vars || {})")


def test_the_document_prints_the_reason_in_its_own_language():
    from src.bulletin.i18n import CATALOG_DIR, Translator
    from src.bulletin.render import _skip_reason
    from src.bulletin.sections import _THROUGH_TIME_SKIP

    sec = _long_period_section()
    days = str(sec["skipped_vars"]["days"])
    fr = _skip_reason(sec, Translator("fr"))
    assert fr.startswith("la période couvre " + days + " jours"), fr
    assert "62" in fr and "{" not in fr
    assert _skip_reason(sec, Translator("en")) == sec["skipped"]
    # An older record without the frame keeps its English sentence.
    legacy = {"skipped": sec["skipped"]}
    assert _skip_reason(legacy, Translator("fr")) == sec["skipped"]
    for path in sorted(CATALOG_DIR.glob("*.json")):
        cat = json.loads(path.read_text(encoding="utf-8"))
        assert _THROUGH_TIME_SKIP in cat, f"{path.name} does not translate the frame"


# --- V6: the Review's checkboxes sit inline ---------------------------------------- #

def test_the_review_checkboxes_keep_their_own_size_beside_their_label():
    """app.css gives every input width:100%, so inside the wrapping row the box took a
    line of its own and pushed the section name under it."""
    js = read_static("app-agenda.js")
    assert_present(js, 'const _BUL_CHECK_BOX = "width:auto;flex:none;margin:0;padding:0";')
    assert_present(js, 'const _BUL_CHECK_ROW = "gap:8px;align-items:baseline;flex-wrap:nowrap";')
    body = strip_comments(function_body(js, "_bulRender"))
    boxes = re.findall(r'<input type="checkbox"[^>]*>', body)
    assert len(boxes) == 2, boxes
    for box in boxes:
        assert 'style="${_BUL_CHECK_BOX}"' in box, box


# --- V7: the seasons state their own accuracy -------------------------------------- #

def test_the_seasons_state_what_was_measured_and_no_invented_figure():
    from src.events import astronomy

    acc = astronomy.seasons_for_year(2026)["accuracy"]
    assert acc == astronomy._SEASON_ACCURACY
    assert acc != astronomy._ACCURACY, "the seasons still carry the moon's sentence"
    assert "2 minutes" not in acc and "27.a" in acc and "within 9 s" in acc
    assert "not a general error bound" in acc
    # The "within 9 s" is the 27.a check the suite really runs, and it holds.
    err_s = abs(astronomy._jde_season(1962, "june_solstice") - 2437837.39245) * 86400
    assert err_s < 9, err_s
    _keyed_everywhere(acc)


# --- V8: the AI hardware chips ------------------------------------------------------ #

def test_the_hardware_chips_label_value_and_hovers_are_keyed():
    from src.llm.backend import _CAPABILITY_METHOD

    body = function_body(read_static("app-ai-tools.js"), "_hwChips")
    assert_present(body, 'chip(t("Cores")')
    assert_present(body, 'cap.method ? t(cap.method) : ""')
    assert_absent(body, 'chip("Cores"')
    for key in ("Cores", "detected", "none detected", _CAPABILITY_METHOD,
                "A dedicated GPU was detected, so vLLM can serve here.",
                "No dedicated GPU was found. vLLM needs one; Ollama runs on the CPU."):
        _keyed_everywhere(key)
    # The "overwritten" pill lives in app-backup.js (another batch's file); its key is
    # already there in all twelve.
    _keyed_everywhere("overwritten")


# --- V9: the System panel keyed and repainted -------------------------------------- #

def test_the_vitals_panel_repaints_on_a_switch_from_what_it_holds():
    core = read_static("app-core.js")
    body = strip_comments(function_body(core, "_renderVitals"))
    for label in ("Now collecting", "Pages this run", "Next pass", "Targets",
                  "Estimated duration", "Per-source download rate", "System", "CPU"):
        assert f'esc(t9("{label}"))' in body, label
        _keyed_everywhere(label)
    assert 't9(_phaseTxt || "Collecting…")' in body
    _keyed_everywhere("Collecting…")
    assert "api(" not in function_body(core, "repaintVitalsFromCache")
    boot = read_static("app-boot.js")
    listener = boot[boot.index('document.addEventListener("oo:langchange"'):]
    listener = listener[: listener.index("\n    });") + 8]
    assert "repaintVitalsFromCache()" in listener


# --- V10: job progress units and fixed labels ---------------------------------------- #

def test_the_task_manager_page_names_what_a_count_counts():
    tm = read_static("taskmanager.html")
    body = function_body(tm, "jobRow")
    assert_present(body, "esc(t(j.progress.unit))")
    for unit in ("keywords", "articles", "files", "stages"):
        _keyed_everywhere(unit)


#: The FIXED labels /api/jobs sends (src/api/jobs.py), each read from its source: the page
#: draws t(j.label), and t() is an exact lookup. A label carrying a value ("Importing
#: {label}", "Downloading model {m}") is not a key and is listed in the batch report.
_JOB_BASE_LABELS = (
    "collection pass — collecting articles",
    "collection pass — background tasks (markets · calendars · checks)",
    "collection pass",
    "collection loop (idle)",
    "fetch in flight",
    "background task",
    "Re-indexing the corpus",
    "Quarantining flagged non-article junk",
    "Scanning for non-article junk (dry-run)",
    "Re-indexing search for Arabic, Chinese and Japanese",
    "Backing up (volumes + parity)",
    "Restoring",
    "Finishing the import",
    "Importing",
    "Setting each keyword's language from its mentions",
    "Folding keyword forms into their base form",
)
_TASK_LABELS = (
    "qualifying candidate sources",
    "backfilling a newly-qualified source's archive",
    "refreshing the Home briefing",
    "background housekeeping (markets/calendar/law/discovery)",
)


def _paused(label: str) -> str:
    # jobs.py's own construction of a paused job's label.
    return "Paused for an import — " + label[0].lower() + label[1:]


def test_every_fixed_job_label_is_keyed_everywhere():
    jobs = (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")
    labels = list(_JOB_BASE_LABELS)
    for base in _JOB_BASE_LABELS:
        assert f'"{base}"' in jobs, f"jobs.py no longer sends {base!r}: update this list"
    assert '" + pruning keywords"' in jobs
    labels += ["Re-indexing the corpus + pruning keywords"]
    labels += [_paused(x) for x in ("Re-indexing the corpus", "Re-indexing the corpus + pruning keywords",
                                    "Setting each keyword's language from its mentions",
                                    "Folding keyword forms into their base form")]
    labels += ["Paused for an import — re-indexing search for Arabic, Chinese and Japanese"]
    runner = (_ROOT / "src" / "scheduler" / "runner.py").read_text(encoding="utf-8")
    for label in _TASK_LABELS:
        assert f'"{label}"' in runner, f"runner.py no longer registers {label!r}"
    for label in labels + list(_TASK_LABELS):
        _keyed_everywhere(label)


def _registered_by_the_app(job) -> bool:
    mod = getattr(job._worker, "__module__", None) or ""
    return not mod.split(".")[0].startswith("test")


def test_every_registered_background_job_label_is_keyed_everywhere():
    """The generic background jobs register themselves at import; their labels reach the
    same row, so each is a key."""
    import src.api
    from src.jobs import background

    for mod in pkgutil.iter_modules(src.api.__path__):
        importlib.import_module(f"src.api.{mod.name}")
    # The registry is process-wide, and other test files register throwaway jobs into it
    # ("Reg", "T"): under another file order this read them as app labels and failed on the
    # macOS leg. Only a job whose worker the app's own code defines is a label a user sees.
    labels = sorted({j.label for j in background._REGISTRY.values() if _registered_by_the_app(j)})
    assert len(labels) >= 20, f"the registry looks unpopulated: {labels}"
    for label in labels:
        _keyed_everywhere(label)


# --- V11: a switch never fetches for a panel never opened ---------------------------- #

def test_every_static_placeholder_in_a_repaint_host_is_marked():
    """The keyword repaint re-runs a host's loader when the host has rows. A host's own
    markup "Loading…" is not rows: every such placeholder carries the marker the guard
    reads, or a switch fetches for a panel the reader never opened."""
    from tests.js_source_helper import array_literal

    html = read_static("index.html")
    corpus = read_static("app-corpus.js")
    body = function_body(corpus, "ooKwRepaintOnLangChange")
    assert_present(body, 'host.querySelector(":scope > [data-oo-placeholder]")')
    hosts = re.findall(r'\[\s*"([\w-]+)"\s*,', array_literal(body, "callers"))
    assert len(hosts) >= 8, hosts
    unmarked = []
    for host in hosts:
        m = re.search(r'id="' + re.escape(host) + r'"[^>]*>(<div[^>]*>)', html)
        if m and "Loading" in html[m.end(): m.end() + 40] and "data-oo-placeholder" not in m.group(1):
            unmarked.append(host)
    assert not unmarked, f"static placeholders the guard would count as rows: {unmarked}"
    for host in ("ins-landscape", "fam-list", "famc-list", "trd-windows", "sg-list"):
        assert re.search(r'id="' + host + r'"[^>]*><div class="muted" data-oo-placeholder', html), host


def test_the_graph_views_read_through_the_per_view_cache():
    lib = read_static("app-library.js")
    for fn in ("_libGraphTile", "_libQualificationTile", "_libLanguageTile"):
        body = strip_comments(function_body(lib, fn))
        assert "_libGet(`/api/library/" in body, fn
        assert "await api(`/api/library/" not in body and "api(`/api/library/history" not in body, fn


# --- V13, V14: no colon welded after a label ------------------------------------------ #

def test_the_two_walked_labels_take_the_locales_own_separator():
    welded = re.compile(r't\("([^"]+)"\)\)?\}:[\s<]')
    for name, label in (("app-home.js", "Trending now"), ("app-ai-tools.js", "app folder, not in use")):
        code = strip_comments(read_static(name))
        assert not [m.group(1) for m in welded.finditer(code) if m.group(1) == label], (name, label)
        assert f'ooLabelHtml(esc(t("{label}"))' in code, (name, label)
        _keyed_everywhere(label)


# --- V15: dead task-manager rules --------------------------------------------------- #

def test_the_task_manager_carries_no_rule_for_a_class_nothing_uses():
    tm = read_static("taskmanager.html")
    style = tm[tm.index("<style>"): tm.index("</style>")]
    for cls in ("tm-status", "tm-sbtn", "tm-sel"):
        assert not re.search(r"\." + cls + r"\b", style), f".{cls} is styled but never used"
        rest = tm.replace(style, "")
        assert not re.search(r"class=[\"'][^\"']*\b" + cls + r"\b", rest), f"{cls} is used after all"
    assert 'id="tm-status"' in tm, "the id the dead class rule shadowed stays"
    assert css_rule(style, "body")


# --- V16: the reader page's numbers ------------------------------------------------- #

def test_the_reader_page_formats_counts_with_the_ported_formatter():
    reader = read_static("reader.js")
    assert_present(function_body(reader, "num"), "fmtNum(n == null ? 0 : n, 0)")
    assert "toLocaleString" not in strip_comments(reader)

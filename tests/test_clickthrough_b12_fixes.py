"""Batch B12 of the 2026-09-26 delegated click-through, pinned: consent routing and the
consent popup's host table (X1, X2, X3), the local-AI wording (X4), the Governments
partial-roster refusal (X5), the Quality gates panel (X6), the Library's Database &
storage labels (X7), the Home collection frame (X8), the task-manager page (X9) and the
app-wide ``.vr`` row (X10).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced in Chromium first and measured there after. CI runs no browser,
so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b12_node_test.js``); what is a contract between two files (the
engine's vocabulary and the locale files, the consent table and SECURITY.md) is pinned
here from the shipped sources themselves.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    app_js,
    array_literal,
    assert_absent,
    assert_present,
    css_rule,
    event_listener_bodies,
    function_body,
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
    for code, d in _locales().items():
        assert key in d, f"{code}.json has no key {key!r}"
        want = sorted(re.findall(r"\{(\w+)\}", key))
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
            f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
        )


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b12_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- X1: the task-manager page's Resume -------------------------------------- #


def test_the_task_manager_resume_never_posts_a_download_resume_without_the_popup():
    """The page has no consent popup of its own, so a download resume reads the network
    state and, unless it is ONLINE, goes to the app (``/?resume=<id>``), where
    ``jobResume`` passes the ONE popup. A local job keeps its direct POST."""
    tm = read_static("taskmanager.html")
    assert_present(tm, 'location.href = "/?resume=" + encodeURIComponent(id)')
    assert_present(tm, "if (online !== true)")
    assert_present(tm, "TM.resume(\\'' + esc(j.id) + '\\', true)",
                   why="the local-job Resume must say it is local")
    boot = read_static("app-boot.js")
    body = function_body(boot, "_hydrateResumeHandoff")
    assert_present(body, "jobResume(id)")
    assert_present(body, "/^(dump|osm):./.test(id)")
    # jobResume is the gated path the hand-off relies on: it must still ask first.
    assert_present(function_body(app_js(), "jobResume"), 'ensureOnline(t("Resume a paused download"))')


# --- X2: every consent reason is keyed --------------------------------------- #


def test_no_consent_popup_reason_is_an_english_literal():
    """``ensureOnline(reason)`` prints the reason as the popup's headline. Two call sites
    passed bare English, so the popup named the action in English under every language."""
    js = strip_comments(app_js())
    bare = re.findall(r"ensureOnline\(\s*[\"'`][^\"'`]*[\"'`]", js)
    assert not bare, f"untranslated consent reasons: {bare}"
    assert_present(function_body(js, "fetchStatFigure"), 'ensureOnline(t("Fetch official statistics figures"))')
    assert_present(function_body(js, "pullMailbox"), 'ensureOnline(t("Pull newsletters from your mailbox"))')
    for key in ("Fetch official statistics figures", "Pull newsletters from your mailbox"):
        _keyed_everywhere(key)


# --- X3: the installer's hosts in the consent table -------------------------- #

_SPAWNED = (
    "Part of this lane is programs the app starts — pip, the Hugging Face downloader and "
    "Ollama's own install script, which downloads the Ollama program from ollama.com (and, "
    "for an NVIDIA GPU with no driver, the driver from NVIDIA's and your system's package "
    "servers). The app cannot limit where these programs connect."
)


def _ai_lane() -> dict:
    lanes = json.loads(array_literal(read_static("net-hosts.js"), "OO_NET_LANES"))
    lane = next((x for x in lanes if x.get("id") == "ai"), None)
    assert lane, "no ai lane in net-hosts.js"
    return lane


def test_the_ai_lane_names_the_hosts_the_install_really_reaches():
    """The installer follows GitHub's ``browser_download_url`` (github.com, which then
    redirects to release-assets.githubusercontent.com), and Ollama's own install script
    downloads the program from ollama.com. Both were missing from the table the popup's
    hover reads, so it listed fewer hosts than the lane contacts."""
    hosts = _ai_lane()["hosts"]
    for host in ("api.github.com", "github.com", "release-assets.githubusercontent.com", "ollama.com"):
        assert host in hosts, f"the ai lane does not list {host}: {hosts}"
    doc = (_ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    row = next((ln for ln in doc.splitlines() if ln.startswith("|") and "`ollama.com`" in ln
                and "`github.com`" in ln), None)
    assert row, "SECURITY.md has no host row naming both github.com and ollama.com"


def test_the_hover_says_part_of_the_lane_is_programs_the_app_cannot_limit():
    lane = _ai_lane()
    assert lane.get("spawned") is True
    body = function_body(read_static("app-core.js"), "_laneHostTitle")
    assert_present(body, "if (lane.spawned)")
    assert_present(body, f"t({json.dumps(_SPAWNED, ensure_ascii=False)})")
    _keyed_everywhere(_SPAWNED)
    for code, d in _locales().items():
        # The hostname is a token of the sentence, kept in Latin script in every locale.
        assert re.search(r"(?<![\w.])ollama\.com(?![\w.])", d[_SPAWNED]), f"{code}: the hostname must stay in Latin script"


# --- X4: loopback Ollama is not stopped by airplane mode --------------------- #


def test_the_unavailable_local_model_is_not_blamed_on_airplane_mode(monkeypatch):
    """The kill switch refuses only a non-loopback model address, so an unavailable local
    model means the local AI is not running. Saying "or airplane mode" sent the reader
    online to fix a local problem."""
    from src.api import ai as ai_api
    from src.llm import backend as llm_backend

    class _Down:
        def is_available(self) -> bool:
            return False

    class _Ctx:
        def stopping(self) -> bool:
            return False

        def set_progress(self, **_kw) -> None:
            return None

    saved: list[dict] = []
    monkeypatch.setattr(llm_backend, "get_client_with_name", lambda *a, **k: ("ollama", _Down()))
    monkeypatch.setattr(ai_api, "_save_langdetect_state", lambda tally: saved.append(dict(tally)))
    tally = ai_api._langdetect_worker(_Ctx(), model="m", limit=1, continuous=False)
    assert "airplane" not in tally["reason"].lower(), tally["reason"]
    assert "not running" in tally["reason"], tally["reason"]
    assert saved and saved[-1]["reason"] == tally["reason"]

    ui = function_body(read_static("app-settings.js"), "pollLangDetect")
    assert_present(ui, 't("The local model is unavailable: the local AI is not running.")')
    assert_absent(ui, "airplane mode")
    _keyed_everywhere("The local model is unavailable: the local AI is not running.")
    assert "The local model is unavailable (Ollama down or airplane mode)." not in _locales()["en"]


# --- X5: the partial-roster refusal ------------------------------------------ #


def test_the_refusal_names_the_choice_and_carries_a_code_the_screen_can_translate():
    from src.stats.aggregate import Member, aggregate_indicator
    from src.stats.indicators import indicator_aggregation, indicator_meta

    out = aggregate_indicator(
        indicator=indicator_meta("SP.POP.TOTL"),
        aggregation=indicator_aggregation("SP.POP.TOTL"),
        members=[Member("fr", 68.0), Member("de", 84.0), Member("it", None)],
        weights=None, allow_incomplete=False,
    )
    assert out["strategies"], "no strategies in the refusal"
    for key, res in out["strategies"].items():
        assert res.get("refused_code") == "incomplete", key
        assert res.get("label"), f"{key}: the refused card has no label, so the screen shows the key"
        assert "allow_incomplete" not in res["refused"], res["refused"]
        assert "Compute over the members that did report" in res["refused"]
    gov = read_static("app-gov-law.js")
    body = function_body(gov, "_govGroupHtml")
    assert_present(body, 'r.refused_code === "incomplete"')
    assert_present(body, 'action: t("Compute over the members that did report")')
    assert_present(body, "renderGovGroup(true)\">${esc(t(\"Compute over the members that did report\"))}",
                   why="the frame names the SAME key the button renders")
    frame = re.search(r'_govTf\("(\{missing\} of \{members\} members did not report[^"]+)"', body)
    assert frame, "the refusal frame is not a _govTf key"
    _keyed_everywhere(frame.group(1))


# --- X6: the Quality gates panel --------------------------------------------- #


@pytest.fixture
def _empty_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_every_sentence_the_gates_payload_declares_is_a_key_in_all_twelve(_empty_db):
    """The panel renders the engine's own vocabulary -- the gate questions, verdicts and
    notes, and every tunable's label, unit, impact and floor reason -- so it cannot drift
    from what the engine applies. That vocabulary went out in English under every
    language; now each sentence goes through t() and each is a key, read here from the
    SHIPPED payload rather than from a list that could fall behind it."""
    from src.api import source_management as sm

    payload = sm.qualification_config(db=_empty_db)
    strings: list[str] = []
    for gate in payload["gates"]:
        strings += [gate["question"], gate["verdict"], gate["note"]]
        for row in gate["tunables"]:
            strings += [row[k] for k in ("label", "unit", "impact", "floor_reason") if row.get(k)]
    assert len(strings) > 40, f"the payload shrank to {len(strings)} strings -- the walk is not reading it"
    loc = _locales()
    missing = {code: sorted({s for s in strings if s not in d}) for code, d in loc.items()}
    missing = {c: m for c, m in missing.items() if m}
    assert not missing, f"unkeyed gate vocabulary: {missing}"


def test_the_panel_passes_that_vocabulary_through_the_i18n_engine():
    js = read_static("app-ai-tools.js")
    load = function_body(js, "loadQualificationGates")
    for needle in ("esc(t(g.question))", "esc(t(g.note))",
                   '_qualTf("Verdict: {verdict}", {verdict: t(g.verdict)})',
                   '_qualTfHtml("Collecting now: {n}"',
                   '"Judged so far — qualified: {qualified} · disqualified: {disqualified} · '
                   'not yet judged: {unqualified}"'):
        assert_present(load, needle)
    # The count used to follow a bare adjective ("4 qualifié"), which cannot agree in a
    # language that inflects; the label now precedes its count inside one frame.
    assert_absent(load, '${t("qualified")}')
    tunable = function_body(js, "_qualTunableHtml")
    for needle in ("esc(t(row.label))", "t(row.unit)", ".map((x) => t(x))"):
        assert_present(tunable, needle)
    merge = function_body(js, "_renderOverlayMerge")
    assert_present(merge, 'i.route === "measured here" ? t("this instance") : i.name')
    server = (_ROOT / "src" / "api" / "diagnostics" / "qualification_merge.py").read_text(encoding="utf-8")
    assert '"name": "this instance", "route": "measured here"' in server, (
        "the panel keys this instance's row off the server's route; the two must move together"
    )
    for key in ("Collecting now: {n}", "Verdict: {verdict}", "this instance",
                "Judged so far — qualified: {qualified} · disqualified: {disqualified} · "
                "not yet judged: {unqualified}"):
        _keyed_everywhere(key)


def test_no_inflecting_locale_puts_a_count_before_a_bare_adjective():
    """"4 qualifié": the French singular after a plural count. Checked in every locale
    whose adjective agrees in number or gender: each category is a LABEL before its count."""
    loc = _locales()
    key = ("Judged so far — qualified: {qualified} · disqualified: {disqualified} · "
           "not yet judged: {unqualified}")
    for code in ("fr", "es", "pt", "de", "ru", "ar", "hi", "bn", "id", "ja", "zh"):
        val = loc[code][key]
        for slot in ("{qualified}", "{disqualified}", "{unqualified}"):
            before = val.split(slot)[0].rstrip()
            assert before.endswith((":", "：")), f"{code}: {slot} is not preceded by its label: {val!r}"
    assert "qualifiées : {qualified}" in loc["fr"][key], loc["fr"][key]


# --- X7: Database & storage ---------------------------------------------------- #


def test_the_database_lines_are_keyed_and_repainted_on_a_language_switch():
    lib = read_static("app-library.js")
    paint = function_body(lib, "_paintDbFile")
    assert_present(paint, 'esc(_t("Backend"))')
    assert_present(paint, 'esc(_t("on disk"))')
    load = function_body(lib, "loadDbStats")
    assert_present(load, '_t("No tables yet.")')
    assert_present(load, '_t("Could not load stats:")')
    assert_absent(load, "`Backend <span")
    assert_absent(load, "'<div class=\"muted\">No tables yet.</div>'")
    repaint = function_body(lib, "repaintDbStorageFromCache")
    assert_absent(repaint, "api(", why="a relabel must never re-run the disk walk")
    listeners = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("repaintDbStorageFromCache()" in h for h in listeners), (
        f"{len(listeners)} oo:langchange listener(s), none repaints Database & storage"
    )
    for key in ("Backend", "on disk", "No tables yet.", "Could not load stats:"):
        _keyed_everywhere(key)


# --- X8: Home "Automatic collection" ----------------------------------------- #


def test_home_collection_state_is_one_frame_so_the_colon_is_the_locales():
    # 2026-09-27 re-walk U-10: the state WORD joined the frame (one sentence per state,
    # the pill's edges marked), so French agrees it with 'collecte' -- the frame still
    # owns the colon, which is what this test was written for.
    body = function_body(read_static("app-home.js"), "renderHomeStatus")
    for state in ("running", "stopped"):
        assert_present(body, 'tf("Automatic collection: {pill}' + state
                       + '{endpill}", {pill: "\\u0001", endpill: "\\u0002"})')
    assert_absent(body, 't("Automatic collection")}:')
    for key in ("Automatic collection: {pill}running{endpill}",
                "Automatic collection: {pill}stopped{endpill}"):
        _keyed_everywhere(key)
    assert _locales()["fr"]["Automatic collection: {pill}stopped{endpill}"] == (
        "Collecte automatique : {pill}arrêtée{endpill}"
    )


# --- X9: the task-manager page -------------------------------------------------- #


def test_the_task_manager_follows_a_language_picked_in_another_tab():
    tm = read_static("taskmanager.html")
    m = re.search(r'window\.addEventListener\("storage", function \(e\) \{(.*?)\n  \}\);', tm, re.S)
    assert m, "the task manager has no storage listener"
    assert_present(m.group(1), 'e.key !== "oo.lang"')
    assert_present(m.group(1), "pickLang(e.newValue)")


def test_the_sticky_strips_stack_on_measured_heights():
    """Measured at 375 px: the header scrolls away (it is the app's header.topbar, not
    the old sticky .tm-head the 43/86 px offsets were written for), so scrolled content
    showed through a 43 px band above the summary, and the summary wraps to 64 px, so the
    tabs covered its bottom 21 px."""
    tm = read_static("taskmanager.html")
    summary = css_rule(tm, ".tm-summary").replace(" ", "")
    tabs = css_rule(tm, ".tm-tabs").replace(" ", "")
    assert "position:sticky" in summary and "top:0;" in summary, summary
    assert "top:var(--tm-sum-h" in tabs, tabs
    assert "top:43px" not in summary and "top:86px" not in tabs
    assert_present(tm, "new ResizeObserver(set).observe(sum)")
    assert_present(tm, 'setProperty("--tm-sum-h"')


# --- X10: the .vr row outside the task manager ------------------------------ #


def test_the_vr_row_lays_out_label_and_value_everywhere():
    """The fixity mismatches, the calendar directory and "Your calendars" use ``.vr``,
    whose only rules were scoped to the vitals window and one Settings panel, so their
    label ran into the value with no gap at all."""
    css = read_static("app.css")
    rule = css_rule(css, "\n    .vr").replace(" ", "")
    assert "display:flex" in rule and "justify-content:space-between" in rule, rule
    for src, needle in (("app-settings.js", '`<div class="vr"><span>#${m.id}'),
                        ("app-agenda.js", '<div class="vr">')):
        assert_present(read_static(src), needle)


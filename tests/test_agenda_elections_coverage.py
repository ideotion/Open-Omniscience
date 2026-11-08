"""The Agenda's Elections coverage view: the tier report (#1829) drawn as data.

S06-04 S1 asks for "a coverage report as the artifact": every floor country's tier
state plus the floor's own status. The report rides the network-free
``/api/diagnostics/elections-floor`` answer; this view draws it in the Agenda
(invariant #8: the data itself, beside the calendar it describes). These guards pin
what must not drift: it is a view of the ONE ooSubtabs switch, it reads only the
loopback endpoint, both caveats and the method are drawn visibly (the informed-
consent non-negotiable), every string it draws is keyed in all 12 locales, and a
language switch repaints it without a request.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
AGENDA = (STATIC / "app-agenda.js").read_text(encoding="utf-8")
BOOT = (STATIC / "app-boot.js").read_text(encoding="utf-8")


def _render_fn() -> str:
    start = AGENDA.index("function renderAgendaCoverage(")
    end = AGENDA.index("function agNavToday()", start)
    return AGENDA[start:end]


def test_it_is_a_view_of_the_one_agenda_switch_with_its_own_container():
    nav = HTML.split('id="agenda-views"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="coverage"' in nav
    tab = HTML.split('id="tab-agenda"', 1)[1].split('class="tab-page"', 1)[0]
    assert 'id="agenda-coverage"' in tab and "data-i18n-dyn" in tab.split('id="agenda-coverage"', 1)[1][:60]
    assert 'const isCov = view === "coverage"' in AGENDA
    assert "if (isCov) { renderAgendaCoverage(); return; }" in AGENDA


def test_it_reads_only_the_loopback_report_and_needs_no_consent_gate():
    fn = _render_fn()
    assert 'api("/api/diagnostics/elections-floor")' in fn
    assert "ensureOnline" not in fn and "http" not in fn.replace("/api/", "")


def test_both_caveats_and_the_method_are_drawn_visibly_never_behind_a_toggle():
    fn = _render_fn()
    for needle in ("floor.caveat", "rep.caveat", "rep.method"):
        assert needle in fn, needle
    assert "hidden" not in fn and "<details" not in fn


def test_the_counts_are_the_full_counts_and_there_is_no_score():
    fn = _render_fn()
    assert "counts[k] || 0" in fn  # the chip shows the report's own tally, never the filtered rows
    assert not re.search(r"score|rating|ranking|grade", fn, re.I)


def test_every_string_the_view_draws_is_keyed_in_all_twelve_locales():
    fn = _render_fn() + AGENDA[AGENDA.index("const _AG_COV_STATES"):AGENDA.index("function _agCovRepaint")]
    literals = set(re.findall(r'\bTF?\("((?:[^"\\]|\\.)*)"', fn))
    literals |= set(re.findall(r'\["\w+", "([^"]+)", "[\w-]*"\]', fn))
    button = re.search(r'<button data-tab="coverage" title="([^"]+)">([^<]+)</button>', HTML)
    assert button, "the coverage view's button"
    literals |= {button.group(1), button.group(2)}
    assert len(literals) >= 15
    for path in sorted((STATIC / "locales").glob("*.json")):
        keys = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(s for s in literals if s not in keys)
        assert not missing, f"{path.name}: {missing}"


def test_the_servers_own_sentences_are_keyed_so_they_translate_too():
    from src.api.diagnostics.system import elections_coverage_floor

    out = elections_coverage_floor()
    rep = out["tier_report"]
    served = {out["caveat"], rep["caveat"], rep["method"]}
    served |= {r["reason"] for r in rep["countries"] if r["reason"]}
    served.add("every projection has passed; status unknown")
    for path in sorted((STATIC / "locales").glob("*.json")):
        keys = json.loads(path.read_text(encoding="utf-8"))
        assert served <= set(keys), f"{path.name}: {sorted(served - set(keys))}"


def test_a_language_switch_repaints_it_from_the_held_payload_without_a_request():
    assert '_agCovRepaint === "function") _agCovRepaint()' in BOOT
    start = AGENDA.index("function _agCovRepaint()")
    body = AGENDA[start:AGENDA.index("function agCovFilter", start)]
    assert "api(" not in body and "_agCov.then" in body


def test_the_event_filters_step_aside_in_the_coverage_view():
    """The category, country, tag and subscribed filters narrow calendar EVENTS; the
    report is per floor country and ignores them. Left visible they would read as broken."""
    for fid in ("agenda-cats", "agenda-country", "agenda-tag", "agenda-subonly"):
        i = HTML.index(f'id="{fid}"')
        host = HTML.rindex("<div", 0, HTML.rindex('<label', 0, i) + 1)
        assert 'class="ag-filter"' in HTML[host:i], fid
    assert 'closest(".ag-filter")' in AGENDA and 'host.style.display = isCov ? "none" : ""' in AGENDA


def test_the_renderer_draws_what_the_report_says():
    """Drives renderAgendaCoverage in node: caveats + method drawn, server text escaped,
    filter keeps full counts, a repaint never fetches, the RTL date is isolated, and a
    failure the user never saw is asked again on the way back."""
    proc = subprocess.run(["node", str(ROOT / "tests" / "agenda_coverage_node_test.js")],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "agenda coverage node test: ok" in proc.stdout

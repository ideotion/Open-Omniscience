"""S04-06 S6 — the consented ring load's SURFACE: the gate, the caveat, the refusal.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The module's own suite proves the rate and the refusals in the worker. What can only be
checked here is that the surface in front of it obeys the two invariants this slice
touches: the ONE network consent (#14) sits between the operator and the egress, and the
caveat is on the panel rather than behind a toggle (informed consent by layering).

THE PAIR THAT MATTERS is the button and the endpoint. Invariant #14f was recorded from
exactly this shape going wrong: OpenTimestamps had a gated BUTTON in front of an ungated
ENDPOINT, so anything that did not come through the UI egressed silently. So both halves
are asserted, and asserted separately.
"""

from __future__ import annotations

import json
import pathlib
import re

from src.ingest import activate_kill_switch, clear_kill_switch
from tests.js_source_helper import assert_absent, function_source, read_static

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")


def _panel() -> str:
    """The ring-load panel's markup, sliced at its own <section>."""
    i = _HTML.index('<h2 style="margin-top:0;font-size:13px">Keyword translations')
    start = _HTML.rindex("<section", 0, i)
    return _HTML[start:_HTML.index("</section>", i)]


# --------------------------------------------------------------------------- #
#  The consent gate, on BOTH halves
# --------------------------------------------------------------------------- #
def test_the_load_button_passes_the_one_network_consent():
    """Invariant #14: every offline -> online transition goes through `ensureOnline`.

    The result must be USED, not merely awaited — the recorded `app-ai-tools` defect was
    an `await ensureOnline(...)` whose answer was discarded, which reads in a diff exactly
    like a gate and is none.
    """
    src = function_source(read_static("app-insights.js"), "ringLoadStart")
    assert "ensureOnline(" in src, "the load button egresses without the one consent"
    at = re.search(r"!\s*await\s+ensureOnline\(", src)
    assert at, "ensureOnline's answer is not negated, so it is awaited and discarded:\n" + src
    # PARENS, NOT `[^)]*`: the consent reason is a sentence that CONTAINS parentheses
    # ("(one request every 10 seconds, ...)"), and a character-class regex stops at the
    # first of them — a guard that would fail on the very wording it is guarding.
    i, depth = at.end() - 1, 0
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    tail = src[i + 1:].lstrip()
    assert tail.startswith(") return") or tail.startswith(")) return"), (
        "the consent's answer does not stop the egress — an awaited consent whose result "
        "is discarded is not a gate. It is followed by: " + tail[:80]
    )


def test_the_endpoint_refuses_on_its_own_and_names_the_kill_switch():
    """Invariant #14f, from the OpenTimestamps finding: a gated button in front of an
    ungated endpoint egresses for anyone who did not come through the UI. And #14e's
    corollary: the refusal must NAME airplane mode, or an operator reads a generic
    failure and goes looking at Wikidata for their own setting."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.insights import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    activate_kill_switch()
    try:
        r = client.post("/api/insights/ring-load?limit=1")
    finally:
        clear_kill_switch()
    assert r.status_code == 409, r.text
    assert "airplane mode" in r.json()["detail"].lower(), r.text


def test_the_local_gap_read_is_NOT_gated_and_says_why():
    """The other side of the same rule, which is easy to get wrong in the safe-looking
    direction. Invariant #14e gates a pre-action estimate BECAUSE estimates egress first;
    this one reads the local keyword index, so gating it would ask an operator to consent
    to a request nobody makes. Asserted together with the method string that tells them
    so — an ungated read whose payload did not say it is local would be the same silence
    #14e was written about, pointing the other way."""
    src = function_source(read_static("app-insights.js"), "loadRingGaps")
    assert_absent(src, "ensureOnline",
                  why="the local gap read must not demand consent for a call it never makes")

    # The claim lives in the PAYLOAD the surface renders, so it is read from a real
    # answer rather than from the source: a method string asserted against the code that
    # produces it can only ever agree with itself.
    from src.analytics.ring_loader import gap_summary
    from tests.test_keyword_ring_loader import _sess

    out = gap_summary(_sess())
    assert "No network call was made" in out["method"], out["method"]


# --------------------------------------------------------------------------- #
#  The caveat is on the surface, not behind a toggle
# --------------------------------------------------------------------------- #
def test_the_unreviewed_caveat_is_visible_by_default():
    """The informed-consent non-negotiable: caveats are visible by default and the long
    form is LAYERED into the hover, never hidden behind a calm-UI toggle. Q406 = b removed
    the human review step, so "nobody reviews them" is the caveat this panel owes."""
    panel = _panel()
    caveat = re.search(r'<p class="card-caveat"[^>]*>(.*?)</p>', panel, re.S)
    assert caveat, "the panel carries no visible .card-caveat line:\n" + panel
    text = re.sub(r"<[^>]+>", "", caveat.group(1))
    assert "nobody reviews them" in text, text
    assert "hidden" not in caveat.group(0), "the caveat is inside a hidden block"
    assert "<details" not in panel[: panel.index(caveat.group(0))], (
        "the caveat sits behind a disclosure widget inside the panel"
    )


def test_every_visible_string_on_the_panel_is_keyed_in_all_twelve_locales():
    """A chrome string with no key renders in English for eleven of twelve readers. The
    i18n gates are RATCHETS over the whole tree, so "the gate is green" is never evidence
    that THESE strings are covered — that claim has to be made here."""
    strings = [
        "Keyword translations",
        "— load rings from Wikidata",
        "Concepts to load",
        "Load from Wikidata",
    ]
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    missing = []
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in strings:
            if s not in data:
                missing.append(f"{path.name}: {s!r}")
    assert not missing, "\n  ".join(missing)


def test_the_consent_lane_and_the_panel_name_the_same_host():
    """One host, named in the lane table the consent hover reads and in the code that
    reaches it. A panel that promised a different host than the hover lists would make the
    consent popup wrong about the one thing it exists to say."""
    lanes = read_static("net-hosts.js")
    lane = re.search(r'\{[^{}]*"id":\s*"keyword-rings".*?\}', lanes, re.S)
    assert lane, "no keyword-rings lane in net-hosts.js"
    assert '"www.wikidata.org"' in lane.group(0), lane.group(0)
    assert '"fetcher": true' in lane.group(0), "the lane must declare the ethical fetcher"

    from src.analytics.wikidata_rings import API_ENDPOINT

    assert API_ENDPOINT.startswith("https://www.wikidata.org/"), API_ENDPOINT


def test_the_panel_loads_when_its_advanced_section_opens():
    """The Advanced sections load lazily; a panel nobody wires renders "Loading…" forever.
    Asserted against the loader MAP rather than against a call anywhere in the file, which
    is the difference between "the function is mentioned" and "the section runs it"."""
    shell = read_static("app-shell.js")
    m = re.search(r"keywords:\s*\(\)\s*=>\s*\{(.*?)\},", shell, re.S)
    assert m, "no keywords entry in _ADV_LOADERS"
    assert "loadRingGaps()" in m.group(1), m.group(1)

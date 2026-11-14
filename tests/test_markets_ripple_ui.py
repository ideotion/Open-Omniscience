"""Markets shows the full list of commodity / topic coverage co-movements (Lane M's routes list, R684).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``GET /api/signals/supply-chain-ripple`` had no button: Home showed at most a couple of these pairs as Leads and
the list behind them was reachable by curl only. The behaviour (no fetch until asked, the visible caveat in every
state, keyed empty-state reasons, exact article ids, the stale-reply guard) is driven in node
(``markets_ripple_node_test.js``); this file is its driver plus the static claims.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_MARKETS = (_STATIC / "app-markets.js").read_text(encoding="utf-8")


def test_markets_ripple_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "markets_ripple_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_panel_sits_in_the_commodities_section_and_repaints_on_a_language_switch() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    section = html[html.index('id="tab-markets"') :]
    section = section[: section.index("</section>")]
    assert 'id="mkt-ripple"' in section
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert "paintMktRipple()" in boot


def test_the_scan_is_not_run_on_every_visit() -> None:
    """The correlation scan runs on the reader's click; opening Markets only paints."""
    load = function_source(_MARKETS, "loadMarkets")
    assert "paintMktRipple()" in load and "mktRippleLoad" not in load


def test_every_empty_reason_the_server_sends_has_a_keyed_sentence() -> None:
    server = (_ROOT / "src" / "analytics" / "supply_chain_ripple.py").read_text(encoding="utf-8")
    import re

    notes = set(re.findall(r'_empty\("([^"]+)"\)', server))
    assert notes, "the server's empty notes moved"
    for note in notes:
        assert f'"{note}":' in _MARKETS, f"no keyed sentence for the server note {note!r}"
    en = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "Coverage that moves with a commodity",
            "Coverage moving together, never proof that one causes the other.",
            "Pairs tested: {tests} · shown: {shown} · window: {days} days",
            "No tracked commodity matches a keyword in your corpus yet.",
        ):
            assert key in en and data.get(key), f"{path.name}: {key}"

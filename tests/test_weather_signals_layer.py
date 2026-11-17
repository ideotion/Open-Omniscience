"""The weather-signals layer on Insights > Trends (row 122, register ruling G7: a toggleable layer, OFF by default).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour (off reads nothing, a refused store reads as off, on reads the one local route, off again clears) is run
as real code in ``weather_signals_layer_node_test.js``. Here: the page ships the switch OFF with its caveat visible,
the strings exist in all twelve locales, and the route the layer reads is no longer listed as having no caller.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"

KEYS = (
    "Weather signals",
    "Weather signals: off",
    "Weather signals: on",
    "A separate layer of signals deduced from your articles. Off by default, and never mixed with the keywords above. "
    "Turning it on reads a file on this computer and sends nothing.",
    "A weather signal is deduced from several articles that name a climate event, a place and a time window. It is not "
    "a confirmed event, and no anomaly has been checked against a baseline.",
    "Could not read the weather signals.",
    "No weather signal has been derived yet.",
    "Derived {when} from your articles · {n} signals",
    "Derived from your articles · {n} signals",
    "{n} articles",
    "anomaly not checked",
)


def _trends_section() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index('<section class="panel ins-view" id="ins-trends"')
    return html[start:html.index("</section>", start)]


def test_the_layer_behaves():
    proc = subprocess.run(["node", str(pathlib.Path(__file__).with_name("weather_signals_layer_node_test.js"))],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_page_ships_the_switch_off_with_its_caveat_visible():
    sec = _trends_section()
    m = re.search(r'<button id="trd-wsig-toggle"[^>]*>([^<]*)</button>', sec)
    assert m, "the switch lives on the Trends view"
    tag = m.group(0)
    assert 'role="switch"' in tag and 'aria-checked="false"' in tag, "a switch, shipped off"
    assert m.group(1) == "Weather signals: off"
    assert 'data-on-click="toggleWeatherSignals()"' in tag and "onclick" not in tag.lower().replace("data-on-click", "")
    cav = re.search(r'<p id="trd-wsig-caveat"[^>]*>', sec)
    assert cav and "card-caveat" in cav.group(0), "the caveat is a visible caveat line"
    assert "hidden" not in cav.group(0) and "display:none" not in cav.group(0).replace(" ", "")


def test_every_string_exists_in_all_twelve_locales():
    for path in sorted((STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in KEYS:
            assert key in data and data[key].strip(), f"{path.name}: {key!r}"
            for ph in ("{when}", "{n}"):
                assert data[key].count(ph) == key.count(ph), f"{path.name}: placeholder {ph} in {key!r}"


def test_the_read_is_local_and_the_route_is_no_longer_listed_as_uncalled():
    js = (STATIC / "app-corpus.js").read_text(encoding="utf-8")
    body = js[js.index("async function paintWeatherSignals("):js.index("function setTrendLens(")]
    assert body.count("api(") == 1 and 'api("/api/signals/weather-signals")' in body
    assert body.index("if (!weatherSignalsOn()") < body.index("api("), "off returns before anything is read"
    boot = (STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert "repaintWeatherSignals()" in boot, "a language switch redraws the layer from its last reading"
    tsv = (ROOT / "configs" / "routes_without_ui.tsv").read_text(encoding="utf-8")
    assert not any(line.startswith("GET\t/api/signals/weather-signals\t") for line in tsv.splitlines())

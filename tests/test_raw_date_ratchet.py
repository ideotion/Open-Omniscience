"""Raw ISO-date slices in the UI: a zero-slack ratchet and the helper's behaviour (0.5.1 item 46, R258/R259).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. In a right-to-left page an Arabic letter before an ISO date turns its digits into
Arabic numbers (bidi rule W2) and the hyphen stops joining them, so ``2025-12-14`` is drawn
``14-12-2025``. #1498 fixed the keyed Home card frames; this sweep moved every other place that
puts a date NEXT TO TEXT onto ``ooIsoDate`` / ``ooIsoDateTime`` (app-core.js), which isolates the
date under ``dir=rtl`` and is byte-identical otherwise.

THE RATCHET. Each file's count of ``slice(0, 10)`` / ``slice(0, 16)`` (and substring/substr) must EQUAL
its pin. A new one reddens by file name; a conversion that removes one reddens too until the pin is
lowered in the same change, so the ratchet cannot hold room for a regression (the same shape as
``test_inline_handler_ratchet.py``). What the pinned remainder is, by file:

* a date ALONE in its own table cell (measured monotonic, no text before it): app-ai-tools, app-analysis,
  app-claim, app-settings, investigate, app-map's three timestamp cells;
* a date already isolated by its own element (app-backup's ``dir=ltr`` span);
* computation, not rendering: query-string / range bounds, chart axes, ids, hashes, filenames, array
  windows (app-agenda, app-analysis, app-core, app-corpus, app-diagnostics, app-evidence, app-insights,
  app-markets, ootimeline), the helpers' own slices (app-core), and plain-text export lines (app-analysis; its synthesis.html export too, a saved file
  must not carry invisible isolate characters).

If your slice RENDERS a date in a sentence or a "name · date" line, use ``ooIsoDate`` instead and leave
the pin alone. If it is one of the kinds above, raise the pin by one and say which kind in the commit.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

_PATTERN = re.compile(r"(?:slice|substring|substr)\(\s*0\s*,\s*1[06]\s*\)")

#: file -> number of matches. ZERO SLACK.
_PINS = {
    "app-agenda.js": 1,
    "app-ai-tools.js": 2,
    "app-analysis.js": 8,
    "app-backup.js": 2,
    "app-claim.js": 1,
    "app-core.js": 3,
    "app-corpus.js": 1,
    "app-diagnostics.js": 1,
    "app-evidence.js": 1,
    "app-home.js": 1,
    "app-insights.js": 3,
    "app-living.js": 1,
    "app-map.js": 3,
    "app-markets.js": 6,
    "app-settings.js": 4,
    "investigate.js": 2,
    "ootimeline.js": 1,
    "reader.js": 1,
}


def _files():
    """EVERY script the app serves: all ``*.js`` and ``*.html`` under src/static, vendored libraries
    excluded (third-party code is not ours to pin). Inline ``<script>`` blocks live in the html files."""
    return sorted(
        p for ext in ("*.js", "*.html") for p in _STATIC.rglob(ext) if "vendor" not in p.relative_to(_STATIC).parts
    )


def _counts():
    out = {}
    for p in _files():
        n = len(_PATTERN.findall(p.read_text(encoding="utf-8")))
        if n:
            out[p.name] = n
    return out


def test_every_raw_date_slice_is_accounted_for_and_nothing_holds_room():
    got = _counts()
    assert got == _PINS, (
        "raw date slices changed: a slice that renders a date beside text should be "
        "ooIsoDate(...)/ooIsoDateTime(...) (see this file's docstring); otherwise move the pin. "
        f"files off their pin: { {k: (got.get(k, 0), _PINS.get(k, 0)) for k in set(got) | set(_PINS) if got.get(k, 0) != _PINS.get(k, 0)} }"
    )


def test_the_pattern_finds_what_it_is_meant_to_find():
    for hit in ("x.slice(0, 10)", "x.slice(0,10)", "String(x).slice( 0 , 16 )", "x.substring(0, 10)", "x.substr(0,10)"):
        assert _PATTERN.search(hit), hit
    for miss in ("x.slice(0, 7)", "x.slice(1, 10)", "x.slice(0, 100)", "x.slice(0, 160)"):
        assert not _PATTERN.search(miss), miss


def test_the_helpers_behave_under_both_directions():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oo_iso_date_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_swapped_sites_use_the_helper_and_the_helper_lives_in_the_first_module():
    core = (_STATIC / "app-core.js").read_text(encoding="utf-8")
    assert "function ooIsoDate(" in core and "function ooIsoDateTime(" in core
    assert '"\\u2068" + v + "\\u2069"' in core
    for name in ("app-home.js", "app-analysis.js", "app-claim.js", "app-corpus.js", "app-insights.js",
                 "app-shell.js", "app-living.js"):
        assert "ooIsoDate" in (_STATIC / name).read_text(encoding="utf-8"), name


def test_the_scan_covers_every_served_script_and_page():
    names = {p.relative_to(_STATIC).as_posix() for p in _files()}
    for must in ("app-core.js", "reader.js", "taskmanager.js", "i18n.js", "ooviz.js", "oosky.js", "unlock.js",
                 "data-volume.js", "guis/gallery.js", "index.html", "investigate.html", "taskmanager.html",
                 "unlock.html"):
        assert must in names, must
    assert not any("vendor/" in n for n in names)

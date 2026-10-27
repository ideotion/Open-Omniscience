"""A server enum word is never printed raw where the page can name it (0.5.1, R291).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured first in the Maintenance panel (R289): an Arabic page read «الحالة: done». ``i18n.js`` translates a text
node only when its trimmed value EQUALS a locale key, so a word standing alone in a node is translated for free,
while the same word joined to other text in one node ("done · 453 of 453 articles read", "offline — the network
kill switch is engaged") never matches. The fix for such a word is a closed map through ``t()`` that shows an
unknown word exactly as the server sent it (``_maintStateLabel``, ``_wxVerdictLabel``, ``kwKindLabel``).

THE RATCHET. Each file's count of ``esc(x.state)`` / ``esc(x.status)`` / ``esc(x.kind)`` must EQUAL its pin (zero
slack, the shape of ``test_raw_number_ratchet.py``). A new raw print fails here and forces a decision: key it, or
move the pin AND say below which kind it is. What the pinned remainder is (read, not browser-measured):

* STANDING ALONE in its own node, so the walker translates it when the key exists: app-map.js (dump status pill),
  app-sources.js (``x.status`` pill), investigate.js (a table cell).
* AN IDENTIFIER OR USER-DEFINED OPEN SET, so it is shown as sent on purpose: app-map.js ``e.kind`` (a Wikimedia
  dump file name), reader.js (AI keyword kind, set by a custom prompt), app-home.js (annotation and claim kinds: the
  server accepts any string, the UI's own select offers six that could be mapped later), app-insights.js (``data-kind`` attributes, never drawn), ooversions.js (a CSS class).
* MAPPED THROUGH t() SINCE R291: app-diagnostics.js ``st.state`` of the background-AI line (closed list idle | running | done |
  cancelled | error, tests/test_ai_coordinator_status_line.py); the two that remain there are open sets (``e.kind`` a dump file
  kind, ``k.kind`` a keyword kind).
* OTHER LANES' FILES, NOT CLASSIFIED HERE: app-backup.js, app-settings.js, taskmanager.js. They are pinned so that they cannot grow, not declared correct.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

_RAW = re.compile(r"""esc\(\s*[A-Za-z_][\w.]*\.(?:state|status|kind)\s*\)""")

_PINS = {
    "app-backup.js": 1, "app-diagnostics.js": 2, "app-home.js": 2, "app-insights.js": 2, "app-map.js": 2,
    "app-settings.js": 1, "app-sources.js": 1, "investigate.js": 1, "ooversions.js": 1, "reader.js": 1,
    "taskmanager.js": 2,
}

_VERDICTS = ("robots-disallowed", "robots-unavailable", "offline", "dead-series", "http-error", "refused",
             "unreachable", "fetch-failed", "parse-failed")


def _files():
    return sorted(
        p for ext in ("*.js", "*.html") for p in _STATIC.rglob(ext) if "vendor" not in p.relative_to(_STATIC).parts
    )


def test_every_raw_enum_print_is_accounted_for_and_nothing_holds_room():
    got = {}
    for p in _files():
        n = len(_RAW.findall(p.read_text(encoding="utf-8")))
        if n:
            got[p.relative_to(_STATIC).as_posix()] = n
    assert got == _PINS, (
        "a raw esc(x.state|status|kind) print changed: if the value is a closed set of words, map it through t() "
        "with unknown shown as sent (see this file's docstring); otherwise move the pin and say which kind it is. "
        f"Found: {got}"
    )


def test_the_pattern_finds_what_it_is_meant_to_find():
    for hit in ("esc(st.state)", "${esc(e.status)}", "esc( r.kind )", "esc(a.b.kind)"):
        assert _RAW.search(hit), hit
    for miss in ("esc(_maintStateLabel(st.state, t))", "esc(kwKindLabel(p.kind))", "esc(x.stated)", "esc(t(x.kind))"):
        assert not _RAW.search(miss), miss


def test_the_two_sites_go_through_their_maps():
    home = (_STATIC / "app-home.js").read_text(encoding="utf-8")
    assert "_wxVerdictLabel(d.verdict, t)" in home and "${d.verdict || \"\"}" not in home
    words = re.search(r"const _WX_VERDICT_WORDS = \[(.*?)\];", home, re.S)
    assert words, "the closed verdict set must stay a named constant"
    assert tuple(re.findall(r'"([a-z-]+)"', words.group(1))) == _VERDICTS
    corpus = (_STATIC / "app-corpus.js").read_text(encoding="utf-8")
    assert "esc(kwKindLabel(p.kind))" in corpus and "esc(p.kind)" not in corpus


def test_every_word_the_maps_use_has_a_translation_in_all_twelve_locales():
    files = sorted((_STATIC / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        loc = json.loads(f.read_text(encoding="utf-8"))
        for key in _VERDICTS + ("downloading",):
            assert loc.get(key), (f.stem, key)


def test_every_import_report_kind_has_a_translation_in_all_twelve_locales():
    """app-backup.js prints an import-history row's ``kind`` alone in a node, so the i18n walker translates it only
    if the word is a locale key (R291). That ``kind`` is the PREFIX OF THE REPORT'S FILE NAME
    (``import_reports.list_import_reports``: ``p.stem.split("-", 1)[0]``), and the prefix is the first argument
    of every ``persist_import_report("<kind>", ...)`` call. It is NOT the import queue's ``KINDS`` (corpus, legacy,
    blobs, newsletters), which never become a file-name prefix (found by the Opus read of #1540)."""
    seen = set()
    for p in (_ROOT / "src").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        seen.update(re.findall(r"""persist_import_report\(\s*["']([a-z]+)["']""", text))
    assert seen == {"restore", "newsletter", "incomplete"}, (
        "a new import-report writer appeared: key its kind in all 12 locales and add it here. Found: " f"{sorted(seen)}"
    )
    for f in sorted((_STATIC / "locales").glob("*.json")):
        loc = json.loads(f.read_text(encoding="utf-8"))
        for key in sorted(seen):
            assert loc.get(key), (f.stem, key)


def test_the_label_functions_behave():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "raw_token_labels_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout

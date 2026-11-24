"""Why the six unlock.js lines stay on the frozen-renderer list (row 367, Plan's ruling).

``configs/i18n_frozen_renderers.txt`` keeps ``unlock.js dlCheck``, ``dlContinue``, ``dlRestartRequired``, ``go``, ``tick``
and ``waitReadyThenEnter``: they write translated words once, and nothing on the lock page could ask them to redraw.
That is safe only while the lock page changes language ONCE, in the first-launch language step, before any of those
six has drawn anything: it has no language switcher, and its one ``setLang`` is inside ``pickLanguage``. If either
fact changes, those lines freeze in the wrong language and must be held through ooLive like the app's own.
"""

from __future__ import annotations

import pathlib
import re

_STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "unlock.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "unlock.html").read_text(encoding="utf-8")


def _body(name: str) -> str:
    at = _JS.index("function " + name + "(")
    start = _JS.index("{", _JS.index(")", at))
    depth = 0
    for i in range(start, len(_JS)):
        depth += {"{": 1, "}": -1}.get(_JS[i], 0)
        if depth == 0:
            return _JS[start : i + 1]
    raise AssertionError(name + " has no end")


def test_the_lock_page_sets_its_language_only_in_the_first_launch_step():
    assert len(re.findall(r"\bsetLang\(", _JS)) == 1, (
        "unlock.js may set the language in one place only"
    )
    assert "setLang" in _body("pickLanguage"), "and that place is the first-launch language step"
    # ... reached only from the language step's own buttons, and that step only from the first-launch branch, before the
    # six lines can draw (they draw after the passphrase).
    assert len(re.findall(r"\bpickLanguage\(", _JS)) == 2, (
        "pickLanguage is declared and called once"
    )
    assert "pickLanguage(" in _body("showLanguageStep"), "its one caller is the language step"
    calls = [
        line
        for line in _JS.splitlines()
        if re.search(r"\bshowLanguageStep\(\)", line) and "function " not in line
    ]
    assert len(calls) == 1 and '"fresh"' in calls[0], (
        "the language step opens only on a first launch"
    )
    assert "oo:langchange" not in _JS, (
        "a lock page that listens for a switch must hold its lines through ooLive"
    )


def test_the_lock_page_has_no_language_switcher():
    for switcher in ("oo-lang-select", "lang-switch", "lang-menu"):
        assert f'id="{switcher}"' not in _HTML, (
            switcher + " on the lock page would leave the six unlock.js lines frozen"
        )


def test_the_six_lines_are_still_the_ones_this_reason_covers():
    listed = (
        pathlib.Path(__file__).resolve().parents[1] / "configs" / "i18n_frozen_renderers.txt"
    ).read_text(encoding="utf-8")
    rows = sorted(line.split()[1] for line in listed.splitlines() if line.startswith("unlock.js "))
    assert rows == [
        "dlCheck",
        "dlContinue",
        "dlRestartRequired",
        "go",
        "tick",
        "waitReadyThenEnter",
    ]
    assert "tests/test_unlock_language_once.py" in listed, (
        "the list names the test that pins why these lines stay"
    )

"""The background-AI status line prints no raw job word (R291).

``_paintAiCoordinator`` printed the job's state (``done`` / ``cancelled`` / ``error``) as the server sent it, the worker's own
English line without its keyed frame, and that English line beside the translated "paused — your batch is running" pill. The
keys for the three words already existed in all twelve locales; the code never asked for them. The renderer is driven in node
(``tests/ai_coordinator_state_node_test.js``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

_ROOT = Path(__file__).resolve().parent.parent
_JS = (_ROOT / "src" / "static" / "app-diagnostics.js").read_text(encoding="utf-8")
_PAINT = function_source(_JS, "_paintAiCoordinator")
_LOCALES = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))


def test_the_renderer_behaves():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ai_coordinator_state_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_state_words_are_asked_for_by_literal_key_in_every_locale():
    """The string scan reads literal ``t("...")`` calls: a lookup by variable would hide the three words from it."""
    body = _PAINT
    for word in ("done", "cancelled", "error"):
        assert f't("{word}")' in body, f"{word} is not asked for by a literal key"
    assert len(_LOCALES) == 12
    for path in _LOCALES:
        table = json.loads(path.read_text(encoding="utf-8"))
        for word in ("done", "cancelled", "error"):
            assert table.get(word), f"{path.name} has no {word!r}"
            if path.stem != "en" and (path.stem, word) != ("es", "error"):  # Spanish spells it the same
                assert table[word] != word, f"{path.name}: {word!r} is the English word"


def test_no_raw_state_or_detail_is_pushed_into_the_line():
    body = _PAINT
    assert "parts.push(esc(st.state))" not in body
    assert "esc(st.detail ||" not in body
    assert "_framedText(st.detail, st.detail_i18n, st.detail_vars, t)" in body

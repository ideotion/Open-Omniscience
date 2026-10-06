"""The AI backend <select> must not be flipped back by a panel load that started before the pick.

Found by the 2026-10-06 row-I sweep (``ai-backend-select`` read ``REVERTED`` in 9 of the first 31
width x theme runs): ``loadAiBackendPanel`` writes the select from the server's stored value, so a
load already in flight when the operator picks holds the OLD value and set the select back for the
seconds until the load that follows the save corrected it. Measured in Chromium with the first
``/api/llm/backend`` answer delayed 1.2 s and the stored value ``auto``: pick ``ollama`` -> the select
read ``auto`` for about two seconds before this change and held ``ollama`` after it. Each pick now
counts, and a load writes the select only when no pick happened since it started.
"""

from __future__ import annotations

from tests.js_source_helper import function_body, read_static

SRC = read_static("app-ai-tools.js")


def test_a_load_that_started_before_the_pick_does_not_write_the_select():
    assert "let _aiBackendPicks = 0;" in SRC
    assert "const picksAtStart = _aiBackendPicks;" in SRC
    assert 'if (sel && picksAtStart === _aiBackendPicks) sel.value = b.stored_override || "auto";' in SRC


def test_every_pick_is_counted_before_its_save_and_reload():
    body = function_body(SRC, "setAiBackend")
    assert "_aiBackendPicks++;" in body
    assert body.index("_aiBackendPicks++;") < body.index("/api/settings"), (
        "counted before the PUT, so the reload that follows the save still writes the select"
    )


def test_the_counter_name_is_declared_once():
    assert SRC.count("let _aiBackendPicks") == 1

"""Row 164 and row 165 (2026-11-18): the task manager's AI pill, and the last two bucket accents.

The task manager painted an offline AI as plain ``pill warn``: colour alone, no diagonal bar,
no hover naming the reason, against the app's own red-plus-bar pill. Both pages now take the
class and hover from ONE function, ``ooAiPillState`` in ``ai-pill.js`` (reused, not copied).
The node suite runs that function; these checks pin that both pages actually call it.

Row 165: the ``context`` and ``investigate`` briefing buckets had no left-border accent while
the other six did.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def test_the_ai_pill_node_suite():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ai_pill_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_both_pages_load_the_shared_module_before_their_painter():
    for page, painter in (("index.html", "app-ai-tools.js"), ("taskmanager.html", "taskmanager.js")):
        html = _read(page)
        shared = html.find('<script src="/static/ai-pill.js"></script>')
        own = html.find(f'<script src="/static/{painter}"></script>')
        assert shared != -1, f"{page} does not load ai-pill.js"
        assert own != -1 and shared < own, f"{page} loads ai-pill.js after {painter}"
    assert '"/static/ai-pill.js"' in _read("sw.js")


def test_both_painters_call_the_shared_function_and_keep_no_copy():
    app = _read("app-ai-tools.js")
    tm = _read("taskmanager.js")
    assert "ooAiPillState(" in app
    assert "ooAiPillState(" in tm
    # The offline vocabulary lives in ai-pill.js only: neither page re-types it.
    for src in (app, tm):
        assert "AI is offline — click to start it" not in src
        assert "neither Ollama nor vLLM answers" not in src
    # The task manager's pill code no longer paints the bare colour-only class.
    pill_code = function_body(tm, "paintLlm") + function_body(tm, "loadLlm")
    assert '"pill warn"' not in pill_code and '"pill ok"' not in pill_code


def test_task_manager_pill_repaints_on_language_switch_and_owns_its_hover():
    tm = _read("taskmanager.js")
    assert 'addEventListener("oo:langchange", paintLlm)' in tm
    assert re.search(r'<span id="llm"[^>]*data-i18n-dyn', _read("taskmanager.html"))
    # The click lands on Settings > AI, which the app's #models alias opens.
    assert 'location.href = "/#models"' in tm
    assert 'name === "models"' in _read("app-shell.js")


def test_every_briefing_bucket_has_a_left_border_accent():
    css = _read("app.css")
    producers = (_ROOT / "src" / "briefing" / "producers.py").read_text(encoding="utf-8")
    buckets = set(re.findall(r'bucket[=:]\s*"([a-z]+)"', producers))
    assert {"context", "investigate"} <= buckets
    for b in sorted(buckets):
        assert re.search(r"\.card\.bk-" + b + r"\b[^{]*\{[^}]*border-left:3px", css), b

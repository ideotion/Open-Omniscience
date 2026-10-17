"""The vLLM log notes node test, plus the source guard that the panel renders them."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, function_body

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_log_notes_say_what_the_view_leaves_out():
    r = subprocess.run(["node", str(_ROOT / "tests" / "vllm_log_notes_node_test.js")], capture_output=True, text=True, timeout=60, cwd=str(_ROOT))
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "VLLM LOG NOTES OK" in r.stdout


def test_the_server_log_panel_renders_the_notes():
    panel = function_body(app_js(), "loadVllmStatusPanel")
    assert "vllmLogNotes(s)" in panel and "notes +" in panel, "the notes must reach the page, not only exist as a function"

"""The omnibar's instant rung: driven in node, and the few source facts that must not drift.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SHELL = (_ROOT / "src" / "static" / "app-shell.js").read_text(encoding="utf-8")
_LOCALES = _ROOT / "src" / "static" / "locales"
_STRINGS = (
    "Newest added titles — not ranked, text not searched",
    "more titles match — type more to narrow",
    "The title index does not cover older articles yet — build it",
    "Building the instant title index",
)


def test_instant_rung_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "instant_rung_node_test.js")], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_the_request_is_a_local_read_with_no_debounce_and_no_api_wrapper() -> None:
    """A debounce would put back the wait the rung exists to remove, and api() would count an aborted
    keystroke as 'server unreachable'. It must stay a plain, abortable, same-origin fetch."""
    from tests.js_source_helper import function_source

    body = function_source(_SHELL, "_instFetch")
    assert "setTimeout" not in body and "await api(" not in body
    assert "/api/search/instant" in body and "AbortController" in body and "_instSeq" in body


def test_every_string_the_rung_shows_is_in_all_twelve_locales() -> None:
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _STRINGS:
            assert data.get(s), f"{path.name} is missing {s!r}"

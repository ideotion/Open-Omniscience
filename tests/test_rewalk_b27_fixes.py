"""Batch B27 of the 2026-09-27 delegated re-walk, pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each row was reproduced first in Chromium against an encrypted seeded state (en, fr, ar,
zh; 1440 and 375 px). CI runs no browser, so the behaviour runs as real, EXTRACTED code
under node (``tests/rewalk_b27_node_test.js``): the consent popup's bounded disclosure
(M-14), the walker's ancestor opt-out for attributes (T-2), the guided-setup theme chips
(U-11), the AI pill's keyed hover (T-7), Help's debounced find (H-3), the retired Mode row
(T-5), /tasks' health dot (T-6) and its theme (T-8). The airplane coach (O-1) is pinned by
tests/test_net_coach_placement.py and tests/net_coach_place_node_test.js. What is a
contract between two files is pinned here: the checkbox rule every Settings panel leans on
(H-5, S-8) and the Help list's titles and blurbs, which the server sends in English and the
walker translates only if each is a key (H-4).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _docs_registry() -> dict[str, dict[str, str]]:
    """The Help reader's allow-list, read from src/api/main.py's source (no app import)."""
    tree = ast.parse((_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        target: ast.expr
        rhs: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            target, rhs = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, rhs = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "_DOCS" and rhs is not None:
            value = ast.literal_eval(rhs)
            assert isinstance(value, dict) and value, "_DOCS is no longer a literal dict"
            return value
    raise AssertionError("_DOCS not found in src/api/main.py -- re-anchor this test")


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "rewalk_b27_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks ok" in proc.stdout


# --- H-5, S-8: a tick box keeps its native size ---------------------------------------- #

def test_every_checkbox_keeps_its_native_size():
    """The generic ``input`` rule gives every field width:100%. For a checkbox inside a flex
    label that became a share of the row (#discovery-external 150-209 px, its label pushed
    into three narrow lines) and inside a wrapping row a line of its own (#qual-enabled
    188-233 px). Rows patched one at a time with style="width:auto" kept the class alive, so
    the rule that fixes it is the one every checkbox and radio already matches."""
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    rule = re.search(r'input\[type="checkbox"\],\s*input\[type="radio"\]\s*\{([^}]*)\}', css)
    assert rule, "the checkbox/radio rule moved -- re-anchor this test"
    body = re.sub(r"\s+", "", rule.group(1))
    assert "width:auto" in body, "checkboxes inherit width:100% again (re-walk H-5, S-8)"
    assert "flex:00auto" in body, "a checkbox in a flex row can grow or shrink again (re-walk H-5, S-8)"


# --- H-4: the Help list is in the reader's language ------------------------------------ #

@pytest.mark.parametrize("field", ["title", "blurb"])
def test_every_help_document_title_and_blurb_is_keyed_in_all_twelve(field):
    """/api/docs sends each document's title and blurb in English and the Help list renders
    them as text for the DOM walker, which translates a string only when it IS a key. Nine
    of the ten titles and all ten blurbs were not, so the list stayed English in every
    language (re-walk H-4)."""
    docs = _docs_registry()
    missing = []
    for code, d in _locales().items():
        for slug, entry in docs.items():
            text = entry[field]
            if not (d.get(text) or "").strip():
                missing.append(f"{code}: {slug}.{field} {text!r}")
    assert not missing, "untranslated Help list entries:\n" + "\n".join(missing)


@pytest.mark.parametrize("key", [
    "No AI backend is reachable right now — neither Ollama nor vLLM answers.",       # T-7
    "This machine's network interfaces could not be read just now.",                  # M-14
    "Could not read whether these are on:",                                           # M-14's honest fallback
])
def test_the_sentences_this_batch_relies_on_are_keyed_in_all_twelve(key):
    for code, d in _locales().items():
        assert (d.get(key) or "").strip(), f"{code}.json has no value for {key!r}"

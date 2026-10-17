"""The History tab's pass-counts line: its words, its locale keys, and the vocabulary it shares with the scheduler.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/scheduler/runner.py`` writes ``pass_counts`` into the record of a run that raised, with a basis word from a closed
vocabulary (``pass_returned``, ``pass_raised``, ``not_reported``); ``src/static/taskmanager.js`` reads it and shows the basis on
the row. The two are separate languages joined by three strings, so a rename on one side would turn every row into "not
reported" with nothing failing. The node test (``tests/history_pass_counts_node_test.js``) pins what the page draws; this file
pins what it draws it FROM, and that every phrase it uses ships in all twelve languages.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.scheduler import runner
from tests.js_source_helper import function_source

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_JS = (_ROOT / "src" / "static" / "taskmanager.js").read_text(encoding="utf-8")

#: Every phrase the line puts on the page (the English source string is the key).
_KEYS = (
    "Sources processed",
    "Articles stored",
    "{a} of {b}",
    "not reported",
    "The pass stopped part-way",
    "The pass finished, a later step failed",
    "The pass raised an error. The counts are every source whose worker had returned a result by the time it ended, including sources a pool finished after the first failure surfaced. Counts only, read from the run record.",
    "The pass ran to its end and a later step failed. The counts are the pass’s own. Counts only, read from the run record.",
    "The failure came before the pass counted anything, so these figures are unknown. They are not zero.",
    "The failure came before anything was counted",
)


def test_the_page_reads_the_words_the_scheduler_writes():
    """The three basis words in the page are the scheduler's constants, and the page knows no others."""
    assert runner.COUNTS_PARTIAL == "pass_raised"
    assert runner.COUNTS_COMPLETE == "pass_returned"
    assert runner.COUNTS_UNREPORTED == "not_reported"
    seen = set(re.findall(r'"(pass_raised|pass_returned|not_reported)"', _JS))
    assert seen == {runner.COUNTS_PARTIAL, runner.COUNTS_COMPLETE, runner.COUNTS_UNREPORTED}, seen
    assert 'r.pass_counts' in _JS, "renderHistory no longer reads the member the scheduler writes"


@pytest.mark.parametrize("code", sorted(p.stem for p in _LOCALES.glob("*.json")))
def test_every_phrase_of_the_line_ships_in_every_language(code):
    data = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    for key in _KEYS:
        assert key in data and str(data[key]).strip(), f"{code}: {key[:50]!r} is missing"
    assert "{a}" in data["{a} of {b}"] and "{b}" in data["{a} of {b}"], f"{code}: the frame lost a placeholder"
    for key in _KEYS[6:9]:
        # The unknown-is-not-zero statement and the method are the caveat: a language may not drop them to an empty shell.
        assert len(str(data[key])) >= 20, f"{code}: the hover text is a stub"


def test_every_phrase_the_page_uses_is_one_the_locale_test_knows():
    """A phrase added to the line without a locale key would fall back to English in eleven languages."""
    body = "\n".join(function_source(_JS, name) for name in ("passBasisText", "passBasisTitle", "passCountsLine"))
    used = set(re.findall(r't\("((?:[^"\\]|\\.)*)"\)', body)) | set(re.findall(r'tf\("((?:[^"\\]|\\.)*)"', body))
    used = {u.replace('\\"', '"') for u in used}
    assert used <= set(_KEYS), sorted(used - set(_KEYS))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_node_suite_passes():
    p = subprocess.run(["node", str(_ROOT / "tests" / "history_pass_counts_node_test.js")], capture_output=True, text=True, timeout=120, cwd=_ROOT)
    assert p.returncode == 0, p.stdout + p.stderr

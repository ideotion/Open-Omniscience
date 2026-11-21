"""No renderer builds an SVG ``<title>`` child: every hover rides a title ATTRIBUTE (row 269, invariant #17).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The shared #oo-tip bubble marks ``[title]`` elements and opens on hover and touch long-press. An SVG
``<title>`` child reaches only a mouse, so on a phone a chart mark's count, date or name could not be read
at all. Row 268 moved the map markers (app-map.js); this row moved the charts in app-library.js,
app-insights.js, app-corpus.js and app-analysis.js, and this guard keeps every script under src/static from
building one again. The one ``<title>`` allowed is the document title of a standalone HTML page the app
writes for export, which is a page's name, not a hover.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import strip_comments

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"

# A standalone HTML document's own name (app-analysis.js writes the Synthesis export as a whole page).
_DOCUMENT_TITLE = re.compile(r"<head>(?:<meta [^>]*>)*<title>")


def _scripts() -> dict[str, str]:
    return {
        str(p.relative_to(STATIC)): p.read_text(encoding="utf-8")
        for p in sorted(STATIC.rglob("*.js"))
        if "vendor" not in p.parts
    }


def test_no_script_builds_an_svg_title_child():
    offenders = []
    for name, src in _scripts().items():
        for n, line in enumerate(src.splitlines(), 1):
            if not strip_comments(line).strip():  # a whole-line comment explaining the rule is not a renderer
                continue
            if "<title>" in line and not _DOCUMENT_TITLE.search(line):
                offenders.append(f"{name}:{n}: {line.strip()[:120]}")
    assert not offenders, (
        "an SVG <title> child reaches only a mouse; use a title attribute:\n" + "\n".join(offenders)
    )


def test_the_guard_still_sees_what_it_guards():
    # A guard that reads no files passes forever: the renderers it covers must be among what it read.
    names = set(_scripts())
    for script in (
        "app-map.js",
        "app-library.js",
        "app-insights.js",
        "app-corpus.js",
        "app-analysis.js",
    ):
        assert script in names, script
    assert _DOCUMENT_TITLE.search((STATIC / "app-analysis.js").read_text(encoding="utf-8")), (
        "the one allowed <title> (the Synthesis export page) moved: re-check the exemption"
    )


def test_the_chart_hovers_run_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run(
        [node, str(ROOT / "tests" / "chart_hover_titles_r269_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr

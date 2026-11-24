"""Row 394: a superseded analysis run never writes, on its failure path too.

The behaviour of loadAnalysis, _anLoadArtFacets and loadAnContext is driven in
``an_superseded_failure_node_test.js``; this file is its driver. The lazy renderers that
node test does not drive are pinned here at the source: each catch that writes first
checks that its run, key or commodity still owns the panel.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from tests.js_source_helper import function_body, read_static

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_superseded_failures_never_write_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "an_superseded_failure_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "an_superseded_failure_node_test.js: OK" in proc.stdout


def _catch_heads(body: str) -> list[str]:
    return [
        m.group(1).strip()[:160] for m in re.finditer(r"catch \(\w+\) \{([^\n]*\n?[^\n]*)", body)
    ]


def test_every_writing_catch_in_loadanalysis_checks_its_run_first():
    body = function_body(read_static("app-analysis.js"), "loadAnalysis")
    heads = [h for h in _catch_heads(body) if "never block a render" not in h]
    assert len(heads) >= 6, heads
    for head in heads:
        assert head.startswith("if (stale()) return;"), head


def test_the_lazy_renderers_check_ownership_before_writing_a_failure():
    an = read_static("app-analysis.js")
    guards = {
        "renderAnTrend": "if (_anTrend.key !== key) return;",
        "renderAnRelated": "if (_anRelated.key !== key) return;",
        "renderAnCompetitive": "if (_anLastParams && _anLastParams.toString() !== key) return;",
        "renderAnPrice": "if (stale()) return;",
    }
    for fn, guard in guards.items():
        heads = _catch_heads(function_body(an, fn))
        assert heads, fn
        assert heads[-1].startswith(guard), (fn, heads[-1])
    trend = function_body(an, "renderAnTrend")
    # both awaits in the trend are followed by the key check, not only the catch
    assert trend.count("if (_anTrend.key !== key) return;") >= 3
    price = function_body(an, "renderAnPrice")
    assert "_anCommodity !== c" in price

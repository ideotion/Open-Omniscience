"""Audit finding 2026-07-17: agMonthShift() (src/static/app.js) drove the agenda's
Month/Trimester/Semester navigation, but its old wraparound only handled a plain
+-1 step correctly -- it hardcoded "month 12" / "month 1" on any underflow/
overflow regardless of how far the shift actually went, so Trimester (+-3) and
Semester (+-6) navigation landed on the WRONG month whenever the shift crossed a
year boundary (e.g. February 2026 stepped back 3 months landed on "December 2025"
instead of the correct "November 2025").

This test EXTRACTS the real function body from app.js and runs it through node,
so a regression in the shipped source is caught -- not a hand-reimplementation
that could silently drift from the real code (the established pattern in
tests/test_ooviz.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "src" / "static" / "app.js"

# (start year, start month, shift in months, expected [year, month])
_CASES = [
    (2026, 2, -3, [2025, 11]),   # Trimester back across a year boundary
    (2026, 10, 6, [2027, 4]),    # Semester forward across a year boundary
    (2026, 12, 1, [2027, 1]),    # plain +1, December -> January (the old-working case)
    (2026, 1, -1, [2025, 12]),   # plain -1, January -> December (the old-working case)
    (2026, 6, 0, [2026, 6]),     # no-op
    (2026, 1, -12, [2025, 1]),   # exactly a year back
    (2026, 1, -13, [2024, 12]),  # more than a year back
]


def _extract_agMonthShift() -> str:
    src = _APP_JS.read_text(encoding="utf-8")
    start = src.index("function agMonthShift(d) {")
    end = src.index("\n    }\n", start) + len("\n    }\n")
    return src[start:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_agMonthShift_source_exists_and_is_extractable():
    fn = _extract_agMonthShift()
    assert "AGV.y = y; AGV.m = m;" in fn


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_agMonthShift_handles_multi_month_shifts_across_year_boundaries(tmp_path):
    fn = _extract_agMonthShift()
    harness = f"""
const results = [];
for (const [y0, m0, d] of {json.dumps([[y, m, d] for y, m, d, _ in _CASES])}) {{
  const AGV = {{ y: y0, m: m0, day: null }};
  function renderAgenda() {{}} // no-op stub -- the function calls this at the end
  {fn}
  agMonthShift(d);
  results.push([AGV.y, AGV.m]);
}}
console.log(JSON.stringify(results));
"""
    script = tmp_path / "agMonthShift_test.js"
    script.write_text(harness, encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    got = json.loads(r.stdout.strip())
    expected = [c[3] for c in _CASES]
    assert got == expected, f"got {got}, expected {expected}"

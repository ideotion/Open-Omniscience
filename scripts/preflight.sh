#!/usr/bin/env bash
# preflight.sh — run the CI `test` job's BLOCKING gates locally BEFORE pushing.
#
# Mirrors .github/workflows/ci.yml (the `test` job) with the EXACT commands. Written after the
# 2026-07-15 opt-tail CI cycle, where three gates each masked the next (ruff-blocking F401 hid a
# pytest break hid a mypy-ratchet rise), costing ~9 min per CI round to peel one layer. Running
# all three locally in one pass collapses that cycle.
#
# The mypy ratchet is DETERMINISTIC only with the pinned mypy + the full extras installed:
#     pip install -e ".[analysis,dev,segmentation,pdf,ocr]"
# Two things do NOT reproduce in every sandbox and are NOT the app's fault: sqlcipher3 (the
# encrypted-store tests) and real sockets/package-metadata. Those pytest failures pass in CI —
# this script surfaces the pytest summary but never auto-passes/fails on it (you judge a red
# against that known-environmental set). ruff + mypy DO reproduce cleanly and are the hard gates.
#
# Usage:  bash scripts/preflight.sh            # ruff + mypy (fast, clean pass/fail)
#         bash scripts/preflight.sh --tests    # also run the full pytest suite (advisory)
#
# Open Omniscience - Global Intelligence Platform for Investigative Journalism
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
set -u
cd "$(dirname "$0")/.." || exit 2

run_tests=0
[ "${1:-}" = "--tests" ] && run_tests=1

# The baseline is single-sourced from ci.yml so this never drifts from the gate it mirrors.
baseline=$(grep -oE 'MYPY_BASELINE: *"[0-9]+"' .github/workflows/ci.yml 2>/dev/null | grep -oE '[0-9]+' | head -1)
baseline=${baseline:-127}
fail=0
hr() { printf -- '----------------------------------------------------------------------\n'; }

hr
echo "GATE 1/3 — ruff correctness (BLOCKING)"
echo "  ruff check --select=F,B --extend-ignore=B008 src/ tests/"
if ruff check --select=F,B --extend-ignore=B008 src/ tests/; then
  echo "  PASS — ruff correctness clean"
else
  echo "  FAIL — ruff correctness reported errors (fix before pushing)"
  fail=1
fi

hr
echo "GATE 2/3 — mypy ratchet (BLOCKING), baseline ${baseline}"
echo "  python -m mypy src/"
mypy_ver=$(python -m mypy --version 2>/dev/null || echo "")
if [ -z "${mypy_ver}" ]; then
  # No mypy → an empty count reads as "0 errors", a FALSE pass. Fail loudly instead: a
  # preflight that green-lights a push when its checker never ran is worse than no gate.
  echo "  mypy MISSING — install it (pip install -e '.[dev]') and activate the venv. Gate SKIPPED, treated as FAIL."
  fail=1
else
# Strip ANSI so the count matches CI (which runs mypy un-coloured under no TTY). BOTH the
# colour SGR codes (\x1b[..m) AND the charset-reset (\x1b(B) mypy emits right after "error:"
# must go — else " error: " (with trailing space) never matches and the count reads 0.
count=$(python -m mypy src/ 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/\x1b(B//g' | grep -c " error: ")
echo "  ${mypy_ver} | errors: ${count} (baseline ${baseline})"
if [ "${count}" -gt "${baseline}" ]; then
  echo "  FAIL — mypy count ROSE above the baseline. New/offending errors (tail):"
  python -m mypy src/ 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/\x1b(B//g' | grep " error: " | tail -25 | sed 's/^/    /'
  echo "    (diff against the base branch to isolate the ones your change added.)"
  fail=1
elif [ "${count}" -lt "${baseline}" ]; then
  echo "  PASS — mypy UNDER the baseline (${count} < ${baseline}); consider lowering MYPY_BASELINE in ci.yml"
else
  echo "  PASS — mypy at the baseline"
fi
fi

hr
echo "GATE 3/3 — pytest (advisory here; the hard gate is CI's full env)"
if [ "${run_tests}" -eq 1 ]; then
  echo "  python -m pytest -q"
  echo "  REVIEW any failures against the known-environmental set BEFORE trusting a red:"
  echo "    sqlcipher3-absent · socket/PermissionError · PackageNotFoundError (metadata) · httpfs egress."
  echo "  A failure OUTSIDE that set is a REAL regression — do not push on it."
  python -m pytest -q
  echo "  (^ pytest result is advisory — this script's exit code reflects the ruff+mypy hard gates only.)"
else
  echo "  SKIPPED — pass --tests to run the full suite (slow; has environmental noise in a bare sandbox)."
fi

hr
if [ "${fail}" -eq 0 ]; then
  echo "PREFLIGHT PASSED — the reproducible hard gates (ruff + mypy) are green. Safe to push."
  echo "  (If you ran --tests, confirm any pytest reds are all environmental first.)"
else
  echo "PREFLIGHT FAILED — fix the FAIL gate(s) above before pushing."
fi
exit "${fail}"

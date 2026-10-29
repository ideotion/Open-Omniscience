#!/usr/bin/env bash
# preflight.sh — run three of the CI `test` job's gates locally BEFORE pushing.
#
# Mirrors .github/workflows/ci.yml (the `test` job): the ruff correctness and mypy commands are the
# job's own, verbatim, and the mypy gate means what the job's means (BLOCKING: any error fails). The
# pytest command is the job's WITHOUT its `-rsfE` flags (`-r` replaces pytest's default `fE`, so the
# job names the skip listing `s` first and `fE` after it, which puts the FAILED and ERROR lines last,
# at the tail of its log): a bare sandbox skips hundreds of tests and that block would bury the
# failures this advisory run is read for, which pytest's default `-rfE` already prints.
# tests/test_ci_pytest_flags_and_preflight.py pins the commands and that one difference.
# NOT run here: the job's other steps (the ruff style ratchet, planned-work index, i18n, migration
# drift, bandit and pip-audit among them); `python scripts/guards_for_diff.py --run` covers the
# style ratchet and the tests a diff picks.
# Written after the 2026-07-15 opt-tail CI cycle, where three gates each masked the next
# (ruff-blocking F401 hid a pytest break hid a mypy-ratchet rise), costing ~9 min per CI round to
# peel one layer. Running all three locally in one pass collapses that cycle.
#
# The mypy gate is DETERMINISTIC only with the pinned mypy + the full extras installed:
#     pip install -e ".[analysis,dev,segmentation,pdf,ocr,geo]"
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
echo "GATE 2/3 — mypy (BLOCKING: any error fails, as in the job)"
echo "  python -m mypy src/"
mypy_ver=$(python -m mypy --version 2>/dev/null || echo "")
if [ -z "${mypy_ver}" ]; then
  # No mypy → an empty count reads as "0 errors", a FALSE pass. Fail loudly instead: a
  # preflight that green-lights a push when its checker never ran is worse than no gate.
  echo "  mypy MISSING — install it (pip install -e '.[dev]') and activate the venv. Gate SKIPPED, treated as FAIL."
  fail=1
else
# Strip ANSI so the lines match what CI prints (mypy runs un-coloured there, under no TTY). BOTH the
# colour SGR codes (\x1b[..m) AND the charset-reset (\x1b(B) mypy emits right after "error:"
# must go — else " error: " (with trailing space) never matches and the count reads 0.
# The gate is mypy's EXIT STATUS, as the job's is: a crash or a config error prints no " error: " line.
mypy_out=$(python -m mypy src/ 2>/dev/null)
mypy_rc=$?
mypy_errors=$(printf '%s\n' "${mypy_out}" | sed 's/\x1b\[[0-9;]*m//g; s/\x1b(B//g' | grep " error: ")
count=$(printf '%s\n' "${mypy_errors}" | grep -c " error: ")
echo "  ${mypy_ver} | exit status: ${mypy_rc} | errors: ${count}"
if [ "${mypy_rc}" -ne 0 ]; then
  echo "  FAIL — mypy exited ${mypy_rc}, and so would the job. Errors (tail; none means it did not get as far as reporting one):"
  [ -n "${mypy_errors}" ] && printf '%s\n' "${mypy_errors}" | tail -25 | sed 's/^/    /'
  echo "    (diff against the base branch to isolate the ones your change added.)"
  fail=1
else
  echo "  PASS — mypy clean"
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
  echo "PREFLIGHT PASSED — the reproducible hard gates (ruff + mypy) are green. The job's other steps were not run (see the header)."
  echo "  (If you ran --tests, confirm any pytest reds are all environmental first.)"
else
  echo "PREFLIGHT FAILED — fix the FAIL gate(s) above before pushing."
fi
exit "${fail}"

"""The restore's stage PLAN — the honest denominator behind "phase N of M".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ruling 2026-07-29 item 17: the number of remaining phases must be visible to
the user. M is NOT a constant — a dry run stops after ``corpus_delta_before`` and a
restore with ``reindex_imported=False`` never runs the ``reindex`` stage — so a
hardcoded denominator would be a fabricated number.

The load-bearing test here is the DRIFT GUARD: the declared plan is compared against
the ``timings.stage(...)`` calls that actually appear in ``run_restore``'s own source,
in order. Without it the plan is a second source of truth that silently rots the first
time someone adds or removes a stage, and the user is shown a confidently wrong
position — the failure mode this project's honesty rules exist to prevent.
"""

import re
from pathlib import Path

from src.backup.merge import (
    _RESTORE_STAGES_ALWAYS,
    _RESTORE_STAGES_COMMIT,
    _stage_pinger,
    restore_stage_plan,
)

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"


def _run_restore_source() -> str:
    """run_restore's body only, so a stage() call in some other function can never
    silently satisfy (or break) this guard. Async-agnostic split, per the project's
    recorded stale-source-anchor lesson."""
    src = _MERGE_PY.read_text(encoding="utf-8")
    parts = re.split(r"\n(?:async )?def run_restore\(", src)
    assert len(parts) == 2, "expected exactly one run_restore definition"
    body = parts[1]
    # Stop at the next top-level def/class so we read ONLY run_restore.
    nxt = re.search(r"\n(?:async )?(?:def|class) ", body)
    return body[: nxt.start()] if nxt else body


def test_the_plan_matches_the_stages_run_restore_actually_walks():
    """DRIFT GUARD: declared plan == the real timings.stage() sequence, in order."""
    body = _run_restore_source()
    actual = re.findall(r'timings\.stage\(\s*"([a-z_]+)"\s*\)', body)
    declared = list(_RESTORE_STAGES_ALWAYS + _RESTORE_STAGES_COMMIT)
    assert actual == declared, (
        "the restore stage plan drifted from run_restore's own timings.stage() calls.\n"
        f"  declared: {declared}\n"
        f"  actual:   {actual}\n"
        "Update _RESTORE_STAGES_ALWAYS/_RESTORE_STAGES_COMMIT in src/backup/merge.py."
    )


def test_a_dry_run_stops_after_the_pre_commit_stages():
    plan = restore_stage_plan(commit=False)
    assert plan == _RESTORE_STAGES_ALWAYS
    assert "swap" not in plan and "reindex" not in plan, "a preview never commits"


def test_a_committing_restore_includes_the_commit_tail():
    plan = restore_stage_plan(commit=True)
    assert plan[: len(_RESTORE_STAGES_ALWAYS)] == _RESTORE_STAGES_ALWAYS
    assert "swap" in plan and "reindex" in plan
    assert len(plan) == len(_RESTORE_STAGES_ALWAYS) + len(_RESTORE_STAGES_COMMIT)


def test_skipping_the_reindex_shrinks_the_denominator():
    """The whole reason M cannot be a constant: the same commit=True restore walks a
    DIFFERENT number of stages depending on this flag, so a fixed denominator would
    mis-report the position for every stage after it."""
    with_reindex = restore_stage_plan(commit=True, reindex_imported=True)
    without = restore_stage_plan(commit=True, reindex_imported=False)
    assert "reindex" in with_reindex and "reindex" not in without
    assert len(without) == len(with_reindex) - 1
    # ...and every stage BEFORE the reindex keeps its position (only the tail shifts).
    cut = with_reindex.index("reindex")
    assert without[:cut] == with_reindex[:cut]


def test_the_pinger_reports_one_based_positions_against_the_real_plan():
    plan = restore_stage_plan(commit=True)
    seen: list[tuple[str, int, int]] = []
    ping = _stage_pinger(plan, lambda name, i, total: seen.append((name, i, total)))
    assert ping is not None
    for name in plan:
        ping(name)
    assert [s[0] for s in seen] == list(plan)
    assert [s[1] for s in seen] == list(range(1, len(plan) + 1))
    assert {s[2] for s in seen} == {len(plan)}


def test_an_unplanned_stage_reports_zero_never_a_guessed_position():
    """An honest unknown. A plausible-but-wrong index would be worse than a visibly
    wrong 0, because nobody would notice it."""
    seen: list[tuple[str, int, int]] = []
    ping = _stage_pinger(("a", "b"), lambda name, i, total: seen.append((name, i, total)))
    assert ping is not None
    ping("something_new")
    assert seen == [("something_new", 0, 2)]


def test_the_pinger_is_none_when_there_is_no_sink():
    """StageTimings treats None as "no on_start", so the no-callback path stays
    byte-identical to before this feature existed."""
    assert _stage_pinger(restore_stage_plan(commit=True), None) is None

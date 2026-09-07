"""The restore's stage PLAN — the honest denominator behind "phase N of M".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ruling 2026-07-29 item 17: the number of remaining phases must be visible to
the user. M is NOT a constant — a dry run stops BEFORE ``corpus_delta_before``, a HELD
item (checkpoint interval K) stops after its own report row, and a restore with
``reindex_imported=False`` never runs the ``reindex`` stage — so a hardcoded
denominator would be a fabricated number.

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
    _RESTORE_STAGES_HELD,
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
    # In SOURCE order: the held branch's two stages sit between the dry-run return
    # and the commit path, so the three declared tuples concatenate to exactly what
    # run_restore walks top to bottom. A stage that appears twice in the source (both
    # paths run side_files_and_custody and report_json_write) therefore appears twice
    # here too — which is what makes the guard able to see a held branch that has
    # silently lost one of them.
    declared = list(_RESTORE_STAGES_ALWAYS + _RESTORE_STAGES_HELD + _RESTORE_STAGES_COMMIT)
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
    # The preview returns ABOVE corpus_delta_before, so counting it would make M one
    # larger than the number of stages the preview walks — a small fabricated
    # denominator, fixed 2026-09-07 by moving that stage into the commit tuple.
    assert "corpus_delta_before" not in plan


def test_a_held_item_stops_after_its_own_report_row():
    """The checkpoint-interval-K plan. A held item does the two stages that cannot
    wait for the checkpoint and none of the ones that can, so its denominator is
    genuinely shorter — and it must NOT contain the swap, which is the whole point."""
    plan = restore_stage_plan(commit=True, hold_after_merge=True)
    assert plan == _RESTORE_STAGES_ALWAYS + _RESTORE_STAGES_HELD
    for absent in ("swap", "reindex", "pre_restore_snapshot", "corpus_delta_before"):
        assert absent not in plan, f"a held item never reaches {absent}"
    # ...and it is strictly shorter than the committing plan, which is what makes the
    # position honest rather than a constant reused across two different walks.
    assert len(plan) < len(restore_stage_plan(commit=True))


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

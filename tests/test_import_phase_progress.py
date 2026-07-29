"""Per-phase ETA + the honest "phase N of M" counter (field report 2026-07-29).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE BUG: importing a 50,000-article backup quoted "~4000 min left". ``_uxPoll``
captured ONE ``startMs`` for the whole job while ``view.frac`` resets to ~0 at every
phase boundary, so the rule of three charged the entire preceding job (verify +
reassemble + merge) against the fraction of the phase that had just begun — an
over-estimate of roughly 5-15x early in the re-index.

THE RULING (item 17): the estimate is per PHASE, and the number of remaining phases
must be visible.

Backend behaviour is pinned by driving the real manager; the frontend half is pinned
at source level (no browser in-session), with every assertion SCOPED to the function
body it claims to guard — a whole-file substring search can pass against both the code
it means to reject and the code it means to accept (the project's recorded lesson).
"""

import re
import time
from pathlib import Path

from src.backup.volume_job import _RESTORE_MANAGER_PHASES, VolumeBackupManager

_APP_JS = Path(__file__).resolve().parents[1] / "src" / "static" / "app.js"


def _wait(mgr: VolumeBackupManager, timeout: float = 5.0) -> dict:
    t0 = time.time()
    while mgr.status()["running"] and time.time() - t0 < timeout:
        time.sleep(0.01)
    return mgr.status()


def _js_function(name: str) -> str:
    """One function's body, so an assertion cannot be satisfied by an identical
    fragment somewhere else in an 18k-line file."""
    src = _APP_JS.read_text(encoding="utf-8")
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n    (?:async )?function ", src[start + 10 :])
    return src[start : start + 10 + nxt.start()] if nxt else src[start:]


# --------------------------------------------------------------------------- #
#  backend: the position rides every progress ping
# --------------------------------------------------------------------------- #
def test_restore_stage_pings_carry_their_position_offset_by_the_manager_phases(
    tmp_path, monkeypatch
):
    import src.backup.artifact as artifact_mod
    import src.backup.merge as merge_mod
    import src.scheduler.runner as sched_mod

    def fake_run_restore(staged, *, commit, allow_unverified, stage_progress_cb=None, **kw):
        # run_restore reports 1-based positions within ITS OWN plan; the manager owns
        # the phases that ran before it and must offset them.
        assert stage_progress_cb is not None
        stage_progress_cb("swap", 9, 16)
        return {"committed": True}

    monkeypatch.setattr(sched_mod, "pause_for_exclusive_operation", lambda timeout=10.0: True)
    monkeypatch.setattr(sched_mod, "resume_after_exclusive_operation", lambda was_paused: None)
    monkeypatch.setattr(merge_mod, "run_restore", fake_run_restore)
    monkeypatch.setattr(artifact_mod, "read_volume_backup", lambda *a, **k: object())
    monkeypatch.setattr(artifact_mod, "cleanup_staging", lambda staged: None)

    src = tmp_path / "src"
    src.mkdir()
    mgr = VolumeBackupManager()
    seen: list[dict] = []
    real = mgr._on_prog
    mgr._on_prog = lambda p: (seen.append(dict(p)), real(p))

    mgr.start_restore(str(src), "pw")
    assert _wait(mgr)["state"] == "done"

    offset = len(_RESTORE_MANAGER_PHASES)
    swap = [p for p in seen if p.get("phase") == "swap"]
    assert swap, "the swap stage must ping with its position"
    assert swap[-1]["phase_index"] == offset + 9
    assert swap[-1]["phase_total"] == offset + 16


def test_the_position_survives_the_two_longest_phases(tmp_path, monkeypatch):
    """The merge and the re-index are exactly the phases a user waits on. Their
    fine-grained pings must carry the position too, or the counter blanks out for
    the whole of them — which is when it matters most."""
    import src.backup.artifact as artifact_mod
    import src.backup.merge as merge_mod
    import src.scheduler.runner as sched_mod

    def fake_run_restore(
        staged, *, commit, allow_unverified, progress_cb=None, reindex_progress_cb=None, **kw
    ):
        progress_cb(7, 14, "curation")
        reindex_progress_cb(120, 50000)
        return {"committed": True}

    monkeypatch.setattr(sched_mod, "pause_for_exclusive_operation", lambda timeout=10.0: True)
    monkeypatch.setattr(sched_mod, "resume_after_exclusive_operation", lambda was_paused: None)
    monkeypatch.setattr(merge_mod, "run_restore", fake_run_restore)
    monkeypatch.setattr(artifact_mod, "read_volume_backup", lambda *a, **k: object())
    monkeypatch.setattr(artifact_mod, "cleanup_staging", lambda staged: None)

    src = tmp_path / "src"
    src.mkdir()
    mgr = VolumeBackupManager()
    seen: list[dict] = []
    real = mgr._on_prog
    mgr._on_prog = lambda p: (seen.append(dict(p)), real(p))
    mgr.start_restore(str(src), "pw")
    assert _wait(mgr)["state"] == "done"

    merging = [p for p in seen if p.get("merge_steps")]
    reindexing = [p for p in seen if p.get("reindex_total")]
    assert merging and reindexing
    for p in merging + reindexing:
        assert p.get("phase_index"), "a long phase must still report its position"
        assert p.get("phase_total"), "…and its denominator"
        assert p["phase_index"] <= p["phase_total"]
    # the re-index is later in the plan than the merge — a real ordering, not a guess
    assert reindexing[-1]["phase_index"] > merging[-1]["phase_index"]


def test_the_denominator_is_computed_not_hardcoded():
    """M varies with the flags, so no constant can be right for every restore."""
    from src.backup.merge import restore_stage_plan

    committing = len(_RESTORE_MANAGER_PHASES) + len(restore_stage_plan(commit=True))
    no_reindex = len(_RESTORE_MANAGER_PHASES) + len(
        restore_stage_plan(commit=True, reindex_imported=False)
    )
    preview = len(_RESTORE_MANAGER_PHASES) + len(restore_stage_plan(commit=False))
    assert committing > no_reindex > preview, (
        "three genuinely different totals — a hardcoded M would be wrong for two of them"
    )


# --------------------------------------------------------------------------- #
#  frontend (source-level; browser-unverified per fork-3)
# --------------------------------------------------------------------------- #
def test_uxPoll_rebaselines_the_eta_on_every_phase_change():
    body = _js_function("_uxPoll")
    assert "let etaKey = null" in body and "let etaStart" in body
    assert "if (key !== etaKey) { etaKey = key; etaStart = Date.now(); }" in body, (
        "the ETA baseline must reset when the phase changes"
    )
    assert "_uxRuleOfThree(etaStart, view.frac)" in body
    # The bug being fixed: a single job-wide baseline must be GONE from this function.
    assert "_uxRuleOfThree(startMs" not in body
    assert "const startMs = Date.now();" not in body


def test_progress_view_tags_each_phase_so_the_eta_can_be_scoped():
    body = _js_function("_uxProgressView")
    assert 'phaseKey: "merge"' in body and 'phaseKey: "reindex"' in body, (
        "merge and re-index must be distinct ETA scopes — they are different units at "
        "different rates"
    )


def test_phase_counter_renders_only_a_real_position():
    body = _js_function("_uxPhaseCount")
    assert "p.phase_index" in body and "p.phase_total" in body
    assert "if (!i || !n || i > n) return \"\";" in body, (
        "index 0 (backend could not place the stage) and a nonsensical i>n must render "
        "nothing rather than a fabricated position"
    )
    assert "phase {n} of {total}" in body, "a fixed, keyable template — never a built string"


def test_the_phase_template_is_keyed_in_every_locale():
    """A tf() template only translates if its KEY exists; and adding it to en.json
    alone would redden the --min 100 gate for the other eleven."""
    import json

    loc = _APP_JS.parent / "locales"
    files = sorted(loc.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for f in files:
        obj = json.loads(f.read_text(encoding="utf-8"))
        val = obj.get("phase {n} of {total}")
        assert val, f"{f.name} is missing the phase-count template"
        assert "{n}" in val and "{total}" in val, (
            f"{f.name} dropped a placeholder — it would render a literal brace"
        )

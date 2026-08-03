"""Decompose a run journal into "where did the time actually go".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 2026-08-03 field import was reported as "3h30 to import 650 MB,
and I had to abort it". Every number needed to correct that was already in the run
journal -- and getting them out took an afternoon of hand-arithmetic over
``run-journal-raw.json``:

    all eighteen stages, summed        118.6 s
    total elapsed when killed       11,006.9 s
    => the re-index                 10,888.3 s   98.9% of the import
    ...of which, frozen at exactly
       article 9,000 (= 18 x 500)    8,395.0 s   76.3% of the WHOLE run

The import was not slow. It ran for two minutes and then hung for two hours and
twenty minutes. Nobody should have to compute that by hand to find it out, and the
operator certainly should not: the difference between "slow" and "hung" is the
difference between tuning and a bug hunt, and the journal knew all along.

WHAT IT REFUSES TO SAY. A stall here is a WINDOW IN WHICH A REAL COUNTER DID NOT
MOVE -- never "stuck", which this cannot know. A phase that publishes no counter
(``prepare_staged`` is 54% of a large import and reports only a phase name) is
reported as ``no-counter``, never as stalled: emitting "not moving" for ninety
minutes of healthy work is exactly the fabricated verdict the beat schema was built
to avoid, and the same rule has to hold one level up.

Likewise the CPU during a stall is reported only where it was measured. The child
walk stands down under its own cost budget, and the beats say so; a stall that
cannot say what the workers were doing must say THAT, because "the parent was busy
and the children unmeasured" and "the parent was busy and the children idle" are
different diagnoses and only one of them was observed.
"""

from __future__ import annotations

from typing import Any

#: A run is only interesting as a stall if it sat still for at least this long.
#: Well above a slow batch: the field freeze was 8,395 s, and a healthy 500-article
#: precompute window on the same hardware was ~140 s.
_STALL_MIN_S = 120.0

#: Namespaces whose entries are timed INSIDE another stage, so summing both
#: double-counts. ``merge_step:<name>`` is recorded alongside the ``merge`` stage it
#: sits in; unlike ``prepare_staged:validate`` the prefix is not itself a stage, so
#: it cannot be detected structurally.
_ROLLUP_NAMESPACES = frozenset({"merge_step"})


def _median(vals: list[float]) -> float:
    ordered = sorted(vals)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _stall_windows(beats: list[dict]) -> list[dict]:
    """Maximal runs of consecutive beats over which a REAL counter did not advance.

    Keyed on the counter's own value, not on a ``d_done`` delta: a beat that simply
    did not publish ``done`` must not read as "no progress". Beats whose counter
    CHANGES (a new phase) end the window, because a counter reset is not a stall.
    """
    out: list[dict] = []
    run: list[dict] = []

    def _flush() -> None:
        if len(run) < 2:
            return
        span = (run[-1].get("el_s") or 0) - (run[0].get("el_s") or 0)
        if span < _STALL_MIN_S:
            return
        # What WAS measured while it sat there. Parent CPU is always sampled; child
        # CPU is not, and the difference is the whole diagnosis.
        # PER-BEAT rates, then the median -- never sum/window_span. The child walk
        # measures only SOME beats, so dividing its summed CPU by the FULL window
        # dilutes a real 0.57 cores into 0.12 and understates exactly the signal this
        # exists to surface. That is the same partial-denominator error the runlog
        # aggregate carried, in a different shape; a rate must be divided by the time
        # its own samples cover.
        def _rates(key: str) -> list[float]:
            vals = []
            for prev, cur in zip(run, run[1:], strict=False):
                d = cur.get(key)
                span = (cur.get("el_s") or 0) - (prev.get("el_s") or 0)
                if d is not None and span > 0:
                    vals.append(d / span)
            return vals

        kid = _rates("d_kids_cpu_s")
        cpu = _rates("d_cpu_s")
        entry: dict[str, Any] = {
            "phase": run[-1].get("phase"),
            "counter": run[-1].get("counter"),
            "stuck_at": run[0].get("done"),
            "total": run[-1].get("total"),
            "from_el_s": round(run[0].get("el_s") or 0, 1),
            "to_el_s": round(run[-1].get("el_s") or 0, 1),
            "seconds": round(span, 1),
            "beats": len(run),
        }
        if cpu:
            entry["parent_cores"] = round(_median(cpu), 2)
            entry["parent_samples"] = len(cpu)
        if kid:
            entry["child_cores"] = round(_median(kid), 2)
            entry["child_samples"] = len(kid)
            if len(kid) < len(run) - 1:
                entry["child_partial"] = (
                    f"{len(kid)}/{len(run) - 1} beats measured children; the rate is over "
                    "those beats only, never diluted across the ones that did not"
                )
            entry["children_seen"] = max(
                (b.get("kids_n") for b in run if isinstance(b.get("kids_n"), int)), default=None
            )
            # THE distinction the field run turned on. Both readings are "no progress";
            # only one of them is a deadlock, and they need opposite fixes.
            entry["reading"] = (
                "workers were BUSY and produced nothing -- pathological work, not a deadlock"
                if entry["child_cores"] > 0.05
                else "workers were idle -- consistent with a wedge or with nothing running"
            )
        else:
            entry["children_unmeasured"] = (
                "the child walk stood down for this window, so what the workers were "
                "doing was never sampled -- not the same as idle"
            )
        gate_held = [b for b in run if isinstance(b.get("gate"), dict) and b["gate"].get("held")]
        entry["write_gate_held_in_any_beat"] = bool(gate_held)
        out.append(entry)

    for b in beats:
        if not isinstance(b.get("done"), int):
            _flush()
            run = []
            continue
        if run and (b.get("counter") != run[-1].get("counter") or b["done"] != run[-1]["done"]):
            _flush()
            run = []
        run.append(b)
    _flush()
    return out


def analyse_run(summary: dict, beats: list[dict] | None = None) -> dict:
    """Turn one run journal into "where did the time go", with its own caveats.

    ``summary`` is what :func:`src.backup.runlog.summarise` returns; ``beats`` the raw
    beat list when available (the stall analysis needs it and says so when it is not).
    """
    stages: dict[str, float] = {
        k: v for k, v in (summary.get("stages") or {}).items() if isinstance(v, int | float)
    }
    # Which entries are already CONTAINED in another, and so must not be summed twice.
    # Two shapes, and the difference matters: "prepare_staged:validate" nests under a
    # stage that IS recorded, while "merge_step:articles" nests under "merge" through a
    # namespace that is not itself a stage. Everything else with a colon is top-level --
    # notably "stage_a:reassemble", which has no parent at all. A naive "any colon is a
    # sub-stage" rule silently dropped the four stage_a entries and under-reported the
    # accounted time by 36 s of the field run's 118.
    def _is_substage(key: str) -> bool:
        if ":" not in key:
            return False
        prefix = key.split(":", 1)[0]
        return prefix in stages or prefix in _ROLLUP_NAMESPACES

    top = {k: v for k, v in stages.items() if not _is_substage(k)}
    accounted = round(sum(top.values()), 1)

    last = summary.get("last_beat") or {}
    elapsed = last.get("el_s")
    out: dict[str, Any] = {
        "run_id": summary.get("run_id"),
        "kind": summary.get("kind"),
        "complete": summary.get("complete"),
        "outcome": summary.get("outcome") or ("complete" if summary.get("complete") else "incomplete"),
        "died_in_stage": summary.get("died_in_stage"),
        "stages_top_level_s": accounted,
        "slowest_stages": sorted(
            ({"stage": k, "seconds": round(v, 1)} for k, v in top.items()),
            key=lambda r: -r["seconds"],
        )[:5],
    }

    if isinstance(elapsed, int | float) and elapsed > 0:
        out["elapsed_s"] = round(elapsed, 1)
        # The stage that never ended has no entry in `stages`, so whatever the timed
        # stages do not account for is the time spent inside it. Naming this is the
        # single most useful line in the whole report for a killed run.
        unaccounted = round(elapsed - accounted, 1)
        if unaccounted > 0:
            out["unaccounted_s"] = unaccounted
            out["unaccounted_share"] = round(unaccounted / elapsed, 3)
            out["unaccounted_note"] = (
                f"time inside {summary.get('died_in_stage') or 'the stage that never finished'}, "
                "which has no completed-stage timing precisely because it never completed"
            )
    else:
        out["elapsed_unavailable"] = "no beat carried an elapsed time"

    if beats:
        stalls = _stall_windows(beats)
        out["stalls"] = stalls
        if stalls:
            worst = max(stalls, key=lambda s: s["seconds"])
            out["longest_stall"] = worst
            if out.get("elapsed_s"):
                out["longest_stall_share"] = round(worst["seconds"] / out["elapsed_s"], 3)
            # The headline the operator actually needs, in words, with its own bound.
            out["headline"] = (
                f"{worst['seconds']:.0f}s of the {out.get('elapsed_s', 0):.0f}s run made no "
                f"progress on '{worst['counter']}' (stuck at {worst['stuck_at']}). A stall is a "
                "window in which a counter did not move -- not proof the process was stuck."
            )
        else:
            out["stalls_none"] = (
                f"no counter sat still for {_STALL_MIN_S:.0f}s or more; phases that publish no "
                "counter are not examined, because 'not moving' cannot be said of them"
            )
    else:
        out["stalls_unavailable"] = "the raw beats were not supplied, so no stall analysis was run"
    return out


def latest_run_timeline(*, max_runs: int = 4) -> dict:
    """Analyse the most recent runs. Degrades loudly: a journal that cannot be read is
    reported as unreadable, never as "no runs" -- the two must not look alike."""
    try:
        from src.backup.runlog import raw_runs, summarise
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"run journal unavailable: {exc}"}

    try:
        raw = raw_runs(max_runs=max_runs)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"could not read the run journal: {exc}"}

    runs: list[dict] = []
    for run_id, payload in (raw or {}).items():
        try:
            beats = (payload or {}).get("beats") or []
            runs.append(analyse_run(summarise(run_id), beats))
        except Exception as exc:  # noqa: BLE001 - one bad run must not hide the others
            runs.append({"run_id": run_id, "error": str(exc)})
    return {
        "available": True,
        "schema": "oo-run-timeline-1",
        "runs": runs,
        "stall_threshold_s": _STALL_MIN_S,
        "method": (
            "Top-level stage seconds from the run journal; entries nested in another "
            "stage are excluded so nothing is counted twice. Unaccounted time is elapsed "
            "minus those stages, i.e. time inside a stage that never finished. A stall is "
            "a window in which a REAL counter did not advance -- never a claim that the "
            "process was stuck, which this cannot know. CPU rates are medians of per-beat "
            "rates over the beats that measured them, never diluted across beats that "
            "did not."
        ),
    }

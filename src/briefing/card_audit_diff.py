"""
Audit-to-audit diff — the missing instrument of the card-system improvement loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

CONTINUOUS IMPROVEMENT (maintainer-ruled 2026-07-31, app-wide posture): improve ->
audit -> improve -> audit, in the pharmaceutical sense. The loop needs three
instruments, and TWO WERE ALREADY BUILT:

  1. a determinism check      -- ``card_audit._determinism_check``, ON BY DEFAULT
                                 (``determinism: bool = True``), skipped only by an
                                 explicit budget and reported as skipped, never as
                                 a stable feed.
  2. persisted audit runs     -- ``card_audit._report_path`` writes one
                                 ``oo-card-audit-<stamp>.json`` per deep run, so
                                 runs accumulate and stay comparable.
  3. an audit-to-audit diff   -- THIS MODULE. Nothing compared two saved runs, so
                                 "did the fix work, and did anything else regress?"
                                 could only be answered by reading two JSON files
                                 side by side.

WHY THE CLASSIFIER IS NOT SHARED WITH ``scripts/kpi_diff.py``. That script is
deliberately stdlib-only and documented to run *without the app installed*
(``python3 scripts/kpi_diff.py OLD.json NEW.json``, which puts ``scripts/`` on
``sys.path`` -- not the repo root), so it cannot import from ``src``. Moving its
helpers here would break that property, and importing them from a script into
runtime code inverts the dependency. The vocabulary (improved / regressed /
unchanged / not-measurable / not-comparable) is deliberately IDENTICAL so the two
cycle reports read alike; the logic here is genuinely smaller because card-audit
metrics are plain counts with no "exact/green-verdict" case. That is a recorded
decision, not accidental duplication.

HONESTY RAILS. A metric absent from either side is not-comparable, never assumed
zero. A check that did not run reports not-measurable, never "stable". Counts with
no direction-of-goodness (how many cards surfaced) are reported as changed /
unchanged and are NEVER called an improvement -- more cards is not better. There is
no blended verdict and no score: the output is per-metric classifications plus
per-category counts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

SCHEMA = "oo-card-audit-metrics-1"
DIFF_SCHEMA = "oo-card-audit-diff-1"

# Same vocabulary as scripts/kpi_diff.py, deliberately (see the module docstring).
IMPROVED, REGRESSED, UNCHANGED = "improved", "regressed", "unchanged"
NOT_MEASURABLE, NOT_COMPARABLE, CHANGED = "not-measurable", "not-comparable", "changed"

DOWN, UP = "down", "up"  # direction-of-goodness; None means "no goodness direction"


class CardAuditDiffError(Exception):
    """A malformed / incompatible report — the comparison cannot be honest."""


def _dig(obj: Any, *path: str) -> Any:
    """Walk nested dicts, returning None the moment the path leaves a dict.

    Returning None (rather than 0) is what keeps an ABSENT metric distinguishable
    from a metric that was measured and happened to be zero.
    """
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _len_or_none(v: Any) -> int | None:
    return len(v) if isinstance(v, list) else None


def _determinism_value(report: dict) -> int | None:
    """0 = stable, 1 = unstable, None = the check did not run.

    ``stable`` is None whenever the check was skipped, and the audit's own note says
    an unrun check is never reported as a stable feed. That None must survive to
    not-measurable here rather than being read as "fine".
    """
    stable = _dig(report, "validation_summary", "determinism", "stable")
    if stable is None:
        return None
    return 0 if stable else 1


# id, human name, direction-of-goodness, extractor.
# Direction None => a count with no goodness direction: it is reported as
# changed/unchanged and never as an improvement or a regression.
_METRIC_SPECS: tuple[tuple[str, str, str | None, Any], ...] = (
    # -- producer inventory (the negative-space dimension) -- #
    ("P1", "producers reporting error", DOWN,
     lambda r: _len_or_none(_dig(r, "producer_inventory", "errored"))),
    ("P2", "producers registered", None,
     lambda r: _dig(r, "producer_inventory", "total")),
    ("P3", "producers with no signal", None,
     lambda r: _len_or_none(_dig(r, "producer_inventory", "silent"))),
    # -- arithmetic (does trigger.math reproduce signal?) -- #
    ("A1", "math rows that failed to reproduce", DOWN,
     lambda r: _dig(r, "validation_summary", "arithmetic", "failed_n")),
    ("A2", "math rows not mechanically checkable", DOWN,
     lambda r: _dig(r, "validation_summary", "arithmetic", "not_checkable_n")),
    ("A3", "math rows reproduced", UP,
     lambda r: _dig(r, "validation_summary", "arithmetic", "reproduced_n")),
    ("A4", "cards carrying no trigger block", DOWN,
     lambda r: _dig(r, "validation_summary", "arithmetic", "cards_without_trigger")),
    # -- non-fabrication -- #
    ("N1", "cards missing a method", DOWN,
     lambda r: _dig(r, "validation_summary", "non_fabrication", "method_missing_n")),
    ("N2", "cards missing a caveat", DOWN,
     lambda r: _dig(r, "validation_summary", "non_fabrication", "caveat_missing_n")),
    ("N3", "cards with banned key matches", DOWN,
     lambda r: _dig(r, "validation_summary", "non_fabrication",
                    "cards_with_banned_key_matches")),
    # -- corpus fidelity -- #
    ("C1", "cards without article ids", DOWN,
     lambda r: _dig(r, "validation_summary", "corpus_fidelity", "cards_without_article_ids")),
    ("C2", "cards whose articles do not resolve", DOWN,
     lambda r: _dig(r, "validation_summary", "corpus_fidelity", "cards_with_missing_articles")),
    ("C3", "cards citing quarantined articles", DOWN,
     lambda r: _dig(r, "validation_summary", "corpus_fidelity",
                    "cards_with_quarantined_articles")),
    ("C4", "cards whose n mismatches their ids", DOWN,
     lambda r: _dig(r, "validation_summary", "corpus_fidelity", "cards_where_n_mismatches_ids")),
    # -- determinism -- #
    ("D1", "producer pass unstable across two runs", DOWN, _determinism_value),
    # -- feed shape (informational) -- #
    ("F1", "cards surfaced", None,
     lambda r: _dig(r, "validation_summary", "cards_surfaced")),
    ("F2", "cards suppressed by the dedup belt", None,
     lambda r: _dig(r, "validation_summary", "cards_suppressed")),
)


def card_audit_metrics(report: dict) -> dict:
    """Project a saved card-audit report onto a comparable metrics snapshot.

    The audit payload is large and mostly per-card detail; this reduces it to the
    handful of numbers an improvement cycle actually moves, each carrying its own
    direction-of-goodness so the diff can classify it without a blended verdict.

    A metric the report does not carry stays ``None`` -- absent, not zero.
    """
    if not isinstance(report, dict):
        raise CardAuditDiffError("card-audit report is not an object")
    metrics = []
    for mid, name, direction, extract in _METRIC_SPECS:
        try:
            value = extract(report)
        except Exception:  # noqa: BLE001 - one odd field must not sink the projection
            value = None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            value = None  # absent or non-numeric => not measurable, never coerced
        metrics.append({"id": mid, "name": name, "direction": direction, "value": value})
    return {
        "schema": SCHEMA,
        "generated_at": report.get("generated_at"),
        "depth": report.get("depth"),
        "metrics": metrics,
    }


def classify_metric(old: dict | None, new: dict | None) -> str:
    """Classify one metric across two snapshots from its direction-of-goodness.

    Mirrors ``scripts/kpi_diff.classify``'s vocabulary. Simpler than it, because
    card-audit metrics are plain counts: there is no "exact/green-verdict" case.
    """
    if old is None or new is None:
        return NOT_COMPARABLE
    ov, nv = old.get("value"), new.get("value")
    if ov is None or nv is None:
        return NOT_MEASURABLE
    direction = new.get("direction") or old.get("direction")
    if direction not in (UP, DOWN):
        # No goodness direction: report movement, never call it good or bad.
        return UNCHANGED if ov == nv else CHANGED
    if ov == nv:
        return UNCHANGED
    better = (nv > ov) if direction == UP else (nv < ov)
    return IMPROVED if better else REGRESSED


def diff_card_audit_metrics(old: dict, new: dict) -> dict:
    """Per-metric cycle report over two projected snapshots. No blended verdict."""
    old_by = {m.get("id"): m for m in old.get("metrics", []) if isinstance(m, dict)}
    new_by = {m.get("id"): m for m in new.get("metrics", []) if isinstance(m, dict)}
    rows: list[dict] = []
    for mid, name, direction, _ in _METRIC_SPECS:
        o, n = old_by.get(mid), new_by.get(mid)
        rows.append({
            "id": mid,
            "name": name,
            "direction": direction,
            "classification": classify_metric(o, n),
            "old_value": (o or {}).get("value"),
            "new_value": (n or {}).get("value"),
        })
    # Any metric present in the data but not in the spec table (an older or newer
    # report shape) is surfaced rather than silently dropped.
    known = {r["id"] for r in rows}
    extra_ids = {k for k in (set(old_by) | set(new_by)) if k is not None} - known
    for extra_id in sorted(extra_ids, key=str):
        o, n = old_by.get(extra_id), new_by.get(extra_id)
        ref = n or o or {}
        rows.append({
            "id": extra_id,
            "name": ref.get("name"),
            "direction": ref.get("direction"),
            "classification": classify_metric(o, n),
            "old_value": (o or {}).get("value"),
            "new_value": (n or {}).get("value"),
            "note": "not in this build's metric table — reported, not interpreted",
        })
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    return {
        "schema": DIFF_SCHEMA,
        "old_generated_at": old.get("generated_at"),
        "new_generated_at": new.get("generated_at"),
        "metrics": rows,
        "counts": counts,  # per-category counts — a listing, never a blended score
        "method": (
            "Per-metric improved/regressed/unchanged/not-measurable/not-comparable from each "
            "metric's declared direction-of-goodness. Counts with no direction (cards surfaced, "
            "producers registered) report changed/unchanged and are never called an improvement. "
            "A metric absent from either report is not-comparable, never assumed zero; a check "
            "that did not run is not-measurable, never 'stable'."
        ),
        "caveat": (
            "Two audits of a LIVE corpus. Real ingest between the runs moves numbers on its own, "
            "so a regression here is a prompt to look, never by itself a defect — and an "
            "improvement may reflect the corpus, not the fix."
        ),
    }


def diff_card_audit_reports(old_report: dict, new_report: dict) -> dict:
    """Diff two saved card-audit reports end to end (project, then compare)."""
    return diff_card_audit_metrics(card_audit_metrics(old_report), card_audit_metrics(new_report))


# --------------------------------------------------------------------------- #
#  Saved-report access
# --------------------------------------------------------------------------- #


def list_card_audit_reports() -> list[str]:
    """Saved deep card-audit report filenames, oldest first. Never raises."""
    try:
        from src.briefing.card_audit import _report_dir

        return sorted(p.name for p in _report_dir().glob("oo-card-audit-*.json"))
    except Exception:  # noqa: BLE001 - a missing data dir is not an error here
        return []


def _read_report(name: str) -> dict:
    from src.briefing.card_audit import _report_dir

    path = _report_dir() / name
    # The name comes from our own glob, but a caller may pass one: keep it inside
    # the report dir rather than trusting it (the standing traversal-guard rule).
    if path.parent.resolve() != _report_dir().resolve():
        raise CardAuditDiffError(f"{name}: outside the report directory")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a corrupt saved file degrades loudly here
        raise CardAuditDiffError(f"{name}: unreadable card-audit report ({exc})") from exc


def diff_latest_card_audits() -> dict:
    """Compare the two newest saved deep audits.

    Degrades with a stated reason rather than raising, so it is safe to surface:
    fewer than two saved runs is the normal state of a fresh install, not an error.
    """
    names = list_card_audit_reports()
    if len(names) < 2:
        return {
            "available": False,
            "reason": (
                f"{len(names)} saved deep card-audit run(s); two are needed to compare"
            ),
            "note": (
                "the improvement loop compares consecutive DEEP runs "
                "(POST /api/diagnostics/card-audit/run), not the live summary-depth report"
            ),
            "saved_runs": names,
        }
    try:
        old, new = _read_report(names[-2]), _read_report(names[-1])
    except CardAuditDiffError as exc:
        return {"available": False, "reason": str(exc), "saved_runs": names}
    out = diff_card_audit_reports(old, new)
    out.update({"available": True, "old_report": names[-2], "new_report": names[-1]})
    return out


# --------------------------------------------------------------------------- #
#  Selftest (recursive-loop harness)
# --------------------------------------------------------------------------- #


def run_card_audit_diff_selftest() -> dict:
    """Prove the differ's mechanism on synthetic reports — no corpus, no files.

    Each case asserts one property the loop depends on; a failure names the case.
    """
    cases: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        cases.append({"case": name, "passed": bool(ok), "detail": detail})

    def _report(**summary) -> dict:
        """A minimal report carrying just the fields the projection reads."""
        return {
            "generated_at": summary.pop("generated_at", "2026-01-01T00:00:00+00:00"),
            "producer_inventory": {
                "errored": [{"name": f"p{i}"} for i in range(summary.pop("errored", 0))],
                "total": summary.pop("total", 10),
                "silent": [],
            },
            "validation_summary": {
                "cards_surfaced": summary.pop("cards_surfaced", 5),
                "cards_suppressed": 0,
                "determinism": {"stable": summary.pop("stable", True)},
                "arithmetic": {
                    "failed_n": summary.pop("failed_n", 0),
                    "not_checkable_n": 0,
                    "reproduced_n": summary.pop("reproduced_n", 3),
                    "cards_without_trigger": 0,
                },
                "non_fabrication": {
                    "method_missing_n": 0,
                    "caveat_missing_n": 0,
                    "cards_with_banned_key_matches": 0,
                },
                "corpus_fidelity": {
                    "cards_without_article_ids": 0,
                    "cards_with_missing_articles": 0,
                    "cards_with_quarantined_articles": 0,
                    "cards_where_n_mismatches_ids": 0,
                },
            },
        }

    def _row(diff: dict, mid: str) -> dict:
        return next(r for r in diff["metrics"] if r["id"] == mid)

    # 1. A fixed defect is an improvement.
    d = diff_card_audit_reports(_report(errored=3), _report(errored=0))
    _check("fewer producer errors reads as improved",
           _row(d, "P1")["classification"] == IMPROVED, str(_row(d, "P1")))

    # 2. A new defect is a regression.
    d = diff_card_audit_reports(_report(failed_n=0), _report(failed_n=2))
    _check("new arithmetic failures read as regressed",
           _row(d, "A1")["classification"] == REGRESSED, str(_row(d, "A1")))

    # 3. An up-metric moves the other way.
    d = diff_card_audit_reports(_report(reproduced_n=1), _report(reproduced_n=9))
    _check("more reproduced math rows reads as improved",
           _row(d, "A3")["classification"] == IMPROVED, str(_row(d, "A3")))

    # 4. A count with no goodness direction is never an improvement.
    d = diff_card_audit_reports(_report(cards_surfaced=5), _report(cards_surfaced=40))
    _check("more cards is 'changed', never 'improved'",
           _row(d, "F1")["classification"] == CHANGED, str(_row(d, "F1")))

    # 5. A determinism check that did not run is not-measurable, never stable.
    d = diff_card_audit_reports(_report(stable=True), _report(stable=None))
    _check("an unrun determinism check is not-measurable",
           _row(d, "D1")["classification"] == NOT_MEASURABLE, str(_row(d, "D1")))

    # 6. Instability is a regression.
    d = diff_card_audit_reports(_report(stable=True), _report(stable=False))
    _check("a feed that became unstable reads as regressed",
           _row(d, "D1")["classification"] == REGRESSED, str(_row(d, "D1")))

    # 7. A number the report does not carry is NOT read as zero.
    #    The row still exists (we always project every spec'd metric), so its
    #    verdict is not-measurable -- "we could not measure it" -- rather than a
    #    zero-to-zero pass. not-comparable is reserved for a metric id missing from
    #    a snapshot outright (case 9).
    stripped = _report()
    del stripped["validation_summary"]["arithmetic"]
    d = diff_card_audit_reports(stripped, _report())
    row = _row(d, "A1")
    _check("an unreported number is not-measurable, not a zero-to-zero pass",
           row["classification"] == NOT_MEASURABLE and row["old_value"] is None, str(row))

    # 8. No blended verdict anywhere in the payload.
    d = diff_card_audit_reports(_report(), _report())
    banned = ("score", "ranking", "rating", "grade")
    flat = json.dumps(d).lower()
    _check("no score-shaped key in the payload",
           not any(f'"{b}"' in flat or f'_{b}"' in flat for b in banned), "")

    # 9. A metric id present on one side only is not-comparable, and is still
    #    REPORTED rather than dropped (a report shape from another build).
    a = card_audit_metrics(_report())
    b = card_audit_metrics(_report())
    b["metrics"].append({"id": "ZZ", "name": "from another build", "direction": DOWN, "value": 1})
    d = diff_card_audit_metrics(a, b)
    zz = [r for r in d["metrics"] if r["id"] == "ZZ"]
    _check("a metric only one side knows is reported as not-comparable",
           bool(zz) and zz[0]["classification"] == NOT_COMPARABLE, str(zz))

    # SHAPE CONTRACT: ``recursive_loop._selftest_passed`` reads a top-level ``passed``
    # BOOL (or a ``summary.failed`` int) and reports None -- "shape not recognized",
    # never a fabricated green -- for anything else. An earlier cut returned ``passed``
    # as a COUNT, which is an int, so the loop honestly refused to call it green. Counts
    # therefore live under ``*_count``, matching run_leads_selftest / run_skeleton_selftest.
    passed = all(c["passed"] for c in cases)
    return {
        "schema": "oo-card-audit-diff-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": cases,
        "total": len(cases),
        "passed": passed,
        "passed_count": sum(1 for c in cases if c["passed"]),
        "failed_count": sum(1 for c in cases if not c["passed"]),
        "method": (
            "Synthetic before/after reports through the real projection and classifier. "
            "Proves the mechanism only — it says nothing about any real corpus."
        ),
    }

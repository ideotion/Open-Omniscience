"""
The V1 KPI snapshot (R1, V1_PATHWAY §2.3) — each metric stands alone, no composite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A read-only, versioned snapshot of the K1–K14 board — the V1 definition made mechanical
so the KPI differ (R2) can classify improved / regressed / unchanged between two cycles.
Every metric carries ``{id, name, value, method, n, as_of, source_endpoint, direction,
target, verdict}``:

  * ``direction`` (``up`` / ``down`` / ``exact``) is ALWAYS present — R2 cannot classify a
    delta without a declared direction-of-goodness;
  * ``target`` may be ``"pending-ruling-V1-6"`` (the numeric bar is a ruling, not the
    direction);
  * ``verdict`` is ``green`` / ``red`` / ``measured-no-bar`` / ``not-measurable-here`` —
    NEVER a fabricated pass (the S1 lesson: a pass on a proxy over-reads). A metric whose
    instrument lacks data on THIS machine (no live corpus, no graded gold set, no P0
    report, no CI facts in-process) reports ``not-measurable-here`` — that is the honest
    answer, not a gap to paper over. ``measured-no-bar`` is the DIFFERENT fact that the
    figure IS known and the numeric bar is still a ruling (``target: pending-ruling-V1-6``):
    reusing ``not-measurable-here`` there would say the metric could not be read, which is
    false, and would put a real number behind a verdict whose whole meaning is that there
    is none. It is never a way to dodge a red — the selftest requires it to carry a value
    AND a pending-ruling target.

HONESTY BY CONSTRUCTION: no composite (no overall score / percentage / count-of-greens);
this GET NEVER triggers a heavy crunch (an expensive instrument reports its last persisted
value with an ``as_of``, or ``not-measurable-here`` — it is not re-run here). Only the cheap,
in-process instruments (the latency reservoir K2, the locale files K11) are read live.

That "last persisted value" clause described nothing until 2026-09-07: no resolver read a
persisted file, and the one expensive instrument the ring-lifecycle ruling asks the board to
watch — K6, cross-language translation coverage — was on the board and STRUCTURALLY
unreadable, because ``engine_report`` is computed on demand, streamed to the caller and never
written down. A metric that can only ever answer "not-measurable-here" is not being watched;
it is being listed. ``record_translation_coverage()`` (called where the measurement is MADE,
never from this GET) closes that, and K6 now reports the real figure WITH the date it was
measured and how old it is — never re-stamped as fresh, because a stale value read as current
is the fabricated-freshness trap, and two snapshots quoting one measurement are not evidence
of stability (``scripts/kpi_diff.py`` classifies that pair ``same-measurement``, not
``unchanged``).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = "oo-kpi-1"
_NM = "not-measurable-here"
# Measured, but the bar it would be judged against is still a maintainer ruling.
_NO_BAR = "measured-no-bar"
_LOCALES = Path(__file__).resolve().parent.parent / "static" / "locales"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# The K1–K14 board (V1_PATHWAY §2.3). ``nm`` is the honest reason a metric is not measurable
# in-process on a dev machine (most are: live-corpus / graded-gold-set / operator-run / CI /
# expensive-crunch gated). K2 + K11 have live resolvers below; K5, K6, K7 and K8 read the last persisted
# measurement of their instrument, with its date, or say none was recorded (R706 for K5/K7/K8).
_SPECS: tuple[dict, ...] = (
    {"id": "K1", "name": "Warm unlock at 100 GB+", "direction": "down", "target": "< 2 s",
     "source_endpoint": "/api/system/startup-status",
     "nm": "needs a live 100 GB+ corpus warm-unlock timing (operator run); not on a dev boot"},
    {"id": "K2", "name": "Interactive endpoint p95", "direction": "down", "target": "< 500 ms",
     "source_endpoint": "/api/diagnostics/request-latency"},
    {"id": "K3", "name": "Backup at corpus scale", "direction": "exact",
     "target": "pass bounded-RAM + verify + staged-restore",
     "source_endpoint": "/api/diagnostics/p0-validation/last",
     "nm": "needs a P0-validation report from the operator's live corpus run"},
    {"id": "K4", "name": "Crash-free long run", "direction": "up", "target": "≥ 14-day continuous",
     "source_endpoint": "/api/diagnostics/session-forensics",
     "nm": "a duration metric — needs a multi-day live run + memory-guard-clean forensics"},
    {"id": "K5", "name": "Keyword noise (generic-term-candidate share of top terms)",
     "direction": "down", "target": "pending-ruling-V1-6",
     "source_endpoint": "/api/diagnostics/keyword-engine",
     "nm": "no keyword-engine run has recorded its generic-term list on this machine yet (run the "
           "keyword-engine diagnostic, or take an all-diagnostics bundle, on the live corpus); the "
           "scan is never run on this GET"},
    {"id": "K6", "name": "Cross-language translation coverage", "direction": "up",
     "target": "pending-ruling-V1-6", "source_endpoint": "/api/diagnostics/keyword-engine",
     "nm": "engine_report.translation_coverage is an expensive corpus scan — never run on this "
           "GET; no run has recorded one yet (run the keyword-engine diagnostic, or take an "
           "all-diagnostics bundle, on the live corpus)"},
    {"id": "K7", "name": "Date-extraction recall", "direction": "up",
     "target": "pending-ruling-V1-6", "source_endpoint": "/api/diagnostics/dates",
     "nm": "no standard date diagnostic (the 1500 most recent articles, no language or day filter) has "
           "recorded its coverage on this machine yet (run the date diagnostics, or take an all-diagnostics "
           "bundle); the article scan is never run on this GET"},
    {"id": "K8", "name": "Source health + diversity", "direction": "up",
     "target": "pending-ruling-V1-6 (per-region flag distribution inspected, not scored)",
     "source_endpoint": "/api/diagnostics/source-audit",
     "nm": "no source audit has recorded its status counts on this machine yet (run the source "
           "audit, or take an all-diagnostics bundle); the audit is never run on this GET"},
    {"id": "K9", "name": "Retrieval quality (nDCG/MRR/Recall per language)", "direction": "up",
     "target": "no regression vs frozen baseline (floors at first grading)",
     "source_endpoint": "/api/diagnostics/ir-eval",
     "nm": "needs a graded IR gold set (R6); not-measurable until it is graded"},
    {"id": "K10", "name": "Perception quality (precision/recall/hallucination per stratum)",
     "direction": "up", "target": "clear the harness before extraction ships (floors pending)",
     "source_endpoint": "/api/diagnostics/perception-eval-selftest",
     "nm": "needs a graded who/where/when gold set (R6); not-measurable today"},
    {"id": "K11", "name": "i18n completeness", "direction": "exact",
     "target": "min 100% ×12 (+ audit-chrome 0, CI-verified)",
     "source_endpoint": "scripts/i18n_report.py"},
    {"id": "K12", "name": "Browser verification (share of flagged surfaces ≥ Gecko-verified)",
     "direction": "up", "target": "100% at 1.0 + human UX pass",
     "source_endpoint": "R3 (AppVM ui_walk)",
     "nm": "awaits R3 — the flagged-surface inventory does not exist in-process yet"},
    {"id": "K13", "name": "Vertical coverage", "direction": "exact",
     "target": "first slice ingested + freshness green, per §4 vertical",
     "source_endpoint": "/api/diagnostics/freshness",
     "nm": "per-vertical coverage diagnostics await the §4 vertical builds"},
    {"id": "K14", "name": "Development health (suite · mypy ratchet · open P0s)",
     "direction": "exact", "target": "suite green · mypy ≤ baseline · open data-loss P0s = 0",
     "source_endpoint": "CI",
     "nm": "suite/mypy/CI are out-of-process facts (subprocess forbidden here) — read from CI"},
)


def _entry(spec: dict, *, value=None, n=None, as_of=None, verdict=_NM, method: str = "") -> dict:
    return {
        "id": spec["id"],
        "name": spec["name"],
        "value": value,
        "method": method or spec.get("nm", ""),
        "n": n,
        "as_of": as_of,
        "source_endpoint": spec.get("source_endpoint"),
        "direction": spec["direction"],  # always present (R2 needs it)
        "target": spec["target"],
        "verdict": verdict,
    }


def _k2_made_of(snappy_bar: dict, worst: dict, unlock: dict | None = None) -> tuple[str, str]:
    """What K2's number is MADE OF, as two method fragments: how the worst route's slowest call
    sat against an unlock, and how the breaches across all interactive routes divide.

    The 2026-09-30 round had K2 red on sixteen of sixteen instances, most of them on a route
    with one or two samples, and nothing in the entry said whether that was a slow read, a
    refused request or a first call after an unlock. The value, n and verdict are unchanged --
    this only says what they are made of -- and every figure is read from the latency summary:
    a summary that predates the attribution yields only the fragments its keys support (the
    call needs ``slowest``; the split needs ``breaching`` and ``interactive_routes``).

    A call's distance from an unlock is fixed when the call is RECORDED, against the latest unlock
    that had finished by then, while these words are chosen when the report is built. So they must
    not say "the last unlock" (a later one may exist) and, when the distance is absent, they read
    ``unlock`` (the summary's own stamp record) to tell "no unlock has ever finished here" from
    "none had finished when this call ended"."""
    from src.monitoring.unlock_marker import UNLOCK_ROUTES

    slowest = worst.get("slowest")
    call = ""
    if isinstance(slowest, dict) and slowest.get("ms") is not None:
        d = slowest.get("started_after_unlock_s")
        ended = slowest.get("ended_at")
        finished = unlock.get("count") if isinstance(unlock, dict) else None
        if d is None:
            if ended is None:
                # A clock that failed (or a summary that predates the stamp) leaves no end time, and
                # then nothing can be said about where the call sat against an unlock, the case below
                # that reads "it ended before any unlock had finished" included.
                where = "its end time was not recorded, so its distance from an unlock is unknown"
            elif not isinstance(finished, int):
                where = "its distance from an unlock was not recorded"  # no stamp record to read
            elif finished >= 1:
                where = "it ended before any unlock had finished in this process"
            else:
                where = "no unlock has finished in this process, so its distance from one is unknown"
        elif d >= 0:
            where = f"it began {d:,.1f} s after the latest unlock to finish before it ended"
        else:
            # The stamp lies between this call's start and its end: an unlock finished while it ran.
            # Only the two requests that PERFORM an unlock are that unlock's own request.
            own = " (the unlock's own request)" if worst.get("route") in UNLOCK_ROUTES else ""
            where = f"it began {-d:,.1f} s BEFORE an unlock finished while it ran{own}"
        call = (
            f"; its slowest call took {float(slowest['ms']):,.1f} ms (status {slowest.get('status')})"
            + (f", ended {ended}," if ended else ",")
            + f" and {where}"
        )
    split = ""
    breaching, interactive = snappy_bar.get("breaching"), snappy_bar.get("interactive_routes")
    if isinstance(breaching, int) and isinstance(interactive, int):
        split = f"{breaching} of {interactive} interactive routes are over the bar"
        thin, floor = snappy_bar.get("breaching_low_n"), snappy_bar.get("min_n")
        if isinstance(thin, int) and isinstance(floor, int):
            split += f" ({thin} of them on fewer than {floor} samples)"
        kinds = [
            f"{snappy_bar[key]} {label}"
            for key, label in (
                ("breaching_refusal_or_error_driven", "only through refused or errored requests"),
                ("breaching_first_call_only", "only on their first call"),
                ("breaching_single_call", "on a single call"),
            )
            if isinstance(snappy_bar.get(key), int)
        ]
        if kinds:
            split += "; " + ", ".join(kinds) + " (counted by route, and overlapping)"
    return call, split


def _k2_latency(spec: dict) -> dict:
    """K2: worst interactive-route p95 vs the 500 ms bar, from the in-memory latency reservoir."""
    from src.monitoring import latency

    summ = latency.summary()
    # S5 item 2 (field-feedback 2026-07-23): summ["snappy_bar"] is a DICT
    # ({"bar_ms": ..., "interactive_routes": ..., ...}, see latency.summary()),
    # not a plain float — the old `float(summ.get("snappy_bar") or 500.0)` raised
    # TypeError on every real call (float() of a dict), silently degrading K2 to
    # "not-measurable" behind the honest resolver-error fallback. Read the nested
    # bar_ms field.
    snappy_bar = summ.get("snappy_bar") or {}
    bar = float(snappy_bar.get("bar_ms") or 500.0)
    # EVERY interactive route, low-n included (field bundle 2026-08-02). Restricting the
    # selection to pass|fail excluded every route a human actually waits on, because a
    # thin window is the SIGNATURE of an interactive read: the UI polls
    # /api/system/network 275 times a session and a person opens the article list twice.
    # K2 therefore reported green at 31.2 ms — the worst of three 2-second pollers —
    # while GET /api/articles sat at a measured p95 of 68,137 ms in the same reservoir.
    # The measurement is real; only its typicality is uncertain, so it is reported WITH
    # its n rather than dropped. Exempt (heavy/on-demand) routes stay out: the bar
    # genuinely does not cover them.
    interactive = [
        r for r in (summ.get("routes") or []) if r.get("snappy") in ("pass", "fail", "low-n")
    ]
    if not interactive:
        return _entry(spec, method=(
            "no interactive-route latency samples on this process yet — make a few reads first "
            "(the reservoir is in-memory, per-process; empty is honest, not a gap)"))
    worst = max(interactive, key=lambda r: float(r.get("p95_ms") or 0.0))
    worst_p95 = round(float(worst.get("p95_ms") or 0.0), 1)
    worst_n = int(worst.get("window_n") or 0)
    thin = worst.get("snappy") == "low-n"
    call_note, split_note = _k2_made_of(snappy_bar, worst, summ.get("unlock"))
    return _entry(
        spec,
        value=worst_p95,
        # The worst route's OWN sample count, not the fleet sum: an n of 1,081 summed
        # across pollers said nothing about the 2-sample route the value came from.
        n=worst_n,
        as_of=_now(),
        verdict="red" if worst_p95 >= bar else "green",
        method=(
            f"worst interactive-route p95 over the recent window vs the {bar:.0f} ms bar "
            f"({worst.get('route')}, n={worst_n}"
            + (
                "; thin window — a real measurement whose typicality is unproven, never "
                "a reason to withhold it"
                if thin
                else ""
            )
            + call_note
            + ")"
            + (f"; {split_note}" if split_note else "")
            + "; measured, per-process reservoir, counts only, no score"
        ),
    )


# --------------------------------------------------------------------------- #
#  K6 — cross-language translation coverage (a PERSISTED measurement, not a live one)
# --------------------------------------------------------------------------- #
# One small fixed-shape file, replaced each run. Deliberately NOT an append-only
# journal: the standing lesson is that "rare events" is a premise nobody enforces, and
# an unbounded diagnostic stream has already made this app unbootable once. The cycle
# history lives in the KPI SNAPSHOTS the operator keeps, which is what kpi_diff reads.
_COVERAGE_FILE = "keyword-coverage.json"
_COVERAGE_SCHEMA = "oo-keyword-coverage-1"


def _coverage_path():
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d / _COVERAGE_FILE


def record_translation_coverage(report: dict) -> dict | None:
    """Write down what a keyword-engine run measured about ring coverage.

    Called from the endpoint that RUNS the scan — never from ``kpi_snapshot`` — so the
    KPI GET stays read-only and free. Best-effort: a write that fails records nothing and
    K6 then says, truthfully, that no run has recorded a measurement. Returns the stored
    record, or ``None`` when there was nothing to store or the write failed.

    ``pct`` of ``None`` (an empty corpus: no top terms to divide by) is stored AS None.
    Storing 0.0 there would say "we looked at the keywords and none are ring-covered",
    which is the opposite of "there were no keywords to look at"."""
    block = (report or {}).get("translation_coverage")
    if not isinstance(block, dict):
        return None
    record = {
        "schema": _COVERAGE_SCHEMA,
        "measured_at": _now(),
        "pct": block.get("pct"),
        "top_n": block.get("top_n"),
        "in_a_ring": block.get("in_a_ring"),
        "rings_total": block.get("rings_total"),
    }
    try:
        path = _coverage_path()
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(part, path)
    except Exception:  # noqa: BLE001 - a diagnostic side-record never breaks the diagnostic
        return None
    return record


def read_translation_coverage() -> dict | None:
    """The last recorded coverage measurement, or ``None`` when none was ever written."""
    try:
        path = _coverage_path()
        if not path.exists():
            return None
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return rec if isinstance(rec, dict) and rec.get("schema") == _COVERAGE_SCHEMA else None


# The TRANSLATION SWEEP's own coverage (S05-08 S1, gate row H of 0.5). A second persisted
# file rather than a field in the one above, because the two are written by different
# instruments at different times, and one file per writer is what lets each keep its own
# date. K6 shows both, each alone -- never summed, because "a ring covers it" and "a model
# guessed it" are different claims about a translation.
_SWEEP_FILE = "translation-sweep-coverage.json"
_SWEEP_SCHEMA = "oo-translation-sweep-coverage-1"


def _sweep_path():
    return _coverage_path().with_name(_SWEEP_FILE)


def record_sweep_coverage(measurement: dict) -> dict | None:
    """Persist what the translation sweep measured about the keyword head. Called by the
    sweep where it MEASURES, never by the KPI GET. Returns the record, or None."""
    if not isinstance(measurement, dict) or "head_n" not in measurement:
        return None
    record = {"schema": _SWEEP_SCHEMA, "measured_at": _now(), **measurement}
    try:
        path = _sweep_path()
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(part, path)
    except Exception:  # noqa: BLE001 - a side-record never breaks the sweep
        return None
    return record


def read_sweep_coverage() -> dict | None:
    """The last recorded sweep measurement, or None when no sweep ever wrote one."""
    try:
        path = _sweep_path()
        if not path.exists():
            return None
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return rec if isinstance(rec, dict) and rec.get("schema") == _SWEEP_SCHEMA else None


def _k6_sweep_block() -> dict:
    """The sweep's half of K6: its own figures, date and age, or an honest absence."""
    rec = read_sweep_coverage()
    if rec is None:
        return {
            "verdict": _NM,
            "value": None,
            "as_of": None,
            "method": (
                "no translation sweep has recorded a measurement on this machine -- turn "
                "on background AI with keyword translation included; the sweep writes its "
                "coverage at the end of every pass"
            ),
        }
    head_n = rec.get("head_n")
    age = _age_days(rec.get("measured_at"))
    return {
        "verdict": _NO_BAR,
        "value": rec.get("tentative"),
        "n": head_n,
        "as_of": rec.get("measured_at"),
        "target_lang": rec.get("target_lang"),
        "counts": {k: rec.get(k) for k in
                   ("verified", "tentative", "untranslated", "same_language", "no_language")},
        "model": rec.get("model"),
        "pass_complete": rec.get("pass_complete"),
        "method": (
            f"Of the {head_n} most-spread keywords, {rec.get('tentative')} carry a TENTATIVE "
            f"(≈, local-model) translation into {rec.get('target_lang')}, beside "
            f"{rec.get('verified')} a verified ring translates and {rec.get('untranslated')} "
            "nothing translates yet. Recorded by the translation sweep"
            + (f", {age} day(s) ago" if age is not None else "")
            + "; counts only, never re-run here, never summed with the ring figure."
        ),
    }


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - then).total_seconds() / 86400.0, 1)


def _k6_coverage(spec: dict) -> dict:
    """K6, with the translation sweep's own persisted figure riding beside it."""
    entry = _k6_ring_coverage(spec)
    entry["sweep"] = _k6_sweep_block()
    return entry


def _k6_ring_coverage(spec: dict) -> dict:
    """K6: the share of the most-mentioned keywords that belong to a cross-language ring.

    Read from the last recorded run, and reported WITH its date and its age: the value is
    a real measurement of the corpus as it was THEN, and re-stamping it ``as_of`` now
    would turn a months-old figure into a claim about today."""
    rec = read_translation_coverage()
    if rec is None:
        return _entry(spec)  # not-measurable-here, with the spec's honest reason
    pct, top_n = rec.get("pct"), rec.get("top_n")
    measured_at = rec.get("measured_at")
    age = _age_days(measured_at)
    aged = f", measured {age} day(s) ago" if age is not None else ""
    if pct is None:
        # A run happened and produced no share. That is not-measurable in the ordinary
        # sense, so it carries no value and no as_of (the NM honesty guard); the date it
        # was looked at still belongs in the reason.
        return _entry(
            spec, n=top_n,
            method=("the last keyword-engine run (" + str(measured_at) + ") found no top "
                    "terms to divide by — an empty or unindexed corpus. No coverage share "
                    "exists, which is a different fact from a coverage of 0"),
        )
    return _entry(
        spec,
        value=pct,
        n=top_n,
        as_of=measured_at,
        # target is "pending-ruling-V1-6": there is no bar, so green/red would be invented.
        verdict=_NO_BAR,
        method=(
            f"{rec.get('in_a_ring')} of the {top_n} most-mentioned keywords fall in one of "
            f"{rec.get('rings_total')} cross-language rings ({pct}%), recorded by the "
            f"keyword-engine diagnostic{aged}. A PERSISTED measurement of the corpus as it "
            "was then, never re-run here and never re-stamped as fresh; counts only, no "
            "score. The numeric bar is ruling V1-6, so the figure is reported and the "
            "pass/fail verdict withheld rather than invented."
        ),
    )


def _k11_i18n(spec: dict) -> dict:
    """K11: minimum locale key-coverage across the 12 locales (cheap in-process file read).

    Mirrors i18n_report's coverage definition (keys present vs en.json). The audit-chrome=0
    half (no un-keyed chrome strings) is a heavier scan verified in CI — noted, not re-run."""
    en_path = _LOCALES / "en.json"
    if not en_path.exists():
        return _entry(spec, method="locale files not found in-process")
    source_keys = set(json.loads(en_path.read_text(encoding="utf-8")).keys())
    total = len(source_keys)
    worst_pct = 100.0
    worst_code = None
    n_locales = 0
    for path in sorted(_LOCALES.glob("*.json")):
        if path.stem == "en":
            continue
        n_locales += 1
        keys = set(json.loads(path.read_text(encoding="utf-8")).keys()) & source_keys
        pct = round(100 * len(keys) / total, 1) if total else 100.0
        if pct < worst_pct:
            worst_pct, worst_code = pct, path.stem
    return _entry(
        spec,
        value=worst_pct,
        n=n_locales,
        as_of=_now(),
        verdict="green" if worst_pct >= 100.0 else "red",
        method=(f"minimum locale key-coverage across {n_locales} locales vs en.json "
                f"(lowest: {worst_code or '—'}); the audit-chrome=0 half is CI-verified"),
    )


# --------------------------------------------------------------------------- R706: K5, K7, K8
# The same channel PR #1019 built for K6, for the three V1-6 metrics that had none: each instrument writes down what it
# MEASURED, where it measures (never this GET), one file per writer so each keeps its own date; each resolver reads that file
# and reports the figure WITH its date and how it was measured. Where the instrument measures no such figure, or never ran,
# the metric is "not measured" (``not-measurable-here``, no value, no as_of): never a figure computed here, never a default.
_NOISE_FILE, _NOISE_SCHEMA = "keyword-generic-terms.json", "oo-keyword-generic-terms-1"
_DATES_FILE, _DATES_SCHEMA = "date-extraction-coverage.json", "oo-date-extraction-coverage-1"
_SOURCES_FILE, _SOURCES_SCHEMA = "source-audit-status.json", "oo-source-audit-status-1"


def _write_record(name: str, schema: str, fields: dict) -> dict | None:
    """Persist one instrument's measurement beside K6's record. Best-effort: a failed write records nothing (the KPI then says
    no run recorded one) and never breaks the diagnostic that measured it."""
    record = {"schema": schema, "measured_at": _now(), **fields}
    try:
        from src.safety.file_lock import atomic_replace

        atomic_replace(_coverage_path().with_name(name), json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - a diagnostic side-record never breaks the diagnostic
        return None
    return record


def _read_record(name: str, schema: str) -> dict | None:
    """The last record ``name`` holds, or None when none was written, the file is unreadable, or it is another schema's."""
    try:
        path = _coverage_path().with_name(name)
        if not path.exists():
            return None
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return rec if isinstance(rec, dict) and rec.get("schema") == schema else None


def _int_or_none(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def record_keyword_generic_terms(report: dict) -> dict | None:
    """Write down the generic-term review list a keyword-engine run produced (K5). Called by the endpoint that runs the scan."""
    block = (report or {}).get("generic_terms")
    if not isinstance(block, dict):
        return None
    by_lang = block.get("by_language")
    return _write_record(_NOISE_FILE, _NOISE_SCHEMA, {
        "candidate_terms": _int_or_none(block.get("candidate_terms")),
        "top_per_language": _int_or_none(block.get("top_per_language")),
        "languages": len(by_lang) if isinstance(by_lang, dict) else None,
    })


def read_keyword_generic_terms() -> dict | None:
    return _read_record(_NOISE_FILE, _NOISE_SCHEMA)


#: The date diagnostics' default scan (the route's and the all-diagnostics bundle's): the population K7 records.
DATES_STANDARD_SCAN = 1500


def record_date_coverage(payload: dict, query: dict) -> dict | None:
    """Write down a STANDARD date-diagnostics run's coverage (K7): the most recent :data:`DATES_STANDARD_SCAN` articles, no
    language or day filter. Any other run measures another population (a slice, or a quick probe of 50), so it records nothing
    and the last standard figure stays, with its own date; two K7 figures are then always over the same kind of sample."""
    q = query or {}
    if q.get("lang") or q.get("days") or q.get("scan") != DATES_STANDARD_SCAN:
        return None
    corpus = (payload or {}).get("corpus")
    if not isinstance(corpus, dict):
        return None
    return _write_record(_DATES_FILE, _DATES_SCHEMA, {
        "scanned": _int_or_none(corpus.get("scanned")),
        "articles_total": _int_or_none(corpus.get("articles_total")),
        "with_extracted": _int_or_none(corpus.get("articles_with_extracted_dates")),
        "coverage_pct": corpus.get("coverage_pct") if corpus.get("scanned") else None,  # the diagnostic's own share; none on 0
        "datelike_no_extract": _int_or_none(corpus.get("articles_with_datelike_text_but_no_extraction")),
        "scan_cap": _int_or_none((query or {}).get("scan")),
    })


def read_date_coverage() -> dict | None:
    return _read_record(_DATES_FILE, _DATES_SCHEMA)


def record_source_audit_status(report: dict, *, allowlisted: int = 0) -> dict | None:
    """Write down a source audit's status counts and its per-region failing share (K8). Called by the endpoint that audits.
    ``allowlisted`` is how many domains ``OO_SOURCE_AUDIT_ALLOWLIST`` capped at watch for this run: it moves the tallies, so
    it is recorded and named beside them."""
    if not isinstance(report, dict) or "status_counts" not in report:
        return None
    counts = [{"status": str(c.get("status")), "n": _int_or_none(c.get("n"))}
              for c in report.get("status_counts") or [] if isinstance(c, dict)]
    audited = _int_or_none(report.get("sources_audited"))
    healthy = next((_int_or_none(c["n"]) for c in counts if c["status"] == "healthy"), None)
    regions = ((report.get("region_self_audit") or {}).get("by_region") or {})
    by_region = [{"region": str(r), "total": _int_or_none(v.get("total")), "pct_failing": v.get("pct_failing")}
                 for r, v in sorted(regions.items()) if isinstance(v, dict)]
    return _write_record(_SOURCES_FILE, _SOURCES_SCHEMA, {
        "sources_audited": audited,
        # Taken where the audit is made, so the board shows what was recorded and computes nothing (R706); none on 0 audited.
        "healthy_pct": round(100.0 * healthy / audited, 1) if audited and healthy is not None else None,
        "min_articles": _int_or_none(report.get("min_articles")),
        "allowlisted_domains": _int_or_none(allowlisted),
        "status_counts": counts,
        "by_region": by_region,
    })


def read_source_audit_status() -> dict | None:
    return _read_record(_SOURCES_FILE, _SOURCES_SCHEMA)


def _ago(measured_at) -> str:
    age = _age_days(measured_at)
    return f", {age} day(s) ago" if age is not None else ""


def _k5_noise(spec: dict) -> dict:
    """K5: the keyword-engine run lists generic-term REVIEW candidates; it measures no share of the top terms, so there is no
    figure to show. The last run's date and list size are stated in the reason; the value stays empty (R706)."""
    rec = read_keyword_generic_terms()
    if rec is None:
        return _entry(spec)
    return _entry(spec, method=(
        f"not measured: the keyword-engine run of {rec.get('measured_at')}{_ago(rec.get('measured_at'))} listed "
        f"{rec.get('candidate_terms')} generic-term review candidates (up to {rec.get('top_per_language')} per language, "
        f"{rec.get('languages')} languages), a list for a person to review, not a share of the top terms. No share is "
        "measured anywhere, so none is shown or computed here; it needs the term set ruling V1-6 will define."
    ))


def _k7_dates(spec: dict) -> dict:
    """K7: the share of scanned articles in which the extractor found at least one date, from the last standard run."""
    rec = read_date_coverage()
    if rec is None:
        return _entry(spec)
    scanned, found, at, pct = rec.get("scanned"), rec.get("with_extracted"), rec.get("measured_at"), rec.get("coverage_pct")
    if not scanned or found is None or not isinstance(pct, (int, float)):
        return _entry(spec, method=(
            f"not measured: the date diagnostics run of {at} scanned no articles (an empty corpus), so no share exists; "
            "that is a different fact from a coverage of 0"
        ))
    return _entry(spec, value=pct, n=scanned, as_of=at, verdict=_NO_BAR, method=(
        f"{found} of the {scanned} most recent articles scanned (of {rec.get('articles_total')}) carry at least one date the "
        f"extractor found ({pct}%), recorded by the standard date diagnostics run{_ago(at)} (the most recent "
        f"{DATES_STANDARD_SCAN} articles, never the whole corpus once it is larger); "
        f"{rec.get('datelike_no_extract')} more hold date-like text it did not turn into a date. A share of ARTICLES, not a "
        "recall over every date in the text (the recall probe over-matches, so it is no denominator). A persisted "
        "measurement, never re-run here; counts only. The bar is ruling V1-6, so no verdict is given."
    ))


def _cohort_floor() -> int | str:
    """The source audit's cohort floor, read from the audit itself so the sentence cannot drift from the rule."""
    try:
        from src.analytics.source_audit import SOURCE_COHORT_FLOOR

        return SOURCE_COHORT_FLOOR
    except Exception:  # noqa: BLE001 - the sentence still reads without the number
        return "its"


def _k8_sources(spec: dict) -> dict:
    """K8: the share of audited sources whose extraction the last source audit rated healthy, with the per-region failing
    shares beside it (inspected, never folded into the figure)."""
    rec = read_source_audit_status()
    if rec is None:
        return _entry(spec)
    audited, at = rec.get("sources_audited"), rec.get("measured_at")
    counts = {c.get("status"): c.get("n") for c in rec.get("status_counts") or [] if isinstance(c, dict)}
    healthy, pct = counts.get("healthy"), rec.get("healthy_pct")
    if not audited:
        return _entry(spec, method=(
            f"not measured: the source audit of {at} audited no source (none had {rec.get('min_articles')} articles), so "
            "no share exists"
        ))
    if healthy is None or not isinstance(pct, (int, float)):
        return _entry(spec, method=f"not measured: the source audit of {at} recorded no healthy count, so no share exists")
    tally = ", ".join(f"{n} {s}" for s, n in counts.items())
    entry = _entry(spec, value=pct, n=audited, as_of=at, verdict=_NO_BAR, method=(
        f"{healthy} of the {audited} audited sources read as healthy ({pct}%; {tally}), recorded by the source "
        f"audit{_ago(at)}"
        + (f", with {rec.get('allowlisted_domains')} allowlisted domain(s) capped at watch" if rec.get("allowlisted_domains")
           else "")
        + ". COHORT-RELATIVE, not absolute health: a source is healthy when none of its criteria falls in the bad tail of "
        "its same-language cohort, so a large cohort holds some sources outside healthy by construction, and a cohort under "
        f"the floor ({_cohort_floor()} sources) gets no soft baseline; the share can move when a cohort crosses that floor with no source "
        "changing. Extraction validity, never editorial merit; each status is its own count, never blended. The per-region "
        "failing shares ride beside it to be inspected, not scored. A persisted measurement, never re-run here. The bar is "
        "ruling V1-6, so no verdict is given."
    ))
    entry["by_region"] = rec.get("by_region") or []
    return entry


_RESOLVERS = {"K2": _k2_latency, "K5": _k5_noise, "K6": _k6_coverage, "K7": _k7_dates, "K8": _k8_sources, "K11": _k11_i18n}


def kpi_snapshot(session=None) -> dict:  # noqa: ARG001 - session accepted for the endpoint contract
    """The read-only K1–K14 KPI snapshot. Deterministic, no heavy crunch, no composite."""
    metrics: list[dict] = []
    for spec in _SPECS:
        resolver = _RESOLVERS.get(spec["id"])
        if resolver is None:
            metrics.append(_entry(spec))  # not-measurable-here with the spec's honest reason
            continue
        try:
            metrics.append(resolver(spec))
        except Exception as exc:  # noqa: BLE001 - a resolver fault degrades to not-measurable
            metrics.append(_entry(spec, method=f"resolver error (not-measurable): {type(exc).__name__}"))
    return {
        "schema": _SCHEMA,
        "generated_at": _now(),
        "metrics": metrics,
        "method": (
            "One entry per K1–K14 metric with a declared direction-of-goodness and target; "
            "only the cheap in-process instruments (latency reservoir, locale files) are read "
            "live, the rest report not-measurable-here honestly. Each metric stands alone."
        ),
        "caveat": (
            "NO composite — there is no overall score or count-of-greens by design. "
            "not-measurable-here is the honest verdict for a metric whose instrument needs the "
            "live corpus, a graded gold set, an operator P0 run, CI facts, or an expensive scan "
            "not run on this GET. Feed two snapshots to scripts/kpi_diff.py for the cycle report."
        ),
    }


def run_kpi_selftest() -> dict:
    """Mechanism proof (no DB, no network): every metric declares a direction and an honest
    verdict, the payload carries no composite/score key, and not-measurable is used honestly."""
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    snap = kpi_snapshot()
    metrics = snap.get("metrics", [])
    _check("schema", snap.get("schema") == _SCHEMA, str(snap.get("schema")))
    _check("all_14_present", len(metrics) == 14, str(len(metrics)))
    _check("direction_always_present",
           all(m.get("direction") in ("up", "down", "exact") for m in metrics))
    _check("verdict_in_domain",
           all(m.get("verdict") in ("green", "red", _NM, _NO_BAR) for m in metrics))
    _check("target_always_present", all(m.get("target") for m in metrics))
    # not-measurable honesty: a NM metric carries no fabricated value/verdict.
    nm = [m for m in metrics if m["verdict"] == _NM]
    _check("not_measurable_is_honest", all(m.get("value") is None for m in nm),
           f"{len(nm)} not-measurable metrics")
    # measured-no-bar honesty: it must carry the figure it claims to have measured AND a
    # target that really is an open ruling — otherwise it is a way to withhold a red.
    nb = [m for m in metrics if m["verdict"] == _NO_BAR]
    _check("measured_no_bar_is_honest",
           all(m.get("value") is not None and "pending-ruling" in str(m.get("target"))
               for m in nb),
           f"{len(nb)} measured-no-bar metrics")

    # no composite: walk keys for the banned score substrings (the key-walker convention).
    def _no_score(o) -> bool:
        if isinstance(o, dict):
            for k, v in o.items():
                if any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade")):
                    return False
                if not _no_score(v):
                    return False
        elif isinstance(o, list):
            return all(_no_score(v) for v in o)
        return True

    _check("no_composite_score_key", _no_score(snap))

    failed = sum(1 for c in checks if not c["passed"])
    return {
        "schema": "oo-kpi-selftest-1",
        "passed": failed == 0,
        "checks": checks,
        "summary": {"total": len(checks), "failed": failed},
        "method": "runs kpi_snapshot() on a dev process and asserts the honesty invariants "
                  "(direction present, verdict in domain, not-measurable honest, no composite).",
    }

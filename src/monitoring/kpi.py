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
import math
import os
import re
import threading
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
    # R751(d): the target names the open bar instead of a pass condition no ruling has set (Q1017 = a: bars are set from
    # recorded values, S08-02 S2), so a recorded vertical reads measured-no-bar, never green on an unruled freshness.
    {"id": "K13", "name": "Vertical coverage", "direction": "exact",
     "target": "pending-ruling-V1-6 (per vertical: first slice ingested + freshness; bars by S08-02 S2)",
     "source_endpoint": ("/api/climate/fetch · /api/diagnostics/elections-floor · /api/diagnostics/law-coverage · "
                         "diagnostics bundle (osm-change-files.json) · /api/living/overview (wiki coverage)"),
     "nm": "no vertical or lane has a first measurement on this machine yet (no climate fetch recorded, no Wikidata "
           "election snapshot on disk, no law, OSM or wiki coverage read recorded); nothing is fetched or "
           "scanned on this GET"},
    {"id": "K14", "name": "Development health (suite · mypy ratchet · open P0s)",
     "direction": "exact", "target": "suite green · mypy ≤ baseline · open data-loss P0s = 0",
     "source_endpoint": "CI",
     "nm": "suite/mypy/CI are out-of-process facts (subprocess forbidden here) — read from CI"},
)


# --------------------------------------------------------------------------- row 201: the method as keyed FRAMES
# A method used to be one English f-string with its figures welded in, so no locale key could ever match it and the hover
# read English in all twelve languages. Each method is now a list of FRAMES, ``{"t": template, "v": vars}``: the template is
# a fixed key with ``{name}`` holes, and the vars are the DATA (counts, dates, routes), which never translate. The pieces
# join with NO separator (each template carries its own punctuation and spacing), and the English ``method`` field is BUILT
# from the same frames, so the two cannot drift; it stays as the fallback for a client, or a saved snapshot, without them.
# ``tr`` lists the vars whose value is itself a key (a word such as "an unknown number of" standing where a count would):
# a number passes through it unchanged, because t() returns any string that is not a key.
_HOLE = re.compile(r"\{(\w+)\}")
#: Every value a ``tr`` var may carry that is not a number: each is a locale key (tests/test_kpi_method_frames.py).
TR_WORDS = ("an unknown number of", "unknown number of", "an unknown number", "its")


def _fr(template: str, *, tr: tuple[str, ...] = (), **variables) -> dict:
    """One keyed piece of a method: ``template`` (a locale key) and the data that fills its holes, kept as the exact
    English spelling (a string) so the English rebuilds byte for byte and a tuned figure never changes a key."""
    out: dict = {"t": template, "v": {k: str(v) for k, v in variables.items()}}
    if tr:
        out["tr"] = list(tr)
    return out


def frames_text(frames: list[dict]) -> str:
    """The English a list of method frames renders to. A hole with no value stays verbatim (the UI's tf does the same)."""
    def _fill(fr: dict) -> str:
        values: dict = fr.get("v") or {}
        return _HOLE.sub(lambda m: str(values.get(m.group(1), m.group(0))), fr["t"])

    return "".join(_fill(fr) for fr in frames or [])


def _method(frames: list[dict], key: str = "method") -> dict:
    """``{key: english, key_i18n: frames}``, to spread into a block."""
    return {key: frames_text(frames), f"{key}_i18n": frames}


def _entry(spec: dict, *, value=None, n=None, as_of=None, verdict=_NM, method: list[dict] | None = None) -> dict:
    frames = method if method else ([_fr(spec["nm"])] if spec.get("nm") else [])
    return {
        "id": spec["id"],
        "name": spec["name"],
        "value": value,
        **_method(frames),
        "n": n,
        "as_of": as_of,
        "source_endpoint": spec.get("source_endpoint"),
        "direction": spec["direction"],  # always present (R2 needs it)
        "target": spec["target"],
        "verdict": verdict,
    }


# Pieces chosen from a table rather than written at the call: (the first piece, a later piece). The first opens with its
# own bracket or "; ", a later one with ", " or "; ", so no key is bare punctuation. Every string in these tables is a
# locale key (FRAME_TABLES, scanned by tests/test_kpi_method_frames.py).
_K2_KINDS: dict[str, tuple[str, str]] = {
    "breaching_refusal_or_error_driven": ("; {n} only through refused or errored requests",
                                          ", {n} only through refused or errored requests"),
    "breaching_first_call_only": ("; {n} only on their first call", ", {n} only on their first call"),
    "breaching_single_call": ("; {n} on a single call", ", {n} on a single call"),
}
_OSM_UNKNOWN: dict[str, tuple[str, str]] = {
    "countries_change_files_unknown": (
        " ({k} countries' lane predates the table of change files, so their change files are unknown, never 0",
        "; {k} countries' lane predates the table of change files, so their change files are unknown, never 0"),
    "countries_gaps_unknown": (" ({k} countries' lane predates the table of gaps, so their gaps are unknown, never 0",
                               "; {k} countries' lane predates the table of gaps, so their gaps are unknown, never 0"),
}
_WIKI_UNKNOWN: dict[str, tuple[str, str]] = {
    "editions_pages_unknown": (" ({k} editions' pages seen unknown, never 0", "; {k} editions' pages seen unknown, never 0"),
    "editions_without_total": (" ({k} editions' own article count unknown, never 0",
                               "; {k} editions' own article count unknown, never 0"),
    "editions_text_bound_unknown": (" ({k} editions' text count in one tier unknown, never 0",
                                    "; {k} editions' text count in one tier unknown, never 0"),
    "editions_event_unreadable": (" ({k} editions' last event could not be read, which is not the same as none",
                                  "; {k} editions' last event could not be read, which is not the same as none"),
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
    call, split = _k2_made_of_frames(snappy_bar, worst, unlock)
    return frames_text(call), frames_text(split)


def _k2_made_of_frames(snappy_bar: dict, worst: dict, unlock: dict | None = None) -> tuple[list[dict], list[dict]]:
    """:func:`_k2_made_of` as keyed frames (row 201): the same two fragments, each a list of pieces."""
    from src.monitoring.unlock_marker import UNLOCK_ROUTES

    slowest = worst.get("slowest")
    call: list[dict] = []
    if isinstance(slowest, dict) and slowest.get("ms") is not None:
        d = slowest.get("started_after_unlock_s")
        ended = slowest.get("ended_at")
        finished = unlock.get("count") if isinstance(unlock, dict) else None
        if d is None:
            if ended is None:
                # A clock that failed (or a summary that predates the stamp) leaves no end time, and then nothing can be
                # said about where the call sat against an unlock, the case below that reads "it ended before any unlock
                # had finished" included.
                where = _fr("its end time was not recorded, so its distance from an unlock is unknown")
            elif not isinstance(finished, int):
                where = _fr("its distance from an unlock was not recorded")  # no stamp record to read
            elif finished >= 1:
                where = _fr("it ended before any unlock had finished in this process")
            else:
                where = _fr("no unlock has finished in this process, so its distance from one is unknown")
        elif d >= 0:
            where = _fr("it began {s} s after the latest unlock to finish before it ended", s=f"{d:,.1f}")
        elif worst.get("route") in UNLOCK_ROUTES:
            # The stamp lies between this call's start and its end: an unlock finished while it ran. Only the two requests
            # that PERFORM an unlock are that unlock's own request.
            where = _fr("it began {s} s BEFORE an unlock finished while it ran (the unlock's own request)", s=f"{-d:,.1f}")
        else:
            where = _fr("it began {s} s BEFORE an unlock finished while it ran", s=f"{-d:,.1f}")
        ms, status = f"{float(slowest['ms']):,.1f}", slowest.get("status")
        call = [
            _fr("; its slowest call took {ms} ms (status {status}), ended {ended}, and ", ms=ms, status=status, ended=ended)
            if ended else _fr("; its slowest call took {ms} ms (status {status}), and ", ms=ms, status=status),
            where,
        ]
    split: list[dict] = []
    breaching, interactive = snappy_bar.get("breaching"), snappy_bar.get("interactive_routes")
    if isinstance(breaching, int) and isinstance(interactive, int):
        split.append(_fr("{breaching} of {interactive} interactive routes are over the bar",
                         breaching=breaching, interactive=interactive))
        thin, floor = snappy_bar.get("breaching_low_n"), snappy_bar.get("min_n")
        if isinstance(thin, int) and isinstance(floor, int):
            split.append(_fr(" ({thin} of them on fewer than {floor} samples)", thin=thin, floor=floor))
        kinds = [key for key in _K2_KINDS if isinstance(snappy_bar.get(key), int)]
        if kinds:
            split += [_fr(_K2_KINDS[key][1 if i else 0], n=snappy_bar[key]) for i, key in enumerate(kinds)]
            split.append(_fr(" (counted by route, and overlapping)"))
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
        return _entry(spec, method=[_fr(
            "no interactive-route latency samples on this process yet — make a few reads first "
            "(the reservoir is in-memory, per-process; empty is honest, not a gap)")])
    worst = max(interactive, key=lambda r: float(r.get("p95_ms") or 0.0))
    worst_p95 = round(float(worst.get("p95_ms") or 0.0), 1)
    worst_n = int(worst.get("window_n") or 0)
    thin = worst.get("snappy") == "low-n"
    call_frames, split_frames = _k2_made_of_frames(snappy_bar, worst, summ.get("unlock"))
    return _entry(
        spec,
        value=worst_p95,
        # The worst route's OWN sample count, not the fleet sum: an n of 1,081 summed
        # across pollers said nothing about the 2-sample route the value came from.
        n=worst_n,
        as_of=_now(),
        verdict="red" if worst_p95 >= bar else "green",
        method=(
            [_fr("worst interactive-route p95 over the recent window vs the {bar} ms bar ({route}, n={n}",
                 bar=f"{bar:.0f}", route=worst.get("route"), n=worst_n)]
            + ([_fr("; thin window — a real measurement whose typicality is unproven, never a reason to withhold it")]
               if thin else [])
            + call_frames
            # The closing bracket rides the next piece, so no key is bare punctuation.
            + ([_fr("); {breaching} of {interactive} interactive routes are over the bar", **split_frames[0]["v"])]
               + split_frames[1:] if split_frames else [])
            + [_fr("; measured, per-process reservoir, counts only, no score") if split_frames
               else _fr("); measured, per-process reservoir, counts only, no score")]
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
            **_method([_fr(
                "no translation sweep has recorded a measurement on this machine -- turn "
                "on background AI with keyword translation included; the sweep writes its "
                "coverage at the end of every pass"
            )]),
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
        **_method([
            _fr("Of the {head_n} most-spread keywords, {tentative} carry a TENTATIVE (≈, local-model) translation into "
                "{lang}, beside {verified} a verified ring translates and {untranslated} nothing translates yet. "
                "Recorded by the translation sweep",
                head_n=head_n, tentative=rec.get("tentative"), lang=rec.get("target_lang"), verified=rec.get("verified"),
                untranslated=rec.get("untranslated")),
            *([_fr(", {age} day(s) ago", age=age)] if age is not None else []),
            _fr("; counts only, never re-run here, never summed with the ring figure."),
        ]),
    }


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):  # a hand-edited record may hold a number or a list here
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
    if pct is None:
        # A run happened and produced no share. That is not-measurable in the ordinary
        # sense, so it carries no value and no as_of (the NM honesty guard); the date it
        # was looked at still belongs in the reason.
        return _entry(
            spec, n=top_n,
            method=[_fr("the last keyword-engine run ({at}) found no top terms to divide by — an empty or unindexed "
                        "corpus. No coverage share exists, which is a different fact from a coverage of 0", at=measured_at)],
        )
    return _entry(
        spec,
        value=pct,
        n=top_n,
        as_of=measured_at,
        # target is "pending-ruling-V1-6": there is no bar, so green/red would be invented.
        verdict=_NO_BAR,
        method=[
            _fr("{in_a_ring} of the {top_n} most-mentioned keywords fall in one of {rings} cross-language rings ({pct}%), "
                "recorded by the keyword-engine diagnostic",
                in_a_ring=rec.get("in_a_ring"), top_n=top_n, rings=rec.get("rings_total"), pct=pct),
            *([_fr(", measured {age} day(s) ago", age=age)] if age is not None else []),
            _fr(". A PERSISTED measurement of the corpus as it was then, never re-run here and never re-stamped as fresh; "
                "counts only, no score. The numeric bar is ruling V1-6, so the figure is reported and the pass/fail "
                "verdict withheld rather than invented."),
        ],
    )


def _k11_i18n(spec: dict) -> dict:
    """K11: minimum locale key-coverage across the 12 locales (cheap in-process file read).

    Mirrors i18n_report's coverage definition (keys present vs en.json). The audit-chrome=0
    half (no un-keyed chrome strings) is a heavier scan verified in CI — noted, not re-run."""
    en_path = _LOCALES / "en.json"
    if not en_path.exists():
        return _entry(spec, method=[_fr("locale files not found in-process")])
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
        method=[_fr("minimum locale key-coverage across {n} locales vs en.json (lowest: {lowest}); the audit-chrome=0 half "
                    "is CI-verified", n=n_locales, lowest=worst_code or "—")],
    )


# --------------------------------------------------------------------------- R706: K5, K7, K8
# The same channel PR #1019 built for K6, for the three V1-6 metrics that had none: each instrument writes down what it
# MEASURED, where it measures (never this GET), one file per writer so each keeps its own date; each resolver reads that file
# and reports the figure WITH its date and how it was measured. Where the instrument measures no such figure, or never ran,
# the metric is "not measured" (``not-measurable-here``, no value, no as_of): never a figure computed here, never a default.
_NOISE_FILE, _NOISE_SCHEMA = "keyword-generic-terms.json", "oo-keyword-generic-terms-1"
_DATES_FILE, _DATES_SCHEMA = "date-extraction-coverage.json", "oo-date-extraction-coverage-1"
_SOURCES_FILE, _SOURCES_SCHEMA = "source-audit-status.json", "oo-source-audit-status-1"


def _write_record(name: str, schema: str, fields: dict, *, fsync: bool = True) -> dict | None:
    """Persist one instrument's measurement beside K6's record. Best-effort: a failed write records nothing (the KPI then says
    no run recorded one) and never breaks the diagnostic that measured it."""
    record = {"schema": schema, "measured_at": _now(), **fields}
    try:
        from src.safety.file_lock import atomic_replace

        atomic_replace(_coverage_path().with_name(name), json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
                       fsync=fsync)
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


def _ago(measured_at) -> list[dict]:
    age = _age_days(measured_at)
    return [_fr(", {age} day(s) ago", age=age)] if age is not None else []


def _k5_noise(spec: dict) -> dict:
    """K5: the keyword-engine run lists generic-term REVIEW candidates; it measures no share of the top terms, so there is no
    figure to show. The last run's date and list size are stated in the reason; the value stays empty (R706)."""
    rec = read_keyword_generic_terms()
    if rec is None:
        return _entry(spec)
    return _entry(spec, method=[
        _fr("not measured: the keyword-engine run of {at}", at=rec.get("measured_at")),
        *_ago(rec.get("measured_at")),
        _fr(" listed {n} generic-term review candidates (up to {per} per language, {langs} languages), a list for a person "
            "to review, not a share of the top terms. No share is measured anywhere, so none is shown or computed here; it "
            "needs the term set ruling V1-6 will define.",
            n=rec.get("candidate_terms"), per=rec.get("top_per_language"), langs=rec.get("languages")),
    ])


def _k7_dates(spec: dict) -> dict:
    """K7: the share of scanned articles in which the extractor found at least one date, from the last standard run."""
    rec = read_date_coverage()
    if rec is None:
        return _entry(spec)
    scanned, found, at, pct = rec.get("scanned"), rec.get("with_extracted"), rec.get("measured_at"), rec.get("coverage_pct")
    if not scanned or found is None or not isinstance(pct, (int, float)):
        return _entry(spec, method=[_fr(
            "not measured: the date diagnostics run of {at} scanned no articles (an empty corpus), so no share exists; "
            "that is a different fact from a coverage of 0", at=at)])
    return _entry(spec, value=pct, n=scanned, as_of=at, verdict=_NO_BAR, method=[
        _fr("{found} of the {scanned} most recent articles scanned (of {total}) carry at least one date the extractor "
            "found ({pct}%), recorded by the standard date diagnostics run",
            found=found, scanned=scanned, total=rec.get("articles_total"), pct=pct),
        *_ago(at),
        _fr(" (the most recent {cap} articles, never the whole corpus once it is larger); {datelike} more hold date-like "
            "text it did not turn into a date. A share of ARTICLES, not a recall over every date in the text (the recall "
            "probe over-matches, so it is no denominator). A persisted measurement, never re-run here; counts only. The "
            "bar is ruling V1-6, so no verdict is given.",
            cap=DATES_STANDARD_SCAN, datelike=rec.get("datelike_no_extract")),
    ])


def _cohort_floor() -> int | str:
    """The source audit's cohort floor, read from the audit itself so the sentence cannot drift from the rule."""
    try:
        from src.analytics.source_audit import SOURCE_COHORT_FLOOR

        return SOURCE_COHORT_FLOOR
    except Exception:  # noqa: BLE001 - the sentence still reads without the number
        return "its"


#: K8's tally, one keyed piece per audit status: (the first piece, a later piece). A status the audit adds later reads
#: through the ``None`` row, its id as data, until it is keyed here.
_K8_TALLY: dict[str | None, tuple[str, str]] = {
    "healthy": ("{n} healthy", ", {n} healthy"),
    "watch": ("{n} watch", ", {n} watch"),
    "degraded": ("{n} degraded", ", {n} degraded"),
    "failing": ("{n} failing", ", {n} failing"),
    None: ("{n} {status}", ", {n} {status}"),
}


#: The tables a frame's template is picked from (see ``_K2_KINDS``).
FRAME_TABLES = (_K2_KINDS, _OSM_UNKNOWN, _WIKI_UNKNOWN, _K8_TALLY)


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
        return _entry(spec, method=[_fr(
            "not measured: the source audit of {at} audited no source (none had {min} articles), so no share exists",
            at=at, min=rec.get("min_articles"))])
    if healthy is None or not isinstance(pct, (int, float)):
        return _entry(spec, method=[_fr(
            "not measured: the source audit of {at} recorded no healthy count, so no share exists", at=at)])
    tally = [_fr(_K8_TALLY.get(st, _K8_TALLY[None])[1 if i else 0], n=n, status=st)
             for i, (st, n) in enumerate(counts.items())]
    entry = _entry(spec, value=pct, n=audited, as_of=at, verdict=_NO_BAR, method=[
        _fr("{healthy} of the {audited} audited sources read as healthy ({pct}%; ", healthy=healthy, audited=audited, pct=pct),
        *tally,
        _fr("), recorded by the source audit"),
        *_ago(at),
        *([_fr(", with {n} allowlisted domain(s) capped at watch", n=rec.get("allowlisted_domains"))]
          if rec.get("allowlisted_domains") else []),
        _fr(". COHORT-RELATIVE, not absolute health: a source is healthy when none of its criteria falls in the bad tail of "
            "its same-language cohort, so a large cohort holds some sources outside healthy by construction, and a cohort "
            "under the floor ({floor} sources) gets no soft baseline; the share can move when a cohort crosses that floor "
            "with no source changing. Extraction validity, never editorial merit; each status is its own count, never "
            "blended. The per-region failing shares ride beside it to be inspected, not scored. A persisted measurement, "
            "never re-run here. The bar is ruling V1-6, so no verdict is given.", tr=("floor",), floor=_cohort_floor()),
    ])
    entry["by_region"] = rec.get("by_region") or []
    return entry


# --------------------------------------------------------------------------- K13, the verticals (row 183, R751)
# The R706 channel again for climate: a fetch writes down what it stored where it stores it, and K13 only reads that file.
# The elections block reads its two files directly instead, the way K11 reads the locale files: the shipped catalogue and
# the Wikidata snapshot the operator's networked run left on disk ARE the persisted measurement, cheap to read (one YAML,
# one JSON, cached by the snapshot's own stamp), and a copy of them written by the diagnostic would only go stale.
# Lane blocks (law, OSM, wiki) and the 0.7/0.8 verticals join the same ``verticals`` list (R751(a)): blocks under K13,
# no new K id.
_CLIMATE_FILE, _CLIMATE_SCHEMA = "vertical-climate.json", "oo-vertical-climate-1"
_CLIMATE_LOCK = threading.Lock()  # two fetches finishing together must not drop each other's dataset


def record_climate_fetch(record: dict) -> dict | None:
    """Write down one climate fetch (K13). Called by the climate fetch job once its session committed, never by the KPI GET.

    Kept per DATASET, the last fetch of each: its time, how many figures the source gave, and how many were new or revised.
    The unit fetched (a region, a GHCN station) is NOT written: this file is plaintext beside the encrypted library, and
    which station someone reads is theirs. ``figures`` 0 is kept as 0: the source answered with nothing, a fact of its own.
    A fetch is one UNIT (a region, a station) while the entry is per dataset, so the last fetch that DID bring figures is
    kept beside the last fetch: an empty answer for one station never erases the figures another station's fetch stored."""
    if not isinstance(record, dict):
        return None
    dataset = record.get("dataset")
    try:
        from src.stats.climate import DATASETS
    except Exception:  # noqa: BLE001 - without the dataset list nothing can be checked, so nothing is written
        return None
    if not isinstance(dataset, str) or dataset not in DATASETS:
        return None
    raw_tally = record.get("tally")
    tally: dict = raw_tally if isinstance(raw_tally, dict) else {}
    entry: dict = {
        "fetched_at": str(record.get("fetched_at") or _now()),
        "figures": _int_or_none(record.get("figures")),
        "new": _int_or_none(tally.get("new")),
        "revised": _int_or_none(tally.get("revised")),
    }
    with _CLIMATE_LOCK:
        prev: dict = _read_record(_CLIMATE_FILE, _CLIMATE_SCHEMA) or {}
        held = prev.get("datasets")
        datasets: dict = {k: v for k, v in held.items() if k in DATASETS and isinstance(v, dict)} if isinstance(held, dict) else {}
        earlier = datasets.get(dataset) or {}
        if isinstance(entry["figures"], int) and entry["figures"] > 0:
            entry["last_with_figures"] = {"fetched_at": entry["fetched_at"], "figures": entry["figures"]}
        elif isinstance(earlier.get("last_with_figures"), dict):
            entry["last_with_figures"] = earlier["last_with_figures"]
        datasets[dataset] = entry
        return _write_record(_CLIMATE_FILE, _CLIMATE_SCHEMA, {"datasets": dict(sorted(datasets.items()))})


def read_climate_fetches() -> dict | None:
    return _read_record(_CLIMATE_FILE, _CLIMATE_SCHEMA)


_MEDICAL_FILE, _MEDICAL_SCHEMA = "vertical-medical.json", "oo-vertical-medical-1"
_MEDICAL_COUNTS = ("cited", "cited_found", "cited_not_found", "named", "named_found", "named_not_found")


def _medical_count(v) -> int | None:
    """A new int equal to a non-negative count, or None: the value written is never the object passed in."""
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def record_medical_fetch(record: dict) -> dict | None:
    """Write down the last PubMed fetch (K13). Called by the medical fetch job once it ran, never by the KPI GET.

    COUNTS ONLY, and NLM's own public file name: which papers the corpus cites is the user's, and this file is plaintext
    beside the encrypted library, so no PMID, DOI or PMCID is ever written here. ``applied`` 0 is kept as 0 (the run read
    the listing and applied nothing: nothing was new, or the first file failed), and a failure is a yes or no: its words
    are exception text, which the task manager shows and this plaintext record does not keep."""
    if not isinstance(record, dict):
        return None
    # Every value written is an object built HERE (a fresh int, a re-serialised timestamp, a name rebuilt from
    # NLM's two sequence numbers): nothing the caller handed in is copied through to the plaintext file.
    raw_cov, raw_class = record.get("coverage"), record.get("by_class")
    cov: dict = raw_cov if isinstance(raw_cov, dict) else {}
    by_class: dict = raw_class if isinstance(raw_class, dict) else {}
    try:
        fetched_at = datetime.fromisoformat(str(record.get("fetched_at"))).isoformat()
    except (TypeError, ValueError):
        fetched_at = _now()
    m = re.fullmatch(r"pubmed([0-9]{2})n([0-9]{4})\.xml(\.gz)?", str(record.get("last_file") or ""))
    fields = {
        "fetched_at": fetched_at,
        "listed": _medical_count(record.get("listed")),
        "remaining": _medical_count(record.get("remaining")),
        "applied": _medical_count(record.get("applied")),
        "failed": record.get("failed") is True,
        "stopped": record.get("stopped") is True,
        "papers": _medical_count(record.get("papers")),
        "by_class": {k: _medical_count(by_class.get(k)) for k in ("journal", "preprint", "retracted")},
        "coverage": {k: _medical_count(cov.get(k)) for k in _MEDICAL_COUNTS},
        # A name that is not NLM's own pattern is not written: nothing but a public file name belongs here.
        "last_file": f"pubmed{int(m.group(1)):02d}n{int(m.group(2)):04d}.xml.gz" if m else None,
    }
    return _write_record(_MEDICAL_FILE, _MEDICAL_SCHEMA, fields)


def read_medical_fetch() -> dict | None:
    return _read_record(_MEDICAL_FILE, _MEDICAL_SCHEMA)


def _medical_block() -> dict:
    rec = read_medical_fetch()
    if rec is None:
        return {"vertical": "medical", "state": "not-measured", "first_slice": False,
                **_method([_fr("no PubMed fetch has been recorded on this machine (Advanced, Medical papers: Fetch records "
                               "one)")], "reason")}
    applied, failed = rec.get("applied"), rec.get("failed")
    if failed is True:
        outcome = "fetched, stopped at a file that failed (the task manager names it)"
    elif not isinstance(applied, int):
        outcome = "fetched, what it applied was not recorded"
    elif applied == 0:
        outcome = "fetched, no new update file applied"
    else:
        outcome = "fetched, applied new update files"
    cov = rec.get("coverage") if isinstance(rec.get("coverage"), dict) else {}
    block = {
        "vertical": "medical", "state": "recorded", "as_of": rec.get("fetched_at"), "age_days": _age_days(rec.get("fetched_at")),
        # The first slice is in once one update file has been applied, whatever it kept: the update files are the transport.
        "first_slice": bool(rec.get("last_file")),
        "newest_file_applied": rec.get("last_file"), "files_applied_last_run": applied, "files_listed": rec.get("listed"),
        "files_remaining": rec.get("remaining"), "stopped": rec.get("stopped"), "outcome": outcome,
        "papers_kept": rec.get("papers"), "by_class": rec.get("by_class"), "coverage": cov,
        **_method([_fr(
            "Read from the last PubMed fetch's own record: how many of NLM's update files it applied, how many remain, how "
            "many records are kept per provenance class, and how many cited paper ids were found or not found yet. Update "
            "files carry only papers NLM revised recently, so a cited paper not found here is not missing from PubMed (R750). "
            "Counts only; no id is written to the record.")]),
    }
    if not block["first_slice"]:
        block.update(_method([_fr("the last PubMed fetch has not applied an update file yet")], "reason"))
    return block


def _climate_block() -> dict:
    rec = read_climate_fetches()
    try:
        from src.stats.climate import DATASETS

        listed = len(DATASETS)
    except Exception:  # noqa: BLE001 - the count is a label; the block still reads without it
        listed = None
    datasets = (rec or {}).get("datasets")
    if rec is None or not isinstance(datasets, dict) or not datasets:
        return {"vertical": "climate", "state": "not-measured", "first_slice": False,
                **_method([_fr("no climate fetch has been recorded on this machine (the Climate tab's Fetch button records "
                               "one)")], "reason")}
    rows = []
    for name, d in sorted(datasets.items()):
        if not isinstance(d, dict):
            continue
        figures, new, revised = d.get("figures"), d.get("new"), d.get("revised")
        kept = d.get("last_with_figures") if isinstance(d.get("last_with_figures"), dict) else None
        if figures == 0:
            outcome = "source gave no figures"
        elif not isinstance(new, int) or not isinstance(revised, int):
            outcome = "fetched, what it stored was not recorded"  # never claim new figures the record does not show
        elif new == 0 and revised == 0:
            # A fetch that stored nothing new is a fetch: the source had nothing new, never "not read".
            outcome = "fetched, nothing new"
        else:
            outcome = "fetched, stored new or revised figures"
        rows.append({
            "dataset": name, "fetched_at": d.get("fetched_at"), "age_days": _age_days(d.get("fetched_at")),
            "figures": figures, "new": new, "revised": revised, "outcome": outcome,
            "last_fetch_with_figures_at": kept.get("fetched_at") if kept else None,
            "has_figures": (isinstance(figures, int) and figures > 0) or kept is not None,
        })
    if not rows:
        return {"vertical": "climate", "state": "not-measured", "first_slice": False,
                **_method([_fr("the climate fetch record holds no readable dataset entry")], "reason")}
    with_figures = sum(1 for r in rows if r["has_figures"])
    return {
        "vertical": "climate", "state": "recorded", "first_slice": with_figures > 0, "as_of": rec.get("measured_at"),
        "datasets_fetched": len(rows), "datasets_listed": listed, "datasets": rows,
        **_method([
            _fr("the last recorded fetch of each climate dataset: {n} of {listed} datasets fetched on this machine, ",
                n=len(rows), listed=listed) if listed is not None
            else _fr("the last recorded fetch of each climate dataset: {n} of the datasets fetched on this machine, ",
                     n=len(rows)),
            _fr("{with_figures} of them with figures from the source at some fetch. Each age is the fetch's own; no "
                "freshness bar is set (S08-02 S2), so no dataset is called fresh or stale.", with_figures=with_figures),
        ]),
    }


def _elections_block() -> dict:
    """The elections floor, read from the shipped catalogue and the snapshot file on disk (no fetch, no scan)."""
    from datetime import date

    from src.civic.coverage_floor import floor_coverage
    from src.events.catalog import layered_events

    today = date.today()
    events, snap = layered_events(today)  # one read, so the snapshot line and the counts agree
    rep = floor_coverage(today, events=events)
    rows = snap.get("rows")
    present = snap.get("state") == "present"
    loaded = present and isinstance(rows, int) and rows > 0
    # A snapshot on disk is a measurement even when it holds no rows (the run found nothing), the same as a climate fetch
    # whose source gave no figures: recorded, but no first slice. Only an absent or unreadable snapshot is "not measured".
    block = {
        "vertical": "elections", "state": "recorded" if present else "not-measured", "first_slice": loaded,
        "as_of": snap.get("as_of") if present else None,
        "floor_countries": rep.get("floor_countries"), "covered": rep.get("covered_n"),
        "only_passed_projection": rep.get("only_passed_projection_n"),
        "present_but_dateless": rep.get("present_but_dateless_n"), "missing": rep.get("missing_n"),
        "floor_as_of": rep.get("as_of"),
        "snapshot_state": snap.get("state"), "snapshot_as_of": snap.get("as_of"),
        # Age and staleness as the snapshot's own reading states them (row 258), computed in one place
        # (calendar_report.with_snapshot), so this block and the Agenda never disagree on a day boundary.
        "snapshot_age_days": snap.get("age_days") if present else None,
        "snapshot_stale": snap.get("stale") if present else None,
        "snapshot_stale_after_days": snap.get("stale_after_days") if present else None,
        "snapshot_rows": rows,
        **_method([_fr(
            "the elections floor diagnostic's own counts over the shipped catalogue layered with the Wikidata "
            "snapshot on disk, each state apart (covered, only a passed projection, present but dateless, "
            "missing). The first slice is the snapshot, so the vertical counts as ingested only when a snapshot "
            "with rows is present; the shipped catalogue alone is not an ingest. Read from files, never fetched.")]),
    }
    if not present:
        block.update(_method([_fr("no readable Wikidata election snapshot on this machine (state: {state}); the "
                                  "operator's networked run writes one", state=snap.get("state"))], "reason"))
    elif not loaded:
        block.update(_method([_fr("the Wikidata election snapshot on this machine holds no rows, so there is no first "
                                  "slice")], "reason"))
    return block


# --------------------------------------------------------------------------- K13, the law lane (row 184, R751(a))
# The law coverage report is computed on demand over every tracked document, so it is never run on the GET: the route that
# makes it (the /law-coverage diagnostic, which the all-diagnostics bundle also calls) writes down its counts here.
_LAW_FILE, _LAW_SCHEMA = "lane-law-coverage.json", "oo-lane-law-coverage-1"


def record_law_coverage(report: dict) -> dict | None:
    """Write down what a law coverage report counted (K13's law block). Called by the route that makes it, never by the
    KPI GET. Counts only: no jurisdiction, country or document is named, and nothing is divided."""
    if not isinstance(report, dict) or "documents" not in report:
        return None
    raw_rows = report.get("jurisdictions")
    rows = [j for j in raw_rows if isinstance(j, dict)] if isinstance(raw_rows, list) else []
    def _hours(v) -> float | None:  # a finite, real number of hours; a check stamped in the future (clock skew) is age 0
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return None
        return max(float(v), 0.0)

    olds = [h for j in rows if (h := _hours(j.get("oldest_check_age_hours"))) is not None]
    news = [h for j in rows if (h := _hours(j.get("newest_check_age_hours"))) is not None]
    raw_floor = report.get("floor")
    floor: dict = raw_floor if isinstance(raw_floor, dict) else {}
    by_state = floor.get("by_state") if isinstance(floor.get("by_state"), dict) else None
    floor_state = floor.get("state") if isinstance(floor.get("state"), str) else None
    counts: dict | None = None
    if by_state is not None:
        # A null state is one the report did not look up (row 272: an unread catalogue): kept as null, never dropped or 0.
        counts = {str(k): (len(v) if isinstance(v, list) else None) for k, v in by_state.items() if isinstance(v, list) or v is None}
        if floor_state == "unchecked":
            # The catalogue could not be read, so the states that need it were never looked up: unknown, never 0.
            # Only what the database says (tracked) and the unchecked bucket itself are counts.
            counts = {k: (v if k in ("tracked", "unchecked") else None) for k, v in counts.items()}
    raw_catalog = report.get("catalog")
    catalog: dict = raw_catalog if isinstance(raw_catalog, dict) else {}
    return _write_record(_LAW_FILE, _LAW_SCHEMA, {
        "documents": _int_or_none(report.get("documents")),
        "baselined": _int_or_none(report.get("baselined")),
        "jurisdictions": len(rows),
        "never_checked": sum(j["never_checked"] for j in rows if _int_or_none(j.get("never_checked")) is not None),
        # Hours since a document was last checked, across jurisdictions: the most-neglected and the most-recent, each apart.
        "oldest_check_age_hours": max(olds) if olds else None,
        "newest_check_age_hours": min(news) if news else None,
        "catalog_readable": catalog.get("readable") if isinstance(catalog.get("readable"), bool) else None,
        "floor_state": floor_state,
        "floor_by_state": counts,
    })


def read_law_coverage() -> dict | None:
    return _read_record(_LAW_FILE, _LAW_SCHEMA)


def _law_block() -> dict:
    rec = read_law_coverage()
    if rec is None:
        return {"vertical": "law", "kind": "lane", "state": "not-measured", "first_slice": False,
                **_method([_fr("no law coverage report has run on this machine (run the law coverage diagnostic, or take "
                               "an all-diagnostics bundle)")], "reason")}
    docs = rec.get("documents")
    floor = rec.get("floor_by_state")
    floor_n = sum(v for v in floor.values() if isinstance(v, int)) if isinstance(floor, dict) else None
    tracked = floor.get("tracked") if isinstance(floor, dict) else None
    unchecked = rec.get("floor_state") == "unchecked"
    block = {
        "vertical": "law", "kind": "lane", "state": "recorded",
        "first_slice": isinstance(docs, int) and docs > 0, "as_of": rec.get("measured_at"),
        "documents": docs, "baselined": rec.get("baselined"), "jurisdictions": rec.get("jurisdictions"),
        "never_checked": rec.get("never_checked"),
        "oldest_check_age_hours": rec.get("oldest_check_age_hours"),
        "newest_check_age_hours": rec.get("newest_check_age_hours"),
        "catalog_readable": rec.get("catalog_readable"), "floor_state": rec.get("floor_state"),
        "floor_by_state": floor,
        **_method([
            _fr("the last law coverage report's own counts: {docs} tracked documents in {jur} jurisdictions; of the "
                "{floor_n} countries on the language floor, {tracked} are tracked, ", tr=("floor_n", "tracked"),
                docs=docs, jur=rec.get("jurisdictions"), floor_n=floor_n if floor_n is not None else "unknown number of",
                tracked=tracked if tracked is not None else "an unknown number"),
            _fr("and the other states are unknown: the law catalogue could not be read, so they were never looked up. ")
            if unchecked else _fr("each other state counted apart. "),
            _fr("A tracked-document count is an entry point, never a coverage claim, and nothing is divided. The check "
                "ages are the report's own, from when it ran."),
        ]),
    }
    if not block["first_slice"]:
        block.update(_method([_fr("the last law coverage report counted no tracked document")], "reason"))
    return block


# --------------------------------------------------------------------------- K13, the OSM lane (row 184, R751(a))
# The OSM change-file member reads the lane store on demand when a diagnostics bundle is built; it writes its counts here as it
# reads them. Never a country code: which countries an operator follows is theirs, so only how many.
_OSM_FILE, _OSM_SCHEMA = "lane-osm.json", "oo-lane-osm-1"


def record_osm_lane(rows: list | None) -> dict | None:
    """Write down what the OSM change-file member counted (K13's OSM block). ``rows`` is the member's per-country rows, or
    ``None`` when no OSM lane exists on this install. Counts and the newest applied time only; nothing is divided."""
    if rows is None:
        return _write_record(_OSM_FILE, _OSM_SCHEMA, {"lane": "absent", "countries": 0})
    if not isinstance(rows, list):
        return None
    rs = [r for r in rows if isinstance(r, dict)]

    def _known(key: str) -> tuple[int | None, int]:
        # (sum over the countries whose table answered, the countries whose table did not). When none answered, the sum is
        # unknown (None), never 0: an old lane that cannot say is not a lane with no change file.
        vals = [_int_or_none(r.get(key)) for r in rs]
        known = [v for v in vals if v is not None]
        return (sum(known) if known or not rs else None), len(vals) - len(known)

    diffs, diffs_unknown = _known("diffs_recorded")
    gaps, gaps_unknown = _known("gaps_total")
    statuses: dict = {}
    for r in rs:
        st = r.get("status") if isinstance(r.get("status"), str) else "unknown"
        statuses[st] = statuses.get(st, 0) + 1
    applied = [(age, a) for r in rs if isinstance(a := r.get("last_applied_at"), str) and (age := _age_days(a)) is not None]
    return _write_record(_OSM_FILE, _OSM_SCHEMA, {
        "lane": "present",
        "countries": len(rs),
        "countries_by_status": dict(sorted(statuses.items())),
        "countries_with_change_files": sum(1 for r in rs if (_int_or_none(r.get("diffs_recorded")) or 0) > 0),
        "change_files_recorded": diffs,
        "countries_change_files_unknown": diffs_unknown,
        "gaps_total": gaps,
        "countries_gaps_unknown": gaps_unknown,
        "newest_change_file_applied_at": min(applied, key=lambda p: p[0])[1] if applied else None,
    })


def read_osm_lane() -> dict | None:
    return _read_record(_OSM_FILE, _OSM_SCHEMA)


def _osm_method(rec: dict, complete_n: int) -> list[dict]:
    def n(key: str) -> str:  # a count as recorded, or "an unknown number of" for anything a hand edit left that is not one
        v = _int_or_none(rec.get(key))
        return str(v) if v is not None else "an unknown number of"

    unknown: list[dict] = []
    for key, pair in _OSM_UNKNOWN.items():
        k = _int_or_none(rec.get(key))
        if k:
            unknown.append(_fr(pair[1 if unknown else 0], k=k))
    return [
        _fr("the OSM change-file member's own counts, from its last read of the lane store: {countries} countries listed, "
            "{complete} of them cut to completion; {diffs} daily change files recorded over {with_files} countries, "
            "{gaps} gaps", tr=("countries", "diffs", "with_files", "gaps"), countries=n("countries"), complete=complete_n,
            diffs=n("change_files_recorded"), with_files=n("countries_with_change_files"), gaps=n("gaps_total")),
        *unknown,
        _fr("). A first slice is one country cut to completion. No country is named; nothing is divided.") if unknown
        else _fr(". A first slice is one country cut to completion. No country is named; nothing is divided."),
    ]


def _osm_block() -> dict:
    rec = read_osm_lane()
    if rec is None:
        return {"vertical": "osm", "kind": "lane", "state": "not-measured", "first_slice": False,
                **_method([_fr("no OpenStreetMap change-file record has been read on this machine (take an all-diagnostics "
                               "bundle)")], "reason")}
    if rec.get("lane") == "absent":
        return {"vertical": "osm", "kind": "lane", "state": "recorded", "first_slice": False, "as_of": rec.get("measured_at"),
                "lane": "absent", "countries": 0,
                **_method([_fr("the OSM change-file member's own read of the lane store: no OSM lane exists on this "
                               "install.")]),
                **_method([_fr("no OpenStreetMap country has been cut on this install")], "reason")}
    raw_status = rec.get("countries_by_status")
    by_status: dict = raw_status if isinstance(raw_status, dict) else {}
    complete_n: int = _int_or_none(by_status.get("complete")) or 0
    countries = rec.get("countries")
    block = {
        "vertical": "osm", "kind": "lane", "state": "recorded", "first_slice": complete_n > 0,
        "as_of": rec.get("measured_at"), "lane": "present",
        "countries": countries, "countries_by_status": by_status,
        "countries_with_change_files": rec.get("countries_with_change_files"),
        "change_files_recorded": rec.get("change_files_recorded"),
        "countries_change_files_unknown": rec.get("countries_change_files_unknown"),
        "gaps_total": rec.get("gaps_total"), "countries_gaps_unknown": rec.get("countries_gaps_unknown"),
        "newest_change_file_applied_at": rec.get("newest_change_file_applied_at"),
        **_method(_osm_method(rec, complete_n)),
    }
    if not block["first_slice"]:
        block.update(_method([_fr("no OpenStreetMap country has been cut to completion")], "reason"))
    return block


# --------------------------------------------------------------------------- K13, the wiki lane (row 184, R751(a))
# The per-edition coverage report reads the wiki lane on demand (Living sources, the lane counters, the soak and release runs, the
# diagnostics bundle); it writes its counts here as it makes them. Never an edition code: only how many.
_WIKI_FILE, _WIKI_SCHEMA = "lane-wiki.json", "oo-lane-wiki-1"


def record_wiki_coverage(rows: list | None, measured: bool) -> dict | None:
    """Write down what a per-edition wiki coverage report counted (K13's wiki block). ``rows`` are the report's per-edition rows
    (before any compact trim); ``measured`` is the report's own. Counts and the newest event time only; nothing is divided."""
    if not isinstance(rows, list) or not isinstance(measured, bool):
        return None
    rs = [r for r in rows if isinstance(r, dict)]

    def _count(r: dict, key: str) -> int | None:
        return _int_or_none(r.get(key))

    def _text(r: dict, key: str) -> int | None:
        ft = r.get("full_text")
        return _int_or_none(ft.get(key)) if isinstance(ft, dict) else None

    def _sum(vals: list) -> int | None:  # the sum of what is known; when nothing is (or no edition ran), unknown (None), never 0
        known = [v for v in vals if v is not None]
        return sum(known) if known else None

    def _sum_all(vals: list) -> int | None:  # an UPPER bound is only one when every part is known: a partial sum may sit below the lower
        return sum(vals) if vals and all(v is not None for v in vals) else None

    ran = [r for r in rs if r.get("has_run") is True]
    pages = [_count(r, "pages_seen") for r in ran]
    hot = [_text(r, "hot_pages_with_text") for r in ran]
    warm = [_text(r, "warm_pages_with_text") for r in ran]
    totals = [_count(r, "edition_articles") for r in ran]
    gaps = [_int_or_none(r["gaps"].get("total")) if isinstance(r.get("gaps"), dict) else None for r in ran]
    events = [(age, e) for r in ran if isinstance(e := r.get("last_event_recorded_at"), str) and (age := _age_days(e)) is not None]
    return _write_record(_WIKI_FILE, _WIKI_SCHEMA, {
        "measured": measured,
        "editions_listed": len(rs),
        "editions_with_a_run": len(ran),
        "editions_with_pages_seen": sum(1 for v in pages if v),
        "editions_with_text": sum(1 for h, w in zip(hot, warm, strict=True) if h or w),
        "editions_walk_complete": sum(1 for r in ran if r.get("walk_complete") is True),
        "pages_seen": _sum(pages),
        "editions_pages_unknown": sum(1 for v in pages if v is None),
        "edition_articles": _sum(totals),
        "editions_without_total": sum(1 for v in totals if v is None),
        # HOT and WARM may both hold one page (a promotion keeps its WARM row): the report's own two bounds, summed per edition.
        "pages_with_text_lower_bound": _sum([max(h or 0, w or 0) if (h is not None or w is not None) else None
                                             for h, w in zip(hot, warm, strict=True)]),
        "pages_with_text_upper_bound": _sum_all([h + w if h is not None and w is not None else None
                                                 for h, w in zip(hot, warm, strict=True)]),
        "editions_text_bound_unknown": sum(1 for h, w in zip(hot, warm, strict=True) if h is None or w is None),
        "gaps_total": _sum(gaps),
        "newest_event_recorded_at": min(events, key=lambda p: p[0])[1] if events else None,
        # The stream's last events could not be read for these: their newest event is unknown, not "none".
        "editions_event_unreadable": sum(1 for r in ran if r.get("last_event_unreadable") is True),
    }, fsync=False)  # rebuilt by the next report (every Living sources poll reads one): never worth a flush on a GET


def read_wiki_coverage() -> dict | None:
    return _read_record(_WIKI_FILE, _WIKI_SCHEMA)


def _wiki_method(rec: dict) -> list[dict]:
    def n(key: str) -> str:  # a count as recorded, or "an unknown number of" for anything a hand edit left that is not one
        v = _int_or_none(rec.get(key))
        return str(v) if v is not None else "an unknown number of"

    unknown: list[dict] = []
    for key, pair in _WIKI_UNKNOWN.items():
        k = _int_or_none(rec.get(key))
        if k:
            unknown.append(_fr(pair[1 if unknown else 0], k=k))
    lo, up = _int_or_none(rec.get("pages_with_text_lower_bound")), _int_or_none(rec.get("pages_with_text_upper_bound"))
    if lo is not None and up is not None and up >= lo:
        text = _fr("between {lo} and {up} pages with a text (a page promoted from WARM to HOT may be counted twice)",
                   lo=lo, up=up)
    elif lo is not None:
        text = _fr("at least {lo} pages with a text (the upper bound is unknown while an edition's WARM count is)", lo=lo)
    else:
        text = _fr("an unknown number of pages with a text")
    return [
        _fr("the per-edition wiki coverage report's own counts, from its last read of the lane: {ran} of {listed} editions "
            "listed have run; {with_pages} have pages seen and {with_text} hold a text; {pages} pages seen, ",
            tr=("ran", "listed", "with_pages", "with_text", "pages"), ran=n("editions_with_a_run"),
            listed=n("editions_listed"), with_pages=n("editions_with_pages_seen"), with_text=n("editions_with_text"),
            pages=n("pages_seen")),
        text,
        _fr(", {gaps} gaps", tr=("gaps",), gaps=n("gaps_total")),
        *unknown,
        _fr("). A first slice is one edition with pages seen or a stored text. No edition is named; nothing is divided.")
        if unknown else
        _fr(". A first slice is one edition with pages seen or a stored text. No edition is named; nothing is divided."),
    ]


def _wiki_block() -> dict:
    rec = read_wiki_coverage()
    if rec is None:
        return {"vertical": "wiki", "kind": "lane", "state": "not-measured", "first_slice": False,
                **_method([_fr("no wiki coverage report has read a wiki lane on this machine (the lane has never run, or "
                               "no report has been taken since: Living sources, the lane counters or an all-diagnostics "
                               "bundle make one)")], "reason")}
    pages_n = _int_or_none(rec.get("editions_with_pages_seen")) or 0
    text_n = _int_or_none(rec.get("editions_with_text")) or 0
    keys = ("measured", "editions_listed", "editions_with_a_run", "editions_with_pages_seen", "editions_with_text",
            "editions_walk_complete", "pages_seen", "editions_pages_unknown", "edition_articles", "editions_without_total",
            "pages_with_text_lower_bound", "pages_with_text_upper_bound", "editions_text_bound_unknown", "gaps_total",
            "newest_event_recorded_at", "editions_event_unreadable")
    block = {"vertical": "wiki", "kind": "lane", "state": "recorded", "first_slice": pages_n > 0 or text_n > 0,
             "as_of": rec.get("measured_at"), **{k: rec.get(k) for k in keys}, **_method(_wiki_method(rec))}
    if not block["first_slice"]:
        block.update(_method([_fr("the last wiki coverage report counted no edition with pages seen or a stored text")],
                             "reason"))
    return block


def _k13_verticals(spec: dict) -> dict:
    """K13: one block per vertical and per lane (R751(a)), read from what each recorded. The value is a COUNT (blocks whose
    first slice is in), with n = the blocks listed; never a share, never a blend of their figures."""
    blocks = []
    for name, build in (("climate", _climate_block), ("elections", _elections_block), ("law", _law_block),
                        ("medical", _medical_block), ("osm", _osm_block), ("wiki", _wiki_block)):
        try:
            blocks.append(build())
        except Exception as exc:  # noqa: BLE001 - one vertical's fault never hides the others
            blocks.append({"vertical": name, "state": "not-measured", "first_slice": False,
                           **_method([_fr("its block could not be read ({error})", error=type(exc).__name__)], "reason")})
    recorded = [b for b in blocks if b["state"] == "recorded"]
    if not recorded:
        entry = _entry(spec)
        entry["verticals"] = blocks
        return entry
    ingested = [b["vertical"] for b in blocks if b["first_slice"]]
    # The newest of the blocks' own dates (a fetch time, a snapshot date): compared by age, since the two are not one format.
    # A date in the future (clock skew) is not "newer" than today's: its age counts as 0.
    dated = [(max(age, 0.0), b.get("as_of")) for b in recorded if (age := _age_days(b.get("as_of"))) is not None]
    as_of = min(dated, key=lambda pair: pair[0])[1] if dated else None
    entry = _entry(spec, value=len(ingested), n=len(blocks), as_of=as_of, verdict=_NO_BAR, method=[
        # The names are the blocks' own ids (data); each block below draws its translated name.
        _fr("{n} of the {total} verticals and lanes listed have a first slice in ({names}); ", n=len(ingested),
            total=len(blocks), names=", ".join(ingested)) if ingested
        else _fr("{n} of the {total} verticals and lanes listed have a first slice in (none); ", n=len(ingested),
                 total=len(blocks)),
        _fr("each block below carries its own figures, date and method, read from what it recorded where it measured. A "
            "count, not a score: the blocks are never blended. A persisted measurement, never fetched or re-run here. The "
            "bar is open (Q1017 = a, S08-02 S2), so no verdict is given."),
    ])
    entry["verticals"] = blocks
    return entry


_RESOLVERS = {"K2": _k2_latency, "K5": _k5_noise, "K6": _k6_coverage, "K7": _k7_dates, "K8": _k8_sources, "K11": _k11_i18n,
              "K13": _k13_verticals}


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
            metrics.append(_entry(spec, method=[_fr("resolver error (not-measurable): {error}", error=type(exc).__name__)]))
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

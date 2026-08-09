"""
What the background AI is actually doing — read from what it already records.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-09: *"let's make a collapsed 'details' section giving details
about what exactly has been done by the AI background metadata enhancement. Let's make
it a live feed with details about latest detected keywords, languages, and so forth, and
the amount total for each category, and the remaining amount. Let's add an important
figure to these: article processing per hour (per category + total)."*

THIS IS A READER, NOT A RECORDER, and the difference was the finding. Three of the four
sweeps already append a per-batch JSONL record — with ``started_at`` AND ``finished_at``
— *while the run is in flight*, alongside detail records carrying the values they found.
The clock and the findings have been on disk all along. What did not exist was anything
that reads them: ``last_*_report`` parses a header, a footer and a line count, and the
only other route to the detail records is downloading the whole log. So the honest fix is
a bounded tail reader over records that already exist, not a fifth instrument.

TWO RATES, BOTH REAL, NEVER ONE. Under the coordinator the sweeps take turns, so a
sweep's articles-per-hour has two different honest answers and publishing only one would
mislead in opposite directions:

  * ``while_working_per_hour`` — items divided by the summed batch durations. The
    model's own speed. Answers "would a faster model help?".
  * ``wall_clock_per_hour`` — items divided by first-start-to-last-finish. What the
    corpus actually gains per hour, including every gap where this sweep was waiting its
    turn. Answers "when will this finish?".

They diverge by exactly the duty cycle, which is the thing a GPU sitting at 20% is
about. Reporting the first as though it were the second would promise a completion date
the machine cannot keep; reporting the second as the model's speed would blame the model
for the scheduler.

BOUNDED BY CONSTRUCTION. Each log is read from its END, at most ``tail_bytes``, seeking
rather than materialising: a reader with no ceiling of its own is how a 1.6 GB journal
turned an app into an OOM at boot, and that ceiling has to be the reader's own rather
than an assumption about the writer. The first line of a tail is usually a fragment and
is dropped. The window that survives is STATED (``window``), so a figure over the last
few batches is never read as a figure over the run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "oo-ai-activity-1"

#: How much of each log's tail to read. Generous enough to hold many batches of the
#: largest record type (source-tags details carry up to 20 evidence terms per domain),
#: small enough that reading four of them is trivial next to one model call.
DEFAULT_TAIL_BYTES = 256 * 1024

#: How many recently-found items to surface per sweep. The feed is a window onto live
#: work, not an export -- the download button remains the way to get everything.
DEFAULT_RECENT = 12


# --------------------------------------------------------------------------- #
#  bounded reading
# --------------------------------------------------------------------------- #
def read_tail_records(path: Path, *, tail_bytes: int = DEFAULT_TAIL_BYTES) -> list[dict]:
    """The JSON objects in the last ``tail_bytes`` of a JSONL file.

    Never reads the whole file: an AI sweep left running for days writes a log whose
    size is proportional to how much there was to report, so the reader needs its own
    ceiling. A leading fragment (the tail almost never starts on a line boundary) and
    any unparseable line are dropped rather than raising -- a half-written last line is
    the normal state of a file being appended to right now."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    out: list[dict] = []
    try:
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop the partial first line
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return out
    return out


def newest_log(directory: Path, prefix: str) -> Path | None:
    """The most recent ``<prefix>*.jsonl`` in ``directory``, by name.

    By NAME, not mtime: the names carry a sortable UTC stamp, and a coordinator turn
    appends to an older run's log, which would make mtime pick a file the operator
    would not call the current one."""
    try:
        files = sorted(p for p in directory.glob(f"{prefix}*.jsonl") if p.is_file())
    except OSError:
        return None
    return files[-1] if files else None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
#  rates
# --------------------------------------------------------------------------- #
def rates_from_batches(batches: list[dict], *, item_key: str) -> dict:
    """The two honest rates over the batches present in the tail.

    ``item_key`` names which count in a batch record is the unit of work, because the
    sweeps do not share one: triage judges keywords, source-tags judges domains,
    perception-extract processes articles. Dividing them all by "articles" would put
    three different units under one label."""
    timed: list[tuple[datetime, datetime, float]] = []
    for b in batches:
        start, end = _parse_ts(b.get("started_at")), _parse_ts(b.get("finished_at"))
        n = b.get(item_key)
        if start is None or end is None or not isinstance(n, (int, float)):
            continue
        timed.append((start, end, float(n)))
    if not timed:
        return {
            "measurable": False,
            "reason": (
                "no batch in the readable tail carries both a start and a finish time"
            ),
        }
    items = sum(n for _s, _e, n in timed)
    working_s = sum(max(0.0, (e - s).total_seconds()) for s, e, _n in timed)
    span_s = max(0.0, (max(e for _s, e, _n in timed) - min(s for s, _e, _n in timed)).total_seconds())

    def _per_hour(seconds: float) -> float | None:
        # A sub-second window over a couple of batches would divide into a number with
        # four digits of implied precision it has not earned. Below a second we simply
        # do not have a rate yet.
        return round(items / seconds * 3600, 1) if seconds >= 1.0 and items else None

    return {
        "measurable": True,
        "batches": len(timed),
        "items": int(items),
        "item_unit": item_key,
        "working_s": round(working_s, 1),
        "span_s": round(span_s, 1),
        "while_working_per_hour": _per_hour(working_s),
        "wall_clock_per_hour": _per_hour(span_s),
        "window_from": min(s for s, _e, _n in timed).isoformat(timespec="seconds"),
        "window_to": max(e for _s, e, _n in timed).isoformat(timespec="seconds"),
        "method": (
            "while_working = items / summed batch durations (the model's own speed); "
            "wall_clock = items / first-start-to-last-finish (what the corpus gains, "
            "including every gap where this sweep waited its turn). Over the batches in "
            "the readable tail of the current log, not the whole run."
        ),
    }


# --------------------------------------------------------------------------- #
#  per-sweep readers
# --------------------------------------------------------------------------- #
def _state_file(directory: Path, name: str) -> dict:
    try:
        return json.loads((directory / name).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _triage_activity(directory: Path, *, tail_bytes: int, recent: int) -> dict:
    log = newest_log(directory, "oo-keyword-triage-")
    out: dict[str, Any] = {
        "key": "keyword_triage",
        "label": "Keyword triage",
        "unit": "keywords",
        "state": _state_file(directory, "triage_progress_state.json"),
    }
    if log is None:
        out["running_log"] = None
        out["note"] = "no run log yet — this sweep has not run on this machine"
        return out
    out["running_log"] = log.name
    records = read_tail_records(log, tail_bytes=tail_bytes)
    batches = [r for r in records if r.get("schema") == "oo-keyword-triage-batch-1"]
    out["rates"] = rates_from_batches(batches, item_key="verdicts_out")
    found: list[dict] = []
    for rec in reversed(records):
        if rec.get("schema") != "oo-keyword-triage-verdicts-1":
            continue
        verdicts = rec.get("verdicts")
        if not isinstance(verdicts, dict):
            continue
        for term, v in reversed(list(verdicts.items())):
            if len(found) >= recent:
                break
            item = {"term": term}
            if isinstance(v, dict):
                item["verdict"] = v.get("verdict")
                item["kind"] = v.get("kind")
            found.append(item)
        if len(found) >= recent:
            break
    out["latest"] = found
    return out


def _source_tags_activity(directory: Path, *, tail_bytes: int, recent: int) -> dict:
    log = newest_log(directory, "oo-source-tags-")
    out: dict[str, Any] = {
        "key": "source_tags",
        "label": "Source tags",
        "unit": "sources",
        "state": _state_file(directory, "source_tags_progress_state.json"),
    }
    if log is None:
        out["running_log"] = None
        out["note"] = "no run log yet — this sweep has not run on this machine"
        return out
    out["running_log"] = log.name
    records = read_tail_records(log, tail_bytes=tail_bytes)
    batches = [r for r in records if r.get("schema") == "oo-source-tags-batch-1"]
    out["rates"] = rates_from_batches(batches, item_key="sources_in")
    found = []
    for rec in reversed(records):
        if rec.get("schema") != "oo-source-tags-detail-1" or len(found) >= recent:
            continue
        found.append({
            "domain": rec.get("domain"),
            "tags": rec.get("proposed_tags"),
            "status": rec.get("status"),
            "reason": rec.get("reason"),
        })
    out["latest"] = found
    return out


def _perception_activity(directory: Path, *, tail_bytes: int, recent: int) -> dict:
    log = newest_log(directory, "oo-perception-extract-")
    out: dict[str, Any] = {
        "key": "perception_extract",
        "label": "Who / where / when",
        "unit": "articles",
        "state": _state_file(directory, "perception_extract_progress_state.json"),
    }
    if log is None:
        out["running_log"] = None
        out["note"] = "no run log yet — this sweep has not run on this machine"
        return out
    out["running_log"] = log.name
    records = read_tail_records(log, tail_bytes=tail_bytes)
    batches = [r for r in records if r.get("schema") == "oo-perception-extract-batch-1"]
    out["rates"] = rates_from_batches(batches, item_key="attempted")
    # This sweep's batch records carry COUNTS only; what it found is in ai_keyword rows.
    # Said rather than left as an empty list, which would read as "it found nothing".
    out["latest"] = []
    out["latest_note"] = (
        "The extracted names, places and dates are stored as AI-layer candidates rather "
        "than written to the log, so they are read from the corpus below."
    )
    return out


def _langdetect_activity(directory: Path) -> dict:
    """Langdetect is the one sweep with no per-batch record — its state file is a single
    blob, overwritten, and written only when the run ENDS. So its rate cannot come from
    a log, and saying so is better than deriving one from a single timestamp."""
    state = _state_file(directory.parent, "langdetect_state.json")
    return {
        "key": "langdetect",
        "label": "Language detection",
        "unit": "articles",
        "state": state,
        "running_log": None,
        "rates": {
            "measurable": False,
            "reason": (
                "this sweep writes one summary when a run ends, not a record per batch, "
                "so there is no series in a log to measure. Its per-hour figure comes "
                "from the stored results themselves below."
            ),
        },
        "latest": [],
    }


# --------------------------------------------------------------------------- #
#  the corpus side: what actually landed, and when
# --------------------------------------------------------------------------- #
#: The AI-layer kinds a background sweep writes, and the category each belongs to.
AI_KINDS = {
    "language": "langdetect",
    "ai-who": "perception_extract",
    "ai-place": "perception_extract",
    "ai-date": "perception_extract",
}


def stored_activity(session, *, recent: int = DEFAULT_RECENT, hours: int = 24) -> dict:
    """What the sweeps have actually WRITTEN, from ``ai_keyword`` itself.

    This is the other half, and for langdetect it is the only half: the row's own
    ``created_at`` is the per-item clock, so it answers both "what was found lately" and
    "how many per hour" for the sweeps that store their results.

    Bounded: ``recent`` rows per kind, and the rate is over a stated recent window.
    ``created_at`` is nullable and un-indexed, so rows without one are counted as
    unclocked rather than dropped or dated."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from src.database.models import AiKeyword

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=max(1, hours))
    out: dict[str, Any] = {"window_hours": max(1, hours), "kinds": []}
    for kind, category in AI_KINDS.items():
        rows = list(
            session.execute(
                select(AiKeyword.term, AiKeyword.language, AiKeyword.created_at)
                .where(AiKeyword.kind == kind)
                .order_by(AiKeyword.id.desc())
                .limit(max(1, recent))
            )
        )
        in_window = session.execute(
            select(func.count())
            .select_from(AiKeyword)
            .where(AiKeyword.kind == kind, AiKeyword.created_at >= since)
        ).scalar() or 0
        total = session.execute(
            select(func.count()).select_from(AiKeyword).where(AiKeyword.kind == kind)
        ).scalar() or 0
        out["kinds"].append({
            "kind": kind,
            "category": category,
            "total": int(total),
            "in_window": int(in_window),
            # A count over a window IS a rate, and this one needs no assumption. Zero
            # is published as zero, not as None: we looked, over a stated window, and
            # the answer was none — which is a measurement. "Never ran" is carried by
            # `total` being 0 as well, so the two cases stay distinguishable.
            "per_hour": round(in_window / max(1, hours), 1),
            "latest": [
                {
                    "term": t,
                    "language": lang,
                    "at": c.isoformat(timespec="seconds") if c else None,
                }
                for t, lang, c in rows
            ],
        })
    out["method"] = (
        "Counts of AI-layer candidate rows by kind: the total ever stored, and how many "
        "carry a created_at inside the window. per_hour is that count divided by the "
        "window — a real count over real time, not an extrapolation."
    )
    out["caveat"] = (
        "These are AI-derived candidates, never the trusted rule-based index. A row "
        "whose created_at is absent (older rows predate the column being filled) counts "
        "toward the total and not toward the window."
    )
    return out


# --------------------------------------------------------------------------- #
#  the whole picture
# --------------------------------------------------------------------------- #
def recent_activity(
    *,
    session=None,
    directory: Path | None = None,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
    recent: int = DEFAULT_RECENT,
    hours: int = 24,
) -> dict:
    """One payload for the Settings "Details" feed and the diagnostics bundle."""
    if directory is None:
        from src.paths import data_dir

        directory = Path(data_dir()) / "triage"
    directory = Path(directory)

    sweeps = [
        _triage_activity(directory, tail_bytes=tail_bytes, recent=recent),
        _source_tags_activity(directory, tail_bytes=tail_bytes, recent=recent),
        _perception_activity(directory, tail_bytes=tail_bytes, recent=recent),
        _langdetect_activity(directory),
    ]

    stored: dict[str, Any]
    if session is None:
        stored = {
            "available": False,
            "reason": "no database session was supplied to this reader",
        }
    else:
        try:
            stored = {"available": True, **stored_activity(session, recent=recent, hours=hours)}
        except Exception as exc:  # noqa: BLE001 - a degraded half must not blank the feed
            stored = {
                "available": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "log_directory": str(directory),
        "tail_bytes": tail_bytes,
        "sweeps": sweeps,
        "stored": stored,
        "coordinator": _coordinator_view(),
        "caveat": (
            "Read from the tail of each sweep's current log, so the figures cover the "
            "batches still on disk rather than the whole run, and the window each "
            "covers is stated beside it. Every value here is an AI-derived candidate — "
            "the trusted keyword index is built by rule, never by a model."
        ),
    }


def _coordinator_view() -> dict:
    """The lane's own state, plus the reason a sweep can look idle while working.

    The coordinator calls each member's job FUNCTION directly rather than through that
    member's registered BackgroundJob, so while the lane is driving a sweep, that
    sweep's own status endpoint reports ``idle`` with no result. Anyone reading these
    per-sweep surfaces needs that stated, or a busy machine reads as a stopped one."""
    view: dict[str, Any] = {
        "note": (
            "While the background lane is driving a sweep, that sweep's own job status "
            "reads idle — the lane runs members directly rather than through their "
            "registered jobs. The figures here come from the sweeps' logs, so they stay "
            "true either way."
        )
    }
    try:
        # Through the JOB REGISTRY, not by importing the API module: a reader in the
        # ai_layer reaching up into src.api would invert the layering, and the registry
        # is the lookup that already exists for exactly this.
        from src.jobs.background import get_job

        job = get_job("ai-coordinator")
        view["status"] = job.status() if job is not None else None
        if job is None:
            view["status_reason"] = (
                "the lane's job is registered lazily when it is first started, and it "
                "has not been started in this process"
            )
    except Exception as exc:  # noqa: BLE001 - the lane's absence is not the feed's failure
        view["status"] = None
        view["status_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return view


# --------------------------------------------------------------------------- #
#  Selftest (recursive-loop harness)
# --------------------------------------------------------------------------- #
def run_activity_selftest() -> dict:
    """Prove the reader is bounded and the two rates really differ, on a fixture."""
    import tempfile

    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        log = d / "oo-perception-extract-20260101-000000-000000.jsonl"
        # Two batches, each 10 s of work, 100 s apart: the model's own speed and what
        # the corpus gains differ by an order of magnitude, which is the whole point.
        lines = [
            {"schema": "oo-perception-extract-run-1", "started_at": "2026-01-01T00:00:00"},
            {"schema": "oo-perception-extract-batch-1", "batch": 0, "attempted": 10,
             "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:10"},
            {"schema": "oo-perception-extract-batch-1", "batch": 1, "attempted": 10,
             "started_at": "2026-01-01T00:01:40", "finished_at": "2026-01-01T00:01:50"},
        ]
        log.write_text(
            "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8"
        )
        got = _perception_activity(d, tail_bytes=DEFAULT_TAIL_BYTES, recent=5)
        rates = got.get("rates", {})
        _check("rates are measurable from the real record shape", rates.get("measurable") is True,
               detail=str(rates.get("reason", "")))
        _check("both rates are published",
               rates.get("while_working_per_hour") is not None
               and rates.get("wall_clock_per_hour") is not None)
        _check(
            "the two rates differ when the lane idles between turns",
            (rates.get("while_working_per_hour") or 0) > (rates.get("wall_clock_per_hour") or 0),
            detail=f"working={rates.get('while_working_per_hour')} "
                   f"wall={rates.get('wall_clock_per_hour')}",
        )
        # 20 items in 20 s of work = 3600/h; over a 110 s span = ~654/h.
        _check("while_working is items / summed batch durations",
               rates.get("while_working_per_hour") == 3600.0,
               detail=str(rates.get("while_working_per_hour")))

        # BOUNDED: a log far larger than the ceiling must not be read whole.
        big = d / "oo-keyword-triage-20260101-000000-000000.jsonl"
        filler = json.dumps({"schema": "oo-keyword-triage-batch-1", "pad": "x" * 500}) + "\n"
        with big.open("w", encoding="utf-8") as fh:
            for _ in range(4000):  # ~2 MB
                fh.write(filler)
            fh.write(json.dumps({
                "schema": "oo-keyword-triage-batch-1", "verdicts_out": 7,
                "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:10",
            }) + "\n")
        recs = read_tail_records(big, tail_bytes=16 * 1024)
        _check("the tail reader stops at its ceiling",
               0 < len(recs) < 200, detail=f"{len(recs)} records from a ~2 MB log")
        _check("and it still reaches the newest record",
               any(r.get("verdicts_out") == 7 for r in recs))

        _check("a missing log is a stated absence, not an empty rate",
               _source_tags_activity(d, tail_bytes=1024, recent=3).get("note") is not None)

    empty = rates_from_batches([{"attempted": 5}], item_key="attempted")
    _check("a batch with no clock yields no rate",
           empty.get("measurable") is False and bool(empty.get("reason")))

    return {
        "schema": "oo-ai-activity-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
    }


__all__ = [
    "AI_KINDS",
    "DEFAULT_RECENT",
    "DEFAULT_TAIL_BYTES",
    "SCHEMA",
    "newest_log",
    "rates_from_batches",
    "read_tail_records",
    "recent_activity",
    "run_activity_selftest",
    "stored_activity",
]

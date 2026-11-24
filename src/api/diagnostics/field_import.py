"""The import's own record, as three small files the Field data button saves (row 414, 2026-11-24).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Row 412 accounted for a week-long import of 2M articles from one measured run and found most of the week unaccounted for:
the measured run went into a nearly empty store, so every stage that grows with the live corpus was measured at zero. The numbers
that settle it are already on the machine that ran the import -- the run journal, each item's import report, the re-index drain's
metrics -- and none of them was in what the Field data button saves. ``FIELD_DATA_EXPORTS`` in ``src/static/app-diagnostics.js``
GETs these three routes; delete one only together with its entry there.

WHAT THEY READ, AND WHAT THEY NEVER READ. Files the import wrote (``data/run_logs/``, ``data/import_reports/``) and the drain
job's in-memory state. NEVER the corpus: no database is opened, so these three take nothing from a running import but a few file
reads. (The button's other entries do read the corpus; the button is meant to be pressed once the import queue has ended.) The drain status is the job's own state WITHOUT the backlog count its API route adds, because that
count is a read of the corpus.

WHAT LEAVES THE MACHINE: NUMBERS AND THE APP'S OWN TOKENS, NOTHING ELSE (R734, R736, R114). Every value goes through
:func:`projected`, an allowlist rather than a mask:

* numbers, booleans and ``None`` are kept (a float that is not finite is withheld: a JSON response cannot carry it);
* a string is kept ONLY under one of the keys in :data:`_FI_STRING_KEYS`, and only in the one shape that key allows: a
  lower-case word for an outcome or a state, a lower-case stage name, one of the app's lower-case reasons, an engine stamp, an
  import run's id, an ISO time. Every other string is withheld, however harmless it looks: a backup's folder name, a
  correspondent's public key and a label copied under a new key are all well-formed tokens, so shape alone is never the test;
* every kept string and every kept key passes the shared scrubber (``scrubbed_value``) for the passphrases the process holds;
* a dict key is kept only when it is a lower-case word as the app writes its fields (or a stage name under a stage prefix); any
  other key (a domain, a name, a file, a CamelCase field) is withheld with its whole value;
* a list longer than :data:`FIELD_IMPORT_MAX_LIST` is replaced by its length.

What was withheld is COUNTED in each file (``withheld``), never silently dropped. The rule fails closed: a string that matches
nothing is withheld, whatever it was.

THE SIZE RULE. Each file is at most :data:`FIELD_IMPORT_MAX_BYTES` (200 KB, the maintainer's 2026-11-15 limit), enforced here on
the serialised bytes: entries are newest first and the OLDEST are dropped until it fits, and the file says how many
(``dropped_oldest``). An entry that alone exceeds the limit is replaced by its size. Read-only, loopback, no network.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from src.api.country_wire import CountryWireResponse as JSONResponse

from ._base import router

FIELD_IMPORT_SCHEMA = "oo-field-import-1"
#: The largest file the button may save (maintainer 2026-11-15: «the loop has to limit itself to 200kb files»).
FIELD_IMPORT_MAX_BYTES = 200_000
#: Runs and reports read, newest first: the run journal keeps 40 runs (``src/backup/runlog.py`` ``_KEEP_RUNS``).
FIELD_IMPORT_MAX_ENTRIES = 40
#: A list longer than this is written as its length (a list of article ids is a count here, not evidence).
FIELD_IMPORT_MAX_LIST = 64
#: A report larger than this is listed with its size and not parsed (the listing's own bound in ``import_reports``).
FIELD_IMPORT_REPORT_PARSE_MAX = 4 * 1024 * 1024

_FI_ISO_TIME = re.compile(
    r"\A\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?\Z"
)
#: A word the app writes: lower case, digits, ``_``, ``:`` and ``-``. An outcome, a state, a stage.
_FI_WORD = re.compile(r"\A[a-z][a-z0-9_:\-]{0,63}\Z")
#: A stage as the app names it, which may hold a space ("merge_step:country codes"); lower case only.
_FI_STAGE = re.compile(r"\A[a-z][a-z0-9_:\- ]{0,79}\Z")
#: One of the app's own fixed reasons: a lower-case sentence with no punctuation that a path, an address or a quote needs.
_FI_REASON = re.compile(r"\A[a-z][a-z0-9 ,()\-]{0,159}\Z")
#: An extraction engine's stamp (``e1-<hex>``, ``w1-<hex>``) and an import run's id (``imp-20261115T112935Z-476095``).
_FI_ENGINE = re.compile(r"\A[a-z]\d-[0-9a-f]{8,64}\Z")
_FI_RUN_ID = re.compile(r"\A[a-z]{2,12}-\d{8}T\d{6}Z-[0-9a-f]{4,12}(-\d{1,4})?\Z")

#: THE ONLY KEYS A STRING IS KEPT UNDER, each with the one shape it may have. A string under any other key is withheld,
#: whatever it looks like: a backup's folder name, a correspondent's public key or a label copied under a new key is a
#: perfectly well-formed token, so the shape alone can never be the test (security read of row 414, 2026-11-24).
_FI_STRING_KEYS: dict[str, re.Pattern[str]] = {
    **dict.fromkeys(
        (
            "outcome",
            "kind",
            "state",
            "status",
            "mode",
            "ev",
            "phase_kind",
            "basis",
            "articles_basis",
        ),
        _FI_WORD,
    ),
    **dict.fromkeys(
        ("phase", "stage", "last_phase", "died_in_stage", "died_after_stage"), _FI_STAGE
    ),
    **dict.fromkeys(("reason", "www_reason"), _FI_REASON),
    **dict.fromkeys(("engine", "www_engine", "baseline_engine"), _FI_ENGINE),
    **dict.fromkeys(("run_id", "id"), _FI_RUN_ID),
    **dict.fromkeys(
        (
            "t",
            "at",
            "written",
            "started_at",
            "ended_at",
            "finished_at",
            "created_at",
            "last_seen_at",
            "generated_at",
            "state_at",
            "since",
        ),
        _FI_ISO_TIME,
    ),
}
#: A dict key is kept when it is a word as the app writes them, or a stage with a space under a stage prefix; any other key
#: (a domain, a name, a file, a CamelCase field) is withheld with its whole value.
_FI_KEY = re.compile(r"\A[a-z0-9][a-z0-9_:\-]{0,79}\Z")
_FI_STAGE_KEY = re.compile(
    r"\A(merge_step|stage_a|prepare_staged|verify|snapshot_working_copy):[a-z0-9_\- ]{1,64}\Z"
)


def projected(value: Any, *, key: str = "", counts: dict[str, int] | None = None) -> Any:
    """``value`` reduced to what may leave the machine (the module docstring's rules). ``counts`` gathers what was withheld."""
    from src.monitoring.secret_scrub import scrubbed_value

    c = counts if counts is not None else {}

    def withhold(kind: str) -> None:
        c[kind] = c.get(kind, 0) + 1

    def walk(v: Any, k: str, depth: int) -> Any:
        if depth > 24:
            withhold("too_deep")
            return None
        if v is None or isinstance(v, bool | int):
            return v
        if isinstance(v, float):
            if math.isfinite(v):
                return v
            withhold("not_finite")
            return None
        if isinstance(v, str):
            shape = _FI_STRING_KEYS.get(k)
            if shape is _FI_REASON and ":" in v:
                # A reason may carry an exception's own text after a colon ("verify failed: no such table x"); only the
                # app's part before it leaves (security re-read of row 414, residual 1).
                v = v.split(":", 1)[0].rstrip()
                withhold("reason_tails")
            if shape is None or not shape.match(v) or scrubbed_value(v) != v:
                withhold("strings")
                return None
            return v
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            for kk, vv in v.items():
                if (
                    not isinstance(kk, str)
                    or not (_FI_KEY.match(kk) or _FI_STAGE_KEY.match(kk))
                    or scrubbed_value(kk) != kk
                ):
                    withhold("keys")
                    continue
                out[kk] = walk(vv, kk, depth + 1)
            return out
        if isinstance(v, list | tuple):
            if len(v) > FIELD_IMPORT_MAX_LIST:
                withhold("long_lists")
                return {"len": len(v)}
            return [walk(x, k, depth + 1) for x in v]
        withhold("other")
        return None

    return walk(value, key, 0)


def _fi_envelope(
    kind: str, entries: list[Any], counts: dict[str, int], **extra: Any
) -> dict[str, Any]:
    from src import __version__

    return {
        "schema": FIELD_IMPORT_SCHEMA,
        "kind": kind,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": __version__,
        **extra,
        "count": len(entries),
        "dropped_oldest": 0,
        "withheld": dict(counts),
        "rule": (
            "numbers, booleans and the app's own one-word tokens only; titles, addresses, paths, file names, labels and "
            "messages are withheld and counted; newest first, the oldest dropped to stay under the size limit"
        ),
        "entries": entries,
    }


def bounded(payload: dict[str, Any], *, limit: int = FIELD_IMPORT_MAX_BYTES) -> bytes:
    """``payload`` serialised, its ``entries`` (newest first) cut from the OLDEST end until it fits ``limit`` bytes."""

    def size_of(x: Any) -> int:
        return len(json.dumps(x, separators=(",", ":"), default=str).encode("utf-8"))

    entries = list(payload["entries"])
    sizes = [size_of(e) for e in entries]
    for i, n in enumerate(sizes):
        if n > limit // 2:
            entries[i] = {"too_large": True, "bytes": n}
            sizes[i] = size_of(entries[i])
    # A first cut from the sizes (an entry costs its bytes and a comma), then the exact check on the real bytes.
    overhead = size_of({**payload, "entries": [], "count": 0, "dropped_oldest": 0}) + 64
    total = overhead + sum(n + 1 for n in sizes)
    keep = len(entries)
    while keep and total > limit:
        keep -= 1
        total -= sizes[keep] + 1
    while True:
        body = {
            **payload,
            "entries": entries[:keep],
            "count": keep,
            "dropped_oldest": len(entries) - keep,
        }
        data = json.dumps(body, separators=(",", ":"), default=str).encode("utf-8")
        if len(data) <= limit or not keep:
            return data
        keep -= 1


def _fi_response(payload: dict[str, Any], name: str) -> JSONResponse:
    return JSONResponse(
        json.loads(bounded(payload)),
        headers={
            "Content-Disposition": f'attachment; filename="oo-{name}-{datetime.now().strftime("%Y%m%d")}.json"'
        },
    )


#: Run-journal milestones kept beside each run's summary: the settings the run ran under and the size it worked at.
_FI_RUN_MILESTONES = ("knobs", "import_scale")


def build_run_journal() -> dict[str, Any]:
    from src.backup.runlog import _iter_jsonl, list_runs, run_logs_dir, summarise

    counts: dict[str, int] = {}
    entries: list[Any] = []
    for r in list_runs()[:FIELD_IMPORT_MAX_ENTRIES]:
        rid = r.get("run_id")
        if not isinstance(rid, str) or not rid:
            entries.append({"unreadable": "no run id"})
            continue
        try:
            entry: dict[str, Any] = {"summary": summarise(rid)}
            kept: dict[str, list] = {}
            for rec in _iter_jsonl(run_logs_dir() / f"{rid}.jsonl", raw=True):
                ev = rec.get("ev")
                if ev in _FI_RUN_MILESTONES and len(kept.setdefault(ev, [])) < 4:
                    kept[ev].append(rec)
            entry["milestones"] = kept
        except Exception as exc:  # noqa: BLE001 - one unreadable journal never hides the rest
            entry = {"run_id": rid, "unreadable": type(exc).__name__}
        entries.append(projected(entry, counts=counts))
    return _fi_envelope("run-journal", entries, counts)


def build_import_reports() -> dict[str, Any]:
    from src.backup.import_reports import _reports_dir, list_import_reports

    counts: dict[str, int] = {}
    entries: list[Any] = []
    base = _reports_dir()
    for meta in list_import_reports()[:FIELD_IMPORT_MAX_ENTRIES]:
        fname = meta.get("filename")
        head = {
            "kind": meta.get("kind"),
            "outcome": meta.get("outcome"),
            "written": meta.get("created_at"),
        }
        if (
            not isinstance(fname, str)
            or int(meta.get("size_bytes") or 0) > FIELD_IMPORT_REPORT_PARSE_MAX
        ):
            entries.append(
                projected(
                    {**head, "unread": "too_large", "bytes": meta.get("size_bytes")}, counts=counts
                )
            )
            continue
        try:
            # The listing named it inside the reports folder; read it there, as the listing did, never through a caller's path.
            data = json.loads((base / fname).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - an unreadable report is listed as unread, never as empty
            entries.append(projected({**head, "unread": type(exc).__name__}, counts=counts))
            continue
        if isinstance(data, dict):
            data.pop("written_at_ns", None)
        entries.append(projected({**head, "report": data}, counts=counts))
    return _fi_envelope("import-reports", entries, counts)


def build_drain_status() -> dict[str, Any]:
    from src.api.backup_v2 import _REINDEX_RESUME_JOB

    counts: dict[str, int] = {}
    # The job's own state only. The route /api/backup/reindex-backlog/resume/status adds the backlog, a read of the corpus;
    # this file does not, so it is safe to save beside a running import.
    st = _REINDEX_RESUME_JOB.status()
    st.pop("backlog", None)
    entries = [projected(st, counts=counts)]
    return _fi_envelope(
        "drain-status", entries, counts, backlog="not read here: counting it reads the corpus"
    )


@router.get("/field-run-journal")
def field_run_journal() -> JSONResponse:
    """The newest import and export runs' journals (summary, settings and size), projected and at most 200 KB."""
    return _fi_response(build_run_journal(), "field-run-journal")


@router.get("/field-import-reports")
def field_import_reports() -> JSONResponse:
    """The newest import reports (stage times, counts, engine stamps), projected and at most 200 KB."""
    return _fi_response(build_import_reports(), "field-import-reports")


@router.get("/field-drain-status")
def field_drain_status() -> JSONResponse:
    """The re-index drain's own metrics, including its rate against the store's size, projected and at most 200 KB."""
    return _fi_response(build_drain_status(), "field-drain-status")

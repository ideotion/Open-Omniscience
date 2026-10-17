"""The record of a rollup build that STOPPED part-way, kept across a restart.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (a running install, 2026-10-16): the boot's rollup build ran for 921 s and was stopped by
DuckDB's own memory limit (1,004 MB on that tier, with no offload allowed for an encrypted corpus, so the
limit is a wall). The stop is kept in memory and holds every later build back (``rollup_serve._stopped_build_verdict``),
but a restart forgot it, and the next boot spent the same 921 s to find the same wall. This file is the stop
record, so a process that starts after it does not repeat what the last one already measured.

What it holds is exactly the in-memory ``_STATE["stopped"]`` record: the reason code, the stage, the numbers it
was read against (DuckDB's limit, the memory the build grew by, the newest mention id and the corpus epoch at the
stop) and when. No term, no path, no article, and no engine text: a reason is a code and the rest are numbers.

The rule that releases the hold is NOT here (it is a decision about the machine and the corpus, and lives next to
the verdicts in ``rollup_serve``); this module only keeps and returns the record. A record that cannot be written
or read never blocks a build: a missing record is no evidence of a stop, so the build proceeds and the failure is
logged. A record that is present but malformed is named in the log and ignored, never half-trusted.
"""

from __future__ import annotations

import json
import logging
import os

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

_FILENAME = "rollup_stopped.json"
FORMAT = 1

#: The fields kept, with the types each may take. Anything else in a record (an engine's own text most of all)
#: is dropped on the way in, so the file can hold nothing a reader should not see.
_FIELDS: dict[str, tuple[type, ...]] = {
    "reason": (str,),
    "stage": (str,),
    "at": (int, float),
    "grew_mb": (int, float),
    "observed_grew_mb": (int, float),
    "epoch": (int,),
    "duckdb_limit_mb": (int, float),
    "mentions_total": (int,),
    "rows_done": (int,),
    "mentions_count": (int,),
    "checked_at": (int, float),
    # how the sharded aggregate was cut when it stopped: shards, the shard it stopped in, the parts it had been halved to
    # the budget reading the build ran under (R147): threads, the machine total the limit came from, and when it was read
    "duckdb_threads": (int,),
    "budget_total_mb": (int, float),
    "budget_read_at": (str,),
    "shards": (int,),
    "shard": (int,),
    "split": (int,),
    # the serve check that stopped it (R157): the query's code and what it cost, against the resident rollup
    "query": (str,),
    "peak_mib": (int, float),
    "resident_mib": (int, float),
    # the class NAME of the engine error that stopped it (never its text)
    "engine_error_class": (str,),
    # a build that ended in an error of its own (R172): the run of consecutive failures, and why the stage is missing when it is.
    # For that record ``stage`` is the LAST REPORTED stage, not the raising statement. A restart reads the count and holds nothing.
    "consecutive_failures": (int,),
    "stage_why": (str,),
    # whether DuckDB could spill when it stopped (False: the limit was a wall); a later process where it may releases
    "offload_allowed": (bool,),
    # which code stopped it: a record is evidence about THAT build only (see ``rollup_serve.BUILD_CODE_VERSION``)
    "app_version": (str,),
    "build_code": (int,),
}


def _path():
    from src.paths import data_dir

    return data_dir() / _FILENAME


def clean(record: dict) -> dict:
    """The kept fields of ``record`` whose values have the expected type (a bool is not a number here)."""
    out: dict = {}
    for key, types in _FIELDS.items():
        value = record.get(key)
        if value is None or (isinstance(value, bool) and bool not in types) or not isinstance(value, types):
            continue
        out[key] = value
    return out


def write(record: dict) -> bool:
    """Keep ``record`` (atomically replacing the last one). ``False`` when it could not be written."""
    kept = clean(record)
    if not kept.get("reason"):
        return False
    try:
        path = _path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"format": FORMAT, **kept}, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001 - a hold that cannot be kept must not stop the build's own record
        log_failure(_LOG, "rollup hold: could not keep the stop record", exc, level=logging.WARNING)
        return False


def read() -> dict | None:
    """The kept record, or ``None``: no file (the only case that means "no stop"), an unreadable file or a malformed
    one (the last two are logged by class, never silently taken for absence)."""
    try:
        text = _path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "rollup hold: the stop record could not be read; ignored", exc, level=logging.WARNING)
        return None
    try:
        rec = json.loads(text)
    except ValueError as exc:
        log_failure(_LOG, "rollup hold: the stop record is not valid JSON; ignored", exc, level=logging.WARNING)
        return None
    if not isinstance(rec, dict) or rec.get("format") != FORMAT:
        _LOG.warning("rollup hold: the stop record has an unknown format; ignored")
        return None
    kept = clean(rec)
    if not kept.get("reason"):
        _LOG.warning("rollup hold: the stop record names no reason; ignored")
        return None
    return kept


def clear() -> None:
    """Remove the record (the hold was released, or a build finished)."""
    try:
        _path().unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "rollup hold: could not remove the stop record", exc, level=logging.WARNING)

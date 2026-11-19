"""The dossier's rail-availability counter for the Diagnostics zip (S08-01 S3, row 178).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IT RECORDS. Each dossier this process opened: how many rails were joined, which joined rails had
rows on this machine and which did not (a gap is a gap, never a 0 counted as a value), and which rails
were not joined with their code. Beside the newest openings, a tally per rail over every opening since
the process started. Counts, times and rail names only.

WHAT IT WITHHOLDS. The Wikidata id and the item's label. They say what the operator was investigating,
and the zip is a file the operator sends to someone else: the member's job is to show whether the rails
work, which the shape answers without the subject.

WHERE IT LIVES. In memory, for this process: a restart starts the counter again and the member says
since when it counts. No file is written on a dossier open, so opening one never touches the disk.

It is a counter, never a bar (S3 «may not decide: any bar»): nothing here says a dossier is good.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

#: The most raw JSON the slot asks for (``diagnostics_slots``). MEASURED on this module's own test: the
#: fixed part with all nine rails and the not-joined codes of a country and of a non-country in the tally
#: is 1,046 bytes, and one opening is 205 (not a country) to 262 bytes (a country), so 2,400 keeps about the
#: five newest; the tally covers every opening whatever the cut.
DEFAULT_MAX_BYTES = 2_400

#: The newest openings kept in memory (the member shows as many of them as fit).
KEEP_RECENT = 20

METHOD = (
    "One record per dossier opened in this process since the start time shown: the joined rails, the joined rails "
    "that had rows on this machine and those that had none, and the rails not joined with their code. The tally adds "
    "every opening, per rail. Rows means the rail's own store answered with at least one item; nothing is weighed. "
    "The item's id and label are withheld."
)

_LOCK = threading.Lock()
_RECENT: deque[dict[str, Any]] = deque(maxlen=KEEP_RECENT)
_STATE: dict[str, Any] = {"since": None, "opened": 0, "country": 0, "rails": {}, "not_joined": {}}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(payload: dict) -> None:
    """Count one opened dossier. Never raises: a counter must not cost the operator their dossier."""
    try:
        avail = payload.get("availability") or {}
        rails = [str(r.get("key")) for r in payload.get("rails") or [] if r.get("key")]
        with_rows = [str(k) for k in avail.get("rails_with_rows") or []]
        without = [k for k in rails if k not in with_rows]
        not_joined = []
        for r in payload.get("not_joined") or []:
            key = str(r.get("key") or "")
            code = r.get("code")
            not_joined.append(f"{key}:{code}" if code else key)
        entry: dict[str, Any] = {"at": _now(), "country": bool(payload.get("country")), "joined": len(rails),
                 "with_rows": with_rows, "without_rows": without, "not_joined": not_joined}
        with _LOCK:
            if _STATE["since"] is None:
                _STATE["since"] = entry["at"]
            _STATE["opened"] += 1
            _STATE["country"] += int(entry["country"])
            for k in rails:
                t = _STATE["rails"].setdefault(k, {"joined": 0, "with_rows": 0})
                t["joined"] += 1
                t["with_rows"] += int(k in with_rows)
            for k in not_joined:
                _STATE["not_joined"][k] = _STATE["not_joined"].get(k, 0) + 1
            _RECENT.append(entry)
    except Exception:  # noqa: BLE001 - see the docstring
        return


def reset() -> None:
    """Forget every opening (tests; a process restart does the same)."""
    with _LOCK:
        _RECENT.clear()
        _STATE.update({"since": None, "opened": 0, "country": 0, "rails": {}, "not_joined": {}})


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def diagnostics_member(max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """The counter, the newest openings first, cut to ``max_bytes`` oldest first with the cut named."""
    try:
        budget = int(max_bytes)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"error": type(exc).__name__, "reason": "max_bytes is not a whole number"}
    with _LOCK:
        recent = [dict(e) for e in reversed(_RECENT)]
        out: dict[str, Any] = {
            "method": METHOD,
            "scope": "this process, in memory; a restart starts again",
            "since": _STATE["since"],
            "n": _STATE["opened"],
            "n_country": _STATE["country"],
            "rails": {k: dict(v) for k, v in sorted(_STATE["rails"].items())},
            "not_joined": dict(sorted(_STATE["not_joined"].items())),
            "recent": recent,
            "recent_kept_in_memory": KEEP_RECENT,
            "dropped_to_fit": 0,
        }
    while out["recent"] and _size(out) > budget:
        out["recent"].pop()
        out["dropped_to_fit"] += 1
    if _size(out) > budget:
        out["over_budget"] = True
    return out

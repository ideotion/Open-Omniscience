"""The release ladder's record as a diagnostic may keep it: numbers, step names and the CLASS of an error (2026-10-07).

``src/scheduler/release.py`` records what each step of the ladder freed. That record is copied into the snapshot a session writes
beside its high-water marks (``session_pressure.json``, and from there ``session-forensics.json``) and into the ledger's end
record (and from there ``boots.json``): files the debug bundle carries. A step's ``error`` is the class of the exception and
nothing it said, and this module is what makes that true of a record that was built by anything else (an older build's, which
kept ``Class: text``): it REBUILDS the record from an allow-list and keeps nothing it does not name. Stdlib only.
"""

from __future__ import annotations

import re
from typing import Any

from src.monitoring.secret_scrub import scrubbed_value

#: A class name, a step name, a serve's name: what a code identifier looks like. Anything else is not copied as a name.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")
#: The most characters of a step's ``skipped`` (words of the code's own, that a step writes: ``this process has pages in swap``).
_SKIPPED_MAX = 120
#: How many steps and how many serve names one record keeps. The ladder has five steps and there are two serves; a record that
#: names more is not one this code wrote, and what is kept of it is cut, never trusted.
_STEPS_MAX = 12
_NAMES_MAX = 8


def _class_only(value: Any) -> str:
    """The class named at the start of ``value`` (``ValueError: boom`` is ``ValueError``), or a fixed word when it does not start
    with one. ``value.split(":")[0]`` and nothing after it is ever kept."""
    head = str(value).split(":", 1)[0].strip() if isinstance(value, str) else ""
    return head if _NAME.match(head) else "(error)"


def _number(value: Any) -> int | float | bool | None | str:
    return value if value is None or (isinstance(value, (int, float, bool)) and value == value) else "(not a number)"


def _names(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [v for v in value[:_NAMES_MAX] if isinstance(v, str) and _NAME.match(v)]


def _step(step: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    name = step.get("step")
    out["step"] = name if isinstance(name, str) and _NAME.match(name) else "(unnamed)"
    for key in ("ok", "freed_mb", "collected"):
        if key in step:
            out[key] = _number(step[key])
    if "closed" in step:
        closed = step["closed"]
        out["closed"] = _names(closed) if isinstance(closed, list) else _number(closed)
    if isinstance(step.get("busy"), list):
        out["busy"] = _names(step["busy"])
    if isinstance(step.get("skipped"), str):
        out["skipped"] = step["skipped"][:_SKIPPED_MAX]
    if "error" in step:
        out["error"] = _class_only(step["error"])
    if isinstance(step.get("errors"), dict):
        out["errors"] = {k: _class_only(v) for k, v in list(step["errors"].items())[:_NAMES_MAX] if isinstance(k, str) and _NAME.match(k)}
    return out


def allow_listed(record: Any) -> dict[str, Any] | None:
    """``record`` rebuilt from the allow-list: the top-level numbers and ``process_swapping``, and per step its name, ``ok``,
    ``freed_mb``, ``closed``, ``collected``, ``skipped``, ``busy`` and its error as a class. ``None`` when ``record`` is not a
    mapping. Never raises."""
    try:
        if not isinstance(record, dict):
            return None
        out: dict[str, Any] = {
            k: _number(v) for k, v in record.items() if isinstance(k, str) and _NAME.match(k) and (v is None or isinstance(v, (int, float, bool)))
        }
        steps = record.get("steps")
        if isinstance(steps, list):
            out["steps"] = [_step(s) for s in steps[:_STEPS_MAX] if isinstance(s, dict)]
        return out
    except Exception:  # noqa: BLE001 - a diagnostic never fails its caller
        return None


def scrub_marks(marks: Any) -> tuple[dict[str, Any] | None, str | None]:
    """A copy of a session's high-water marks with every release-ladder record in them (``guard.last_release`` of each heavy and light
    snapshot) rebuilt from the allow-list, and dropped where it is not a record: a reader that copies the marks of an earlier session
    into a report must not copy an engine's text with them. ``(marks, None)``, or ``(None, <class of the failure>)`` when it could not be
    done: the caller says the scrub failed, never that the record is absent. Never raises."""
    try:
        out = dict(marks)
        for key in ("pressure", "pressure_light"):
            snaps = out.get(key)
            if not isinstance(snaps, list):
                continue
            clean = []
            for snap in snaps:
                if isinstance(snap, dict) and isinstance(snap.get("guard"), dict) and "last_release" in snap["guard"]:
                    guard = {k: v for k, v in snap["guard"].items() if k != "last_release"}
                    rebuilt = allow_listed(snap["guard"].get("last_release"))
                    if rebuilt is not None:
                        guard["last_release"] = rebuilt
                    snap = {**snap, "guard": guard}
                clean.append(snap)
            out[key] = clean
        # Thread names in the snapshots are request-chosen text, and an older build's sidecar kept them as they were.
        cleaned = scrubbed_value(out)
        if not isinstance(cleaned, dict):
            raise ValueError("the marks could not be checked")
        return cleaned, None
    except Exception as exc:  # noqa: BLE001 - a diagnostic never fails its caller
        return None, type(exc).__name__

"""Sentences the server writes for the page (a caveat, a method, a reason), keyed so they read in the page's language.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 206. A caveat or method the server sent arrived in English on every page, whatever the reader's language: the
client printed it as given, and a sentence with a number welded in could never match a locale key. ``said`` sends
the English (the fallback, built FROM the frame so the two cannot drift) beside one keyed frame, the briefing card's
format (``src/briefing/card.py``): ``{"t": template, "v": {hole: value}}``. The page renders it with ``ooSaidHtml``
/ ``ooSaidText`` (``src/static/app-core.js``); a page without the frame shows the English, labelled as such (R289).

A hole's value may itself be a frame (``frame(...)``): a sentence built from parts, such as a hardware reason that
quotes what each probe said, renders each part in the page's language. ``said_frames`` sends several frames that
read one after the other, joined by a space, for a sentence whose parts vary by case.

The TEMPLATE of every ``said(...)`` and ``frame(...)`` call must be a string literal (or a module-level string
constant of the same file), and it must be a locale key in all twelve languages: ``tests/test_server_text_keyed.py``
reads every such call in ``src/`` and fails otherwise, so a sentence cannot be added in English only. Values are
data and never translate, except a value named in ``tr``, which is itself a keyed word, and a value that is a frame.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["frame", "frame_of", "said", "said_frames", "spoken"]

_HOLE = re.compile(r"\{(\w+)\}")


def frame(template: str, *, tr: Any = (), **variables: Any) -> dict:
    """One keyed frame ``{"t": template, "v": {hole: value}}``. A value may be another frame."""
    fr: dict = {"t": template, "v": dict(variables)}
    if tr:
        fr["tr"] = list(tr)
    return fr


def _is_frame(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("t"), str)


def spoken(fr: Any) -> str:
    """The English of a frame, nested frames filled in. A plain value is its own text.

    A hole with no value stays verbatim, the same rule as the page's ``tf``."""
    if not _is_frame(fr):
        return "" if fr is None else str(fr)
    variables = fr.get("v") or {}

    def _fill(m: re.Match[str]) -> str:
        value = variables.get(m.group(1))
        if value is None:
            return m.group(0)
        return spoken(value) if _is_frame(value) else str(value)

    return _HOLE.sub(_fill, fr["t"])


def frame_of(payload: Any, field: str = "reason") -> Any:
    """What another payload said in ``field``, ready to sit in a hole: its frame when it sent exactly one, else its
    English (which the page then shows as data, untranslated)."""
    if not isinstance(payload, dict):
        return None
    frames = payload.get(f"{field}_i18n")
    if isinstance(frames, list) and len(frames) == 1 and _is_frame(frames[0]):
        return frames[0]
    return payload.get(field)


def said(field: str, template: str, *, tr: Any = (), **variables: Any) -> dict:
    """``{field: english, field + "_i18n": [frame]}``, to spread into a response dict.

    Standard library only, on purpose: this is imported by the backup, statistics and model-backend modules, and a
    dependency on the briefing package (whose ``__init__`` loads the producers) would tie them into its import graph."""
    fr = frame(template, tr=tr, **variables)
    return {field: spoken(fr), f"{field}_i18n": [fr]}


def said_frames(field: str, *frames: dict) -> dict:
    """Several frames that read one after the other, joined by a space, in English and on the page alike."""
    kept = [f for f in frames if _is_frame(f)]
    return {field: " ".join(spoken(f) for f in kept), f"{field}_i18n": kept}

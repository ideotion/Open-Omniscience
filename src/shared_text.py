"""Sentences the server writes for the page (a caveat, a method, a reason), keyed so they read in the page's language.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 206. A caveat or method the server sent arrived in English on every page, whatever the reader's language: the
client printed it as given, and a sentence with a number welded in could never match a locale key. ``said`` sends
the English (the fallback, built FROM the frame so the two cannot drift) beside one keyed frame, the briefing card's
format (``src/briefing/card.py``): ``{"t": template, "v": {hole: value}}``. The page renders it with ``ooSaidHtml``
/ ``ooSaidText`` (``src/static/app-core.js``); a page without the frame shows the English, labelled as such (R289).

The TEMPLATE must be a string literal (or a module-level string constant of the same file), and it must be a locale key in all twelve languages:
``tests/test_server_text_keyed.py`` reads every ``said(...)`` call in ``src/`` and fails otherwise, so a sentence
cannot be added in English only. Values are data and never translate, except a value named in ``tr``, which is
itself a keyed word.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["said"]

_HOLE = re.compile(r"\{(\w+)\}")


def said(field: str, template: str, *, tr: Any = (), **variables: Any) -> dict:
    """``{field: english, field + "_i18n": [frame]}``, to spread into a response dict.

    Standard library only, on purpose: this is imported by the backup, statistics and model-backend modules, and a
    dependency on the briefing package (whose ``__init__`` loads the producers) would tie them into its import graph.
    A hole with no value stays verbatim in the English, the same rule as the page's ``tf``."""
    fr: dict = {"t": template, "v": dict(variables)}
    if tr:
        fr["tr"] = list(tr)

    def _fill(m: re.Match[str]) -> str:
        value = variables.get(m.group(1))
        return m.group(0) if value is None else str(value)

    english = _HOLE.sub(_fill, template)
    return {field: english, f"{field}_i18n": [fr]}

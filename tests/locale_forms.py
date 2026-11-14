"""Read a locale file the way the UI reads a value that has no number (2026-11-14).

A translation may hold one form per CLDR plural category, "[one]...[few]...[other]...", and
``OOI18N.t()``, the DOM walker and ``tf()`` without a count all render its ``[other]`` form. The
tests that check a value's placeholders against its key compare that form: the rule that EVERY
form carries exactly the key's placeholders is pinned once, in tests/test_i18n_plural_forms.py.
A value without markers is returned unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_MARK = re.compile(r"\[(zero|one|two|few|many|other)\]")


def other_form(value: Any) -> Any:
    """The ``[other]`` form of a plural value; any other value as it is."""
    if not (isinstance(value, str) and value.startswith("[") and _MARK.match(value)):
        return value
    parts = _MARK.split(value)
    forms = dict(zip(parts[1::2], parts[2::2], strict=True))
    return forms["other"] if parts[0] == "" and "other" in forms else value


def flat(table: Any) -> Any:
    """A locale table with every plural value read as its ``[other]`` form."""
    if not isinstance(table, dict):
        return table
    return {k: other_form(v) for k, v in table.items()}


def load_locale(path: Path | str) -> Any:
    """``json.loads`` of a locale file, through :func:`flat`."""
    return flat(json.loads(Path(path).read_text(encoding="utf-8")))

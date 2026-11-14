"""The feed tally says a Stop in words (R353 = B, OPEN_QUEUE item 20).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``stopped_unwalked`` (R327) counts the entries of a feed a Stop left unrequested. It is not an
outcome (R320/R337), so the Sources tally no longer prints it as a raw key beside the real
counts: ``tally()`` in ``app-sources.js`` says it after them as a translated sentence and
``tallyHover()`` carries the long form. The behaviour runs as EXTRACTED code under node
(``tests/stopped_unwalked_tally_node_test.js``); this file is its driver plus the locale
contract. The key itself stays in the tally JSON (``tests/test_stop_is_not_an_outcome.py``).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.locale_forms import load_locale

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"

_KEYS = [
    "{counts} · {n} entries not asked for (you stopped collection)",
    "{n} entries not asked for (you stopped collection)",
    "Stop was pressed while this feed was being read: the remaining entries were never requested, "
    "and they are not failures. The feed is read again on the next collection pass.",
]


def test_stopped_unwalked_tally_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "stopped_unwalked_tally_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "6 passed" in proc.stdout, proc.stdout


def test_every_string_is_keyed_in_all_twelve_locales_with_its_placeholders() -> None:
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = load_locale(path)
        for key in _KEYS:
            assert data.get(key, "").strip(), f"{path.name} has no value for {key!r}"
            assert sorted(re.findall(r"\{(\w+)\}", data[key])) == sorted(re.findall(r"\{(\w+)\}", key)), (
                f"{path.name} changes the placeholders of {key!r}"
            )


def test_the_batch_cell_escapes_the_plain_tally() -> None:
    # tally() returns PLAIN text now; the one innerHTML sink (the per-feed result cell) must escape it.
    src = (_ROOT / "src" / "static" / "app-sources.js").read_text(encoding="utf-8")
    assert "esc(tally(x.tally))" in src
    assert "`${esc(k)}: ${v}`" not in src

"""Row 432, lane members: a backup's lane store is never written to, so no trigger it carries ever fires.

The corpus and custody log have their triggers and views dropped from the staged copy (``staged_key.disarm_staged``).
Lane members are not disarmed: ``lane_merge`` ATTACHes the member as ``inc`` to the live lane's connection and only
READS from it. A trigger stored in ``inc`` can only be on a table of ``inc`` (SQLite refuses a non-TEMP trigger that
names another database), so it fires only on a write to the member, and this module never writes to one: every write
names ``main.`` or ``temp.``. This file pins that two ways: a source guard that fails when any write statement in
``lane_merge.py`` targets anything else, and a real merge of a member carrying a trigger on every table the merge reads,
whose bytes are unchanged afterwards (that test, and the refusal of views matched without regard to case, live beside
the other hostile-member tests in ``tests/test_lane_backup_merge.py``, which owns the two-machine fixture).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.backup import lane_merge

_SRC = Path(lane_merge.__file__)

#: Every SQL statement form that writes, with its target.
_WRITE = re.compile(
    r"\b(INSERT(?: OR \w+)? INTO|REPLACE INTO|UPDATE|DELETE FROM|DROP (?:TABLE|INDEX|TRIGGER|VIEW)(?: IF EXISTS)?"
    r"|CREATE (?:TEMP |TEMPORARY )?(?:UNIQUE )?(?:TABLE|INDEX|TRIGGER|VIEW)(?: IF NOT EXISTS)?|ALTER TABLE)\s+([^\s(]+)"
)


def test_every_write_in_the_lane_merge_names_main_or_temp():
    """An unqualified write could resolve to ``inc`` when the live lane lacks the table; a write naming ``inc`` would
    fire the member's triggers. Neither may appear."""
    text = _SRC.read_text(encoding="utf-8")
    bad = []
    for m in _WRITE.finditer(text):
        verb, target = m.group(1), m.group(2)
        if target.startswith(("main.", "temp.")) or " TEMP " in f" {verb} " or "TEMPORARY" in verb:
            continue
        if verb == "UPDATE" and target == "SET":  # ON CONFLICT ... DO UPDATE SET: the INSERT's own target
            continue
        bad.append(f"{_SRC.name}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}")
    assert not bad, "a write in the lane merge that does not name main. or temp.: " + "; ".join(bad)
    assert "executescript" not in text  # a script would bypass the per-statement check above
    assert len(re.findall(r"AS inc\b", text)) == 1  # the one ATTACH: nothing else names the member

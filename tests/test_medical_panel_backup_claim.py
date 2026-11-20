"""Row 215: the Medical papers panel's sentence about backups follows what a backup actually carries.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R746 started ``medical.db`` as a «waiting» lane and the panel said so: «A backup does not carry it yet». #2169 put
``medical`` in ``lane_merge.MERGEABLE_KINDS``, and the backup writer carries exactly those kinds
(``stream_backup``), but the panel kept the old sentence, telling a user their papers were not backed up when they
were. This pins the panel's claim to the list the writer reads, both ways, and to every locale.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.backup.lane_merge import MERGEABLE_KINDS

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
CARRIED = ("Records are kept in their own file, medical.db, never mixed with your news articles. A backup carries them, "
           "and every kept record can also be fetched again.")
_NOT_CARRIED = re.compile(r"backup does not carry|not carry it yet|not included yet", re.I)


def _panel_text() -> str:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<section class="panel" id="medical-lane">(.*?)</section>', html, re.S)
    assert m, "the Medical papers panel (#medical-lane) is gone"
    return m.group(1)


def test_the_panel_says_a_backup_carries_the_papers_exactly_when_the_writer_does() -> None:
    panel = _panel_text()
    if "medical" in MERGEABLE_KINDS:
        assert CARRIED in panel, "a backup carries medical.db, and the panel must say so"
        assert not _NOT_CARRIED.search(panel), "the panel still says a backup leaves the papers out"
    else:  # the lane went back to waiting: the panel must say so again, never claim a backup it does not make
        assert CARRIED not in panel


def test_the_backup_writer_carries_the_kinds_the_claim_reads() -> None:
    """The claim reads ``MERGEABLE_KINDS`` because the writer does: if the writer stops using that list, this test must
    be revisited rather than the panel quietly drifting again."""
    src = (_ROOT / "src" / "backup" / "stream_backup.py").read_text(encoding="utf-8")
    assert "from src.backup.lane_merge import MERGEABLE_KINDS, snapshot_lane_for_backup" in src


def test_every_locale_carries_the_sentence_and_none_keeps_the_old_one() -> None:
    old = "A backup does not carry it yet"
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert str(data.get(CARRIED, "")).strip(), f"{path.name}: the panel sentence is not translated"
        assert not any(old in k for k in data), f"{path.name}: still keys the old sentence"

"""R829 A1 / R834: the schema check of a staged corpus knows every trigger, view and virtual table the app makes.

The check reads a fixed list (``staged_key._CORPUS_OBJECTS``), never the live store: read from the live store, the
verdict on a foreign file depended on the user's own (a store missing a trigger refused a backup that had it). This
ratchet keeps the list complete: every such object the source creates is either in it or named as living in another
store (``_NOT_CORPUS_OBJECTS``).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.backup import staged_key

_ROOT = Path(__file__).resolve().parents[1]
_CREATE = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?(TRIGGER|VIEW|VIRTUAL\s+TABLE)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?([A-Za-z_{][A-Za-z_0-9{}]*)",
    re.IGNORECASE,
)


#: Files whose CREATE statements build a scratch database of their own, never a corpus.
_SCRATCH_ONLY = {"src/monitoring/merge_diag.py"}  # a diagnostic over an in-memory copy it makes itself


def _templates() -> dict[str, str]:
    from src.database import fts_title
    from src.database.models import MENTIONS_VIEW

    return {"{TABLE}": fts_title.TABLE, "{MENTIONS_VIEW}": MENTIONS_VIEW}


def _created_names() -> set[str]:
    subs = _templates()
    names = set()
    for top in ("src", "migrations"):
        for path in (_ROOT / top).rglob("*.py"):
            if path.relative_to(_ROOT).as_posix() in _SCRATCH_ONLY:
                continue
            for _kind, name in _CREATE.findall(path.read_text(encoding="utf-8")):
                for k, v in subs.items():
                    name = name.replace(k, v)
                if name.upper() in {"IF", "AS"} or "{" in name:
                    continue
                names.add(name.lower())
    return names


def test_every_object_the_source_creates_is_known_or_named_as_another_stores():
    created = _created_names()
    assert "article_fts_ai" in created and "keyword_mentions_all" in created  # the scan is not blind
    unknown = created - set(staged_key._CORPUS_OBJECTS) - staged_key._NOT_CORPUS_OBJECTS
    assert not unknown, f"add these to _CORPUS_OBJECTS or _NOT_CORPUS_OBJECTS in src/backup/staged_key.py: {unknown}"


def test_the_lists_do_not_overlap_and_the_check_reads_no_live_store(monkeypatch):
    assert not set(staged_key._CORPUS_OBJECTS) & staged_key._NOT_CORPUS_OBJECTS

    class _Broken:
        def connect(self):
            raise AssertionError("the check read the live store")

    monkeypatch.setattr("src.database.session.engine", _Broken())
    assert staged_key._known_objects() == staged_key._CORPUS_OBJECTS

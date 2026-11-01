"""A host's own Crawl-delay is a DEFERRAL on the Law table and in the "Track changes now" toast (R406; Q1013 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: the tracker handled a deferral correctly (``deferred`` in its own tally key, no error, the check time kept) but STORED it as
``fetch error: Crawl-delay ...``, on purpose, until a verdict and its label were ruled. So the Law table and the coverage report called
the same documents errors that the tally did not count, and the toast never read ``deferred``.
After: ``deferred: ...`` is stored, ``_verdict_of`` reads it, the pill is neutral with the stored reason on hover, and the toast says
how many were deferred. The Python half is pinned in ``tests/test_law_check_stamp.py`` and ``tests/test_law.py``; this file runs the
JS half under node (``law_deferred_node_test.js``) and keys the two new strings in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STRINGS = ("deferred", "{n} deferred (the host's own Crawl-delay)")


def test_the_pill_and_the_toast_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "law_deferred_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "law_deferred_node_test.js: OK" in proc.stdout


def test_the_new_strings_are_keyed_and_translated_in_all_twelve_locales():
    english = json.loads((_ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    paths = sorted((_ROOT / "src/static/locales").glob("*.json"))
    assert len(paths) == 12
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _STRINGS:
            assert key in data, f"{path.name} lacks {key!r}"
            if path.name != "en.json":
                assert data[key] != english[key], f"{path.name} carries {key!r} untranslated"
    assert "{n}" in english[_STRINGS[1]]
    for path in paths:
        assert "{n}" in json.loads(path.read_text(encoding="utf-8"))[_STRINGS[1]], f"{path.name} lost the {{n}} slot"


def test_the_coverage_report_names_the_deferred_verdict_in_its_method():
    """The method text lists the verdict names the mix can hold (it is shown beside the counts), so a verdict that can appear in the
    mix and is not named there is a count the reader cannot look up."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base
    from src.law.coverage import law_coverage_report

    engine = sa.create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    method = law_coverage_report(sessionmaker(bind=engine, future=True)())["method"]
    assert "unchanged / deferred / other" in method


def test_what_the_tracker_stores_is_what_the_classifier_reads():
    """One word on both sides: the prefix ``track.py`` writes is the prefix ``_verdict_of`` judges first."""
    from src.api.law import _verdict_of

    track = (_ROOT / "src/law/track.py").read_text(encoding="utf-8")
    assert 'doc.last_status = f"deferred: {record_text(exc)}"' in track
    assert _verdict_of("deferred: anything the reason says, even robots.txt") == "deferred"

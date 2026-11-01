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

import pytest

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


def test_the_coverage_report_names_every_verdict_its_mix_can_hold_in_its_method():
    """The method text is shown beside the counts, so a verdict that can appear in the mix and is not named there is a count the reader
    cannot look up. The verdicts are read out of ``_verdict_of`` itself (every string it returns), so a verdict added later is checked
    too; ``never_checked`` is counted in its own field and is the only one not in the mix. Whole words only: «changed» is not
    satisfied by «unchanged»."""
    import ast
    import re

    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base
    from src.law.coverage import law_coverage_report

    tree = ast.parse((_ROOT / "src/api/law.py").read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_verdict_of")
    returned = {
        n.value.value for n in ast.walk(func) if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    }
    assert {"deferred", "re_extracted", "changed", "unchanged"} <= returned, returned  # the reader found the real returns
    engine = sa.create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    method = law_coverage_report(sessionmaker(bind=engine, future=True)())["method"]
    for verdict in sorted(returned - {"never_checked"}):
        assert re.search(rf"(?<![a-z_]){verdict}(?![a-z_])", method), f"{verdict!r} can be in the verdict mix and the method text does not name it"


def test_the_message_the_fetcher_really_raises_is_read_as_a_deferral_only_with_the_new_prefix(tmp_path, monkeypatch):
    """Drive the real fetcher to get the message a deferral is raised with (``src/ingest/__init__.py``, ``Crawl-delay {n:g} s: not before
    <time>``), so a reworded raise cannot leave the hand-written strings of the other tests passing while the real one is read wrongly:
    behind ``deferred: `` (what the tracker stores now) it is a deferral; behind ``fetch error: `` (what builds before R406 stored, and
    what builds before #1541 also stored for a FAILED request) it stays an error, because the text cannot tell those apart."""
    from urllib.robotparser import RobotFileParser

    from src.api.law import _verdict_of
    from src.ingest import CrawlDelayDeferred, EthicalFetcher
    from src.monitoring.secret_scrub import record_text

    monkeypatch.delenv("OO_CRAWL_DELAY_MAX_WAIT", raising=False)  # the sibling test_crawl_delay_retry_is_a_failure.py does the same
    fetcher = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json")
    robots = RobotFileParser()
    robots.parse(["User-agent: *", "Crawl-delay: 3600"])
    fetcher._robots["https://slow.example"] = (robots, fetcher._now() + 9999)
    fetcher._sleep = lambda _s: None
    fetcher._respect_rate_limit("slow.example", "https://slow.example")  # the first touch is free
    with pytest.raises(CrawlDelayDeferred) as raised:
        fetcher._respect_rate_limit("slow.example", "https://slow.example")
    text = record_text(raised.value)
    assert _verdict_of(f"deferred: {text}") == "deferred", text  # what it stores now
    assert _verdict_of(f"fetch error: {text}") == "error", text  # what it stored before: ambiguous, so not guessed

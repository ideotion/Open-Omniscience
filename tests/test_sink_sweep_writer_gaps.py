"""Writers and traced labels that had no passphrase test (sink sweep, audit gap list, 2026-10-16).

Each case hands the writer a failure whose words hold the unlocked session's passphrase and reads back the FILE the writer made (the
file the bundle and the backup carry), not the return value. A writer that stops taking the passphrase out goes red here.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.monitoring import feed_preflight

_PW = "corpus'key\"two\\y"
SRC = Path(__file__).resolve().parents[1] / "src"


def _quoted(*_a, **_k):
    raise RuntimeError(f"driver said: {_PW} and {_PW.replace(chr(39), chr(39) * 2)}")


@pytest.fixture(autouse=True)
def _held(monkeypatch, tmp_path):
    monkeypatch.setattr("src.database.connect._passphrase", _PW)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr(feed_preflight, "data_dir", lambda: tmp_path)


def _forms() -> tuple[str, ...]:
    return (_PW, json.dumps(_PW)[1:-1], _PW.replace("'", "''"))


def test_feed_preflight_log_file_carries_no_passphrase_from_any_of_its_three_failure_paths(monkeypatch, tmp_path):
    """The robots check, the market-feed sample and the calendar sample each write ``record_text`` of what they caught into
    ``feed_preflight.jsonl`` (in the backup's log members and the bundle). MUTATION TARGETS: the three ``record_text`` calls."""
    targets = (
        [{"kind": "market_feed", "key": "m1", "url": "https://m.example/a.csv", "host": "m.example"}],
        [{"kind": "calendar_feed", "key": "c1", "url": "https://c.example/a.ics", "host": "c.example"}],
    )
    monkeypatch.setattr(feed_preflight, "_feed_targets", lambda: targets)
    monkeypatch.setattr("src.events.feeds.verify_feed", _quoted)
    fetcher = SimpleNamespace(_guard_target=_quoted, fetch=_quoted, user_agent="t")
    out = feed_preflight.run_feed_preflight(fetcher)
    assert out["complete"] is True
    text = (tmp_path / "feed_preflight.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert {r.get("kind") for r in rows} >= {"robots", "market_feed", "calendar_feed"}
    assert sum(1 for r in rows if "error" in r) == 4  # two robots hosts, one calendar sample, one market sample
    for form in _forms():
        assert form not in text, form


def test_import_results_log_file_carries_no_passphrase(monkeypatch, tmp_path):
    """``import_all_feeds`` appends every per-feed verdict to ``import_results.jsonl`` (bundle ``imports``, backup log member); a
    feed whose import raises with the passphrase in its words must reach the file without it. MUTATION TARGET: ``record_text`` at
    the per-feed ``except`` of ``src/api/markets.py``."""
    from src.api import markets
    from src.markets.feed_catalog import Feed

    feeds = [Feed(key="g1", name="G", symbol="G1", category="metals", url="https://f.example/g.csv", currency="USD", unit="t", market="m")]
    monkeypatch.setattr("src.markets.feed_catalog.feeds_for_category", lambda category=None: feeds)
    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _quoted)
    db = SimpleNamespace(rollback=lambda: None)
    out = markets.import_all_feeds(db=db)
    assert out["failed"] == 1
    text = (tmp_path / "import_results.jsonl").read_text(encoding="utf-8")
    assert "RuntimeError" in text
    for form in _forms():
        assert form not in text, form
        assert form not in json.dumps(out), form


_KEY_STATEMENT = re.compile(r"(pragma\s+(hex)?key|pragma\s+rekey|\bkey\s+'[^']|\bhexkey\b)", re.IGNORECASE)


def test_no_statement_the_merge_runs_can_carry_a_key():
    """The merge's per-statement labels (``_stmt_label``: the first 120 characters of the SQL) go to the beat files and the journal,
    and the bundle carries both. They are not scrubbed, because nothing the merge traces holds a key: ATTACH uses an empty
    ``KEY ''`` and no key statement runs on the traced connection. This pins that reading, so the day a keyed statement is written
    into the merge it fails here, and the label gets its scrub in the same change. MUTATION TARGET: add ``PRAGMA key = '{k}'`` to a
    string in ``src/backup/merge.py``."""
    tree = ast.parse((SRC / "backup" / "merge.py").read_text(encoding="utf-8"))
    hits = [
        (n.lineno, n.value[:80])
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _KEY_STATEMENT.search(n.value)
        and not re.fullmatch(r"\s*ATTACH.*KEY\s+''.*", n.value, re.IGNORECASE | re.DOTALL)
    ]
    assert not hits, f"a keyed statement in the merge would be traced into a journal label unscrubbed: {hits}"

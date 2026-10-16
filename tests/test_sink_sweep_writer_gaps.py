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


# ---- the bundle's readers of files an older build wrote raw ---------------------------------------------------------------------


def _bundle():
    from src.api.diagnostics import bundle

    return bundle


def test_left_over_journals_are_checked_before_they_are_cut_and_folded(tmp_path):
    """A left-over all-diagnostics journal from an older build holds a passphrase an error quoted: the line is checked whole, BEFORE
    the per-line cut (a cut through a key leaves its start), and the torn line's ``raw`` excerpt carries none either. MUTATION TARGETS:
    the scrub before the cut in ``_read_previous_run_journals``, the one on the parsed record and the one on the ``raw`` excerpt."""
    b = _bundle()
    good = json.dumps({"event": "end", "file": "m", "outcome": "error", "error": f"near {_PW} here"})
    torn = '{"event": "end", "file": "m", "error": "' + _PW + " torn"
    long_pad = "x" * (b._PREVIOUS_JOURNAL_MAX_LINE_CHARS - 12)
    cut = json.dumps({"event": "note", "pad": long_pad, "error": _PW})  # the key straddles the per-line cut
    j = tmp_path / "oo-all-diagnostics-20260101-000000.journal.jsonl"
    j.write_text("\n".join([good, torn, cut]) + "\n", encoding="utf-8")
    previous = b._read_previous_run_journals(tmp_path, tmp_path / "own.journal.jsonl")
    text, block = b._fold_previous_run_journals(previous)
    blob = text + json.dumps(block) + json.dumps(previous)
    for form in _forms():
        assert form not in blob, form
    assert block["runs"][0]["unparsed_lines"] >= 1
    # the fold alone, handed raw lines, is also safe (it is called with whatever a reader gives it)
    text2, block2 = b._fold_previous_run_journals({"carried": [{"journal": "j", "bytes": 1, "truncated": False, "lines": [good, torn]}], "not_carried": []})
    for form in _forms():
        assert form not in text2 + json.dumps(block2), form


def test_import_results_member_checks_what_an_older_build_wrote(monkeypatch, tmp_path):
    """The bundle's ``imports`` member reads the last 50 lines of ``import_results.jsonl`` (never rotated). An older build's line holds
    the passphrase in an error; a torn line is counted and named, never passed on. MUTATION TARGET: the scrub of each record."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    old = {"at": "2026-01-01", "kind": "commodity", "results": [{"key": "k", "detail": f"driver said {_PW}"}]}
    (tmp_path / "import_results.jsonl").write_text(json.dumps(old) + '\n{"at": "torn ' + _PW + "\n", encoding="utf-8")
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    with TestClient(app) as c:
        data = c.get("/api/diagnostics/debug-bundle").json()["data"]
    imports = data["imports"]
    for form in _forms():
        assert form not in json.dumps(imports), form
    assert any(isinstance(r, dict) and r.get("lines_not_read") == 1 for r in imports), imports


def test_merge_diag_checks_the_statement_labels_an_older_beat_or_journal_holds(monkeypatch, tmp_path):
    """The merge diagnostics publish the ``sql`` label of every beat and journal record. An older file can hold one with the passphrase in
    it; the label is checked before it becomes a key. MUTATION TARGETS: the two ``scrubbed`` calls on the labels and the one on the last
    record."""
    from src.monitoring import merge_diag

    monkeypatch.setattr("src.backup.runlog.run_logs_dir", lambda: tmp_path)
    label = f"ATTACH 'x' AS m KEY '{_PW}'"
    beat = {"ev": "beat", "sql": label, "sql_s": 3.0}
    (tmp_path / "20260101T000000Z-a.beat.jsonl").write_text(json.dumps(beat) + "\n" + json.dumps(beat) + "\n", encoding="utf-8")
    recs = [
        {"ev": "merge_statement_begin", "el_s": 1.0, "sql": label},
        {"ev": "merge_statement_begin", "el_s": 4.0, "sql": "SELECT 2"},
        {"ev": "merge_statement_begin", "el_s": 6.0, "sql": label, "note": f"also {_PW}"},  # the last record is published whole
    ]
    (tmp_path / "20260101T000000Z-b.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    out = json.dumps([merge_diag.sampled_statements(), merge_diag.attributed_statements()])
    for form in _forms():
        assert form not in out, form
    assert "ATTACH" in out, "the label is still reported, with the key taken out"


def test_a_withheld_journal_line_is_counted_as_withheld_not_as_torn(monkeypatch):
    """A left-over journal line that parses but cannot be walked by the check is withheld and COUNTED as that, beside (not inside) the
    torn lines. MUTATION TARGET: the ``withheld`` branch in ``_fold_previous_run_journals``."""
    b = _bundle()
    good = json.dumps({"event": "end", "file": "m", "outcome": "ok"})
    monkeypatch.setattr(b, "_scrubbed_value", lambda value, *a, **k: "unreadable" if isinstance(value, dict) else value)
    text, block = b._fold_previous_run_journals({"carried": [{"journal": "j", "bytes": 1, "truncated": False, "lines": [good, "{torn"]}], "not_carried": []})
    run = block["runs"][0]
    assert run["withheld_lines"] == 1 and run["unparsed_lines"] == 1, run
    assert '"event": "end"' not in text, "a line that could not be checked is not passed on"


def test_a_big_journal_that_is_not_utf8_only_near_its_end_is_still_flagged(tmp_path, monkeypatch):
    """The decoder fails per block: records before the bad bytes in that block are lost with it, and a listing that said nothing would read
    as a whole journal. MUTATION TARGET: ``milestones_not_read`` in ``list_runs``."""
    from src.backup import runlog

    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path)
    rows = [{"ev": "run_begin", "t": "2026-01-01T00:00:00Z", "kind": "k"}] + [{"ev": "note", "i": i, "pad": "x" * 200} for i in range(400)]
    (tmp_path / "20260101T000000Z-big.jsonl").write_bytes(("\n".join(json.dumps(r) for r in rows) + "\n").encode() + b'\xff\xfe{"ev":"x"}\n')
    entry = runlog.list_runs()[0]
    assert entry["milestones_not_read"]["file_not_utf8"] is True, entry

"""Post-import CORPUS-DELTA view: a committed restore-merge reports a before -> after
per-dimension snapshot (maintainer field report 2026-07-20, after merging a 10 GB
corpus: "4,855,433 imported… I'm sure it doesn't contain 5 million articles" — the old
headline summed EVERY merged TABLE, not articles).

This drives the REAL commit path through the torture helper (mirrors
test_restore_bumps_epoch.py) and asserts ``report["corpus_delta"]`` carries the real
before/after counters -- cheap COUNT/DISTINCT/MIN/MAX aggregates, never a whole-table
content re-scan -- and that they match the known fixture delta.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"


def _helper(data_dir: Path, *args: str) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=180,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_committed_restore_reports_a_corpus_delta_snapshot(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-d1").get("artifact")
    _helper(a, "build", "A")

    report = _helper(a, "merge", str(art), "--passphrase", "pw-d1", "--commit")["report"]
    assert report["committed"] is True

    delta = report["corpus_delta"]
    assert set(delta) == {"before", "after"}
    for snap in (delta["before"], delta["after"]):
        assert set(snap) == {
            "articles", "sources", "languages", "countries", "keywords",
            "date_min", "date_max",
        }

    # The fixture: A starts with 1 source / 2 articles / 2 keywords; merging B in adds
    # B's own source + unique article + filler article (2 new articles) and B's unique
    # keyword (the shared "elections" keyword collapses as a duplicate, not double-added).
    assert delta["before"]["articles"] == 2
    assert delta["after"]["articles"] == 4
    assert delta["before"]["sources"] == 1
    assert delta["after"]["sources"] == 2
    assert delta["before"]["keywords"] == 2
    assert delta["after"]["keywords"] == 3

    # plan.articles.new is the SAME real per-article count the delta's articles
    # dimension must agree with (the root-cause fix: articles are counted once, the
    # same way, everywhere -- never re-derived from a cross-table row-sum).
    articles_new = report["plan"]["articles"]["new"]
    assert delta["after"]["articles"] - delta["before"]["articles"] == articles_new


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_preview_restore_carries_no_corpus_delta(tmp_path):
    """A dry-run preview (commit=False) never touches the live corpus, so there is no
    "after" to report -- the delta is commit-only, never a fabricated pair."""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-d2").get("artifact")
    _helper(a, "build", "A")

    report = _helper(a, "merge", str(art), "--passphrase", "pw-d2")["report"]  # no --commit
    assert report["committed"] is False
    assert "corpus_delta" not in report

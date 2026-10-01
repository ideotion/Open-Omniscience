"""Batch B25 of the 2026-09-27 delegated re-walk, pinned: the Import dialog (row I).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What renders is behaviour, run as real, EXTRACTED code under node: the result block's
source-qualification lines (I-1, I-2) in ``tests/import_conclusion_node_test.js``, the
stage and per-backup rows' dots (I-4, I-7) in ``tests/import_stages_node_test.js``, and the
reopened dialog (I-5) in ``tests/import_reopen_node_test.js``, which this file runs. What
is a contract between two files is pinned here: the folder field's direction (I-3), the
re-index job's detail line and the keys it needs (I-6), and the zh wording of the result
block (I-8).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(key: str) -> None:
    want = sorted(re.findall(r"\{(\w+)\}", key))
    for code, d in _locales().items():
        assert key in d, f"{code}.json has no key {key!r}"
        assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
            f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_reopen_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "import_reopen_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "3 passed" in proc.stdout, proc.stdout


# --- I-3: a folder path reads left to right in every language --------------------------------- #

def test_every_folder_the_picker_fills_is_a_left_to_right_field():
    """An RTL page reordered '/mnt/backup' into 'mnt/backup/' and clipped the start of a long
    path in the Import field, where the Export destination (#ux-dest, J3) was already fixed.
    The picker's own targets are read off its call sites, so a new one is covered too."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    targets = sorted(set(re.findall(r"ooFolderPicker\('([\w-]+)'", html)))
    assert "ux-imp-src" in targets and "ux-dest" in targets, targets
    for tid in targets:
        tag = re.search(r'<input id="' + re.escape(tid) + r'"[^>]*>', html)
        assert tag, f"no <input id={tid!r}> for a folder-picker target"
        assert 'dir="ltr"' in tag.group(0), f"#{tid} inherits the page's direction: {tag.group(0)}"
    # The picker's OWN line showing the same path (#fp-path, filled by _fpNav in app-map.js):
    # the re-walk's review saw '/tmp' drawn as 'tmp/' there once the fields above were fixed.
    line = re.search(r'<div id="fp-path"[^>]*>', html)
    assert line, "the folder picker lost its path line #fp-path"
    assert 'dir="ltr"' in line.group(0), f"#fp-path inherits the page's direction: {line.group(0)}"


# --- I-6: the re-index job's detail line travels as a keyed frame ----------------------------- #

class _Ctx:
    """The JobContext surface the resume worker uses, keeping each detail AS SENT."""

    def __init__(self) -> None:
        self.stopping = False
        self.details: list = []

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail is not None:
            self.details.append(detail)

    def set_metrics(self, metrics) -> None:
        pass


def _drain(monkeypatch, batches):
    import src.api.backup_v2 as B
    import src.backup.merge as M

    monkeypatch.setattr(M, "reindex_backlog", lambda: {
        "available": True, "batches": batches, "batches_pending": len(batches),
        "articles_pending": sum(b["articles"] for b in batches),
    })
    monkeypatch.setattr(M, "reindex_imported_articles",
                        lambda bid, **kw: {"reindexed": 1, "failed": 0})
    ctx = _Ctx()
    B._reindex_resume_worker(ctx)
    return ctx.details


def test_the_per_import_line_is_a_frame_beside_the_unchanged_english(monkeypatch):
    """'import 2 (1200 article(s))' printed in English, its count ungrouped, in fr and zh:
    a plain str left detail_i18n null, so /tasks fell back to t() of a sentence no key
    matched. The count is a one/many keyed phrase (the task manager formats the number)."""
    from src.jobs.background import Framed

    details = _drain(monkeypatch, [{"batch_id": 2, "articles": 1200}, {"batch_id": 5, "articles": 1}])
    lines = [d for d in details if str(d).startswith("import ")]
    assert [str(d) for d in lines] == ["import 2 (1200 article(s))", "import 5 (1 article(s))"]
    for d in lines:
        assert isinstance(d, Framed), f"a plain str reaches no key: {d!r}"
        assert d.i18n == "import {batch} ({articles})"
    assert lines[0].vars == {"batch": "2", "articles": {"i18n": "{n} articles", "vars": {"n": 1200}}}
    assert lines[1].vars["articles"] == {"i18n": "{n} article", "vars": {"n": 1}}
    # the batch id is DATA (an identifier, not a quantity to group)
    assert isinstance(lines[0].vars["batch"], str)


def test_the_first_line_of_the_same_job_is_keyed_too(monkeypatch):
    from src.jobs.background import Framed

    first = _drain(monkeypatch, [{"batch_id": 1, "articles": 3}])[0]
    assert isinstance(first, Framed) and first.i18n == "starting…", repr(first)


@pytest.mark.parametrize("key", [
    "import {batch} ({articles})", "{n} article", "{n} articles", "starting…",
    # I-1 / I-2's two new strings
    "engine not recorded",
    "Sources already judged are counted per backup, below: the backups of one run overlap, "
    "so those counts are not added up.",
])
def test_every_key_the_new_lines_need_is_there_x12(key):
    _keyed_everywhere(key)


# --- I-8: the zh result block ------------------------------------------------------------------ #

_RESULT_BLOCK_KEYS = [
    "database records, all types",
    "Your corpus grew by {articles} articles from {sources} new sources spanning {languages} new languages.",
    "How your corpus grew",
    "Backup disagreed, your verdict kept: {n}",
    "{n} conflict (your version kept)",
    "{n} conflicts (your version kept)",
    "conflicts (your version kept)",
    "Conflicts (your version kept)",
    "Nothing new: every row in this archive is already in your corpus.",
    "Snapshotting your corpus…",
    # the lost-work line of the result block and the run view's staged line (review round 2)
    "Discarded, not in your corpus: {n} — the shared working copy was never saved. Import them again.",
    "Merged, not yet saved: {n} — written to your corpus at the next checkpoint, one every {k} backups.",
]


@pytest.mark.parametrize("key", _RESULT_BLOCK_KEYS)
def test_the_zh_result_block_uses_full_width_punctuation_and_one_form_of_address(key):
    """The result block printed '数据库记录(所有类型)' and '…新增了 933 篇文章,来自…' with
    half-width punctuation, and said 您 where the rest of the Import dialog says 你."""
    value = _locales()["zh"][key]
    assert "您" not in value, f"{key!r} addresses the reader as 您 inside a 你 dialog: {value!r}"
    assert not re.search(r"[,()]", value), f"half-width punctuation in zh {key!r}: {value!r}"

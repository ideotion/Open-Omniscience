"""A member the write-ahead-log guard stood aside from is recorded as paused, not as an error.

Before: while the log is pinned, the card-audit member raises ``HeavyPaused`` (an HTTP 503 with no chained timeout). The member loop knew only a 503 chained to a
``StatementTimeout``, so the guard working was written as outcome ``error`` with a ``card-audit.json.error.txt``, and the error tally counted it. After: matched by class
name through the MRO (the bundle does not import heavy.py), the member is ``skipped-paused`` with its own marker file, and a real failure is still ``error``."""

from __future__ import annotations

import json
import zipfile

import pytest

from src.api import diagnostics as d
from src.api.diagnostics import bundle as _diag_bundle
from src.api.heavy import HeavyPaused


class _Ctx:
    stopping = False

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        pass


@pytest.fixture
def members(monkeypatch, tmp_path):
    def _paused():
        raise HeavyPaused(10)

    def _failed():
        raise RuntimeError("this one really failed")

    rows = [("ok.json", lambda: {"x": 1}), ("paused.json", _paused), ("failed.json", _failed)]
    monkeypatch.setattr(_diag_bundle, "_all_diagnostics_members", lambda db: rows)
    monkeypatch.setattr(_diag_bundle, "_all_diagnostics_dir", lambda: tmp_path)


def test_a_paused_member_is_skipped_paused_and_a_real_failure_stays_an_error(members):
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        names = set(z.namelist())
        by_file = {m["file"]: m for m in json.loads(z.read("manifest.json"))["members"]}
    assert by_file["paused.json"]["outcome"] == "skipped-paused" and by_file["paused.json"]["ok"] is False
    assert "paused.json.skipped-paused.txt" in names and "paused.json.error.txt" not in names
    assert by_file["failed.json"]["outcome"] == "error" and "failed.json.error.txt" in names
    assert by_file["ok.json"]["outcome"] == "ok"

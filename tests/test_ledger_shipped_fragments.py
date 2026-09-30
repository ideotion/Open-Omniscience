"""The shipped ledger takes one file per new row, so parallel PRs never share a line
(scripts/ledger_shipped.py). GitHub does not apply `merge=union`, so a row appended to the
shared file made every open PR conflict after every merge."""
from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "ledger_shipped.py"
_spec = importlib.util.spec_from_file_location("ledger_shipped", _SCRIPT)
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)

_ROW = {
    "date": "2026-09-30", "area": "tests", "item": "An item, with a comma", "status": "shipped",
    "refs": "PR #1", "key_paths": "a.py; b.py", "summary": 'Two\nlines and a "quote".',
}


def _ledger(tmp_path: Path) -> Path:
    p = tmp_path / "shipped.csv"
    p.write_bytes(
        b"date,area,item,status,refs,key_paths,summary\r\n2026-01-01,x,y,shipped,PR #0,k,s\n"
    )
    return p


def test_new_writes_one_fragment_that_reads_back_exactly(tmp_path):
    csv_path = _ledger(tmp_path)
    path = ls.new(_ROW, csv_path)
    assert path.parent == tmp_path / "shipped.d" and path.name.startswith("2026-09-30-")
    assert ls.fragment_rows(csv_path) == [[_ROW[k] for k in ls.HEADER]]
    assert ls.check(csv_path) == []


def test_fold_appends_in_binary_and_removes_the_fragments(tmp_path):
    csv_path = _ledger(tmp_path)
    before = csv_path.read_bytes()
    ls.new(_ROW, csv_path)
    assert ls.fold(csv_path) == 1
    after = csv_path.read_bytes()
    assert after.startswith(before), "the existing bytes, CRLF included, must be untouched"
    assert not list((tmp_path / "shipped.d").glob("*.csv"))
    rows = list(csv.reader(io.StringIO(after.decode(), newline="")))
    assert rows[-1] == [_ROW[k] for k in ls.HEADER]


@pytest.mark.parametrize(
    "body,needle",
    [
        ("date,area\n2026-09-30,x\n", "ledger header"),
        (",".join(ls.HEADER) + "\n", "exactly one row"),
        (",".join(ls.HEADER) + "\n2026-09-30,a,b,c,d,e,f\n2026-09-30,a,b2,c,d,e,f\n", "exactly one row"),
        (",".join(ls.HEADER) + "\n2026-09-29,a,b,c,d,e,f\n", "start with the row's date"),
    ],
)
def test_a_malformed_fragment_is_named(tmp_path, body, needle):
    csv_path = _ledger(tmp_path)
    d = tmp_path / "shipped.d"
    d.mkdir()
    (d / "2026-09-30-bad.csv").write_text(body, encoding="utf-8")
    problems = ls.check(csv_path)
    assert len(problems) == 1 and needle in problems[0] and "2026-09-30-bad.csv" in problems[0]
    with pytest.raises(SystemExit):
        ls.fold(csv_path)


def test_a_fragment_repeating_a_ledger_key_is_refused(tmp_path):
    csv_path = _ledger(tmp_path)
    ls.new({**_ROW, "date": "2026-01-01", "area": "x", "item": "y"}, csv_path)
    assert any("already in the ledger" in p for p in ls.check(csv_path))


def test_the_real_fragments_are_well_formed_and_carry_no_placeholder():
    csv_path = _ROOT / "docs" / "ledger" / "shipped.csv"
    assert ls.check(csv_path) == []
    for row in ls.fragment_rows(csv_path):
        assert "pending" not in row[4].lower(), f"unswept `PR pending` in {row[0]} {row[1]}"


def test_release_notes_reads_fragments_after_the_file(tmp_path):
    spec = importlib.util.spec_from_file_location("rn_frag", _ROOT / "scripts" / "release_notes.py")
    import sys

    rn = importlib.util.module_from_spec(spec)
    sys.modules["rn_frag"] = rn
    spec.loader.exec_module(rn)
    csv_path = _ledger(tmp_path)
    ls.new(_ROW, csv_path)
    rows = rn.read_rows(csv_path)
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-09-30"]
    assert rows[-1]["summary"] == _ROW["summary"]

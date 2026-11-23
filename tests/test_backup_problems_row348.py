"""Row 348: every backup-verify problem carries a stable code + params beside its English line.

The verify panel rendered the server's English ``problems`` lines as they came, so a
non-English reader got English in the one place a backup's health is explained. The
server now adds ``problem_codes`` (same order, additive: ``problems`` is unchanged for API
callers and the P0 check) and the panel says each in the reader's language, falling back
to the English line for a code it does not know. The verdict logic is unchanged.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup.stream_backup import verify_stream_backup
from tests.test_stream_backup import _backup, _make_corpus

ROOT = Path(__file__).resolve().parent.parent
SB = ROOT / "src" / "backup" / "stream_backup.py"
JS = ROOT / "src" / "static" / "app-backup.js"


def _fail_calls() -> list[ast.Call]:
    tree = ast.parse(SB.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "verify_stream_backup"
    )
    return [
        c
        for c in ast.walk(fn)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_fail"
    ]


def _js_frames() -> dict[str, str]:
    src = JS.read_text(encoding="utf-8")
    blk = src[src.index("const BACKUP_PROBLEM_FRAMES = {") :]
    blk = blk[: blk.index("};")]
    return dict(re.findall(r'^\s*"([\w-]+)": "(.*)",$', blk, re.M))


def test_every_fail_site_has_a_code_the_panel_can_say():
    calls = _fail_calls()
    assert len(calls) >= 8
    frames = _js_frames()
    seen: set[str] = set()
    for c in calls:
        assert len(c.args) >= 2, f"_fail at line {c.lineno} has no code"
        code = c.args[1]
        codes = (
            [code.value]
            if isinstance(code, ast.Constant)
            else [x.value for x in (code.body, code.orelse)]  # the signature's IfExp
            if isinstance(code, ast.IfExp)
            else None
        )
        assert codes, f"_fail at line {c.lineno}: the code must be a literal"
        seen.update(codes)
        for k in codes:
            assert k in frames, f"code {k!r} (line {c.lineno}) has no frame in app-backup.js"
            params = {kw.arg for kw in c.keywords}
            assert params == set(re.findall(r"\{(\w+)\}", frames[k])), (k, params)
    assert seen == set(frames), f"frames with no server code: {set(frames) - seen}"


def test_every_frame_is_keyed_in_all_twelve_locales_with_its_placeholders():
    frames = _js_frames()
    files = sorted((ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for frame in frames.values():
            assert frame in d, f"{f.name} lacks {frame[:40]}"
            assert set(re.findall(r"\{\w+\}", d[frame])) == set(re.findall(r"\{\w+\}", frame)), (
                f.name
            )


def test_codes_ride_beside_the_unchanged_english_lines(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    ok = verify_stream_backup(dest, passphrase="pw")
    assert ok["ok"] is True and ok["problems"] == [] and ok["problem_codes"] == []

    deep = verify_stream_backup(dest, passphrase="WRONG")
    assert deep["ok"] is False
    assert deep["problems"] == ["the passphrase does not match this volume set"]
    assert deep["problem_codes"] == [{"code": "passphrase-mismatch", "params": {}}]

    for p in dest.glob("*.oopar"):
        p.unlink()
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    raw = bytearray(victim.read_bytes())
    raw[500] ^= 0x01
    victim.write_bytes(bytes(raw))
    rep = verify_stream_backup(dest)
    assert len(rep["problems"]) == len(rep["problem_codes"])
    coded = {c["code"]: c["params"] for c in rep["problem_codes"]}
    assert coded["bad-volumes"] == {"volumes": victim.name}
    assert (
        victim.name
        in rep["problems"][[c["code"] for c in rep["problem_codes"]].index("bad-volumes")]
    )


def test_the_panel_helper():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(ROOT / "tests" / "backup_problems_row348_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr

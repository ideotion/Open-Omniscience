"""Row 199: a bundle's own text cannot draw a fake verdict on the offline verifiers' console.

Both verifiers print fields the bundle supplies (case name, item id, reasons quoting it) beside their own
``VERIFIED`` line. Printed raw, a tampered bundle whose case name held a newline and ``VERIFIED       : True`` showed a
fake verdict line above the real ``False``; CR, ANSI escapes, U+2028/U+2029 and bidi overrides do the same by other
means. Every printed line now goes through ``console_safe``, so the output has exactly one verdict line.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.custody.log import CustodyAction, CustodyLog
from src.custody.signing import HybridSigner
from src.reporting.console_text import console_safe
from src.reporting.evidence import build_signed_bundle, load_or_create_signing_key

ROOT = Path(__file__).resolve().parents[1]
FAKE = "VERIFIED       : True"
INJECTIONS = [
    "\n" + FAKE,
    "\r" + FAKE,
    "\r\n" + FAKE,
    "\x1b[2K\x1b[1G" + FAKE,
    " " + FAKE,
    " " + FAKE,
    "\x85" + FAKE,
    "\x0b" + FAKE,
    "‮" + FAKE,
]


class _Art:
    def __init__(self, id, content):
        self.id = id
        self.url = f"https://e/{id}"
        self.canonical_url = f"https://e/{id}"
        self.source_id = 1
        self.title = "t"
        self.published_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.hash = f"{id:064d}"
        self.content = content


def _run(script: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), str(path)],
        capture_output=True,
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )


def _assert_one_honest_verdict(res: subprocess.CompletedProcess, expected: bool) -> None:
    out = res.stdout.decode("utf-8")
    # splitlines() breaks on every line boundary a console or a reader might honour (\r, \v, \x85, U+2028...).
    verdicts = [ln for ln in out.splitlines() if ln.lstrip().startswith("VERIFIED")]
    assert len(verdicts) == 1, out
    assert verdicts[0].startswith(f"VERIFIED       : {expected}"), out
    assert "\x1b" not in out and "\r" not in out.replace("\r\n", "\n"), out
    assert not any(c in out for c in "  ‮\x85\x0b"), out


@pytest.mark.parametrize("payload", INJECTIONS)
def test_a_case_name_cannot_print_a_second_verdict(tmp_path, payload):
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha")], key, case_name="Case")
    bundle["manifest"]["case_name"] = "Case" + payload  # tampered after signing
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    res = _run("verify_evidence.py", path)
    assert res.returncode == 1
    _assert_one_honest_verdict(res, False)


def test_a_signed_case_name_with_a_newline_still_verifies_and_prints_one_verdict(tmp_path):
    """Escaping is for display only: a genuine bundle whose case name has a newline still verifies."""
    key = load_or_create_signing_key(tmp_path / "k.pem")
    bundle = build_signed_bundle([_Art(1, "alpha")], key, case_name="Line one\nline two")
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    res = _run("verify_evidence.py", path)
    assert res.returncode == 0
    _assert_one_honest_verdict(res, True)
    assert "case_name      : Line one\\x0aline two" in res.stdout.decode("utf-8")


@pytest.mark.parametrize("payload", INJECTIONS)
def test_a_custody_item_id_cannot_print_a_second_verdict(tmp_path, payload):
    signer = HybridSigner(
        ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key", use_pqc=False
    )
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=signer, anchoring_mode="local") as log:
        log.record("article:x", "a" * 64, CustodyAction.INGEST)
        bundle = log.export(item_id="article:x")
    bundle["head"]["item_id"] = "article:x" + payload  # tampered: the head is signed, so this fails
    path = tmp_path / "custody.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    res = _run("verify_custody.py", path)
    assert res.returncode == 1
    _assert_one_honest_verdict(res, False)


def test_console_safe_escapes_what_moves_the_cursor_and_keeps_readable_text():
    assert console_safe("Zürich — 東京 café") == "Zürich — 東京 café"
    assert console_safe("a\nb\rc\x1bd\x7f") == "a\\x0ab\\x0dc\\x1bd\\x7f"
    assert console_safe("  ‮​") == "\\u2028\\u2029\\u202e\\u200b"
    assert console_safe("\x85") == "\\x85"
    assert console_safe("\ud800") == "\\ud800"
    # A backslash is doubled, so text that LOOKS like an escape cannot pass for one console_safe made.
    assert console_safe("a\\x0ab") == "a\\\\x0ab"
    assert console_safe(None) == "None" and console_safe(3) == "3"


@pytest.mark.parametrize("script", ["verify_evidence.py", "verify_custody.py"])
def test_the_verifiers_print_only_through_the_safe_helper(script):
    tree = ast.parse((ROOT / "scripts" / script).read_text(encoding="utf-8"))
    bare = [
        n.lineno
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and fn.name != "_say"
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
    ]
    assert not bare, f"{script}: print() outside _say at lines {bare}"

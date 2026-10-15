"""A thread's name can hold a passphrase (it is named from a request); no record or log line carries it raw."""
from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import pytest

MARKER = "horse-battery-staple-91"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", MARKER)


def test_thread_snapshot_names_carry_no_held_passphrase(held):
    from src.monitoring import session_hwm

    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name=f"oo-dump-{MARKER}", daemon=True)
    t.start()
    try:
        snap = session_hwm.thread_snapshot()
    finally:
        stop.set()
        t.join(2)
    names = [e["name"] for e in snap]
    assert any(n.startswith("oo-dump-") for n in names), names  # the thread was seen
    assert MARKER not in json.dumps(snap)


def test_session_forensics_member_nets_an_older_snapshot_that_kept_the_name(held, monkeypatch):
    from src.api.diagnostics import bundle

    old = {"previous_session_peaks": {"threads": [{"name": f"served-cache-{MARKER}", "stack": ["f"]}]}}
    monkeypatch.setattr(bundle, "session_forensics_report", lambda download=False: old)
    member = bundle._session_forensics_member()
    text = json.dumps(member)
    assert "served-cache-" in text
    assert MARKER not in text


def _marks_with_the_name() -> dict:
    snap = {"why": "near the line", "threads": [{"name": f"oo-dump-{MARKER}", "stack": ["f (x.py:1)"]}]}
    return {"session_id": "s1", "pressure": [dict(snap)], "pressure_light": [dict(snap)]}


def test_scrub_marks_takes_the_name_out_of_an_older_sidecar(held):
    from src.monitoring.release_view import scrub_marks

    out, failed = scrub_marks(_marks_with_the_name())
    assert failed is None
    text = json.dumps(out)
    assert "oo-dump-" in text and MARKER not in text


def test_the_standalone_forensics_route_and_its_text_carry_no_name(held, monkeypatch):
    from src.monitoring import forensics, session_history, session_hwm

    monkeypatch.setattr(session_hwm, "previous_why", lambda: (_marks_with_the_name(), None))
    monkeypatch.setattr(session_history, "previous_session_id", lambda: "s1")
    peaks = forensics._previous_peaks()
    assert peaks and peaks.get("available") is True
    assert MARKER not in json.dumps(peaks)
    assert MARKER not in forensics.render_text(
        {"previous_session": {"previous_session": "unclean-end", "previous_session_peaks": peaks}}
    )


def test_the_end_record_written_to_the_ledger_carries_no_name(held):
    from src.monitoring import session_history

    hwm = {"pressure": [{"why": "x", "threads": [{"name": f"served-cache-{MARKER}", "stack": ["f (x.py:1)"]}]}]}
    rec = session_history._pressure_record(hwm)
    assert rec and rec.get("threads")
    assert MARKER not in json.dumps(rec)


# The sites that write a thread's name into a file or a log line, each through scrubbed_name. Read from the syntax tree, so
# an alias, getattr, getName or a bare current_thread import is seen too.
_FILES = (
    "src/database/damage.py",
    "src/database/writer.py",
    "src/database/maintenance.py",
    "src/monitoring/session_hwm.py",
    "src/monitoring/session_history.py",
)
#: Held in memory only; every line and member that PUBLISHES it scrubs it.
_IN_MEMORY_ONLY = {("src/database/writer.py", "self._holder = threading.current_thread().name")}
_THREADISH = {"thread", "cur", "current", "th", "t", "me"}


def _is_thread_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _THREADISH
    if isinstance(node, ast.Call):
        f = node.func
        return (isinstance(f, ast.Attribute) and f.attr in {"current_thread", "currentThread", "main_thread"}) or (
            isinstance(f, ast.Name) and f.id in {"current_thread", "currentThread", "main_thread"}
        )
    return False


def _raw_thread_names(rel: str) -> list[str]:
    src = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def wrapped(node: ast.AST) -> bool:
        cur = parents.get(id(node))
        while cur is not None:
            if isinstance(cur, ast.Call) and getattr(cur.func, "id", getattr(cur.func, "attr", "")) == "scrubbed_name":
                return True
            cur = parents.get(id(cur))
        return False

    bad: list[str] = []
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Attribute) and node.attr in {"name", "getName", "_name"} and _is_thread_expr(node.value):
            hit = True
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr" and len(node.args) >= 2:
            a = node.args[1]
            hit = _is_thread_expr(node.args[0]) and isinstance(a, ast.Constant) and a.value in {"name", "_name"}
        elif isinstance(node, ast.ImportFrom) and node.module == "threading":
            hit = any(a.name in {"current_thread", "currentThread"} for a in node.names)
        if hit and not wrapped(node):
            line = lines[node.lineno - 1].strip()
            if (rel, line) not in _IN_MEMORY_ONLY:
                bad.append(f"{rel}:{node.lineno}: {line}")
    return bad


@pytest.mark.parametrize("rel", _FILES)
def test_no_raw_thread_name_reaches_a_record_or_a_log_in(rel):
    assert not _raw_thread_names(rel)


def test_the_guard_sees_the_forms_it_claims_to(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    probe = tmp_path / "src" / "p.py"
    probe.write_text(
        "import threading\n"
        "from threading import current_thread\n"
        "a = getattr(thread, 'name')\n"
        "cur = threading.current_thread()\n"
        "b = cur.name\n"
        "c = threading.current_thread().getName()\n"
        "ok = scrubbed_name(threading.current_thread().name)\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    found = _raw_thread_names("src/p.py")
    assert len(found) == 4, found  # the import, getattr, cur.name, getName; the wrapped one passes


def test_the_write_gate_holder_lines_are_scrubbed():
    text = (ROOT / "src/database/writer.py").read_text(encoding="utf-8")
    assert 'by %r", held, scrubbed_name(holder))' in text
    assert "        scrubbed_name(holder),\n        s.get(\"waiters\")," in text

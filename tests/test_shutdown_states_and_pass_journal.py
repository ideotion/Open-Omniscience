"""A deliberate stop must never read as a crash, and a death in the pass tail must
name its step (S0.2 + S0.5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

TWO DEFECTS (2026-09-02).

S0.2 — the ADVERTISED way to stop the app is "close this window" (scripts/launch.sh
prints exactly that), and closing a terminal sends SIGHUP to its foreground process
group. uvicorn installs handlers for SIGINT and SIGTERM only, so SIGHUP kept its
default disposition: the process died before the lifespan shutdown ran, the sentinel
was never flipped, and the next boot reported an unclean end. Ctrl-C and the in-app
power button were already clean — this covers the one path that was not. The sentinel
also gained teardown phases, because stopping the scheduler and disposing an encrypted
pool is not instant and a death inside that window used to be indistinguishable from a
death hours earlier.

S0.5 — the field's S2 session wrote its pass-end summary and never appended a run
record. Everything between is a window nothing survived, and ``record_run`` sits
BELOW the write-gate checkpoint that can block forever.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys

import pytest

from src.monitoring import forensics
from src.scheduler import pass_journal


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(forensics, "_WAL_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_STOP_SIGNAL", None)
    return tmp_path


# --------------------------------------------------------------------------- #
#  S0.2 — shutdown states
# --------------------------------------------------------------------------- #


def test_a_death_during_teardown_is_distinguishable_from_a_death_before_it(dd):
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    # ... and the process dies here, inside the teardown
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    rep = forensics.previous_session_report()
    assert rep["previous_session"] == "unclean-end-during-shutdown"
    assert rep["shutdown_reason"] == "lifespan shutdown"

    # dying AFTER dispose is a third, different fact
    forensics.record_shutdown_phase("dispose-done")
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    assert forensics.previous_session_report()["previous_session"] == "unclean-end-after-dispose"


def test_a_full_teardown_still_reads_clean(dd):
    """NEGATIVE TWIN. The phases must not turn a clean stop into a reported crash."""
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    forensics.record_shutdown_phase("dispose-done")
    forensics.record_clean_shutdown()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    assert forensics.previous_session_report()["previous_session"] == "clean"


def test_the_signal_that_initiated_the_stop_is_recorded_and_rendered(dd):
    forensics.record_session_start()
    forensics.note_stop_signal("SIGHUP")
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    forensics.record_clean_shutdown()
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    rep = forensics.previous_session_report()
    assert rep["stop_signal"] == "SIGHUP"
    assert "stop initiated by: SIGHUP" in forensics.render_text()


def test_install_signal_handlers_registers_sighup_on_the_real_module(dd):
    """Drives the REAL function, not a stub that 'mirrors main()'. A stub would pass
    whether or not main.py changed — that is the vacuity trap this slice's own brief
    names."""
    from src.api.main import install_signal_handlers

    previous = signal.getsignal(signal.SIGHUP)
    try:
        installed = install_signal_handlers()
        assert "SIGHUP" in installed
        handler = signal.getsignal(signal.SIGHUP)
        assert callable(handler)
        assert handler not in (signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGHUP, previous)


def _uvicorn_run_host() -> ast.FunctionDef:
    """The function that actually starts the server.

    Anchored on the CALL, not on a function NAME: the entry point is ``main()`` but
    the server is started by ``_serve()``, and a guard that assumed ``main`` looked in
    the wrong body and reported a correct wiring as missing. Deriving the host from
    ``uvicorn.run`` also survives a rename."""
    src = open("src/api/main.py", encoding="utf-8").read()
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "run"
                and getattr(getattr(node.func, "value", None), "id", "") == "uvicorn"
            ):
                return fn
    raise AssertionError("no function calls uvicorn.run")


def test_the_handlers_are_installed_before_uvicorn_run():
    """AST guard: the registration must happen before the server starts, or uvicorn's
    own SIGINT/SIGTERM handlers are installed into a process that still dies on HUP."""
    fn = _uvicorn_run_host()
    install_line = uvicorn_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "install_signal_handlers":
                install_line = node.lineno
            elif name == "run" and getattr(getattr(node.func, "value", None), "id", "") == "uvicorn":
                uvicorn_line = node.lineno
    assert install_line is not None, f"{fn.name}() must call install_signal_handlers()"
    assert uvicorn_line is not None
    assert install_line < uvicorn_line


def test_uvicorn_gets_a_graceful_shutdown_deadline():
    """Without one, a logout SIGTERM arriving during a minutes-long request leaves
    the app waiting until logind SIGKILLs it — which skips the lifespan entirely."""
    fn = _uvicorn_run_host()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "run"
            and getattr(getattr(node.func, "value", None), "id", "") == "uvicorn"
        ):
            kwargs = {k.arg for k in node.keywords}
            assert "timeout_graceful_shutdown" in kwargs
            return
    raise AssertionError("no uvicorn.run call found")


def test_a_real_sighup_reaches_the_graceful_path():
    """End-to-end on a REAL signal in a REAL child process: install the handlers, send
    SIGHUP, and assert the process ends through the SIGTERM path the handler re-raises
    onto rather than dying on SIGHUP's default disposition.

    MUTATION: drop the SIGHUP registration and the child dies of SIGHUP (-1), not
    SIGTERM (-15)."""
    code = (
        "import os, signal, sys, time\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from src.api.main import install_signal_handlers\n"
        # uvicorn's own SIGTERM handler is not present here, so stand in for it: the
        # point under test is that SIGHUP is ROUTED onto the SIGTERM path at all.
        "signal.signal(signal.SIGTERM, lambda *a: os._exit(7))\n"
        "install_signal_handlers()\n"
        "os.kill(os.getpid(), signal.SIGHUP)\n"
        "time.sleep(5)\n"
        "os._exit(1)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=60, cwd=os.getcwd()
    )
    assert proc.returncode == 7, (
        f"SIGHUP must reach the graceful path; rc={proc.returncode} "
        f"stderr={proc.stderr.decode()[-2000:]}"
    )


def test_the_lifespan_teardown_actually_stamps_the_phases():
    """MUTATION TARGET, added because the first matrix run found this unguarded.

    The state-machine tests above call ``record_shutdown_phase`` directly, so removing
    the calls from the lifespan reddened nothing — the states were tested and the
    WIRING was not. This reads the parse tree (a parser cannot see a comment, so a
    comment quoting the call name can never satisfy it), scopes to the lifespan, and
    checks both phases are stamped AFTER the yield, in order."""
    src = open("src/api/main.py", encoding="utf-8").read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {
                getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            }
            if "record_clean_shutdown" in names and "record_session_start" in names:
                fn = node
                break
    assert fn is not None, "no function both starts and cleanly ends the session"

    yields = [n.lineno for n in ast.walk(fn) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    assert yields, "the lifespan must yield"
    after_yield = min(yields)

    stamped: dict[str, int] = {}
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and (getattr(node.func, "id", None) == "record_shutdown_phase")
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            stamped[node.args[0].value] = node.lineno
    assert "shutting-down" in stamped, f"the teardown must stamp shutting-down; got {stamped}"
    assert "dispose-done" in stamped, f"the teardown must stamp dispose-done; got {stamped}"
    assert stamped["shutting-down"] > after_yield, "stamp the teardown, not the startup"
    assert stamped["shutting-down"] < stamped["dispose-done"]

    clean = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "record_clean_shutdown"
    ]
    assert clean and min(clean) > stamped["dispose-done"], "clean comes last"


def test_launch_sh_traps_hup():
    src = open("scripts/launch.sh", encoding="utf-8").read()
    line = next(ln for ln in src.splitlines() if ln.strip().startswith("trap "))
    assert "HUP" in line, f"the advertised stop sends SIGHUP; trap is: {line}"


# --------------------------------------------------------------------------- #
#  S0.5 — the pass-tail phase journal
# --------------------------------------------------------------------------- #


def test_a_completed_phase_pairs_and_reports_nothing_unfinished(dd):
    with pass_journal.phase("hygiene", pass_id="p1"):
        pass
    rep = pass_journal.report()
    assert rep["records"] == 2
    assert rep["died_during"] is None


def test_a_phase_that_never_returns_is_named_and_left_unmarked(dd):
    """MUTATION TARGET. A begin with no end IS the evidence — nothing may be written
    to mean 'handled', or every crashed run reads as finished from the first restart."""
    with pass_journal.phase("lane-kick", pass_id="p1"):
        pass
    # the process dies inside the checkpoint: a begin, and then silence
    pj = pass_journal.phase("hygiene", pass_id="p1")
    pj.__enter__()

    rep = pass_journal.report()
    assert rep["died_during"]["phase"] == "hygiene"
    assert "pairing" in rep["died_during"]["basis"].lower()
    # the basis must name what it CANNOT distinguish
    assert "full disk" in rep["died_during"]["basis"].lower()


def test_an_exception_inside_a_phase_is_recorded_and_re_raised(dd):
    with pytest.raises(ValueError):
        with pass_journal.phase("discovery"):
            raise ValueError("boom")
    recs = pass_journal.read()
    end = [r for r in recs if r.get("event") == "phase_end"][-1]
    assert "ValueError: boom" in end["error"]
    assert pass_journal.report()["died_during"] is None  # it ended, badly but it ended


def test_the_journal_never_writes_into_the_scheduler_run_log(dd):
    """Phase records in scheduler_runs.jsonl would surface as phantom passes in the
    task manager, the bundle and forensics (runlog.recent_runs reads every line)."""
    with pass_journal.phase("record-run"):
        pass
    assert (dd / "pass_journal.jsonl").exists()
    assert not (dd / "scheduler_runs.jsonl").exists()


def test_the_journal_is_bounded(dd):
    for i in range(pass_journal._MAX_LINES + 200):
        pass_journal._append({"event": "phase_begin", "phase": f"p{i}"})
    pass_journal.trim()
    lines = (dd / "pass_journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= pass_journal._MAX_LINES


def test_an_unmeasurable_reading_is_absent_from_a_record_never_zero(dd, monkeypatch):
    monkeypatch.setattr(pass_journal, "_readings", dict)
    with pass_journal.phase("hygiene"):
        pass
    rec = pass_journal.read()[0]
    assert "rss_mb" not in rec and "mem_avail_mb" not in rec


def test_the_runner_wraps_the_tail_steps_that_can_hang(dd):
    """The four steps the field window contains, plus the two in the finally. Anchored
    on the CALL, not on a comment mentioning it."""
    src = open("src/scheduler/runner.py", encoding="utf-8").read()
    tree = ast.parse(src)
    wrapped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_tail_phase":
                    if call.args and isinstance(call.args[0], ast.Constant):
                        wrapped.add(call.args[0].value)
    for step in ("lane-kick", "discovery", "source-enrichment", "briefing-refresh-kick",
                 "hygiene", "record-run"):
        assert step in wrapped, f"the pass tail must journal {step!r}; got {sorted(wrapped)}"


def test_the_report_says_where_a_pass_died_from_the_inner_step(dd, monkeypatch):
    """Patch the INNER step (checkpoint_wal), not run_pass_hygiene — the latter
    swallows everything, so patching it proves nothing about the journal."""
    import src.scheduler.hygiene as hygiene

    def _never_returns(*a, **kw):
        raise KeyboardInterrupt("the process died in the checkpoint")

    monkeypatch.setattr(hygiene, "checkpoint_wal", _never_returns, raising=False)
    with pytest.raises(KeyboardInterrupt):
        with pass_journal.phase("hygiene", pass_id="p1"):
            hygiene.checkpoint_wal()
    # the end record exists (the context manager ran) — so simulate the harder case:
    # the process is killed and no end is written at all.
    pass_journal.phase("record-run", pass_id="p1").__enter__()
    rep = pass_journal.report()
    assert rep["died_during"]["phase"] == "record-run"


def test_forensics_surfaces_the_journal_in_the_text_the_maintainer_sends(dd):
    forensics.record_session_start()
    pass_journal.phase("hygiene", pass_id="p1").__enter__()
    txt = forensics.render_text()
    assert "Collector pass tail" in txt
    assert "a phase was never finished: hygiene" in txt


def test_the_journal_never_breaks_a_pass(dd, monkeypatch):
    """The failsafe. An instrument that can take the thing it observes down with it is
    a second failure layered on the first."""
    import src.scheduler.runner as runner

    def _boom(*a, **kw):
        raise RuntimeError("journal is broken")

    monkeypatch.setattr(pass_journal, "phase", _boom)
    with runner._tail_phase("hygiene", pass_id="p1"):
        pass  # must not raise

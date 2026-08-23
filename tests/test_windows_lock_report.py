"""Guards for the Windows lock diagnostic.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The module answers one field question -- "who is holding the corpus so the
restore cannot replace it" -- and the ways it can lie are all of the same shape:
reporting a question that was NOT answered as an answer. Every guard below is
about that boundary, and each has its negative-space twin, because a report that
says "held" for everything is exactly as useless as one that says "free".

These run on Linux, which is the point: the Windows-only paths are reached by
driving the pure helpers directly rather than by asserting they exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.monitoring import windows_locks as wl

FREE = {"probed": True, "exclusive_open": True}
HELD = {"probed": True, "exclusive_open": False, "winerror": 32}
UNPROBED = {"probed": False, "reason": "probe unavailable: boom"}
ABSENT = {"probed": False, "reason": "file does not exist"}


def _rep(*, applicable: bool = True, ours: list[str] | None = None) -> dict:
    return {"applicable": applicable, "this_process": {"held_by_this_process": ours or []}}


def _f(name: str, exists: bool, probe: dict) -> dict:
    return {"path": rf"C:\data\{name}", "exists": exists, "exclusive_open_probe": probe}


# --------------------------------------------------------------------------
# The reading. This is the sentence a person acts on.
# --------------------------------------------------------------------------


def test_an_unprobed_file_is_never_reported_as_an_all_clear() -> None:
    """The defect this guard exists for: `.get("exclusive_open", True)`.

    A probe that did not RUN and a probe that found the file FREE are opposite
    answers, and only one of them means a restore is safe to retry. A default of
    True collapses them and prints the reassuring one.
    """
    said = wl._reading(_rep(), [_f("x.db", True, FREE), _f("x.db-wal", True, UNPROBED)])
    assert "not an all-clear" in said
    assert "x.db-wal" in said
    assert "nothing else holds" not in said


def test_a_genuinely_free_corpus_still_gets_its_all_clear() -> None:
    """The twin: an over-cautious reader that never clears anything is useless."""
    said = wl._reading(_rep(), [_f("x.db", True, FREE), _f("x.db-wal", True, FREE)])
    assert "nothing else holds" in said
    assert "not an all-clear" not in said


def test_a_held_file_names_itself_and_says_the_restore_would_be_refused() -> None:
    said = wl._reading(_rep(), [_f("x.db", True, FREE), _f("x.db-wal", True, HELD)])
    assert "x.db-wal" in said
    assert "would be refused" in said
    # The free sibling must not be named as a holder.
    assert "Held open right now: x.db-wal." in said


def test_the_reading_separates_our_own_bug_from_something_to_close() -> None:
    """The decisive half of the whole module.

    "close the other program" is useless advice if we are the holder, and
    "this is a bug in the app" is a false accusation if we are not.
    """
    theirs = wl._reading(_rep(), [_f("x.db-wal", True, HELD)])
    ours = wl._reading(_rep(ours=[r"C:\data\x.db-wal"]), [_f("x.db-wal", True, HELD)])
    assert "another program" in theirs and "bug in the app" not in theirs
    assert "bug in the app" in ours and "another program" not in ours


def test_an_absent_wal_is_the_healthy_answer_not_a_gap() -> None:
    """A clean SQLite close checkpoints and deletes the -wal.

    Treating its absence as an unmeasured file would report every healthy
    machine as un-diagnosable.
    """
    said = wl._reading(_rep(), [_f("x.db", True, FREE), _f("x.db-wal", False, ABSENT)])
    assert "nothing else holds" in said
    assert "not an all-clear" not in said


def test_no_corpus_at_all_is_its_own_answer() -> None:
    said = wl._reading(_rep(), [_f("x.db", False, ABSENT), _f("x.db-wal", False, ABSENT)])
    assert "nothing here to hold open" in said


def test_off_windows_the_reading_says_the_question_does_not_apply() -> None:
    """POSIX unlinks an open file, so a lock report there is not a clean bill of
    health -- it is a different operating system."""
    said = wl._reading(_rep(applicable=False), [_f("x.db-wal", True, HELD)])
    assert "not Windows" in said
    # It must not print the held-file sentence on a platform where it is meaningless.
    assert "would be refused" not in said


# --------------------------------------------------------------------------
# Exclusion containment. A fabricated "you already excluded this" is the
# direction that costs: it tells an operator a remedy is applied when it is not.
# --------------------------------------------------------------------------


def test_an_exclusion_on_a_sibling_folder_does_not_cover_us() -> None:
    trap = r"C:\Users\me\Open-Omniscience-old"
    parent = r"C:\Users\me\Open-Omniscience"
    # Prove the trap is real before proving the guard closes it.
    assert trap.startswith(parent)
    assert wl._path_is_within(trap, parent) is False


@pytest.mark.parametrize(
    ("child", "parent", "want"),
    [
        (r"C:\Users\me\Open-Omniscience\data", r"C:\Users\me\Open-Omniscience", True),
        (r"C:\Users\me\Open-Omniscience", r"C:\Users\me\Open-Omniscience", True),
        (r"C:\Users\me\Open-Omniscience\data", r"C:\Users\me\Open-Omniscience\\", True),
        (r"C:\Users\me\Open-Omniscience\data", r"c:\users\me\open-omniscience", True),
        (r"C:/Users/me/Open-Omniscience/data", r"C:\Users\me\Open-Omniscience", True),
        (r"C:\Users\me\Open-Omniscience", r"C:\Other", False),
        (r"C:\Users\me\Open-Omniscience", "", False),
    ],
)
def test_exclusion_containment_matches_by_component(child: str, parent: str, want: bool) -> None:
    assert wl._path_is_within(child, parent) is want


# --------------------------------------------------------------------------
# The probe's own honesty off Windows, and the handle-value trap.
# --------------------------------------------------------------------------


def test_off_windows_the_probe_declines_rather_than_guessing(tmp_path) -> None:
    f = tmp_path / "open_omniscience.db"
    f.write_bytes(b"x")
    out = wl._exclusive_open_probe(f)
    if sys.platform.startswith("win"):  # pragma: no cover - not this sandbox
        pytest.skip("this guard is about the non-Windows degrade path")
    assert out["probed"] is False
    assert "exclusive_open" not in out, "a declined probe must not publish a verdict"
    assert "not Windows" in out["reason"]


def test_a_missing_file_is_declined_with_its_own_reason(tmp_path) -> None:
    out = wl._exclusive_open_probe(tmp_path / "nope.db-wal")
    assert out["probed"] is False
    assert "exclusive_open" not in out


def test_invalid_handle_value_is_the_unsigned_form_never_minus_one() -> None:
    """CreateFileW returns a HANDLE, and ctypes hands back the UNSIGNED value.

    Comparing it against a literal -1 is False on every FAILED call, so a
    refused open would read as a success -- the module's headline finding
    inverted on exactly the case it exists to detect.
    """
    import ctypes

    assert wl._INVALID_HANDLE == ctypes.c_void_p(-1).value
    assert wl._INVALID_HANDLE != -1
    assert wl._INVALID_HANDLE > 0


# --------------------------------------------------------------------------
# The process sweep: a bound that is not stated is a silent truncation.
# --------------------------------------------------------------------------


def test_the_holder_sweep_reports_what_it_did_not_reach(monkeypatch) -> None:
    """An empty holder list means 'not visible' when anything was skipped."""
    import psutil

    class _Slow:
        info = {"pid": 1, "name": "slow.exe"}

        def open_files(self):
            return []

    monkeypatch.setattr(wl, "_HOLDER_SWEEP_BUDGET_S", -1.0)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [_Slow(), _Slow(), _Slow()])
    out = wl._other_holders([])
    assert out["available"] is True
    assert out["processes_not_reached_within_budget"] == 3
    assert out["complete"] is False
    assert out["holders"] == []
    assert "never" in out["caveat"]


def test_a_complete_sweep_that_found_nothing_says_so(monkeypatch) -> None:
    """The twin: if every process WAS inspected, the empty list is a real finding."""
    import psutil

    class _Ok:
        info = {"pid": 1, "name": "ok.exe"}

        def open_files(self):
            return []

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [_Ok()])
    out = wl._other_holders([])
    assert out["complete"] is True
    assert out["processes_not_reached_within_budget"] == 0


def test_a_refused_process_is_counted_not_swallowed(monkeypatch) -> None:
    import psutil

    class _Denied:
        info = {"pid": 2, "name": "system"}

        def open_files(self):
            raise psutil.AccessDenied(2)

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [_Denied()])
    out = wl._other_holders([])
    assert out["processes_that_refused_inspection"] == 1
    assert out["complete"] is False, "a refused process leaves the sweep incomplete"


# --------------------------------------------------------------------------
# The whole report.
# --------------------------------------------------------------------------


def test_the_report_runs_and_never_claims_windows_facts_off_windows() -> None:
    out = wl.windows_lock_report()
    assert out["applicable"] is sys.platform.startswith("win")
    assert isinstance(out["elapsed_s"], float)
    for key in ("platform", "data_dir", "files", "this_process", "other_processes", "method", "caveat", "reading"):
        assert key in out, key
    if not out["applicable"]:
        assert out["antivirus"]["probed"] is False
        for f in out["files"]:
            assert f["exclusive_open_probe"]["probed"] is False


def test_the_report_publishes_the_budget_the_swap_actually_waits() -> None:
    """A diagnostic quoting a different number than the code uses is worse than
    quoting none: it sends the reader to check the wrong thing."""
    from src.backup.merge import _SWAP_HANDLE_WAIT_S

    out = wl.windows_lock_report()
    assert out["swap_wait_budget_s"] == _SWAP_HANDLE_WAIT_S
    assert "swap_wait_budget_s_unavailable" not in out


def test_the_report_modifies_nothing(tmp_path, monkeypatch) -> None:
    """Read-only is the whole licence for running this beside a broken restore."""
    ddir = tmp_path / "data"
    ddir.mkdir()
    db = ddir / "open_omniscience.db"
    db.write_bytes(b"corpus")
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in ddir.iterdir()}

    monkeypatch.setattr(wl, "_corpus_paths", lambda: [db, db.with_name(db.name + "-wal")])
    monkeypatch.setattr("src.database.session.data_dir", lambda: ddir)
    wl.windows_lock_report()

    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in ddir.iterdir()}
    assert after == before, "the diagnostic wrote, created or touched something"


# --------------------------------------------------------------------------
# Wiring. A diagnostic nothing can reach is the dead-end shape this project has
# paid for repeatedly: a capability built, tested, and never called.
# --------------------------------------------------------------------------


def test_the_endpoint_and_its_caller_agree_on_the_composed_route() -> None:
    """Assert the route the router really SERVES, not the decorator string.

    A `/windows-locks` decorator under a `/api/diagnostics` prefix composes to
    `/api/diagnostics/windows-locks`; asserting the two halves side by side is
    what let a `/api/backup/...` vs `/api/backup/v2/...` mismatch 404 in the field.
    """
    from tests.js_source_helper import app_js, function_body

    from src.api.diagnostics import router

    # FastAPI composes prefix + decorator at decoration time, so r.path IS the
    # served path -- and `_wiring` mounts this router with no second prefix.
    wiring = (Path(__file__).resolve().parents[1] / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")
    assert "app.include_router(router)" in wiring, (
        "include_router now takes arguments; re-derive the served path before trusting r.path"
    )
    served = {
        r.path
        for r in router.routes
        if "GET" in getattr(r, "methods", set()) and "windows-locks" in r.path
    }
    assert served == {"/api/diagnostics/windows-locks"}, served

    # Assert BOTH call sites by name. A bare `url in js` is satisfied by the
    # download alone, so a broken FETCH url -- the one that produces the inline
    # reading, i.e. the whole point of the button -- would slip through it.
    body = function_body(app_js(), "windowsLocksReport")
    url = served.pop()
    assert f'api("{url}")' in body, "the fetch does not call the served path"
    assert f'window.open("{url}?download=1"' in body, "the download does not call it either"


def test_the_button_is_wired_to_the_function_that_exists() -> None:
    """Both halves: markup calling a name, and that name being declared.

    Either alone passes while the click throws — `onclick` resolves against the
    global scope and nothing else.
    """
    from tests.js_source_helper import app_js, read_static

    html = read_static("index.html")
    assert 'onclick="windowsLocksReport(this)"' in html
    assert 'id="win-locks-status"' in html, "the reading has nowhere to render"
    assert "async function windowsLocksReport(" in app_js()


def test_the_reading_is_rendered_not_merely_downloaded() -> None:
    """The value of this button for an operator staring at [WinError 32] is the
    SENTENCE. A download alone would make them open a file to learn one line."""
    from tests.js_source_helper import app_js, function_body

    body = function_body(app_js(), "windowsLocksReport")
    assert "r.reading" in body, "the reading is computed and never shown"
    assert "win-locks-status" in body


def test_the_ui_binds_t_before_calling_it() -> None:
    """`t` is not a global; an unbound call throws the moment the panel opens."""
    from tests.js_source_helper import app_js, function_body

    body = function_body(app_js(), "windowsLocksReport")
    if 't("' in body:
        assert "OOI18N.t" in body, "t() is called without being bound"

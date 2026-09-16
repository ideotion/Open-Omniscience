"""Q1149 = a — the click-through runner's ENCRYPTED variant.

The seeded, walked states have always run the app's PLAINTEXT path (``OO_DB_PLAINTEXT=1``),
which is the one path no real operator uses. This slice lets them run encrypted, walks them in
through the REAL ``#view-unlock`` form, and records each state's at-rest reality from the app's
own header read rather than from the environment that booted it.

**These tests run everywhere, browser or not.** ``scripts/ui_clickthrough_run.py`` imports
``playwright.sync_api`` at module level, so the loader below injects a stub for that ONE name
when the real package is absent. Nothing here needs a browser: the behaviour under test is the
probe's endpoint choice and the hooks' refusals, both of which are pure given a fake HTTP
reader. The browser-driving code stays covered by ``tests/test_ui_walk_playwright.py``, which
is skip-guarded for real.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
import urllib.error
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _ROOT / "scripts" / "ui_clickthrough_run.py"
_SEED = _ROOT / "scripts" / "ui_clickthrough_seed.py"


def _load_runner():
    """Import the runner script as a module, stubbing only what a browserless host lacks."""
    if "playwright.sync_api" not in sys.modules:
        try:  # pragma: no cover - whichever branch this host takes, the other is the same test
            import playwright.sync_api  # noqa: F401
        except ImportError:
            pkg = types.ModuleType("playwright")
            pkg.__path__ = []  # type: ignore[attr-defined]
            sub = types.ModuleType("playwright.sync_api")
            sub.sync_playwright = lambda: (_ for _ in ()).throw(  # type: ignore[attr-defined]
                RuntimeError("stubbed: these tests never drive a browser")
            )
            sys.modules["playwright"] = pkg
            sys.modules["playwright.sync_api"] = sub
    spec = importlib.util.spec_from_file_location("_oo_clickthrough_run", _RUNNER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves its own annotations through
    # sys.modules[cls.__module__], so a module executed while unregistered raises
    # AttributeError on None the moment it defines its first dataclass.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------- #
# The probe — the endpoint choice IS the feature
# ---------------------------------------------------------------------------------------- #
def test_the_probe_falls_back_to_lock_state_when_doctor_is_503_while_locked(runner, monkeypatch):
    """MEASURED 2026-09-16: ``/api/system/doctor`` is NOT in ``ALLOWED_WHILE_LOCKED``, so it
    answers 503 ``{"locked": true}`` on exactly the state an encrypted run boots into. A
    doctor-only probe reports ``unknown`` for every encrypted state, and ``--require-encrypted``
    then refuses the very run it exists to demand."""
    calls: list[str] = []

    def fake_get_json(url: str, **kw):
        calls.append(url)
        if url.endswith("/api/system/doctor"):
            raise _http_error(503, b'{"detail":"the database is locked","locked":true}')
        return {"state": "locked", "locked": True, "plaintext_mode": False, "driver": True}

    monkeypatch.setattr(runner, "_get_json", fake_get_json)
    row = runner._probe_at_rest("C", "http://127.0.0.1:8000", "before-walk")

    assert row["detected"] == "encrypted", row
    assert row["via"] == "lock-state"
    assert row["lock_state"] == "locked"
    assert "doctor" in row["reason"] and "lock-state" in row["reason"]
    assert any(u.endswith("/api/system/lock-state") for u in calls), calls


def test_the_probe_reports_the_cipher_from_doctor_once_the_store_is_open(runner, monkeypatch):
    """After the walk unlocks it, ``doctor`` answers and names the engine's cipher. The custody
    log is read alongside the corpus: they are separate files with separate headers."""
    monkeypatch.setattr(
        runner, "_get_json",
        lambda url, **kw: {
            "driver": True,
            "corpus": {"state": "encrypted", "cipher": "4.12.0 community"},
            "custody_log": {"state": "absent"},
        },
    )
    row = runner._probe_at_rest("C", "http://127.0.0.1:8000", "after-walk")
    assert row["detected"] == "encrypted"
    assert row["via"] == "doctor"
    assert row["cipher"] == "4.12.0 community"
    assert row["custody_log"] == "absent"
    assert row["when"] == "after-walk"


def test_an_unreachable_state_is_unknown_with_its_reason_and_never_plaintext(runner, monkeypatch):
    """"We could not read it" and "we read it and it is not encrypted" are opposite facts, and
    only one of them is a finding about the app. Reporting the first as the second would make a
    dead instance look like a data-safety defect."""
    def boom(url: str, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(runner, "_get_json", boom)
    row = runner._probe_at_rest("D", "http://127.0.0.1:8003", "before-walk")
    assert row["detected"] == "unknown"
    assert row["detected"] != "plaintext"
    assert "connection refused" in row["reason"]


def test_an_unknown_lock_vocabulary_is_unknown_never_a_guessed_verdict(runner, monkeypatch):
    """If ``app_lock_state()``'s four words ever change, the probe says the vocabulary moved.
    Inferring "plaintext" from a word we do not know would be a fabricated finding."""
    def fake_get_json(url: str, **kw):
        if url.endswith("/api/system/doctor"):
            raise _http_error(503)
        return {"state": "quantum-superposed", "driver": True}

    monkeypatch.setattr(runner, "_get_json", fake_get_json)
    row = runner._probe_at_rest("B", "http://127.0.0.1:8002", "before-walk")
    assert row["detected"] == "unknown"
    assert "quantum-superposed" in row["reason"]


def test_the_lock_state_map_covers_every_word_app_lock_state_can_return(runner):
    """The map is only a header read in different vocabulary if it covers the whole vocabulary.
    Read from ``src/api/unlock.py``'s own docstring rather than from memory."""
    doc = (_ROOT / "src" / "api" / "unlock.py").read_text(encoding="utf-8")
    line = re.search(r'def app_lock_state\(\) -> str:\n    """([^\n]*)', doc)
    assert line, "app_lock_state's docstring moved; the map below can no longer be checked"
    # The last alternative trails into a parenthetical that wraps ("fresh (non-SQLite ->"),
    # so take each alternative's FIRST token rather than the whole slice.
    words = {w.strip().split()[0] for w in line.group(1).split("|") if w.strip()}
    assert words <= set(runner._LOCK_STATE_TO_AT_REST), (
        f"app_lock_state can return {words - set(runner._LOCK_STATE_TO_AT_REST)}, which the "
        "at-rest map does not cover — those states would read as 'unknown'"
    )


# ---------------------------------------------------------------------------------------- #
# configured vs detected, and the passphrase
# ---------------------------------------------------------------------------------------- #
def test_configured_and_detected_are_recorded_as_separate_facts(runner, monkeypatch):
    """The recorded rule for any configuration feature: report what was ASKED FOR and what was
    MEASURED separately, because an operator whose setting silently failed has no other way to
    tell. A run that collapses them can only ever agree with itself."""
    monkeypatch.setattr(runner, "ENCRYPTED_PASS", "hunter2-but-longer")
    monkeypatch.setattr(
        runner, "_get_json",
        lambda url, **kw: {"driver": True, "corpus": {"state": "plaintext"}},
    )
    report = runner.Report()
    row = runner._record_at_rest(report, "C", "http://127.0.0.1:8000", "before-walk")
    assert row["configured"] == "encrypted"
    assert row["detected"] == "plaintext"
    assert report.at_rest == [row]


def test_the_passphrase_never_reaches_the_report(runner, monkeypatch):
    """The report is committed as an audit artifact. The runner records WHETHER an unlock
    happened, never the secret that performed it."""
    secret = "a-very-distinctive-passphrase-9917"
    monkeypatch.setattr(runner, "ENCRYPTED_PASS", secret)
    monkeypatch.setattr(
        runner, "_get_json",
        lambda url, **kw: {"driver": True, "corpus": {"state": "encrypted"}},
    )
    report = runner.Report()
    runner._record_at_rest(report, "C", "http://127.0.0.1:8000", "before-walk")

    class _Page:
        def goto(self, *a, **k): ...
        def wait_for_timeout(self, *a, **k): ...
        def is_visible(self, sel): return sel == "#view-unlock"
        def fill(self, *a, **k): ...
        def click(self, *a, **k): ...
        def wait_for_function(self, *a, **k): ...

    runner._unlock_if_locked(_Page(), report, "state_c", "http://127.0.0.1:8000")
    import json
    from dataclasses import asdict

    assert secret not in json.dumps(asdict(report)), "the passphrase leaked into the report"


# ---------------------------------------------------------------------------------------- #
# the hooks' refusals
# ---------------------------------------------------------------------------------------- #
def test_without_the_passphrase_the_unlock_hook_does_not_touch_the_page(runner, monkeypatch):
    """The plaintext run must keep its exact previous behaviour, down to the page never being
    navigated by this hook — otherwise every historical walk becomes uncomparable."""
    monkeypatch.setattr(runner, "ENCRYPTED_PASS", "")
    touched: list[str] = []

    class _Page:
        def __getattr__(self, name):
            def _rec(*a, **k):
                touched.append(name)
            return _rec

    report = runner.Report()
    runner._unlock_if_locked(_Page(), report, "state_b", "http://127.0.0.1:8002")
    assert touched == [], f"the hook touched the page in a plaintext run: {touched}"
    assert report.coverage == []


def test_an_encrypted_run_that_finds_no_lock_screen_says_so(runner, monkeypatch):
    """Not an error and not silence: either the state is not encrypted or it was pre-unlocked,
    and both change what every later row for that state means."""
    monkeypatch.setattr(runner, "ENCRYPTED_PASS", "something")

    class _Page:
        def goto(self, *a, **k): ...
        def wait_for_timeout(self, *a, **k): ...
        def is_visible(self, sel): return False

    report = runner.Report()
    runner._unlock_if_locked(_Page(), report, "state_c", "http://127.0.0.1:8000")
    assert len(report.coverage) == 1
    row = report.coverage[0]
    assert row.result == "partial"
    assert "not encrypted or was already unlocked" in row.note


def test_a_failed_unlock_is_a_p1_finding_not_a_silent_continue(runner, monkeypatch):
    monkeypatch.setattr(runner, "ENCRYPTED_PASS", "wrong")

    class _Page:
        def goto(self, *a, **k): ...
        def wait_for_timeout(self, *a, **k): ...
        def is_visible(self, sel): return sel == "#view-unlock"
        def fill(self, *a, **k): ...
        def click(self, *a, **k): ...
        def wait_for_function(self, *a, **k):
            raise TimeoutError("never reached the app")

    report = runner.Report()
    runner._unlock_if_locked(_Page(), report, "state_c", "http://127.0.0.1:8000")
    assert [f.severity for f in report.findings] == ["P1"]
    assert report.coverage[0].result == "blocked"


# ---------------------------------------------------------------------------------------- #
# a drill that raises must not take the run's record with it
# ---------------------------------------------------------------------------------------- #
def test_a_failing_drill_becomes_a_finding_instead_of_ending_the_run(runner):
    """MEASURED 2026-09-16: `drill_bulletin` hit a 30s click timeout against a real markup
    defect on `main`, the exception left `main()`, and report.json / findings.csv /
    coverage.csv were never written — an entire walk, and the at-rest attestations an
    encrypted run exists to produce, lost to one broken surface. The drill that fails is
    exactly the one whose failure the report should carry."""
    report = runner.Report()

    def boom(*_a):
        raise TimeoutError("Page.click: Timeout 30000ms exceeded")

    assert runner._drill(report, "bulletin", boom, object()) is None
    assert [f.severity for f in report.findings] == ["P1"]
    assert "Timeout 30000ms" in report.findings[0].detail
    assert report.coverage[0].result == "blocked"


def test_a_drill_that_succeeds_returns_its_value_unchanged(runner):
    """`drill_reader` returns the article id the a11y pass reuses; a wrapper that swallowed
    it would silently un-drill the next step."""
    report = runner.Report()
    assert runner._drill(report, "reader", lambda a, b: 4242, 1, 2) == 4242
    assert report.findings == [] and report.coverage == []


def test_every_state_c_drill_runs_through_the_guard():
    """One unguarded drill is all it takes to lose the run again."""
    src = _runner_source_without_comments()
    for name in ("reader", "worldmap_lens", "task_manager_panels", "settings_ai_pill",
                 "bulletin", "agenda_provenance", "a11y", "honesty"):
        assert f'_drill(report, "{name}", ' in src, f"the {name} drill is not guarded"


# ---------------------------------------------------------------------------------------- #
# source guards — the wiring, which no unit test can reach
# ---------------------------------------------------------------------------------------- #
def _runner_source_without_comments() -> str:
    """Comment-stripped source: a rule's explanatory comment necessarily quotes the rule's own
    vocabulary, in both directions (the recorded source-guard lesson)."""
    out = []
    for line in _RUNNER.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split("  # ")[0])
    return "\n".join(out)


def test_every_walked_state_walks_in_through_the_unlock_hook():
    """State A runs the create flow and needs no hook. B, C and D are the seeded, walked states
    the ruling is about, and a hook wired into two of three is how one state silently keeps
    reporting a plaintext walk."""
    src = _runner_source_without_comments()
    for label, url in (("state_b", "STATE_B_URL"), ("state_c", "STATE_C_URL"),
                       ("state_d", "STATE_D_URL")):
        assert f'_unlock_if_locked(page, report, "{label}", {url})' in src, (
            f"{label} does not walk in through the encrypted-unlock hook"
        )


def test_at_rest_is_measured_before_and_after_the_walk():
    """One after-walk row cannot distinguish a store that was ALREADY encrypted from one this
    run encrypted itself; one before-walk row cannot report the cipher, because `doctor` is
    unreachable while the store is locked."""
    src = _runner_source_without_comments()
    assert '_record_at_rest(report, label, url, "before-walk")' in src
    assert '_record_at_rest(report, label, url, "after-walk")' in src


def test_require_encrypted_refuses_on_the_walked_states_only():
    """State A is EXPECTED to be encrypted-and-locked — it runs the create flow — so counting it
    would let an otherwise-plaintext walk satisfy the flag on a state that proves nothing about
    the seeded path."""
    src = _runner_source_without_comments()
    assert "--require-encrypted" in src
    assert 'r["state"] in ("B", "C", "D")' in src
    assert "raise SystemExit(2)" in src


def test_the_encrypted_passphrase_arrives_by_env_like_the_import_one():
    src = _runner_source_without_comments()
    assert 'ENCRYPTED_PASS = os.environ.get("OO_UIWALK_ENCRYPTED_PASS", "")' in src


def test_the_seed_script_documents_the_encrypted_variant():
    """The runner cannot seed anything; an operator who reads only the seeder must still find
    the encrypted path, or the variant exists only in a test."""
    doc = _SEED.read_text(encoding="utf-8")
    assert "OO_DB_PASSPHRASE" in doc
    assert "--require-encrypted" in doc
    assert "OO_UIWALK_ENCRYPTED_PASS" in doc

"""S1.3 — below the floor, REDUCE *and* DECLINE (2026-09-02 crash analysis, ruling 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import machine_floor as MF
from tests.js_source_helper import read_static

_SRC = Path(__file__).resolve().parents[1] / "src"


# --------------------------------------------------------------------------- #
# The verdict.
# --------------------------------------------------------------------------- #
def test_a_small_machine_is_below_the_floor_and_the_reason_carries_the_numbers():
    v = MF.machine_floor(override=False, total_mb=3379.0, available_mb=512.0)
    assert v["below"] is True
    assert v["declines"] is True
    # The three numbers a reader needs: what it has, what is free, what it is judged against.
    assert "3379" in v["reason"]
    assert "512" in v["reason"]
    assert "4096" in v["reason"] or "1024" in v["reason"]


def test_a_machine_below_on_available_alone_is_below():
    """Either half of the floor is enough: a large box already down to 300 MB is
    in exactly the trouble the floor exists to notice."""
    v = MF.machine_floor(override=False, total_mb=16384.0, available_mb=300.0)
    assert v["below"] is True
    assert "1024" in v["reason"]


def test_a_healthy_machine_is_not_below_the_floor():
    """The mandatory twin: a floor that refused everything would be a fabricated
    failure, and would read as 'the fix works' in every small-machine test."""
    v = MF.machine_floor(override=False, total_mb=8192.0, available_mb=4096.0)
    assert v["below"] is False
    assert v["declines"] is False
    assert "8192" in v["reason"] and "4096" in v["reason"]


def test_the_override_keeps_the_measurement_and_only_changes_the_effect():
    """``below`` is a fact about the MACHINE and the override must not erase it —
    a report has to be able to say 'small AND the operator chose to run anyway'."""
    v = MF.machine_floor(override=True, total_mb=3379.0, available_mb=512.0)
    assert v["below"] is True, "the override must not rewrite the measurement"
    assert v["overridden"] is True
    assert v["declines"] is False, "the effective answer is what the override changes"


def test_the_override_is_read_from_the_documented_environment_variable(monkeypatch):
    monkeypatch.setenv(MF._OVERRIDE_ENV, "1")
    v = MF.machine_floor(total_mb=3379.0, available_mb=512.0)
    assert v["overridden"] is True and v["declines"] is False
    monkeypatch.setenv(MF._OVERRIDE_ENV, "0")
    assert MF.machine_floor(total_mb=3379.0, available_mb=512.0)["declines"] is True


def test_an_unmeasurable_machine_is_a_third_state_and_is_never_refused(monkeypatch):
    """Refusing on a measurement nobody made is the fabricated-failure mirror of
    the fabricated pass — and on a core install psutil is simply absent."""
    monkeypatch.setattr(MF, "_mem_readings", lambda: (None, None))
    v = MF.machine_floor(override=False)
    assert v["below"] is None, "unmeasurable must not collapse into False"
    assert v["declines"] is False
    assert "could not be read" in v["reason"]


def test_a_partial_reading_still_judges_on_what_it_has(monkeypatch):
    """One readable half is evidence; discarding it would decline less on exactly
    the machines that can least afford the scan."""
    monkeypatch.setattr(MF, "_mem_readings", lambda: (3379.0, None))
    v = MF.machine_floor(override=False)
    assert v["below"] is True
    assert "unreadable available" in v["reason"]


# --------------------------------------------------------------------------- #
# The need estimate.
# --------------------------------------------------------------------------- #
def test_the_need_estimate_is_linear_in_the_article_count():
    """The measured shape: a fixed cache + overhead plus a per-article term."""
    base = MF.scan_need_mb(0)
    assert base == pytest.approx(MF._SCAN_CACHE_MB + MF._SCAN_HEADROOM_MB, abs=0.2)
    a, b = MF.scan_need_mb(100_000), MF.scan_need_mb(200_000)
    assert (b - base) == pytest.approx(2 * (a - base), rel=0.01)


def test_the_need_estimate_reproduces_the_field_machines_arithmetic():
    """~305 MB at ~123k articles — the figure the crash analysis derived
    independently. If this drifts, the constant moved and the reason must say so.
    """
    assert MF.scan_need_mb(123_000) == pytest.approx(305.0, abs=2.0)


def test_the_need_method_states_every_term_it_used():
    """A published derivation must show the work it did — a reader who divides
    must land on the printed number."""
    b = MF.scan_budget(10_000, override=False, total_mb=8192.0, available_mb=4096.0)
    m = b["need_method"]
    assert "64" in m and "1200" in m and "10000" in m and "100" in m
    assert MF.scan_need_mb(10_000) == pytest.approx(
        MF._SCAN_CACHE_MB + (10_000 * MF._BYTES_PER_ARTICLE) / (1024 * 1024)
        + MF._SCAN_HEADROOM_MB,
        abs=0.2,
    )


def test_an_unmeasurable_available_makes_affordability_a_third_state(monkeypatch):
    monkeypatch.setattr(MF, "_mem_readings", lambda: (None, None))
    b = MF.scan_budget(1000, override=False)
    assert b["affordable"] is None, "'we could not tell' is not 'no'"
    assert "skipped" not in b


def test_the_decline_payload_carries_the_two_numbers_it_is_refusing_on():
    b = MF.scan_budget(123_000, override=False, total_mb=3379.0, available_mb=512.0)
    assert b["skipped"] == "memory"
    assert b["available_mb"] == 512.0
    assert b["need_mb"] > 0


def test_a_healthy_machine_gets_no_skipped_key():
    b = MF.scan_budget(123_000, override=False, total_mb=8192.0, available_mb=4096.0)
    assert "skipped" not in b, "a healthy machine must not carry a refusal"


# --------------------------------------------------------------------------- #
# The wiring.
# --------------------------------------------------------------------------- #
def test_the_qualification_pass_declines_before_it_spends_any_network(monkeypatch):
    """Gated at the ONE place the whole-corpus scan is reached, and BEFORE the
    trial fetches — spending Tor bandwidth on evidence we have already decided
    not to judge would be the worst of both."""
    import src.catalog.qualification as Q

    fetched: list[object] = []
    monkeypatch.setattr(Q, "_corpus_articles", lambda _s: 123_000)
    monkeypatch.setattr(
        Q, "scan_budget",
        lambda n, **kw: MF.scan_budget(n, override=False, total_mb=3379.0, available_mb=100.0),
    )
    monkeypatch.setattr(Q, "trial_fetch", lambda *a, **k: fetched.append(a))
    monkeypatch.setattr(Q, "select_unqualified", lambda *a, **k: pytest.fail(
        "the pass selected candidates after declining"))

    out = Q.run_qualification_pass(object(), object(), per_pass=5)
    assert out["skipped"] == "memory"
    assert out["evaluated"] == 0
    assert out["need_mb"] > 0 and "available_mb" in out
    assert out["override_env"] == MF._OVERRIDE_ENV
    assert fetched == [], "no network may be spent on a declined pass"


def test_a_healthy_machine_still_runs_the_qualification_pass(monkeypatch):
    """The twin that keeps the gate from becoming an off switch."""
    import src.catalog.qualification as Q

    monkeypatch.setattr(Q, "_corpus_articles", lambda _s: 1000)
    monkeypatch.setattr(
        Q, "scan_budget",
        lambda n, **kw: MF.scan_budget(n, override=False, total_mb=16384.0, available_mb=8192.0),
    )
    reached: list[int] = []

    def _sel(*a, **k):
        reached.append(1)
        return []

    monkeypatch.setattr(Q, "select_unqualified", _sel)
    monkeypatch.setattr(Q, "select_due_disqualified", lambda *a, **k: [])
    out = Q.run_qualification_pass(object(), None, per_pass=5)
    assert reached, "a healthy machine must reach the selection"
    assert "skipped" not in out


def test_the_fan_out_is_capped_below_the_floor():
    """Behavioural, not a source grep: drive the real policy."""
    w, v = MF.capped_workers(50, override=False, total_mb=3379.0, available_mb=512.0)
    assert w == MF.FLOOR_MAX_WORKERS
    assert v["declines"] is True


def test_the_fan_out_is_untouched_above_the_floor():
    """The twin: a cap that fired everywhere would be a silent throughput loss on
    every healthy machine, and every below-the-floor test would still pass."""
    w, v = MF.capped_workers(50, override=False, total_mb=16384.0, available_mb=8192.0)
    assert w == 50 and v["declines"] is False


def test_the_override_lifts_the_fan_out_cap_too():
    w, _ = MF.capped_workers(50, override=True, total_mb=3379.0, available_mb=512.0)
    assert w == 50, "the documented override must lift every half of the floor"


def test_a_fan_out_already_under_the_cap_is_never_raised():
    """The cap is a ceiling, never a target: an operator who chose 2 keeps 2."""
    w, _ = MF.capped_workers(2, override=False, total_mb=3379.0, available_mb=512.0)
    assert w == 2


def test_the_runner_uses_the_shared_policy_and_never_rewrites_the_setting():
    """One source assertion, scoped to the runner's own w_max block: the cap must
    come from the shared helper (so it cannot drift from the floor) and the
    operator's stored setting must never be written back."""
    from src.scheduler import runner

    body = Path(runner.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert "capped_workers" in code, "the runner must use the shared cap policy"
    assert "settings.collect_parallelism =" not in code, (
        "the operator's stored setting must never be rewritten"
    )


def test_no_code_path_imposes_an_address_space_rlimit():
    """A self-imposed RLIMIT_AS is a FALSE ceiling: DuckDB and numpy reserve
    virtual space far above RSS, so it raises MemoryError in unrelated code long
    before the process is actually large. The cgroup (S1.5) is the real one.
    """
    offenders = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # comment-stripped: the explanation of why this is absent necessarily
        # names the thing it forbids.
        code = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
        )
        if "setrlimit" in code or "RLIMIT_AS" in code:
            offenders.append(str(path.relative_to(_SRC)))
    assert not offenders, f"an address-space cap is a false ceiling: {offenders}"


# --------------------------------------------------------------------------- #
# The visible caveat (the ruling's "never a hard block, always stated" half).
# --------------------------------------------------------------------------- #
def test_the_verdict_rides_every_scheduler_response():
    """Behavioural: the caveat must reach the collection state without a second
    poll the UI might never make — the same reason ``online`` rides it."""
    from src.api.scheduler import _status_payload

    mf = _status_payload()["machine_floor"]
    assert set(mf) >= {"below", "overridden", "declines", "available_mb", "reason", "caveat"}


def test_the_caveat_strings_are_keyed_in_every_locale():
    """Both halves ship x12. The FRAME is a template (the numbers are data): a
    sentence with the numbers welded in could never be keyed at all."""
    import json

    frame = "Limited memory: {available} MB free of {total} MB."
    root = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    assert frame in read_static("app-sources.js"), (
        "the frame must be the string the renderer passes to tf()"
    )

    locales = sorted(p for p in root.glob("*.json"))
    assert len(locales) == 12, f"expected 12 locales, found {len(locales)}"
    for p in locales:
        m = json.loads(p.read_text(encoding="utf-8"))
        assert frame in m, f"{p.name} is missing the memory-floor frame"
        # the frame's holes must survive translation, or the reader sees "{total}"
        assert "{available}" in m[frame] and "{total}" in m[frame], (
            f"{p.name} dropped a placeholder from the frame"
        )


def test_the_caveat_is_hidden_only_when_the_machine_is_above_the_floor():
    """Source-scoped to the renderer: it must key on the EFFECTIVE answer, so an
    overridden machine (which is still below) stops warning about a pause that is
    no longer happening.

    Sliced through ``js_source_helper`` rather than by hand: a hand-rolled
    ``index()`` slice is exactly the over-run this repo has a ratchet against.
    """
    from tests.js_source_helper import function_body, strip_comments

    code = strip_comments(function_body(read_static("app-sources.js"), "renderMachineFloor"))
    assert "mf.declines" in code, "the caveat must key on the effective answer"
    assert "mf.below" not in code, (
        "keying on `below` would keep warning after the operator overrode it"
    )
    assert "!mf ||" in code, "an older server (no verdict) must say nothing, not warn"


# --------------------------------------------------------------------------- #
# S1.5 — the manual states the one ceiling that actually works.
# --------------------------------------------------------------------------- #
def test_the_manual_documents_the_cgroup_ceiling_and_why_a_self_cap_is_not_one():
    """docs<->app reciprocity: the ruling's second half is a documentation
    deliverable, so its absence is a failing test rather than a forgotten note."""
    man = (Path(__file__).resolve().parents[1] / "docs" / "USER_MANUAL.md").read_text(
        encoding="utf-8"
    )
    assert "systemd-run" in man and "MemoryMax" in man, "the real ceiling must be documented"
    assert "MemorySwapMax" in man, (
        "without it the app can still swap the machine into a crawl before the limit"
    )
    # the honest cost, both directions
    assert "the app is killed" in man
    assert "RLIMIT_RSS" in man and "RLIMIT_AS" in man, (
        "the manual must say WHY a self-imposed cap is not a ceiling"
    )
    assert MF._OVERRIDE_ENV in man, "the documented override must be in the manual"

"""P0.1 acceptance gate (src/testing/scale_bench.acceptance_gate) — Round 2 ZETA.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gate is the instrument that turns a benchmark report into a pass/fail
against the AUDIT CONDITIONS. The load-bearing negative cases: a PLAINTEXT
corpus must NEVER pass (its numbers omit every SQLCipher codec cost), an
unevaluated RSS bound must never silently pass as "bounded", and the OFFICIAL
mode must reject a multi-phase run (earlier phases inflate process-lifetime
peak RSS and can mask a backup spike).
"""

from src.testing.scale_bench import acceptance_gate


def _report(**over):
    base = {
        "corpus": {"encrypted": True, "path": "/x/open_omniscience.db"},
        "phases_requested": ["backup", "verify", "restore"],
        "phases": {
            "backup": {"wall_s": 12.3, "peak_rss_mb": 400.0, "volumes": 5},
            "verify": {"ok": True, "wall_s": 3.2},
            "restore": {"wall_s": 20.0, "verified": True},
        },
    }
    base.update(over)
    return base


def _check(gate: dict, name: str) -> dict:
    return next(c for c in gate["checks"] if c["name"] == name)


def test_gate_passes_a_clean_encrypted_report():
    gate = acceptance_gate(_report(), max_backup_peak_rss_mb=1024)
    assert gate["ok"] is True and gate["failures"] == []


def test_gate_fails_a_plaintext_corpus():
    gate = acceptance_gate(
        _report(corpus={"encrypted": False, "path": "/x/db"}), max_backup_peak_rss_mb=1024
    )
    assert gate["ok"] is False
    assert "corpus_encrypted" in gate["failures"]


def test_gate_fails_on_the_plaintext_caveat_even_if_encrypted_flag_lies():
    gate = acceptance_gate(_report(plaintext_caveat="PLAINTEXT corpus: ..."))
    assert gate["ok"] is False
    assert "no_plaintext_caveat" in gate["failures"]


def test_gate_enforces_a_supplied_rss_bound_but_never_invents_one():
    over = acceptance_gate(_report(), max_backup_peak_rss_mb=100)
    assert over["ok"] is False and "backup_peak_rss_bounded" in over["failures"]

    unevaluated = acceptance_gate(_report())  # no bound supplied
    check = _check(unevaluated, "backup_peak_rss_bounded")
    assert check["ok"] is None  # explicitly NOT evaluated — never a silent pass
    assert unevaluated["ok"] is True  # and never a silent fail either


def test_gate_fails_on_backup_error_or_verify_not_ok_or_restore_skipped():
    r = _report()
    r["phases"]["backup"] = {"error": "OOM"}
    assert "backup_ran" in acceptance_gate(r)["failures"]

    r = _report()
    r["phases"]["verify"] = {"ok": False, "report": {"bad_volumes": ["vol-x"]}}
    assert "verify_ok" in acceptance_gate(r)["failures"]

    r = _report()
    r["phases"]["restore"] = {"skipped": "no backup was produced to restore"}
    assert "restore_ran" in acceptance_gate(r)["failures"]

    r = _report()
    del r["phases"]["verify"]  # verify absent entirely -> not acceptable
    assert "verify_ok" in acceptance_gate(r)["failures"]


def test_gate_official_mode_requires_a_fresh_backup_only_process():
    full = _report()  # multi-phase run
    gate = acceptance_gate(full, official=True)
    assert "official_backup_process" in gate["failures"]

    official = _report(
        phases_requested=["backup"],
        phases={"backup": {"wall_s": 10.0, "peak_rss_mb": 300.0}},
    )
    gate = acceptance_gate(official, official=True, max_backup_peak_rss_mb=1024)
    assert gate["ok"] is True
    # official mode gates only the backup evidence (verify/restore ride the full run)
    assert not any(c["name"] in ("verify_ok", "restore_ran") for c in gate["checks"])


def test_gate_checks_interrupt_and_resume_when_the_report_carries_one():
    r = _report()
    r["phases"]["backup"].update(
        {"interrupted": {"after_volumes": 3, "wall_s": 5.0}, "resumed": True, "volumes_reused": 3}
    )
    assert acceptance_gate(r)["ok"] is True

    r["phases"]["backup"]["volumes_reused"] = 0  # a "resume" that reused nothing
    gate = acceptance_gate(r)
    assert "interrupt_and_resume" in gate["failures"]

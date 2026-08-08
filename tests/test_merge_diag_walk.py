"""The structural-walk probe, and the ratio that refuses to be a lookalike.

``PRAGMA quick_check`` runs TWICE per queued backup — ``prepare_staged:validate``
over the incoming staged corpus (plaintext by design) and ``verify_copy`` over the
merged working copy (which preserves the live at-rest state, so encrypted). The
first was measured in the field at 1,839–2,414 s. The second never has been,
because no import survived long enough to reach it.

This probe exists to predict the second from the first, and the interesting part is
what it refuses to say. Its first version reported encryption as a **0.81×
speed-up** — because ``connect`` gives a fresh encrypted file 16384-byte pages and a
fresh plaintext one 4096, quick_check costs per page, and the ratio was therefore
measuring geometry. The comparability check below is that bug, pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.monitoring import merge_diag


# --------------------------------------------------------------------------- #
# The refusal. Pure, so it is testable without building real databases.
# --------------------------------------------------------------------------- #


def test_arms_at_different_page_sizes_yield_no_ratio() -> None:
    """The shipped bug, as a guard. 4096 vs 16384 is not a slower codec, it is a
    different operation — and the number it produced (0.81) read as a finding."""
    got = merge_diag.codec_multiplier(
        {"mb_per_s": 83.5, "page_size": 4096},
        {"mb_per_s": 102.5, "page_size": 16384},
    )
    assert got["codec_multiplier"] is None
    assert "not comparable" in got["codec_multiplier_unavailable"]
    assert "4096" in got["codec_multiplier_unavailable"]


def test_matched_arms_yield_the_ratio_and_state_their_method() -> None:
    got = merge_diag.codec_multiplier(
        {"mb_per_s": 240.0, "page_size": 16384},
        {"mb_per_s": 100.0, "page_size": 16384},
    )
    assert got["codec_multiplier"] == 2.4
    assert got["codec_multiplier_method"]


def test_a_missing_rate_is_a_stated_gap_not_a_ratio() -> None:
    """The negative-space twin of the one above: an arm whose walk was too fast to
    time reports no rate, and a ratio built on it would be invented."""
    got = merge_diag.codec_multiplier(
        {"mb_per_s": None, "page_size": 16384},
        {"mb_per_s": 100.0, "page_size": 16384},
    )
    assert got["codec_multiplier"] is None
    assert "invented" in got["codec_multiplier_unavailable"]


def test_a_missing_page_size_never_passes_the_comparability_check() -> None:
    """``None == None`` is True, and that would let two arms of unknown geometry
    through the very check that exists to stop exactly this."""
    got = merge_diag.codec_multiplier(
        {"mb_per_s": 240.0}, {"mb_per_s": 100.0}
    )
    assert got["codec_multiplier"] is None


# --------------------------------------------------------------------------- #
# The real probe
# --------------------------------------------------------------------------- #


def test_the_real_probe_builds_both_arms_at_one_geometry(tmp_path, monkeypatch) -> None:
    """Drives the production function. A test that asserted on hand-built dicts
    would prove the arithmetic and miss the thing that was actually wrong."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # Big enough that the walk clears the probe's own timer-resolution floor. At
    # 4 MiB it finished in 0.017 s, the probe correctly refused to divide a rate
    # out of that, and the test failed on the refusal rather than on the code.
    monkeypatch.setattr(merge_diag, "_WALK_BYTES", 24 * 1024 * 1024)
    out = merge_diag.walk_probe()

    plain = out["plaintext"]
    assert plain["quick_check"] == "ok"
    assert plain["page_size"] == merge_diag._WALK_PAGE_SIZE, (
        "the plaintext arm fell back to SQLite's 4096 default — PRAGMA page_size "
        "needs a VACUUM to take effect, and must precede journal_mode=WAL"
    )
    assert plain["walks"] == merge_diag._WALK_REPEATS

    enc = out["encrypted"]
    if "skipped" in enc:
        pytest.skip(f"no encrypted arm on this install: {enc['skipped']}")
    assert enc["page_size"] == plain["page_size"]
    assert out["codec_multiplier"] is not None, out


def test_the_probe_leaves_nothing_behind(tmp_path, monkeypatch) -> None:
    """It builds real multi-MB files on the operator's disk. A probe that leaks
    them is a probe that fills a drive one bundle at a time."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(merge_diag, "_WALK_BYTES", 2 * 1024 * 1024)
    merge_diag.walk_probe()
    assert not list(tmp_path.glob(merge_diag._PROBE_PREFIX + "*"))

"""The merge probe's memory arm measures a window, not the process's whole history.

`cost_probe` reported per-row cost as a delta of ``ru_maxrss`` — a high-water mark that
NEVER FALLS. So the delta only shows anything when the probe pushes the process past its
all-time peak. Inside a long pytest session (or any long-lived app process that has
already done something bigger) a perfectly real 40 MB allocation registered as **0.0
KB/row**, and that zero was published as a measurement.

That is the failure that reddened the Core-only lane on `main`: the test passes alone and
fails after ~6,900 tests. It reads like a timing flake on a fast runner and is nothing of
the kind — it is order-dependent, and reproducible on demand by raising the mark first.

Two properties are pinned here: a window is measured where the platform allows it, and
where it does not, the gap is STATED rather than reported as zero.
"""

from __future__ import annotations

import sys

import pytest

from src.monitoring import merge_diag


def test_current_rss_moves_with_a_real_allocation_and_falls_back():
    """The whole point of the new reader: unlike the high-water mark, it goes down."""
    before = merge_diag._rss_current_mb()
    if before is None:
        pytest.skip("/proc/self/statm is Linux-only; the peak path is tested below")
    ballast = bytearray(120 * 1024 * 1024)
    during = merge_diag._rss_current_mb()
    assert during is not None and during > before + 50, (during, before)
    del ballast
    after = merge_diag._rss_current_mb()
    assert after is not None and after < during - 50, (
        "current RSS must FALL when memory is released — a mark that only rises is "
        "exactly the instrument this replaces"
    )


def test_a_raised_high_water_mark_never_yields_a_fabricated_zero():
    """The CI failure, reproduced — and the property that actually holds.

    Raising ``ru_maxrss`` far above anything the probe allocates used to force
    ``kb_per_row`` to 0.0. Switching to current RSS fixes the *usual* case, but not
    this one: freeing the ballast leaves the pages in glibc's arena, so the probe's
    next 40 MB is served without RSS growing either. CI found exactly that.

    So the guarantee is not "always a number" — no RSS-based reader can promise that
    — it is **never a fabricated zero**. Either a real measurement, or a stated gap.
    """
    if merge_diag._rss_current_mb() is None:
        pytest.skip("current-RSS reading unavailable on this platform")
    ballast = bytearray(400 * 1024 * 1024)
    del ballast  # the mark stays raised; the arena stays warm
    arm = merge_diag.cost_probe(avg_row_bytes=512)["arms"][0]

    assert arm.get("rss_method") == "current"
    assert arm["kb_per_row"] != 0.0, "0.0 KB/row is a claim, and nothing was measured"
    if arm["kb_per_row"] is None:
        assert arm["kb_per_row_unavailable"], "an absent number owes its reason"
        assert "did not grow" in arm["kb_per_row_unavailable"]
    else:
        assert arm["kb_per_row"] > 0, arm
    assert arm["seconds"] > 0, "the timing half is a real measurement either way"


def test_an_unobservable_delta_is_a_stated_gap_not_a_zero(monkeypatch):
    """Where only the high-water mark exists and it did not move, say so.

    0.0 KB/row would be a fabricated measurement in precisely the case where nothing
    was measured — the mistake `_rss_mb`'s own docstring warns about one level down.
    """
    monkeypatch.setattr(merge_diag, "_rss_current_mb", lambda: None)
    monkeypatch.setattr(merge_diag, "_rss_mb", lambda: 500.0)  # never moves
    arm = merge_diag.cost_probe(avg_row_bytes=512)["arms"][0]

    assert arm["rss_method"] == "peak"
    assert arm["kb_per_row"] is None, "a zero here is a claim we did not measure"
    assert "high-water mark" in arm["kb_per_row_unavailable"]
    assert arm["seconds"] > 0, "the TIMING half is still a real measurement"


def test_the_peak_path_still_reports_a_real_delta_when_the_mark_does_move(monkeypatch):
    """The twin. The gap must be stated only when the delta is genuinely unobservable —
    an over-eager version would suppress every peak-path measurement, including good
    ones, and look conservative doing it."""
    monkeypatch.setattr(merge_diag, "_rss_current_mb", lambda: None)
    readings = iter([100.0, 140.0])
    monkeypatch.setattr(merge_diag, "_rss_mb", lambda: next(readings, 140.0))
    arm = merge_diag.cost_probe(avg_row_bytes=512)["arms"][0]

    assert arm["rss_method"] == "peak"
    assert arm["kb_per_row"] is not None and arm["kb_per_row"] > 0, arm
    assert "kb_per_row_unavailable" not in arm


# --------------------------------------------------------------------------- #
# The unit slip in _rss_mb
# --------------------------------------------------------------------------- #


def test_ru_maxrss_is_converted_per_platform():
    """Both arms of the old ternary were the same expression, so the unit branch it
    was written for never happened and macOS read 1024x high.

    Linux reports ``ru_maxrss`` in kilobytes, macOS in bytes.
    """
    import resource

    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    got = merge_diag._rss_mb()
    expected = (raw / 1024.0 / 1024.0) if sys.platform == "darwin" else (raw / 1024.0)
    assert got == pytest.approx(expected)

    # And the result must be a plausible process size on any platform. The old code
    # returned raw/1024 unconditionally, which on macOS is a four-digit "MB" figure for
    # an ordinary process — the tell that the branch was dead.
    assert got is not None and 1.0 < got < 100_000.0, got


def test_the_unit_branch_is_on_the_platform_not_the_magnitude():
    """The dead ternary keyed off `kb > 1024*1024`, which a Linux process legitimately
    above 1 GB satisfies — so even a 'fixed' magnitude test would have mis-scaled the
    exact machines this diagnostic is for (the field import that motivated it ran at
    ~6 GB RSS)."""
    import inspect

    src = inspect.getsource(merge_diag._rss_mb)
    assert 'sys.platform == "darwin"' in src
    assert "1024 * 1024" not in src, "magnitude must not decide the unit"

"""
The per-PROCESS bandwidth budget, composed with the collection-speed governor.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED 2026-09-15 (answer sheet Q1012 = a): "a per-PROCESS budget composed with the
collection-speed governor (``#rate-toggle``), never a second rate authority beside
it; per-job caps stay omitted."

WHAT WAS ACTUALLY WRONG, which is the reason this module is composition and not a
new control. The governor (``src.scheduler.bandwidth``) has always owned the one
rate target an operator can set, and it has always been fed ONLY the collector's
own byte counter (``activity_monitor.bytes_total``, stamped by ``EthicalFetcher``).
The wiki-dump and OSM download managers pull their bytes through an entirely
separate loop with its own samplers, so a multi-gigabyte dump running at 10 MB/s
was INVISIBLE to the one authority that is supposed to hold the process to
"target 500 KiB/s". The knob was therefore not describing the process; it was
describing a part of it, without saying so.

So there is no new target here, and there is deliberately nowhere to put one:

  * :func:`budget_kbps` DERIVES the ceiling from the governor's own ``mode`` and
    ``target_kbps``. It reads those two fields off the governor object rather than
    taking them as arguments, because an argument is a place a second, drifting
    value can enter -- the recorded "two modules publishing one quantity" defect.
    ``maximum`` mode has no ceiling and returns ``None``; a ``0`` would read as
    "no bytes allowed", which is the opposite fact.
  * :func:`compose` widens the governor's INPUT from the collector's share to the
    whole process, so the existing controller regulates the whole budget. The
    controller, the target, the permits and the back-off are all unchanged.

WHERE THE BYTES COME FROM, and the gauge this must never be. Every figure is
OWNER-MEASURED: the collector's cumulative counter, stamped by the fetch that
received the bytes, and the download samplers, stamped by the worker that received
them (``src.ingest.download_rate``). A machine-wide NIC counter would be the
recorded P4 defect wearing a different unit -- a control loop reading a
whole-machine gauge throttles itself for someone else's traffic, and in this
direction it would be worse than the CPU case, because another tenant's download
would look exactly like ours and the collector would be cut for it.

WHAT IT REFUSES TO SAY:

  * **An unmeasurable component is ABSENT with a reason, never 0.** A download too
    young to measure, one that has just restarted, and one that is stalled are
    three different facts, and the samplers already tell them apart; this module
    carries their refusals through rather than summing them into a zero.
  * **A partial total is published AS a lower bound.** When some download cannot be
    measured, ``partial`` is True and ``unmeasured`` names what was left out. Acting
    on a lower bound is the SAFE direction for a ceiling -- if what we could measure
    already exceeds the budget, the true total certainly does -- but the reader is
    told, because a lower bound presented as a total is a fabricated measurement.
  * **The share the governor can actually move is named separately.** Its only lever
    is the collector's concurrent-fetch permits, so when a file download is what is
    spending the budget, cutting permits cannot recover it. That is the honest
    outcome of a PER-PROCESS ceiling rather than a defect -- the operator asked the
    whole process to stay under a rate -- but an operator watching collection slow
    to one worker is owed the sentence that says which half is spending their
    budget, or they will read it as the collector being broken.

DELIBERATELY NOT HERE: a per-JOB cap. Q1012 keeps invariant #20's omission, and
the reason is unchanged -- a second rate authority beside the governor is how two
surfaces come to disagree about one quantity. Nothing in this module throttles
anything; it measures and composes, and the governor remains the only thing that
acts.
"""

from __future__ import annotations

from typing import Any

#: What a composed figure means, published beside it.
METHOD = (
    "the app's own download bytes -- the collector's fetch counter plus every "
    "file-download sampler that is currently measurable -- against the budget the "
    "collection-speed governor is set to"
)

#: Bytes/s -> kilobits/s (decimal), the unit the operator's target is written in.
_BITS_PER_BYTE = 8
_BITS_PER_KBIT = 1000.0


def bytes_per_s_to_kbps(bytes_per_s: float) -> float:
    """Owner-measured bytes/s in the governor's own unit (kilobits/s, decimal)."""
    return round(float(bytes_per_s) * _BITS_PER_BYTE / _BITS_PER_KBIT, 1)


def budget_kbps(governor: Any) -> int | None:
    """The per-process ceiling, read from the governor's OWN knobs.

    ``None`` means there is no ceiling: ``maximum`` mode is the operator asking for
    as much as the machine and the hosts will give, and the governor backs off on
    contention rather than on a rate. Returning ``0`` instead would read as "no
    bytes allowed", which is a different instruction entirely.

    Reads ``governor.mode`` / ``governor.target_kbps`` rather than accepting them as
    parameters: a parameter is a place a second copy of the target can enter, and
    the whole point of Q1012 = a is that there is exactly one.
    """
    mode = getattr(governor, "mode", None)
    if mode != "target":
        return None
    target = getattr(governor, "target_kbps", None)
    if target is None:
        return None
    try:
        value = int(target)
    except (TypeError, ValueError):
        # A governor whose target is unreadable has no ceiling to compose with, and
        # NARROWING the None out above rather than casting it away is the difference
        # between the type checker agreeing and the type checker being silenced.
        return None
    return value if value > 0 else None


def compose(
    governor: Any,
    collector_kbps: float,
    *,
    download_rate: dict | None = None,
) -> dict:
    """Compose the process-wide measured rate with the governor's own budget.

    ``collector_kbps`` is the collector's share, already measured by the caller from
    the app's cumulative fetch counter. ``download_rate`` is
    :func:`src.ingest.download_rate.process_download_rate`'s answer; it is read
    lazily when not supplied so that a caller cannot accidentally hand in a stale
    reading taken at some other moment.

    Returns the record the governor is fed from and the task manager renders. The
    caller passes ``process_kbps`` to ``governor.observe`` -- that call is the whole
    composition, and it is the only behavioural change: the same controller, the
    same target, now reading the whole process instead of one part of it.
    """
    if download_rate is None:
        from src.ingest.download_rate import process_download_rate

        download_rate = process_download_rate()

    try:
        collector = max(0.0, round(float(collector_kbps), 1))
    except (TypeError, ValueError):
        collector = 0.0

    downloads_measured = bool(download_rate.get("measured"))
    downloads = (
        bytes_per_s_to_kbps(download_rate.get("bytes_per_s") or 0.0)
        if downloads_measured
        else None
    )
    unmeasured = list(download_rate.get("unmeasured") or [])

    process = round(collector + (downloads or 0.0), 1)
    budget = budget_kbps(governor)
    # ``partial`` is the honesty flag, not an error: the sum is real, it is simply a
    # LOWER bound on the process while any download is unmeasurable. The distinction
    # matters in exactly one direction -- under budget with unmeasured downloads is
    # not evidence of being under budget, while over budget is conclusive either way.
    partial = bool(unmeasured)

    out: dict[str, Any] = {
        "mode": getattr(governor, "mode", None),
        "budget_kbps": budget,
        "process_kbps": process,
        "collector_kbps": collector,
        # ABSENT, never 0: no download running and a download we cannot yet measure
        # are both "we are not adding a number here", and a 0 would claim the second
        # one is contributing nothing when we do not know that.
        "downloads_kbps": downloads,
        "downloads_measured": downloads_measured,
        "downloads_idle": bool(download_rate.get("idle")),
        "partial": partial,
        "unmeasured": unmeasured,
        "method": METHOD,
    }
    if not downloads_measured:
        out["downloads_reason"] = download_rate.get("reason")

    if budget is None:
        out["over_budget"] = None
        out["budget_reason"] = (
            "no ceiling: the collection speed is set to maximum, so the governor "
            "backs off on contention rather than on a rate"
        )
        return out

    out["over_budget"] = process > budget
    # The governor's only lever is the collector's concurrent-fetch permits, so name
    # what it can and cannot reach. A reader watching collection fall to one worker
    # while a dump saturates the line needs this sentence to tell a working budget
    # from a broken collector.
    out["governed_kbps"] = collector
    if out["over_budget"] and downloads_measured and downloads and downloads > budget:
        out["budget_reason"] = (
            f"a file download alone is using {downloads:g} kbit/s of the "
            f"{budget:g} kbit/s budget; reducing collection cannot recover it"
        )
    elif out["over_budget"]:
        out["budget_reason"] = (
            f"the process is measuring {process:g} kbit/s against a "
            f"{budget:g} kbit/s budget"
            + (" (a lower bound: some downloads are unmeasurable)" if partial else "")
        )
    else:
        # UNDER budget is exactly where the lower bound has to be said out loud.
        # Over budget, a lower bound is already conclusive; under budget it is not
        # evidence of being under budget at all, and a bare "110 of 500" would read
        # as though it were.
        out["budget_reason"] = (
            f"{process:g} of {budget:g} kbit/s"
            + (
                " measured; a lower bound, because some downloads are unmeasurable"
                if partial
                else ""
            )
        )
    return out

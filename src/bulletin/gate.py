"""
The Bulletin's hardware gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED (design record §3, AMENDED 2026-09-07 by the maintainer's answer to open
question 4): the gate covers the **narration layer**, not the whole feature. The
deterministic document is pure SQL and runs anywhere, so it is offered anywhere;
Layer B is thousands of model calls and stays gated on hardware that can
practically make them.

**TWO VERDICTS, NOT ONE.** ``available`` answers *can this machine produce the
document* and ``narration_available`` answers *can it narrate one*. Below the bar
those are opposite answers, so one key could not carry both without the
one-key-two-meanings defect this codebase has paid for repeatedly — a caller
reading a single ``available`` would have to guess which question it answered.

The mechanism is the existing ``inference_capability()``, and using it rather than
``detect_gpu()`` is load-bearing. Those are two predicates on purpose:
``detect_gpu()`` answers "can vLLM run HERE?" and is read by every vLLM-gating
call site; vLLM ships manylinux wheels only and cannot serve Apple Metal, so
teaching it about Apple Silicon would route every Mac to a backend that cannot
run there. ``inference_capability()`` is the only correct place for hardware
policy, and ``tests/test_inference_hardware_gate.py``'s ast guard enforces that.

NEVER A HARD BLOCK: the standing ``llm_allow_impractical_hw`` /
``OO_LLM_ALLOW_IMPRACTICAL_HW=1`` override reveals narration with the warning
stated, and the verdict reports ``overridden`` so neither direction is silent.
"""

from __future__ import annotations

# OPEN QUESTION 4 (design record §20) lives here, and here only: *should Layer A be
# available below the hardware gate, given it needs no model?*
#
# RULED 2026-09-07: **no gate on the document.** A GPU-less operator gets the
# deterministic half, which is what this constant being False means; the narration
# verdict beside it is a hardware FACT and never reads this constant, so flipping
# it back gates the document again and cannot silently gate anything else.
LAYER_A_REQUIRES_CAPABLE_HARDWARE = False

_METHOD = (
    "reads inference_capability() (the practical-local-inference predicate, which "
    "composes detect_gpu() and detect_apple_silicon()); never re-derives hardware "
    "policy. Two verdicts: the document (deterministic, no model) and the narration "
    "layer (a local model, thousands of calls)."
)

#: The disclosure when the document is NOT gated — the ruled state. It must not
#: claim the machine was refused anything it was not: below the bar the document
#: is produced and only the prose is withheld.
_CAVEAT_DOCUMENT_UNGATED = (
    "The document itself needs no model: it is exact SQL over your corpus and is "
    "produced on any machine. Only the narration layer is gated on hardware that can "
    "practically run a local model, because it is thousands of calls rather than one "
    "interactive one. Below that bar the document is complete and simply carries no "
    "model-written sentences — which is what makes that layer removable rather than "
    "required. The override reveals narration anyway, with the warning stated."
)

#: The disclosure when the document IS gated — the original ruling's state. Kept
#: correct rather than deleted: flipping the constant back must restore an honest
#: sentence, not leave the ungated wording describing a refusal it no longer
#: matches. A disclosure that is only right in the state that happens to ship is
#: how a one-line flip becomes a lie.
_CAVEAT_DOCUMENT_GATED = (
    "The Bulletin is gated as a whole on hardware that can practically run a local "
    "model, because its narration layer is thousands of calls rather than one "
    "interactive one. The deterministic half needs no model and is withheld only "
    "because the feature is gated as a whole. The override reveals it."
)

_CAVEAT_NARRATION = (
    "AI-derived and removable. Narration is gated on hardware that can practically "
    "run a local model: the workload is one constrained call per story, not one "
    "interactive summary, so a machine that handles the second may still be refused "
    "the first. A refusal costs prose and no figures — every number in the document "
    "is computed without a model either way."
)

#: The disclosure when nothing was measured. Correct whichever way the constant is
#: set, because it makes no claim about the gate at all — the recorded rule that an
#: unreadable hardware fact reports *unmeasured*, never *below*.
_CAVEAT_UNMEASURED = (
    "This machine's hardware could not be read, so nothing here is a measurement of "
    "it. An unreadable probe is reported as unmeasured, never as a machine that "
    "falls short — and never as one that passes."
)


def _degraded(exc: Exception) -> dict:
    """A probe that raised answers UNAVAILABLE for both verdicts, with the error.

    Never an assumed pass, and never an assumed refusal dressed as a measurement:
    the reason names the probe, so "we could not tell" cannot be read as "this
    machine cannot".
    """
    reason = f"the hardware capability probe failed: {type(exc).__name__}: {exc}"
    return {
        "available": False,
        "reason": reason,
        "narration_available": False,
        "narration_reason": reason,
        "overridden": False,
        "warnings": [],
        "capability": None,
        "method": _METHOD,
        "caveat": _CAVEAT_UNMEASURED,
        "narration_caveat": _CAVEAT_UNMEASURED,
    }


def bulletin_available(*, capability: dict | None = None) -> dict:
    """Can this machine produce a Bulletin, and can it narrate one?

    Returns ``{available, reason, narration_available, narration_reason,
    overridden, warnings, capability, method, caveat, narration_caveat}``.
    ``capability`` may be passed in by a caller that already probed, so a page
    rendering several gated surfaces pays for one probe.

    Degrades LOUDLY: if the hardware probe itself raises, both verdicts are
    unavailable WITH the error — never an assumed pass, and never a crash in a
    surface that only wanted to know whether to draw a button.
    """
    cap = capability
    if cap is None:
        try:
            from src.llm.backend import inference_capability

            cap = inference_capability()
        except Exception as exc:  # noqa: BLE001 - a probe failure degrades, never raises
            return _degraded(exc)

    # THE ONE READ of the open-question-4 constant, bound once so the verdict, the
    # reason and the caveat all derive from the same value. A local is not a second
    # place to flip — it is the same place, read once — which is what keeps the
    # read-count guard meaningful while letting the disclosure differ by state.
    gate_covers_document = LAYER_A_REQUIRES_CAPABLE_HARDWARE

    practical = bool(cap.get("practical"))
    hardware_reason = str(cap.get("reason") or "")

    available = practical or not gate_covers_document
    if practical:
        reason = hardware_reason or "this machine can practically run a local model"
    elif available:
        reason = (
            "the document needs no model, so it is produced on this machine even though "
            "it cannot practically run one"
        )
    else:
        reason = hardware_reason or "this machine cannot practically run a local model"

    if practical:
        narration_reason = hardware_reason or "this machine can practically run a local model"
    else:
        narration_reason = hardware_reason or "this machine cannot practically run a local model"
        if not gate_covers_document:
            # Only sayable while the document is ungated. With the constant flipped
            # back the document is NOT produced, so this clause would be a fabricated
            # reassurance — which is why it is conditional rather than appended once.
            narration_reason += " — the document is produced without it and says so"

    return {
        "available": available,
        "reason": reason,
        # The model verdict is a HARDWARE FACT and reads no policy constant: flipping
        # open question 4 back must gate the document again and must not, by that
        # act, change what is true about the machine's ability to narrate.
        "narration_available": practical,
        "narration_reason": narration_reason,
        "overridden": bool(cap.get("overridden")),
        # Carried verbatim so a caller can render the same warnings the AI panel does,
        # instead of paraphrasing hardware facts into a second, drifting wording.
        "warnings": list(cap.get("warnings") or []),
        "capability": cap,
        "method": _METHOD,
        "caveat": _CAVEAT_DOCUMENT_GATED if gate_covers_document else _CAVEAT_DOCUMENT_UNGATED,
        "narration_caveat": _CAVEAT_NARRATION,
    }

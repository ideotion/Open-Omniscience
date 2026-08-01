"""
The Bulletin's hardware gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED (design record §3): **the whole feature is unavailable on hardware that
cannot practically run local inference** — not merely the narration layer, the
feature does not appear.

The mechanism is the existing ``inference_capability()``, and using it rather than
``detect_gpu()`` is load-bearing. Those are two predicates on purpose:
``detect_gpu()`` answers "can vLLM run HERE?" and is read by every vLLM-gating
call site; vLLM ships manylinux wheels only and cannot serve Apple Metal, so
teaching it about Apple Silicon would route every Mac to a backend that cannot
run there. ``inference_capability()`` is the only correct place for hardware
policy, and ``tests/test_inference_hardware_gate.py``'s ast guard enforces that.

NEVER A HARD BLOCK: the standing ``llm_allow_impractical_hw`` /
``OO_LLM_ALLOW_IMPRACTICAL_HW=1`` override reveals the feature with the warning
stated, and the verdict reports ``overridden`` so neither direction is silent.
"""

from __future__ import annotations

# OPEN QUESTION 4 (design record §20) lives here, and here only: *should Layer A be
# available below the hardware gate, given it needs no model?*
#
# The ruling as given gates the whole feature, so this is True. The recorded
# consequence is that a GPU-less operator is denied even the deterministic
# document, which is pure SQL and would run anywhere. Flipping this one constant
# is the entire implementation of the other answer — which is why the gate is a
# constant and not a condition scattered across call sites.
LAYER_A_REQUIRES_CAPABLE_HARDWARE = True

_METHOD = (
    "reads inference_capability() (the practical-local-inference predicate, which "
    "composes detect_gpu() and detect_apple_silicon()); never re-derives hardware policy"
)
_CAVEAT = (
    "The Bulletin is gated on hardware that can practically run a local model, "
    "because its narration layer is thousands of calls rather than one interactive "
    "one. The deterministic half needs no model and is withheld only because the "
    "feature is gated as a whole. The override reveals it."
)


def bulletin_available(*, capability: dict | None = None) -> dict:
    """Is the Bulletin available on this machine?

    Returns ``{available, reason, overridden, capability, method, caveat}``.
    ``capability`` may be passed in by a caller that already probed, so a page
    rendering several gated surfaces pays for one probe.

    Degrades LOUDLY: if the hardware probe itself raises, the answer is
    unavailable WITH the error — never an assumed pass, and never a crash in a
    surface that only wanted to know whether to draw a button.
    """
    cap = capability
    if cap is None:
        try:
            from src.llm.backend import inference_capability

            cap = inference_capability()
        except Exception as exc:  # noqa: BLE001 - a probe failure degrades, never raises
            return {
                "available": False,
                "reason": f"the hardware capability probe failed: {type(exc).__name__}: {exc}",
                "overridden": False,
                "capability": None,
                "method": _METHOD,
                "caveat": _CAVEAT,
            }

    practical = bool(cap.get("practical"))
    available = practical or not LAYER_A_REQUIRES_CAPABLE_HARDWARE
    if practical:
        reason = str(cap.get("reason") or "this machine can practically run a local model")
    elif available:
        reason = (
            "the deterministic half needs no model, so it is offered even though this "
            "machine cannot practically run one"
        )
    else:
        reason = str(cap.get("reason") or "this machine cannot practically run a local model")

    return {
        "available": available,
        "reason": reason,
        "overridden": bool(cap.get("overridden")),
        # Carried verbatim so a caller can render the same warnings the AI panel does,
        # instead of paraphrasing hardware facts into a second, drifting wording.
        "warnings": list(cap.get("warnings") or []),
        "capability": cap,
        "method": _METHOD,
        "caveat": _CAVEAT,
    }

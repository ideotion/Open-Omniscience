"""
Dual-backend LLM resolution (B1, 2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED (A12, binding): vLLM on GPU-equipped machines (concurrency is the point,
B3), Ollama KEPT for the CPU-only fleet -- never a silent replacement, never
dropped. This module is the ONE place that decision is made, so every consumer
(the Settings AI tab, bulk summarize/translate, the triage/tag toggles, the law-
change summaries) resolves the SAME way instead of each hardcoding Ollama.

The resolution is DISCLOSED, never silent: ``resolve_backend()`` returns the
detection FACTS alongside the decision (GPU presence, vLLM installed/running,
Ollama available) so the Settings -> AI tab can state the active backend and
WHY, per the honesty non-negotiable (no fabricated capability, no hidden switch).

``LlmBackend`` is a structural Protocol (mypy-checked, not runtime-enforced) --
both ``OllamaClient`` and ``VllmClient`` already satisfy it without inheriting
from anything, so every existing Ollama-only call site keeps working unchanged;
only the RESOLVED client type changes when a GPU + an installed vLLM are present.
"""

from __future__ import annotations

import os
import platform
import subprocess  # noqa: S404 - fixed argv, no shell, 5s timeout (nvidia-smi probe only)
from typing import Protocol, runtime_checkable

from src.llm.ollama import GenerationResult, total_ram_gb

_VALID_OVERRIDES = ("auto", "ollama", "vllm")

# The clause every reason ends with when NOTHING can serve a request. A module
# constant so tests and any UI pin the sentence instead of a brittle literal.
NO_BACKEND_REASON = "no AI backend is reachable right now"


@runtime_checkable
class LlmBackend(Protocol):
    """The structural surface every LLM backend client provides. Both
    ``OllamaClient`` (``src.llm.ollama``) and ``VllmClient``
    (``src.llm.vllm_client``) satisfy this without declaring it explicitly --
    Python Protocols check structurally, so no inheritance/registration is
    needed and neither client's own module needs to import the other's."""

    def generate(
        self,
        prompt: str,
        *,
        model: str = ...,
        system: str | None = ...,
        keep_alive: str | None = ...,
    ) -> GenerationResult: ...

    def list_installed(self) -> list[str]: ...

    def is_available(self) -> bool: ...

    def close(self) -> None: ...


def detect_gpu() -> dict:
    """Best-effort NVIDIA GPU presence + VRAM probe via ``nvidia-smi`` (no torch/
    pynvml -- core stays free of GPU libraries). Honest ``available: False`` when
    the probe fails (no GPU, no driver, the command is missing, or it times out) --
    never asserted from guesswork. AMD/other GPUs are not probed here (vLLM's own
    ROCm path exists, per its PyPI description, but this app has no verified
    detection story for it yet; an honest gap, not a fabricated "no GPU")."""
    try:
        out = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell, 5s cap
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "nvidia-smi not found or timed out"}
    if out.returncode != 0 or not out.stdout.strip():
        return {"available": False, "reason": "nvidia-smi returned no GPU"}
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    name = parts[0] if parts else None
    vram_mb: int | None = None
    if len(parts) > 1:
        try:
            vram_mb = int(float(parts[1]))
        except ValueError:
            vram_mb = None
    return {"available": True, "name": name, "vram_mb": vram_mb}


# --------------------------------------------------------------------------- #
#  HARDWARE SUITABILITY GATE (2026-07-30, maintainer-ruled)
#
#  RULED: "Using vLLM or Ollama on <8GB RAM, GPU-less laptops is impractical,
#  it's ok to limit them. This is only for my GPU enabled machine (by GPU, I
#  mean dedicated GPU, not the integrated ones we find on most CPUs nowadays,
#  and I exclude from this reasoning the sorts of Mac minis having dual-use
#  memory that is precisely good at inference, this is another matter)."
#
#  TWO PREDICATES, DELIBERATELY NOT ONE -- do not merge them:
#
#    1. "Can vLLM run HERE?"  ->  detect_gpu() (above). CUDA-capable dedicated
#       NVIDIA GPU. resolve_backend() routes to vLLM on this and this only.
#    2. "Is local inference PRACTICAL on this machine at all?" -> the policy
#       predicate below. Dedicated NVIDIA GPU **OR** Apple Silicon.
#
#  vLLM is CUDA/ROCm and does NOT run on Apple Metal (vllm ships manylinux
#  wheels only -- see vllm_lifecycle.platform_support()). So teaching
#  detect_gpu() to answer True on Apple Silicon would route every Mac to a
#  vLLM that cannot serve them. Apple Silicon is inference-PRACTICAL (unified
#  memory, the maintainer's explicit carve-out) while remaining vLLM-INCAPABLE,
#  and only two separate predicates can express both facts at once.
# --------------------------------------------------------------------------- #

# The unified-memory floor at/above which Apple Silicon is treated as practical.
#
# REASONING (a stated, revisable judgement -- NOT a benchmark this project has
# run): Apple Silicon shares ONE pool between CPU and GPU, and macOS caps the
# GPU-usable fraction well below the total. An 8B-class model at 4-bit is
# roughly 4.5-5 GB of weights BEFORE the KV cache and context window, and this
# app is not the only tenant -- it is simultaneously running a browser UI and an
# encrypted SQLCipher corpus. On an 8 GB machine that combination leaves the
# system swapping rather than inferring; 16 GB fits an 8B-class model alongside
# the app with headroom. Below the floor the operator can still force it on
# (OO_LLM_ALLOW_IMPRACTICAL_HW / the Settings toggle) -- this is a DEFAULT, never
# a block.
APPLE_SILICON_MIN_UNIFIED_RAM_GB = 16.0

# Env override (the OO_* convention). "unsupported/impractical" here means
# "below the practicality bar this gate enforces" -- NOT "will not function".
ENV_ALLOW_IMPRACTICAL_HW = "OO_LLM_ALLOW_IMPRACTICAL_HW"

# RULING 15 (maintainer, 2026-07-31) REFINES the 2026-07-30 rule this file used
# to encode. That rule refused local inference wherever a dedicated GPU was
# absent -- explicitly including "a 64 GB GPU-less workstation", which is the
# case that made it too blunt. The tiers are now:
#
#   HARD REFUSAL   fewer than MIN_CPU_CORES cores OR less than MIN_SYSTEM_RAM_GB
#                  of RAM. Below this, local inference is not worth starting.
#   WARNING        no dedicated GPU at all, or a GPU with less than
#                  MIN_VRAM_WARN_GB. Practical, but say so.
#
# So a GPU-less machine that clears the floor now DEFAULTS ON with the warning
# stated, rather than being refused. The Apple Silicon carve-out, the override
# and the never-a-hard-block posture are unchanged.
MIN_CPU_CORES = 4
MIN_SYSTEM_RAM_GB = 6.0

# 5, not 6, and the reason is measured rather than chosen: Mistral-7B Q4 needs
# ~4.4 GB and was measured at 5.1 GB in use, so a 6 GB line would warn about
# cards that genuinely run the default model. The warning exists to set
# expectations, not to discourage hardware that works.
MIN_VRAM_WARN_GB = 5.0

# The verifiable consequence of running local inference on unsuitable hardware.
# DELIBERATE WORDING (2026-07-30): the rationale behind the ruling mentions heat
# damaging hardware, but this project does not state claims it cannot
# substantiate -- modern CPUs thermal-THROTTLE rather than damage themselves.
# The throttling/slowness/core-saturation half is observable and survives
# challenge; the damage half is not asserted anywhere in this codebase.
IMPRACTICAL_CONSEQUENCE = (
    "local inference here would be impractically slow, saturate every core for "
    "hours, and run the machine into sustained thermal throttling"
)

_CAPABILITY_METHOD = (
    "nvidia-smi probe for a dedicated NVIDIA GPU; platform.system()/machine() "
    "plus total system RAM for Apple Silicon unified memory. Read-only, no network."
)

_CAPABILITY_CAVEAT = (
    "Detects dedicated NVIDIA GPUs and Apple Silicon only. AMD/Intel discrete "
    "GPUs are NOT probed (an honest gap, not a measurement), so such a machine "
    "reports as GPU-less and is judged on its CPU/RAM alone; integrated GPUs are "
    "deliberately excluded. Presence is not a performance promise -- a low-VRAM "
    "dedicated GPU still passes this gate with a warning, and per-model fit is "
    "judged separately by the model catalog's RAM hints and the vLLM install "
    "preflight."
)


def detect_apple_silicon() -> dict:
    """Best-effort Apple Silicon (arm64 macOS) presence + unified-RAM probe.

    PURE DETECTION, no policy: this answers "is this an Apple Silicon Mac, and
    how much unified memory does it have?" -- the RAM FLOOR is applied by
    ``inference_capability()``, exactly as ``detect_gpu()`` reports GPU presence
    while ``resolve_backend()`` owns the routing policy.

    An Intel Mac is NOT Apple Silicon: it has no unified memory, which is the
    entire reason for the maintainer's carve-out. ``unified_ram_gb`` is ``None``
    when the RAM probe cannot read a value -- an honest absence, never a 0.
    """
    try:
        system = platform.system()
        machine = platform.machine()
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the resolver
        return {"available": False, "reason": f"platform probe failed: {str(exc)[:120]}"}
    if system != "Darwin":
        return {
            "available": False,
            "reason": f"not macOS (platform.system() = {system or 'unknown'!r})",
        }
    if machine.lower() not in ("arm64", "aarch64"):
        # Named specifically, because "not Apple Silicon" on a Mac is a different
        # situation from "not a Mac" and the operator deserves the real reason.
        # DELIBERATELY not phrased as "this is an Intel Mac": an x86_64 Python
        # running under Rosetta on an M-series Mac reports x86_64 here too, and
        # asserting the hardware from an interpreter-level reading would be a
        # claim we cannot make. What we DID observe is the architecture Python
        # reports -- so that is what the sentence says.
        return {
            "available": False,
            "reason": (
                f"macOS, but Python reports architecture {machine or 'unknown'!r} rather "
                "than arm64 -- either an Intel Mac (no unified memory) or an x86_64 "
                "interpreter running under Rosetta; install an arm64 Python to use "
                "Apple Silicon here"
            ),
        }
    return {
        "available": True,
        "name": f"Apple Silicon ({machine})",
        "unified_ram_gb": total_ram_gb(),
    }


def _capability(
    *,
    practical: bool,
    kind: str | None,
    name: str | None,
    reason: str,
    overridden: bool,
    override_requested: bool,
    vram_mb: int | None = None,
    unified_ram_gb: float | None = None,
    warnings: list[str] | None = None,
    cpu_cores: int | None = None,
    total_ram_gb_: float | None = None,
) -> dict:
    """ONE builder for EVERY branch, so a field can never be present in three
    returns and silently missing from the fourth (the same rationale as
    ``_result()`` above -- an absent field reads as an answer)."""
    return {
        "practical": practical,
        "kind": kind,
        "name": name,
        "vram_mb": vram_mb,
        "unified_ram_gb": unified_ram_gb,
        "reason": reason,
        "method": _CAPABILITY_METHOD,
        "caveat": _CAPABILITY_CAVEAT,
        "overridden": overridden,
        "override_requested": override_requested,
        "min_unified_ram_gb": APPLE_SILICON_MIN_UNIFIED_RAM_GB,
        # Ruling 15's tiers, reported so a caller never has to re-derive them.
        # warnings is ALWAYS a list: an absent key would read as "no warnings"
        # in exactly the branch that forgot to set it.
        "warnings": list(warnings or []),
        "cpu_cores": cpu_cores,
        "total_ram_gb": total_ram_gb_,
        "min_cpu_cores": MIN_CPU_CORES,
        "min_system_ram_gb": MIN_SYSTEM_RAM_GB,
        "min_vram_warn_gb": MIN_VRAM_WARN_GB,
    }


def _override_requested(override: bool | None) -> bool:
    """Has the operator asked to run local inference on hardware this gate calls
    impractical?

    Precedence: an explicit argument (a caller that already loaded settings passes
    it, so no branch pays a second read) -> the persisted Settings toggle -> the
    ``OO_LLM_ALLOW_IMPRACTICAL_HW`` env var. The settings read is GUARDED: a
    settings hiccup falls through to the env var rather than taking down a
    hardware probe, and never fabricates an enable."""
    if override is not None:
        return bool(override)
    try:
        from src.config.app_settings import load_settings

        if bool(load_settings().llm_allow_impractical_hw):
            return True
    except Exception:  # noqa: BLE001 - a preference read must never break the probe
        pass
    return os.getenv(ENV_ALLOW_IMPRACTICAL_HW, "0") == "1"


def inference_capability(*, override: bool | None = None, gpu: dict | None = None) -> dict:
    """Is running a local LLM on THIS machine practical? Returns::

        {
          "practical": bool,          # the EFFECTIVE answer callers gate on
          "kind": "nvidia" | "apple-silicon" | None,
          "name": str | None,
          "vram_mb": int | None,          # NVIDIA only
          "unified_ram_gb": float | None, # Apple Silicon only
          "reason": str,              # why practical / why not -- ALWAYS present
          "method": str,
          "caveat": str,
          "overridden": bool,           # practical is True BECAUSE of the override
          "override_requested": bool,   # the operator set the override at all
          "min_unified_ram_gb": float,  # the documented Apple Silicon floor
          "warnings": list[str],        # practical, but say what to expect
          "cpu_cores": int | None,
          "total_ram_gb": float | None,
          "min_cpu_cores": int,
          "min_system_ram_gb": float,
          "min_vram_warn_gb": float,
        }

    POLICY (maintainer-ruled 2026-07-31, RULING 15, superseding the 2026-07-30
    GPU-absence rule this function used to encode):

      HARD REFUSAL -- and ONLY this:
        no accelerator at all AND (fewer than ``MIN_CPU_CORES`` cores OR less
        than ``MIN_SYSTEM_RAM_GB`` of RAM).

      PRACTICAL, with a WARNING:
        * no dedicated GPU but the CPU/RAM floor clears -- the case the old rule
          refused and ruling 15 explicitly named as too blunt;
        * a dedicated NVIDIA GPU under ``MIN_VRAM_WARN_GB``;
        * Apple Silicon under ``APPLE_SILICON_MIN_UNIFIED_RAM_GB``.

      PRACTICAL, no warning:
        a dedicated NVIDIA GPU with enough VRAM, or Apple Silicon at/above the
        unified-memory floor.

    A DETECTED ACCELERATOR IS POSITIVE EVIDENCE and is never refused by the
    CPU/RAM floor: the floor exists to judge the machine when nothing else
    vouches for it. This also keeps the gate correct on a core install, where
    ``psutil`` is an optional ``[analysis]`` dependency and the RAM read returns
    ``None``.

    ONE JUDGEMENT CALL, stated rather than hidden: ruling 15 says the Apple
    Silicon carve-out is "unchanged" while also stating that the hard-refusal
    tier IS the CPU/RAM floor. A SECOND, higher hard floor for Apple Silicon
    alone would contradict that, and would refuse an 8 GB M-series Mac while
    passing a 4-core/6 GB GPU-less PC -- treating the carve-out's own hardware
    worse than the machines it exists to favour. So the recognition is unchanged
    and the 16 GB line becomes a warning threshold, exactly like the VRAM line.

    NEVER A HARD BLOCK. ``practical: False`` means AI features DEFAULT to off
    with the reason stated; the operator can always turn them back on
    (``OO_LLM_ALLOW_IMPRACTICAL_HW=1`` or the Settings toggle), and when they do
    the verdict says ``overridden: True`` and the disclosure still shows. Neither
    direction is silent.

    THE THIRD STATE IS EPISTEMIC, NOT PERMISSIVE. Where a floor CANNOT BE
    CHECKED because the measurement is missing -- Apple Silicon whose unified RAM
    could not be read, or a GPU-less machine whose cores/RAM could not be counted
    -- the answer is ``practical: False`` naming the ABSENCE. A pass granted on an
    absent measurement is a fabricated capability just as a fail invented from one
    would be a fabricated refusal. The refusal explains the absence and points at
    the override.

    ``gpu``: an already-computed ``detect_gpu()`` payload. Callers that just ran
    it (``resolve_backend()``, ``/api/llm/backend``) pass it through so this costs
    ZERO additional ``nvidia-smi`` probes -- mirroring ``install_preflight(gpu=)``.
    """
    requested = _override_requested(override)

    if gpu is None:
        try:
            gpu = detect_gpu()
        except Exception as exc:  # noqa: BLE001 - a failed probe is never a "no GPU"
            gpu = {"available": False, "reason": f"GPU probe failed: {str(exc)[:120]}"}
    try:
        apple = detect_apple_silicon()
    except Exception as exc:  # noqa: BLE001 - likewise; degrade, never crash
        apple = {"available": False, "reason": f"Apple Silicon probe failed: {str(exc)[:120]}"}

    # ---- ruling 15's HARD floor, applied where it actually decides something.
    #
    # ORDER MATTERS, and the first cut had it wrong: this ran BEFORE the probes,
    # so on a core install -- where psutil is an optional [analysis] dependency
    # and total_ram_gb() returns None -- it refused local inference on EVERY
    # machine, including one with a perfectly good dedicated GPU, because RAM
    # could not be counted. A detected GPU is itself strong evidence the machine
    # is capable; refusing it over an unreadable RAM figure inverts the point of
    # the floor.
    #
    # So: a detected dedicated GPU or Apple Silicon is POSITIVE EVIDENCE and is
    # never refused for want of a measurement (an unreadable figure downgrades to
    # a warning below). The floor is decisive exactly where ruling 15 aimed it --
    # the CPU-only case, where nothing else vouches for the machine.
    cores = os.cpu_count()
    ram_gb = total_ram_gb()
    has_accelerator = bool(gpu.get("available")) or bool(apple.get("available"))
    if not has_accelerator:
        # NAME what the probes actually said. "nvidia-smi timed out" and "this
        # machine has no GPU" are different claims, and only one of them was
        # measured -- collapsing them is the fabrication the probe-failure tests
        # exist to catch.
        probe_why = f"{gpu.get('reason') or 'no dedicated NVIDIA GPU detected'}; {apple.get('reason')}"
        if cores is None or ram_gb is None:
            missing = "CPU core count" if cores is None else "total system RAM"
            return _capability(
                practical=bool(requested),
                kind=None,
                name=None,
                reason=(
                    f"no usable accelerator was detected ({probe_why}), and this "
                    f"machine's {missing} could not be read, so the {MIN_CPU_CORES}-core / "
                    f"{MIN_SYSTEM_RAM_GB:g} GB floor could not be checked either"
                    + (
                        " -- enabled anyway by the operator override."
                        if requested
                        else ". AI features default to off; the override turns them on."
                    )
                ),
                overridden=bool(requested),
                override_requested=requested,
                cpu_cores=cores,
                total_ram_gb_=ram_gb,
            )
        if cores < MIN_CPU_CORES or ram_gb < MIN_SYSTEM_RAM_GB:
            short = []
            if cores < MIN_CPU_CORES:
                short.append(f"{cores} CPU core(s), below the {MIN_CPU_CORES} needed")
            if ram_gb < MIN_SYSTEM_RAM_GB:
                short.append(f"{ram_gb:g} GB RAM, below the {MIN_SYSTEM_RAM_GB:g} GB needed")
            return _capability(
                practical=bool(requested),
                kind=None,
                name=None,
                reason=(
                    f"{' and '.join(short)}, and no usable accelerator ({probe_why}) "
                    f"-- {IMPRACTICAL_CONSEQUENCE}"
                    + (
                        ". Enabled anyway by the operator override."
                        if requested
                        else ". AI features default to off; the override turns them on."
                    )
                ),
                overridden=bool(requested),
                override_requested=requested,
                cpu_cores=cores,
                total_ram_gb_=ram_gb,
            )

    # NVIDIA first and deterministically: if both somehow report available, the
    # CUDA path is the one that also unlocks vLLM, so it is the honest label.
    if gpu.get("available"):
        return _capability(
            practical=True,
            kind="nvidia",
            name=gpu.get("name"),
            vram_mb=gpu.get("vram_mb"),
            reason="a dedicated NVIDIA GPU is present -- local inference is practical here",
            overridden=False,
            override_requested=requested,
            warnings=_vram_warnings(gpu.get("vram_mb")),
            cpu_cores=cores,
            total_ram_gb_=ram_gb,
        )

    if apple.get("available"):
        # COERCE before comparing. A probe that hands back a non-numeric value
        # (the project has been bitten by TEXT-typed read-backs before) would
        # otherwise raise straight out of this comparison. Found by the pre-push
        # adversarial pass, when the langdetect ride-along still swallowed
        # exceptions -- so the raise made the gate fail OPEN, the one direction a
        # default-off gate must never fail. That call site now fails CLOSED too;
        # this stays as the first line of defence, because a caller that guards
        # itself is not a reason for a probe to raise. An uncoercible value is
        # UNMEASURED, which is the honest third state below.
        ram = apple.get("unified_ram_gb")
        try:
            ram = None if ram is None else float(ram)
        except (TypeError, ValueError):
            ram = None
        if ram is None:
            # UNMEASURED, not "too small". Distinguishable from a real shortfall.
            return _capability(
                practical=bool(requested),
                kind="apple-silicon",
                name=apple.get("name"),
                unified_ram_gb=None,
                reason=(
                    "Apple Silicon detected, but its unified memory could not be read, "
                    f"so the {APPLE_SILICON_MIN_UNIFIED_RAM_GB:g} GB floor could not be "
                    "checked"
                    + (
                        " -- enabled anyway by the operator override."
                        if requested
                        else ". AI features default to off; the override turns them on."
                    )
                ),
                overridden=bool(requested),
                override_requested=requested,
                # Reported even here: these WERE read, and blanking a figure we
                # actually have would be an invented absence -- the mirror image
                # of the invented measurement this branch exists to refuse.
                cpu_cores=cores,
                total_ram_gb_=ram_gb,
            )
        if ram >= APPLE_SILICON_MIN_UNIFIED_RAM_GB:
            return _capability(
                practical=True,
                kind="apple-silicon",
                name=apple.get("name"),
                unified_ram_gb=ram,
                reason=(
                    f"Apple Silicon with {ram:g} GB unified memory (>= the "
                    f"{APPLE_SILICON_MIN_UNIFIED_RAM_GB:g} GB floor) -- unified memory is "
                    "well suited to local inference"
                ),
                overridden=False,
                override_requested=requested,
                cpu_cores=cores,
                total_ram_gb_=ram_gb,
            )
        return _capability(
            practical=True,
            kind="apple-silicon",
            name=apple.get("name"),
            unified_ram_gb=ram,
            reason=(
                f"Apple Silicon with {ram:g} GB unified memory -- practical, though "
                f"below the {APPLE_SILICON_MIN_UNIFIED_RAM_GB:g} GB that fits an "
                "8B-class model alongside the app with headroom"
            ),
            overridden=False,
            override_requested=requested,
            warnings=[
                f"{ram:g} GB unified memory is under the "
                f"{APPLE_SILICON_MIN_UNIFIED_RAM_GB:g} GB comfort floor: expect a "
                "smaller model, or slower going on a large one."
            ],
            cpu_cores=cores,
            total_ram_gb_=ram_gb,
        )

    # No dedicated GPU. Under ruling 15 this is a WARNING, not a refusal: the
    # machine already cleared the CPU/RAM floor above, which is the bar that
    # actually decides whether local inference is worth starting. Still state
    # WHICH probe said what, so "nvidia-smi timed out" never reads as the flat,
    # fabricated claim "this machine has no GPU".
    gpu_why = gpu.get("reason") or "no dedicated NVIDIA GPU detected"
    return _capability(
        practical=True,
        kind=None,
        name=None,
        reason=(
            f"{cores} CPU cores and {ram_gb:g} GB RAM clear the "
            f"{MIN_CPU_CORES}-core / {MIN_SYSTEM_RAM_GB:g} GB floor -- local inference is "
            "practical here, on the CPU"
        ),  # both figures are readable here: the floor above returned otherwise
        overridden=False,
        override_requested=requested,
        warnings=[
            "No dedicated GPU was found, so inference runs on the CPU: expect it to "
            "be slow and to keep the cores busy while it works. "
            f"({gpu_why}; {apple.get('reason')}. AMD/Intel discrete GPUs are not "
            "probed by this app, so a discrete-Radeon machine reports this too.)"
        ],
        cpu_cores=cores,
        total_ram_gb_=ram_gb,
    )


def _vram_warnings(vram_mb: object) -> list[str]:
    """Warn about a thin-VRAM dedicated GPU -- never refuse one (ruling 15).

    UNMEASURED VRAM produces NO warning rather than a guessed one: the GPU is
    present and practical either way, and inventing a shortfall from an absent
    measurement is the same fabrication as inventing a pass from one.

    The parameter is ``object`` on purpose -- ``detect_gpu()`` reads a subprocess
    and the project has been bitten by TEXT-typed read-backs before -- so the type
    is NARROWED here rather than asserted. ``bool`` is excluded explicitly: it is
    a subclass of ``int``, so ``float(True)`` would quietly become a measured
    "1 MB of VRAM" and emit a warning about a number nobody read. That is the
    ``int(True) == 1`` trap this codebase already has a lesson about.
    """
    if isinstance(vram_mb, bool) or not isinstance(vram_mb, (int, float, str)):
        return []
    try:
        mb = float(vram_mb)
    except (TypeError, ValueError):
        return []
    gb = mb / 1024.0
    if gb >= MIN_VRAM_WARN_GB:
        return []
    return [
        f"{gb:.1f} GB of VRAM is under the {MIN_VRAM_WARN_GB:g} GB the default model "
        "wants: expect to use a smaller one, or to run partly on the CPU."
    ]


def _vllm_status() -> dict:
    """Delegates to ``src.llm.vllm_lifecycle`` (B2) -- imported lazily so a plain
    backend-resolution call never pays for importing the lifecycle module's own
    (heavier) subprocess-management machinery unless vLLM is actually in play."""
    try:
        from src.llm.vllm_lifecycle import is_installed, is_running
    except ImportError:
        return {"installed": False, "running": False}
    return {"installed": is_installed(), "running": is_running()}


def _ollama_available() -> bool:
    try:
        from src.llm.ollama import OllamaClient

        return OllamaClient().is_available()
    except Exception:  # noqa: BLE001 - a probe must never crash the resolver
        return False


def _ollama_installed() -> bool:
    """Is the ``ollama`` BINARY present? Cheap (``shutil.which``), no network, and --
    crucially -- truthful while the daemon is stopped."""
    try:
        from src.llm.ollama_lifecycle import is_installed

        return is_installed()
    except Exception:  # noqa: BLE001 - a probe must never crash the resolver
        return False



def _result(
    *,
    backend: str,
    reason: str,
    override: str | None,
    gpu: dict,
    vllm: dict,
    ollama_ok: bool,
) -> dict:
    """Build the resolution payload. ONE builder for EVERY branch, so a field can
    never be present in three returns and silently missing from the fourth (the
    "an aggregation that omits an entry makes absent read as passed" family --
    the four hand-repeated dict literals this replaces were exactly that shape).

    ``available``/``no_backend`` are DERIVED from probes ``resolve_backend`` has
    already run this call -- no extra probe, no extra latency."""
    vllm_running = bool(vllm.get("running"))
    reachable = ollama_ok if backend == "ollama" else vllm_running
    # INSTALLED-vs-RUNNING for Ollama (field report 2026-07-29). Derived HERE, in the
    # one builder, for the same reason every other field is: so it cannot be present
    # in three branches and silently missing from the fourth. The reachability half is
    # reused from the probe the caller already ran -- only the binary check is new, and
    # that is a shutil.which, not a network call, so no branch pays a second probe.
    ollama_installed = _ollama_installed()
    return {
        "backend": backend,
        "reason": reason,
        "override": override,
        "gpu": gpu,
        "vllm": vllm,
        "ollama_available": ollama_ok,
        # --- V4 (2026-07-29) capability fields, purely ADDITIVE ------------ #
        "available": reachable,
        "no_backend": not (ollama_ok or vllm_running),
        # --- launchability (2026-07-29 field report), purely ADDITIVE ------ #
        # ``ollama`` mirrors the shape of ``vllm`` above so the UI can treat the two
        # backends uniformly. ``can_launch`` says a Launch button is honest to show:
        # the software is here, it is simply not answering.
        "ollama": {
            "installed": ollama_installed,
            "running": ollama_ok,
            "can_launch": ollama_installed and not ollama_ok,
        },
        "vllm_can_launch": bool(vllm.get("installed")) and not vllm_running,
    }


def resolve_backend(*, override: str | None = None) -> dict:
    """The ONE decision point: which backend should serve inference right now,
    and why. Returns::

        {
          "backend": "ollama" | "vllm",   # SELECTION -- who would serve
          "reason": "<disclosed, human-readable>",
          "override": "<the requested override, or None>",
          "gpu": {...},            # detect_gpu()
          "vllm": {"installed": bool, "running": bool},
          "ollama_available": bool,
          "available": bool,       # CAPABILITY -- is the SELECTED backend reachable NOW
          "no_backend": bool,      # NOTHING is reachable (neither Ollama nor vLLM)
        }

    SELECTION AND CAPABILITY ARE NOT THE SAME QUESTION (V4, 2026-07-29). The
    operator's 2026-07-29 diagnostics bundle showed ``backend: "ollama"`` with
    the reason "... using Ollama meanwhile" while ``ollama_available`` was
    ``false``: true about selection, misleading about capability -- that machine
    had NO working backend. ``ollama_available`` was computed and returned but
    consulted by no branch. Now every reason names the real situation, and a
    caller can test capability without re-deriving it.

    COST: both new fields are derived from probes this function ALREADY runs on
    every call (``_ollama_available()``, and ``_vllm_status()``'s ``is_running()``
    live health check) -- no additional probe, no additional latency.

    HONESTY: ``available`` is never assumed true. Both probes return False when
    they fail OR error, so False means "not observed reachable", never "known
    dead" -- the conservative direction; neither can report an unreachable
    backend as reachable. Two known conflations ride along, named not hidden:
    ``_ollama_available()`` cannot distinguish a stopped daemon from a
    misconfigured non-loopback ``OO_OLLAMA_URL``, and ``_vllm_status()``'s
    ImportError fallback reports ``running: False`` without probing.

    Precedence: an explicit ``override`` (or ``OO_LLM_BACKEND``) of "ollama"/"vllm"
    always wins (an operator's explicit choice is never second-guessed) -- but an
    override that selects an unreachable backend now SAYS SO rather than reading
    as a working choice; "auto" (the default) prefers vLLM ONLY when a GPU is
    present AND vLLM is installed AND its server is currently running -- vLLM is
    never auto-selected merely because it is installed (a stopped server would
    silently 503 every call); the caller-facing "start vLLM" flow (B2/B4) is what
    brings it up. Ollama is the default and fallback in every other case (RULED
    A12 -- never dropped)."""
    env_override = os.getenv("OO_LLM_BACKEND", "").strip().lower()
    chosen_override = (override or env_override or "auto").strip().lower()
    if chosen_override not in _VALID_OVERRIDES:
        chosen_override = "auto"

    gpu = detect_gpu()
    vllm = _vllm_status()
    ollama_ok = _ollama_available()
    vllm_running = bool(vllm.get("running"))

    if chosen_override == "ollama":
        if ollama_ok:
            reason = "explicit override (ollama) -- Ollama is reachable"
        elif vllm_running:
            reason = (
                "explicit override (ollama), but Ollama is NOT reachable "
                "-- vLLM's server IS running; clear the override or start Ollama"
            )
        else:
            reason = (
                f"explicit override (ollama), but Ollama is NOT reachable -- {NO_BACKEND_REASON}"
            )
        return _result(
            backend="ollama",
            reason=reason,
            override=chosen_override,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    if chosen_override == "vllm":
        if vllm_running:
            reason = "explicit override (vllm) -- its server is running"
        elif ollama_ok:
            reason = (
                "explicit override (vllm), but its server is NOT running "
                "-- Ollama IS reachable; clear the override to use it"
            )
        else:
            reason = (
                "explicit override (vllm), but its server is NOT running "
                f"-- {NO_BACKEND_REASON}"
            )
        return _result(
            backend="vllm",
            reason=reason,
            override=chosen_override,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    # auto: vLLM only when a GPU is present AND vLLM is installed AND running.
    if gpu.get("available") and vllm.get("installed") and vllm_running:
        return _result(
            backend="vllm",
            reason="GPU detected + vLLM installed and running (concurrency-capable)",
            override=None,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    # Every remaining branch FALLS BACK to Ollama -- so the reason must state
    # whether that fallback can actually serve a request (the V4 finding). The
    # SELECTION half of each sentence is unchanged (it is substring-pinned by
    # tests); only the trailing capability clause is now computed from a probe.
    if gpu.get("available") and vllm.get("installed"):
        selection = "GPU + vLLM installed but its server is not running"
        fallback = "using Ollama meanwhile (Ollama is reachable)"
    elif gpu.get("available"):
        selection = "GPU detected but vLLM is not installed"
        fallback = "using Ollama meanwhile (Ollama is reachable)"
    else:
        selection = "no GPU detected (or vLLM unavailable)"
        fallback = "Ollama is the CPU-first backend (reachable)"
    if ollama_ok:
        reason = f"{selection} -- {fallback}"
    elif vllm_running:
        # A vLLM server CAN be up while auto-selection declines it (is_running()
        # detects "a server started by another means entirely"): a backend IS
        # reachable, so this must NOT read as no_backend.
        reason = (
            f"{selection}, and Ollama is NOT reachable -- vLLM's server IS running "
            "but was not auto-selected (that needs a detected GPU and an installed vLLM)"
        )
    else:
        reason = f"{selection}, and Ollama is NOT reachable either -- {NO_BACKEND_REASON}"
    return _result(
        backend="ollama",
        reason=reason,
        override=None,
        gpu=gpu,
        vllm=vllm,
        ollama_ok=ollama_ok,
    )


# One client instance PER BACKEND KIND (never per call -- httpx connection pooling
# is worth reusing), re-resolved on every ``get_client()`` call so a backend that
# comes up/down mid-session (vLLM starting, Ollama restarting) is picked up without
# a process restart. Module-level singleton dict, mirrors the existing per-kind
# singleton convention (``src.api.llm._client`` before this change, ``OllamaClient``
# itself for pull_queue, etc.).
_clients: dict[str, object] = {}


def get_client_with_name(*, backend: str | None = None) -> tuple[str, LlmBackend]:
    """Resolve + return ``(backend_name, client)`` in ONE detection pass -- so a
    caller that also needs the backend NAME (B3's concurrency ceiling picks a
    different worker count for vLLM vs. Ollama) never re-runs GPU/vLLM/Ollama
    detection a second time just to learn what ``get_client()`` already knew."""
    from src.llm.ollama import OllamaClient
    from src.llm.vllm_client import VllmClient

    resolved = resolve_backend(override=backend)
    kind = resolved["backend"]
    # dict.setdefault is ONE atomic dict operation -- no check-then-act window
    # between reading membership and writing the cache entry (the 2026-07-25,
    # transversal audit 09, benign TOCTOU finding). A losing instance under a
    # genuine race is still constructed (as before) but never even bound to a
    # local before being superseded -- reclaimed near-instantly by refcounting.
    client = _clients.setdefault(kind, VllmClient() if kind == "vllm" else OllamaClient())
    return kind, client  # type: ignore[return-value]


def get_client(*, backend: str | None = None) -> LlmBackend:
    """Resolve + return the shared client for the active backend (lazily
    constructed, one instance per kind for the process lifetime)."""
    _, client = get_client_with_name(backend=backend)
    return client


def _reset_clients_for_tests() -> None:
    _clients.clear()


def outage_reason() -> str | None:
    """WHY the local model is failing, in the resolver's own words -- or None if a
    backend is reachable and the failure is something else.

    Field report 2026-08-02: with vLLM installed but its server dead and Ollama not
    running, Start background AI reported "local model hiccup (1/10) -- retrying in 5s"
    and counted to ten. Every one of those words was wrong: it was not a hiccup, and
    the app already knew exactly what it was -- ``resolve_backend()`` returns
    ``no_backend: true`` with a precise reason. The honest sentence was one field away
    while the operator read a misleading one.

    THIS DELIBERATELY DOES NOT DECIDE WHETHER TO KEEP RETRYING, and the first cut of it
    did. That was wrong: a health probe cannot tell a backend that is GONE from one that
    is momentarily unreachable (a model reload, a restart, a busy server all answer the
    same way), so ending a multi-hour sweep on that probe would break the transient-retry
    guarantee the backoff exists to provide -- the repo's own progressive-sweep tests
    caught it immediately. The retry budget is unchanged; only what the operator is TOLD
    changes, which is the actual defect.

    Never raises: a probe that cannot read returns None and the caller keeps its
    existing wording.
    """
    try:
        resolved = resolve_backend()
    except Exception:  # noqa: BLE001 - a message-enrichment probe must never break a run
        return None
    if resolved.get("no_backend") or not resolved.get("available"):
        return str(resolved.get("reason") or "no AI backend is reachable right now")
    return None

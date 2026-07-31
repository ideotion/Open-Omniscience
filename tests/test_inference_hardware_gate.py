"""
Tests for the HARDWARE SUITABILITY GATE (2026-07-30, maintainer-ruled):
local inference is offered by default only where it is practical -- a dedicated
NVIDIA GPU, or Apple Silicon with enough unified memory.

Deliberately heavy on the NEGATIVE space. The interesting failures of a gate are
not "does it pass good hardware" but: does an UNMEASURED value read as a
measured refusal, does a crashed probe fabricate a "no GPU", does an override
read as a hardware pass, and -- the trap this whole design exists to avoid --
does making Apple Silicon *practical* accidentally route Macs to a vLLM that
cannot run there.

No probe touches real hardware: platform/subprocess/RAM are all monkeypatched.
"""

from __future__ import annotations

import subprocess

import pytest

from src.config.app_settings import load_settings as _REAL_LOAD_SETTINGS
from src.llm import backend as B

_APPLE = {"available": True, "name": "Apple Silicon (arm64)", "unified_ram_gb": 32.0}
_NO_GPU = {"available": False, "reason": "nvidia-smi not found or timed out"}
_NVIDIA = {"available": True, "name": "NVIDIA GeForce RTX 4070", "vram_mb": 12282}
_NOT_APPLE = {"available": False, "reason": "not macOS (platform.system() = 'Linux')"}


@pytest.fixture(autouse=True)
def _neutral_override(monkeypatch):
    """No env override, and a settings read that yields the default (off), so a
    test asserting a refusal can never be silently rescued by an ambient enable."""
    monkeypatch.delenv(B.ENV_ALLOW_IMPRACTICAL_HW, raising=False)

    class _S:
        llm_allow_impractical_hw = False

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _S())
    yield


def _stub_hw(monkeypatch, *, gpu, apple):
    monkeypatch.setattr(B, "detect_gpu", lambda: gpu)
    monkeypatch.setattr(B, "detect_apple_silicon", lambda: apple)


# --------------------------------------------------------------------------- #
#  THE TRAP. Apple Silicon is inference-PRACTICAL and vLLM-INCAPABLE at the same
#  time. Conflating the two predicates would route every Mac to a vLLM that
#  ships no macOS wheel and cannot serve them.
# --------------------------------------------------------------------------- #
def test_apple_silicon_is_practical_but_never_routes_to_vllm(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_APPLE)
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": True, "running": True})
    monkeypatch.setattr(B, "_ollama_available", lambda: True)

    cap = B.inference_capability()
    assert cap["practical"] is True
    assert cap["kind"] == "apple-silicon"

    # ... and the SELECTION predicate is untouched: vLLM is installed AND running
    # here, so the ONLY thing keeping this machine on Ollama is detect_gpu()
    # staying False on Apple Silicon. If a future edit "helpfully" taught
    # detect_gpu() about Apple Silicon, this assertion is what would catch it.
    assert B.resolve_backend()["backend"] == "ollama"


def test_detect_gpu_contract_is_unchanged_and_apple_silicon_does_not_satisfy_it(monkeypatch):
    """detect_gpu() answers "can vLLM run here?" and must keep answering exactly
    that. Pinned because 8+ vLLM-gating call sites read it."""

    class _Done:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 4070, 12282\n"

    monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: _Done())
    r = B.detect_gpu()
    assert r == {"available": True, "name": "NVIDIA GeForce RTX 4070", "vram_mb": 12282}

    # On a machine with no nvidia-smi, detect_gpu is False REGARDLESS of the OS --
    # Apple Silicon must not leak into this predicate.
    monkeypatch.setattr(B.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(B.platform, "machine", lambda: "arm64")

    def _missing(*a, **k):
        raise FileNotFoundError("no nvidia-smi")

    monkeypatch.setattr(B.subprocess, "run", _missing)
    assert B.detect_gpu()["available"] is False


# --------------------------------------------------------------------------- #
#  The policy.
# --------------------------------------------------------------------------- #
def test_dedicated_nvidia_gpu_is_practical(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NVIDIA, apple=_NOT_APPLE)
    cap = B.inference_capability()
    assert cap["practical"] is True
    assert cap["kind"] == "nvidia"
    assert cap["vram_mb"] == 12282
    assert cap["overridden"] is False


def test_gpuless_linux_box_is_not_practical_and_says_why(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    cap = B.inference_capability()
    assert cap["practical"] is False
    assert cap["kind"] is None
    assert cap["overridden"] is False
    # The reason must carry BOTH probes' own words, so "nvidia-smi timed out"
    # never flattens into the bare claim "this machine has no GPU".
    assert "nvidia-smi not found or timed out" in cap["reason"]
    assert "not macOS" in cap["reason"]
    assert B.IMPRACTICAL_CONSEQUENCE in cap["reason"]


def test_a_gpuless_machine_with_plenty_of_ram_is_still_not_practical(monkeypatch):
    """The ruling is about the ABSENCE OF A DEDICATED GPU, not only about RAM.
    A 256 GB GPU-less workstation still lands here -- if this ever flips, the
    gate has quietly become a RAM check and stopped implementing the ruling."""
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    # NB: backend.py binds total_ram_gb at import, so the patch must target ITS
    # namespace -- patching src.llm.ollama would leave the bound name untouched
    # and this test would pass without ever simulating the big-RAM machine.
    monkeypatch.setattr(B, "total_ram_gb", lambda: 256.0)
    assert B.inference_capability()["practical"] is False


def test_amd_discrete_gpus_are_named_as_an_honest_gap(monkeypatch):
    """A Radeon owner falls into "not practical". That is a NON-DETECTION, not a
    measurement, and the refusal must say so + point at the override rather than
    implying their card was examined and judged."""
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    cap = B.inference_capability()
    assert "AMD" in cap["reason"]
    assert "override" in cap["reason"]
    assert "not probed" in cap["caveat"].lower()


# --------------------------------------------------------------------------- #
#  Apple Silicon RAM floor -- and the third, EPISTEMIC state.
# --------------------------------------------------------------------------- #
def test_apple_silicon_below_the_unified_ram_floor_is_not_practical(monkeypatch):
    _stub_hw(
        monkeypatch,
        gpu=_NO_GPU,
        apple={"available": True, "name": "Apple Silicon (arm64)", "unified_ram_gb": 8.0},
    )
    cap = B.inference_capability()
    assert cap["practical"] is False
    assert cap["kind"] == "apple-silicon"
    assert cap["unified_ram_gb"] == 8.0
    assert cap["min_unified_ram_gb"] == B.APPLE_SILICON_MIN_UNIFIED_RAM_GB
    assert "below" in cap["reason"]


def test_apple_silicon_with_unreadable_ram_refuses_as_UNMEASURED_not_as_too_small(monkeypatch):
    """The third state must stay EPISTEMIC, not permissive AND not a fabricated
    shortfall: we could not read the memory, so we cannot verify the floor.
    A pass granted on an absent measurement would be a fabricated capability;
    a reason claiming the RAM is "below the floor" would be a fabricated
    measurement. The refusal explains the ABSENCE and points at the override."""
    _stub_hw(
        monkeypatch,
        gpu=_NO_GPU,
        apple={"available": True, "name": "Apple Silicon (arm64)", "unified_ram_gb": None},
    )
    cap = B.inference_capability()
    assert cap["practical"] is False
    assert cap["unified_ram_gb"] is None          # an honest absence, never a 0
    assert "could not be read" in cap["reason"]
    assert "below" not in cap["reason"]           # never a shortfall we did not measure
    assert "override" in cap["reason"]


def test_apple_silicon_exactly_at_the_floor_is_practical(monkeypatch):
    """Boundary: the floor is inclusive, so a 16 GB Mac is not refused by an
    off-by-one."""
    _stub_hw(
        monkeypatch,
        gpu=_NO_GPU,
        apple={
            "available": True,
            "name": "Apple Silicon (arm64)",
            "unified_ram_gb": B.APPLE_SILICON_MIN_UNIFIED_RAM_GB,
        },
    )
    assert B.inference_capability()["practical"] is True


def test_a_non_arm64_mac_is_not_apple_silicon_and_the_reason_does_not_overclaim(monkeypatch):
    """Darwin alone is not the carve-out -- UNIFIED MEMORY is. The reason must
    distinguish this from "not a Mac", but must NOT assert "this is an Intel Mac":
    an x86_64 Python under Rosetta on an M-series Mac reads identically here, so
    the sentence may only report the architecture Python ACTUALLY reported."""
    monkeypatch.setattr(B.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(B.platform, "machine", lambda: "x86_64")
    apple = B.detect_apple_silicon()
    assert apple["available"] is False
    assert "x86_64" in apple["reason"]
    assert "Rosetta" in apple["reason"]        # the alternative explanation is offered
    assert "macOS" in apple["reason"]          # ... and it is still distinguished from "not a Mac"

    monkeypatch.setattr(B, "detect_gpu", lambda: _NO_GPU)
    assert B.inference_capability()["practical"] is False


def test_detect_apple_silicon_accepts_arm64_on_darwin_only(monkeypatch):
    monkeypatch.setattr(B.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(B.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(B, "total_ram_gb", lambda: 24.0)
    r = B.detect_apple_silicon()
    assert r["available"] is True and r["unified_ram_gb"] == 24.0

    # Same arm64 machine word, different OS: an arm64 Linux box is NOT the
    # unified-memory carve-out.
    monkeypatch.setattr(B.platform, "system", lambda: "Linux")
    assert B.detect_apple_silicon()["available"] is False


# --------------------------------------------------------------------------- #
#  Degrade honestly -- a failed probe is never a measurement.
# --------------------------------------------------------------------------- #
def test_a_crashing_gpu_probe_refuses_with_the_failure_NAMED_never_a_fake_no_gpu(monkeypatch):
    def _boom():
        raise RuntimeError("nvidia-smi exploded")

    monkeypatch.setattr(B, "detect_gpu", _boom)
    monkeypatch.setattr(B, "detect_apple_silicon", lambda: _NOT_APPLE)
    cap = B.inference_capability()
    assert cap["practical"] is False
    assert "GPU probe failed" in cap["reason"]
    assert "nvidia-smi exploded" in cap["reason"]


def test_a_timing_out_nvidia_smi_is_reported_as_a_timeout(monkeypatch):
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

    monkeypatch.setattr(B.subprocess, "run", _timeout)
    monkeypatch.setattr(B, "detect_apple_silicon", lambda: _NOT_APPLE)
    cap = B.inference_capability()
    assert cap["practical"] is False
    assert "timed out" in cap["reason"]


def test_a_crashing_platform_probe_degrades_instead_of_raising(monkeypatch):
    def _boom():
        raise OSError("platform unavailable")

    monkeypatch.setattr(B.platform, "system", _boom)
    r = B.detect_apple_silicon()
    assert r["available"] is False
    assert "platform probe failed" in r["reason"]

    monkeypatch.setattr(B, "detect_gpu", lambda: _NO_GPU)
    assert B.inference_capability()["practical"] is False  # never raises


def test_nvidia_with_unreadable_vram_still_passes_and_keeps_None(monkeypatch):
    """detect_gpu legitimately returns vram_mb=None when the parse fails. The GPU
    is still PRESENT, so the gate passes -- and the unknown VRAM stays None
    rather than becoming a 0 that would read as a measured zero."""
    _stub_hw(
        monkeypatch,
        gpu={"available": True, "name": "NVIDIA Tesla", "vram_mb": None},
        apple=_NOT_APPLE,
    )
    cap = B.inference_capability()
    assert cap["practical"] is True
    assert cap["vram_mb"] is None


# --------------------------------------------------------------------------- #
#  The override -- never a hard block, never a silent enable.
# --------------------------------------------------------------------------- #
def test_env_override_flips_practical_and_marks_it_overridden(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    assert B.inference_capability()["practical"] is False

    monkeypatch.setenv(B.ENV_ALLOW_IMPRACTICAL_HW, "1")
    cap = B.inference_capability()
    assert cap["practical"] is True
    assert cap["overridden"] is True
    assert cap["override_requested"] is True
    # The disclosure must SURVIVE the override -- an operator who forced it on is
    # still told what they forced.
    assert "override" in cap["reason"]
    assert B.IMPRACTICAL_CONSEQUENCE in cap["reason"]


def test_settings_toggle_also_overrides(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)

    class _S:
        llm_allow_impractical_hw = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _S())
    cap = B.inference_capability()
    assert cap["practical"] is True and cap["overridden"] is True


def test_an_explicit_argument_beats_both_settings_and_env(monkeypatch):
    """A caller that already loaded settings passes the value in; that must be
    authoritative, or the two sources could disagree per branch."""
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    monkeypatch.setenv(B.ENV_ALLOW_IMPRACTICAL_HW, "1")
    assert B.inference_capability(override=False)["practical"] is False
    assert B.inference_capability(override=True)["practical"] is True


def test_overridden_is_False_on_genuinely_capable_hardware(monkeypatch):
    """`overridden` means "practical is True BECAUSE of the override". On a real
    GPU it must stay False even with the override set, or the disclosure would
    tell an NVIDIA owner their hardware was rejected and forced through."""
    _stub_hw(monkeypatch, gpu=_NVIDIA, apple=_NOT_APPLE)
    monkeypatch.setenv(B.ENV_ALLOW_IMPRACTICAL_HW, "1")
    cap = B.inference_capability()
    assert cap["practical"] is True
    assert cap["overridden"] is False        # the hardware passed on its own
    assert cap["override_requested"] is True  # ... but the flag IS set, and we say so


def test_a_settings_read_that_blows_up_falls_through_to_the_env(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)

    def _boom():
        raise RuntimeError("settings store is corrupt")

    monkeypatch.setattr("src.config.app_settings.load_settings", _boom)
    assert B.inference_capability()["practical"] is False   # never a fabricated enable
    monkeypatch.setenv(B.ENV_ALLOW_IMPRACTICAL_HW, "1")
    assert B.inference_capability()["practical"] is True


def test_only_the_exact_env_value_1_enables(monkeypatch):
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    for bogus in ("", "0", "true", "yes", "no", "2"):
        monkeypatch.setenv(B.ENV_ALLOW_IMPRACTICAL_HW, bogus)
        assert B.inference_capability()["practical"] is False, bogus


# --------------------------------------------------------------------------- #
#  Payload shape + cost.
# --------------------------------------------------------------------------- #
_KEYS = {
    "practical", "kind", "name", "vram_mb", "unified_ram_gb", "reason",
    "method", "caveat", "overridden", "override_requested", "min_unified_ram_gb",
}


@pytest.mark.parametrize(
    "gpu,apple",
    [
        (_NVIDIA, _NOT_APPLE),
        (_NO_GPU, _APPLE),
        (_NO_GPU, {"available": True, "name": "AS", "unified_ram_gb": 8.0}),
        (_NO_GPU, {"available": True, "name": "AS", "unified_ram_gb": None}),
        (_NO_GPU, _NOT_APPLE),
    ],
)
def test_every_branch_returns_the_same_keys_and_no_score_field(monkeypatch, gpu, apple):
    """One builder, every branch -- a field must never be present in four returns
    and silently missing from the fifth (an absent field reads as an answer).
    Also walks the keys for the project's banned score/rating/grade substrings."""
    _stub_hw(monkeypatch, gpu=gpu, apple=apple)
    cap = B.inference_capability()
    assert set(cap) == _KEYS
    assert cap["reason"] and cap["method"] and cap["caveat"]
    for k in cap:
        low = k.lower()
        for banned in ("score", "ranking", "rating", "grade"):
            assert banned not in low, f"{k} looks like a score field"


def test_passing_a_precomputed_gpu_dict_runs_no_second_nvidia_smi_probe(monkeypatch):
    """resolve_backend()/the API layer hand their already-computed gpu dict in.
    If that stopped being honoured, every health poll would silently double its
    subprocess cost."""
    calls = []
    monkeypatch.setattr(B, "detect_gpu", lambda: calls.append(1) or _NO_GPU)
    monkeypatch.setattr(B, "detect_apple_silicon", lambda: _NOT_APPLE)

    B.inference_capability(gpu=_NVIDIA)
    assert calls == []                       # the passed-in dict was used as-is
    B.inference_capability()
    assert len(calls) == 1                   # ... and omitting it does probe


# --------------------------------------------------------------------------- #
#  WORDING. The rationale behind the ruling mentions heat damaging hardware, but
#  this project does not state claims it cannot substantiate -- modern CPUs
#  thermal-THROTTLE rather than damage themselves. Guard the whole module so a
#  future edit cannot reintroduce a damage claim in a reason string.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "gpu,apple,override",
    [
        (_NVIDIA, _NOT_APPLE, None),
        (_NO_GPU, _APPLE, None),
        (_NO_GPU, {"available": True, "name": "AS", "unified_ram_gb": 4.0}, None),
        (_NO_GPU, {"available": True, "name": "AS", "unified_ram_gb": 4.0}, True),
        (_NO_GPU, {"available": True, "name": "AS", "unified_ram_gb": None}, None),
        (_NO_GPU, _NOT_APPLE, None),
        (_NO_GPU, _NOT_APPLE, True),
    ],
)
def test_no_hardware_damage_claim_reaches_the_user(monkeypatch, gpu, apple, override):
    """BEHAVIOURAL, not a source grep: assert what the operator actually READS.

    A source-wide grep would also forbid the comments that EXPLAIN why the claim
    is absent, and would still miss a damage claim built inline in an f-string.
    Driving every branch and inspecting the emitted user-facing strings catches
    the inline case and leaves the rationale writable."""
    _stub_hw(monkeypatch, gpu=gpu, apple=apple)
    cap = B.inference_capability(override=override)
    user_text = " ".join(
        str(cap[k]) for k in ("reason", "method", "caveat")
    ).lower()
    for banned in ("damage", "destroy", "burn out", "fry ", "harm your", "ruin"):
        assert banned not in user_text, (
            f"unsubstantiated hardware claim {banned!r} reached the user: {cap['reason']}"
        )


def test_the_substantiable_consequence_is_the_one_actually_stated():
    """The verifiable half IS asserted -- the gate still explains itself, it just
    explains itself with a claim that survives challenge."""
    assert "thermal throttling" in B.IMPRACTICAL_CONSEQUENCE
    assert "impractically slow" in B.IMPRACTICAL_CONSEQUENCE
    assert "saturate every core" in B.IMPRACTICAL_CONSEQUENCE


# --------------------------------------------------------------------------- #
#  WIRING. The gate is only worth anything where it is actually consulted.
# --------------------------------------------------------------------------- #
def test_llm_health_carries_the_hardware_state_in_BOTH_branches(monkeypatch):
    """The pill needs a THIRD state. `available` and `no_backend` already
    distinguish "selected backend down" from "nothing reachable"; "this machine
    cannot practically run one" is a further, different situation -- and it must
    be present whether or not the model list call succeeds, or the pill would
    show it only on one of the two paths."""
    from src.api import llm as L
    from src.llm.ollama import LLMUnavailable

    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(B, "_ollama_available", lambda: True)

    class _Up:
        base_url = "http://127.0.0.1:11434"

        def list_installed(self):
            return ["granite4:micro"]

    class _Down(_Up):
        def list_installed(self):
            raise LLMUnavailable("connection refused")

    for client in (_Up(), _Down()):
        out = L.llm_health(client=client)
        assert out["hardware_practical"] is False, client
        assert "no dedicated GPU" in out["hardware_reason"], client
        assert out["hardware_overridden"] is False, client


def test_llm_health_reports_unknown_hardware_as_None_not_as_a_verdict(monkeypatch):
    """A crashed probe must not fabricate EITHER answer on the pill path."""
    from src.api import llm as L

    def _boom(**kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr("src.llm.backend.inference_capability", _boom)
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(B, "_ollama_available", lambda: True)

    class _Up:
        base_url = "http://127.0.0.1:11434"

        def list_installed(self):
            return []

    out = L.llm_health(client=_Up())
    assert out["hardware_practical"] is None
    assert out["hardware_reason"] is None


def test_ai_diagnostics_carries_hardware_under_its_own_key(monkeypatch):
    """Rides the all-diagnostics bundle. `practical` is its OWN key, so a crashed
    section (`section_ok: False`) can never be read as a measured "impractical" --
    the sentinel-collision lesson that renamed _safe's key off `available`."""
    from src.monitoring import ai_diagnostics as D

    _stub_hw(monkeypatch, gpu=_NVIDIA, apple=_NOT_APPLE)
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(B, "_ollama_available", lambda: False)

    report = D.ai_diagnostics_report()
    assert "hardware" in report
    hw = report["hardware"]
    assert hw["practical"] is True and hw["kind"] == "nvidia"
    assert "section_ok" not in hw          # a real measurement, not a degrade sentinel
    assert hw["method"] and hw["caveat"]


def test_ai_diagnostics_hardware_section_degrades_without_breaking_the_bundle(monkeypatch):
    from src.monitoring import ai_diagnostics as D

    def _boom(**kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr("src.llm.backend.inference_capability", _boom)
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(B, "_ollama_available", lambda: False)

    report = D.ai_diagnostics_report()
    assert report["hardware"]["section_ok"] is False   # ABSENCE of a measurement
    assert "practical" not in report["hardware"]       # ... never a fabricated verdict
    assert report["schema"] == D.SCHEMA                # the bundle still built


def test_the_background_langdetect_ridealong_is_gated_and_names_the_skip(monkeypatch):
    """The concrete "default to off": an unattended background sweep is exactly
    the hours-of-core-saturation the ruling targets. The skip is NAMED (the
    ride-along's honest-skip convention), never a silent no-op."""
    from src.api import ai as A

    class _S:
        ai_langdetect_auto = True
        llm_allow_impractical_hw = False

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _S())
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)

    def _never():
        raise AssertionError("the job must not even be probed on unsuitable hardware")

    monkeypatch.setattr(A._LANGDETECT_JOB, "start", _never)
    out = A.advance_langdetect_auto_start(session=None)
    assert out["enabled"] is True
    assert out["skipped"].startswith("hardware:")
    assert "no dedicated GPU" in out["skipped"]


def test_the_ridealong_runs_again_once_the_operator_overrides(monkeypatch):
    """Proves the gate is a DEFAULT, not a block: the same unsuitable machine
    proceeds past the hardware check when the operator says so."""
    from src.api import ai as A

    class _S:
        ai_langdetect_auto = True
        llm_allow_impractical_hw = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _S())
    _stub_hw(monkeypatch, gpu=_NO_GPU, apple=_NOT_APPLE)
    monkeypatch.setattr(
        A._LANGDETECT_JOB, "status", lambda: {"state": "idle"}
    )
    monkeypatch.setattr(A, "_langdetect_candidate_count", lambda s: 0)

    out = A.advance_langdetect_auto_start(session=None)
    # It got PAST the hardware gate -- it now stops for an ordinary reason.
    assert out.get("skipped") != "hardware"
    assert not str(out.get("skipped", "")).startswith("hardware:")


def test_the_setting_roundtrips_and_defaults_off(monkeypatch, tmp_path):
    from src.config import app_settings as S

    # The autouse fixture stubs load_settings; save_settings calls it internally,
    # so restore the REAL one here or this would exercise the stub, not the store.
    monkeypatch.setattr(S, "load_settings", _REAL_LOAD_SETTINGS)
    monkeypatch.setattr(S, "_settings_path", lambda: tmp_path / "app_settings.json")
    monkeypatch.setattr(S, "_use_kv", lambda: False)
    assert S.load_settings().llm_allow_impractical_hw is False   # default OFF
    S.save_settings({"llm_allow_impractical_hw": True})
    assert S.load_settings().llm_allow_impractical_hw is True
    S.save_settings({"llm_allow_impractical_hw": False})
    assert S.load_settings().llm_allow_impractical_hw is False
    with pytest.raises(S.AppSettingsError):
        S.save_settings({"llm_allow_impractical_hw": "yes"})


# --------------------------------------------------------------------------- #
#  Found by the pre-push adversarial pass (2026-07-30): a non-numeric RAM value
#  raised straight out of the floor comparison. That matters MORE than an
#  ordinary crash, because the langdetect ride-along swallows exceptions -- so a
#  raise there failed the gate OPEN, the single direction a default-off gate must
#  never fail.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bogus", ["32", "", "n/a", object(), [], {}])
def test_a_non_numeric_unified_ram_never_raises_and_never_fails_open(monkeypatch, bogus):
    _stub_hw(
        monkeypatch,
        gpu=_NO_GPU,
        apple={"available": True, "name": "AS", "unified_ram_gb": bogus},
    )
    cap = B.inference_capability()          # must not raise
    if isinstance(bogus, str) and bogus == "32":
        # Coercible: honour it as the measurement it plainly is (the house
        # response to TEXT-typed read-backs), so 32 GB is not thrown away.
        assert cap["practical"] is True and cap["unified_ram_gb"] == 32.0
    else:
        assert cap["practical"] is False
        assert cap["unified_ram_gb"] is None      # UNMEASURED, never a fabricated 0
        assert "could not be read" in cap["reason"]


def test_the_gate_fails_CLOSED_inside_the_ridealong_when_a_probe_explodes(monkeypatch):
    """The ride-along's `except Exception: pass` is deliberate (never break a
    scrape) -- so the gate must not depend on exceptions to refuse. Pinned as a
    property: a hostile probe payload still leaves the job unstarted."""
    from src.api import ai as A

    class _S:
        ai_langdetect_auto = True
        llm_allow_impractical_hw = False

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _S())
    _stub_hw(
        monkeypatch,
        gpu=_NO_GPU,
        apple={"available": True, "name": "AS", "unified_ram_gb": "not a number"},
    )

    def _never(*a, **k):
        raise AssertionError("the job must not start on unsuitable hardware")

    monkeypatch.setattr(A._LANGDETECT_JOB, "start", _never)
    out = A.advance_langdetect_auto_start(session=None)
    assert str(out.get("skipped", "")).startswith("hardware:")


# --------------------------------------------------------------------------- #
#  Source-level wiring guards. Mirrors the parity pattern in
#  tests/test_ai_langdetect_resilience.py: a setting is only real if the
#  dataclass, the PUT model and the consumer all agree.
# --------------------------------------------------------------------------- #
def test_the_override_setting_has_dataclass_and_PUT_parity_and_defaults_off():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    app_settings_src = (root / "config" / "app_settings.py").read_text(encoding="utf-8")
    settings_api_src = (root / "api" / "settings.py").read_text(encoding="utf-8")
    # DEFAULT OFF is the ruling -- an override that shipped on would be no gate.
    assert "llm_allow_impractical_hw: bool = False" in app_settings_src
    assert "llm_allow_impractical_hw: bool | None = None" in settings_api_src


def test_the_two_predicates_stay_separate_in_the_source():
    """A future edit must not fold the hardware policy into detect_gpu(). The
    behavioural pin is test_apple_silicon_is_practical_but_never_routes_to_vllm;
    this is the cheap structural echo of it, and names WHY in its failure."""
    import ast
    from pathlib import Path

    src = Path(B.__file__).read_text(encoding="utf-8")
    # ast, not a string split: the module CONSTANTS between the two functions
    # legitimately mention platform.system() (it is the documented method), and a
    # naive split swept them into "detect_gpu's body" and failed on the docs
    # rather than on the code.
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "detect_gpu"
    )
    gpu_body = ast.get_source_segment(src, fn) or ""
    assert "platform." not in gpu_body, (
        "detect_gpu() answers 'can vLLM run here?' (CUDA only). Teaching it about "
        "Apple Silicon would route Macs to a vLLM that ships no macOS wheel -- put "
        "OS/arch policy in inference_capability() instead."
    )
    assert "def detect_apple_silicon(" in src
    assert "def inference_capability(" in src


def test_the_gate_is_actually_consulted_where_it_matters():
    """A predicate nothing reads is decoration. Pins the three consumers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    for rel in (
        ("api", "llm.py"),           # /api/llm/backend + the pill's /health
        ("api", "ai.py"),            # the background langdetect ride-along
        ("monitoring", "ai_diagnostics.py"),  # the all-diagnostics bundle
    ):
        text = (root.joinpath(*rel)).read_text(encoding="utf-8")
        assert "inference_capability" in text, f"{'/'.join(rel)} never consults the gate"

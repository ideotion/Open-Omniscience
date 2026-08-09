"""A machine with a DRIVER but no CUDA TOOLKIT must still be able to start vLLM.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-09, and the cause of ten identical deaths the earlier rounds of
this chain never named. On an RTX 4070 laptop with a stock driver install, every start
got PAST weight loading and KV-cache allocation and then died with exit code 1::

    INFO [topk_topp_sampler.py:55] Using FlashInfer for top-p & top-k sampling.
    ...
    ERROR [core.py:1330] RuntimeError: Could not find nvcc and default
                         cuda_home='/usr/local/cuda' doesn't exist

vLLM 0.26 picks FlashInfer for top-k/top-p sampling when the package is importable, and
FlashInfer COMPILES that kernel on first use. That first use is ``warmup_kernels`` at
the very end of engine init -- so the model is already resident in VRAM when the
compiler is missed, which is exactly why the operator saw "the model loads in VRAM and
then unloads for unknown reasons".

Two independent things are pinned here:

  1. the FIX -- no toolkit means the server is launched with vLLM's native PyTorch
     sampler, which needs no compiler; and a machine that HAS a toolkit is left alone;
  2. the INSTRUMENT -- ``failure_excerpt`` must reach that ``RuntimeError``. It sits at
     byte 26,370 of a 45,782-byte log, outside the retained head AND the retained tail,
     so only the search can find it. The structural half (first non-wrapper terminal
     exception) is tested with the specific signature REMOVED, because a rule that only
     works when we already knew the answer is not a rule.
"""

from __future__ import annotations

import src.llm.vllm_lifecycle as V

# The shape of the real log, reduced to what each assertion needs: a child traceback
# whose terminal exception is the reason, then the parent's wrapper saying it is not.
_REAL_LOG = "\n".join(
    [
        "(APIServer pid=77061) INFO 08-09 13:22:00 [api_utils.py:273] non-default args: {...}",
        "(EngineCore pid=77605) INFO 08-09 13:22:45 [cuda.py:482] Using FLASH_ATTN attention backend",
        "(EngineCore pid=77605) INFO 08-09 13:23:10 [topk_topp_sampler.py:55] Using FlashInfer for top-p & top-k sampling.",
        *[f"(EngineCore pid=77605) ERROR [core.py:1330]   File \"f{i}.py\", line {i}" for i in range(60)],
        "(EngineCore pid=77605) RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist",
        "(APIServer pid=77061) Traceback (most recent call last):",
        *[f"(APIServer pid=77061)   File \"g{i}.py\", line {i}" for i in range(60)],
        "(APIServer pid=77061) RuntimeError: Engine core initialization failed. See root cause above.",
    ]
)


def _no_toolkit(monkeypatch):
    monkeypatch.setattr(V.shutil, "which", lambda name: None)
    monkeypatch.delenv("CUDA_HOME", raising=False)
    monkeypatch.delenv("CUDA_PATH", raising=False)
    monkeypatch.setattr(V.Path, "is_file", lambda self: False)


# --------------------------------------------------------------------------- #
#  the fix: a driver is enough to RUN a model
# --------------------------------------------------------------------------- #
def test_no_nvcc_means_no_jit_sampler(monkeypatch):
    """THE FIX. Without a compiler the JIT sampler cannot work, so it is not used."""
    _no_toolkit(monkeypatch)
    monkeypatch.delenv("VLLM_USE_FLASHINFER_SAMPLER", raising=False)
    assert V.cuda_toolkit_present() is False
    assert V._server_env()["VLLM_USE_FLASHINFER_SAMPLER"] == "0"


def test_a_machine_with_a_toolkit_is_left_alone(monkeypatch):
    """The negative-space twin. Disabling it everywhere would cost speed on every
    machine that can compile — the condition is a real fact, not a blanket."""
    monkeypatch.setattr(V.shutil, "which", lambda name: "/usr/local/cuda/bin/nvcc")
    monkeypatch.delenv("VLLM_USE_FLASHINFER_SAMPLER", raising=False)
    assert V.cuda_toolkit_present() is True
    assert "VLLM_USE_FLASHINFER_SAMPLER" not in V._server_env()


def test_an_operator_setting_wins(monkeypatch):
    """An operator who has said what they want is not second-guessed — as everywhere
    else in this module."""
    _no_toolkit(monkeypatch)
    monkeypatch.setenv("VLLM_USE_FLASHINFER_SAMPLER", "1")
    assert V._server_env().get("VLLM_USE_FLASHINFER_SAMPLER") != "0"


def test_the_toolkit_probe_reads_CUDA_HOME(monkeypatch, tmp_path):
    """`nvcc` off PATH but a toolkit installed is a real configuration, and it is the
    one FlashInfer's own lookup honours."""
    nvcc = tmp_path / "bin" / "nvcc"
    nvcc.parent.mkdir(parents=True)
    nvcc.write_text("", encoding="utf-8")
    monkeypatch.setattr(V.shutil, "which", lambda name: None)
    monkeypatch.setenv("CUDA_HOME", str(tmp_path))
    assert V.cuda_toolkit_present() is True


# --------------------------------------------------------------------------- #
#  the instrument: the excerpt must reach the reason
# --------------------------------------------------------------------------- #
def _log(tmp_path, monkeypatch, text=_REAL_LOG):
    p = tmp_path / "server.log"
    p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(V, "server_log_path", lambda: p)
    return p


def test_the_excerpt_reaches_the_nvcc_error(tmp_path, monkeypatch):
    """At the 400-character budget the START JOURNAL passes — the tight case is the
    discriminating one; a generous limit would 'pass' on a log this shape anyway."""
    _log(tmp_path, monkeypatch)
    out = V.failure_excerpt(limit=400)
    assert out["signature"] == "cuda-toolkit-missing"
    assert "Could not find nvcc" in out["excerpt"]
    assert "no CUDA toolkit" in out.get("advice", "")


def test_the_structural_rule_finds_it_without_the_signature(tmp_path, monkeypatch):
    """THE HALF THAT MATTERS. The signature table is an enumeration, and the next cause
    is by definition one it does not contain. With the nvcc entry removed the terminal
    exception must still be found — otherwise the generic 'a traceback exists' match
    returns a window of stack frames and the operator learns nothing."""
    _log(tmp_path, monkeypatch)
    monkeypatch.setattr(
        V, "_FATAL_SIGNATURES", tuple(s for s in V._FATAL_SIGNATURES if "nvcc" not in s[1])
    )
    out = V.failure_excerpt(limit=400)
    assert out["signature"] == "exception"
    assert "Could not find nvcc" in out["excerpt"]


def test_the_wrapper_exception_is_never_the_answer(tmp_path, monkeypatch):
    """vLLM's parent re-raises its child's failure and says so in as many words. It is
    always present and always last, so 'the terminal exception' must mean the first
    NON-wrapper one, or the excerpt hands back the sentence whose entire content is
    that the answer is elsewhere."""
    _log(tmp_path, monkeypatch)
    monkeypatch.setattr(
        V, "_FATAL_SIGNATURES", tuple(s for s in V._FATAL_SIGNATURES if "nvcc" not in s[1])
    )
    out = V.failure_excerpt(limit=400)
    assert "See root cause above" not in out["excerpt"]


def test_a_log_with_no_exception_still_degrades_to_the_head(tmp_path, monkeypatch):
    """Negative space: no recognisable failure must not raise, and must not claim a
    signature it did not find."""
    _log(tmp_path, monkeypatch, text="just some output\nand more of it\n")
    out = V.failure_excerpt(limit=400)
    assert out["available"] is True
    assert out["signature"] is None
    assert "just some output" in out["excerpt"]

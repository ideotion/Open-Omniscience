"""A bench panel that can only show a disabled button is not drawn.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD REPORT 2026-08-09, verbatim: "downloading other models (for benchmark) doesn't
seem to work, can you check it out?"

Reproduced against the real endpoint rather than inferred: on a GPU machine with vLLM
installed and Ollama absent, ``/api/llm/bench-roster`` answers ``prerequisite: "ollama"``
for the Ollama panel -- and BOTH panels were rendered, the Ollama one FIRST in the
document (``index.html``: ``ollama-bench-box`` sits above ``vllm-bench-box``). So the
operator met two panels with the same heading and the same tick-boxes, ticked models in
the first, and pressed a button that was disabled. Nothing happened, which is the report.

The decision is a NAMED PURE FUNCTION so both directions can be driven in node. The
negative-space twin is the load-bearing half: hiding too eagerly would leave a fresh
machine with no bench panel AND no "install it first" line -- the same defect pointing
the other way, and invisible in a diff.

BROWSER-UNVERIFIED (fork-3/Q6a): source guards, node execution, and a live endpoint
drive -- no click-through.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.js_source_helper import function_body, function_source, read_static

APP = read_static("app.js")
HTML = read_static("index.html")


# --------------------------------------------------------------------------- #
#  the endpoint publishes the fact the panel needs
# --------------------------------------------------------------------------- #
def _machine(*, vllm_installed: bool, ollama_installed: bool, gpu: bool) -> dict:
    """A ``resolve_backend`` payload, built the way the real one is shaped.

    Hand-written doubles of this payload have drifted before (a two-key stub passed for
    months while omitting every field a caller might read), so the fields that decide
    the answer are all present and named exactly as production names them."""
    return {
        "backend": "vllm" if vllm_installed else "ollama",
        "available": vllm_installed or ollama_installed,
        "vllm": {"installed": vllm_installed, "running": vllm_installed},
        "ollama": {"installed": ollama_installed, "running": ollama_installed},
        "gpu": {"present": gpu},
    }


def test_the_roster_says_which_backend_the_machine_itself_will_serve_with(monkeypatch):
    """Without this the panel can only guess, or parse ``chosen_because``, which is a
    human sentence and not an API."""
    import src.api.llm as L
    import src.llm.backend as B

    monkeypatch.setattr(
        B, "resolve_backend", lambda: _machine(vllm_installed=True, ollama_installed=False, gpu=True)
    )
    for asked in ("vllm", "ollama", None):
        r = L.bench_roster(asked)
        assert r["provisioning_backend"] == "vllm", (
            f"asked for {asked!r}: the machine's own answer must ride on every response"
        )


def test_the_reported_machine_makes_the_ollama_panel_dead(monkeypatch):
    """The exact reproduction: a GPU box with vLLM installed and Ollama absent."""
    import src.api.llm as L
    import src.llm.backend as B

    monkeypatch.setattr(
        B, "resolve_backend", lambda: _machine(vllm_installed=True, ollama_installed=False, gpu=True)
    )
    ollama = L.bench_roster("ollama")
    vllm = L.bench_roster("vllm")
    # This pair is what produced two identical headings, one of them inert.
    assert ollama["prerequisite"] == "ollama" and ollama["backend"] != ollama["provisioning_backend"]
    assert vllm["prerequisite"] is None


def test_the_ollama_panel_is_live_again_once_ollama_is_installed(monkeypatch):
    """Nothing is lost for an operator who genuinely runs both backends."""
    import src.api.llm as L
    import src.llm.backend as B

    monkeypatch.setattr(
        B, "resolve_backend", lambda: _machine(vllm_installed=True, ollama_installed=True, gpu=True)
    )
    assert L.bench_roster("ollama")["prerequisite"] is None


# --------------------------------------------------------------------------- #
#  the panel's own decision, run
# --------------------------------------------------------------------------- #
#: (case name, roster payload, should the panel be drawn)
_CASES = [
    # The report itself: a dead duplicate on a vLLM machine.
    ("ollama panel on a vLLM box", {"backend": "ollama", "provisioning_backend": "vllm",
                                    "prerequisite": "ollama"}, False),
    ("vllm panel on a vLLM box", {"backend": "vllm", "provisioning_backend": "vllm",
                                  "prerequisite": None}, True),
    # NEGATIVE-SPACE TWIN. A fresh machine has installed NOTHING, so the serving panel
    # carries a prerequisite too -- and it must still be drawn, because it is the one
    # place that says which backend to install. Hiding it would trade one fabricated
    # dead end for another.
    ("fresh machine, serving panel", {"backend": "vllm", "provisioning_backend": "vllm",
                                      "prerequisite": "vllm"}, True),
    ("fresh machine, other panel", {"backend": "ollama", "provisioning_backend": "vllm",
                                    "prerequisite": "vllm"}, False),
    # A real dual-backend operator keeps both.
    ("both installed, other panel", {"backend": "ollama", "provisioning_backend": "vllm",
                                     "prerequisite": None}, True),
    ("nothing at all", None, False),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_panel_decision_holds_in_both_directions(tmp_path):
    fn = function_source(APP, "_benchPanelApplies")
    harness = f"""
{fn}
const cases = {json.dumps([c[1] for c in _CASES])};
console.log(JSON.stringify(cases.map((r) => _benchPanelApplies(r))));
"""
    script = tmp_path / "bench_panel.js"
    script.write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip())
    for (name, _payload, want), actual in zip(_CASES, got, strict=True):
        assert actual is want, f"{name}: expected drawn={want}, got {actual}"


def test_the_loader_actually_consults_it_and_hides_the_host():
    """A pure function nothing calls is the dead-end shape this repo has shipped before."""
    body = function_body(APP, "loadBenchRoster")
    assert "_benchPanelApplies(r)" in body, "the loader must ask the question"
    assert 'host.style.display = "none"' in body, "and act on the answer"


def test_both_hosts_still_exist_so_a_revealed_panel_has_somewhere_to_land():
    for el in ("ollama-bench-box", "vllm-bench-box"):
        assert f'id="{el}"' in HTML
